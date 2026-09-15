"""Frozen synthetic learning curves; no clinical model publication or automatic retry."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'backend') not in sys.path:
    sys.path.insert(0, str(ROOT / 'backend'))

from app.schemas.synthetic_prediction_cases import GenerationConfig
from app.services.synthetic_prediction_cases import canonical_json, generate_cohort
from app.services.synthetic_prediction_quality import assess_cohort
from app.services.prediction_calculation import build_engineering_samples, project_calculation_inputs, predict_baselines
from app.services.prediction_candidate_training import fit_candidate_models, predict_candidate_models
from app.services.prediction_candidate_export import _runtime
from app.services.prediction_stability import build_partitions, evaluate_role, aggregate_runs


PROTOCOL = {
    'version': 'synthetic_prediction_stability.v1', 'seeds': [20260914, 20260915, 20260916],
    'patients_per_disease': 1200, 'challenge_per_disease': 400, 'validation_fraction': .2,
    'training_groups_per_disease': {'120': 64, '600': 320, '1200': 640},
    'split_order': 'sha256(stability.v1:{seed}:{disease}:{dependency_group_id}),group_id',
    'candidate_configuration': 'unchanged_prediction_candidate_training',
    'roles': ['training', 'internal_validation', 'challenge'],
    'seed_aggregation': 'equal_seed_mean_min_max_with_valid_count_no_confidence_interval',
    'automatic_retries': 0, 'failure_verification': 'inputs_checked_not_retried',
    'clinical_status': 'not_assessable', 'model_publication': False,
}
CODE_FILES = (
    'backend/app/schemas/synthetic_prediction_cases.py',
    'backend/app/services/synthetic_prediction_cases.py',
    'backend/app/services/synthetic_prediction_fixtures.py',
    'backend/app/services/synthetic_prediction_quality.py',
    'backend/app/services/prediction_calculation.py',
    'backend/app/services/prediction_calculation_metrics.py',
    'backend/app/services/prediction_candidate_training.py',
    'backend/app/services/prediction_candidate_evaluation.py',
    'backend/app/services/prediction_candidate_export.py',
    'backend/app/services/prediction_stability.py',
    'scripts/run_synthetic_prediction_stability.py',
    'docs/superpowers/specs/2026-09-14-synthetic-prediction-stability-design.md',
)


def _hash(value):
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def _envelope():
    return {'protocol': PROTOCOL, 'runtime': _runtime(),
            'code_sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in CODE_FILES}}


def _write(directory, name, value):
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(canonical_json(value) + '\n')


def _read(path):
    def invalid(value):
        raise ValueError('nonfinite_json')
    return json.loads(path.read_text(encoding='utf-8'), parse_constant=invalid)


def _file_records(directory):
    result = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError('symlink_artifact')
        if path.is_file() and path != directory / 'manifest.json':
            raw = path.read_bytes()
            result[path.relative_to(directory).as_posix()] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    return result


def _source(seed):
    config = GenerationConfig(seed=seed, patients_per_disease=PROTOCOL['patients_per_disease'],
                              challenge_per_disease=PROTOCOL['challenge_per_disease'])
    cohort = generate_cohort(config)
    quality = assess_cohort(cohort)
    if quality['status'] != 'passed':
        raise ValueError('source_quality_failed')
    features = project_calculation_inputs(cohort['prediction_inputs'])
    samples = build_engineering_samples(cohort['patients'], cohort['prediction_inputs'],
                                        cohort['followup_outcomes'], cohort['generation_audit'])
    partitions = build_partitions(samples, seed,
        train_group_sizes=tuple(PROTOCOL['training_groups_per_disease'].values()),
        validation_fraction=PROTOCOL['validation_fraction'])
    return {'cohort': cohort, 'quality': quality, 'features': features, 'samples': samples, 'partitions': partitions}


def _unit(source, budget, *, recorded_fit_errors=()):
    groups = source['partitions']
    selections = {'training': set(groups['training_groups'][str(budget)]),
                  'internal_validation': set(groups['validation_groups']), 'challenge': set(groups['challenge_groups'])}
    role_features = {r: [f for f in source['features'] if f['dependency_group_id'] in chosen]
                     for r, chosen in selections.items()}
    role_samples = {r: [s for s in source['samples'] if s['dependency_group_id'] in chosen]
                    for r, chosen in selections.items()}
    begin = perf_counter()
    fitted = fit_candidate_models(role_features['training'], role_samples['training'],
                                  recorded_fit_errors=recorded_fit_errors)
    trained = perf_counter()
    predictions = {r: predict_candidate_models(features, fitted['models'], fitted['estimators'])
                   for r, features in role_features.items()}
    predicted = perf_counter()
    baselines = {r: predict_baselines(features) for r, features in role_features.items()}
    scores = {r: evaluate_role(role_samples[r], predictions[r], baselines[r], r) for r in role_features}
    finished = perf_counter()
    return {'models': fitted['models'], 'predictions': predictions, 'baseline_predictions': baselines, 'scores': scores}, {
        'fit_seconds': trained - begin, 'prediction_seconds': predicted - trained,
        'evaluation_seconds': finished - predicted, 'total_seconds': finished - begin}


def _counts(units):
    return {'units': len(units), 'model_attempts': sum(len(u['models']) for u in units),
            'fitted_models': sum(m['status'] == 'fitted' for u in units for m in u['models']),
            'predictions': sum(len(p) for u in units for p in u['predictions'].values()),
            'baseline_predictions': sum(len(p) for u in units for p in u['baseline_predictions'].values()),
            'comparisons': sum(len(s['evaluation']['comparisons']) for u in units for s in u['scores'].values())}


def _status(units, aggregate):
    expected = len(PROTOCOL['seeds']) * len(PROTOCOL['training_groups_per_disease'])
    return ('passed' if len(units) == expected and aggregate and all(a['complete'] for a in aggregate)
            and all(m['status'] == 'fitted' for u in units for m in u['models']) else 'incomplete')


def _receipt(directory, envelope, units, aggregate, status, error=None):
    records = _file_records(directory)
    return {'run_id': 'stab-' + _hash(envelope)[:16], 'protocol_identity_sha256': _hash(envelope),
            'status': status, 'error': error, 'clinical_status': 'not_assessable', 'clinical_validity_claim': False,
            'counts': _counts(units), 'files': records, 'data_content_sha256': _hash(records),
            'fit_error_verification': ('inputs_checked_not_retried' if any(m['reason'] == 'model_fit_error'
                                      for u in units for m in u['models']) else 'not_applicable'),
            'created_at': datetime.now(timezone.utc).isoformat()}


def run_experiment(output_dir, progress=None):
    directory = Path(output_dir).absolute()
    for name in ('synthetic-prediction-cases', 'synthetic-prediction-calculation', 'synthetic-prediction-candidates'):
        if directory.resolve().is_relative_to(ROOT / 'outputs' / name):
            raise ValueError('output_inside_previous_artifacts')
    directory.mkdir(parents=True, exist_ok=False)
    envelope, units, runs, aggregate = _envelope(), [], [], []
    try:
        # Freeze exact code/runtime/protocol before generating or fitting any data.
        _write(directory, 'protocol.json', envelope)
        for seed in PROTOCOL['seeds']:
            source = _source(seed)
            for name, value in source.items():
                _write(directory, f'seed-{seed}/{name}.json', value)
            for scale, budget in PROTOCOL['training_groups_per_disease'].items():
                unit, timing = _unit(source, budget)
                for name, value in unit.items():
                    _write(directory, f'seed-{seed}/scale-{scale}/{name}.json', value)
                _write(directory, f'seed-{seed}/scale-{scale}/timings.json', timing)
                units.append(unit)
                runs.append({'seed': seed, 'scale': int(scale), 'roles': unit['scores']})
                if progress:
                    progress({'seed': seed, 'scale': int(scale), 'fitted_models': sum(m['status'] == 'fitted' for m in unit['models']),
                              'model_attempts': len(unit['models']), 'seconds': round(timing['total_seconds'], 2)})
        aggregate = aggregate_runs(runs)
        _write(directory, 'aggregate.json', aggregate)
        if _envelope() != envelope:
            raise ValueError('source_code_changed_during_run')
        manifest = _receipt(directory, envelope, units, aggregate, _status(units, aggregate))
        _write(directory, 'manifest.json', manifest)
        return {k: manifest[k] for k in ('status', 'run_id', 'data_content_sha256', 'counts', 'clinical_status')}
    except Exception:
        if not (directory / 'manifest.json').exists():
            _write(directory, 'manifest.json', _receipt(directory, envelope, units, aggregate,
                                                       'failed', 'experiment_runtime_error'))
        raise


def verify_experiment(output_dir, progress=None):
    directory = Path(output_dir)
    def rejected(reason):
        return {'status': 'failed', 'reason': reason}
    try:
        if directory.is_symlink():
            return rejected('symlink_artifact')
        manifest = _read(directory / 'manifest.json')
        actual = _file_records(directory)
        if manifest['files'] != actual or manifest['data_content_sha256'] != _hash(actual):
            return rejected('file_integrity_mismatch')
        envelope = _envelope()
        if (_read(directory / 'protocol.json') != envelope or manifest['protocol_identity_sha256'] != _hash(envelope)
                or manifest['run_id'] != 'stab-' + _hash(envelope)[:16] or manifest['status'] not in {'passed', 'incomplete'}):
            return rejected('protocol_or_status_mismatch')
        expected_names, units, runs = {'protocol.json', 'aggregate.json'}, [], []
        for seed in PROTOCOL['seeds']:
            source = _source(seed)
            for name, value in source.items():
                filename = f'seed-{seed}/{name}.json'
                expected_names.add(filename)
                if _read(directory / filename) != value:
                    return rejected('source_recalculation_mismatch')
            for scale, budget in PROTOCOL['training_groups_per_disease'].items():
                prefix = f'seed-{seed}/scale-{scale}'
                recorded = _read(directory / prefix / 'models.json')
                errors = [f"{m['task_id']}:{m['model_id']}" for m in recorded
                          if m['status'] == 'error' and m['reason'] == 'model_fit_error']
                unit, _ = _unit(source, budget, recorded_fit_errors=errors)
                for name, value in unit.items():
                    filename = f'{prefix}/{name}.json'
                    expected_names.add(filename)
                    if _read(directory / filename) != value:
                        return rejected('unit_recalculation_mismatch')
                timing_name = f'{prefix}/timings.json'
                expected_names.add(timing_name)
                timing = _read(directory / timing_name)
                if set(timing) != {'fit_seconds', 'prediction_seconds', 'evaluation_seconds', 'total_seconds'} or any(
                    not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v < 0 for v in timing.values()):
                    return rejected('invalid_timing')
                units.append(unit)
                runs.append({'seed': seed, 'scale': int(scale), 'roles': unit['scores']})
                if progress:
                    progress({'verified_seed': seed, 'scale': int(scale)})
        aggregate = aggregate_runs(runs)
        expected = _receipt(directory, envelope, units, aggregate, _status(units, aggregate))
        if (set(actual) != expected_names or _read(directory / 'aggregate.json') != aggregate
                or any(manifest[k] != expected[k] for k in expected if k != 'created_at')
                or _envelope() != envelope):
            return rejected('summary_recalculation_mismatch')
        return {'status': 'passed', 'engineering_status': manifest['status'], 'clinical_status': 'not_assessable',
                'run_id': manifest['run_id'], 'counts': manifest['counts'],
                'fit_error_verification': manifest['fit_error_verification'],
                'data_content_sha256': manifest['data_content_sha256']}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return rejected('unreadable_or_invalid_experiment')


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('invalid_arguments')


def _print(value):
    print(json.dumps(value, ensure_ascii=False, sort_keys=True), flush=True)


def main(argv=None):
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output-dir', type=Path)
    group.add_argument('--verify-dir', type=Path)
    try:
        args = parser.parse_args(argv)
    except ValueError:
        _print({'status': 'error', 'error': 'invalid_arguments'})
        return 2
    try:
        result = (verify_experiment(args.verify_dir, _print) if args.verify_dir else
                  run_experiment(args.output_dir, _print))
    except FileExistsError:
        _print({'status': 'error', 'error': 'output_exists'})
        return 2
    except ValueError:
        _print({'status': 'error', 'error': 'experiment_not_verified'})
        return 3
    except Exception:
        _print({'status': 'error', 'error': 'experiment_runtime_error'})
        return 4
    _print(result)
    return 0 if result['status'] == 'passed' and result.get('engineering_status', 'passed') == 'passed' else 3


if __name__ == '__main__':
    raise SystemExit(main())
