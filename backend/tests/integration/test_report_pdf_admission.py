from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.services.report_pdf_archive_service import (
    prepare_pdf_archive,
    read_pdf_archive_status,
)
from app.services.report_pdf_errors import PdfError


@pytest.fixture
def completed_report(db, queued_report, monkeypatch):
    db.execute(
        text(
            "UPDATE ai_reports SET status='completed',content='saved',input_snapshot_sha256=NULL,generation_fingerprint=NULL WHERE id=:id"
        ),
        {"id": queued_report},
    )
    db.execute(
        text("DELETE FROM report_generation_jobs WHERE report_id=:id"),
        {"id": queued_report},
    )
    db.commit()
    monkeypatch.setattr(settings, "REPORT_PDF_ENABLED", True)
    monkeypatch.setattr(settings, "REPORT_PDF_ACCEPTING", True)
    monkeypatch.setattr(
        "app.services.report_pdf_archive_service.load_renderer_manifest",
        lambda _: (None, "a" * 64),
    )
    return queued_report


def test_idempotency_closed_replay_and_cross_user(db, completed_report, monkeypatch):
    key = str(uuid4())
    first = prepare_pdf_archive(db, 1, completed_report, key)
    monkeypatch.setattr(settings, "REPORT_PDF_ACCEPTING", False)
    assert (
        prepare_pdf_archive(db, 1, completed_report, key).attempt_id == first.attempt_id
    )
    assert (
        prepare_pdf_archive(db, 1, completed_report, str(uuid4())).attempt_id
        == first.attempt_id
    )
    with pytest.raises(PdfError, match="report_not_found"):
        read_pdf_archive_status(db, 2, completed_report)
    db.rollback()
    with pytest.raises(PdfError, match="idempotency_conflict"):
        prepare_pdf_archive(db, 1, 999, key)
    db.execute(text("DELETE FROM ai_reports WHERE id=:id"), {"id": completed_report})
    db.commit()
    with pytest.raises(PdfError, match="idempotency_resource_missing"):
        prepare_pdf_archive(db, 1, completed_report, key)


def test_concurrent_different_keys_reuse_one_attempt(
    db, integration_engine, completed_report
):
    factory = sessionmaker(bind=integration_engine, expire_on_commit=False)

    def submit(_):
        with factory() as session:
            return prepare_pdf_archive(session, 1, completed_report, str(uuid4()))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    assert results[0].attempt_id == results[1].attempt_id
    assert (
        db.execute(text("SELECT count(*) FROM report_pdf_attempts")).scalar_one() == 1
    )


def test_admission_failure_does_not_leave_partial_archive(
    db, completed_report, monkeypatch
):
    original = db.commit

    def fail():
        db.flush()
        raise RuntimeError("injected")

    monkeypatch.setattr(db, "commit", fail)
    with pytest.raises(RuntimeError, match="injected"):
        prepare_pdf_archive(db, 1, completed_report, str(uuid4()))
    monkeypatch.setattr(db, "commit", original)
    assert (
        db.execute(text("SELECT count(*) FROM report_pdf_archives")).scalar_one() == 0
    )
    assert (
        db.execute(text("SELECT count(*) FROM report_pdf_attempts")).scalar_one() == 0
    )
