from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def archive(db, report_id):
    db.execute(
        text(
            "INSERT INTO report_pdf_archives(report_id,state,source_sha256,renderer_sha256,source_integrity) VALUES(:id,'queued',:sha,:sha,'valid')"
        ),
        {"id": report_id, "sha": "a" * 64},
    )
    db.commit()


def attempt(db, report_id):
    return db.execute(
        text(
            "INSERT INTO report_pdf_attempts(report_id,status,phase,object_key,source_sha256,renderer_sha256,queue_deadline) VALUES(:id,'queued','queued',:key,:sha,:sha,clock_timestamp()+interval '600 seconds') RETURNING id"
        ),
        {
            "id": report_id,
            "key": f"reports/{report_id}/{uuid4()}/document.pdf",
            "sha": "a" * 64,
        },
    ).scalar_one()


def test_original_constraints_and_immutable_published_identity(db, queued_report):
    archive(db, queued_report)
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE report_pdf_archives SET state='ready'"))
    db.rollback()
    first = attempt(db, queued_report)
    db.commit()
    with pytest.raises(DBAPIError):
        attempt(db, queued_report)
    db.rollback()
    db.execute(
        text(
            "UPDATE report_pdf_attempts SET status='completed',finished_at=clock_timestamp()"
        )
    )
    db.execute(
        text(
            "UPDATE report_pdf_archives SET state='ready',current_attempt_id=:id,published_attempt_id=:id,pdf_sha256=:sha,size_bytes=5,page_count=1,archived_at=clock_timestamp()"
        ),
        {"id": first, "sha": "b" * 64},
    )
    db.commit()
    with pytest.raises(DBAPIError, match="pdf_original_immutable"):
        db.execute(
            text("UPDATE report_pdf_archives SET pdf_sha256=:sha"), {"sha": "c" * 64}
        )
    db.rollback()
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM report_pdf_attempts"))
        db.commit()
    db.rollback()
    with pytest.raises(DBAPIError,match="pdf_attempt_immutable"):
        db.execute(text("UPDATE report_pdf_attempts SET object_key=:key"),{"key":f"reports/{queued_report}/{uuid4()}/document.pdf"})
        db.commit()
    db.rollback()
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
    assert (
        db.execute(text("SELECT count(*) FROM report_pdf_archives")).scalar_one() == 0
    )


def test_reports_without_pdf_also_leave_deletion_fact(db, queued_report):
    db.execute(text("DELETE FROM ai_reports WHERE id=:id"), {"id": queued_report})
    db.commit()
    assert (
        db.execute(text("SELECT count(*) FROM report_deletion_tombstones")).scalar_one()
        == 1
    )
