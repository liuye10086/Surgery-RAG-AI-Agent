import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'evaluate_synthetic_prediction_candidates.py'


def command(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True, encoding='utf-8')


def test_missing_arguments_use_safe_json():
    run = command()
    assert run.returncode == 2
    assert json.loads(run.stdout)['error'] == 'invalid_arguments'
    assert not run.stderr


def test_invalid_source_and_existing_output_do_not_expose_paths(tmp_path):
    out = tmp_path / 'exists'
    out.mkdir()
    args = ('--source-dir', tmp_path / 'private-source', '--calculation-dir', tmp_path / 'private-calc', '--output-dir')
    run = command(*args, out)
    assert run.returncode == 2
    assert json.loads(run.stdout)['error'] == 'output_exists'
    run = command(*args, tmp_path / 'new')
    assert run.returncode == 3
    assert 'private-' not in run.stdout + run.stderr
    assert not run.stderr


@pytest.mark.parametrize('mode,code', [('incomplete', 3), ('io', 4)])
def test_cli_model_failure_and_runtime_failure_are_not_success(mode, code, capsys, monkeypatch):
    spec = importlib.util.spec_from_file_location('candidate_cli', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def result(*args):
        if mode == 'io': raise OSError('sensitive private directory')
        return {'status': 'incomplete', 'clinical_status': 'not_assessable'}
    monkeypatch.setattr(module, 'evaluate_candidate_package', result)
    assert module.main(['--source-dir','a','--calculation-dir','b','--output-dir','c']) == code
    assert 'sensitive' not in capsys.readouterr().out
