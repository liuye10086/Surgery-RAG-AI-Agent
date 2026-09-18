"""Explicit, single-model rebuild and read-only replay of frozen synthetic evidence."""

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile

from app.schemas.numeric_history_bundle import NumericHistoryBundle, NumericHistoryRfModel, RfParameters
from app.schemas.numeric_model_bundle import TASKS, json_sha256
from app.schemas.numeric_prediction import NumericInput, NumericInputPacket
from app.services.numeric_history_bundle import (
    history_bundle_sha256, history_implementation_sha256, load_numeric_history_bundle,
    predict_numeric_history_bundle, verify_numeric_history_runtime,
)
from app.services.numeric_history_features import project_numeric_history_features
from app.services.numeric_model_bundle import (
    bundle_sha256, load_numeric_model_bundle, predict_numeric_bundle, verify_numeric_bundle_runtime,
)
from app.services.prediction_history_features import project_history_features

ROOT = Path(__file__).resolve().parents[3]
HISTORY_DIR = ROOT / 'outputs/synthetic-prediction-history/2026-09-15-v1'
LEGACY_PATH = ROOT / 'outputs/numeric-acceptance/2026-09-15/model-v2/bundle.json'
OUTPUT_DIR = ROOT / 'outputs/numeric-history-integration/2026-09-16-v1'
MANIFEST_SHA = '59a01c52f762d902cbd2a2b6faada56acc80c8b25d27d9ce40b92e7429c0e918'
LEGACY_SHA = '32b8069f92dab3e104f3668c3639cdc6e5461f5bedf61a4f7590ce2cef478215'
DATA_SHA = '8dd120326c41885217e9bac419b38168ba0435ada661779bbfcc14055f33e682'
PROTOCOL_SHA = 'fa171097693d166e0210f592b0f5033e822b2fafb0e485c7cc711d9b9c50dd40'
RUN_ID = 'hist-fa171097693d166e'
SELECTION = dict(schema_version='numeric_history_selection.v1', seed=20260914,
                 task_id='ad.mmse.12m', model_id='random_forest:history_v1:value_history')
ROLES = ('training', 'internal_validation', 'challenge')
FEATURE_NAMES = ['anchor_value', 'prior_value', 'slope_per_day']
BUILD_FILES = ('backend/app/services/numeric_history_bundle_build.py', 'scripts/build_numeric_history_bundle.py')


class BuildError(ValueError):
    """Stable public failure code; never includes paths or source contents."""


def _require(condition, code):
    if not condition:
        raise BuildError(code)


def _safe_path(path):
    path = Path(path).absolute()
    for node in (path, *path.parents):
        _require(not node.is_symlink(), 'unsafe_path')
        try:
            attributes = getattr(node.stat(follow_symlinks=False), 'st_file_attributes', 0)
        except FileNotFoundError:
            continue
        _require(not attributes & 0x400, 'unsafe_path')
    return path


def _read_json(path):
    path = _safe_path(path)
    _require(path.is_file(), 'source_missing')
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    def invalid(value):
        raise BuildError('nonfinite_json')
    value = json.loads(path.read_bytes(), object_pairs_hook=pairs, parse_constant=invalid)
    def finite(item):
        if isinstance(item, float):
            _require(math.isfinite(item), 'nonfinite_json')
        elif isinstance(item, dict):
            for nested in item.values():
                finite(nested)
        elif isinstance(item, list):
            for nested in item:
                finite(nested)
    finite(value)
    return value


def _record(path):
    path = _safe_path(path)
    _require(path.is_file(), 'source_missing')
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
            size += len(chunk)
    return dict(sha256=digest.hexdigest(), bytes=size)


def _runtime():
    return {'python': sys.version.split()[0], **{name: version(distribution) for name, distribution in
            (('numpy', 'numpy'), ('scipy', 'scipy'), ('sklearn', 'scikit-learn'), ('joblib', 'joblib'))}}


def _build_identity():
    return {name: _record(ROOT / name)['sha256'] for name in BUILD_FILES}


def _validate_output(output_dir):
    path = _safe_path(output_dir)
    if path.exists():
        raise FileExistsError('output_exists')
    resolved = path.resolve()
    _require(resolved == OUTPUT_DIR.resolve(), 'output_outside_allowed_tree')
    for ancestor in path.parents:
        _require(not (ancestor / 'manifest.json').exists() and not (ancestor / 'protocol.json').exists(),
                 'output_inside_artifact')
    return path


def _source_snapshot(history_dir, legacy_path):
    history_dir, legacy_path = _safe_path(history_dir), _safe_path(legacy_path)
    _require(history_dir.is_dir() and legacy_path.is_file(), 'source_missing')
    _require(history_dir.resolve() == HISTORY_DIR.resolve() and legacy_path.resolve() == LEGACY_PATH.resolve(),
             'source_path_mismatch')
    manifest_record = _record(history_dir / 'manifest.json')
    _require(manifest_record['sha256'] == MANIFEST_SHA, 'manifest_identity_mismatch')
    manifest = _read_json(history_dir / 'manifest.json')
    _require(manifest['status'] == 'passed' and manifest['run_id'] == RUN_ID
             and manifest['data_content_sha256'] == DATA_SHA and not manifest['is_test_fixture']
             and manifest['protocol_identity_sha256'] == PROTOCOL_SHA, 'source_identity_mismatch')
    records = {}
    for name, expected in manifest['files'].items():
        relative = PurePosixPath(name)
        _require(not relative.is_absolute() and '..' not in relative.parts and '\\' not in name
                 and ':' not in name and relative.as_posix() == name, 'unsafe_manifest_path')
        records[name] = _record(history_dir / name)
        _require(records[name] == expected, 'source_file_changed')
    actual = set()
    for base, dirs, files in os.walk(history_dir, followlinks=False):
        for name in dirs + files:
            _safe_path(Path(base) / name)
        actual.update((Path(base) / name).relative_to(history_dir).as_posix() for name in files)
    _require(actual == set(records) | {'manifest.json'}, 'source_file_set_changed')
    _require(json_sha256(records) == DATA_SHA, 'source_data_identity_mismatch')
    protocol = _read_json(history_dir / 'protocol.json')
    _require(json_sha256(protocol) == PROTOCOL_SHA, 'protocol_identity_mismatch')
    _require(_runtime() == protocol['runtime'], 'runtime_changed')
    for name, digest in protocol['code_sha256'].items():
        _require(_record(ROOT / name)['sha256'] == digest, 'source_code_changed')
    legacy = load_numeric_model_bundle(legacy_path)
    _require(bundle_sha256(legacy) == LEGACY_SHA, 'legacy_identity_mismatch')
    verify_numeric_bundle_runtime(legacy)
    return dict(manifest=manifest_record, files=records, legacy=_record(legacy_path),
                protocol_identity_sha256=PROTOCOL_SHA, runtime=_runtime(), build_source_sha256=_build_identity()), legacy


def _unique(rows, key):
    index = {row[key]: row for row in rows}
    _require(len(index) == len(rows), 'duplicate_identity')
    return index


def _validate_partitions(features, samples):
    feature_index, sample_index = _unique(features, 'sample_id'), _unique(samples, 'sample_id')
    _require(feature_index.keys() == sample_index.keys(), 'sample_set_mismatch')
    groups, subjects, task_subjects = {}, {}, set()
    for sample_id, feature in feature_index.items():
        sample = sample_index[sample_id]
        role = feature['evaluation_role']
        _require(role in ROLES and feature['pool'] == ('challenge_pool' if role == 'challenge' else 'development_pool'),
                 'invalid_partition')
        group, subject = feature['dependency_group_id'], feature['subject_id']
        _require(group not in groups or groups[group] == role, 'dependency_crosses_partitions')
        _require(subject not in subjects or subjects[subject] == (group, role), 'subject_crosses_partitions')
        groups[group], subjects[subject] = role, (group, role)
        key = (feature['task_id'], subject)
        _require(key not in task_subjects, 'duplicate_analysis_patient')
        task_subjects.add(key)
        for key in ('subject_id', 'dependency_group_id', 'task_id', 'horizon_months', 'anchor_date', 'source', 'pool', 'evaluation_role'):
            _require(feature[key] == sample[key], 'sample_identity_mismatch')
    return feature_index, sample_index


def _load_sources(history_dir, legacy_path):
    snapshot, legacy = _source_snapshot(history_dir, legacy_path)
    seed = Path(history_dir) / 'seed-20260914'
    data = {key: _read_json(seed / f'{key}.json') for key in ('cohort', 'features', 'samples', 'models', 'predictions')}
    features, samples = _validate_partitions(data['features'], data['samples'])
    packets = _unique(data['cohort']['prediction_inputs'], 'sample_id')
    _require(packets.keys() == features.keys() and len(packets) == 4800, 'input_count_mismatch')
    _require(Counter((row['task_id'], row['evaluation_role']) for row in features.values()) ==
             Counter({(task, role): count for task in TASKS for role, count in zip(ROLES, (640, 160, 400))}),
             'role_count_mismatch')
    records = [row for row in data['models'] if row['task_id'] == SELECTION['task_id'] and row['model_id'] == SELECTION['model_id']]
    _require(len(records) == 1 and records[0]['status'] == 'fitted' and records[0]['reason'] is None,
             'selected_model_missing')
    record = records[0]
    _require(record['parameters'] == RfParameters().model_dump(mode='json')
             and record['feature_names'] == FEATURE_NAMES, 'selected_configuration_mismatch')
    comparisons = [dict(seed=20260914, **row) for role in ROLES
                   for row in _read_json(seed / role / 'evaluation.json')['comparisons']
                   if _selected_comparison(row)]
    aggregates = [row for row in _read_json(Path(history_dir) / 'aggregate.json') if _selected_comparison(row)]
    return dict(snapshot=snapshot, legacy=legacy, features=features, samples=samples, packets=packets,
                record=record, predictions=data['predictions'], comparisons=comparisons, aggregates=aggregates)


def _selected_comparison(row):
    return (row['task_id'] == SELECTION['task_id'] and row['candidate_model_id'] == SELECTION['model_id']
            and row['comparison_name'] in ('value_history_vs_last_value', 'value_history_vs_anchor_history'))


def _packet(raw):
    # The sealed offline source has no run/dataset binding on each packet. Add
    # the enclosing artifact's verified identity; retain its synthetic provenance.
    _require(raw['source']['source_kind'] == 'synthetic' and raw['source']['is_synthetic'] is True,
             'synthetic_source_required')
    source = dict(raw['source'], run_id=RUN_ID, dataset_id='synthetic-prediction-history',
                  dataset_version='2026-09-15-v1')
    return NumericInputPacket.model_validate({**raw, 'source': source})


def _projection(data):
    original = _unique(project_history_features(list(data['packets'].values())), 'sample_id')
    old_rows, new_rows, packets = [], [], {}
    keys = ('anchor_value', 'prior_value', 'slope_per_day', 'n_pre', 'span_pre_days')
    for sample_id in sorted(original):
        old, saved = original[sample_id], data['features'][sample_id]
        _require(all(saved[key] == value for key, value in old.items()), 'source_projection_mismatch')
        packet = _packet(data['packets'][sample_id])
        packets[sample_id] = packet
        result = project_numeric_history_features(packet)
        reason = packet.input_reason if old['history_reason'] == 'anchor_not_available' else old['history_reason']
        expected = dict(sample_id=sample_id, eligible=old['history_status'] in ('available', 'error'),
                        status=old['history_status'], reason=reason, **{key: old[key] for key in keys})
        actual = dict(sample_id=sample_id, **result.model_dump(mode='json'))
        _require(expected == actual, 'projection_replay_mismatch')
        old_rows.append(expected)
        new_rows.append(actual)
    return packets, dict(rows=len(new_rows), differences=0, original_sha256=json_sha256(old_rows),
                         projected_sha256=json_sha256(new_rows))


def _training(data):
    import numpy as np
    train = [data['samples'][key] for key in sorted(data['samples'])
             if data['samples'][key]['task_id'] == SELECTION['task_id']
             and data['samples'][key]['evaluation_role'] == 'training'
             and data['samples'][key]['anchor_status'] == 'eligible'
             and data['samples'][key]['label_status'] == 'valid'
             and data['features'][key]['history_status'] in ('available', 'error')]
    _require(all(data['features'][row['sample_id']]['history_status'] == 'available' for row in train),
             'history_training_calculation_error')
    identity = [{key: row[key] for key in ('sample_id', 'subject_id', 'dependency_group_id')} for row in train]
    x = [[data['features'][row['sample_id']][name] for name in FEATURE_NAMES] for row in train]
    y = [row['actual'] for row in train]
    _require(len({row['dependency_group_id'] for row in train}) >= 2, 'insufficient_training_support')
    _require(all(type(v) in (int, float) and math.isfinite(v) for row in x for v in row)
             and all(type(v) in (int, float) and math.isfinite(v) for v in y), 'nonfinite_training_data')
    matrix = np.asarray(x, dtype=float)
    mean, std = matrix.mean(axis=0), matrix.std(axis=0, ddof=0)
    scale = np.where(std == 0, 1., std)
    actual = dict(training_sample_ids=[row['sample_id'] for row in train],
                  training_subject_ids=[row['subject_id'] for row in train],
                  training_dependency_groups=sorted({row['dependency_group_id'] for row in train}),
                  training_identity_sha256=json_sha256(identity), training_target_sha256=json_sha256(y),
                  training_data_sha256=json_sha256(dict(identity=identity, feature_names=FEATURE_NAMES, X=x, y=y)),
                  mean=mean.tolist(), std=std.tolist(), scale=scale.tolist(),
                  constant_columns=[name for name, sigma in zip(FEATURE_NAMES, std) if sigma == 0])
    for key, value in actual.items():
        _require(data['record'][key] == value, 'training_identity_mismatch')
    return actual, (matrix - mean) / scale, np.asarray(y, dtype=float)


def _export_trees(estimator):
    trees = []
    for fitted in estimator.estimators_:
        tree, nodes = fitted.tree_, []
        for index in range(tree.node_count):
            if tree.children_left[index] == -1:
                nodes.append(dict(kind='leaf', value=float(tree.value[index, 0, 0])))
            else:
                nodes.append(dict(kind='branch', feature_index=int(tree.feature[index]),
                                  threshold=float(tree.threshold[index]), left=int(tree.children_left[index]),
                                  right=int(tree.children_right[index])))
        trees.append(dict(nodes=nodes))
    return trees


def _fit_selected(data):
    # This is the only fitting call in S2. Neither preflight nor verification calls it.
    from sklearn.ensemble import RandomForestRegressor
    training, x, y = _training(data)
    estimator = RandomForestRegressor(**data['record']['parameters'])
    estimator.fit(x, y)
    raw = {key: value for key, value in training.items() if key != 'constant_columns'}
    raw.update(task_id=SELECTION['task_id'], model_id=SELECTION['model_id'], feature_names=FEATURE_NAMES,
               parameters=data['record']['parameters'], trees=_export_trees(estimator), source_seed=20260914)
    raw['parameters_sha256'] = json_sha256(raw)
    return NumericHistoryRfModel.model_validate(raw)


def _assemble(data, model):
    challenge = [row for row in data['features'].values()
                 if row['task_id'] == SELECTION['task_id'] and row['evaluation_role'] == 'challenge']
    evidence = dict(schema_version='numeric_history_evidence.v1', source_kind='synthetic',
                    clinical_status='not_assessable', clinical_validity_claim=False, run_id=RUN_ID,
                    manifest_sha256=MANIFEST_SHA, data_content_sha256=DATA_SHA, protocol_identity_sha256=PROTOCOL_SHA,
                    selection=SELECTION, source_seed=20260914, model_id=SELECTION['model_id'],
                    training_identity_sha256=model.training_identity_sha256, parameters_sha256=model.parameters_sha256,
                    challenge_subject_ids=sorted(row['subject_id'] for row in challenge),
                    challenge_dependency_groups=sorted({row['dependency_group_id'] for row in challenge}),
                    comparisons=data['comparisons'], aggregates=data['aggregates'])
    return NumericHistoryBundle(implementation_sha256=history_implementation_sha256(data['legacy'].implementation_sha256),
        legacy_bundle=data['legacy'], legacy_bundle_sha256=bundle_sha256(data['legacy']), history_model=model,
        task_assignments=[dict(task_id=task, provider='history_rf' if task == SELECTION['task_id'] else 'legacy_ridge')
                          for task in TASKS], history_evidence=evidence)


def _compare_prediction(recorded, actual):
    expected = {**recorded, 'status': 'available' if recorded['status'] == 'valid' else recorded['status']}
    _require(all(expected[key] == actual.get(key) for key in
                 ('sample_id', 'task_id', 'model_id', 'status', 'reason', 'value')), 'prediction_replay_mismatch')


def _replay(data, bundle, packets, projection):
    selected = [row for row in data['predictions'] if row['task_id'] == SELECTION['task_id']
                and row['model_id'] == SELECTION['model_id']]
    recorded = _unique(selected, 'sample_id')
    _require(set(recorded) == {key for key, row in packets.items() if row.task_id == SELECTION['task_id']},
             'prediction_sample_set_mismatch')
    grouped = defaultdict(list)
    for packet in packets.values():
        grouped[packet.subject_id].append(packet)
    roles = {role: dict(rows=0, available=0, abstain=0, error=0, max_abs_difference=0., state_differences=0) for role in ROLES}
    legacy_rows = {task: [] for task in TASKS if task != SELECTION['task_id']}
    actual_rows = []
    for subject_id in sorted(grouped):
        pair = sorted(grouped[subject_id], key=lambda row: row.horizon_months)
        first = pair[0]
        numeric = NumericInput(disease_code='ad' if first.task_id.startswith('ad.') else 'fatty_liver',
            subject_id=subject_id, dependency_group_id=first.dependency_group_id, anchor_date=first.anchor_date,
            packets=pair, source={**first.source.model_dump(mode='json'), 'manifest_sha256': MANIFEST_SHA,
                                  'input_file_sha256': data['snapshot']['files']['seed-20260914/cohort.json']['sha256']})
        result = predict_numeric_history_bundle(numeric, bundle)
        old = predict_numeric_bundle(numeric, data['legacy'])
        old_by_task = {row.task_id: row for row in old.predictions}
        for packet, row in zip(pair, result.predictions):
            if row.task_id == SELECTION['task_id']:
                actual = dict(sample_id=packet.sample_id, task_id=row.task_id, model_id=row.algorithm.model_id,
                              status=row.status, reason=row.reason, value=row.value)
                _compare_prediction(recorded[packet.sample_id], actual)
                actual_rows.append(actual)
                counter = roles[data['features'][packet.sample_id]['evaluation_role']]
                counter['rows'] += 1
                counter[row.status] += 1
            else:
                expected = old_by_task[row.task_id].model_dump(mode='json')
                actual = row.model_dump(mode='json', exclude={'algorithm', 'raw_prediction'})
                expected['status'] = 'abstain' if expected['status'] == 'unavailable' else expected['status']
                _require(actual == expected, 'legacy_prediction_replay_mismatch')
                legacy_rows[row.task_id].append(dict(sample_id=packet.sample_id, **actual))
        for current, previous in zip(result.baseline_predictions, old.baseline_predictions):
            expected = previous.model_dump(mode='json')
            expected['status'] = 'abstain' if expected['status'] == 'unavailable' else expected['status']
            _require(current.model_dump(mode='json', exclude={'algorithm', 'raw_prediction'}) == expected,
                     'baseline_prediction_replay_mismatch')
    return dict(schema_version='numeric_history_replay.v1', status='passed', projection=projection, roles=roles,
                rf_predictions_sha256=json_sha256(actual_rows),
                legacy={task: dict(rows=len(rows), differences=0, predictions_sha256=json_sha256(rows),
                                  parameters_sha256=next(m.parameters_sha256 for m in data['legacy'].models if m.task_id == task))
                        for task, rows in legacy_rows.items()})


def preflight_numeric_history_bundle(history_dir: Path, legacy_bundle_path: Path, output_dir: Path) -> dict:
    _validate_output(output_dir)
    data = _load_sources(history_dir, legacy_bundle_path)
    _, projection = _projection(data)
    _training(data)
    _require(_source_snapshot(history_dir, legacy_bundle_path)[0] == data['snapshot'], 'source_changed_during_build')
    return dict(status='passed', mode='preflight', selection=SELECTION, projection=projection, fitted_models=0)


def _write(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        stream.write('\n')


def _validate_stage(stage, output_dir):
    stage, output_dir = _safe_path(stage), _safe_path(output_dir)
    _require(stage.resolve().parent == output_dir.resolve().parent
             and stage.name.startswith('.numeric-history-') and stage != output_dir,
             'unsafe_stage_path')
    return stage


def build_numeric_history_bundle(history_dir: Path, legacy_bundle_path: Path, output_dir: Path) -> dict:
    output_dir = _validate_output(output_dir)
    data = _load_sources(history_dir, legacy_bundle_path)
    packets, projection = _projection(data)
    bundle = _assemble(data, _fit_selected(data))
    verify_numeric_history_runtime(bundle)
    replay = _replay(data, bundle, packets, projection)
    _require(_source_snapshot(history_dir, legacy_bundle_path)[0] == data['snapshot'], 'source_changed_during_build')
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.numeric-history-', dir=output_dir.parent))
    try:
        _write(stage / 'bundle.json', bundle.model_dump(mode='json'))
        _write(stage / 'replay.json', replay)
        # Reload strict bytes before the complete manifest can become visible.
        _require(history_bundle_sha256(load_numeric_history_bundle(stage / 'bundle.json')) == history_bundle_sha256(bundle),
                 'export_roundtrip_mismatch')
        manifest = dict(schema_version='numeric_history_build.v1', status='passed', source_kind='synthetic',
            clinical_validity_claim=False, clinical_status='not_assessable', production_enabled=False,
            created_at=datetime.now(timezone.utc).isoformat(), selection=SELECTION, fitted_models=1,
            sources=data['snapshot'], legacy_bundle_sha256=bundle.legacy_bundle_sha256,
            bundle_sha256=history_bundle_sha256(bundle), implementation_sha256=bundle.implementation_sha256,
            training_identity_sha256=bundle.history_model.training_identity_sha256,
            training_data_sha256=bundle.history_model.training_data_sha256,
            training_target_sha256=bundle.history_model.training_target_sha256,
            parameters_sha256=bundle.history_model.parameters_sha256,
            files={name: _record(stage / name) for name in ('bundle.json', 'replay.json')})
        _require(_source_snapshot(history_dir, legacy_bundle_path)[0] == data['snapshot'], 'source_changed_during_build')
        _write(stage / 'manifest.json', manifest)
        _validate_output(output_dir)
        _validate_stage(stage, output_dir)
        stage.rename(output_dir)
        return dict(status='passed', mode='build', bundle_sha256=manifest['bundle_sha256'], fitted_models=1, replay=replay)
    finally:
        if stage.exists():
            _validate_stage(stage, output_dir)
            shutil.rmtree(stage)


def verify_numeric_history_bundle(output_dir: Path) -> dict:
    output_dir = _safe_path(output_dir)
    manifest = _read_json(output_dir / 'manifest.json')
    manifest_record = _record(output_dir / 'manifest.json')
    expected_keys = {'schema_version', 'status', 'source_kind', 'clinical_validity_claim', 'clinical_status',
        'production_enabled', 'created_at', 'selection', 'fitted_models', 'sources', 'legacy_bundle_sha256',
        'bundle_sha256', 'implementation_sha256', 'training_identity_sha256', 'training_data_sha256',
        'training_target_sha256', 'parameters_sha256', 'files'}
    _require(manifest.get('schema_version') == 'numeric_history_build.v1' and manifest.get('status') == 'passed'
             and manifest.get('selection') == SELECTION and type(manifest.get('fitted_models')) is int
             and manifest['fitted_models'] == 1 and set(manifest) == expected_keys
             and manifest.get('source_kind') == 'synthetic' and manifest.get('clinical_status') == 'not_assessable'
             and manifest.get('clinical_validity_claim') is False and manifest.get('production_enabled') is False,
             'invalid_build_manifest')
    try:
        _require(datetime.fromisoformat(manifest['created_at']).tzinfo is not None, 'invalid_build_manifest')
    except (TypeError, ValueError) as exc:
        raise BuildError('invalid_build_manifest') from exc
    _require(set(p.name for p in output_dir.iterdir()) == {'manifest.json', 'bundle.json', 'replay.json'}, 'artifact_file_set_changed')
    _require(manifest['files'] == {name: _record(output_dir / name) for name in ('bundle.json', 'replay.json')}, 'artifact_file_changed')
    data = _load_sources(HISTORY_DIR, LEGACY_PATH)
    _require(manifest['sources'] == data['snapshot'], 'source_snapshot_mismatch')
    bundle = load_numeric_history_bundle(output_dir / 'bundle.json')
    verify_numeric_history_runtime(bundle)
    training, _, _ = _training(data)
    for key, value in training.items():
        if key != 'constant_columns':
            _require(getattr(bundle.history_model, key) == value, 'training_identity_mismatch')
    expected_bundle = _assemble(data, bundle.history_model)
    _require(bundle == expected_bundle, 'bundle_source_mismatch')
    for key, value in dict(bundle_sha256=history_bundle_sha256(bundle), legacy_bundle_sha256=bundle.legacy_bundle_sha256,
        implementation_sha256=bundle.implementation_sha256, training_identity_sha256=bundle.history_model.training_identity_sha256,
        training_data_sha256=bundle.history_model.training_data_sha256, training_target_sha256=bundle.history_model.training_target_sha256,
        parameters_sha256=bundle.history_model.parameters_sha256).items():
        _require(manifest.get(key) == value, 'manifest_bundle_mismatch')
    packets, projection = _projection(data)
    replay = _replay(data, bundle, packets, projection)
    _require(replay == _read_json(output_dir / 'replay.json'), 'replay_receipt_mismatch')
    _require(_source_snapshot(HISTORY_DIR, LEGACY_PATH)[0] == data['snapshot'], 'source_changed_during_verify')
    _require(_record(output_dir / 'manifest.json') == manifest_record
             and manifest['files'] == {name: _record(output_dir / name) for name in ('bundle.json', 'replay.json')},
             'artifact_changed_during_verify')
    return dict(status='passed', mode='verify', bundle_sha256=history_bundle_sha256(bundle), fitted_models=0, replay=replay)
