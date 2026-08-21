"""Train longitudinal progression models from imported case records."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.progression_engine import extract_features


DATASETS = {
    "fatty_liver": {
        "disease_name": "脂肪肝",
        "source_dataset": "longitudinal_300",
    },
    "ad": {
        "disease_name": "阿尔茨海默病",
        "source_dataset": "ad_longitudinal_300",
    },
}

FEATURE_STATS = (
    "first",
    "last",
    "delta",
    "delta_pct",
    "slope",
    "rises_count",
    "n_observations",
)
DEFAULT_OUT_DIR = ROOT / "backend" / "app" / "ml_models"


def load_all_patients(db, dataset: str) -> dict[str, list[dict]]:
    """Load all P001-P300 visits, including synthetic cases, for one dataset."""
    from app.db.models import CaseRecord, Disease

    try:
        config = DATASETS[dataset]
    except KeyError as exc:
        raise ValueError(f"Unsupported dataset: {dataset}") from exc

    records = (
        db.query(CaseRecord)
        .join(Disease, CaseRecord.disease_id == Disease.id)
        .filter(Disease.name == config["disease_name"])
        .all()
    )
    patients: dict[str, list[dict]] = {}
    for record in records:
        metadata = record.case_metadata or {}
        if metadata.get("source_dataset") != config["source_dataset"]:
            continue
        patient_id = (record.patient_label or "").strip()
        if not patient_id:
            continue
        patients.setdefault(patient_id, []).append(
            {
                "visit_date": metadata.get("visit_date"),
                "indicators": record.indicators or [],
                "confirmed": bool(record.confirmed),
            }
        )

    return {
        patient_id: sorted(
            patients[patient_id],
            key=lambda visit: str(visit.get("visit_date") or ""),
        )
        for patient_id in sorted(patients)
    }


def build_training_rows(
    patients_visits: dict[str, list[dict]],
    dataset: str | None = None,
) -> tuple[list[list[float]], list[int], list[str], list[str]]:
    """Aggregate visits into one ordered feature vector and label per patient."""
    extracted_by_patient = {
        patient_id: extract_features(visits)
        for patient_id, visits in patients_visits.items()
    }
    indicator_names = sorted(
        {
            indicator_name
            for features in extracted_by_patient.values()
            for indicator_name in features
            if not (dataset == "ad" and indicator_name == "cdr")
        }
    )
    feature_names = [
        f"{indicator_name}.{stat}"
        for indicator_name in indicator_names
        for stat in FEATURE_STATS
    ]

    rows: list[list[float]] = []
    labels: list[int] = []
    patient_ids: list[str] = []
    for patient_id in sorted(patients_visits):
        visits = sorted(
            patients_visits[patient_id],
            key=lambda visit: str(visit.get("visit_date") or ""),
        )
        if not visits:
            continue
        patient_features = extracted_by_patient[patient_id]
        row = []
        for feature_name in feature_names:
            indicator_name, stat = feature_name.rsplit(".", 1)
            value = patient_features.get(indicator_name, {}).get(stat)
            row.append(float(value) if value is not None else math.nan)
        rows.append(row)
        labels.append(int(bool(visits[-1].get("confirmed"))))
        patient_ids.append(patient_id)

    return rows, labels, patient_ids, feature_names


def _make_model():
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline

    return Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("classifier", GradientBoostingClassifier(random_state=42)),
        ]
    )


def patient_kfold_cv(
    rows: list[list[float]],
    labels: list[int],
    patient_ids: list[str],
    k: int = 5,
) -> list[dict[str, Any]]:
    """Run GroupKFold CV and expose fold indices to make leakage auditable."""
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold

    if not (len(rows) == len(labels) == len(patient_ids)):
        raise ValueError("rows, labels, and patient_ids must have equal lengths")
    if len(set(patient_ids)) < k:
        raise ValueError(f"GroupKFold requires at least {k} distinct patients")

    splitter = GroupKFold(n_splits=k, shuffle=True, random_state=42)
    fold_results = []
    for fold_number, (train_indices, validation_indices) in enumerate(
        splitter.split(rows, labels, groups=patient_ids),
        start=1,
    ):
        train_indices_list = train_indices.tolist()
        validation_indices_list = validation_indices.tolist()
        model = _make_model()
        model.fit(
            [rows[index] for index in train_indices_list],
            [labels[index] for index in train_indices_list],
        )
        probabilities = model.predict_proba(
            [rows[index] for index in validation_indices_list]
        )[:, 1]
        auc = float(
            roc_auc_score(
                [labels[index] for index in validation_indices_list],
                probabilities,
            )
        )
        fold_results.append(
            {
                "fold": fold_number,
                "auc": auc,
                "train_indices": train_indices_list,
                "validation_indices": validation_indices_list,
            }
        )
    return fold_results


def train_and_save(dataset: str, db_url: str | None, out_dir: str | Path) -> dict:
    """Train one dataset on all 300 patients and write model plus metadata."""
    import joblib
    import sklearn
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.config import settings

    if dataset not in DATASETS:
        raise ValueError(f"Unsupported dataset: {dataset}")
    engine = create_engine(db_url or settings.DATABASE_URL, future=True)
    db = sessionmaker(bind=engine, future=True)()
    try:
        patients = load_all_patients(db, dataset)
    finally:
        db.close()
        engine.dispose()

    rows, labels, patient_ids, feature_names = build_training_rows(
        patients,
        dataset=dataset,
    )
    if len(set(patient_ids)) != 300:
        raise ValueError(
            f"{dataset} expected 300 patients (P001-P300), got "
            f"{len(set(patient_ids))}"
        )
    if set(labels) != {0, 1}:
        raise ValueError(f"{dataset} training labels must contain both classes")

    fold_results = patient_kfold_cv(rows, labels, patient_ids, k=5)
    cv_scores = [fold["auc"] for fold in fold_results]
    model = _make_model()
    model.fit(rows, labels)

    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{dataset}_progression_model"
    model_path = output_dir / f"{stem}.joblib"
    meta_path = output_dir / f"{stem}.meta.json"
    joblib.dump(model, model_path)

    metadata = {
        "dataset": dataset,
        "disease_name": DATASETS[dataset]["disease_name"],
        "feature_names": feature_names,
        "trained_on": len(set(patient_ids)),
        "cv_auc_scores": cv_scores,
        "cv_auc_mean": statistics.mean(cv_scores),
        "cv_auc_std": statistics.pstdev(cv_scores),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "sklearn_version": sklearn.__version__,
    }
    meta_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {**metadata, "model_path": str(model_path), "meta_path": str(meta_path)}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        choices=["fatty_liver", "ad", "all"],
        default="all",
    )
    parser.add_argument("--db-url")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    datasets = DATASETS if args.dataset == "all" else (args.dataset,)
    for dataset in datasets:
        result = train_and_save(dataset, args.db_url, args.out_dir)
        print(f"[{dataset}] patient-level GroupKFold AUC")
        for fold, auc in enumerate(result["cv_auc_scores"], start=1):
            print(f"  fold {fold}: {auc:.4f}")
        print(
            f"  mean +/- std: {result['cv_auc_mean']:.4f} +/- "
            f"{result['cv_auc_std']:.4f}"
        )
        print(f"  trained_on: {result['trained_on']}")
        print(f"  model: {result['model_path']}")
        print(f"  metadata: {result['meta_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
