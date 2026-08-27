from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def cli():
    path = ROOT / "scripts" / "train_longitudinal_model_suite.py"
    spec = importlib.util.spec_from_file_location("suite_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("suite_cli_missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_cli_is_audit_only(cli, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        cli,
        "run_audit",
        lambda dataset_dir, disease: {"status": "audit_only", "disease": disease},
    )
    monkeypatch.setattr(
        cli,
        "run_training",
        lambda *args, **kwargs: pytest.fail("training called without --train"),
    )

    assert cli.main(["--dataset-dir", str(tmp_path), "--disease", "all"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "audit_only"


def test_suite_cli_refuses_nonempty_output(cli, tmp_path, capsys):
    output = tmp_path / "candidate"
    output.mkdir()
    (output / "existing").write_text("keep", encoding="utf-8")

    assert cli.main([
        "--train", "--dataset-dir", str(tmp_path / "dataset"),
        "--output-dir", str(output), "--disease", "ad",
    ]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "output_exists"
    assert (output / "existing").read_text(encoding="utf-8") == "keep"


def test_training_writes_candidate_sets_without_release_side_effects(cli, monkeypatch, tmp_path):
    dataset = SimpleNamespace(
        manifest_sha256="a" * 64,
        data_content_sha256="b" * 64,
        group_split_sha256="c" * 64,
        run_id="dataset-test",
    )
    monkeypatch.setattr(cli, "read_dataset_manifest", lambda _: dataset)
    monkeypatch.setattr(
        cli,
        "read_disease_group_splits",
        lambda _: {
            "fatty_liver": SimpleNamespace(disease="fatty_liver", sha256="d" * 64),
            "ad": SimpleNamespace(disease="ad", sha256="e" * 64),
        },
    )
    monkeypatch.setattr(
        cli,
        "read_training_timelines",
        lambda *_: [SimpleNamespace(group_id="patient.v1." + "1" * 64)],
    )
    monkeypatch.setattr(
        cli,
        "train_disease_suite",
        lambda **kwargs: {
            "status": "candidate",
            "bundles": [
                {
                    "task": f"{kwargs['disease']}.next_stage",
                    "artifact_type": "stage",
                    "model_path": f"bundles/{kwargs['disease']}/model.joblib",
                    "metadata_path": f"bundles/{kwargs['disease']}/model.meta.json",
                    "evaluation_path": f"bundles/{kwargs['disease']}/model.evaluation.json",
                    "model_sha256": "f" * 64,
                    "metadata_sha256": "1" * 64,
                    "evaluation_sha256": "2" * 64,
                }
            ],
            "models": {},
        },
    )

    output = tmp_path / "candidate"
    payload = cli.run_training(
        tmp_path / "dataset", output, disease="all", seed=42
    )

    assert payload["status"] == "candidate"
    for disease in ("fatty_liver", "ad"):
        manifests = list((output / disease).glob("*.candidate-set.json"))
        assert len(manifests) == 1
        candidate = json.loads(manifests[0].read_text(encoding="utf-8"))
        assert candidate["dataset"] == disease
        assert candidate["production_enabled"] is False
        for item in candidate["bundles"]:
            for field in (
                "model_path",
                "metadata_path",
                "evaluation_path",
                "manifest_path",
            ):
                assert not Path(item[field]).is_absolute()
    assert not list(output.rglob("review-*.json"))
    assert not list(output.rglob("release-*.json"))
    assert not list(output.rglob("active/*.json"))


def test_cli_rejects_enable_flag(cli):
    with pytest.raises(SystemExit):
        cli.main(["--enable"])


def test_timeline_training_scope_is_exactly_the_shared_disease_split(cli):
    split = SimpleNamespace(
        assignments=lambda: {
            "patient.v1." + "1" * 64: "development_train",
            "patient.v1." + "2" * 64: "locked_test",
        }
    )
    timelines = [
        SimpleNamespace(group_id="patient.v1." + value * 64)
        for value in ("1", "2", "3")
    ]

    scoped = cli.timelines_for_split(timelines, split)

    assert [item.group_id for item in scoped] == [
        "patient.v1." + "1" * 64,
        "patient.v1." + "2" * 64,
    ]


def test_demonstration_dataset_selects_explicit_training_files(cli):
    dataset = SimpleNamespace(
        training_profile="synthetic_demonstration",
        training_file_by_disease={
            "fatty_liver": "fatty_liver/demonstration_train.jsonl",
            "ad": "ad/demonstration_train.jsonl",
        },
        timeline_file_by_disease={
            "fatty_liver": "fatty_liver/demonstration_timelines.jsonl",
            "ad": "ad/demonstration_timelines.jsonl",
        },
    )

    assert cli.training_file_for(dataset, "ad") == "ad/demonstration_train.jsonl"
    assert cli.timeline_file_for(dataset, "ad") == "ad/demonstration_timelines.jsonl"


def test_real_dataset_keeps_legacy_training_file_names(cli):
    dataset = SimpleNamespace(
        training_profile="real_only",
        training_file_by_disease={},
        timeline_file_by_disease={},
    )

    assert cli.training_file_for(dataset, "ad") == "ad/real_train.jsonl"
    assert cli.timeline_file_for(dataset, "ad") == "ad/real_timelines.jsonl"
