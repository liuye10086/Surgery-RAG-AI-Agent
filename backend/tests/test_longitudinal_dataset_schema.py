"""Strict contracts for the P0-03 fixed-window dataset."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.schemas.longitudinal_dataset import (
    DATASET_SCHEMA_VERSION,
    CohortCounts,
    DatasetAuditSummary,
    FixedWindowSample,
    LabelAudit,
)


def sample_payload(*, history_visit_count: int = 3) -> dict:
    return {
        "schema_version": DATASET_SCHEMA_VERSION,
        "identity": {
            "disease": "fatty_liver",
            "disease_name": "脂肪肝",
            "source_dataset": "longitudinal_300",
            "patient_label": "P001",
            "group_id": "patient.v1." + "a" * 64,
            "is_synthetic": False,
            "source_document": None,
            "import_version": "1.0.0",
            "as_of": "2024-01-01",
            "current_state": "pre_cirrhosis",
            "target_event": "cirrhosis_or_hcc",
            "history_visit_count": history_visit_count,
            "history_start": "2023-01-01",
        },
        "features": {
            "age": 60,
            "sex": "female",
            "visit_count": history_visit_count,
            "observation_span_days": 365,
            "days_since_previous_visit": 120,
            "indicators": {},
        },
        "label": {
            "status": "negative",
            "training_label": 0,
            "reason_code": "full_window_observed_without_event",
            "window_start": "2024-01-02",
            "window_end": "2024-12-31",
            "target_event": "cirrhosis_or_hcc",
            "event_type": None,
            "event_date": None,
            "last_followup_date": "2025-01-01",
        },
    }


def cohort_counts(**overrides) -> dict:
    values = {
        "patient_count": 1,
        "candidate_patient_count": 1,
        "trainable_patient_count": 1,
        "visit_count": 3,
        "candidate_count": 1,
        "positive_count": 0,
        "negative_count": 1,
        "insufficient_observation_count": 0,
        "not_applicable_count": 0,
        "trainable_count": 1,
        "label_reason_counts": {"full_window_observed_without_event": 1},
    }
    values.update(overrides)
    return values


def test_label_status_and_training_value_must_agree():
    positive = LabelAudit(
        status="positive",
        training_label=1,
        reason_code="target_event_within_window",
        window_start="2024-01-02",
        window_end="2024-12-31",
        target_event="cirrhosis_or_hcc",
        event_type="cirrhosis_date",
        event_date="2024-12-31",
        last_followup_date="2025-01-01",
    )
    assert positive.training_label == 1

    with pytest.raises(ValidationError):
        LabelAudit(
            status="insufficient_observation",
            training_label=0,
            reason_code="followup_ends_before_window",
            window_start="2024-01-02",
            window_end="2024-12-31",
            target_event="dementia",
            event_type=None,
            event_date=None,
            last_followup_date="2024-06-01",
        )


def test_label_event_evidence_must_match_reason():
    with pytest.raises(ValidationError):
        LabelAudit(
            status="positive",
            training_label=1,
            reason_code="target_event_within_window",
            window_start="2024-01-02",
            window_end="2024-12-31",
            target_event="dementia",
            event_type=None,
            event_date=None,
            last_followup_date="2025-01-01",
        )


def test_sample_requires_three_history_visits_and_isolates_features():
    payload = sample_payload(history_visit_count=3)
    sample = FixedWindowSample.model_validate(payload)

    assert sample.schema_version == DATASET_SCHEMA_VERSION
    assert "patient_label" not in sample.features.model_dump()

    payload["identity"]["history_visit_count"] = 2
    payload["features"]["visit_count"] = 2
    with pytest.raises(ValidationError):
        FixedWindowSample.model_validate(payload)


def test_sample_rejects_mismatched_visit_count_target_or_window():
    payload = sample_payload()
    payload["features"]["visit_count"] = 4
    with pytest.raises(ValidationError):
        FixedWindowSample.model_validate(payload)

    payload = sample_payload()
    payload["label"]["target_event"] = "hcc"
    with pytest.raises(ValidationError):
        FixedWindowSample.model_validate(payload)

    payload = sample_payload()
    payload["label"]["window_end"] = "2025-01-01"
    with pytest.raises(ValidationError):
        FixedWindowSample.model_validate(payload)


def test_schema_rejects_extra_feature_fields():
    payload = sample_payload()
    payload["features"]["final_stage"] = "hcc"
    with pytest.raises(ValidationError):
        FixedWindowSample.model_validate(payload)


def test_cohort_counts_require_consistent_status_and_reason_totals():
    assert CohortCounts.model_validate(cohort_counts()).trainable_count == 1

    invalid = cohort_counts(candidate_count=2)
    with pytest.raises(ValidationError):
        CohortCounts.model_validate(invalid)

    invalid = cohort_counts(label_reason_counts={})
    with pytest.raises(ValidationError):
        CohortCounts.model_validate(invalid)


def test_summary_requires_exactly_both_supported_diseases():
    real = cohort_counts()
    synthetic = cohort_counts(
        patient_count=0,
        candidate_patient_count=0,
        trainable_patient_count=0,
        visit_count=0,
        candidate_count=0,
        negative_count=0,
        trainable_count=0,
        label_reason_counts={},
    )
    fatty = {
        "disease": "fatty_liver",
        "disease_name": "脂肪肝",
        "source_datasets": ["longitudinal_300"],
        "real": real,
        "synthetic": synthetic,
        "reordered_patient_count": 0,
    }
    ad = deepcopy(fatty)
    ad.update(
        disease="ad",
        disease_name="阿尔茨海默病",
        source_datasets=["ad_longitudinal_300"],
    )

    summary = DatasetAuditSummary(diseases={"fatty_liver": fatty, "ad": ad})
    assert set(summary.diseases) == {"fatty_liver", "ad"}

    with pytest.raises(ValidationError):
        DatasetAuditSummary(diseases={"fatty_liver": fatty})

    with pytest.raises(ValidationError):
        DatasetAuditSummary(diseases={"fatty_liver": ad, "ad": ad})
