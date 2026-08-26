import pytest
from pydantic import ValidationError

from app.schemas.longitudinal_readiness import (
    DiseaseReadiness,
    LongitudinalReadinessReport,
    ReadinessReason,
    status_from_reasons,
)


def _reason(code: str, severity: str, next_task: str) -> ReadinessReason:
    return ReadinessReason(
        code=code,
        message=f"message:{code}",
        severity=severity,
        next_task=next_task,
    )


def _disease(dataset: str, reasons: list[ReadinessReason]) -> DiseaseReadiness:
    return DiseaseReadiness(
        dataset=dataset,
        disease_name="脂肪肝" if dataset == "fatty_liver" else "阿尔茨海默病",
        status=status_from_reasons(reasons),
        data={
            "status": "available",
            "patient_count": 1,
            "visit_count": 2,
            "all_prefix_count": 1,
            "estimable_prefix_count": 1,
            "positive_count": 1,
            "negative_count": 0,
            "unknown_count": 0,
            "source_datasets": [dataset],
            "real_patient_count": 1,
            "synthetic_patient_count": 0,
            "unknown_provenance_patient_count": 0,
        },
        standard={"status": "available"},
        models={
            "outcome": {"status": "available", "artifact_type": "outcome"},
            "outcome_tasks": {
                ("fatty_liver.pre_cirrhosis_to_progression" if dataset == "fatty_liver" else "ad.pre_dementia_to_dementia"): {
                    "status": "available",
                    "artifact_type": "outcome",
                }
            },
            "stage": {"status": "not_configured", "artifact_type": "stage"},
            "trends": [],
        },
        report_contract={"status": "available", "capabilities": []},
        available_capabilities=["reference_data"],
        reasons=reasons,
        next_tasks=list(dict.fromkeys(reason.next_task for reason in reasons)),
    )


def test_status_from_reasons_uses_strict_severity_order():
    assert status_from_reasons([]) == "ready"
    assert status_from_reasons(
        [_reason("stage_model_missing", "degraded", "P2-01")]
    ) == "degraded"
    assert status_from_reasons(
        [_reason("outcome_model_missing", "blocked", "P0-04")]
    ) == "blocked"


def test_report_requires_both_diseases_and_aggregates_worst_status():
    fatty = _disease(
        "fatty_liver",
        [_reason("stage_model_missing", "degraded", "P2-01")],
    )
    ad = _disease(
        "ad",
        [_reason("approved_standard_missing", "blocked", "P0-02")],
    )
    report = LongitudinalReadinessReport(
        generated_at="2026-08-25T00:00:00Z",
        overall_status="blocked",
        environment={"database_check": "available"},
        diseases={"fatty_liver": fatty, "ad": ad},
    )
    assert report.schema_version == "longitudinal_readiness.v1"
    assert report.overall_status == "blocked"


def test_report_rejects_missing_disease_or_inconsistent_overall_status():
    fatty = _disease("fatty_liver", [])
    with pytest.raises(ValidationError):
        LongitudinalReadinessReport(
            generated_at="2026-08-25T00:00:00Z",
            overall_status="ready",
            environment={"database_check": "available"},
            diseases={"fatty_liver": fatty},
        )


def test_schema_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ReadinessReason(
            code="x",
            message="x",
            severity="blocked",
            next_task="P0-01",
            unexpected=True,
        )
