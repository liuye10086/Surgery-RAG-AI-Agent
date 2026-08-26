from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.longitudinal_model_registry import (
    ARTIFACT_METADATA_SCHEMA_VERSION,
    RELEASE_RECORD_SCHEMA_VERSION,
    REVIEW_RECORD_SCHEMA_VERSION,
    TASK_CONTRACTS,
    ArtifactMetadata,
    ModelRuntimeStatus,
    ReleaseRecord,
    ReviewRecord,
)
from app.services.longitudinal_model_registry import load_model_registry


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_candidate_bundle(root: Path, task="ad.pre_dementia_to_dementia"):
    import joblib
    import pandas as pd
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    contract = TASK_CONTRACTS[task]
    bundle = root / "bundles" / f"{contract.artifact_stem}-model"
    bundle.mkdir(parents=True)
    model_path = bundle / f"{contract.artifact_stem}.joblib"
    metadata_path = bundle / f"{contract.artifact_stem}.meta.json"
    preprocess = ColumnTransformer(
        [
            (
                "numeric",
                Pipeline(
                    [
                        (
                            "imputer",
                            SimpleImputer(
                                strategy="median",
                                add_indicator=True,
                                keep_empty_features=True,
                            ),
                        ),
                        ("scaler", StandardScaler()),
                    ]
                ),
                ["age", "visit_count"],
            ),
            (
                "sex",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                ["sex"],
            ),
        ],
        remainder="drop",
    )
    model = Pipeline(
        [
            ("preprocess", preprocess),
            ("classifier", LogisticRegression(random_state=42)),
        ]
    )
    model.fit(
        pd.DataFrame(
            [
                {"age": 50, "visit_count": 3, "sex": "female"},
                {"age": 70, "visit_count": 4, "sex": "male"},
                {"age": 55, "visit_count": 5, "sex": "female"},
                {"age": 75, "visit_count": 6, "sex": "male"},
            ]
        ),
        [0, 1, 0, 1],
    )
    joblib.dump(model, model_path)
    metadata = ArtifactMetadata.model_validate(
        _valid_artifact_metadata(
            task=task,
            dataset=contract.dataset,
            disease=contract.disease,
            current_state=contract.current_state,
            target=contract.target,
        )
    )
    metadata.model_contract.artifact_sha256 = _sha256(model_path)
    metadata.model_contract.model_id = f"{contract.artifact_stem}-model"
    metadata_path.write_text(metadata.model_dump_json(indent=2), encoding="utf-8")
    return bundle, model_path, metadata_path, metadata


def _write_enabled_release(root: Path, task="ad.pre_dementia_to_dementia", suffix="one"):
    bundle, model_path, metadata_path, metadata = _write_candidate_bundle(
        root / suffix, task
    )
    target_bundle = root / "bundles" / metadata.model_contract.model_id
    target_bundle.parent.mkdir(parents=True, exist_ok=True)
    if target_bundle.exists():
        raise FileExistsError(target_bundle)
    bundle.rename(target_bundle)
    model_path = target_bundle / model_path.name
    metadata_path = target_bundle / metadata_path.name
    review = ReviewRecord.model_validate(
        _valid_review_record(
            review_id=f"review-{suffix}",
            task=task,
            model_id=metadata.model_contract.model_id,
            model_sha256=_sha256(model_path),
            metadata_sha256=_sha256(metadata_path),
            model_path=model_path.relative_to(root).as_posix(),
            metadata_path=metadata_path.relative_to(root).as_posix(),
        )
    )
    review_path = root / "reviews" / f"review-{suffix}.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(review.model_dump_json(indent=2), encoding="utf-8")
    release = ReleaseRecord.model_validate(
        _valid_release_record(
            release_id=f"release-{suffix}",
            review_id=review.review_id,
            task=task,
            model_id=metadata.model_contract.model_id,
            model_sha256=_sha256(model_path),
            metadata_sha256=_sha256(metadata_path),
            review_sha256=_sha256(review_path),
            model_path=model_path.relative_to(root).as_posix(),
            metadata_path=metadata_path.relative_to(root).as_posix(),
            review_path=review_path.relative_to(root).as_posix(),
        )
    )
    release_dir = root / "releases" / TASK_CONTRACTS[task].artifact_stem
    release_dir.mkdir(parents=True, exist_ok=True)
    release_path = release_dir / f"release-{suffix}.json"
    release_path.write_text(release.model_dump_json(indent=2), encoding="utf-8")
    return release_path, model_path, metadata_path


def _rewrite_release_chain(root: Path, release_path: Path, mutate_metadata):
    release = json.loads(release_path.read_text(encoding="utf-8"))
    metadata_path = root / release["metadata_path"]
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    mutate_metadata(metadata)
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    review_path = root / release["review_path"]
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["metadata_sha256"] = _sha256(metadata_path)
    review_path.write_text(json.dumps(review), encoding="utf-8")
    release["metadata_sha256"] = _sha256(metadata_path)
    release["review_sha256"] = _sha256(review_path)
    release_path.write_text(json.dumps(release), encoding="utf-8")


def _candidate_only_registry(root: Path):
    bundle, _, _, metadata = _write_candidate_bundle(root)
    target = root / "bundles" / metadata.model_contract.model_id
    target.parent.mkdir(parents=True, exist_ok=True)
    bundle.rename(target)
    return target


def _reviewed_only_registry(root: Path):
    bundle = _candidate_only_registry(root)
    metadata_path = next(bundle.glob("*.meta.json"))
    model_path = next(bundle.glob("*.joblib"))
    metadata = ArtifactMetadata.model_validate_json(
        metadata_path.read_text(encoding="utf-8")
    )
    review = ReviewRecord.model_validate(
        _valid_review_record(
            model_id=metadata.model_contract.model_id,
            model_sha256=_sha256(model_path),
            metadata_sha256=_sha256(metadata_path),
            model_path=model_path.relative_to(root).as_posix(),
            metadata_path=metadata_path.relative_to(root).as_posix(),
        )
    )
    review_path = root / "reviews" / "review-ad-001.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(review.model_dump_json(indent=2), encoding="utf-8")
    return review_path


def _valid_artifact_metadata(**overrides):
    feature_names = ["age", "visit_count", "sex"]
    feature_hash = hashlib.sha256(
        json.dumps(feature_names, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    payload = {
        "schema_version": ARTIFACT_METADATA_SCHEMA_VERSION,
        "artifact_type": "outcome",
        "task": "ad.pre_dementia_to_dementia",
        "dataset": "ad",
        "disease": "阿尔茨海默病",
        "current_state": "pre_dementia",
        "target": "dementia",
        "horizon_days": 365,
        "feature_contract": {
            "schema_version": "longitudinal_fixed_window_features.v1",
            "feature_version": "longitudinal_fixed_window_features.v1",
            "feature_names": feature_names,
            "feature_order_sha256": feature_hash,
            "numeric_features": ["age", "visit_count"],
            "categorical_features": ["sex"],
            "required_features": ["visit_count"],
            "allowed_missing_features": ["age", "sex"],
            "input_container": "pandas_dataframe",
            "numeric_imputation": "median_add_indicator",
            "categorical_imputation": "most_frequent",
        },
        "dataset_contract": {
            "schema_version": "longitudinal_fixed_window_dataset.v1",
            "manifest_sha256": "b" * 64,
            "data_content_sha256": "c" * 64,
            "training_file_sha256": "d" * 64,
        },
        "model_contract": {
            "model_id": "ad-pre-dementia-" + "e" * 12,
            "model_name": "logistic_regression",
            "model_version": "2026.08.26.1",
            "algorithm": "logistic_regression",
            "artifact_sha256": "e" * 64,
            "packages": {
                "python": "3.11",
                "scikit_learn": "1.9.0",
                "joblib": "1.5.3",
                "numpy": "2.3.5",
                "pandas": "3.0.3",
            },
        },
        "score_contract": {
            "semantics": "model_score",
            "positive_class": 1,
            "threshold": 0.5,
            "minimum": 0.0,
            "maximum": 1.0,
        },
        "calibration": {"status": "not_calibrated", "method": None},
        "audit": {
            "leakage_status": "passed",
            "clinical_validity_claim": False,
            "code_version": "6bf7fdf",
        },
        "status": "candidate",
        "production_enabled": False,
        "created_at": "2026-08-26T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def _valid_review_record(**overrides):
    payload = {
        "schema_version": REVIEW_RECORD_SCHEMA_VERSION,
        "review_id": "review-ad-001",
        "task": "ad.pre_dementia_to_dementia",
        "model_id": "ad-pre-dementia-" + "e" * 12,
        "status": "reviewed",
        "production_enabled": False,
        "reviewer": "owner-1",
        "reviewed_at": datetime(2026, 8, 26, tzinfo=timezone.utc),
        "note": "contract reviewed",
        "model_sha256": "e" * 64,
        "metadata_sha256": "f" * 64,
        "model_path": "bundles/model/model.joblib",
        "metadata_path": "bundles/model/model.meta.json",
    }
    payload.update(overrides)
    return payload


def _valid_release_record(**overrides):
    payload = {
        "schema_version": RELEASE_RECORD_SCHEMA_VERSION,
        "release_id": "release-ad-001",
        "review_id": "review-ad-001",
        "task": "ad.pre_dementia_to_dementia",
        "model_id": "ad-pre-dementia-" + "e" * 12,
        "status": "enabled",
        "production_enabled": True,
        "enabled_by": "owner-1",
        "enabled_at": datetime(2026, 8, 26, 1, tzinfo=timezone.utc),
        "model_sha256": "e" * 64,
        "metadata_sha256": "f" * 64,
        "review_sha256": "1" * 64,
        "model_path": "bundles/model/model.joblib",
        "metadata_path": "bundles/model/model.meta.json",
        "review_path": "reviews/review-ad-001.json",
    }
    payload.update(overrides)
    return payload


def test_registry_task_contracts_are_exact():
    assert set(TASK_CONTRACTS) == {
        "fatty_liver.pre_cirrhosis_to_progression",
        "fatty_liver.cirrhosis_to_hcc",
        "ad.pre_dementia_to_dementia",
    }
    assert TASK_CONTRACTS["fatty_liver.cirrhosis_to_hcc"].target == "hcc"
    assert TASK_CONTRACTS["ad.pre_dementia_to_dementia"].horizon_days == 365


def test_runtime_status_does_not_accept_lifecycle_values():
    with pytest.raises(ValidationError):
        ModelRuntimeStatus(
            artifact_type="outcome",
            status="candidate",
            reason_code="lifecycle_not_enabled",
        )


def test_candidate_metadata_cannot_claim_reviewed_or_enabled_lifecycle():
    with pytest.raises(ValidationError):
        ArtifactMetadata.model_validate(
            _valid_artifact_metadata(status="enabled", production_enabled=True)
        )


def test_review_and_release_records_own_later_lifecycle_states():
    review = ReviewRecord.model_validate(_valid_review_record())
    release = ReleaseRecord.model_validate(_valid_release_record())
    assert (review.status, review.production_enabled) == ("reviewed", False)
    assert (release.status, release.production_enabled) == ("enabled", True)


def test_artifact_metadata_rejects_task_owned_field_mismatch():
    with pytest.raises(ValidationError):
        ArtifactMetadata.model_validate(_valid_artifact_metadata(target="hcc"))


def test_uncalibrated_artifact_cannot_claim_probability_semantics():
    payload = _valid_artifact_metadata()
    payload["score_contract"]["semantics"] = "clinical_probability"
    with pytest.raises(ValidationError):
        ArtifactMetadata.model_validate(payload)


def test_missing_longitudinal_artifacts_degrade_to_explicit_empty_registry(tmp_path):
    registry = load_model_registry("fatty_liver", registry_root=tmp_path)
    assert set(registry.outcomes) == {
        "fatty_liver.pre_cirrhosis_to_progression",
        "fatty_liver.cirrhosis_to_hcc",
    }
    assert all(entry.status.status == "missing" for entry in registry.outcomes.values())
    assert all(
        entry.status.reason_code == "release_record_missing"
        for entry in registry.outcomes.values()
    )


def test_legacy_progression_artifacts_remain_ignored_by_longitudinal_registry(tmp_path):
    (tmp_path / "fatty_liver_progression_model.joblib").write_bytes(b"legacy")
    (tmp_path / "fatty_liver_progression_model.meta.json").write_text("{}", encoding="utf-8")
    registry = load_model_registry("fatty_liver", registry_root=tmp_path)
    assert all(entry.status.status == "missing" for entry in registry.outcomes.values())


def test_candidate_bundle_is_valid_but_disabled_for_production(tmp_path):
    from app.services.longitudinal_model_registry import validate_candidate_bundle

    bundle, _, _, _ = _write_candidate_bundle(tmp_path)
    result = validate_candidate_bundle(bundle)
    assert result.status.status == "disabled"
    assert result.status.lifecycle_status == "candidate"
    assert result.status.reason_code == "lifecycle_not_enabled"
    assert result.prediction_executed is False


def test_candidate_and_reviewed_registry_entries_are_refused_by_production(tmp_path):
    from app.services.longitudinal_model_registry import load_task_model

    candidate_root = tmp_path / "candidate"
    _candidate_only_registry(candidate_root)
    candidate = load_task_model("ad.pre_dementia_to_dementia", candidate_root)
    assert (candidate.status.status, candidate.status.lifecycle_status) == (
        "disabled",
        "candidate",
    )
    assert candidate.status.reason_code == "lifecycle_not_enabled"

    reviewed_root = tmp_path / "reviewed"
    _reviewed_only_registry(reviewed_root)
    reviewed = load_task_model("ad.pre_dementia_to_dementia", reviewed_root)
    assert (reviewed.status.status, reviewed.status.lifecycle_status) == (
        "disabled",
        "reviewed",
    )
    assert reviewed.status.reason_code == "lifecycle_not_enabled"


def test_enabled_release_loads_with_complete_runtime_identity(tmp_path):
    from app.services.longitudinal_model_registry import load_task_model

    _write_enabled_release(tmp_path)
    entry = load_task_model("ad.pre_dementia_to_dementia", tmp_path)
    assert entry.status.status == "available"
    assert entry.status.lifecycle_status == "enabled"
    assert entry.status.task == "ad.pre_dementia_to_dementia"
    assert entry.status.model_version == "2026.08.26.1"
    assert entry.status.artifact_sha256 == entry.metadata.model_contract.artifact_sha256
    assert entry.model is not None


def test_artifact_hash_mismatch_is_rejected_before_loading(tmp_path, monkeypatch):
    import joblib
    from app.services.longitudinal_model_registry import load_task_model

    _, model_path, _ = _write_enabled_release(tmp_path)
    model_path.write_bytes(model_path.read_bytes() + b"tampered")
    monkeypatch.setattr(joblib, "load", lambda _: pytest.fail("artifact was loaded"))
    entry = load_task_model("ad.pre_dementia_to_dementia", tmp_path)
    assert entry.status.status == "incompatible"
    assert entry.status.reason_code == "artifact_hash_mismatch"
    assert entry.model is None


def test_multiple_enabled_release_records_reject_the_whole_task(tmp_path):
    from app.services.longitudinal_model_registry import load_task_model

    first, _, _ = _write_enabled_release(tmp_path, suffix="one")
    second = first.with_name("release-two.json")
    payload = json.loads(first.read_text(encoding="utf-8"))
    payload["release_id"] = "release-two"
    second.write_text(json.dumps(payload), encoding="utf-8")
    entry = load_task_model("ad.pre_dementia_to_dementia", tmp_path)
    assert entry.status.status == "incompatible"
    assert entry.status.reason_code == "multiple_enabled_artifacts"
    assert entry.model is None


def test_static_validation_never_executes_prediction(tmp_path):
    from app.services.longitudinal_model_registry import validate_release_record

    release_path, _, _ = _write_enabled_release(tmp_path)
    result = validate_release_record(release_path, tmp_path)
    assert result.status.status == "available"
    assert result.prediction_executed is False


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda data: data.update(schema_version="wrong"), "metadata_schema_mismatch"),
        (lambda data: data.update(artifact_type="trend"), "artifact_type_mismatch"),
        (lambda data: data.update(task="fatty_liver.cirrhosis_to_hcc"), "task_mismatch"),
        (lambda data: data.update(dataset="fatty_liver"), "dataset_mismatch"),
        (lambda data: data.update(disease="脂肪肝"), "disease_mismatch"),
        (lambda data: data.update(target="hcc"), "target_mismatch"),
        (lambda data: data.update(horizon_days=180), "horizon_mismatch"),
        (
            lambda data: data["feature_contract"].update(feature_version="wrong"),
            "feature_schema_mismatch",
        ),
        (
            lambda data: data["feature_contract"].update(
                feature_names=["age", "age", "sex"]
            ),
            "feature_names_invalid",
        ),
        (
            lambda data: data["feature_contract"].update(
                feature_order_sha256="0" * 64
            ),
            "feature_order_mismatch",
        ),
        (
            lambda data: data["dataset_contract"].update(
                manifest_sha256="bad"
            ),
            "dataset_hash_mismatch",
        ),
        (
            lambda data: data["model_contract"]["packages"].update(
                scikit_learn="0.0.0"
            ),
            "package_incompatible",
        ),
        (
            lambda data: data["score_contract"].update(
                semantics="clinical_probability"
            ),
            "score_semantics_invalid",
        ),
        (
            lambda data: data.update(
                calibration={"status": "calibrated", "method": None}
            ),
            "calibration_contract_invalid",
        ),
    ],
)
def test_release_contract_mismatches_have_stable_reasons(tmp_path, mutation, reason):
    from app.services.longitudinal_model_registry import load_task_model

    release_path, _, _ = _write_enabled_release(tmp_path)
    _rewrite_release_chain(tmp_path, release_path, mutation)
    entry = load_task_model("ad.pre_dementia_to_dementia", tmp_path)
    assert entry.status.status == "incompatible"
    assert entry.status.reason_code == reason
    assert entry.model is None


def test_missing_or_damaged_metadata_has_stable_reason(tmp_path):
    from app.services.longitudinal_model_registry import load_task_model

    missing_root = tmp_path / "missing"
    _, _, metadata_path = _write_enabled_release(missing_root)
    metadata_path.unlink()
    missing = load_task_model("ad.pre_dementia_to_dementia", missing_root)
    assert (missing.status.status, missing.status.reason_code) == (
        "missing",
        "metadata_missing",
    )

    broken_root = tmp_path / "broken"
    _, _, metadata_path = _write_enabled_release(broken_root)
    metadata_path.write_text("{broken", encoding="utf-8")
    broken = load_task_model("ad.pre_dementia_to_dementia", broken_root)
    assert (broken.status.status, broken.status.reason_code) == (
        "incompatible",
        "metadata_invalid",
    )


def test_release_can_be_explicitly_disabled(tmp_path):
    from app.services.longitudinal_model_registry import load_task_model

    release_path, _, _ = _write_enabled_release(tmp_path)
    payload = json.loads(release_path.read_text(encoding="utf-8"))
    payload["production_enabled"] = False
    release_path.write_text(json.dumps(payload), encoding="utf-8")
    entry = load_task_model("ad.pre_dementia_to_dementia", tmp_path)
    assert (entry.status.status, entry.status.reason_code) == (
        "disabled",
        "production_disabled",
    )
