from copy import deepcopy

import pytest

from test_synthetic_numeric_prediction import literal_input


def numeric_fixture(disease='ad', kind='synthetic'):
    raw = literal_input(disease)
    raw['schema_version'] = 'numeric_input.v1'
    source = dict(source_kind=kind, is_synthetic=kind == 'synthetic',
                  generator_version='fixture.v1' if kind == 'synthetic' else None,
                  dataset_id='explicitly-fictional-fixture', dataset_version='v1', run_id='fixture-run')
    raw['source'].update(source)
    for packet in raw['packets']:
        packet['source'] = deepcopy(source)
    return raw


@pytest.mark.parametrize('disease,expected', [('ad', 22.0), ('fatty_liver', 47.5)])
@pytest.mark.parametrize('kind', ['synthetic', 'real'])
def test_two_sources_share_last_value_contract(disease, expected, kind):
    from app.services.numeric_prediction import predict_numeric
    result = predict_numeric(numeric_fixture(disease, kind))
    assert [p.value for p in result.predictions] == [expected, expected]
    assert [p.horizon_months for p in result.predictions] == [6, 12]
    assert result.source.source_kind == kind
    assert result.algorithm.clinical_validity_claim is False


@pytest.mark.parametrize('kind', ['synthetic', 'real'])
@pytest.mark.parametrize('mutation', ['flag', 'future', 'unit', 'horizon', 'unavailable', 'source'])
def test_rejects_invalid_source_and_numeric_states(kind, mutation):
    from app.services.numeric_prediction import predict_numeric
    raw = numeric_fixture(kind=kind)
    if mutation == 'flag':
        raw['source']['is_synthetic'] = int(kind == 'synthetic')
    elif mutation == 'source':
        raw['source']['generator_version'] = 'invalid' if kind == 'real' else None
    else:
        for packet in raw['packets']:
            if mutation == 'future':
                packet['input_observations'][1]['known_on'] = '2024-01-01'
            elif mutation == 'unit':
                packet['input_observations'][1]['unit'] = 'points'
            elif mutation == 'horizon':
                packet['horizon_months'] = 6.0
            else:
                packet['input_status'] = 'unavailable'
    with pytest.raises(ValueError):
        predict_numeric(raw)


def test_saved_validation_does_not_resolve_active_algorithm(monkeypatch):
    from app.services import numeric_prediction as service
    raw = numeric_fixture(kind='real')
    result = service.predict_numeric(raw)
    monkeypatch.setattr(service, 'numeric_algorithm_identity', lambda: pytest.fail('active_algorithm'))
    assert service.validate_numeric_prediction(result, raw, result.algorithm) == result
    changed = result.model_dump(mode='json')
    changed['predictions'][0]['value'] = 20.0
    with pytest.raises(ValueError):
        service.validate_numeric_prediction(changed, raw, result.algorithm)


def test_unavailable_results_preserve_missingness_and_reject_fabricated_value():
    from app.services import numeric_prediction as service
    raw = numeric_fixture(kind='real')
    for packet in raw['packets']:
        packet.update(input_status='unavailable', input_reason='population_not_confirmed')
    result = service.predict_numeric(raw)
    assert [p.value for p in result.predictions] == [None, None]
    assert [p.reason for p in result.predictions] == ['population_not_confirmed'] * 2
    changed = result.model_dump(mode='json')
    changed['predictions'][0].update(status='available', reason=None, value=22.0)
    with pytest.raises(ValueError):
        service.validate_numeric_prediction(changed, raw, result.algorithm)


def test_identity_is_order_independent_and_pins_actual_loaded_source(monkeypatch):
    from pathlib import Path
    from app.services import numeric_prediction as service
    raw = numeric_fixture()
    reordered = deepcopy(raw)
    reordered['packets'].reverse()
    for packet in reordered['packets']:
        packet['input_observations'].reverse()
    assert service.numeric_input_sha256(raw) == service.numeric_input_sha256(reordered)
    saved = service.predict_numeric(raw)
    original = Path.read_bytes
    monkeypatch.setattr(Path, 'read_bytes', lambda path: original(path) + (b'\n# changed\n' if path.name == 'numeric_prediction.py' else b''))
    with pytest.raises(ValueError, match='numeric_implementation_changed'):
        service.predict_numeric(raw)
    assert service.validate_numeric_prediction(saved, raw, saved.algorithm) == saved
