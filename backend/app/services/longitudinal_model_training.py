"""Leak-resistant readers and training helpers for P0-04."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Sequence

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from app.schemas.longitudinal_dataset import FixedWindowSample
from app.schemas.longitudinal_model_registry import (
    TASK_CONTRACTS,
    feature_order_sha256,
)
from app.schemas.longitudinal_model_training import DatasetInput, TASK_SPECS, TaskSpec
from app.schemas.longitudinal_model_suite import ArtifactMetadataV2, EvaluationArtifact
from app.services.longitudinal_group_split import DiseaseGroupSplit
from app.services.longitudinal_model_evaluation import compute_binary_metrics, select_oof_f1_threshold


class ModelInputError(ValueError):
    """Privacy-safe P0-04 input contract error."""


@dataclass(frozen=True)
class TrainingRow:
    sample: FixedWindowSample
    values: dict[str, Any]


@dataclass(frozen=True)
class FeatureCatalog:
    feature_names: tuple[str, ...]
    numeric_features: tuple[str, ...]
    categorical_features: tuple[str, ...]


@dataclass(frozen=True)
class PreparedOutcomeTask:
    task: TaskSpec
    split_sha256: str
    development_train_rows: tuple[TrainingRow, ...]
    development_validation_rows: tuple[TrainingRow, ...]
    locked_test_rows: tuple[TrainingRow, ...]

    @property
    def development_rows(self) -> tuple[TrainingRow, ...]:
        return self.development_train_rows + self.development_validation_rows


@dataclass(frozen=True)
class TrainedOutcomeCandidate:
    task: TaskSpec
    model: Any
    model_name: str
    catalog: FeatureCatalog
    dataset_input: DatasetInput
    split: DiseaseGroupSplit
    evaluation: EvaluationArtifact
    threshold: float
    selection_trace: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True)
class OutcomeCandidateBundleResult:
    bundle_dir: Path
    model_path: Path
    metadata_path: Path
    evaluation_path: Path
    metadata: ArtifactMetadataV2
    evaluation: EvaluationArtifact


_FORBIDDEN = {"schema_version", "disease", "disease_name", "source_dataset", "patient_label", "group_id", "is_synthetic", "source_document", "import_version", "as_of", "current_state", "target_event", "history_visit_count", "history_start", "label", "event_type", "event_date", "last_followup_date", "final_stage", "confirmed", "event_dates", "future", "dementia_date"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_dataset_manifest(dataset_dir: Path) -> DatasetInput:
    root = Path(dataset_dir)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise ModelInputError("manifest_missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelInputError("manifest_invalid") from exc
    if manifest.get("schema_version") != "longitudinal_fixed_window_dataset.v1":
        raise ModelInputError("schema_mismatch")
    if manifest.get("minimum_visits") != 3 or manifest.get("horizon_days") != 365:
        raise ModelInputError("window_mismatch")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ModelInputError("manifest_files_missing")
    for relative, expected in files.items():
        path = root / relative
        if not path.is_file() or _sha256(path) != expected:
            raise ModelInputError("dataset_hash_mismatch")
    stable = {
        "schema_version": manifest["schema_version"],
        "minimum_visits": manifest["minimum_visits"],
        "horizon_days": manifest["horizon_days"],
        "summary": manifest.get("summary"),
        "files": dict(sorted(files.items())),
    }
    if "training_profile" in manifest:
        stable.update(
            training_profile=manifest["training_profile"],
            clinical_validity_claim=manifest.get(
                "clinical_validity_claim", False
            ),
            generator=manifest.get("generator"),
        )
    actual_content = hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if actual_content != manifest.get("data_content_sha256"):
        raise ModelInputError("data_content_hash_mismatch")
    return DatasetInput(
        dataset_dir=str(root.resolve()),
        schema_version=manifest["schema_version"],
        run_id=manifest.get("run_id"),
        manifest_sha256=_sha256(manifest_path),
        data_content_sha256=manifest["data_content_sha256"],
        file_sha256_by_path=dict(files),
        group_split_file=manifest.get("group_split_file"),
        group_split_sha256=manifest.get("group_split_sha256"),
        training_profile=manifest.get("training_profile", "real_only"),
        training_file_by_disease=dict(manifest.get("training_file_by_disease") or {}),
        timeline_file_by_disease=dict(manifest.get("timeline_file_by_disease") or {}),
        clinical_validity_claim=manifest.get("clinical_validity_claim", False),
    )


def _contains_forbidden(value: Any) -> list[str]:
    hits: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            if key_text in _FORBIDDEN or any(token in key_text for token in ("future", "event_dates", "final_stage", "confirmed")):
                hits.add(key_text)
            hits.update(_contains_forbidden(child))
    elif isinstance(value, list):
        for child in value:
            hits.update(_contains_forbidden(child))
    return sorted(hits)


def read_training_samples(
    dataset_dir: Path,
    disease: str,
    *,
    dataset: DatasetInput | None = None,
) -> list[FixedWindowSample]:
    dataset_input = dataset or read_dataset_manifest(dataset_dir)
    relative = dataset_input.training_file_by_disease.get(
        disease, f"{disease}/real_train.jsonl"
    )
    path = Path(dataset_dir) / relative
    if not path.is_file():
        raise ModelInputError("training_file_missing")
    samples: list[FixedWindowSample] = []
    seen: set[tuple[str, str]] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            hits = _contains_forbidden({"features": raw.get("features", {})})
            if hits:
                raise ModelInputError("forbidden_feature")
            sample = FixedWindowSample.model_validate(raw)
        except ModelInputError:
            raise
        except Exception as exc:
            raise ModelInputError("sample_invalid") from exc
        if sample.identity.disease != disease:
            raise ModelInputError("training_disease_mismatch")
        if (
            sample.identity.is_synthetic
            and dataset_input.training_profile != "synthetic_demonstration"
        ):
            raise ModelInputError("formal_training_requires_real_samples")
        if sample.label.status not in {"positive", "negative"} or sample.label.training_label not in {0, 1}:
            raise ModelInputError("non_trainable_sample")
        key = (sample.identity.group_id, sample.identity.as_of.isoformat())
        if key in seen:
            raise ModelInputError("duplicate_training_sample")
        seen.add(key)
        samples.append(sample)
    if not samples:
        raise ModelInputError("training_file_empty")
    return samples


def read_real_train_samples(dataset_dir: Path, disease: str) -> list[FixedWindowSample]:
    """Compatibility reader retaining the real-only P0-04 contract."""
    dataset = read_dataset_manifest(dataset_dir)
    if dataset.training_profile != "real_only":
        raise ModelInputError("formal_training_requires_real_samples")
    return read_training_samples(dataset_dir, disease, dataset=dataset)


def select_task_samples(samples: Sequence[FixedWindowSample], task_name: str) -> list[TrainingRow]:
    try:
        task = TASK_SPECS[task_name]
    except KeyError as exc:
        raise ModelInputError("unknown_task") from exc
    rows: list[TrainingRow] = []
    for sample in samples:
        if sample.identity.disease != task.disease or sample.identity.current_state != task.current_state or sample.identity.target_event != task.target_event:
            continue
        values: dict[str, Any] = {"age": sample.features.age, "sex": sample.features.sex, "visit_count": sample.features.visit_count, "observation_span_days": sample.features.observation_span_days, "days_since_previous_visit": sample.features.days_since_previous_visit}
        for name, indicator in sample.features.indicators.items():
            for stat in ("first", "last", "minimum", "maximum", "mean", "delta", "time_slope_per_day", "recent_delta", "rises_count", "falls_count", "n_observations", "missing_ratio"):
                values[f"{name}.{stat}"] = getattr(indicator, stat)
        rows.append(TrainingRow(sample, values))
    if not rows:
        raise ModelInputError("task_has_no_samples")
    return rows


def build_feature_catalog(rows: Sequence[TrainingRow], task: TaskSpec) -> FeatureCatalog:
    names = sorted({key for row in rows for key in row.values if key != "sex" and key not in _FORBIDDEN})
    return FeatureCatalog(tuple(names + ["sex"]), tuple(names), ("sex",))


def make_preprocessor(feature_catalog: FeatureCatalog, *, scale_numeric: bool) -> ColumnTransformer:
    numeric_steps = [("imputer", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True))]
    if scale_numeric:
        numeric_steps.append(("scaler", StandardScaler()))
    return ColumnTransformer([("numeric", Pipeline(numeric_steps), list(feature_catalog.numeric_features)), ("sex", Pipeline([("imputer", SimpleImputer(strategy="most_frequent")), ("onehot", OneHotEncoder(handle_unknown="ignore"))]), list(feature_catalog.categorical_features))], remainder="drop")


def _make_fitted_candidates(catalog: FeatureCatalog, seed: int = 42) -> dict[str, Pipeline]:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    return {
        "logistic_regression": Pipeline([("preprocess", make_preprocessor(catalog, scale_numeric=True)), ("classifier", LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced", random_state=seed))]),
        "random_forest": Pipeline([("preprocess", make_preprocessor(catalog, scale_numeric=False)), ("classifier", RandomForestClassifier(n_estimators=200, max_depth=4, min_samples_leaf=3, class_weight="balanced", random_state=seed, n_jobs=1))]),
    }


def _frame(rows: Sequence[TrainingRow], catalog: FeatureCatalog):
    import pandas as pd
    return pd.DataFrame([{name: row.values.get(name) for name in catalog.feature_names} for row in rows])


def _code_version() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return completed.stdout.strip() or "unknown"


def _rows_for_groups(
    rows: Sequence[TrainingRow], groups: Sequence[str]
) -> tuple[TrainingRow, ...]:
    allowed = set(groups)
    return tuple(
        row for row in rows if row.sample.identity.group_id in allowed
    )


def prepare_outcome_task(
    rows: Sequence[TrainingRow],
    task: TaskSpec,
    split: DiseaseGroupSplit,
) -> PreparedOutcomeTask:
    if split.disease != task.disease:
        raise ModelInputError("split_disease_mismatch")
    row_groups = {row.sample.identity.group_id for row in rows}
    split_groups = set(split.assignments())
    if not row_groups.issubset(split_groups):
        raise ModelInputError("task_group_missing_from_split")
    prepared = PreparedOutcomeTask(
        task=task,
        split_sha256=split.sha256,
        development_train_rows=_rows_for_groups(
            rows, split.development_train_groups
        ),
        development_validation_rows=_rows_for_groups(
            rows, split.development_validation_groups
        ),
        locked_test_rows=_rows_for_groups(rows, split.locked_test_groups),
    )
    if not prepared.development_train_rows:
        raise ModelInputError("development_train_empty")
    if not prepared.development_validation_rows:
        raise ModelInputError("development_validation_empty")
    if not prepared.locked_test_rows:
        raise ModelInputError("locked_test_empty")
    return prepared


def _labels(rows: Sequence[TrainingRow]) -> list[int]:
    return [int(row.sample.label.training_label) for row in rows]


def _require_binary_support(rows: Sequence[TrainingRow], reason: str) -> None:
    if set(_labels(rows)) != {0, 1}:
        raise ModelInputError(reason)


def _candidate_validation_metrics(
    model: Pipeline,
    rows: Sequence[TrainingRow],
    catalog: FeatureCatalog,
) -> tuple[list[float], dict[str, Any]]:
    probabilities = model.predict_proba(_frame(rows, catalog))[:, 1].tolist()
    labels = _labels(rows)
    metrics = compute_binary_metrics(labels, probabilities, 0.5)
    return probabilities, metrics.model_dump(mode="json")


def evaluate_locked_test(
    model: Pipeline,
    rows: Sequence[TrainingRow],
    catalog: FeatureCatalog,
    threshold: float,
):
    probabilities = model.predict_proba(_frame(rows, catalog))[:, 1].tolist()
    return compute_binary_metrics(_labels(rows), probabilities, threshold)


def train_outcome_task(
    rows: Sequence[TrainingRow],
    task: TaskSpec,
    split: DiseaseGroupSplit,
    dataset_input: DatasetInput,
    output_dir: Path,
    *,
    seed: int = 42,
) -> TrainedOutcomeCandidate:
    prepared = prepare_outcome_task(rows, task, split)
    _require_binary_support(
        prepared.development_train_rows, "development_train_class_missing"
    )
    _require_binary_support(
        prepared.development_validation_rows,
        "development_validation_class_missing",
    )
    _require_binary_support(prepared.locked_test_rows, "locked_test_class_missing")

    catalog = build_feature_catalog(prepared.development_train_rows, task)
    train_frame = _frame(prepared.development_train_rows, catalog)
    train_labels = _labels(prepared.development_train_rows)
    candidate_results: list[dict[str, Any]] = []
    fitted_candidates = _make_fitted_candidates(catalog, seed)
    for model_name, model in sorted(fitted_candidates.items()):
        model.fit(train_frame, train_labels)
        probabilities, metrics = _candidate_validation_metrics(
            model, prepared.development_validation_rows, catalog
        )
        candidate_results.append(
            {
                "model_name": model_name,
                "model": model,
                "probabilities": probabilities,
                "metrics": metrics,
            }
        )
    selected = max(
        candidate_results,
        key=lambda item: (
            item["metrics"].get("pr_auc")
            if item["metrics"].get("pr_auc") is not None
            else -1.0,
            item["metrics"].get("roc_auc")
            if item["metrics"].get("roc_auc") is not None
            else -1.0,
            item["model_name"],
        ),
    )
    validation_labels = _labels(prepared.development_validation_rows)
    threshold = select_oof_f1_threshold(
        validation_labels, selected["probabilities"]
    ).threshold
    frozen_model = _make_fitted_candidates(catalog, seed)[selected["model_name"]]
    frozen_model.fit(
        _frame(prepared.development_rows, catalog),
        _labels(prepared.development_rows),
    )
    selection_trace = (
        "development_candidates_evaluated",
        "candidate_selected",
        "threshold_selected_from_development",
        "candidate_frozen",
    )
    locked_metrics = evaluate_locked_test(
        frozen_model,
        prepared.locked_test_rows,
        catalog,
        threshold,
    )
    class_support = {
        "development_train_negative": _labels(
            prepared.development_train_rows
        ).count(0),
        "development_train_positive": _labels(
            prepared.development_train_rows
        ).count(1),
        "development_validation_negative": validation_labels.count(0),
        "development_validation_positive": validation_labels.count(1),
        "locked_test_negative": _labels(prepared.locked_test_rows).count(0),
        "locked_test_positive": _labels(prepared.locked_test_rows).count(1),
    }
    evaluation = EvaluationArtifact(
        artifact_type="outcome",
        task=task.task,
        dataset=task.disease,
        dataset_manifest_sha256=dataset_input.manifest_sha256,
        data_content_sha256=dataset_input.data_content_sha256,
        training_file_sha256=dataset_input.file_sha256(task.dataset_file),
        split_sha256=split.sha256,
        selection_metrics={
            "primary": "pr_auc",
            "tie_breakers": ["roc_auc", "model_name"],
            "selected_model": selected["model_name"],
            "selected_threshold": threshold,
            "threshold_source": "development_validation_f1",
            "candidates": [
                {
                    "model_name": item["model_name"],
                    "metrics": item["metrics"],
                }
                for item in candidate_results
            ],
            "selection_trace": list(selection_trace),
        },
        locked_test_metrics=locked_metrics.model_dump(mode="json"),
        baselines={
            "development_positive_rate": sum(
                _labels(prepared.development_rows)
            )
            / len(prepared.development_rows),
            "locked_test_positive_rate": sum(_labels(prepared.locked_test_rows))
            / len(prepared.locked_test_rows),
        },
        class_support=class_support,
        locked_test_used_for_selection=False,
    )
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    return TrainedOutcomeCandidate(
        task=task,
        model=frozen_model,
        model_name=selected["model_name"],
        catalog=catalog,
        dataset_input=dataset_input,
        split=split,
        evaluation=evaluation,
        threshold=float(threshold),
        selection_trace=selection_trace,
        created_at=datetime.now(timezone.utc),
    )


def _outcome_v2_metadata(
    candidate: TrainedOutcomeCandidate,
    model_path: Path,
    evaluation_path: Path,
) -> ArtifactMetadataV2:
    import joblib
    import numpy
    import pandas
    import sklearn

    contract = TASK_CONTRACTS[candidate.task.task]
    names = list(candidate.catalog.feature_names)
    required = [
        name
        for name in (
            "visit_count",
            "observation_span_days",
            "days_since_previous_visit",
        )
        if name in names
    ]
    artifact_hash = _sha256(model_path)
    version = candidate.created_at.strftime("%Y.%m.%d.%H%M%S")
    uses_demonstration = (
        candidate.dataset_input.training_profile == "synthetic_demonstration"
    )
    return ArtifactMetadataV2(
        schema_version="longitudinal_model_artifact.v2",
        artifact_type="outcome",
        task=candidate.task.task,
        dataset=candidate.task.disease,
        target=candidate.task.target_event,
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
            "training_file": candidate.task.dataset_file,
            "training_file_sha256": candidate.dataset_input.file_sha256(
                candidate.task.dataset_file
            ),
        },
        split_sha256=candidate.split.sha256,
        evaluation_sha256=_sha256(evaluation_path),
        model_contract={
            "model_id": f"{contract.artifact_stem}-{artifact_hash[:12]}",
            "model_name": candidate.model_name,
            "model_version": version,
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
            "kind": "binary",
            "classes": ["no_event", "event"],
            "positive_class": "event",
            "threshold": candidate.threshold,
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
            "code_version": _code_version(),
        },
        status="candidate",
        production_enabled=False,
        created_at=candidate.created_at,
    )


def write_outcome_candidate_bundle(
    candidate: TrainedOutcomeCandidate,
    bundle_root: Path,
) -> OutcomeCandidateBundleResult:
    import joblib

    contract = TASK_CONTRACTS[candidate.task.task]
    bundle_dir = Path(bundle_root) / contract.artifact_stem
    if bundle_dir.exists():
        raise FileExistsError(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=False)
    model_path = bundle_dir / f"{contract.artifact_stem}.joblib"
    metadata_path = bundle_dir / f"{contract.artifact_stem}.meta.json"
    evaluation_path = bundle_dir / f"{contract.artifact_stem}.evaluation.json"
    try:
        joblib.dump(candidate.model, model_path)
        evaluation_path.write_text(
            candidate.evaluation.model_dump_json(indent=2), encoding="utf-8"
        )
        metadata = _outcome_v2_metadata(
            candidate, model_path, evaluation_path
        )
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
    return OutcomeCandidateBundleResult(
        bundle_dir=bundle_dir,
        model_path=model_path,
        metadata_path=metadata_path,
        evaluation_path=evaluation_path,
        metadata=metadata,
        evaluation=candidate.evaluation,
    )
