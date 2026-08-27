"""Leakage-safe next-stage sample construction and candidate training."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
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
from app.services.longitudinal_model_evaluation import compute_multiclass_metrics
from app.services.disease_progression import get_progression_adapter
from app.services.longitudinal_dataset import PatientTimeline
from app.services.longitudinal_features import (
    build_prefixes,
    summarize_fixed_window_history,
)
from app.services.longitudinal_group_split import DiseaseGroupSplit


StageAuditStatus = Literal["passed", "review_required", "blocked"]


class StageTrainingError(ValueError):
    """Stable, privacy-safe stage training error."""


@dataclass(frozen=True)
class StageTrainingRow:
    disease: str
    group_id: str
    as_of: date
    max_feature_date: date
    current_stage: str
    label: str
    values: dict[str, Any]


@dataclass(frozen=True)
class StageFeatureCatalog:
    feature_names: tuple[str, ...]
    numeric_features: tuple[str, ...]
    categorical_features: tuple[str, ...]


@dataclass(frozen=True)
class StageLabelCopyAudit:
    status: StageAuditStatus
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class OrderedStageMetrics:
    class_order: list[str]
    class_support: dict[str, int]
    macro_f1: float | None
    balanced_accuracy: float | None
    confusion_matrix: list[list[int]]
    unavailable_metrics: list[str]
    ordered_error: float | None


@dataclass(frozen=True)
class TrainedStageCandidate:
    disease: str
    task: str
    model: Any
    model_name: str
    catalog: StageFeatureCatalog
    split: DiseaseGroupSplit
    dataset_input: Any
    evaluation: EvaluationArtifact
    locked_test_metrics: OrderedStageMetrics
    selection_trace: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True)
class StageCandidateBundleResult:
    bundle_dir: Path
    model_path: Path
    metadata_path: Path
    evaluation_path: Path
    metadata: ArtifactMetadataV2
    evaluation: EvaluationArtifact


_FORBIDDEN_STAGE_FEATURES = {
    "final_stage",
    "event_dates",
    "dementia_date",
    "cirrhosis_date",
    "hcc_date",
    "label",
    "patient_label",
    "group_id",
    "source_document",
}


def _indicator_value_at(
    patient: PatientTimeline, when: date, indicator_name: str
) -> float | None:
    for visit in reversed(patient.visits):
        if visit.visit_date > when:
            continue
        for indicator in visit.indicators:
            if str(indicator.get("name", "")).strip().lower() != indicator_name:
                continue
            try:
                return float(indicator.get("value"))
            except (TypeError, ValueError):
                return None
    return None


def _stage_at(patient: PatientTimeline, when: date) -> str:
    if patient.adapter.dataset == "ad":
        dementia_date = patient.event_dates.get("dementia_date")
        if dementia_date is not None and dementia_date <= when:
            return "dementia"
        cdr = _indicator_value_at(patient, when, "cdr")
        if cdr is not None:
            if cdr >= 1:
                return "dementia"
            if cdr >= 0.5:
                return "mci"
            return "normal"
    stage = patient.adapter.stage_order[0]
    for field, next_stage in patient.adapter.event_stage_pairs():
        event = patient.event_dates.get(field)
        if event is not None and event <= when:
            stage = next_stage
    return stage


def _normalized_stage(disease: str, stage: str) -> str:
    if disease == "fatty_liver":
        return "pre_cirrhosis" if stage == "fatty_liver" else stage
    return stage


def _stage_target(patient: PatientTimeline, as_of: date) -> tuple[str, str] | None:
    horizon_end = as_of + timedelta(days=365)
    if not patient.visits:
        return None
    current = _normalized_stage(patient.adapter.dataset, _stage_at(patient, as_of))
    future = _normalized_stage(
        patient.adapter.dataset, _stage_at(patient, horizon_end)
    )
    known_event_in_window = any(
        event is not None and as_of < event <= horizon_end
        for event in patient.event_dates.values()
    )
    if patient.visits[-1].visit_date < horizon_end and not known_event_in_window:
        return None
    if future == current:
        return current, f"stay_{current}"
    return current, future


def _prefix_visit_dict(visit) -> dict[str, object]:
    return {
        "visit_date": visit.visit_date.isoformat(),
        "indicators": [dict(indicator) for indicator in visit.indicators],
    }


def _row_values(
    patient: PatientTimeline,
    prefix_visits,
    current_stage: str,
) -> dict[str, Any]:
    history = summarize_fixed_window_history(
        [_prefix_visit_dict(visit) for visit in prefix_visits]
    )
    age = next(
        (
            visit.patient_age
            for visit in reversed(prefix_visits)
            if visit.patient_age is not None
        ),
        None,
    )
    sex = next(
        (visit.sex for visit in reversed(prefix_visits) if visit.sex is not None),
        None,
    )
    values: dict[str, Any] = {
        "age": age,
        "sex": sex,
        "current_stage": current_stage,
        "visit_count": history["visit_count"],
        "observation_span_days": history["observation_span_days"],
        "days_since_previous_visit": history["days_since_previous_visit"],
    }
    for indicator, summary in history["indicators"].items():
        if patient.adapter.dataset == "ad" and indicator == "cdr":
            continue
        for statistic, value in summary.items():
            values[f"{indicator}.{statistic}"] = value
    return values


def build_stage_rows(
    timelines: Sequence[PatientTimeline],
    disease: str,
    split: DiseaseGroupSplit,
    *,
    allow_synthetic: bool = False,
) -> list[StageTrainingRow]:
    if disease not in {"fatty_liver", "ad"}:
        raise StageTrainingError("unsupported_disease")
    if split.disease != disease:
        raise StageTrainingError("split_disease_mismatch")
    allowed_groups = set(split.assignments())
    rows: list[StageTrainingRow] = []
    for patient in sorted(timelines, key=lambda value: value.group_id):
        if patient.adapter.dataset != disease or (
            patient.is_synthetic and not allow_synthetic
        ):
            continue
        if patient.group_id not in allowed_groups:
            raise StageTrainingError("patient_group_missing_from_split")
        visit_dicts = [_prefix_visit_dict(visit) for visit in patient.visits]
        prefixes = build_prefixes(visit_dicts, minimum_visits=3)
        for prefix_index, prefix in enumerate(prefixes, start=3):
            as_of = date.fromisoformat(str(prefix["as_of"]))
            resolved = _stage_target(patient, as_of)
            if resolved is None:
                continue
            current_stage, label = resolved
            if current_stage in {"hcc", "dementia"}:
                continue
            prefix_visits = patient.visits[:prefix_index]
            rows.append(
                StageTrainingRow(
                    disease=disease,
                    group_id=patient.group_id,
                    as_of=as_of,
                    max_feature_date=max(
                        visit.visit_date for visit in prefix_visits
                    ),
                    current_stage=current_stage,
                    label=label,
                    values=_row_values(patient, prefix_visits, current_stage),
                )
            )
    return rows


def build_stage_feature_catalog(
    rows: Sequence[StageTrainingRow],
) -> StageFeatureCatalog:
    names = sorted({key for row in rows for key in row.values})
    lowered = {name.lower() for name in names}
    if lowered & _FORBIDDEN_STAGE_FEATURES or any(
        any(token in name for token in ("event_date", "final_stage", "future"))
        for name in lowered
    ):
        raise StageTrainingError("forbidden_stage_feature")
    categorical = tuple(
        name for name in names if name in {"sex", "current_stage"}
    )
    numeric = tuple(name for name in names if name not in categorical)
    return StageFeatureCatalog(tuple(names), numeric, categorical)


def audit_stage_label_copy(
    rows: Sequence[StageTrainingRow],
) -> StageLabelCopyAudit:
    reasons: list[str] = []
    ad_rows = [row for row in rows if row.disease == "ad"]
    with_cdr = [row for row in ad_rows if row.values.get("cdr.last") is not None]
    if len(with_cdr) >= 4:
        mapping: dict[float, set[str]] = {}
        for row in with_cdr:
            mapping.setdefault(float(row.values["cdr.last"]), set()).add(row.label)
        if mapping and all(len(labels) == 1 for labels in mapping.values()):
            reasons.append("cdr_label_copy_risk")
    return StageLabelCopyAudit(
        status="review_required" if reasons else "passed",
        reason_codes=tuple(reasons),
    )


def _required_classes(disease: str) -> set[str]:
    if disease == "fatty_liver":
        return {
            "stay_pre_cirrhosis",
            "cirrhosis",
            "stay_cirrhosis",
            "hcc",
        }
    return {"stay_normal", "stay_mci", "mci", "dementia"}


def _output_classes(disease: str) -> list[str]:
    if disease == "fatty_liver":
        return [
            "stay_pre_cirrhosis",
            "cirrhosis",
            "stay_cirrhosis",
            "hcc",
        ]
    return ["stay_normal", "stay_mci", "mci", "dementia"]


def _rows_for_groups(
    rows: Sequence[StageTrainingRow], groups: Sequence[str]
) -> list[StageTrainingRow]:
    allowed = set(groups)
    return [row for row in rows if row.group_id in allowed]


def _frame(rows: Sequence[StageTrainingRow], catalog: StageFeatureCatalog):
    import pandas as pd

    return pd.DataFrame(
        [
            {name: row.values.get(name) for name in catalog.feature_names}
            for row in rows
        ]
    )


def _preprocessor(catalog: StageFeatureCatalog, *, scale_numeric: bool):
    numeric_steps = [
        (
            "imputer",
            SimpleImputer(
                strategy="median",
                add_indicator=True,
                keep_empty_features=True,
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


def _candidate_models(catalog: StageFeatureCatalog, seed: int):
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


def _ordered_metrics(
    labels: Sequence[str],
    predictions: Sequence[str],
    class_order: Sequence[str],
) -> OrderedStageMetrics:
    base: MulticlassMetrics = compute_multiclass_metrics(
        labels, predictions, class_order
    )
    positions = {value: index for index, value in enumerate(class_order)}
    ordered_error = (
        sum(
            abs(positions[label] - positions[prediction])
            for label, prediction in zip(labels, predictions)
        )
        / len(labels)
        if labels
        else None
    )
    return OrderedStageMetrics(
        class_order=base.class_order,
        class_support=base.class_support,
        macro_f1=base.macro_f1,
        balanced_accuracy=base.balanced_accuracy,
        confusion_matrix=base.confusion_matrix,
        unavailable_metrics=base.unavailable_metrics,
        ordered_error=ordered_error,
    )


def evaluate_stage_locked_test(
    model: Pipeline,
    rows: Sequence[StageTrainingRow],
    catalog: StageFeatureCatalog,
    class_order: Sequence[str],
) -> OrderedStageMetrics:
    labels = [row.label for row in rows]
    predictions = model.predict(_frame(rows, catalog)).tolist()
    return _ordered_metrics(labels, predictions, class_order)


def train_stage_candidate(
    rows: Sequence[StageTrainingRow],
    split: DiseaseGroupSplit,
    dataset_input,
    output_dir,
    *,
    seed: int = 42,
):
    if not rows or split.disease not in {"fatty_liver", "ad"}:
        raise StageTrainingError("stage_rows_missing")
    labels = {row.label for row in rows}
    if not _required_classes(split.disease).issubset(labels):
        raise StageTrainingError("stage_class_support_insufficient")
    split_groups = set(split.assignments())
    if not {row.group_id for row in rows}.issubset(split_groups):
        raise StageTrainingError("stage_group_missing_from_split")
    training = _rows_for_groups(rows, split.development_train_groups)
    validation = _rows_for_groups(rows, split.development_validation_groups)
    locked = _rows_for_groups(rows, split.locked_test_groups)
    required = _required_classes(split.disease)
    if any(
        not required.issubset({row.label for row in partition})
        for partition in (training, validation, locked)
    ):
        raise StageTrainingError("stage_class_support_insufficient")
    catalog = build_stage_feature_catalog(training)
    class_order = _output_classes(split.disease)
    candidates = []
    for model_name, model in sorted(_candidate_models(catalog, seed).items()):
        model.fit(_frame(training, catalog), [row.label for row in training])
        metrics = _ordered_metrics(
            [row.label for row in validation],
            model.predict(_frame(validation, catalog)).tolist(),
            class_order,
        )
        candidates.append((model_name, metrics))
    selected_name, selected_metrics = max(
        candidates,
        key=lambda item: (
            item[1].macro_f1 if item[1].macro_f1 is not None else -1.0,
            item[1].balanced_accuracy
            if item[1].balanced_accuracy is not None
            else -1.0,
            item[0],
        ),
    )
    development = training + validation
    frozen = _candidate_models(catalog, seed)[selected_name]
    frozen.fit(
        _frame(development, catalog), [row.label for row in development]
    )
    trace = (
        "development_candidates_evaluated",
        "candidate_selected",
        "candidate_frozen",
    )
    locked_metrics = evaluate_stage_locked_test(
        frozen, locked, catalog, class_order
    )
    if dataset_input is None:
        raise StageTrainingError("dataset_input_required")
    task = f"{split.disease}.next_stage"
    training_file = dataset_input.training_file_by_disease.get(
        split.disease, f"{split.disease}/real_train.jsonl"
    )
    evaluation = EvaluationArtifact(
        artifact_type="stage",
        task=task,
        dataset=split.disease,
        dataset_manifest_sha256=dataset_input.manifest_sha256,
        data_content_sha256=dataset_input.data_content_sha256,
        training_file_sha256=dataset_input.file_sha256(training_file),
        split_sha256=split.sha256,
        selection_metrics={
            "primary": "macro_f1",
            "tie_breakers": ["balanced_accuracy", "model_name"],
            "selected_model": selected_name,
            "selected_metrics": selected_metrics.__dict__,
            "selection_trace": list(trace),
        },
        locked_test_metrics=locked_metrics.__dict__,
        baselines={
            "majority_class": max(
                class_order,
                key=lambda value: sum(row.label == value for row in development),
            )
        },
        class_support={
            f"development_{name}": sum(
                row.label == name for row in development
            )
            for name in class_order
        }
        | {
            f"locked_test_{name}": sum(row.label == name for row in locked)
            for name in class_order
        },
        locked_test_used_for_selection=False,
    )
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    return TrainedStageCandidate(
        disease=split.disease,
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


def _stage_metadata(
    candidate: TrainedStageCandidate,
    model_path: Path,
    evaluation_path: Path,
) -> ArtifactMetadataV2:
    import joblib
    import numpy
    import pandas
    import sklearn

    names = list(candidate.catalog.feature_names)
    required = [
        name
        for name in ("visit_count", "current_stage")
        if name in names
    ]
    stem = f"{candidate.disease}_next_stage_365d"
    artifact_hash = _sha256(model_path)
    training_file = candidate.dataset_input.training_file_by_disease.get(
        candidate.disease, f"{candidate.disease}/real_train.jsonl"
    )
    uses_demonstration = (
        candidate.dataset_input.training_profile == "synthetic_demonstration"
    )
    return ArtifactMetadataV2(
        schema_version="longitudinal_model_artifact.v2",
        artifact_type="stage",
        task=candidate.task,
        dataset=candidate.disease,
        target="next_stage",
        horizon={"kind": "days", "value": 365},
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
            "classes": _output_classes(candidate.disease),
            "ordered": True,
            "score_semantics": "model_score",
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


def write_stage_candidate_bundle(
    candidate: TrainedStageCandidate,
    bundle_root: Path,
) -> StageCandidateBundleResult:
    import joblib

    stem = f"{candidate.disease}_next_stage_365d"
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
        metadata = _stage_metadata(candidate, model_path, evaluation_path)
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
    return StageCandidateBundleResult(
        bundle_dir=bundle_dir,
        model_path=model_path,
        metadata_path=metadata_path,
        evaluation_path=evaluation_path,
        metadata=metadata,
        evaluation=candidate.evaluation,
    )
