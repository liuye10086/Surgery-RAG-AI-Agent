import hashlib
import json
from pathlib import Path
import shutil

import pytest


@pytest.fixture(scope='module')
def package(tmp_path_factory):
    from app.schemas.synthetic_prediction_cases import GenerationConfig
    from app.services.synthetic_prediction_case_export import export_synthetic_cases
    from app.services.prediction_calculation_export import evaluate_synthetic_package
    from app.services.prediction_candidate_export import evaluate_candidate_package
    parent = tmp_path_factory.mktemp('candidate-package')
    source, calc, output = (parent / n for n in ('source', 'calculation', 'candidates'))
    assert export_synthetic_cases(GenerationConfig(), source)['status'] == 'passed'
    assert evaluate_synthetic_package(source, calc)['status'] == 'passed'
    result = evaluate_candidate_package(source, calc, output)
    return source, calc, output, result


def api():
    from app.services import prediction_candidate_export
    return prediction_candidate_export


def test_real_export_recompute_and_trusted_model_roundtrip(package):
    source, calc, output, result = package
    assert result['status'] == 'passed'
    assert result['counts']['fitted_models'] == result['counts']['model_attempts'] == 24
    assert result['counts']['predictions'] == 2880
    assert result['counts']['comparisons'] == 64
    assert api().verify_candidate_export(output)['status'] == 'passed'
    models = json.loads((output / 'models.json').read_text(encoding='utf-8'))
    for model in models:
        assert model['status'] == 'fitted'
        assert len(model['training_sample_ids']) < 80
    manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['trusted_model_roundtrip'] == 'passed'
    assert manifest['clinical_status'] == 'not_assessable'
    assert len(manifest['model_files']) == 24


def test_repeat_is_numerically_identical_and_preserves_sources(package):
    source, calc, output, result = package
    before = {str(p): p.read_bytes() for d in (source, calc) for p in d.iterdir()}
    other = output.parent / 'repeated'
    second = api().evaluate_candidate_package(source, calc, other)
    assert second['run_id'] == result['run_id']
    assert second['data_content_sha256'] == result['data_content_sha256']
    for name in api().DATA_FILES:
        assert (output / name).read_bytes() == (other / name).read_bytes()
    assert before == {str(p): p.read_bytes() for d in (source, calc) for p in d.iterdir()}


def rehash(output, name):
    path = output / name
    manifest_path = output / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['files'][name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}
    manifest['data_content_sha256'] = api().content_hash(manifest['files'])
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')


@pytest.mark.parametrize('kind', ['score', 'model', 'runtime', 'missing_model', 'source', 'code'])
def test_tampering_cannot_be_approved_by_rehashing(package, kind):
    _, _, output, _ = package
    altered = output.parent / ('altered-' + kind)
    shutil.copytree(output, altered)
    manifest = json.loads((altered / 'manifest.json').read_text(encoding='utf-8'))
    if kind == 'score':
        path = altered / 'evaluation.json'
        value = json.loads(path.read_text(encoding='utf-8'))
        value['comparisons'][0]['statistics']['mae'] = 123456.
        path.write_text(json.dumps(value), encoding='utf-8')
        rehash(altered, path.name)
    elif kind in {'runtime', 'source', 'code'}:
        if kind == 'runtime': manifest['runtime']['sklearn'] = 'other'
        elif kind == 'source': manifest['sources']['cases']['run_id'] = 'other'
        else: manifest['code_sha256'][next(iter(manifest['code_sha256']))] = '0'*64
        (altered / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    else:
        name = next(iter(manifest['model_files'].values()))
        if kind == 'model':
            (altered / name).write_bytes(b'not a trusted model')
            rehash(altered, name)
        else:
            (altered / name).unlink()
    assert api().verify_candidate_export(altered)['status'] == 'failed'


def test_verifier_never_deserializes_external_joblib(package, monkeypatch):
    _, _, output, _ = package
    def forbidden(*args, **kwargs):
        raise AssertionError('external pickle must not be executed')
    monkeypatch.setattr(api().joblib, 'load', forbidden)
    assert api().verify_candidate_export(output)['status'] == 'passed'


def test_invalid_sources_existing_and_nested_destinations_rejected(package):
    source, calc, output, _ = package
    with pytest.raises(FileExistsError): api().evaluate_candidate_package(source, calc, output)
    for d in (source, calc):
        with pytest.raises(ValueError, match='output_inside_source'):
            api().evaluate_candidate_package(source, calc, d / 'nested/output')
        assert not (d / 'nested').exists()
    invalid = output.parent / 'invalid-calculation'
    shutil.copytree(calc, invalid)
    (invalid / 'features.jsonl').write_bytes(b'{}\n')
    with pytest.raises(ValueError): api().evaluate_candidate_package(source, invalid, output.parent / 'not-created')
    assert not (output.parent / 'not-created').exists()


def test_io_failure_and_competing_writer_preserve_other_files(package, monkeypatch):
    source, calc, output, _ = package
    m = api()
    destination = output.parent / 'competing'
    original = m.os.rename
    def compete(temporary, target):
        destination.mkdir()
        (destination / 'keep').write_bytes(b'other writer')
        return original(temporary, target)
    monkeypatch.setattr(m.os, 'rename', compete)
    with pytest.raises(FileExistsError): m.evaluate_candidate_package(source, calc, destination)
    assert (destination / 'keep').read_bytes() == b'other writer'
    assert not list(output.parent.glob('.prediction-candidates-*'))
    monkeypatch.setattr(m.os, 'rename', original)
    original_write = Path.write_bytes
    def fail(path, data):
        if path.name == 'evaluation.json': raise OSError('private detail must not escape CLI')
        return original_write(path, data)
    monkeypatch.setattr(Path, 'write_bytes', fail)
    with pytest.raises(OSError): m.evaluate_candidate_package(source, calc, output.parent / 'io-failure')
    assert not list(output.parent.glob('.prediction-candidates-*'))
    assert (destination / 'keep').read_bytes() == b'other writer'


def test_full_pipeline_records_fit_failures_and_cli_returns_incomplete(package, monkeypatch, capsys):
    import importlib.util
    from app.services import prediction_candidate_training as training
    from sklearn.linear_model import Ridge

    class FailingRidge(Ridge):
        def fit(self, X, y, **kwargs):
            raise RuntimeError('controlled fitting failure')

    factory = training._estimator
    monkeypatch.setattr(training, '_estimator', lambda family: FailingRidge(**factory(family).get_params(deep=False))
                        if family == 'ridge' else factory(family))
    source, calc, output, _ = package
    failed = output.parent / 'controlled-fit-failure'
    script = Path(__file__).resolve().parents[2] / 'scripts/evaluate_synthetic_prediction_candidates.py'
    spec = importlib.util.spec_from_file_location('candidate_cli_failure', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    code = module.main(['--source-dir', str(source), '--calculation-dir', str(calc), '--output-dir', str(failed)])
    result = json.loads(capsys.readouterr().out)
    assert code == 3 and result['status'] == 'incomplete'
    assert result['counts']['model_attempts'] == 24
    assert result['counts']['fitted_models'] == 12
    assert api().verify_candidate_export(failed)['engineering_status'] == 'incomplete'
    evaluation = json.loads((failed / 'evaluation.json').read_text(encoding='utf-8'))
    assert len(evaluation['fit_failures']) == 12
    predictions = [json.loads(line) for line in (failed / 'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(predictions) == 2880
    assert any(p['status'] == 'error' for p in predictions)
    assert any(c['counts']['N_pred_error'] > 0 and not c['complete_output'] for c in evaluation['comparisons'])
    assert not list(output.parent.glob('.prediction-candidates-*'))


def test_first_fit_failure_is_archived_without_retrying_that_fit(package, monkeypatch):
    from app.services import prediction_candidate_training as training
    from sklearn.linear_model import Ridge

    attempts = []
    class FailFirstRidge(Ridge):
        def fit(self, X, y, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError('first attempt must remain recorded')
            return super().fit(X, y, **kwargs)

    factory = training._estimator
    created = []
    def controlled(family):
        # Only the first Ridge factory product carries the injected exception.
        if family == 'ridge' and not created:
            created.append(1)
            return FailFirstRidge(**factory(family).get_params(deep=False))
        return factory(family)
    monkeypatch.setattr(training, '_estimator', controlled)
    source, calc, output, _ = package
    failed = output.parent / 'first-fit-failure'
    result = api().evaluate_candidate_package(source, calc, failed)
    assert result['status'] == 'incomplete'
    assert result['counts']['model_attempts'] == 24
    assert result['counts']['fitted_models'] == 23
    assert len(attempts) == 1
    # Return to the healthy implementation: failure verification must not turn it into success.
    monkeypatch.setattr(training, '_estimator', factory)
    verified = api().verify_candidate_export(failed)
    assert verified['status'] == 'passed' and verified['engineering_status'] == 'incomplete'
    assert verified['fit_error_verification'] == 'inputs_checked_not_retried'
    evaluation = json.loads((failed / 'evaluation.json').read_text(encoding='utf-8'))
    assert len(evaluation['fit_failures']) == 1
    assert evaluation['fit_failures'][0]['reason'] == 'model_fit_error'
    models_path = failed / 'models.json'
    models = json.loads(models_path.read_text(encoding='utf-8'))
    next(m for m in models if m['status'] == 'error')['training_data_sha256'] = '0' * 64
    models_path.write_text(json.dumps(models), encoding='utf-8')
    rehash(failed, models_path.name)
    assert api().verify_candidate_export(failed)['status'] == 'failed'
