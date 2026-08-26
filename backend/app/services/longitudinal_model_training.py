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
from app.schemas.longitudinal_model_training import DatasetInput, GroupSplit, InputAudit, TASK_SPECS, TaskSpec


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
    numeric_steps = [("imputer", SimpleImputer(strategy="median", add_indicator=True))]
    if scale_numeric:
        numeric_steps.append(("scaler", StandardScaler()))
    return ColumnTransformer([("numeric", Pipeline(numeric_steps), list(feature_catalog.numeric_features)), ("sex", Pipeline([("imputer", SimpleImputer(strategy="most_frequent")), ("onehot", OneHotEncoder(handle_unknown="ignore"))]), list(feature_catalog.categorical_features))], remainder="drop")
