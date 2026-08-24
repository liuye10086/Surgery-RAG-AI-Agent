"""Build leakage-safe prefix training rows and grouped CV helpers."""

from __future__ import annotations

import math
import sys
from datetime import date, timedelta
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for path in (ROOT, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.services.disease_progression import DiseaseProgressionAdapter
from app.services.longitudinal_features import build_prefixes, summarize_observation


@dataclass(frozen=True)
class CVFold:
    train_groups: list[str]
    validation_groups: list[str]
    train_indices: list[int]
    validation_indices: list[int]


def build_prefix_training_rows(
    patient_visits: dict[str, list[dict[str, Any]]],
    adapter: DiseaseProgressionAdapter,
    horizon: timedelta = timedelta(days=365),
) -> dict[str, Any]:
    rows: list[list[float]] = []
    labels: list[int] = []
    groups: list[str] = []
    as_of_dates: list[str] = []
    feature_names: list[str] = []
    staged: list[tuple[str, dict[str, Any], int | None, str | None]] = []
    for patient_id, patient_input in sorted(patient_visits.items()):
        if isinstance(patient_input, dict):
            patient = dict(patient_input)
            visits = patient.get("visits") or []
        else:
            visits = patient_input
            patient = visits[0].get("patient", {}) if visits else {}
        for prefix in build_prefixes(visits, adapter.minimum_visits):
            as_of = date.fromisoformat(prefix["as_of"])
            label = adapter.outcome_label(patient, as_of, horizon)
            stage = adapter.stage_label(patient, as_of)
            staged.append((patient_id, prefix, label, stage))
            summary = summarize_observation(prefix["visits"])["indicators"]
            for name in summary:
                for stat in ("first", "last", "delta", "delta_pct", "slope", "rises_count", "n_observations"):
                    if f"{name}.{stat}" not in feature_names:
                        feature_names.append(f"{name}.{stat}")
    feature_names.sort()
    stage_labels: list[str | None] = []
    for patient_id, prefix, label, stage in staged:
        if label is None:
            continue
        summary = summarize_observation(prefix["visits"])["indicators"]
        rows.append([float(summary.get(name.split(".")[0], {}).get(name.split(".")[1])) if summary.get(name.split(".")[0], {}).get(name.split(".")[1]) is not None else math.nan for name in feature_names])
        labels.append(label)
        groups.append(patient_id)
        as_of_dates.append(prefix["as_of"])
        stage_labels.append(stage)
    return {"rows": rows, "labels": labels, "stage_labels": stage_labels, "groups": groups, "as_of_dates": as_of_dates, "feature_names": feature_names}


def patient_grouped_cv(rows, labels, groups, estimator_factory: Callable[[], Any], n_splits: int = 5):
    from sklearn.model_selection import GroupKFold

    if len(set(groups)) < n_splits:
        raise ValueError("patient groups are fewer than requested folds")
    folds = []
    for train, validation in GroupKFold(n_splits=n_splits).split(rows, labels, groups):
        model = estimator_factory()
        model.fit([rows[i] for i in train], [labels[i] for i in train])
        folds.append(CVFold(
            train_groups=sorted({groups[i] for i in train}),
            validation_groups=sorted({groups[i] for i in validation}),
            train_indices=train.tolist(),
            validation_indices=validation.tolist(),
        ))
    return folds
