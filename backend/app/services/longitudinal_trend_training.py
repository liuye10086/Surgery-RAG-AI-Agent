"""Audited next-visit direction rows and candidate contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import sys
from pathlib import Path
from typing import Any, Literal, Sequence

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from app.schemas.longitudinal_model_registry import feature_order_sha256
from app.schemas.longitudinal_model_suite import (
    ArtifactMetadataV2,
    EvaluationArtifact,
    MulticlassMetrics,
)
from app.services.longitudinal_dataset import PatientTimeline
from app.services.longitudinal_features import summarize_fixed_window_history
from app.services.longitudinal_group_split import DiseaseGroupSplit, PartitionName
from app.services.longitudinal_model_evaluation import compute_multiclass_metrics


class TrendTrainingError(ValueError):
    """Stable, privacy-safe trend training error."""


@dataclass(frozen=True)
class TrendContract:
    disease: Literal["fatty_liver", "ad"]
    indicator: str
    tolerance: float
    tolerance_version: str = "relative_tolerance.v1"
    class_order: tuple[str, str, str] = ("rising", "stable", "falling")
    unit_policy: str = "source_unit_consistent"
    minimum_patient_support_per_class: int = 1


@dataclass(frozen=True)
class TrendTrainingRow:
    disease: str
    indicator: str
    group_id: str
    partition: PartitionName
    as_of: date
    max_feature_date: date
    label_visit_date: date
    label: str
    features: dict[str, Any]


@dataclass(frozen=True)
class TrendFeatureCatalog:
    feature_names: tuple[str, ...]
    numeric_features: tuple[str, ...]
    categorical_features: tuple[str, ...]


@dataclass(frozen=True)
class TrainedTrendCandidate:
    contract: TrendContract
    task: str
    model: Any
    model_name: str
    catalog: TrendFeatureCatalog
    split: DiseaseGroupSplit
    dataset_input: Any
    evaluation: EvaluationArtifact
    locked_test_metrics: MulticlassMetrics
    selection_trace: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True)
class TrendCandidateBundleResult:
    bundle_dir: Path
    model_path: Path
    metadata_path: Path
    evaluation_path: Path
    metadata: ArtifactMetadataV2
    evaluation: EvaluationArtifact


TREND_CONTRACTS = {
    (disease, indicator): TrendContract(disease, indicator, 0.05)
    for disease, indicators in {
        "fatty_liver": ("alt", "ast", "ggt", "tbil", "alb", "plt", "afp"),
        "ad": ("mmse", "moca", "cdr", "plasma_nfl", "plasma_ptau217"),
    }.items()
    for indicator in indicators
}


def direction_label(current: float, following: float, tolerance: float) -> str:
    if tolerance < 0:
        raise TrendTrainingError("invalid_tolerance")
    if current == 0:
        delta = following - current
        if abs(delta) <= tolerance:
            return "stable"
        return "rising" if delta > 0 else "falling"
    relative = (following - current) / abs(current)
    if relative > tolerance:
        return "rising"
    if relative < -tolerance:
        return "falling"
    return "stable"


def _visit_dict(visit) -> dict[str, object]:
    return {
        "visit_date": visit.visit_date.isoformat(),
        "indicators": [dict(value) for value in visit.indicators],
    }


def _indicator_value(visit, indicator: str) -> float | None:
    for value in visit.indicators:
        if str(value.get("name", "")).strip().lower() == indicator:
            try:
                return float(value.get("value"))
            except (TypeError, ValueError):
                return None
    return None


def build_trend_rows(
    timelines: Sequence[PatientTimeline],
    contract: TrendContract,
    split: DiseaseGroupSplit,
    *,
    allow_synthetic: bool = False,
) -> list[TrendTrainingRow]:
    if split.disease != contract.disease:
        raise TrendTrainingError("split_disease_mismatch")
    assignments = split.assignments()
    rows: list[TrendTrainingRow] = []
    for patient in sorted(timelines, key=lambda value: value.group_id):
        if patient.adapter.dataset != contract.disease or (
            patient.is_synthetic and not allow_synthetic
        ):
            continue
        try:
            partition = assignments[patient.group_id]
        except KeyError as exc:
            raise TrendTrainingError("patient_group_missing_from_split") from exc
        for next_index in range(3, len(patient.visits)):
            prefix = patient.visits[:next_index]
            following = patient.visits[next_index]
            current_value = _indicator_value(prefix[-1], contract.indicator)
            next_value = _indicator_value(following, contract.indicator)
            if current_value is None or next_value is None:
                continue
            history = summarize_fixed_window_history(
                [_visit_dict(visit) for visit in prefix]
            )
            features: dict[str, Any] = {
                "visit_count": history["visit_count"],
                "observation_span_days": history["observation_span_days"],
                "days_since_previous_visit": history["days_since_previous_visit"],
            }
            for name, summary in history["indicators"].items():
                for statistic, value in summary.items():
                    features[f"{name}.{statistic}"] = value
            rows.append(
                TrendTrainingRow(
                    disease=contract.disease,
                    indicator=contract.indicator,
                    group_id=patient.group_id,
                    partition=partition,
                    as_of=prefix[-1].visit_date,
                    max_feature_date=max(visit.visit_date for visit in prefix),
                    label_visit_date=following.visit_date,
                    label=direction_label(current_value, next_value, contract.tolerance),
                    features=features,
                )
            )
    return rows


def build_trend_feature_catalog(
    rows: Sequence[TrendTrainingRow],
) -> TrendFeatureCatalog:
    names = sorted({name for row in rows for name in row.features})
    if any(name in {"next_value", "label", "label_visit_date"} or "future" in name for name in names):
        raise TrendTrainingError("future_feature_detected")
    categorical = tuple(name for name in names if name == "sex")
    return TrendFeatureCatalog(
        tuple(names), tuple(name for name in names if name not in categorical), categorical
    )


def _frame(rows: Sequence[TrendTrainingRow], catalog: TrendFeatureCatalog):
    import pandas as pd

    return pd.DataFrame(
        [
            {name: row.features.get(name) for name in catalog.feature_names}
            for row in rows
        ]
    )


def _preprocessor(catalog: TrendFeatureCatalog, *, scale_numeric: bool):
    numeric_steps = [
        (
            "imputer",
            SimpleImputer(
                strategy="median", add_indicator=True, keep_empty_features=True
            ),
        )
    ]
    if scale_numeric:
        numeric_steps.append(("scaler", StandardScaler()))
    transformers = []
    if catalog.numeric_features:
        transformers.append(
            (
                "numeric",
                Pipeline(numeric_steps),
                list(catalog.numeric_features),
            )
        )
    if catalog.categorical_features:
        transformers.append(
            (
                "categorical",
                Pipeline(
                    [
                        (
                            "imputer",
                            SimpleImputer(strategy="most_frequent"),
                        ),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                list(catalog.categorical_features),
            )
        )
    return ColumnTransformer(transformers, remainder="drop")


def _candidates(catalog: TrendFeatureCatalog, seed: int):
    return {
        "multinomial_logistic_regression": Pipeline(
            [
                ("preprocess", _preprocessor(catalog, scale_numeric=True)),
                (
                    "classifier",
                    LogisticRegression(
                        max_iter=3000,
                        class_weight="balanced",
                        random_state=seed,
                    ),
                ),
            ]
        ),
        "random_forest": Pipeline(
            [
                ("preprocess", _preprocessor(catalog, scale_numeric=False)),
                (
                    "classifier",
                    RandomForestClassifier(
                        n_estimators=200,
                        max_depth=6,
                        min_samples_leaf=2,
                        class_weight="balanced",
                        random_state=seed,
                        n_jobs=1,
                    ),
                ),
            ]
        ),
    }


def evaluate_trend_locked_test(
    model: Pipeline,
    rows: Sequence[TrendTrainingRow],
    catalog: TrendFeatureCatalog,
    class_order: Sequence[str],
) -> MulticlassMetrics:
    return compute_multiclass_metrics(
        [row.label for row in rows],
        model.predict(_frame(rows, catalog)).tolist(),
        class_order,
    )


def train_trend_candidate(
    rows: Sequence[TrendTrainingRow],
    contract: TrendContract,
    split: DiseaseGroupSplit,
    dataset_input,
    output_dir,
    *,
    seed: int = 42,
):
    if {row.label for row in rows} != set(contract.class_order):
        raise TrendTrainingError("trend_class_support_insufficient")
    for partition in ("development_train", "development_validation", "locked_test"):
        scoped = [row for row in rows if row.partition == partition]
        if set(row.label for row in scoped) != set(contract.class_order):
            raise TrendTrainingError("trend_class_support_insufficient")
    if split.disease != contract.disease:
        raise TrendTrainingError("split_disease_mismatch")
    assignments = split.assignments()
    if any(assignments.get(row.group_id) != row.partition for row in rows):
        raise TrendTrainingError("trend_partition_mismatch")
    if dataset_input is None:
        raise TrendTrainingError("dataset_input_required")
    training = [row for row in rows if row.partition == "development_train"]
    validation = [
        row for row in rows if row.partition == "development_validation"
    ]
    locked = [row for row in rows if row.partition == "locked_test"]
    catalog = build_trend_feature_catalog(training)
    candidate_results = []
    for model_name, model in sorted(_candidates(catalog, seed).items()):
        model.fit(_frame(training, catalog), [row.label for row in training])
        metrics = compute_multiclass_metrics(
            [row.label for row in validation],
            model.predict(_frame(validation, catalog)).tolist(),
            contract.class_order,
        )
        candidate_results.append((model_name, metrics))
    selected_name, selected_metrics = max(
        candidate_results,
        key=lambda item: (
            item[1].macro_f1 if item[1].macro_f1 is not None else -1.0,
            item[1].balanced_accuracy
            if item[1].balanced_accuracy is not None
            else -1.0,
            item[0],
        ),
    )
    development = training + validation
    frozen = _candidates(catalog, seed)[selected_name]
    frozen.fit(
        _frame(development, catalog), [row.label for row in development]
    )
    trace = (
        "development_candidates_evaluated",
        "candidate_selected",
        "candidate_frozen",
    )
    locked_metrics = evaluate_trend_locked_test(
        frozen, locked, catalog, contract.class_order
    )
    task = f"{contract.disease}.next_visit_trend.{contract.indicator}"
    training_file = dataset_input.training_file_by_disease.get(
        contract.disease, f"{contract.disease}/real_train.jsonl"
    )
    evaluation = EvaluationArtifact(
        artifact_type="trend",
        task=task,
        dataset=contract.disease,
        dataset_manifest_sha256=dataset_input.manifest_sha256,
        data_content_sha256=dataset_input.data_content_sha256,
        training_file_sha256=dataset_input.file_sha256(training_file),
        split_sha256=split.sha256,
        selection_metrics={
            "primary": "macro_f1",
            "tie_breakers": ["balanced_accuracy", "model_name"],
            "selected_model": selected_name,
            "selected_metrics": selected_metrics.model_dump(mode="json"),
            "selection_trace": list(trace),
            "tolerance": contract.tolerance,
            "tolerance_version": contract.tolerance_version,
        },
        locked_test_metrics=locked_metrics.model_dump(mode="json"),
        baselines={
            "majority_class": max(
                contract.class_order,
                key=lambda value: sum(row.label == value for row in development),
            )
        },
        class_support={
            f"development_{name}": sum(
                row.label == name for row in development
            )
            for name in contract.class_order
        }
        | {
            f"locked_test_{name}": sum(row.label == name for row in locked)
            for name in contract.class_order
        },
        locked_test_used_for_selection=False,
    )
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    return TrainedTrendCandidate(
        contract=contract,
        task=task,
        model=frozen,
        model_name=selected_name,
        catalog=catalog,
        split=split,
        dataset_input=dataset_input,
        evaluation=evaluation,
        locked_test_metrics=locked_metrics,
        selection_trace=trace,
        created_at=datetime.now(timezone.utc),
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metadata(
    candidate: TrainedTrendCandidate,
    model_path: Path,
    evaluation_path: Path,
) -> ArtifactMetadataV2:
    import joblib
    import numpy
    import pandas
    import sklearn

    contract = candidate.contract
    names = list(candidate.catalog.feature_names)
    required = [name for name in ("visit_count",) if name in names]
    stem = f"{contract.disease}_next_visit_trend_{contract.indicator}"
    artifact_hash = _sha256(model_path)
    training_file = candidate.dataset_input.training_file_by_disease.get(
        contract.disease, f"{contract.disease}/real_train.jsonl"
    )
    uses_demonstration = (
        candidate.dataset_input.training_profile == "synthetic_demonstration"
    )
    return ArtifactMetadataV2(
        schema_version="longitudinal_model_artifact.v2",
        artifact_type="trend",
        task=candidate.task,
        dataset=contract.disease,
        target=f"next_visit_direction:{contract.indicator}",
        horizon={"kind": "next_visit", "value": None},
        feature_contract={
            "schema_version": "longitudinal_fixed_window_features.v1",
            "feature_version": "longitudinal_fixed_window_features.v1",
            "feature_names": names,
            "feature_order_sha256": feature_order_sha256(names),
            "numeric_features": list(candidate.catalog.numeric_features),
            "categorical_features": list(candidate.catalog.categorical_features),
            "required_features": required,
            "allowed_missing_features": [
                name for name in names if name not in required
            ],
            "input_container": "pandas_dataframe",
            "numeric_imputation": "median_add_indicator",
            "categorical_imputation": "most_frequent",
        },
        dataset_contract={
            "schema_version": candidate.dataset_input.schema_version,
            "manifest_sha256": candidate.dataset_input.manifest_sha256,
            "data_content_sha256": candidate.dataset_input.data_content_sha256,
            "training_file": training_file,
            "training_file_sha256": candidate.dataset_input.file_sha256(
                training_file
            ),
        },
        split_sha256=candidate.split.sha256,
        evaluation_sha256=_sha256(evaluation_path),
        model_contract={
            "model_id": f"{stem}-{artifact_hash[:12]}",
            "model_name": candidate.model_name,
            "model_version": candidate.created_at.strftime("%Y.%m.%d.%H%M%S"),
            "algorithm": candidate.model_name,
            "artifact_sha256": artifact_hash,
            "packages": {
                "python": f"{sys.version_info.major}.{sys.version_info.minor}",
                "scikit_learn": sklearn.__version__,
                "joblib": joblib.__version__,
                "numpy": numpy.__version__,
                "pandas": pandas.__version__,
            },
        },
        output_contract={
            "kind": "multiclass",
            "classes": list(contract.class_order),
            "ordered": False,
            "score_semantics": "model_score",
            "projected_value_supported": False,
            "prediction_interval_supported": False,
        },
        calibration={"status": "not_calibrated", "method": None},
        audit={
            "leakage_status": (
                "review_required" if uses_demonstration else "passed"
            ),
            "locked_test_used_for_selection": False,
            "synthetic_in_formal_metrics": uses_demonstration,
            "synthetic_purpose": (
                "demonstration_training_only" if uses_demonstration else None
            ),
            "clinical_validity_claim": False,
            "code_version": "unknown",
        },
        status="candidate",
        production_enabled=False,
        created_at=candidate.created_at,
    )


def write_trend_candidate_bundle(
    candidate: TrainedTrendCandidate,
    bundle_root: Path,
) -> TrendCandidateBundleResult:
    import joblib

    contract = candidate.contract
    stem = f"{contract.disease}_next_visit_trend_{contract.indicator}"
    bundle_dir = Path(bundle_root) / stem
    if bundle_dir.exists():
        raise FileExistsError(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=False)
    model_path = bundle_dir / f"{stem}.joblib"
    metadata_path = bundle_dir / f"{stem}.meta.json"
    evaluation_path = bundle_dir / f"{stem}.evaluation.json"
    try:
        joblib.dump(candidate.model, model_path)
        evaluation_path.write_text(
            candidate.evaluation.model_dump_json(indent=2), encoding="utf-8"
        )
        metadata = _metadata(candidate, model_path, evaluation_path)
        metadata_path.write_text(
            metadata.model_dump_json(indent=2), encoding="utf-8"
        )
    except Exception:
        for path in (metadata_path, evaluation_path, model_path):
            if path.exists():
                path.unlink()
        try:
            bundle_dir.rmdir()
        except OSError:
            pass
        raise
    return TrendCandidateBundleResult(
        bundle_dir=bundle_dir,
        model_path=model_path,
        metadata_path=metadata_path,
        evaluation_path=evaluation_path,
        metadata=metadata,
        evaluation=candidate.evaluation,
    )
