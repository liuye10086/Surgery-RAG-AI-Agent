"""Fresh synthetic candidate artifacts, verified by rebuilding trusted models."""

from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

import joblib
import numpy as np
import scipy
import sklearn

from app.services.synthetic_prediction_cases import canonical_json
from app.services.synthetic_prediction_case_export import content_hash, verify_synthetic_case_export
from app.services.prediction_calculation_export import verify_calculation_export
from app.services.prediction_candidate_training import fit_candidate_models, predict_candidate_models
from app.services.prediction_candidate_evaluation import evaluate_candidates


VERSION = 'synthetic_prediction_candidates.v1'
JSONL_FILES = ('features', 'samples', 'predictions', 'paired_rows')
JSON_FILES = ('models', 'evaluation', 'bootstrap_plans')
DATA_FILES = tuple(f'{name}.jsonl' for name in JSONL_FILES) + tuple(f'{name}.json' for name in JSON_FILES) + ('summary.md',)
SOURCE_FILES = ('backend/app/services/prediction_candidate_training.py',
                'backend/app/services/prediction_candidate_evaluation.py',
                'backend/app/services/prediction_candidate_export.py',
                'scripts/evaluate_synthetic_prediction_candidates.py')
CONFIG = {'candidate_families': ['ridge', 'random_forest'], 'training_pool': 'development_pool',
          'standardization': 'training_population_std_zero_scale_one', 'tuning': False,
          'bootstrap_iterations': 2000, 'bootstrap_seed': 20260910, 'confidence_level': .95,
          'bootstrap_rng': 'numpy.Generator(PCG64)', 'quantile_method': 'linear',
          'random_forest_seed': 20260914, 'model_serialization': 'joblib_compress3_protocol5', 'automatic_retries': 0,
          'failure_verification': 'rebuild_inputs_do_not_retry_fit_errors'}


def _record(raw):
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def _runtime():
    return {'python': sys.version.split()[0], 'numpy': np.__version__, 'scipy': scipy.__version__,
            'sklearn': sklearn.__version__, 'joblib': joblib.__version__}


def _code_hashes():
    root = Path(__file__).resolve().parents[3]
    return {name: _record((root / name).read_bytes())['sha256'] for name in SOURCE_FILES}


def _json(raw):
    def invalid_constant(value):
        raise ValueError('nonfinite_json')
    return json.loads(raw, parse_constant=invalid_constant)


def _sources(source_dir, calculation_dir):
    source = verify_synthetic_case_export(source_dir)
    calc = verify_calculation_export(calculation_dir)
    if (source.get('status') != 'passed' or source.get('integrity_status') != 'passed'
            or calc.get('status') != 'passed'):
        raise ValueError('source_not_verified')
    manifest = _json((calculation_dir / 'manifest.json').read_bytes())
    if (manifest['source_run_id'] != source['run_id']
            or manifest['source_data_content_sha256'] != source['data_content_sha256']
            or manifest['run_id'] != calc['run_id'] or manifest['data_content_sha256'] != calc['data_content_sha256']):
        raise ValueError('source_pair_mismatch')
    data = {}
    for key in ('features', 'samples', 'predictions'):
        path = calculation_dir / f'{key}.jsonl'
        raw = path.read_bytes()
        if path.is_symlink() or _record(raw) != manifest['files'][path.name]:
            raise ValueError('source_changed')
        data[key] = [_json(line) for line in raw.splitlines()]
    return data, {'cases': {k: source[k] for k in ('run_id', 'data_content_sha256')},
                  'calculation': {k: calc[k] for k in ('run_id', 'data_content_sha256')}}


def _calculate(source, *, recorded_fit_errors=()):
    fitted = fit_candidate_models(source['features'], source['samples'], recorded_fit_errors=recorded_fit_errors)
    predictions = predict_candidate_models(source['features'], fitted['models'], fitted['estimators'])
    scored = evaluate_candidates(source['samples'], predictions, source['predictions'])
    complete = all(m['status'] == 'fitted' for m in fitted['models']) and all(
        c['complete_output'] for c in scored['evaluation']['comparisons'])
    scored['evaluation']['engineering_status'] = 'passed' if complete else 'incomplete'
    scored['evaluation']['fit_failures'] = [{k: m[k] for k in ('task_id', 'model_id', 'reason')}
                                           for m in fitted['models'] if m['status'] != 'fitted']
    data = {'features': source['features'], 'samples': source['samples'], 'models': fitted['models'],
            'predictions': predictions, **scored}
    return data, fitted['estimators']


def _number(value):
    return '不可估计' if value is None else f'{value:.4f}'


def _summary(data):
    lines = ['# 合成候选模型与D03比较', '',
             '仅用于合成工程验证。开发池用于拟合，挑战池仅作工程描述；未获准临床评价或模型发布。', '',
             f"工程完整性：{data['evaluation']['engineering_status']}；临床性能：not_assessable。", '',
             '## 主分支挑战池', '',
             '| 任务 | 候选 | 合格／标签有效／配对 | MAE | RMSE | 偏差 | 相对保持当前值MAE改善 |',
             '| --- | --- | --- | --- | --- | --- | --- |']
    for c in data['evaluation']['comparisons']:
        if c['pool'] != 'challenge_pool' or c['branch'] != 'main_anchor':
            continue
        n, s = c['counts'], c['statistics']
        lines.append(f"| {c['task_id']} | {c['family']} | {n['N_branch_eligible']}/{n['N_label_valid']}/{n['N_pair_valid']} | "
                     + ' | '.join(_number(s[k]) for k in ('mae', 'rmse', 'bias', 'mae_gain_vs_last')) + ' |')
    lines += ['', '## D03流程增量挑战池', '',
              '两侧使用完全相同开发训练子集；增益=仅锚点模型MAE−加入次数／跨度模型MAE。正值仅表示该合成子集误差减少。', '',
              '| 任务 | 候选 | 合格／标签有效／配对 | 流程增益 | 95%工程区间 |', '| --- | --- | --- | --- | --- |']
    for c in data['evaluation']['comparisons']:
        if c['pool'] != 'challenge_pool' or c['comparison_kind'] != 'd03_flow':
            continue
        n, s, ci = c['counts'], c['statistics'], c['intervals']['flow_mae_gain']
        lines.append(f"| {c['task_id']} | {c['family']} | {n['N_branch_eligible']}/{n['N_label_valid']}/{n['N_pair_valid']} | "
                     f"{_number(s['flow_mae_gain'])} | {_number(ci['lower'])} ～ {_number(ci['upper'])} |")
    lines += ['', '完整预测、失败、资格与缺失分母、参考模型及抽样计划保存于同包JSON制品。',
              '区间条件于当前固定模型，不包含重新训练的不确定性；所有16个临床门槛仍未定，不生成胜出／发布标记。',
              '', '## 失败记录', '', canonical_json(data['evaluation']['fit_failures']), '',
              '## 下一步', '', '增加独立规模／种子稳定性实验；完成最小应用与隔离权限、持久任务、历史和PDF验收。',
              '真实版本仍需A2／A3事实与组样、A4完整评价契约、A5冻结，之后正式独立比较和获准接入发布。', '']
    return '\n'.join(lines)


def _payloads(data, estimators):
    payloads = {f'{name}.jsonl': ''.join(canonical_json(r)+'\n' for r in data[name]).encode('utf-8') for name in JSONL_FILES}
    payloads.update({f'{name}.json': (canonical_json(data[name])+'\n').encode('utf-8') for name in JSON_FILES})
    payloads['summary.md'] = _summary(data).encode('utf-8')
    model_files = {}
    for index, model in enumerate(data['models']):
        key = f"{model['task_id']}:{model['model_id']}"
        if model['status'] != 'fitted':
            continue
        name = f'models/model-{index:02d}.joblib'
        buffer = io.BytesIO()
        joblib.dump(estimators[key], buffer, compress=3, protocol=5)
        payloads[name], model_files[key] = buffer.getvalue(), name
    return payloads, model_files


def _counts(data):
    return {'features': len(data['features']), 'samples': len(data['samples']), 'predictions': len(data['predictions']),
            'paired_rows': len(data['paired_rows']), 'model_attempts': len(data['models']),
            'fitted_models': sum(m['status'] == 'fitted' for m in data['models']),
            'comparisons': len(data['evaluation']['comparisons']), 'bootstrap_plans': len(data['bootstrap_plans'])}


def _identity(sources, hashes):
    digest = content_hash({'version': VERSION, 'sources': sources, 'code_sha256': hashes, 'config': CONFIG, 'runtime': _runtime()})
    return 'cand-' + digest[:16], digest


def _fit_error_verification(models):
    return ('inputs_checked_not_retried' if any(m.get('reason') == 'model_fit_error' for m in models)
            else 'not_applicable')


def _trusted_roundtrip(directory, payloads, models, estimators, model_files, features, predictions):
    loaded = {}
    for key, name in model_files.items():
        raw = (directory / name).read_bytes()
        if raw != payloads[name]:
            raise ValueError('new_model_changed')
        # Only these exact bytes just created in this process are deserialized.
        loaded[key] = joblib.load(io.BytesIO(raw))
    if predict_candidate_models(features, models, loaded) != predictions:
        raise ValueError('model_roundtrip_mismatch')


def _remove_owned(directory, parent):
    if directory.is_symlink() or directory.resolve().parent != parent.resolve() or not directory.name.startswith('.prediction-candidates-'):
        raise OSError('unsafe_cleanup_path')
    shutil.rmtree(directory)


def evaluate_candidate_package(source_dir, calculation_dir, output_dir):
    source_dir, calculation_dir = Path(source_dir).resolve(), Path(calculation_dir).resolve()
    destination = Path(output_dir).absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('output_exists')
    if any(destination.resolve().is_relative_to(p) for p in (source_dir, calculation_dir)):
        raise ValueError('output_inside_source')
    source, identities = _sources(source_dir, calculation_dir)
    hashes = _code_hashes()
    data, estimators = _calculate(source)
    payloads, model_files = _payloads(data, estimators)
    run_id, identity_hash = _identity(identities, hashes)
    records = {name: _record(raw) for name, raw in payloads.items()}
    manifest = {'schema_version': VERSION, 'run_id': run_id, 'run_identity_sha256': identity_hash,
                'sources': identities, 'source_relative_path': os.path.relpath(source_dir, destination),
                'calculation_relative_path': os.path.relpath(calculation_dir, destination),
                'config': CONFIG, 'code_sha256': hashes, 'runtime': _runtime(), 'files': records,
                'model_files': model_files, 'data_content_sha256': content_hash(records), 'counts': _counts(data),
                'clinical_validity_claim': False, 'clinical_status': 'not_assessable',
                'engineering_status': data['evaluation']['engineering_status'], 'trusted_model_roundtrip': 'passed',
                'fit_error_verification': _fit_error_verification(data['models']),
                'created_at': datetime.now(timezone.utc).isoformat()}
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.prediction-candidates-', dir=destination.parent))
    try:
        for name, raw in payloads.items():
            path = temporary / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        _trusted_roundtrip(temporary, payloads, data['models'], estimators, model_files, data['features'], data['predictions'])
        (temporary / 'manifest.json').write_bytes((canonical_json(manifest)+'\n').encode('utf-8'))
        verified = verify_candidate_export(temporary)
        if verified['status'] != 'passed':
            raise ValueError('candidate_not_verified')
        if destination.exists() or destination.is_symlink():
            raise FileExistsError('output_exists')
        os.rename(temporary, destination)
        return {'status': manifest['engineering_status'], 'clinical_status': 'not_assessable', 'run_id': run_id,
                'data_content_sha256': manifest['data_content_sha256'], 'counts': manifest['counts']}
    finally:
        if temporary.exists():
            _remove_owned(temporary, destination.parent)


def verify_candidate_export(output_dir):
    """Refit successes; validate failed fit inputs without retrying or reproducing their cause."""
    directory = Path(output_dir)
    def reject(reason):
        return {'status': 'failed', 'reason': reason}
    try:
        if directory.is_symlink() or any(p.is_symlink() for p in directory.rglob('*')):
            return reject('symlink_artifact')
        manifest = _json((directory / 'manifest.json').read_bytes())
        hashes = _code_hashes()
        if (manifest['schema_version'] != VERSION or manifest['config'] != CONFIG
                or manifest['runtime'] != _runtime() or manifest['code_sha256'] != hashes):
            return reject('candidate_identity_mismatch')
        source, identities = _sources((directory / manifest['source_relative_path']).resolve(),
                                      (directory / manifest['calculation_relative_path']).resolve())
        if manifest['sources'] != identities or (manifest['run_id'], manifest['run_identity_sha256']) != _identity(identities, hashes):
            return reject('candidate_source_mismatch')
        models_raw = (directory / 'models.json').read_bytes()
        if _record(models_raw) != manifest['files']['models.json']:
            return reject('candidate_model_record_mismatch')
        stored_models = _json(models_raw)
        recorded_fit_errors = [f"{m['task_id']}:{m['model_id']}" for m in stored_models
                               if m['status'] == 'error' and m['reason'] == 'model_fit_error']
        # Rebuild identities, training data, parameters and scaling for every record.
        # An exception audit cannot independently establish that exception's cause.
        data, estimators = _calculate(source, recorded_fit_errors=recorded_fit_errors)
        payloads, model_files = _payloads(data, estimators)
        actual_names = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
        if actual_names != set(payloads) | {'manifest.json'} or manifest['model_files'] != model_files:
            return reject('candidate_file_set_mismatch')
        records = {name: _record(raw) for name, raw in payloads.items()}
        if (manifest['files'] != records or manifest['data_content_sha256'] != content_hash(records)
                or any((directory / name).read_bytes() != raw for name, raw in payloads.items())
                or manifest['counts'] != _counts(data) or manifest['clinical_validity_claim'] is not False
                or manifest['clinical_status'] != 'not_assessable'
                or manifest['engineering_status'] != data['evaluation']['engineering_status']
                or manifest['fit_error_verification'] != _fit_error_verification(data['models'])
                or manifest['trusted_model_roundtrip'] != 'passed'):
            return reject('candidate_recalculation_mismatch')
        return {'status': 'passed', 'engineering_status': manifest['engineering_status'], 'clinical_status': 'not_assessable',
                'fit_error_verification': manifest['fit_error_verification'],
                'run_id': manifest['run_id'], 'data_content_sha256': content_hash(records), 'counts': _counts(data)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return reject('unreadable_or_invalid_candidate')
