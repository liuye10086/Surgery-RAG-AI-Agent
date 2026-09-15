"""CLI reports safe status codes without revealing exception details."""

import importlib.util
import json
from pathlib import Path


def cli():
    path = Path(__file__).resolve().parents[1] / 'build_numeric_model_bundle.py'
    spec = importlib.util.spec_from_file_location('numeric_bundle_cli', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_invalid_arguments(capsys):
    assert cli().main([]) == 2
    assert json.loads(capsys.readouterr().out)['error'] == 'invalid_arguments'


def test_cli_existing_directory(tmp_path, capsys):
    code = cli().main(['--source-dir', str(tmp_path), '--calculation-dir', str(tmp_path), '--output-dir', str(tmp_path)])
    assert code == 2
    assert json.loads(capsys.readouterr().out)['error'] == 'output_exists'


def test_cli_safe_runtime_error(monkeypatch, capsys):
    module = cli()
    def fail(*args):
        raise RuntimeError('sensitive-runtime-detail')
    monkeypatch.setattr(module, 'build_numeric_model_bundle', fail)
    assert module.main(['--source-dir', 'a', '--calculation-dir', 'b', '--output-dir', 'c']) == 4
    output = capsys.readouterr().out
    assert 'sensitive-runtime-detail' not in output
    assert json.loads(output)['error'] == 'numeric_model_runtime_error'
