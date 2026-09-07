"""Restore only the exact published original. Never invoke a renderer."""

import hashlib
import multiprocessing
from pathlib import Path

from app.db.models import AIReport, ReportPdfArchive, ReportPdfAttempt
from app.services.report_archive_storage import ArchiveStorage, MAX_BYTES
from app.services.report_pdf_archive_service import _source
from app.services.report_pdf_errors import PdfError
from app.services.report_pdf_repository import lock_pdf_rows, db_now
from app.services.report_read_service import source_digest


def inspect_original(db, report_id):
    report = db.get(AIReport, report_id)
    archive = db.get(ReportPdfArchive, report_id)
    if report is None:
        raise PdfError("report_not_found")
    if archive is None or archive.published_attempt_id is None:
        raise PdfError("pdf_not_ready")
    return {
        "report_id": report_id,
        "state": archive.state,
        "pdf_sha256": archive.pdf_sha256,
        "size_bytes": archive.size_bytes,
        "page_count": archive.page_count,
        "published_attempt_id": str(archive.published_attempt_id),
    }


def restore_matches(candidate, archive):
    return (
        candidate["pdf_sha256"] == archive.pdf_sha256
        and candidate["size_bytes"] == archive.size_bytes
        and candidate["page_count"] == archive.page_count
        and archive.published_attempt_id is not None
        and archive.state in ("missing", "corrupt")
    )


def backup_candidate(path):
    import fitz

    with Path(path).open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if not 1 <= len(data) <= MAX_BYTES:
        raise PdfError("pdf_original_corrupt")
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass or not 1 <= doc.page_count <= 200:
                raise ValueError()
            pages = doc.page_count
    except Exception:
        raise PdfError("pdf_original_corrupt") from None
    return data, {
        "pdf_sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "page_count": pages,
    }


def _restore_child(root, key, data, connection):
    try:
        ArchiveStorage(root).write_candidate(key, data, _restore=True)
        connection.send(True)
    except Exception:
        connection.send(False)
    finally:
        connection.close()


def bounded_restore(root, key, data):
    from app.workers.report_process_control import stop_child

    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=_restore_child, args=(str(root), key, data, send))
    try:
        process.start()
        send.close()
        if not receive.poll(15) or receive.recv() is not True:
            raise PdfError("pdf_storage_unavailable")
    except (OSError, EOFError):
        raise PdfError("pdf_storage_unavailable") from None
    finally:
        if process.pid is not None:
            stop_child(process)
        process.close()
        receive.close()
        send.close()


def restore_pdf_original(db, report_id, backup_file, root, *, apply=False):
    try:
        preview = inspect_original(db, report_id)
        archive = db.get(ReportPdfArchive, report_id)
        report = db.get(AIReport, report_id)
        owner_id = report.user_id
        source_sha = archive.source_sha256
        if source_digest(_source(db, owner_id, report_id)) != source_sha:
            raise PdfError("pdf_source_changed")
        key = db.get(ReportPdfAttempt, archive.published_attempt_id).object_key
        db.rollback()
        data, candidate = backup_candidate(backup_file)
        archive = db.get(ReportPdfArchive, report_id)
        if archive is None or not restore_matches(candidate, archive):
            raise PdfError("pdf_original_corrupt")
        db.rollback()
        result = {
            **preview,
            "backup_sha256": candidate["pdf_sha256"],
            "matches": True,
            "applied": False,
        }
        if not apply:
            return result
        # Bounded below the deletion outbox grace. A concurrent deletion can
        # leave a candidate, but its existing durable cleanup task owns that key.
        bounded_restore(root, key, data)
        report, archive, _ = lock_pdf_rows(db, report_id)
        if report is None:
            raise PdfError("report_not_found")
        if (
            archive is None
            or str(archive.published_attempt_id) != preview["published_attempt_id"]
            or not restore_matches(candidate, archive)
            or archive.source_sha256 != source_sha
        ):
            raise PdfError("pdf_original_corrupt")
        if source_digest(_source(db, owner_id, report_id)) != source_sha:
            raise PdfError("pdf_source_changed")
        archive.state = "ready"
        archive.revision += 1
        archive.updated_at = db_now(db)
        db.commit()
        return {**result, "applied": True, "state": "ready"}
    except BaseException:
        db.rollback()
        raise
