import importlib.util
import json
from pathlib import Path


def cli():
    path = Path(__file__).resolve().parents[1] / 'build_numeric_history_bundle.py'
    spec = importlib.util.spec_from_file_location('history_bundle_cli', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_is_only_preflight(monkeypatch, tmp_path, capsys):
    module = cli()
    calls = []
    monkeypatch.setattr(module, 'preflight_numeric_history_bundle', lambda *a: calls.append('preflight') or {'status': 'passed'})
    monkeypatch.setattr(module, 'build_numeric_history_bundle', lambda *a: calls.append('build'))
    assert module.main(['--history-dir', 'a', '--legacy-bundle', 'b', '--output-dir', str(tmp_path / 'new')]) == 0
    assert calls == ['preflight']
    assert not (tmp_path / 'new').exists()


def test_verify_only_and_no_fit(monkeypatch, capsys):
    module = cli()
    monkeypatch.setattr(module, 'verify_numeric_history_bundle', lambda p: {'status': 'passed'})
    monkeypatch.setattr(module, 'build_numeric_history_bundle', lambda *a: 1 / 0)
    assert module.main(['--verify-dir', 'x']) == 0


def test_invalid_arguments(capsys):
    assert cli().main([]) == 2
    assert json.loads(capsys.readouterr().out)['error'] == 'invalid_arguments'


def test_sensitive_runtime_errors_are_not_exposed(monkeypatch, capsys):
    module = cli()
    def fail(*a):
        raise RuntimeError('secret connection string')
    monkeypatch.setattr(module, 'preflight_numeric_history_bundle', fail)
    assert module.main(['--history-dir', 'a', '--legacy-bundle', 'b', '--output-dir', 'c']) == 4
    assert 'secret' not in capsys.readouterr().out
