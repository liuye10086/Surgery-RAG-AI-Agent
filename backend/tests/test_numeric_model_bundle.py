"""Fixed JSON inference, invalid artifacts, and training separation."""

from copy import deepcopy
import hashlib
import json

import pytest

from test_numeric_prediction import numeric_fixture


TASKS = ('ad.mmse.6m', 'ad.mmse.12m', 'fatty_liver.alt.6m', 'fatty_liver.alt.12m')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def bundle_fixture():
    models = []
    for task in TASKS:
        disease, indicator, horizon = task.split('.')
        record = dict(task_id=task, indicator=indicator, unit='分' if disease == 'ad' else 'U/L',
                      horizon_months=int(horizon[:-1]), feature_names=['anchor_value'], mean=[0.0],
                      std=[1.0], scale=[1.0], coef=[0.5], intercept=3.0,
                      training_sample_ids=[task + ':a', task + ':b'],
                      training_subject_ids=['dev-a', 'dev-b'], training_dependency_groups=['dev-a', 'dev-b'],
                      training_identity_sha256='1' * 64, training_data_sha256='2' * 64)
        record['parameters_sha256'] = digest(record)
        models.append(record)
    evaluation = dict(schema_version='synthetic_prediction_candidates.v1', clinical_validity_claim=False,
                      clinical_status='not_assessable', candidate_model_training='executed',
                      d03_model_comparison='executed', engineering_status='passed', fit_failures=[],
                      comparisons=[dict(task_id=t, model_id='ridge:main_anchor', pool=p,
                                        counts={'N_patient': 2, 'N_label_valid': 2, 'N_pair_valid': 2})
                                   for t in TASKS for p in ('development_pool', 'challenge_pool')])
    return dict(schema_version='numeric_model_bundle.v1', model_id='ridge:main_anchor',
                algorithm_version='numeric.ridge.main_anchor.v1', input_schema_version='numeric_input.v1',
                implementation_sha256='3' * 64, models=models, evaluation=evaluation,
                evaluation_sha256=digest(evaluation),
                source={'cases': {'run_id': 'fixture-case', 'data_content_sha256': '4' * 64},
                        'calculation': {'run_id': 'fixture-calc', 'data_content_sha256': '5' * 64}},
                challenge_subject_ids=['challenge-a'], challenge_dependency_groups=['challenge-a'],
                clinical_validity_claim=False, production_enabled=False)


@pytest.mark.parametrize('disease,expected,baseline', [('ad', 14.0, 22.0), ('fatty_liver', 26.75, 47.5)])
def test_literal_json_prediction_and_baseline(disease, expected, baseline):
    from app.services.numeric_model_bundle import predict_numeric_bundle, bundle_sha256
    raw = numeric_fixture(disease)
    bundle = bundle_fixture()
    result = predict_numeric_bundle(raw, bundle)
    assert result.schema_version == 'numeric_prediction.v2'
    assert [p.value for p in result.predictions] == [expected, expected]
    assert [p.value for p in result.baseline_predictions] == [baseline, baseline]
    assert result.algorithm.bundle_sha256 == bundle_sha256(bundle)
    assert result.source == result.source.model_validate(raw['source'])


@pytest.mark.parametrize('mutation', ['missing_task', 'duplicate_task', 'unit', 'scale', 'nan', 'coef_tamper',
                                      'eval_tamper', 'challenge_leak', 'extra', 'flag'])
def test_invalid_bundle_rejected(mutation):
    from app.schemas.numeric_model_bundle import NumericModelBundle
    raw = bundle_fixture()
    if mutation == 'missing_task': raw['models'].pop()
    elif mutation == 'duplicate_task': raw['models'][1] = deepcopy(raw['models'][0])
    elif mutation == 'unit': raw['models'][0]['unit'] = 'U/L'
    elif mutation == 'scale': raw['models'][0]['scale'] = [0.0]
    elif mutation == 'nan': raw['models'][0]['coef'] = [float('nan')]
    elif mutation == 'coef_tamper': raw['models'][0]['coef'] = [0.9]
    elif mutation == 'eval_tamper': raw['evaluation']['comparisons'][0]['counts']['N_patient'] = 0
    elif mutation == 'challenge_leak': raw['challenge_dependency_groups'] = ['dev-a']
    elif mutation == 'extra': raw['pickle_path'] = 'unsafe.pkl'
    elif mutation == 'flag': raw['production_enabled'] = 0
    with pytest.raises(ValueError):
        NumericModelBundle.model_validate(raw)


def test_saved_bundle_and_prediction_do_not_read_current_files_or_train(tmp_path, monkeypatch):
    from pathlib import Path
    from app.services.numeric_model_bundle import load_numeric_model_bundle, predict_numeric_bundle, validate_trained_numeric_prediction
    path = tmp_path / 'bundle.json'
    path.write_text(json.dumps(bundle_fixture(), ensure_ascii=False), encoding='utf-8')
    bundle = load_numeric_model_bundle(path)
    raw = numeric_fixture()
    saved = predict_numeric_bundle(raw, bundle)
    path.write_text('{}', encoding='utf-8')
    monkeypatch.setattr(Path, 'read_bytes', lambda *args: pytest.fail('inference_reads_files'))
    assert predict_numeric_bundle(raw, bundle) == saved
    assert validate_trained_numeric_prediction(saved, raw, bundle) == saved
    altered = saved.model_dump(mode='json')
    altered['predictions'][0]['value'] += 1
    with pytest.raises(ValueError):
        validate_trained_numeric_prediction(altered, raw, bundle)


@pytest.mark.parametrize('mutation', ['future', 'unit', 'task', 'target'])
def test_invalid_input_rejected(mutation):
    from app.services.numeric_model_bundle import predict_numeric_bundle
    raw = numeric_fixture()
    for packet in raw['packets']:
        if mutation == 'future': packet['input_observations'][1]['known_on'] = '2099-01-01'
        elif mutation == 'unit': packet['input_observations'][1]['unit'] = 'U/L'
        elif mutation == 'task': packet['task_id'] = 'fatty_liver.alt.6m'
        else: packet['actual'] = 20.0
    with pytest.raises(ValueError):
        predict_numeric_bundle(raw, bundle_fixture())


def test_physical_bounds_are_rejected_without_clipping():
    from app.services.numeric_model_bundle import predict_numeric_bundle
    raw = bundle_fixture()
    raw['models'][0]['intercept'] = 31.0
    raw['models'][0]['parameters_sha256'] = digest({k: v for k, v in raw['models'][0].items() if k != 'parameters_sha256'})
    with pytest.raises(ValueError, match='numeric_model_prediction_out_of_bounds'):
        predict_numeric_bundle(numeric_fixture(), raw)


def test_unavailable_input_preserved():
    from app.services.numeric_model_bundle import predict_numeric_bundle
    raw = numeric_fixture()
    for packet in raw['packets']:
        packet.update(input_status='unavailable', input_reason='population_not_confirmed')
    result = predict_numeric_bundle(raw, bundle_fixture())
    assert [p.value for p in result.predictions] == [None, None]
    assert [p.reason for p in result.baseline_predictions] == ['population_not_confirmed'] * 2


@pytest.mark.parametrize('contents', ['{}', '{"schema_version":"numeric_model_bundle.v1","schema_version":"other"}', '{"value":NaN}'])
def test_strict_json_loader(tmp_path, contents):
    from app.services.numeric_model_bundle import load_numeric_model_bundle
    path = tmp_path / 'bundle.json'
    path.write_text(contents, encoding='utf-8')
    with pytest.raises(ValueError):
        load_numeric_model_bundle(path)


def test_builder_requires_fresh_directory_and_verified_sources(tmp_path):
    from app.services.numeric_model_bundle import build_numeric_model_bundle
    destination = tmp_path / 'existing'
    destination.mkdir()
    with pytest.raises(FileExistsError):
        build_numeric_model_bundle(tmp_path / 'missing-source', tmp_path / 'missing-calc', destination)
    with pytest.raises(ValueError, match='source_not_verified'):
        build_numeric_model_bundle(tmp_path / 'missing-source', tmp_path / 'missing-calc', tmp_path / 'new')
    assert not (tmp_path / 'new').exists()


def test_fixed_selection_preserves_challenge_evaluation_and_training_separation(monkeypatch):
    from app.services import numeric_model_bundle as service
    from app.services import prediction_candidate_evaluation as scoring
    from test_prediction_candidate_training import rows
    features, samples = rows()
    # This test exercises the actual frozen fitter. Bootstrap evaluation has its own tests;
    # a fixed result keeps this boundary test small and records all supplied rows.
    observed = []
    def evaluate(actual_samples, predictions, baselines):
        observed.append(deepcopy(actual_samples))
        return {'evaluation': deepcopy(bundle_fixture()['evaluation']), 'paired_rows': [], 'bootstrap_plans': {}}
    monkeypatch.setattr(scoring, 'evaluate_candidates', evaluate)
    source = {'features': features, 'samples': samples, 'predictions': []}
    first, diagnostics = service._fit_bundle(source, bundle_fixture()['source'], '3' * 64)
    assert len(diagnostics['models']) == 24
    assert len(first.models) == 4
    for model in first.models:
        assert model.training_sample_ids == [model.task_id + ':a', model.task_id + ':b']
        assert model.mean == [1.0]
        assert model.coef[0] == pytest.approx(2 / 3)
    changed = deepcopy(source)
    for feature, sample in zip(changed['features'], changed['samples']):
        if sample['pool'] == 'challenge_pool':
            feature['anchor_value'] += 100
            sample['actual'] = -123
    second, _ = service._fit_bundle(changed, bundle_fixture()['source'], '3' * 64)
    assert first.models == second.models
    assert observed[0] == samples
    assert observed[1] == changed['samples']
    assert first.evaluation['comparisons'][0]['counts']['N_patient'] == 2


def test_missing_required_fit_preserves_diagnostics_and_refuses_bundle(monkeypatch):
    from app.services import numeric_model_bundle as service
    from app.services import prediction_candidate_training as training
    from app.services import prediction_candidate_evaluation as scoring
    monkeypatch.setattr(training, 'fit_candidate_models', lambda *args: {
        'models': [{'task_id': TASKS[0], 'model_id': 'ridge:main_anchor', 'status': 'error', 'reason': 'model_fit_error'}],
        'estimators': {},
    })
    monkeypatch.setattr(training, 'predict_candidate_models', lambda *args: [])
    monkeypatch.setattr(scoring, 'evaluate_candidates', lambda *args: {
        'evaluation': {'comparisons': []}, 'paired_rows': [], 'bootstrap_plans': {},
    })
    bundle, diagnostics = service._fit_bundle({'features': [], 'samples': [], 'predictions': []},
                                             bundle_fixture()['source'], '3' * 64)
    assert bundle is None
    assert diagnostics['evaluation']['engineering_status'] == 'incomplete'
    assert diagnostics['evaluation']['fit_failures'][0]['reason'] == 'model_fit_error'


def test_runtime_gate_rejects_disk_and_loaded_implementation_drift(monkeypatch):
    from pathlib import Path
    from app.services import numeric_model_bundle as service
    raw = bundle_fixture()
    raw['implementation_sha256'] = digest(service._implementation_files())
    assert service.verify_numeric_bundle_runtime(raw) is None
    original_read = Path.read_bytes
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'read_bytes', lambda path: original_read(path) +
                      (b'\n# implementation changed\n' if path.name == 'numeric_model_bundle.py' else b''))
        with pytest.raises(ValueError, match='numeric_model_implementation_changed'):
            service.verify_numeric_bundle_runtime(raw)
    monkeypatch.setattr(service, 'predict_numeric_bundle', lambda *args: 'wrong implementation')
    with pytest.raises(ValueError, match='numeric_model_loaded_code_mismatch'):
        service.verify_numeric_bundle_runtime(raw)
