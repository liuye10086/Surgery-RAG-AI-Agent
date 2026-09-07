from sqlalchemy import text
import pytest
from app.services.report_archive_cleanup import delete_owned_report, run_cleanup_once
from app.services.report_pdf_delivery import prepare_delivery
from backend.tests.integration.test_report_pdf_delivery import (
    archived,
    completed_report,
)


def test_delete_with_open_download_defers_cleanup_then_converges(db, archived):
    report_id, storage, candidate = archived
    delivery = prepare_delivery(db, 1, report_id, storage)
    result = delete_owned_report(db, 1, report_id, str(storage.root))
    assert result.deleted
    assert db.execute(text("SELECT count(*) FROM ai_reports")).scalar_one() == 0
    assert (
        db.execute(text("SELECT count(*) FROM report_file_cleanup_tasks")).scalar_one()
        == 1
    )
    delivery.file.close()
    db.execute(
        text(
            "UPDATE report_file_cleanup_tasks SET next_attempt_at=clock_timestamp(),not_before_final_check=clock_timestamp()-interval '1 second'"
        )
    )
    db.commit()
    assert run_cleanup_once(db, str(storage.root)) is True
    assert not storage.candidate_path(candidate.object_key).exists()
    assert (
        db.execute(text("SELECT state FROM report_file_cleanup_tasks")).scalar_one()
        == "done"
    )


def test_storage_failure_survives_as_retryable_cleanup(db, archived):
    report_id, storage, candidate = archived
    db.execute(text("DELETE FROM ai_reports WHERE id=:id"), {"id": report_id})
    db.commit()
    assert run_cleanup_once(db, str(storage.root), delete_io=lambda *_: False) is False
    assert (
        db.execute(text("SELECT state FROM report_file_cleanup_tasks")).scalar_one()
        == "pending"
    )
    assert storage.candidate_path(candidate.object_key).exists()


def test_final_cleanup_removes_late_file_after_report_deletion(
    db, completed_report, tmp_path
):
    from uuid import uuid4
    import fitz
    from app.services.report_pdf_archive_service import prepare_pdf_archive
    from app.services.report_pdf_repository import claim_pdf, publish_pdf
    from app.services.report_archive_storage import ArchiveStorage

    prepare_pdf_archive(db, 1, completed_report, str(uuid4()))
    claim = claim_pdf(db, "late-worker")
    storage = ArchiveStorage(tmp_path)
    db.execute(text("DELETE FROM ai_reports WHERE id=:id"), {"id": completed_report})
    db.commit()
    delete_io = lambda root, key: ArchiveStorage(root).delete_attempt(key)
    assert run_cleanup_once(db, storage.root, delete_io=delete_io) is True
    assert (
        db.execute(text("SELECT state FROM report_file_cleanup_tasks")).scalar_one()
        == "settling"
    )
    db.rollback()
    with fitz.open() as document:
        document.new_page()
        candidate = storage.write_candidate(claim.object_key, document.tobytes())
    assert not publish_pdf(db, claim, candidate, storage)
    db.execute(
        text(
            "UPDATE report_file_cleanup_tasks SET next_attempt_at=clock_timestamp(),not_before_final_check=clock_timestamp()-interval '1 second'"
        )
    )
    db.commit()
    assert run_cleanup_once(db, storage.root, delete_io=delete_io) is True
    assert not storage.candidate_path(claim.object_key).exists()
    assert (
        db.execute(text("SELECT state FROM report_file_cleanup_tasks")).scalar_one()
        == "done"
    )


def test_restore_requires_exact_original_and_preserves_identity(db, archived, tmp_path):
    from app.services.report_archive_recovery import restore_pdf_original
    from app.services.report_pdf_errors import PdfError

    report_id, storage, candidate = archived
    path = storage.candidate_path(candidate.object_key)
    backup = tmp_path / "backup.pdf"
    backup.write_bytes(path.read_bytes())
    path.unlink()
    with pytest.raises(PdfError, match="pdf_original_missing"):
        prepare_delivery(db, 1, report_id, storage)
    preview = restore_pdf_original(db, report_id, backup, storage.root)
    assert preview["matches"] and not preview["applied"] and not path.exists()
    assert (
        restore_pdf_original(db, report_id, backup, storage.root, apply=True)["state"]
        == "ready"
    )
    delivery = prepare_delivery(db, 1, report_id, storage)
    assert delivery.file.read() == backup.read_bytes()
    delivery.file.close()
    assert delivery.sha256 == candidate.pdf_sha256


def test_restore_wrong_backup_and_deleted_report_rejected(db, archived, tmp_path):
    from app.services.report_archive_recovery import restore_pdf_original
    from app.services.report_pdf_errors import PdfError
    import fitz

    report_id, storage, candidate = archived
    path = storage.candidate_path(candidate.object_key)
    path.unlink()
    with pytest.raises(PdfError):
        prepare_delivery(db, 1, report_id, storage)
    backup = tmp_path / "wrong.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(backup)
    with pytest.raises(PdfError, match="pdf_original_corrupt"):
        restore_pdf_original(db, report_id, backup, storage.root, apply=True)
    assert not path.exists()
    db.execute(text("DELETE FROM ai_reports WHERE id=:id"), {"id": report_id})
    db.commit()
    with pytest.raises(PdfError, match="report_not_found"):
        restore_pdf_original(db, report_id, backup, storage.root, apply=True)
