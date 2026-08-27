from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def cli():
    path = ROOT / "scripts" / "train_longitudinal_trend_models.py"
    spec = importlib.util.spec_from_file_location("trend_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_training_orchestrator_writes_candidates_and_records_unestimable(
    cli, monkeypatch, tmp_path
):
    contracts = {
        ("ad", "mmse"): SimpleNamespace(disease="ad", indicator="mmse"),
        ("ad", "moca"): SimpleNamespace(disease="ad", indicator="moca"),
    }
    split = SimpleNamespace(disease="ad", sha256="a" * 64)
    monkeypatch.setattr(cli, "TREND_CONTRACTS", contracts)
    monkeypatch.setattr(
        cli, "read_disease_group_splits", lambda _: {"ad": split}
    )
    monkeypatch.setattr(cli, "build_trend_rows", lambda *args: [args[1].indicator])

    def train(rows, contract, *args, **kwargs):
        if contract.indicator == "moca":
            raise cli.TrendTrainingError("trend_class_support_insufficient")
        return SimpleNamespace(contract=contract)

    monkeypatch.setattr(cli, "train_trend_candidate", train)
    monkeypatch.setattr(
        cli,
        "write_trend_candidate_bundle",
        lambda candidate, root: SimpleNamespace(
            bundle_dir=root / "ad_next_visit_trend_mmse",
            model_path=root / "model.joblib",
            metadata_path=root / "model.meta.json",
            evaluation_path=root / "model.evaluation.json",
            metadata=SimpleNamespace(
                model_contract=SimpleNamespace(
                    model_id="ad-mmse-model",
                    artifact_sha256="b" * 64,
                ),
                evaluation_sha256="c" * 64,
                split_sha256="a" * 64,
            ),
        ),
    )

    payload = cli.run_training(
        timelines_by_disease={"ad": [object()]},
        dataset_input=object(),
        dataset_dir=tmp_path / "dataset",
        output_dir=tmp_path / "output",
        disease="ad",
        seed=42,
    )

    assert payload["status"] == "candidate"
    assert payload["models"]["mmse"]["status"] == "candidate"
    assert payload["models"]["moca"] == {
        "status": "not_estimable",
        "reason_code": "trend_class_support_insufficient",
    }
    assert not list((tmp_path / "output").rglob("review*.json"))
    assert not list((tmp_path / "output").rglob("release*.json"))
    assert not list((tmp_path / "output").rglob("active*.json"))


def test_legacy_single_value_builder_is_not_exposed(cli):
    assert not hasattr(cli, "build_trend_training_rows")
