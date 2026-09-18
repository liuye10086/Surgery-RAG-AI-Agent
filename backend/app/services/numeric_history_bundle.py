"""Fixed JSON inference. Loading and runtime verification are explicit I/O gates."""

import hashlib
import inspect
import json
import math
from pathlib import Path
import struct
import sys
from types import CodeType

from app.schemas.numeric_history_bundle import NumericHistoryBundle, NumericHistoryRfModel, RfTree
from app.schemas.numeric_history_prediction import MixedNumericAlgorithm, NumericPredictionV3, NumericTaskAlgorithm
from app.schemas.numeric_model_bundle import json_sha256
from app.schemas.numeric_prediction import NumericInput
from app.services.numeric_history_features import project_numeric_history_features
from app.services.synthetic_prediction_cases import add_calendar_months

MAX_BUNDLE_BYTES = 8 * 1024 * 1024
SOURCE_FILES = (
    'backend/app/schemas/numeric_history_bundle.py',
    'backend/app/schemas/numeric_history_prediction.py',
    'backend/app/services/numeric_history_features.py',
    'backend/app/services/numeric_history_bundle.py',
    'backend/app/services/prediction_history_features.py',
)


def _payload(value):
    return value.model_dump(mode='python') if hasattr(value, 'model_dump') else value


def _bundle(value):
    return NumericHistoryBundle.model_validate(_payload(value))


def load_numeric_history_bundle(path: Path) -> NumericHistoryBundle:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('numeric_history_invalid_file')
    if path.stat().st_size > MAX_BUNDLE_BYTES:
        raise ValueError('numeric_history_file_too_large')
    with path.open('rb') as stream:
        raw = stream.read(MAX_BUNDLE_BYTES + 1)
    if len(raw) > MAX_BUNDLE_BYTES:
        raise ValueError('numeric_history_file_too_large')

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('numeric_history_duplicate_json_key')
            value[key] = item
        return value

    def invalid_constant(value):
        raise ValueError('numeric_history_nonfinite_json')

    return _bundle(json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant))


def history_bundle_sha256(bundle: NumericHistoryBundle) -> str:
    value = _bundle(bundle).model_dump(mode='json')
    value['task_assignments'].sort(key=lambda row: row['task_id'])
    value['legacy_bundle']['models'].sort(key=lambda row: row['task_id'])
    return json_sha256(value)


def _implementation_files():
    root = Path(__file__).resolve().parents[3]
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def history_implementation_sha256(legacy_implementation_sha256: str) -> str:
    """Build/runtime helper only; inference consumes the saved identity."""
    return json_sha256({'source_sha256': _implementation_files(),
                        'legacy_implementation_sha256': legacy_implementation_sha256})


def verify_numeric_history_runtime(bundle: NumericHistoryBundle) -> None:
    from app.services.numeric_model_bundle import verify_numeric_bundle_runtime
    from app.services import numeric_history_features, prediction_history_features, synthetic_prediction_cases
    from app.schemas import numeric_history_bundle, numeric_history_prediction, numeric_model_bundle, numeric_prediction

    expected_imports = (
        ('project_numeric_history_features', numeric_history_features.project_numeric_history_features),
        ('add_calendar_months', synthetic_prediction_cases.add_calendar_months),
        ('json_sha256', numeric_model_bundle.json_sha256),
        ('NumericHistoryBundle', numeric_history_bundle.NumericHistoryBundle),
        ('NumericHistoryRfModel', numeric_history_bundle.NumericHistoryRfModel),
        ('RfTree', numeric_history_bundle.RfTree),
        ('NumericInput', numeric_prediction.NumericInput),
        ('MixedNumericAlgorithm', numeric_history_prediction.MixedNumericAlgorithm),
        ('NumericPredictionV3', numeric_history_prediction.NumericPredictionV3),
        ('NumericTaskAlgorithm', numeric_history_prediction.NumericTaskAlgorithm),
    )
    if any(globals().get(name) is not expected for name, expected in expected_imports):
        raise ValueError('numeric_history_loaded_code_mismatch')
    if numeric_history_features._ols_slope is not prediction_history_features._ols_slope:
        raise ValueError('numeric_history_loaded_code_mismatch')

    bundle = _bundle(bundle)
    verify_numeric_bundle_runtime(bundle.legacy_bundle)
    hashes = _implementation_files()
    identity = json_sha256({'source_sha256': hashes,
                            'legacy_implementation_sha256': bundle.legacy_bundle.implementation_sha256})
    if identity != bundle.implementation_sha256:
        raise ValueError('numeric_history_implementation_changed')
    root = Path(__file__).resolve().parents[3]
    for name in SOURCE_FILES:
        module_name = name.removeprefix('backend/').removesuffix('.py').replace('/', '.')
        module = sys.modules.get(module_name)
        if module is None:
            raise ValueError('numeric_history_loaded_module_missing')
        compiled = compile((root / name).read_bytes(), module.__file__, 'exec', dont_inherit=True)
        codes, pending = {}, [compiled]
        while pending:
            code = pending.pop()
            codes[code.co_qualname] = code
            pending.extend(c for c in code.co_consts if isinstance(c, CodeType))
        for qualified_name, code in codes.items():
            parts = qualified_name.split('.')
            if any(part.startswith('<') for part in parts) or len(parts) > 2:
                continue
            value = module
            for part in parts:
                value = getattr(value, part, None)
            if inspect.isclass(value):
                continue
            function = value.__func__ if inspect.ismethod(value) else value
            if not inspect.isfunction(function) or function.__code__ != code:
                raise ValueError('numeric_history_loaded_code_mismatch')
    # Imported aliases must still point at the verified implementation.
    if numeric_history_features._ols_slope is not prediction_history_features._ols_slope:
        raise ValueError('numeric_history_loaded_code_mismatch')
    if hashes != _implementation_files():
        raise ValueError('numeric_history_implementation_changed')


def _features32(features):
    if len(features) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in features):
        raise ValueError('standardization_error')
    try:
        result = tuple(struct.unpack('!f', struct.pack('!f', value))[0] for value in features)
    except (OverflowError, struct.error) as exc:
        raise ArithmeticError('standardization_error') from exc
    if not all(math.isfinite(v) for v in result):
        raise ArithmeticError('standardization_error')
    return result


def _tree_value(tree, features32):
    index = 0
    while tree.nodes[index].kind == 'branch':
        node = tree.nodes[index]
        index = node.left if features32[node.feature_index] <= node.threshold else node.right
    return tree.nodes[index].value


def predict_tree_json(tree: RfTree, standardized_features: tuple[float, float, float]) -> float:
    tree = RfTree.model_validate(_payload(tree))
    return _tree_value(tree, _features32(standardized_features))


def predict_forest_json(features: list[float], model: NumericHistoryRfModel) -> float:
    model = NumericHistoryRfModel.model_validate(_payload(model))
    if len(features) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in features):
        raise ValueError('standardization_error')
    standardized = [(value - mean) / scale for value, mean, scale in zip(features, model.mean, model.scale)]
    features32 = _features32(standardized)
    total = 0.0
    for tree in model.trees:
        total += _tree_value(tree, features32)
    prediction = total / 200
    if not math.isfinite(prediction):
        raise ArithmeticError('nonfinite_prediction')
    return prediction


def _descriptor(model_id, parameters_sha256):
    history = model_id == 'random_forest:history_v1:value_history'
    version = {'last_value': 'numeric.last_value.v1', 'ridge:main_anchor': 'numeric.ridge.main_anchor.v1',
               'random_forest:history_v1:value_history': 'numeric.random_forest.history_v1.value_history.v1'}[model_id]
    return NumericTaskAlgorithm(model_id=model_id, algorithm_version=version,
                                feature_version='history_v1:value_history' if history else 'main_anchor',
                                eligibility_version='numeric.history.H.v1' if history else 'numeric.anchor.v1',
                                feature_names=['anchor_value', 'prior_value', 'slope_per_day'] if history else ['anchor_value'],
                                parameters_sha256=parameters_sha256)


def predict_numeric_history_bundle(numeric: NumericInput, bundle: NumericHistoryBundle) -> NumericPredictionV3:
    bundle = _bundle(bundle)
    parsed = NumericInput.model_validate(_payload(numeric))
    if parsed.source.source_kind != 'synthetic':
        raise ValueError('numeric_history_synthetic_required')
    value = parsed.model_dump(mode='json')
    value['packets'].sort(key=lambda row: row['horizon_months'])
    for packet in value['packets']:
        packet['input_observations'].sort(key=lambda row: (row['measured_on'], row['observation_id']))
    legacy = {model.task_id: model for model in bundle.legacy_bundle.models}
    predictions, baselines = [], []
    for packet in sorted(parsed.packets, key=lambda p: p.horizon_months):
        history = packet.task_id == 'ad.mmse.12m'
        model = bundle.history_model if history else legacy[packet.task_id]
        indicator, unit = ('mmse', '分') if parsed.disease_code == 'ad' else ('alt', 'U/L')
        common = dict(task_id=packet.task_id, indicator=indicator, unit=unit, horizon_months=packet.horizon_months,
                      target_date=add_calendar_months(parsed.anchor_date, packet.horizon_months))
        anchor = next((row for row in packet.input_observations if row.observation_id == packet.anchor_observation_id), None)
        status = 'available' if packet.input_status == 'available' else 'abstain'
        reason, predicted, raw = packet.input_reason, None, None
        baseline = anchor.value if status == 'available' else None
        baselines.append({**common, 'algorithm': _descriptor('last_value', json_sha256({})),
                          'status': status, 'reason': reason, 'value': baseline})
        if history:
            features = project_numeric_history_features(packet)
            status, reason = features.status, features.reason
        if status == 'available':
            try:
                if history:
                    predicted = predict_forest_json([features.anchor_value, features.prior_value, features.slope_per_day], model)
                else:
                    predicted = (baseline - model.mean[0]) / model.scale[0] * model.coef[0] + model.intercept
                if not math.isfinite(predicted):
                    status, reason, predicted = 'error', 'nonfinite_prediction', None
                elif predicted < 0 or indicator == 'mmse' and predicted > 30:
                    status, reason, raw, predicted = 'error', 'prediction_out_of_bounds', predicted, None
            except (ArithmeticError, ValueError) as exc:
                reason = str(exc) if str(exc) in ('standardization_error', 'nonfinite_prediction') else 'prediction_calculation_error'
                status, predicted = 'error', None
        predictions.append({**common, 'algorithm': _descriptor('random_forest:history_v1:value_history' if history else 'ridge:main_anchor', model.parameters_sha256),
                            'status': status, 'reason': reason, 'value': predicted, 'raw_prediction': raw})
    parameters = [{'task_id': row.task_id, 'parameters_sha256':
                   bundle.history_model.parameters_sha256 if row.provider == 'history_rf' else legacy[row.task_id].parameters_sha256}
                  for row in sorted(bundle.task_assignments, key=lambda row: row.task_id)]
    return NumericPredictionV3(disease_code=parsed.disease_code, subject_id=parsed.subject_id,
                               dependency_group_id=parsed.dependency_group_id, anchor_date=parsed.anchor_date,
                               source=parsed.source, input_sha256=json_sha256(value),
                               algorithm=MixedNumericAlgorithm(implementation_sha256=bundle.implementation_sha256,
                                                               parameters_sha256=json_sha256(parameters), bundle_sha256=history_bundle_sha256(bundle)),
                               predictions=predictions, baseline_predictions=baselines)
