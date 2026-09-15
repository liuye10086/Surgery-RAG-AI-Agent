"""Fixed JSON inference; training and disk access occur only during explicit build/load."""

import json
import math
from pathlib import Path

from app.schemas.numeric_model_bundle import (
    NumericModelBundle, TrainedNumericAlgorithm, TrainedNumericPrediction, json_sha256,
)
from app.schemas.numeric_prediction import NumericInput
from app.services.numeric_prediction import _canonical_input
from app.services.synthetic_prediction_cases import add_calendar_months


def _payload(value):
    return value.model_dump(mode='python') if hasattr(value, 'model_dump') else value


def _bundle(value):
    return NumericModelBundle.model_validate(_payload(value))


def _strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('numeric_model_duplicate_json_key')
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError('numeric_model_nonfinite_json')

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)


def load_numeric_model_bundle(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('numeric_model_invalid_file')
    return _bundle(_strict_json(path.read_bytes()))


def bundle_sha256(bundle):
    value = _bundle(bundle).model_dump(mode='json')
    value['models'].sort(key=lambda m: m['task_id'])
    return json_sha256(value)


def trained_numeric_algorithm(bundle):
    bundle = _bundle(bundle)
    return TrainedNumericAlgorithm(
        implementation_sha256=bundle.implementation_sha256,
        parameters_sha256=json_sha256([m.model_dump(mode='json') for m in sorted(bundle.models, key=lambda m: m.task_id)]),
        bundle_sha256=bundle_sha256(bundle),
    )


def predict_numeric_bundle(numeric, bundle):
    bundle = _bundle(bundle)
    value = _canonical_input(numeric)
    parsed = NumericInput.model_validate(value)
    by_task = {m.task_id: m for m in bundle.models}
    predictions, baselines = [], []
    for packet in parsed.packets:
        model = by_task[packet.task_id]
        anchor = next((r for r in packet.input_observations if r.observation_id == packet.anchor_observation_id), None)
        baseline = anchor.value if packet.input_status == 'available' else None
        predicted = None
        if baseline is not None:
            predicted = (baseline - model.mean[0]) / model.scale[0] * model.coef[0] + model.intercept
            if not math.isfinite(predicted) or predicted < 0 or model.indicator == 'mmse' and predicted > 30:
                raise ValueError('numeric_model_prediction_out_of_bounds')
        common = dict(task_id=packet.task_id, indicator=model.indicator, unit=model.unit,
                      horizon_months=packet.horizon_months,
                      target_date=add_calendar_months(parsed.anchor_date, packet.horizon_months),
                      status=packet.input_status, reason=packet.input_reason)
        predictions.append({**common, 'value': predicted})
        baselines.append({**common, 'value': baseline})
    return TrainedNumericPrediction(
        disease_code=parsed.disease_code, subject_id=parsed.subject_id,
        dependency_group_id=parsed.dependency_group_id, anchor_date=parsed.anchor_date,
        source=parsed.source, input_sha256=json_sha256(value), algorithm=trained_numeric_algorithm(bundle),
        predictions=predictions, baseline_predictions=baselines,
    )


def validate_trained_numeric_prediction(result, numeric, bundle):
    result = TrainedNumericPrediction.model_validate(_payload(result))
    expected = predict_numeric_bundle(numeric, bundle)
    normalize = lambda item: item.model_copy(update={
        'predictions': sorted(item.predictions, key=lambda p: p.horizon_months),
        'baseline_predictions': sorted(item.baseline_predictions, key=lambda p: p.horizon_months),
    })
    if normalize(result) != normalize(expected):
        raise ValueError('numeric_trained_prediction_mismatch')
    return result


def _fit_bundle(data, source, implementation_sha256):
    # Keep optional numerical runtimes out of load and inference.
    from app.schemas.numeric_model_bundle import NumericRidgeTask, TASKS
    from app.services.prediction_candidate_training import fit_candidate_models, predict_candidate_models
    from app.services.prediction_candidate_evaluation import evaluate_candidates

    fitted = fit_candidate_models(data['features'], data['samples'])
    predictions = predict_candidate_models(data['features'], fitted['models'], fitted['estimators'])
    scored = evaluate_candidates(data['samples'], predictions, data['predictions'])
    evaluation = scored['evaluation']
    evaluation['fit_failures'] = [
        {key: model[key] for key in ('task_id', 'model_id', 'reason')}
        for model in fitted['models'] if model['status'] != 'fitted'
    ]
    complete = not evaluation['fit_failures'] and all(c.get('complete_output', False) for c in evaluation['comparisons'])
    evaluation['engineering_status'] = 'passed' if complete else 'incomplete'
    diagnostics = dict(features=data['features'], samples=data['samples'], models=fitted['models'],
                       predictions=predictions, baseline_predictions=data['predictions'], **scored)
    selected = [m for m in fitted['models'] if m['model_id'] == 'ridge:main_anchor']
    if len(selected) != 4 or {m['task_id'] for m in selected} != set(TASKS) or any(m['status'] != 'fitted' for m in selected):
        return None, diagnostics
    models = []
    for model in selected:
        task = model['task_id']
        disease, indicator, horizon = task.split('.')
        parameters = {k: model[k] for k in NumericRidgeTask.model_fields
                      if k not in ('indicator', 'unit', 'horizon_months', 'parameters_sha256')}
        parameters.update(indicator=indicator, unit='分' if disease == 'ad' else 'U/L', horizon_months=int(horizon[:-1]))
        parameters['parameters_sha256'] = json_sha256(parameters)
        models.append(parameters)
    challenge = [s for s in data['samples'] if s['pool'] == 'challenge_pool']
    bundle = NumericModelBundle(
        implementation_sha256=implementation_sha256, models=models, source=source,
        challenge_subject_ids=sorted({s['subject_id'] for s in challenge}),
        challenge_dependency_groups=sorted({s['dependency_group_id'] for s in challenge}),
        evaluation=evaluation, evaluation_sha256=json_sha256(evaluation),
    )
    return bundle, diagnostics


def _record(raw):
    import hashlib
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def _implementation_files():
    root = Path(__file__).resolve().parents[3]
    files = (
        'backend/app/schemas/numeric_model_bundle.py', 'backend/app/services/numeric_model_bundle.py',
        'backend/app/schemas/numeric_prediction.py', 'backend/app/services/numeric_prediction.py',
        'backend/app/schemas/synthetic_numeric_prediction.py', 'backend/app/schemas/synthetic_prediction_cases.py',
        'backend/app/services/synthetic_prediction_cases.py', 'backend/app/services/prediction_candidate_training.py',
        'backend/app/services/prediction_candidate_evaluation.py', 'backend/app/services/prediction_calculation.py',
        'backend/app/services/prediction_calculation_metrics.py', 'scripts/build_numeric_model_bundle.py',
    )
    return {name: _record((root / name).read_bytes())['sha256'] for name in files}


def verify_numeric_bundle_runtime(bundle):
    """Admission/worker gate only; historical validation must not call this disk check."""
    import inspect
    import sys
    from types import CodeType

    bundle = _bundle(bundle)
    hashes = _implementation_files()
    if json_sha256(hashes) != bundle.implementation_sha256:
        raise ValueError('numeric_model_implementation_changed')
    root = Path(__file__).resolve().parents[3]
    for name in hashes:
        if not name.startswith('backend/'):
            continue
        module_name = name.removeprefix('backend/').removesuffix('.py').replace('/', '.')
        module = sys.modules.get(module_name)
        if module is None:
            # Training modules are deliberately not imported by worker inference.
            continue
        compiled = compile((root / name).read_bytes(), module.__file__, 'exec', dont_inherit=True)
        pending = [compiled]
        while pending:
            code = pending.pop()
            pending.extend(c for c in code.co_consts if isinstance(c, CodeType))
            parts = code.co_qualname.split('.')
            if any(part.startswith('<') for part in parts) or len(parts) > 2:
                continue
            value = module
            for part in parts:
                value = getattr(value, part, None)
            if inspect.isclass(value):
                continue
            function = value.__func__ if inspect.ismethod(value) else value
            if not inspect.isfunction(function) or function.__code__ != code:
                raise ValueError('numeric_model_loaded_code_mismatch')
    if hashes != _implementation_files():
        raise ValueError('numeric_model_implementation_changed')


def _export_snapshot(directory):
    raw = (directory / 'manifest.json').read_bytes()
    manifest = _strict_json(raw)
    records = {'manifest.json': _record(raw)}
    for name, expected in manifest['files'].items():
        if Path(name).name != name or (directory / name).is_symlink():
            raise ValueError('source_changed')
        record = _record((directory / name).read_bytes())
        if record != expected:
            raise ValueError('source_changed')
        records[name] = record
    return records


def _summary(bundle, diagnostics):
    lines = ['# 固定四任务数值模型包', '',
             '固定接入候选为 ridge:main_anchor；保留完整 Ridge、Random Forest 及 D03 评价。',
             '仅使用开发池拟合；挑战池评价不参与拟合或选优。所有资料是合成工程数据，临床性能不可判定。',
             '此包用于工程链路，不代表优于 last_value，也没有发布业务模型。', '',
             '| 任务 | 配对分母 | MAE | last_value MAE | MAE 改善 |', '| --- | --- | --- | --- | --- |']
    for comparison in diagnostics['evaluation']['comparisons']:
        if comparison['model_id'] != 'ridge:main_anchor' or comparison['pool'] != 'challenge_pool':
            continue
        counts, stats = comparison['counts'], comparison['statistics']
        display = lambda value: '不可估计' if value is None else f'{value:.6f}'
        lines.append(f"| {comparison['task_id']} | {counts['N_pair_valid']}/{counts['N_label_valid']} | "
                     f"{display(stats['mae'])} | {display(stats['last_value_mae'])} | {display(stats['mae_gain_vs_last'])} |")
    lines += ['', '全部输出失败、弃权、目标缺失与分母保留在 evaluation.json；具体记录和重采样方案与模型参数一并保存。',
              '推理仅读取 bundle.json 的严格数值参数，不加载 pickle/joblib、不训练、不查询标签。',
              '输入超时点、单位不符及预测超物理范围会明确拒绝，不截断或填值。',
              '' if bundle is not None else '构建失败：四项必需模型未全部拟合成功；没有生成可用 bundle.json。', '']
    return '\n'.join(lines)


def build_numeric_model_bundle(source_dir, calculation_dir, output_dir):
    """Explicitly train/evaluate trusted exports and write a fresh immutable artifact directory."""
    import os
    import shutil
    import sys
    import tempfile
    from datetime import datetime, timezone

    source_dir, calculation_dir = Path(source_dir).resolve(), Path(calculation_dir).resolve()
    destination = Path(output_dir).absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('output_exists')
    if any(destination.resolve().is_relative_to(p) for p in (source_dir, calculation_dir)):
        raise ValueError('output_inside_source')
    # This reader verifies source export integrity and recalculates the frozen calculation
    # export before exposing input features, labels, and the baseline comparison rows.
    from app.services.prediction_candidate_export import _sources
    import numpy as np
    import sklearn

    data, source = _sources(source_dir, calculation_dir)
    snapshots = [_export_snapshot(path) for path in (source_dir, calculation_dir)]
    code = _implementation_files()
    bundle, diagnostics = _fit_bundle(data, source, json_sha256(code))
    if code != _implementation_files() or snapshots != [_export_snapshot(path) for path in (source_dir, calculation_dir)]:
        raise ValueError('numeric_model_build_sources_changed')

    def encode(value):
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')

    payloads = {f'{name}.json': encode(diagnostics[name]) for name in ('models', 'evaluation', 'bootstrap_plans')}
    payloads.update({f'{name}.jsonl': b''.join(encode(row) for row in diagnostics[name])
                     for name in ('features', 'samples', 'predictions', 'baseline_predictions', 'paired_rows')})
    payloads['summary.md'] = _summary(bundle, diagnostics).encode('utf-8')
    if bundle is not None:
        payloads['bundle.json'] = encode(bundle.model_dump(mode='json'))
    records = {name: _record(raw) for name, raw in payloads.items()}
    status = 'passed' if bundle is not None else 'failed'
    manifest = dict(schema_version='numeric_model_bundle_export.v1', status=status,
                    model_id='ridge:main_anchor', source=source, source_snapshots=snapshots,
                    code_sha256=code, runtime={'python': sys.version.split()[0], 'numpy': np.__version__, 'sklearn': sklearn.__version__},
                    files=records, data_content_sha256=json_sha256(records),
                    bundle_sha256=bundle_sha256(bundle) if bundle is not None else None,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    source_kind='synthetic', is_synthetic=True, clinical_validity_claim=False, production_enabled=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.numeric-model-bundle-', dir=destination.parent))
    try:
        for name, raw in payloads.items():
            (temporary / name).write_bytes(raw)
        (temporary / 'manifest.json').write_bytes(encode(manifest))
        if any(_record((temporary / name).read_bytes()) != record for name, record in records.items()):
            raise ValueError('numeric_model_output_mismatch')
        if bundle is not None and load_numeric_model_bundle(temporary / 'bundle.json') != bundle:
            raise ValueError('numeric_model_roundtrip_mismatch')
        if destination.exists() or destination.is_symlink():
            raise FileExistsError('output_exists')
        os.rename(temporary, destination)
    finally:
        if temporary.exists():
            if (temporary.is_symlink() or temporary.resolve().parent != destination.parent.resolve()
                    or not temporary.name.startswith('.numeric-model-bundle-')):
                raise OSError('unsafe_cleanup_path')
            shutil.rmtree(temporary)
    return {'status': status, 'bundle_sha256': manifest['bundle_sha256'],
            'data_content_sha256': manifest['data_content_sha256'], 'clinical_status': 'not_assessable',
            'model_count': len(bundle.models) if bundle is not None else 0,
            'fit_failure_count': len(diagnostics['evaluation']['fit_failures'])}
