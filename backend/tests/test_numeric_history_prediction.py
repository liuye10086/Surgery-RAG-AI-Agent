from copy import deepcopy
from pathlib import Path
import builtins
import socket

import pytest

from test_numeric_prediction import numeric_fixture
from test_numeric_history_bundle import history_bundle_fixture, rehash_model


@pytest.mark.parametrize('disease,expected,baseline', [('ad', [14., 19.], 22.), ('fatty_liver', [26.75, 26.75], 47.5)])
def test_fixed_routes_and_independent_baselines(disease, expected, baseline):
    from app.services.numeric_history_bundle import predict_numeric_history_bundle, history_bundle_sha256
    raw, bundle = numeric_fixture(disease), history_bundle_fixture()
    before = deepcopy(bundle)
    result = predict_numeric_history_bundle(raw, bundle)
    assert result.schema_version == 'numeric_prediction.v3'
    assert [p.value for p in result.predictions] == expected
    assert [p.value for p in result.baseline_predictions] == [baseline] * 2
    assert [p.algorithm.model_id for p in result.predictions] == (
        ['ridge:main_anchor', 'random_forest:history_v1:value_history'] if disease == 'ad' else ['ridge:main_anchor'] * 2)
    assert all(p.algorithm.algorithm_version == 'numeric.last_value.v1' for p in result.baseline_predictions)
    assert result.algorithm.algorithm_version == 'numeric.mixed_history.v1'
    assert result.algorithm.bundle_sha256 == history_bundle_sha256(bundle)
    assert bundle == before


def test_no_history_only_abstains_rf():
    from app.services.numeric_history_bundle import predict_numeric_history_bundle
    raw = numeric_fixture()
    for packet in raw['packets']:
        packet['input_observations'] = packet['input_observations'][1:]
        packet.update(history_state='confirmed_none')
    result = predict_numeric_history_bundle(raw, history_bundle_fixture())
    assert [(p.status, p.value, p.reason) for p in result.predictions] == [
        ('available', 14., None), ('abstain', None, 'history_not_observed')]
    assert [(p.status, p.value) for p in result.baseline_predictions] == [('available', 22.)] * 2


def test_finite_out_of_bounds_retains_only_audit_raw():
    from app.services.numeric_history_bundle import predict_numeric_history_bundle
    bundle = history_bundle_fixture()
    for tree in bundle['history_model']['trees']: tree['nodes'][0]['value'] = 31.
    rehash_model(bundle['history_model'])
    bundle['history_evidence']['parameters_sha256'] = bundle['history_model']['parameters_sha256']
    result = predict_numeric_history_bundle(numeric_fixture(), bundle)
    row = result.predictions[1]
    assert (row.status, row.reason, row.value, row.raw_prediction) == ('error', 'prediction_out_of_bounds', None, 31.)
    assert [p.value for p in result.baseline_predictions] == [22., 22.]


def test_standardization_overflow_is_task_error():
    from app.services.numeric_history_bundle import predict_numeric_history_bundle
    bundle = history_bundle_fixture()
    bundle['history_model']['mean'][0] = -1e308
    rehash_model(bundle['history_model'])
    bundle['history_evidence']['parameters_sha256'] = bundle['history_model']['parameters_sha256']
    result = predict_numeric_history_bundle(numeric_fixture(), bundle)
    assert (result.predictions[1].status, result.predictions[1].reason) == ('error', 'standardization_error')
    assert result.predictions[1].raw_prediction is None
    assert result.predictions[0].value == 14.


def test_pure_inference_does_not_read_disk_train_or_network(monkeypatch):
    from app.services.numeric_history_bundle import predict_numeric_history_bundle
    raw, bundle = numeric_fixture(), history_bundle_fixture()
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        assert not name.startswith(('sklearn', 'numpy', 'app.services.prediction_history_training'))
        return original_import(name, *args, **kwargs)
    def denied(*args, **kwargs): pytest.fail('unexpected I/O')
    monkeypatch.setattr(builtins, '__import__', guarded_import)
    monkeypatch.setattr(builtins, 'open', denied)
    monkeypatch.setattr(Path, 'read_bytes', denied)
    monkeypatch.setattr(Path, 'read_text', denied)
    monkeypatch.setattr(Path, 'open', denied)
    monkeypatch.setattr(socket, 'socket', denied)
    assert [p.value for p in predict_numeric_history_bundle(raw, bundle).predictions] == [14., 19.]


@pytest.mark.parametrize('mutation', ['real', 'future', 'unit', 'extra', 'mutated_model'])
def test_invalid_inputs_are_hard_failures(mutation):
    from app.schemas.numeric_prediction import NumericInput
    from app.services.numeric_history_bundle import predict_numeric_history_bundle
    raw = numeric_fixture(kind='real' if mutation == 'real' else 'synthetic')
    if mutation == 'mutated_model':
        raw = NumericInput.model_validate(raw)
        raw.packets[0].input_observations[0].value = float('nan')
    elif mutation != 'real':
        for packet in raw['packets']:
            if mutation == 'future': packet['input_observations'][0]['known_on'] = '2099-01-01'
            elif mutation == 'unit': packet['input_observations'][0]['unit'] = 'U/L'
            else: packet['outcome'] = 2.
    with pytest.raises(ValueError): predict_numeric_history_bundle(raw, history_bundle_fixture())


@pytest.mark.parametrize('mutation', ['status', 'raw', 'reason', 'route', 'task', 'date', 'baseline'])
def test_result_contract_rejects_inconsistent_states_and_routes(mutation):
    from app.schemas.numeric_history_prediction import NumericPredictionV3
    from app.services.numeric_history_bundle import predict_numeric_history_bundle
    raw = predict_numeric_history_bundle(numeric_fixture(), history_bundle_fixture()).model_dump(mode='json')
    row = raw['predictions'][1]
    if mutation == 'status': row['status'] = 'abstain'
    elif mutation == 'raw': row['raw_prediction'] = 31.
    elif mutation == 'reason': row['reason'] = 'made_up'
    elif mutation == 'route': row['algorithm'] = deepcopy(raw['predictions'][0]['algorithm'])
    elif mutation == 'task': row['task_id'] = 'ad.mmse.6m'
    elif mutation == 'date': row['target_date'] = '2030-01-01'
    else: raw['baseline_predictions'][0]['algorithm'] = deepcopy(raw['predictions'][0]['algorithm'])
    with pytest.raises(ValueError): NumericPredictionV3.model_validate(raw)


def test_order_changes_preserve_input_identity_and_values():
    from app.services.numeric_history_bundle import predict_numeric_history_bundle
    raw, bundle = numeric_fixture(), history_bundle_fixture()
    first = predict_numeric_history_bundle(raw, bundle)
    raw['packets'].reverse()
    for packet in raw['packets']: packet['input_observations'].reverse()
    assert predict_numeric_history_bundle(raw, bundle) == first


def test_nonfinite_forest_reduction_is_error_without_raw():
    from app.services.numeric_history_bundle import predict_numeric_history_bundle
    bundle = history_bundle_fixture()
    for tree in bundle['history_model']['trees']: tree['nodes'][0]['value'] = 1e308
    rehash_model(bundle['history_model'])
    bundle['history_evidence']['parameters_sha256'] = bundle['history_model']['parameters_sha256']
    result = predict_numeric_history_bundle(numeric_fixture(), bundle)
    row = result.predictions[1]
    assert (row.status, row.reason, row.value, row.raw_prediction) == ('error', 'nonfinite_prediction', None, None)
    assert result.predictions[0].value == 14.
    assert result.baseline_predictions[1].value == 22.
