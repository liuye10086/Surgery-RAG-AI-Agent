import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def cli():
    path = ROOT / "scripts" / "train_longitudinal_outcome_models.py"
    spec = importlib.util.spec_from_file_location("p004_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_cli_is_audit_only_and_does_not_train(cli, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "run_audit", lambda dataset_dir: {"status": "audit_only"})
    monkeypatch.setattr(cli, "run_training", lambda *args, **kwargs: pytest.fail("training called"))
    assert cli.main(["--dataset-dir", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "audit_only"


def test_training_requires_train_and_output_dir(cli, tmp_path, capsys):
    assert cli.main(["--dataset-dir", str(tmp_path), "--train"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "output_dir_required"


def test_cli_sanitizes_errors(cli, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "run_audit", lambda dataset_dir: (_ for _ in ()).throw(ValueError("P001 password postgresql://secret")))
    assert cli.main(["--dataset-dir", str(tmp_path)]) == 2
    output = capsys.readouterr().out
    assert all(secret not in output for secret in ("P001", "password", "postgresql://", "Traceback"))


def test_cli_never_auto_enables_registry(cli, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "run_training", lambda *args, **kwargs: {"status": "candidate"})
    assert cli.main(["--dataset-dir", str(tmp_path), "--train", "--output-dir", str(tmp_path / "out")]) == 0
