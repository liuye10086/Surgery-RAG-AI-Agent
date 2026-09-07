from dataclasses import dataclass
from typing import BinaryIO
from uuid import uuid4
from sqlalchemy import text
from app.db.models import ReportPdfArchive, ReportPdfAttempt, ReportPdfDelivery
from app.services.report_pdf_archive_service import _source
from app.services.report_pdf_repository import lock_pdf_rows, db_now
from app.services.report_read_service import source_digest
from app.services.report_pdf_errors import PdfError


@dataclass
class PdfDelivery:
    file: BinaryIO
    filename: str
    size_bytes: int
    sha256: str


def delivery_chunks(delivery):
    try:
        for chunk in iter(lambda: delivery.file.read(1024 * 1024), b""):
            yield chunk
    finally:
        delivery.file.close()


def _identity(archive):
    return (
        archive.published_attempt_id,
        archive.pdf_sha256,
        archive.size_bytes,
        archive.source_sha256,
    )


def mark_original_health(db, report_id, identity, state):
    try:
        report, archive, _ = lock_pdf_rows(db, report_id)
        if archive and _identity(archive) == identity:
            archive.state = state
            archive.revision += 1
            archive.updated_at = db_now(db)
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise


def prepare_delivery(
    db, user_id, report_id, storage=None, *, range_requested=False, delivery_id=None
):
    stream = None
    try:
        source = _source(db, user_id, report_id)
        if range_requested:
            raise PdfError("pdf_range_not_supported")
        archive = db.get(ReportPdfArchive, report_id)
        if archive is None:
            raise PdfError("pdf_not_requested")
        if source_digest(source) != archive.source_sha256:
            raise PdfError("pdf_source_changed")
        if archive.state in ("missing", "corrupt"):
            raise PdfError("pdf_original_" + archive.state)
        if archive.state != "ready":
            raise PdfError("pdf_not_ready")
        identity = _identity(archive)
        attempt = db.get(ReportPdfAttempt, archive.published_attempt_id)
        key = attempt.object_key
        filename = source.title + ".pdf"
        db.rollback()
        if storage is None:
            from app.core.config import settings
            from app.services.report_archive_storage import ArchiveStorage

            storage = ArchiveStorage(settings.REPORT_ARCHIVE_ROOT)
        try:
            stream = storage.open_verified(key, identity[1], identity[2])
        except PdfError as error:
            if error.code in ("pdf_original_missing", "pdf_original_corrupt"):
                mark_original_health(
                    db,
                    report_id,
                    identity,
                    "missing" if error.code.endswith("missing") else "corrupt",
                )
            raise
        report, archive, _ = lock_pdf_rows(db, report_id, user_id=user_id)
        if report is None:
            raise PdfError("report_not_found")
        if not archive or archive.state != "ready" or _identity(archive) != identity:
            raise PdfError("pdf_not_ready")
        if source_digest(_source(db, user_id, report_id)) != identity[3]:
            raise PdfError("pdf_source_changed")
        logical_id = delivery_id or uuid4()
        previous = db.get(ReportPdfDelivery, logical_id)
        if previous and previous.report_id != report_id:
            raise PdfError("idempotency_conflict")
        db.execute(
            text(
                """WITH accepted AS (
            INSERT INTO report_pdf_deliveries(delivery_id,report_id) VALUES(:delivery_id,:report_id)
            ON CONFLICT(delivery_id) DO NOTHING RETURNING report_id)
            UPDATE report_pdf_archives SET delivery_count=delivery_count+1 WHERE report_id IN (SELECT report_id FROM accepted)"""
            ),
            {"delivery_id": logical_id, "report_id": report_id},
        )
        try:
            db.commit()
        except Exception:
            db.rollback()
            # Resolve only this delivery ID. Never repeat the increment after a
            # lost commit response; a subsequent HTTP request is a new delivery.
            confirmed = db.get(ReportPdfDelivery, logical_id)
            if confirmed is None or confirmed.report_id != report_id:
                raise
            db.rollback()
        return PdfDelivery(stream, filename, identity[2], identity[1])
    except BaseException:
        db.rollback()
        if stream is not None:
            stream.close()
        raise
