import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
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


def test_training_summary_contains_only_candidate_bundles(cli, monkeypatch, tmp_path):
    class Bundle:
        def __init__(self, task):
            self.bundle_dir = tmp_path / "out" / task.replace(".", "_")
            self.model_path = self.bundle_dir / "model.joblib"
            self.metadata_path = self.bundle_dir / "model.meta.json"
            self.evaluation_path = self.bundle_dir / "model.evaluation.json"
            self.metadata = SimpleNamespace(
                model_contract=SimpleNamespace(
                    model_id=f"{task}-model",
                    model_version="2026.08.26.1",
                    artifact_sha256="a" * 64,
                ),
                evaluation_sha256="b" * 64,
                split_sha256="c" * 64,
            )

    monkeypatch.setattr(cli, "read_dataset_manifest", lambda _: object())
    monkeypatch.setattr(
        cli,
        "read_disease_group_splits",
        lambda _: {
            "fatty_liver": SimpleNamespace(disease="fatty_liver"),
            "ad": SimpleNamespace(disease="ad"),
        },
    )
    monkeypatch.setattr(cli, "read_real_train_samples", lambda *_: [object()])
    monkeypatch.setattr(cli, "select_task_samples", lambda samples, task: [task])
    def fake_train(*args, **kwargs):
        fit_dir = Path(args[4])
        fit_dir.mkdir(parents=True, exist_ok=True)
        (fit_dir / f"{args[1].task}.joblib").write_bytes(b"intermediate")
        return SimpleNamespace(task=args[1])

    monkeypatch.setattr(cli, "train_outcome_task", fake_train)
    monkeypatch.setattr(
        cli,
        "write_outcome_candidate_bundle",
        lambda result, root: Bundle(result.task.task),
    )

    payload = cli.run_training(tmp_path / "dataset", tmp_path / "out")
    assert payload["status"] == "candidate"
    assert set(payload["tasks"]) == set(cli.TASK_SPECS)
    assert all(item["status"] == "candidate" for item in payload["tasks"].values())
    assert not list((tmp_path / "out").rglob("review*.json"))
    assert not list((tmp_path / "out").rglob("release*.json"))
    assert not (tmp_path / "out" / ".fit").exists()


def test_training_uses_disease_splits_and_writes_v2_evaluation(cli, monkeypatch, tmp_path):
    splits = {
        "fatty_liver": SimpleNamespace(disease="fatty_liver", sha256="a" * 64),
        "ad": SimpleNamespace(disease="ad", sha256="b" * 64),
    }
    calls = []

    class Bundle:
        def __init__(self, task):
            self.bundle_dir = tmp_path / "out" / task.replace(".", "_")
            self.model_path = self.bundle_dir / "model.joblib"
            self.metadata_path = self.bundle_dir / "model.meta.json"
            self.evaluation_path = self.bundle_dir / "model.evaluation.json"
            self.metadata = SimpleNamespace(
                model_contract=SimpleNamespace(
                    model_id=f"{task}-model",
                    model_version="2026.08.27.1",
                    artifact_sha256="c" * 64,
                ),
                split_sha256=splits[task.split(".", 1)[0]].sha256,
                evaluation_sha256="d" * 64,
            )

    monkeypatch.setattr(cli, "read_dataset_manifest", lambda _: object())
    monkeypatch.setattr(cli, "read_disease_group_splits", lambda _: splits)
    monkeypatch.setattr(cli, "read_real_train_samples", lambda *_: [object()])
    monkeypatch.setattr(cli, "select_task_samples", lambda samples, task: [task])

    def fake_train(rows, task, split, dataset, output_dir, **kwargs):
        calls.append((task.task, split.disease))
        return SimpleNamespace(task=task)

    monkeypatch.setattr(cli, "train_outcome_task", fake_train)
    monkeypatch.setattr(
        cli,
        "write_outcome_candidate_bundle",
        lambda candidate, root: Bundle(candidate.task.task),
    )

    payload = cli.run_training(tmp_path / "dataset", tmp_path / "out")

    assert payload["schema_version"] == "longitudinal_model_artifact.v2"
    assert calls == [
        (task_name, task.disease) for task_name, task in cli.TASK_SPECS.items()
    ]
    assert all("evaluation" in item for item in payload["tasks"].values())
    assert all("split_sha256" in item for item in payload["tasks"].values())
    assert not list((tmp_path / "out").rglob("review*.json"))
    assert not list((tmp_path / "out").rglob("release*.json"))
    assert not list((tmp_path / "out").rglob("active*.json"))
