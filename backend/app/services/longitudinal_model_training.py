"""Leak-resistant readers and training helpers for P0-04."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from app.schemas.longitudinal_dataset import FixedWindowSample
from app.schemas.longitudinal_model_training import DatasetInput, GroupSplit, InputAudit, TASK_SPECS, TaskSpec, FoldMetrics, EvaluationSummary


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
    stable = {"schema_version": manifest["schema_version"], "minimum_visits": manifest["minimum_visits"], "horizon_days": manifest["horizon_days"], "summary": manifest.get("summary"), "files": dict(sorted(files.items()))}
    actual_content = hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if actual_content != manifest.get("data_content_sha256"):
        raise ModelInputError("data_content_hash_mismatch")
    return DatasetInput(dataset_dir=str(root.resolve()), schema_version=manifest["schema_version"], manifest_sha256=_sha256(manifest_path), data_content_sha256=manifest["data_content_sha256"], file_sha256=next(iter(files.values()), "0" * 64))


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


def read_real_train_samples(dataset_dir: Path, disease: str) -> list[FixedWindowSample]:
    read_dataset_manifest(dataset_dir)
    path = Path(dataset_dir) / disease / "real_train.jsonl"
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
        if sample.identity.disease != disease or sample.identity.is_synthetic:
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


def audit_input_samples(samples: Sequence[FixedWindowSample], task: TaskSpec) -> InputAudit:
    selected = select_task_samples(samples, task.task)
    return InputAudit(sample_count=len(selected), patient_count=len({row.sample.identity.group_id for row in selected}), positive_count=sum(row.sample.label.training_label == 1 for row in selected), negative_count=sum(row.sample.label.training_label == 0 for row in selected), synthetic_count=sum(row.sample.identity.is_synthetic for row in selected), duplicate_count=len(selected) - len({(row.sample.identity.group_id, row.sample.identity.as_of) for row in selected}), forbidden_feature_hits=[])


def build_feature_catalog(rows: Sequence[TrainingRow], task: TaskSpec) -> FeatureCatalog:
    names = sorted({key for row in rows for key in row.values if key != "sex" and key not in _FORBIDDEN})
    return FeatureCatalog(tuple(names + ["sex"]), tuple(names), ("sex",))


def make_locked_group_split(rows: Sequence[TrainingRow], *, seed: int, test_fraction: float) -> GroupSplit:
    import numpy as np
    groups = sorted({row.sample.identity.group_id for row in rows})
    rng = np.random.default_rng(seed)
    shuffled = list(groups)
    rng.shuffle(shuffled)
    test_count = max(1, int(round(len(groups) * test_fraction)))
    test_groups = sorted(shuffled[:test_count])
    development_groups = sorted(shuffled[test_count:])
    development_indices = [i for i, row in enumerate(rows) if row.sample.identity.group_id in development_groups]
    test_indices = [i for i, row in enumerate(rows) if row.sample.identity.group_id in test_groups]
    return GroupSplit(development_groups=development_groups, locked_test_groups=test_groups, development_indices=development_indices, locked_test_indices=test_indices, seed=seed, test_fraction=test_fraction, group_overlap_check="passed" if set(development_groups).isdisjoint(test_groups) else "failed")


def make_preprocessor(feature_catalog: FeatureCatalog, *, scale_numeric: bool) -> ColumnTransformer:
    numeric_steps = [("imputer", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True))]
    if scale_numeric:
        numeric_steps.append(("scaler", StandardScaler()))
    return ColumnTransformer([("numeric", Pipeline(numeric_steps), list(feature_catalog.numeric_features)), ("sex", Pipeline([("imputer", SimpleImputer(strategy="most_frequent")), ("onehot", OneHotEncoder(handle_unknown="ignore"))]), list(feature_catalog.categorical_features))], remainder="drop")


def make_model_candidates(seed: int = 42) -> dict[str, Pipeline]:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    catalog = FeatureCatalog(tuple(), tuple(), tuple())
    return {
        "logistic_regression": Pipeline([("classifier", LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced", random_state=seed))]),
        "random_forest": Pipeline([("classifier", RandomForestClassifier(n_estimators=200, max_depth=4, min_samples_leaf=3, class_weight="balanced", random_state=seed, n_jobs=1))]),
    }


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


def train_task_to_candidate(rows: Sequence[TrainingRow], task: TaskSpec, dataset_input: DatasetInput, output_dir: Path, *, seed: int = 42):
    import joblib
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    catalog = build_feature_catalog(rows, task)
    candidates = _make_fitted_candidates(catalog, seed)
    X = _frame(rows, catalog)
    y = [row.sample.label.training_label for row in rows]
    model = candidates["logistic_regression"]
    model.fit(X, y)
    stem = task.task.replace(".", "_") + "_365d"
    model_path = output / f"{stem}.joblib"
    joblib.dump(model, model_path)
    return {"task": task.task, "model": model, "model_path": model_path, "dataset_input": dataset_input, "catalog": catalog, "row_count": len(rows), "patient_count": len({row.sample.identity.group_id for row in rows}), "status": "candidate"}


def write_candidate_artifact(result, output_dir: Path):
    import joblib
    import json
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    model_path = Path(result["model_path"])
    if model_path.parent != output:
        model_path = output / model_path.name
        joblib.dump(result["model"], model_path)
    meta_path = output / (model_path.stem + ".meta.json")
    catalog = result["catalog"]
    metadata = {"schema_version": "longitudinal_outcome_model_training.v1", "task": result["task"], "dataset_manifest_sha256": result["dataset_input"].manifest_sha256, "data_content_sha256": result["dataset_input"].data_content_sha256, "dataset_file_sha256": result["dataset_input"].file_sha256, "feature_order_sha256": hashlib.sha256(json.dumps(catalog.feature_names).encode()).hexdigest(), "feature_names": list(catalog.feature_names), "row_count": result["row_count"], "patient_count": result["patient_count"], "status": "candidate", "production_enabled": False, "clinical_validity_claim": False, "leakage_audit": {"synthetic_in_formal_metrics": False}, "model": {"algorithm": "logistic_regression", "random_seed": 42}, "evaluation": {}, "threshold": {"baseline": 0.5}, "calibration": {"status": "not_calibrated"}}
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    return model_path, meta_path


def run_development_cv(rows: Sequence[TrainingRow], task: TaskSpec, *, seed: int = 42) -> EvaluationSummary:
    from sklearn.metrics import average_precision_score, roc_auc_score
    from sklearn.model_selection import StratifiedGroupKFold
    import numpy as np
    labels = np.asarray([row.sample.label.training_label for row in rows], dtype=int)
    groups = np.asarray([row.sample.identity.group_id for row in rows])
    fold_count = 3 if task.task == "fatty_liver.cirrhosis_to_hcc" else 5
    splitter = StratifiedGroupKFold(n_splits=fold_count, shuffle=True, random_state=seed)
    fold_results = []
    for fold_number, (train_idx, validation_idx) in enumerate(splitter.split(np.zeros(len(rows)), labels, groups), start=1):
        train_groups = sorted(set(groups[train_idx]))
        validation_groups = sorted(set(groups[validation_idx]))
        fold_labels = labels[validation_idx]
        catalog = build_feature_catalog(rows, task)
        model = _make_fitted_candidates(catalog, seed)["logistic_regression"]
        model.fit(_frame([rows[i] for i in train_idx], catalog), labels[train_idx])
        probabilities = model.predict_proba(_frame([rows[i] for i in validation_idx], catalog))[:, 1]
        pr_auc = float(average_precision_score(fold_labels, probabilities)) if len(set(fold_labels)) == 2 else None
        roc_auc = float(roc_auc_score(fold_labels, probabilities)) if len(set(fold_labels)) == 2 else None
        fold_results.append(FoldMetrics(fold=fold_number, train_patient_count=len(train_groups), validation_patient_count=len(validation_groups), positive_patient_count=int(fold_labels.sum()), negative_patient_count=int(len(fold_labels) - fold_labels.sum()), train_groups=train_groups, validation_groups=validation_groups, pr_auc=pr_auc, roc_auc=roc_auc, unavailable_metrics=[] if pr_auc is not None else ["pr_auc", "roc_auc"]))
    return EvaluationSummary(split_method="StratifiedGroupKFold", requested_fold_count=fold_count, folds=fold_results)
