import importlib.util
import json
from pathlib import Path

import pytest


def api():
    path = Path(__file__).resolve().parents[1] / 'run_synthetic_prediction_stability.py'
    spec = importlib.util.spec_from_file_location('stability_runner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_protocol_fixes_seeds_scales_and_training_budget():
    m = api()
    assert m.PROTOCOL['seeds'] == [20260914, 20260915, 20260916]
    assert m.PROTOCOL['training_groups_per_disease'] == {'120': 64, '600': 320, '1200': 640}
    assert m.PROTOCOL['patients_per_disease'] == 1200
    assert m.PROTOCOL['challenge_per_disease'] == 400
    assert m.PROTOCOL['validation_fraction'] == .2


def test_existing_destination_is_never_modified(tmp_path):
    m = api()
    keep = tmp_path / 'keep'
    keep.write_bytes(b'original')
    with pytest.raises(FileExistsError):
        m.run_experiment(tmp_path)
    assert list(tmp_path.iterdir()) == [keep] and keep.read_bytes() == b'original'


def test_exception_preserves_frozen_protocol_and_first_failure(tmp_path, monkeypatch):
    m = api()
    calls = []
    def fail(seed):
        calls.append(seed)
        raise RuntimeError('sensitive exception detail')
    monkeypatch.setattr(m, '_source', fail)
    output = tmp_path / 'failed'
    with pytest.raises(RuntimeError):
        m.run_experiment(output)
    assert calls == [20260914]
    assert json.loads((output / 'protocol.json').read_text())['protocol'] == m.PROTOCOL
    manifest = json.loads((output / 'manifest.json').read_text())
    assert manifest['status'] == 'failed' and manifest['error'] == 'experiment_runtime_error'
    assert 'sensitive' not in (output / 'manifest.json').read_text()
    assert m.verify_experiment(output)['status'] == 'failed'


def test_cli_argument_and_runtime_errors_are_sanitized(tmp_path, monkeypatch, capsys):
    m = api()
    assert m.main([]) == 2
    assert json.loads(capsys.readouterr().out)['error'] == 'invalid_arguments'
    def fail(*args, **kwargs):
        raise OSError('private directory details')
    monkeypatch.setattr(m, 'run_experiment', fail)
    assert m.main(['--output-dir', str(tmp_path / 'new')]) == 4
    assert 'private' not in capsys.readouterr().out


@pytest.fixture(scope='module')
def small_package(tmp_path_factory):
    m = api()
    # Isolated test protocol preserves all three seeds/scales and real fitting.
    m.PROTOCOL = {**m.PROTOCOL, 'patients_per_disease': 120, 'challenge_per_disease': 40,
                  'training_groups_per_disease': {'120': 32, '600': 48, '1200': 64}}
    output = tmp_path_factory.mktemp('stability') / 'package'
    result = m.run_experiment(output)
    return m, output, result


def test_real_small_experiment_recomputes_all_units(small_package):
    m, output, result = small_package
    assert result['status'] == 'passed'
    assert result['counts']['units'] == 9
    assert result['counts']['fitted_models'] == result['counts']['model_attempts'] == 216
    assert result['counts']['comparisons'] == 864
    assert m.verify_experiment(output)['status'] == 'passed'
    assert json.loads((output / 'manifest.json').read_text())['clinical_status'] == 'not_assessable'


def test_rehashing_modified_score_does_not_pass_recomputation(small_package, tmp_path):
    import shutil
    m, output, _ = small_package
    changed = tmp_path / 'changed'
    shutil.copytree(output, changed)
    path = changed / 'seed-20260914/scale-120/scores.json'
    value = json.loads(path.read_text())
    value['training']['evaluation']['comparisons'][0]['statistics']['mae'] = 123456.
    path.write_text(json.dumps(value))
    manifest = json.loads((changed / 'manifest.json').read_text())
    manifest['files'] = m._file_records(changed)
    manifest['data_content_sha256'] = m._hash(manifest['files'])
    (changed / 'manifest.json').write_text(json.dumps(manifest))
    assert m.verify_experiment(changed)['status'] == 'failed'


def test_untrusted_manifest_paths_rejected_without_source_execution(small_package, tmp_path, monkeypatch):
    import shutil
    m, output, _ = small_package
    changed = tmp_path / 'changed'
    shutil.copytree(output, changed)
    manifest = json.loads((changed / 'manifest.json').read_text())
    manifest['files']['../foreign.json'] = {'sha256': '0' * 64, 'bytes': 1}
    (changed / 'manifest.json').write_text(json.dumps(manifest))
    def forbidden(*args):
        raise AssertionError('must reject file set first')
    monkeypatch.setattr(m, '_source', forbidden)
    assert m.verify_experiment(changed)['status'] == 'failed'


def test_first_fit_failure_is_not_retried_by_experiment_verifier(tmp_path, monkeypatch):
    from sklearn.linear_model import Ridge
    m = api()
    m.PROTOCOL = {**m.PROTOCOL, 'seeds': [20260914], 'patients_per_disease': 120,
                  'challenge_per_disease': 40, 'training_groups_per_disease': {'120': 32}}
    original = Ridge.fit
    attempts = []
    def fail_first(self, X, y, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError('first fit failed')
        return original(self, X, y, **kwargs)
    monkeypatch.setattr(Ridge, 'fit', fail_first)
    output = tmp_path / 'one-fit-failure'
    result = m.run_experiment(output)
    assert result['status'] == 'incomplete'
    assert result['counts']['fitted_models'] == 23
    assert len(attempts) == 12
    verified = m.verify_experiment(output)
    assert verified['status'] == 'passed' and verified['engineering_status'] == 'incomplete'
    assert verified['fit_error_verification'] == 'inputs_checked_not_retried'
    assert len(attempts) == 23
    monkeypatch.setattr(Ridge, 'fit', original)
    assert m.verify_experiment(output)['engineering_status'] == 'incomplete'


def test_unit_archives_baselines_for_unlabelled_and_abstaining_inputs(monkeypatch):
    m = api()
    m.PROTOCOL = {**m.PROTOCOL, 'patients_per_disease': 120, 'challenge_per_disease': 40,
                  'training_groups_per_disease': {'120': 32}}
    source = m._source(20260914)
    # Model fitting/predictions are tested above; retain real source and baseline/score paths.
    monkeypatch.setattr(m, 'fit_candidate_models', lambda *a, **k: {'models': [], 'estimators': {}})
    monkeypatch.setattr(m, 'predict_candidate_models', lambda *a: [])
    unit, _ = m._unit(source, 32)
    rows = unit['baseline_predictions']['challenge']
    challenge = [s for s in source['samples'] if s['pool'] == 'challenge_pool']
    assert len(rows) == 2 * len(challenge)
    unlabelled = {s['sample_id'] for s in challenge if s['label_status'] != 'valid'}
    assert any(r['sample_id'] in unlabelled and r['status'] == 'valid' for r in rows)
    assert any(r['status'] == 'abstain' and r['reason'] for r in rows)
