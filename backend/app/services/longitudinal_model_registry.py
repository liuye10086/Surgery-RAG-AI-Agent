"""Task-aware validation and loading for longitudinal model artifacts."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Literal

import joblib
import numpy
import pandas
import sklearn
from pydantic import ValidationError

from app.schemas.longitudinal_model_registry import (
    TASK_CONTRACTS,
    ArtifactMetadata,
    ArtifactValidationResult,
    LoadedModelEntry,
    LongitudinalModelRegistry,
    LoadedDiseaseModelSuite,
    SuiteModelEntry,
    ModelRuntimeStatus,
    ReleaseRecord,
    ReviewRecord,
    TaskName,
    feature_order_sha256,
)
from app.schemas.longitudinal_model_suite import (
    ArtifactMetadataV2,
    BundleValidationResult,
    BundleValidationStatus,
    EvaluationArtifact,
)
from app.services.progression_engine import MODEL_DIR
from app.services.longitudinal_release_set import load_disease_release_set


HEX64 = set("0123456789abcdef")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX64


def _bundle_validation(
    status: Literal["available", "missing", "incompatible"],
    reason_code: str,
    metadata: ArtifactMetadataV2 | None = None,
) -> BundleValidationResult:
    return BundleValidationResult(
        status=BundleValidationStatus(status=status, reason_code=reason_code),
        metadata=metadata,
        prediction_executed=False,
    )


def validate_bundle_files(
    *,
    model_path: Path,
    metadata_path: Path,
    evaluation_path: Path,
    manifest_path: Path,
) -> BundleValidationResult:
    """Validate a v2 bundle hash chain without loading or executing its model."""
    paths = {
        "artifact_missing": Path(model_path),
        "metadata_missing": Path(metadata_path),
        "evaluation_missing": Path(evaluation_path),
        "manifest_missing": Path(manifest_path),
    }
    for reason_code, path in paths.items():
        if not path.is_file():
            return _bundle_validation("missing", reason_code)
    try:
        metadata = ArtifactMetadataV2.model_validate_json(
            Path(metadata_path).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValidationError):
        return _bundle_validation("incompatible", "metadata_invalid")
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _bundle_validation("incompatible", "manifest_invalid", metadata)
    if not isinstance(manifest, dict):
        return _bundle_validation("incompatible", "manifest_invalid", metadata)
    if sha256_file(Path(model_path)) != metadata.model_contract.artifact_sha256:
        return _bundle_validation("incompatible", "artifact_hash_mismatch", metadata)
    if sha256_file(Path(manifest_path)) != metadata.dataset_contract.manifest_sha256:
        return _bundle_validation("incompatible", "manifest_hash_mismatch", metadata)
    if manifest.get("data_content_sha256") != metadata.dataset_contract.data_content_sha256:
        return _bundle_validation("incompatible", "data_content_hash_mismatch", metadata)
    files = manifest.get("files")
    if not isinstance(files, dict):
        return _bundle_validation("incompatible", "manifest_files_missing", metadata)
    training_file = metadata.dataset_contract.training_file
    expected_training_hash = files.get(training_file)
    if expected_training_hash != metadata.dataset_contract.training_file_sha256:
        return _bundle_validation(
            "incompatible", "training_file_hash_mismatch", metadata
        )
    training_path = Path(manifest_path).parent / training_file
    if not training_path.is_file() or sha256_file(training_path) != expected_training_hash:
        return _bundle_validation(
            "incompatible", "training_file_hash_mismatch", metadata
        )
    split_file = manifest.get("group_split_file")
    if (
        not isinstance(split_file, str)
        or files.get(split_file) != manifest.get("group_split_sha256")
    ):
        return _bundle_validation("incompatible", "split_hash_mismatch", metadata)
    split_path = Path(manifest_path).parent / split_file
    if (
        not split_path.is_file()
        or sha256_file(split_path) != manifest.get("group_split_sha256")
    ):
        return _bundle_validation("incompatible", "split_hash_mismatch", metadata)
    try:
        split_payload = json.loads(split_path.read_text(encoding="utf-8"))
        disease_splits = split_payload.get("splits")
        disease_split = next(
            item
            for item in disease_splits
            if isinstance(item, dict)
            and item.get("disease") == metadata.dataset
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, StopIteration):
        return _bundle_validation("incompatible", "split_hash_mismatch", metadata)
    if disease_split.get("sha256") != metadata.split_sha256:
        return _bundle_validation("incompatible", "split_hash_mismatch", metadata)
    if sha256_file(Path(evaluation_path)) != metadata.evaluation_sha256:
        return _bundle_validation("incompatible", "evaluation_hash_mismatch", metadata)
    try:
        evaluation = EvaluationArtifact.model_validate_json(
            Path(evaluation_path).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValidationError):
        return _bundle_validation("incompatible", "evaluation_invalid", metadata)
    expected_evaluation_identity = (
        metadata.artifact_type,
        metadata.task,
        metadata.dataset,
        metadata.dataset_contract.manifest_sha256,
        metadata.dataset_contract.data_content_sha256,
        metadata.dataset_contract.training_file_sha256,
        metadata.split_sha256,
    )
    actual_evaluation_identity = (
        evaluation.artifact_type,
        evaluation.task,
        evaluation.dataset,
        evaluation.dataset_manifest_sha256,
        evaluation.data_content_sha256,
        evaluation.training_file_sha256,
        evaluation.split_sha256,
    )
    if actual_evaluation_identity != expected_evaluation_identity:
        return _bundle_validation(
            "incompatible", "evaluation_contract_mismatch", metadata
        )
    return _bundle_validation("available", "bundle_valid", metadata)


def _status(
    *,
    artifact_type: Literal["outcome", "stage", "trend"] = "outcome",
    task: TaskName | None = None,
    status: Literal["available", "missing", "incompatible", "disabled"],
    reason_code: str,
    lifecycle_status: Literal["candidate", "reviewed", "enabled"] | None = None,
    metadata: ArtifactMetadata | None = None,
) -> ModelRuntimeStatus:
    identity = {}
    if metadata is not None:
        identity = {
            "task": metadata.task,
            "model_id": metadata.model_contract.model_id,
            "model_name": metadata.model_contract.model_name,
            "model_version": metadata.model_contract.model_version,
            "artifact_sha256": metadata.model_contract.artifact_sha256,
            "target": metadata.target,
            "horizon_days": metadata.horizon_days,
            "feature_version": metadata.feature_contract.feature_version,
            "score_semantics": metadata.score_contract.semantics,
            "calibration_status": metadata.calibration.status,
        }
    elif task is not None:
        identity["task"] = task
    return ModelRuntimeStatus(
        artifact_type=artifact_type,
        status=status,
        reason_code=reason_code,
        lifecycle_status=lifecycle_status,
        **identity,
    )


def _entry(
    status: ModelRuntimeStatus,
    *,
    metadata: ArtifactMetadata | None = None,
    model: Any | None = None,
) -> LoadedModelEntry:
    return LoadedModelEntry(status=status, metadata=metadata, model=model)


def _validation(
    status: ModelRuntimeStatus,
    *,
    metadata: ArtifactMetadata | None = None,
    model_path: Path | None = None,
    metadata_path: Path | None = None,
    release_path: Path | None = None,
) -> ArtifactValidationResult:
    return ArtifactValidationResult(
        status=status,
        metadata=metadata,
        model_path=str(model_path) if model_path is not None else None,
        metadata_path=str(metadata_path) if metadata_path is not None else None,
        release_path=str(release_path) if release_path is not None else None,
        prediction_executed=False,
    )


def _safe_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "metadata_invalid"
    if not isinstance(value, dict):
        return None, "metadata_invalid"
    return value, None


def _metadata_reason(raw: dict[str, Any], expected_task: TaskName | None) -> str | None:
    if raw.get("schema_version") != "longitudinal_outcome_artifact.v1":
        return "metadata_schema_mismatch"
    if raw.get("artifact_type") != "outcome":
        return "artifact_type_mismatch"
    raw_task = raw.get("task")
    if expected_task is not None and raw_task != expected_task:
        return "task_mismatch"
    if raw_task not in TASK_CONTRACTS:
        return "task_mismatch"
    contract = TASK_CONTRACTS[raw_task]
    if raw.get("dataset") != contract.dataset:
        return "dataset_mismatch"
    if raw.get("disease") != contract.disease:
        return "disease_mismatch"
    if raw.get("current_state") != contract.current_state:
        return "task_mismatch"
    if raw.get("target") != contract.target:
        return "target_mismatch"
    if raw.get("horizon_days") != contract.horizon_days:
        return "horizon_mismatch"

    features = raw.get("feature_contract")
    if not isinstance(features, dict):
        return "feature_schema_mismatch"
    if (
        features.get("schema_version") != "longitudinal_fixed_window_features.v1"
        or features.get("feature_version")
        != "longitudinal_fixed_window_features.v1"
    ):
        return "feature_schema_mismatch"
    names = features.get("feature_names")
    if not (
        isinstance(names, list)
        and names
        and all(isinstance(name, str) and name.strip() for name in names)
        and len(names) == len(set(names))
    ):
        return "feature_names_invalid"
    if features.get("feature_order_sha256") != feature_order_sha256(names):
        return "feature_order_mismatch"

    dataset_contract = raw.get("dataset_contract")
    if not isinstance(dataset_contract, dict) or any(
        not _valid_hash(dataset_contract.get(name))
        for name in (
            "manifest_sha256",
            "data_content_sha256",
            "training_file_sha256",
        )
    ):
        return "dataset_hash_mismatch"

    model_contract = raw.get("model_contract")
    if not isinstance(model_contract, dict) or not _valid_hash(
        model_contract.get("artifact_sha256")
    ):
        return "artifact_hash_mismatch"
    packages = model_contract.get("packages")
    current_packages = {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "scikit_learn": sklearn.__version__,
        "joblib": joblib.__version__,
        "numpy": numpy.__version__,
        "pandas": pandas.__version__,
    }
    if not isinstance(packages, dict) or any(
        packages.get(name) != version for name, version in current_packages.items()
    ):
        return "package_incompatible"

    score = raw.get("score_contract")
    calibration = raw.get("calibration")
    if not isinstance(score, dict) or score.get("semantics") not in {
        "model_score",
        "calibrated_probability",
    }:
        return "score_semantics_invalid"
    if score.get("positive_class") != 1:
        return "score_semantics_invalid"
    if not isinstance(calibration, dict):
        return "calibration_contract_invalid"
    if calibration.get("status") == "not_calibrated":
        if calibration.get("method") is not None or score.get("semantics") != "model_score":
            return "calibration_contract_invalid"
    elif calibration.get("status") == "calibrated":
        if not calibration.get("method") or score.get("semantics") != "calibrated_probability":
            return "calibration_contract_invalid"
    else:
        return "calibration_contract_invalid"
    return None


def _interface_reason(model: Any, metadata: ArtifactMetadata) -> str | None:
    if not callable(getattr(model, "predict_proba", None)):
        return "model_interface_incompatible"
    classes = getattr(model, "classes_", None)
    if classes is None or set(classes) != {0, 1}:
        return "model_interface_incompatible"
    named_steps = getattr(model, "named_steps", None)
    if not isinstance(named_steps, dict) or not {
        "preprocess",
        "classifier",
    }.issubset(named_steps):
        return "model_interface_incompatible"
    preprocess = named_steps["preprocess"]
    transformers = {
        name: (transformer, list(columns))
        for name, transformer, columns in getattr(preprocess, "transformers", [])
        if name in {"numeric", "sex"}
    }
    expected = metadata.feature_contract
    if set(transformers) != {"numeric", "sex"}:
        return "model_interface_incompatible"
    numeric, numeric_columns = transformers["numeric"]
    sex, sex_columns = transformers["sex"]
    if numeric_columns != expected.numeric_features or sex_columns != expected.categorical_features:
        return "model_interface_incompatible"
    numeric_steps = getattr(numeric, "named_steps", {})
    sex_steps = getattr(sex, "named_steps", {})
    imputer = numeric_steps.get("imputer")
    sex_imputer = sex_steps.get("imputer")
    onehot = sex_steps.get("onehot")
    if (
        getattr(imputer, "strategy", None) != "median"
        or getattr(imputer, "add_indicator", None) is not True
        or getattr(sex_imputer, "strategy", None) != "most_frequent"
        or getattr(onehot, "handle_unknown", None) != "ignore"
    ):
        return "model_interface_incompatible"
    return None


def _validate_files(
    model_path: Path,
    metadata_path: Path,
    *,
    expected_task: TaskName | None,
    lifecycle: Literal["candidate", "reviewed", "enabled"],
    enabled: bool,
    inspect_model: bool,
    release_path: Path | None = None,
) -> tuple[ArtifactValidationResult, Any | None]:
    task = expected_task
    if not model_path.is_file():
        return _validation(
            _status(task=task, status="missing", reason_code="artifact_missing"),
            model_path=model_path,
            metadata_path=metadata_path,
            release_path=release_path,
        ), None
    if not metadata_path.is_file():
        return _validation(
            _status(task=task, status="missing", reason_code="metadata_missing"),
            model_path=model_path,
            metadata_path=metadata_path,
            release_path=release_path,
        ), None
    raw, error = _safe_json(metadata_path)
    if error or raw is None:
        return _validation(
            _status(task=task, status="incompatible", reason_code="metadata_invalid"),
            model_path=model_path,
            metadata_path=metadata_path,
            release_path=release_path,
        ), None
    reason = _metadata_reason(raw, expected_task)
    if reason:
        return _validation(
            _status(task=task, status="incompatible", reason_code=reason),
            model_path=model_path,
            metadata_path=metadata_path,
            release_path=release_path,
        ), None
    raw_task = raw["task"]
    contract = TASK_CONTRACTS[raw_task]
    if (
        model_path.name != f"{contract.artifact_stem}.joblib"
        or metadata_path.name != f"{contract.artifact_stem}.meta.json"
    ):
        return _validation(
            _status(task=raw_task, status="incompatible", reason_code="filename_task_mismatch"),
            model_path=model_path,
            metadata_path=metadata_path,
            release_path=release_path,
        ), None
    if sha256_file(model_path) != raw["model_contract"]["artifact_sha256"]:
        return _validation(
            _status(task=raw_task, status="incompatible", reason_code="artifact_hash_mismatch"),
            model_path=model_path,
            metadata_path=metadata_path,
            release_path=release_path,
        ), None
    try:
        metadata = ArtifactMetadata.model_validate(raw)
    except ValidationError:
        return _validation(
            _status(task=raw_task, status="incompatible", reason_code="metadata_invalid"),
            model_path=model_path,
            metadata_path=metadata_path,
            release_path=release_path,
        ), None
    if lifecycle != "enabled":
        return _validation(
            _status(
                status="disabled",
                reason_code="lifecycle_not_enabled",
                lifecycle_status=lifecycle,
                metadata=metadata,
            ),
            metadata=metadata,
            model_path=model_path,
            metadata_path=metadata_path,
            release_path=release_path,
        ), None
    if not enabled:
        return _validation(
            _status(
                status="disabled",
                reason_code="production_disabled",
                lifecycle_status="enabled",
                metadata=metadata,
            ),
            metadata=metadata,
            model_path=model_path,
            metadata_path=metadata_path,
            release_path=release_path,
        ), None
    if not inspect_model:
        return _validation(
            _status(
                status="available",
                reason_code="artifact_available",
                lifecycle_status="enabled",
                metadata=metadata,
            ),
            metadata=metadata,
            model_path=model_path,
            metadata_path=metadata_path,
            release_path=release_path,
        ), None
    try:
        model = joblib.load(model_path)
    except Exception:
        return _validation(
            _status(
                status="incompatible",
                reason_code="artifact_load_failed",
                lifecycle_status="enabled",
                metadata=metadata,
            ),
            metadata=metadata,
            model_path=model_path,
            metadata_path=metadata_path,
            release_path=release_path,
        ), None
    reason = _interface_reason(model, metadata)
    if reason:
        return _validation(
            _status(
                status="incompatible",
                reason_code=reason,
                lifecycle_status="enabled",
                metadata=metadata,
            ),
            metadata=metadata,
            model_path=model_path,
            metadata_path=metadata_path,
            release_path=release_path,
        ), None
    return _validation(
        _status(
            status="available",
            reason_code="artifact_available",
            lifecycle_status="enabled",
            metadata=metadata,
        ),
        metadata=metadata,
        model_path=model_path,
        metadata_path=metadata_path,
        release_path=release_path,
    ), model


def validate_candidate_bundle(
    bundle_dir: Path, *, inspect_model: bool = True
) -> ArtifactValidationResult:
    directory = Path(bundle_dir)
    models = sorted(directory.glob("*.joblib")) if directory.is_dir() else []
    metadata_files = sorted(directory.glob("*.meta.json")) if directory.is_dir() else []
    if not models:
        return _validation(_status(status="missing", reason_code="artifact_missing"))
    if not metadata_files:
        return _validation(_status(status="missing", reason_code="metadata_missing"))
    if len(models) != 1 or len(metadata_files) != 1:
        return _validation(_status(status="incompatible", reason_code="metadata_invalid"))
    result, _ = _validate_files(
        models[0],
        metadata_files[0],
        expected_task=None,
        lifecycle="candidate",
        enabled=False,
        inspect_model=inspect_model,
    )
    return result


def _inside(root: Path, relative: str) -> Path | None:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def validate_release_record(
    release_path: Path, registry_root: Path, *, inspect_model: bool = True
) -> ArtifactValidationResult:
    root = Path(registry_root)
    path = Path(release_path)
    raw_release, error = _safe_json(path)
    if error or raw_release is None:
        return _validation(
            _status(status="incompatible", reason_code="metadata_invalid"),
            release_path=path,
        )
    expected_task = raw_release.get("task")
    if expected_task not in TASK_CONTRACTS:
        return _validation(
            _status(status="incompatible", reason_code="task_mismatch"),
            release_path=path,
        )
    try:
        release = ReleaseRecord.model_validate(raw_release)
    except ValidationError:
        return _validation(
            _status(task=expected_task, status="incompatible", reason_code="metadata_invalid"),
            release_path=path,
        )
    model_path = _inside(root, release.model_path)
    metadata_path = _inside(root, release.metadata_path)
    review_path = _inside(root, release.review_path)
    if model_path is None or metadata_path is None or review_path is None:
        return _validation(
            _status(task=release.task, status="incompatible", reason_code="registry_path_escape"),
            release_path=path,
        )
    if not model_path.is_file():
        return _validation(
            _status(task=release.task, status="missing", reason_code="artifact_missing"),
            model_path=model_path,
            metadata_path=metadata_path,
            release_path=path,
        )
    if not metadata_path.is_file():
        return _validation(
            _status(task=release.task, status="missing", reason_code="metadata_missing"),
            model_path=model_path,
            metadata_path=metadata_path,
            release_path=path,
        )
    if not review_path.is_file():
        return _validation(
            _status(task=release.task, status="missing", reason_code="review_record_missing"),
            model_path=model_path,
            metadata_path=metadata_path,
            release_path=path,
        )
    raw_metadata, metadata_error = _safe_json(metadata_path)
    if metadata_error or raw_metadata is None:
        return _validation(
            _status(
                task=release.task,
                status="incompatible",
                reason_code="metadata_invalid",
            ),
            model_path=model_path,
            metadata_path=metadata_path,
            release_path=path,
        )
    if sha256_file(model_path) != release.model_sha256:
        return _validation(
            _status(task=release.task, status="incompatible", reason_code="artifact_hash_mismatch"),
            model_path=model_path,
            metadata_path=metadata_path,
            release_path=path,
        )
    if sha256_file(metadata_path) != release.metadata_sha256:
        return _validation(
            _status(task=release.task, status="incompatible", reason_code="metadata_hash_mismatch"),
            model_path=model_path,
            metadata_path=metadata_path,
            release_path=path,
        )
    if sha256_file(review_path) != release.review_sha256:
        return _validation(
            _status(task=release.task, status="incompatible", reason_code="integrity_chain_broken"),
            model_path=model_path,
            metadata_path=metadata_path,
            release_path=path,
        )
    raw_review, review_error = _safe_json(review_path)
    if review_error or raw_review is None:
        return _validation(
            _status(task=release.task, status="incompatible", reason_code="integrity_chain_broken"),
            release_path=path,
        )
    try:
        review = ReviewRecord.model_validate(raw_review)
    except ValidationError:
        return _validation(
            _status(task=release.task, status="incompatible", reason_code="integrity_chain_broken"),
            release_path=path,
        )
    if (
        review.review_id != release.review_id
        or review.task != release.task
        or review.model_id != release.model_id
        or review.model_sha256 != release.model_sha256
        or review.metadata_sha256 != release.metadata_sha256
        or review.model_path != release.model_path
        or review.metadata_path != release.metadata_path
    ):
        return _validation(
            _status(task=release.task, status="incompatible", reason_code="integrity_chain_broken"),
            release_path=path,
        )
    result, _ = _validate_files(
        model_path,
        metadata_path,
        expected_task=release.task,
        lifecycle="enabled",
        enabled=release.production_enabled,
        inspect_model=inspect_model,
        release_path=path,
    )
    return result


def _candidate_for_task(task: TaskName, root: Path) -> Path | None:
    contract = TASK_CONTRACTS[task]
    candidates = [
        path.parent
        for path in (root / "bundles").glob(f"*/{contract.artifact_stem}.meta.json")
    ]
    return sorted(candidates)[0] if candidates else None


def _review_for_task(task: TaskName, root: Path) -> ReviewRecord | None:
    for path in sorted((root / "reviews").glob("*.json")):
        raw, error = _safe_json(path)
        if error or raw is None or raw.get("task") != task:
            continue
        try:
            return ReviewRecord.model_validate(raw)
        except ValidationError:
            continue
    return None


def _load_available_model(result: ArtifactValidationResult) -> Any | None:
    if result.status.status != "available" or result.model_path is None:
        return None
    try:
        return joblib.load(result.model_path)
    except Exception:
        return None


def load_task_model(
    task: TaskName, registry_root: Path, *, production: bool = True
) -> LoadedModelEntry:
    root = Path(registry_root)
    release_dir = root / "releases" / TASK_CONTRACTS[task].artifact_stem
    releases = sorted(release_dir.glob("*.json")) if release_dir.is_dir() else []
    if len(releases) > 1:
        return _entry(
            _status(
                task=task,
                status="incompatible",
                reason_code="multiple_enabled_artifacts",
            )
        )
    if len(releases) == 1:
        result = validate_release_record(releases[0], root, inspect_model=True)
        model = _load_available_model(result)
        if result.status.status == "available" and model is None:
            result = _validation(
                _status(
                    status="incompatible",
                    reason_code="artifact_load_failed",
                    lifecycle_status="enabled",
                    metadata=result.metadata,
                ),
                metadata=result.metadata,
            )
        return _entry(result.status, metadata=result.metadata, model=model)

    review = _review_for_task(task, root)
    if review is not None:
        metadata_path = _inside(root, review.metadata_path)
        model_path = _inside(root, review.model_path)
        if metadata_path is not None and model_path is not None:
            result, _ = _validate_files(
                model_path,
                metadata_path,
                expected_task=task,
                lifecycle="reviewed",
                enabled=False,
                inspect_model=True,
            )
            return _entry(result.status, metadata=result.metadata)
    candidate = _candidate_for_task(task, root)
    if candidate is not None:
        result = validate_candidate_bundle(candidate, inspect_model=True)
        return _entry(result.status, metadata=result.metadata)
    return _entry(
        _status(task=task, status="missing", reason_code="release_record_missing")
    )


def empty_optional_model_status(
    artifact_type: Literal["stage", "trend"], reason_code: str
) -> ModelRuntimeStatus:
    return _status(
        artifact_type=artifact_type,
        status="missing",
        reason_code=reason_code,
    )


def load_model_registry(
    dataset: str,
    registry_root: Path | str | None = None,
    *,
    production: bool = True,
    model_dir: Path | str | None = None,
) -> LongitudinalModelRegistry:
    if dataset not in {"fatty_liver", "ad"}:
        raise ValueError("unsupported longitudinal dataset")
    root = Path(registry_root or model_dir or MODEL_DIR)
    tasks = {
        task: load_task_model(task, root, production=production)
        for task, contract in TASK_CONTRACTS.items()
        if contract.dataset == dataset
    }
    return LongitudinalModelRegistry(
        dataset=dataset,
        outcomes=tasks,
        stage=empty_optional_model_status("stage", "stage_model_missing"),
        trend=empty_optional_model_status("trend", "trend_model_missing"),
    )


def _suite_entry_from_bundle(
    bundle: dict[str, Any],
    root: Path,
) -> SuiteModelEntry:
    artifact_type = str(bundle.get("artifact_type", ""))
    task = str(bundle.get("task", ""))
    if artifact_type not in {"outcome", "stage", "trend"} or not task:
        raise ValueError("release_set_bundle_invalid")
    paths = {}
    for name in (
        "model_path",
        "metadata_path",
        "evaluation_path",
        "manifest_path",
    ):
        relative = bundle.get(name)
        if not isinstance(relative, str):
            raise ValueError("release_set_bundle_invalid")
        resolved = _inside(root, relative)
        if resolved is None:
            raise ValueError("registry_path_escape")
        paths[name] = resolved
    validation = validate_bundle_files(
        model_path=paths["model_path"],
        metadata_path=paths["metadata_path"],
        evaluation_path=paths["evaluation_path"],
        manifest_path=paths["manifest_path"],
    )
    metadata = validation.metadata
    if metadata is None:
        return SuiteModelEntry(
            status=ModelRuntimeStatus(
                artifact_type=artifact_type,
                task=task,
                status=validation.status.status,
                reason_code=validation.status.reason_code,
            )
        )
    if metadata.task != task or metadata.artifact_type != artifact_type:
        return SuiteModelEntry(
            status=ModelRuntimeStatus(
                artifact_type=artifact_type,
                task=task,
                status="incompatible",
                reason_code="release_set_bundle_mismatch",
            ),
            metadata=metadata,
        )
    if validation.status.status != "available":
        return SuiteModelEntry(
            status=ModelRuntimeStatus(
                artifact_type=artifact_type,
                task=task,
                status=validation.status.status,
                reason_code=validation.status.reason_code,
                model_id=metadata.model_contract.model_id,
                model_name=metadata.model_contract.model_name,
                model_version=metadata.model_contract.model_version,
                artifact_sha256=metadata.model_contract.artifact_sha256,
                target=metadata.target,
                horizon_days=metadata.horizon.value,
                feature_version=metadata.feature_contract.feature_version,
                score_semantics=metadata.output_contract.score_semantics,
                calibration_status=metadata.calibration.status,
            ),
            metadata=metadata,
        )
    try:
        model = joblib.load(paths["model_path"])
    except Exception:
        return SuiteModelEntry(
            status=ModelRuntimeStatus(
                artifact_type=artifact_type,
                task=task,
                status="incompatible",
                reason_code="artifact_load_failed",
            ),
            metadata=metadata,
        )
    status = ModelRuntimeStatus(
        artifact_type=artifact_type,
        task=task,
        status="available",
        reason_code="artifact_available",
        lifecycle_status="enabled",
        model_id=metadata.model_contract.model_id,
        model_name=metadata.model_contract.model_name,
        model_version=metadata.model_contract.model_version,
        artifact_sha256=metadata.model_contract.artifact_sha256,
        target=metadata.target,
        horizon_days=metadata.horizon.value,
        feature_version=metadata.feature_contract.feature_version,
        score_semantics=metadata.output_contract.score_semantics,
        calibration_status=metadata.calibration.status,
    )
    return SuiteModelEntry(status=status, metadata=metadata, model=model)


def load_disease_model_suite(
    dataset: str,
    registry_root: Path | str,
) -> LoadedDiseaseModelSuite:
    root = Path(registry_root).resolve()
    release_set = load_disease_release_set(dataset, root)
    outcomes: dict[str, SuiteModelEntry] = {}
    stage: SuiteModelEntry | None = None
    trends: dict[str, SuiteModelEntry] = {}
    for bundle in release_set.bundles:
        entry = _suite_entry_from_bundle(bundle, root)
        artifact_type = str(bundle.get("artifact_type"))
        if artifact_type == "outcome":
            outcomes[str(bundle["task"])] = entry
        elif artifact_type == "stage":
            if stage is not None:
                raise ValueError("multiple_stage_bundles")
            stage = entry
        else:
            indicator = bundle.get("indicator")
            if not isinstance(indicator, str) or not indicator:
                raise ValueError("trend_indicator_missing")
            trends[indicator] = entry
    if stage is None:
        raise ValueError("required_bundle_missing")
    return LoadedDiseaseModelSuite(
        dataset=dataset,
        release_set_id=release_set.release_set_id,
        release_set_sha256=release_set.record_sha256,
        data_release_id=release_set.data_release_id,
        split_sha256=release_set.split_sha256,
        outcomes=outcomes,
        stage=stage,
        trends=trends,
    )


def load_active_model_registry(
    dataset: str,
    registry_root: Path | str | None = None,
):
    root = Path(registry_root or MODEL_DIR)
    active_pointer = root / "active" / f"{dataset}.json"
    if active_pointer.exists():
        try:
            pointer_payload = json.loads(active_pointer.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            pointer_payload = None
        if isinstance(pointer_payload, dict) and pointer_payload.get("status") == "inactive":
            return load_model_registry(dataset, registry_root=root)
        return load_disease_model_suite(dataset, root)
    return load_model_registry(dataset, registry_root=root)
