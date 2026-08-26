import pytest
from pydantic import ValidationError

from app.schemas.longitudinal_model_training import (
    MODEL_TRAINING_SCHEMA_VERSION,
    TASK_SPECS,
    FoldMetrics,
    ModelMetadata,
)


def _valid_metadata_kwargs(**overrides):
    payload = {
        "schema_version": MODEL_TRAINING_SCHEMA_VERSION,
        "task": "ad.pre_dementia_to_dementia",
        "dataset_manifest_sha256": "a" * 64,
        "data_content_sha256": "b" * 64,
        "dataset_file_sha256": "c" * 64,
        "feature_order_sha256": "d" * 64,
        "status": "candidate",
        "production_enabled": False,
        "clinical_validity_claim": False,
    }
    payload.update(overrides)
    return payload


def test_task_specs_are_exact_and_distinct():
    assert set(TASK_SPECS) == {
        "fatty_liver.pre_cirrhosis_to_progression",
        "fatty_liver.cirrhosis_to_hcc",
        "ad.pre_dementia_to_dementia",
    }
    assert TASK_SPECS["fatty_liver.pre_cirrhosis_to_progression"].target_event == "cirrhosis_or_hcc"
    assert TASK_SPECS["fatty_liver.cirrhosis_to_hcc"].target_event == "hcc"
    assert TASK_SPECS["ad.pre_dementia_to_dementia"].target_event == "dementia"


def test_metadata_rejects_non_candidate_status():
    with pytest.raises(ValidationError):
        ModelMetadata(**_valid_metadata_kwargs(status="enabled", production_enabled=True, clinical_validity_claim=True))


def test_evaluation_records_unestimable_metrics_without_zero_filling():
    metrics = FoldMetrics(
        fold=1,
        train_patient_count=4,
        validation_patient_count=2,
        positive_patient_count=0,
        negative_patient_count=2,
        pr_auc=None,
        roc_auc=None,
        unavailable_metrics=["pr_auc", "roc_auc"],
    )
    assert metrics.pr_auc is None
    assert "roc_auc" in metrics.unavailable_metrics
