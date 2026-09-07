from datetime import date
import pytest
from pydantic import ValidationError
from app.schemas.report_document import ReportIdentity, ReportDocument


def test_identity_uses_last_visit_anchor_and_recorded_age():
    identity = ReportIdentity(
        report_id=17,
        batch_id="11111111-1111-4111-8111-111111111111",
        anonymous_case_code="CASE-ABCD-2345",
        disease_code="fatty_liver",
        disease_name="脂肪肝",
        age=62,
        sex="female",
        baseline_stage="pre_cirrhosis",
        baseline_stage_label="未肝硬化阶段",
        created_at="2026-09-07T00:00:00Z",
        anchor_date="2025-09-07",
        horizon_days=365,
        prediction_end_date="2026-09-07",
    )
    assert identity.anchor_date == date(2025, 9, 7)
    with pytest.raises(ValidationError):
        ReportIdentity.model_validate({**identity.model_dump(), "age": True})
    with pytest.raises(ValidationError):
        ReportIdentity.model_validate(
            {**identity.model_dump(), "prediction_end_date": "2027-09-07"}
        )


from backend.tests.report_document_fixtures import document_payload
from app.schemas.report_document import InputAudit, ChartPoint, ReportTable


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(schema_version="report_document.v2"),
        lambda d: d.update(unexpected=True),
        lambda d: d["identity"].update(age=True),
        lambda d: d["identity"].update(anonymous_case_code="CASE-0000-0000"),
        lambda d: d["identity"].update(created_at="2026-09-07T00:00:00"),
        lambda d: d["generation_context"].update(disease_code="ad"),
        lambda d: d.update(template_version="unknown"),
        lambda d: d["sections"].pop(),
        lambda d: d["sections"].reverse(),
    ],
)
def test_document_rejects_invalid_contract(mutation):
    payload = document_payload()
    mutation(payload)
    with pytest.raises(ValidationError):
        ReportDocument.model_validate(payload)


def test_document_round_trip():
    payload = document_payload()
    assert ReportDocument.model_validate(payload).model_dump(mode="json") == payload


@pytest.mark.parametrize(
    "value", [True, None, "1", float("nan"), float("inf"), -float("inf")]
)
def test_chart_rejects_non_observations(value):
    with pytest.raises(ValidationError):
        ChartPoint(visit_date="2025-01-01", value=value)


def test_input_audit_rejects_duplicate_or_unprepared_invocation():
    with pytest.raises(ValidationError):
        InputAudit(task="stage", fields=[{"name": "age", "state": "present"}] * 2)
    with pytest.raises(ValidationError):
        InputAudit(task="stage", fields=[], model_invoked=True)
    with pytest.raises(ValidationError):
        InputAudit(
            task="stage",
            fields=[{"name": "age", "state": "required_missing"}],
            model_invoked=True,
            frame_sha256="a" * 64,
        )


def test_table_requires_uniform_width():
    with pytest.raises(ValidationError):
        ReportTable(title="test", headers=["one"], rows=[["a", "b"]])
