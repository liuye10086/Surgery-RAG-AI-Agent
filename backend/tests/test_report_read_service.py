from copy import deepcopy
from datetime import datetime, timezone

import pytest

from backend.tests.test_report_document_integrity import published
from app.services.report_integrity import compute_input_snapshot_sha256
from app.services.report_saved_identity import saved_report_identity
from app.services.report_read_service import project_report, build_pdf_source


def saved_row():
    snapshot, pub = published()
    return dict(
        id=17,
        user_id=1,
        title="private",
        query="private",
        status="completed",
        error_message=None,
        download_count=0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        input_snapshot=snapshot,
        input_snapshot_sha256=compute_input_snapshot_sha256(snapshot),
        generation_batch_id=snapshot["generation_batch_id"],
        generation_fingerprint=pub.generation_fingerprint,
        generation_fingerprint_version="v2",
        content=pub.content,
        prediction_result=pub.prediction_result,
        sources=pub.sources,
        evidence_snapshot=pub.evidence_snapshot,
        evidence_snapshot_sha256=pub.evidence_snapshot_sha256,
        report_document=pub.report_document.model_dump(mode="json"),
        report_document_sha256=pub.report_document_sha256,
    )


def test_identity_uses_only_saved_snapshot():
    assert (
        saved_report_identity(
            9, {"anonymous_case_code": "CASE-ABCD-2345"}
        ).anonymous_case_code
        == "CASE-ABCD-2345"
    )
    for snapshot in (
        [],
        None,
        {"patient_label": "private"},
        {"anonymous_case_code": 12},
    ):
        identity = saved_report_identity(9, snapshot)
        assert identity.title == "报告-9"
        assert identity.anonymous_case_code is None


def test_model_identity_does_not_load_case():
    from app.db.models import AIReport

    report = AIReport(id=9, input_snapshot={"anonymous_case_code": "CASE-ABCD-2345"})
    assert report.anonymous_case_code == "CASE-ABCD-2345"


def test_valid_publication_and_pdf_source():
    detail = project_report(saved_row())
    assert detail.publication_status == "published"
    assert detail.integrity_status == "valid"
    assert "private" not in detail.title
    assert build_pdf_source(detail).report_id == 17


@pytest.mark.parametrize(
    "field,value",
    [
        ("generation_batch_id", "33333333-3333-4333-8333-333333333333"),
        ("id", 99),
        ("report_document", []),
        ("sources", [{"private": True}]),
        ("content", "tampered"),
        ("prediction_result", {"score": float("nan")}),
        ("prediction_result", []),
        ("input_snapshot", []),
        ("generation_fingerprint_version", "v3"),
    ],
)
def test_invalid_publication_is_redacted_before_serialization(field, value):
    row = deepcopy(saved_row())
    row[field] = value
    detail = project_report(row)
    assert detail.publication_status == "invalid"
    assert detail.integrity_status == "invalid"
    assert detail.content == ""
    assert detail.prediction_result == {}
    assert detail.sources == []
    assert detail.report_document is None
    assert detail.input_snapshot is None
    with pytest.raises(ValueError, match="report_not_exportable"):
        build_pdf_source(detail)


def test_failed_report_preserves_verified_snapshot_without_partial_prediction():
    row = saved_row()
    row.update(status="failed", generation_fingerprint_version=None)
    detail = project_report(row)
    assert detail.publication_status == "not_published"
    assert detail.snapshot_integrity == "valid"
    assert detail.input_snapshot == row["input_snapshot"]
    assert detail.prediction_result == {}
    assert detail.content == ""


def test_legacy_report_is_readable_but_not_upgraded_to_verified():
    row = saved_row()
    for field in (
        "report_document",
        "report_document_sha256",
        "generation_fingerprint_version",
        "generation_fingerprint",
        "input_snapshot_sha256",
        "evidence_snapshot",
        "evidence_snapshot_sha256",
    ):
        row[field] = None
    detail = project_report(row)
    assert detail.integrity_status == "unverifiable"
    assert detail.content == row["content"]
    assert build_pdf_source(detail).integrity_status == "unverifiable"


def test_failed_context_is_checked_using_saved_hash_and_strict_schema():
    from backend.tests.report_document_fixtures import context_payload
    from app.services.report_job_repository import context_hash

    row = saved_row()
    row["status"] = "failed"
    context = context_payload()
    job = {"generation_context": context, "context_sha256": context_hash(context)}
    detail = project_report(row, job)
    assert detail.context_integrity == "valid"
    from app.schemas.report_document import ReportGenerationContext

    assert detail.generation_context == ReportGenerationContext.model_validate(
        context
    ).model_dump(mode="json")
    job["generation_context"]["private"] = "must not leak"
    assert project_report(row, job).generation_context is None
    job["context_sha256"] = context_hash(job["generation_context"])
    assert project_report(row, job).context_integrity == "invalid"


def test_owned_read_filters_both_tables_without_case_relationship():
    from unittest.mock import MagicMock
    from app.services.report_read_service import read_owned_report

    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = 0
    db.execute.return_value.mappings.return_value.first.side_effect = [
        saved_row(),
        None,
    ]
    assert read_owned_report(db, 1, 17).id == 17
    sql = [str(call.args[0]) for call in db.execute.call_args_list]
    assert all("user_id =" in statement for statement in sql[:2])
    assert all("JOIN operator_cases" not in statement for statement in sql)


def test_private_report_responses_include_auth_and_validation_errors():
    from app.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    for path in (
        "/api/v1/operator/reports",
        "/api/v1/operator/reports/17",
        "/api/v1/operator/reports/invalid",
    ):
        response = client.get(path)
        assert response.status_code in (401, 403, 422)
        assert response.headers["cache-control"] == "private, no-store"
