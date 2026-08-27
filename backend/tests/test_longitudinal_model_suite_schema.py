from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError


def _feature_contract() -> dict:
    from app.schemas.longitudinal_model_registry import feature_order_sha256

    names = ["age", "visit_count", "sex"]
    return {
        "schema_version": "longitudinal_fixed_window_features.v1",
        "feature_version": "longitudinal_fixed_window_features.v1",
        "feature_names": names,
        "feature_order_sha256": feature_order_sha256(names),
        "numeric_features": ["age", "visit_count"],
        "categorical_features": ["sex"],
        "required_features": ["visit_count"],
        "allowed_missing_features": ["age", "sex"],
        "input_container": "pandas_dataframe",
        "numeric_imputation": "median_add_indicator",
        "categorical_imputation": "most_frequent",
    }


def _output_contract(artifact_type: str) -> dict:
    if artifact_type == "outcome":
        return {
            "kind": "binary",
            "classes": ["no_event", "event"],
            "positive_class": "event",
            "threshold": 0.5,
            "score_semantics": "model_score",
        }
    if artifact_type == "stage":
        return {
            "kind": "multiclass",
            "classes": ["current", "next", "advanced"],
            "ordered": True,
            "score_semantics": "model_score",
        }
    return {
        "kind": "multiclass",
        "classes": ["rising", "stable", "falling"],
        "ordered": False,
        "score_semantics": "model_score",
    }


def valid_metadata(artifact_type: str) -> dict:
    return {
        "schema_version": "longitudinal_model_artifact.v2",
        "artifact_type": artifact_type,
        "task": f"ad.{artifact_type}.fixture",
        "dataset": "ad",
        "target": "dementia" if artifact_type == "outcome" else artifact_type,
        "horizon": {"kind": "days", "value": 365},
        "feature_contract": _feature_contract(),
        "dataset_contract": {
            "schema_version": "longitudinal_fixed_window_dataset.v1",
            "manifest_sha256": "a" * 64,
            "data_content_sha256": "b" * 64,
            "training_file": "ad/real_train.jsonl",
            "training_file_sha256": "c" * 64,
        },
        "split_sha256": "d" * 64,
        "evaluation_sha256": "e" * 64,
        "model_contract": {
            "model_id": f"ad-{artifact_type}-fixture",
            "model_name": "logistic_regression",
            "model_version": "2026.08.27.1",
            "algorithm": "logistic_regression",
            "artifact_sha256": "f" * 64,
            "packages": {
                "python": "3.11",
                "scikit_learn": "1.9.0",
                "joblib": "1.5.3",
                "numpy": "2.3.5",
                "pandas": "3.0.3",
            },
        },
        "output_contract": _output_contract(artifact_type),
        "calibration": {"status": "not_calibrated", "method": None},
        "audit": {
            "leakage_status": "passed",
            "locked_test_used_for_selection": False,
            "synthetic_in_formal_metrics": False,
            "clinical_validity_claim": False,
            "code_version": "661478c",
        },
        "status": "candidate",
        "production_enabled": False,
        "created_at": "2026-08-27T00:00:00Z",
    }


@pytest.mark.parametrize("artifact_type", ["outcome", "stage", "trend"])
def test_v2_metadata_requires_evaluation_and_split_hashes(artifact_type):
    from app.schemas.longitudinal_model_suite import ArtifactMetadataV2

    payload = valid_metadata(artifact_type)
    payload["evaluation_sha256"] = None
    with pytest.raises(ValidationError):
        ArtifactMetadataV2.model_validate(payload)

    payload = valid_metadata(artifact_type)
    payload["split_sha256"] = None
    with pytest.raises(ValidationError):
        ArtifactMetadataV2.model_validate(payload)


def test_uncalibrated_scores_cannot_claim_probability():
    from app.schemas.longitudinal_model_suite import ArtifactMetadataV2

    payload = valid_metadata("stage")
    payload["output_contract"]["score_semantics"] = "calibrated_probability"
    payload["calibration"] = {"status": "not_calibrated", "method": None}
    with pytest.raises(ValidationError):
        ArtifactMetadataV2.model_validate(payload)


def test_synthetic_metrics_require_explicit_demonstration_audit():
    from app.schemas.longitudinal_model_suite import ArtifactMetadataV2

    payload = valid_metadata("outcome")
    payload["audit"]["synthetic_in_formal_metrics"] = True
    with pytest.raises(ValidationError):
        ArtifactMetadataV2.model_validate(payload)

    payload["audit"].update(
        leakage_status="review_required",
        synthetic_purpose="demonstration_training_only",
    )
    metadata = ArtifactMetadataV2.model_validate(payload)
    assert metadata.audit.synthetic_in_formal_metrics is True
    assert metadata.audit.clinical_validity_claim is False
    assert metadata.audit.synthetic_purpose == "demonstration_training_only"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_bundle_validation_rejects_training_hash_not_found_in_manifest(tmp_path):
    from app.schemas.longitudinal_model_suite import ArtifactMetadataV2
    from app.services.longitudinal_model_registry import validate_bundle_files

    dataset_dir = tmp_path / "dataset"
    (dataset_dir / "ad").mkdir(parents=True)
    training_path = dataset_dir / "ad" / "real_train.jsonl"
    training_path.write_text("{}\n", encoding="utf-8")
    split_path = dataset_dir / "group_splits.json"
    split_path.write_text("{}\n", encoding="utf-8")
    stable = {
        "schema_version": "longitudinal_fixed_window_dataset.v1",
        "minimum_visits": 3,
        "horizon_days": 365,
        "summary": {},
        "files": {
            "ad/real_train.jsonl": _sha256(training_path),
            "group_splits.json": _sha256(split_path),
        },
    }
    stable["data_content_sha256"] = hashlib.sha256(
        json.dumps(
            {key: stable[key] for key in ("schema_version", "minimum_visits", "horizon_days", "summary", "files")},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    stable["group_split_file"] = "group_splits.json"
    stable["group_split_sha256"] = _sha256(split_path)
    manifest_path = dataset_dir / "manifest.json"
    manifest_path.write_text(json.dumps(stable), encoding="utf-8")

    model_path = tmp_path / "model.joblib"
    model_path.write_bytes(b"model")
    evaluation_path = tmp_path / "evaluation.json"
    evaluation_path.write_text("{}", encoding="utf-8")
    metadata_payload = valid_metadata("outcome")
    metadata_payload["dataset_contract"].update(
        manifest_sha256=_sha256(manifest_path),
        data_content_sha256=stable["data_content_sha256"],
        training_file_sha256="f" * 64,
    )
    metadata_payload["split_sha256"] = _sha256(split_path)
    metadata_payload["evaluation_sha256"] = _sha256(evaluation_path)
    metadata_payload["model_contract"]["artifact_sha256"] = _sha256(model_path)
    metadata = ArtifactMetadataV2.model_validate(metadata_payload)
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(metadata.model_dump_json(), encoding="utf-8")

    result = validate_bundle_files(
        model_path=model_path,
        metadata_path=metadata_path,
        evaluation_path=evaluation_path,
        manifest_path=manifest_path,
    )

    assert result.status.reason_code == "training_file_hash_mismatch"


def test_bundle_validation_uses_disease_split_identity_not_split_file_hash(tmp_path):
    from app.schemas.longitudinal_model_suite import (
        ArtifactMetadataV2,
        EvaluationArtifact,
    )
    from app.services.longitudinal_model_registry import validate_bundle_files

    dataset_dir = tmp_path / "dataset"
    (dataset_dir / "ad").mkdir(parents=True)
    training_path = dataset_dir / "ad" / "real_train.jsonl"
    training_path.write_text("{}\n", encoding="utf-8")
    disease_split_sha = "d" * 64
    split_path = dataset_dir / "group_splits.json"
    split_path.write_text(
        json.dumps(
            {
                "schema_version": "longitudinal_disease_group_splits.v1",
                "splits": [{"disease": "ad", "sha256": disease_split_sha}],
            }
        ),
        encoding="utf-8",
    )
    files = {
        "ad/real_train.jsonl": _sha256(training_path),
        "group_splits.json": _sha256(split_path),
    }
    stable = {
        "schema_version": "longitudinal_fixed_window_dataset.v1",
        "minimum_visits": 3,
        "horizon_days": 365,
        "summary": {},
        "files": files,
    }
    stable["data_content_sha256"] = hashlib.sha256(
        json.dumps(
            stable,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    stable["group_split_file"] = "group_splits.json"
    stable["group_split_sha256"] = _sha256(split_path)
    manifest_path = dataset_dir / "manifest.json"
    manifest_path.write_text(json.dumps(stable), encoding="utf-8")

    model_path = tmp_path / "model.joblib"
    model_path.write_bytes(b"model")
    evaluation_payload = {
        "artifact_type": "outcome",
        "task": "ad.outcome.fixture",
        "dataset": "ad",
        "dataset_manifest_sha256": _sha256(manifest_path),
        "data_content_sha256": stable["data_content_sha256"],
        "training_file_sha256": _sha256(training_path),
        "split_sha256": disease_split_sha,
        "selection_metrics": {},
        "locked_test_metrics": {},
        "baselines": {},
        "class_support": {},
        "locked_test_used_for_selection": False,
    }
    evaluation = EvaluationArtifact.model_validate(evaluation_payload)
    evaluation_path = tmp_path / "evaluation.json"
    evaluation_path.write_text(evaluation.model_dump_json(), encoding="utf-8")
    metadata_payload = valid_metadata("outcome")
    metadata_payload.update(
        task="ad.outcome.fixture",
        split_sha256=disease_split_sha,
        evaluation_sha256=_sha256(evaluation_path),
    )
    metadata_payload["dataset_contract"].update(
        manifest_sha256=_sha256(manifest_path),
        data_content_sha256=stable["data_content_sha256"],
        training_file_sha256=_sha256(training_path),
    )
    metadata_payload["model_contract"]["artifact_sha256"] = _sha256(model_path)
    metadata = ArtifactMetadataV2.model_validate(metadata_payload)
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(metadata.model_dump_json(), encoding="utf-8")

    result = validate_bundle_files(
        model_path=model_path,
        metadata_path=metadata_path,
        evaluation_path=evaluation_path,
        manifest_path=manifest_path,
    )

    assert result.status.reason_code == "bundle_valid"
