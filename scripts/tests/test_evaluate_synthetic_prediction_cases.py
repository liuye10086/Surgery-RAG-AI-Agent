import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def cli():
    path = Path(__file__).resolve().parents[1] / "evaluate_synthetic_prediction_cases.py"
    spec = importlib.util.spec_from_file_location("calculation_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_rejects_bad_parameters_without_echoing_values(cli, capsys):
    assert cli.main(["--secret", "hidden-test-value"]) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out)["error"] == "invalid_arguments"
    assert "hidden-test-value" not in captured.out + captured.err


def test_cli_rejects_unverified_source(cli, tmp_path, capsys):
    assert cli.main(["--source-dir", str(tmp_path), "--output-dir", str(tmp_path / "new")]) == 3
    assert json.loads(capsys.readouterr().out)["error"] == "calculation_not_verified"
    assert not (tmp_path / "new").exists()


def test_cli_does_not_print_runtime_exception_details(cli, tmp_path, monkeypatch, capsys):
    def fail(*args):
        raise OSError("sensitive-test-value")
    monkeypatch.setattr(cli, "evaluate_synthetic_package", fail)
    assert cli.main(["--source-dir", str(tmp_path), "--output-dir", str(tmp_path / "new")]) == 4
    captured = capsys.readouterr()
    assert "sensitive-test-value" not in captured.out + captured.err


def test_cli_success_status_does_not_mean_clinical_pass(cli, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "evaluate_synthetic_package", lambda *args: {"status": "passed", "clinical_status": "not_assessable"})
    assert cli.main(["--source-dir", str(tmp_path), "--output-dir", str(tmp_path / "new")]) == 0
    assert json.loads(capsys.readouterr().out)["clinical_status"] == "not_assessable"
