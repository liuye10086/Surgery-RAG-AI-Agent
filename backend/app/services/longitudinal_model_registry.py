"""Optional loaders for trained longitudinal outcome and trend artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib

from app.services.progression_engine import MODEL_DIR


def _load_pair(model_path: Path, meta_path: Path) -> dict[str, Any] | None:
    if not model_path.is_file() or not meta_path.is_file():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return {"model": joblib.load(model_path), "meta": meta}


def load_model_registry(dataset: str, model_dir: Path | str = MODEL_DIR) -> dict[str, Any]:
    """Load optional artifacts; absent artifacts use an explicit fallback.

    The service never reuses the legacy single-timepoint model because its
    feature contract differs from the longitudinal prefix model.
    """
    directory = Path(model_dir)
    registry: dict[str, Any] = {}
    outcome = _load_pair(
        directory / f"{dataset}_longitudinal_outcome_365d.joblib",
        directory / f"{dataset}_longitudinal_outcome_365d.meta.json",
    )
    if outcome is not None:
        registry["outcome"] = outcome

    for model_path in sorted(directory.glob(f"{dataset}_trend_*.joblib")):
        indicator = model_path.stem.removeprefix(f"{dataset}_trend_")
        pair = _load_pair(model_path, model_path.with_suffix(".meta.json"))
        if pair is not None:
            registry.setdefault("trends", {})[indicator.lower()] = pair
    return registry
