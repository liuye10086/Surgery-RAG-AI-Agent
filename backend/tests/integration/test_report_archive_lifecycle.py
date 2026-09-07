from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from app.services.report_pdf_delivery import prepare_delivery
from app.services.report_pdf_repository import claim_pdf
from app.services.report_pdf_archive_service import prepare_pdf_archive
from app.services.report_pdf_errors import PdfError
from backend.tests.integration.test_report_pdf_delivery import (
    archived,
    completed_report,
)


def test_two_workers_cannot_claim_same_attempt(
    db, integration_engine, completed_report
):
    prepare_pdf_archive(db, 1, completed_report, str(uuid4()))
    factory = sessionmaker(bind=integration_engine)
    barrier = Barrier(2)

    def claim(name):
        with factory() as session:
            barrier.wait(5)
            return claim_pdf(session, name)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, ["one", "two"]))
    assert sum(c is not None for c in claims) == 1
    assert (
        db.execute(
            text("SELECT count(*) FROM report_pdf_attempts WHERE status='running'")
        ).scalar_one()
        == 1
    )


def test_lost_delivery_commit_response_never_counts_twice(db, archived, monkeypatch):
    report_id, storage, _ = archived
    commit = db.commit

    def lost_response():
        commit()
        raise OSError("simulated_commit_response_lost")

    monkeypatch.setattr(db, "commit", lost_response)
    delivery = prepare_delivery(db, 1, report_id, storage)
    delivery.file.close()
    assert (
        db.execute(text("SELECT delivery_count FROM report_pdf_archives")).scalar_one()
        == 1
    )
    assert (
        db.execute(text("SELECT count(*) FROM report_pdf_deliveries")).scalar_one() == 1
    )


def test_delete_wins_after_file_open_before_delivery_authorization(
    db, integration_engine, archived, monkeypatch
):
    report_id, storage, _ = archived
    opened = []
    original = storage.open_verified

    def open_then_delete(*args):
        stream = original(*args)
        opened.append(stream)
        with integration_engine.begin() as other:
            other.execute(
                text("DELETE FROM ai_reports WHERE id=:id"), {"id": report_id}
            )
        return stream

    monkeypatch.setattr(storage, "open_verified", open_then_delete)
    with pytest.raises(PdfError, match="report_not_found"):
        prepare_delivery(db, 1, report_id, storage)
    assert opened[0].closed
    assert (
        db.execute(text("SELECT count(*) FROM report_pdf_deliveries")).scalar_one() == 0
    )
    assert (
        db.execute(text("SELECT count(*) FROM report_file_cleanup_tasks")).scalar_one()
        == 1
    )


def test_account_cascade_enqueues_files_and_rollback_preserves_original(db, archived):
    report_id, storage, candidate = archived
    db.execute(text("DELETE FROM users WHERE id=1"))
    db.rollback()
    delivery = prepare_delivery(db, 1, report_id, storage)
    delivery.file.close()
    db.execute(text("DELETE FROM users WHERE id=1"))
    db.commit()
    assert (
        db.execute(text("SELECT count(*) FROM report_file_cleanup_tasks")).scalar_one()
        == 1
    )
    assert (
        db.execute(text("SELECT count(*) FROM report_deletion_tombstones")).scalar_one()
        == 1
    )
    assert db.execute(text("SELECT count(*) FROM ai_reports")).scalar_one() == 0
