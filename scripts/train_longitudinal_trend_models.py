"""Candidate-only orchestration for next-visit trend direction models."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for path in (ROOT, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services.longitudinal_group_split import read_disease_group_splits
from app.services.longitudinal_trend_training import (
    TREND_CONTRACTS,
    TrendTrainingError,
    build_trend_rows,
    train_trend_candidate,
    write_trend_candidate_bundle,
)


def run_training(
    *,
    timelines_by_disease: dict[str, list[Any]],
    dataset_input: Any,
    dataset_dir: Path,
    output_dir: Path,
    disease: str,
    seed: int = 42,
) -> dict[str, object]:
    if disease not in {"fatty_liver", "ad"}:
        raise TrendTrainingError("unsupported_disease")
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(output)
    output.mkdir(parents=True, exist_ok=True)
    splits = read_disease_group_splits(dataset_dir)
    try:
        split = splits[disease]
    except KeyError as exc:
        raise TrendTrainingError("disease_split_missing") from exc
    timelines = timelines_by_disease.get(disease, [])
    models: dict[str, dict[str, object]] = {}
    for (contract_disease, indicator), contract in sorted(
        TREND_CONTRACTS.items()
    ):
        if contract_disease != disease:
            continue
        try:
            rows = build_trend_rows(timelines, contract, split)
            candidate = train_trend_candidate(
                rows,
                contract,
                split,
                dataset_input,
                output / ".fit",
                seed=seed,
            )
            bundle = write_trend_candidate_bundle(candidate, output)
        except TrendTrainingError as exc:
            models[indicator] = {
                "status": "not_estimable",
                "reason_code": str(exc),
            }
            continue
        models[indicator] = {
            "status": "candidate",
            "bundle": bundle.bundle_dir.name,
            "model": bundle.model_path.name,
            "metadata": bundle.metadata_path.name,
            "evaluation": bundle.evaluation_path.name,
            "model_id": bundle.metadata.model_contract.model_id,
            "artifact_sha256": bundle.metadata.model_contract.artifact_sha256,
            "evaluation_sha256": bundle.metadata.evaluation_sha256,
            "split_sha256": bundle.metadata.split_sha256,
        }
    fit_dir = output / ".fit"
    if fit_dir.is_dir() and not any(fit_dir.iterdir()):
        fit_dir.rmdir()
    return {
        "schema_version": "longitudinal_model_artifact.v2",
        "status": "candidate",
        "disease": disease,
        "models": models,
    }
