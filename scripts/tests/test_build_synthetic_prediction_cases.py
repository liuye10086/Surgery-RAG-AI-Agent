import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def cli():
    script = Path(__file__).resolve().parents[1] / "build_synthetic_prediction_cases.py"
    spec = importlib.util.spec_from_file_location("synthetic_cases_cli", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_small_run_retains_diagnosis_and_returns_non_success(cli, tmp_path, capsys):
    output = tmp_path / "small"
    assert cli.main(["--output-dir", str(output), "--patients-per-disease", "3",
                     "--challenge-per-disease", "1"]) == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "not_assessable"
    assert payload["counts"]["patients"] == 6
    assert (output / "quality_report.json").is_file()


def test_default_run_passes_quality_and_writes_all_nine_files(cli, tmp_path, capsys):
    output = tmp_path / "default"
    assert cli.main(["--output-dir", str(output)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "passed"
    assert payload["counts"]["patients"] == 240
    assert payload["counts"]["prediction_inputs"] == 480
    assert len(list(output.iterdir())) == 9


@pytest.mark.parametrize("extra", [["--seed", "-1"], ["--seed", "secret-invalid-value"],
                                   ["--challenge-per-disease", "0"], ["--unknown", "secret"]])
def test_bad_parameters_fail_with_safe_error(cli, tmp_path, capsys, extra):
    assert cli.main(["--output-dir", str(tmp_path / "new"), *extra]) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out)["error"] == "invalid_arguments"
    assert "secret" not in captured.out + captured.err
    assert not (tmp_path / "new").exists()


def test_existing_output_is_usage_error(cli, tmp_path, capsys):
    assert cli.main(["--output-dir", str(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "output_exists"


def test_runtime_error_does_not_expose_details(cli, tmp_path, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise OSError("private-path-or-secret")
    monkeypatch.setattr(cli, "export_synthetic_cases", fail)
    assert cli.main(["--output-dir", str(tmp_path / "new")]) == 4
    captured = capsys.readouterr()
    assert json.loads(captured.out)["error"] == "generation_runtime_error"
    assert "private-path" not in captured.out + captured.err
