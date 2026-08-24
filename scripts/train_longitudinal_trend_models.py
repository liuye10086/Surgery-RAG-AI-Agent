"""Helpers for training next-observed-direction models."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for path in (ROOT, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services.disease_progression import derive_next_visit_direction
from app.services.longitudinal_features import sort_visits


def build_trend_training_rows(patient_visits: dict[str, list[dict[str, Any]]], indicator: str, tolerance: float = 0.05) -> dict[str, list[Any]]:
    rows, labels, groups = [], [], []
    for patient_id, visits in sorted(patient_visits.items()):
        ordered = sort_visits(visits)
        for current, following in zip(ordered, ordered[1:]):
            current_value = next((item.get("value") for item in current.get("indicators", []) if str(item.get("name", "")).lower() == indicator.lower()), None)
            next_value = next((item.get("value") for item in following.get("indicators", []) if str(item.get("name", "")).lower() == indicator.lower()), None)
            if current_value is None or next_value is None:
                continue
            labels.append(derive_next_visit_direction(float(current_value), float(next_value), tolerance))
            rows.append([float(current_value)])
            groups.append(patient_id)
    return {"rows": rows, "labels": labels, "groups": groups}
