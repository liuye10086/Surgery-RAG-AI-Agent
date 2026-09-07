import hashlib
import json
from datetime import timedelta
from uuid import UUID, uuid4
from fastapi import HTTPException
from sqlalchemy import text, func

from app.core.config import settings
from app.db.models import (
    AIReport,
    ReportPdfArchive,
    ReportPdfAttempt,
    OperatorIdempotencyKey,
)
from app.schemas.report_pdf_archive import PdfArchiveStatus
from app.services.report_read_service import (
    read_owned_report,
    build_pdf_source,
    source_digest,
)
from app.services.report_pdf_renderer_manifest import load_renderer_manifest
from app.services.report_pdf_errors import PdfError, ERRORS, safe_pdf_code
from app.services.report_pdf_repository import lock_pdf_rows
from app.services.report_job_repository import bounded_transaction, db_now


def request_digest(report_id, retry):
    return hashlib.sha256(
        json.dumps(
            dict(version="pdf_request.v1", report_id=report_id, retry=retry),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def admission_action(archive, *, retry):
    if archive is None:
        return "reject_retry" if retry else "create"
    if archive.published_attempt_id is not None:
        return "reject_retry" if retry else "replay"
    if archive.state in ("queued", "rendering"):
        return "replay"
    return "retry" if retry and archive.state == "failed" else "replay"


def project_archive(report_id, archive, attempt=None):
    if archive is None:
        return PdfArchiveStatus(
            report_id=report_id,
            state="not_requested",
            revision=0,
            message="尚未准备 PDF",
        )
    code = safe_pdf_code(attempt.error_code) if attempt and attempt.error_code else None
    if archive.state in ("missing", "corrupt"):
        code = "pdf_original_" + archive.state
    return PdfArchiveStatus(
        report_id=report_id,
        state=archive.state,
        attempt_id=archive.current_attempt_id,
        revision=archive.revision,
        phase=attempt.phase if attempt else None,
        code=code,
        message=(
            ERRORS[code][1]
            if code
            else {
                "queued": "PDF 已排队",
                "rendering": "正在准备 PDF",
                "ready": "PDF 原件已归档",
                "failed": "PDF 准备失败",
            }.get(archive.state, "PDF 状态已更新")
        ),
        can_retry=archive.state == "failed" and archive.published_attempt_id is None,
        pdf_sha256=archive.pdf_sha256,
        size_bytes=archive.size_bytes,
        page_count=archive.page_count,
        archived_at=archive.archived_at,
    )


def read_pdf_archive_status(db, user_id, report_id):
    if not db.query(AIReport.id).filter_by(id=report_id, user_id=user_id).first():
        raise PdfError("report_not_found")
    archive = db.get(ReportPdfArchive, report_id)
    attempt = (
        db.get(ReportPdfAttempt, archive.current_attempt_id)
        if archive and archive.current_attempt_id
        else None
    )
    return project_archive(report_id, archive, attempt)


def _source(db, user_id, report_id):
    try:
        return build_pdf_source(read_owned_report(db, user_id, report_id))
    except HTTPException:
        raise PdfError("report_not_found") from None
    except ValueError:
        raise PdfError("report_not_exportable") from None


def prepare_pdf_archive(db, user_id, report_id, idempotency_key, *, retry=False):
    if not idempotency_key:
        raise PdfError("idempotency_key_missing")
    try:
        key = UUID(str(idempotency_key))
    except (ValueError, TypeError):
        raise PdfError("idempotency_key_invalid") from None
    scope = "retry_report_pdf" if retry else "prepare_report_pdf"
    digest = request_digest(report_id, retry)
    try:
        previous = (
            db.query(OperatorIdempotencyKey)
            .filter_by(user_id=user_id, scope=scope, idempotency_key=key)
            .first()
        )
        if previous:
            if previous.request_sha256 != digest:
                raise PdfError("idempotency_conflict")
            if not db.get(ReportPdfAttempt, previous.resource_id):
                raise PdfError("idempotency_resource_missing")
        source = _source(db, user_id, report_id)
        source_sha = source_digest(source)
        existing = db.get(ReportPdfArchive, report_id)
        if existing and existing.source_sha256 != source_sha:
            raise PdfError("pdf_source_changed")
        action = "replay" if previous else admission_action(existing, retry=retry)
        db.rollback()
        renderer_sha = None
        if action in ("create", "retry"):
            if not settings.REPORT_PDF_ENABLED or not settings.REPORT_PDF_ACCEPTING:
                raise PdfError("pdf_disabled")
            _, renderer_sha = load_renderer_manifest(
                settings.REPORT_PDF_RENDERER_MANIFEST
            )
        bounded_transaction(db)
        db.execute(text("SELECT pg_advisory_xact_lock(73608)"))
        report, archive, attempt = lock_pdf_rows(db, report_id, user_id=user_id)
        if report is None:
            raise PdfError("report_not_found")
        prior = (
            db.query(OperatorIdempotencyKey)
            .filter_by(user_id=user_id, scope=scope, idempotency_key=key)
            .first()
        )
        if prior:
            if prior.request_sha256 != digest:
                raise PdfError("idempotency_conflict")
            if not db.get(ReportPdfAttempt, prior.resource_id):
                raise PdfError("idempotency_resource_missing")
            result = project_archive(report_id, archive, attempt)
            db.commit()
            return result
        fresh = _source(db, user_id, report_id)
        if source_digest(fresh) != source_sha:
            raise PdfError("pdf_source_changed")
        action = admission_action(archive, retry=retry)
        if action == "reject_retry":
            raise PdfError("pdf_retry_forbidden")
        if archive and archive.source_sha256 != source_sha:
            raise PdfError("pdf_source_changed")
        if action in ("create", "retry"):
            if not settings.REPORT_PDF_ENABLED or not settings.REPORT_PDF_ACCEPTING:
                raise PdfError("pdf_disabled")
            if renderer_sha is None:
                raise PdfError("pdf_renderer_unavailable")
            queued = db.query(ReportPdfAttempt.id).filter_by(status="queued").count()
            active = (
                db.query(ReportPdfAttempt.id)
                .join(AIReport, AIReport.id == ReportPdfAttempt.report_id)
                .filter(
                    AIReport.user_id == user_id,
                    ReportPdfAttempt.status.in_(["queued", "running"]),
                )
                .count()
            )
            if (
                queued >= settings.REPORT_PDF_QUEUE_LIMIT
                or active >= settings.REPORT_PDF_USER_ACTIVE_LIMIT
            ):
                raise PdfError("pdf_capacity_exceeded")
            now = db_now(db)
            if archive is None:
                archive = ReportPdfArchive(
                    report_id=report_id,
                    state="queued",
                    source_sha256=source_sha,
                    source_integrity=source.integrity_status,
                    renderer_sha256=renderer_sha,
                )
                db.add(archive)
                db.flush()
            attempt = ReportPdfAttempt(
                report_id=report_id,
                status="queued",
                phase="queued",
                object_key=f"reports/{report_id}/{uuid4()}/document.pdf",
                source_sha256=source_sha,
                renderer_sha256=renderer_sha,
                queue_deadline=now
                + timedelta(seconds=settings.REPORT_PDF_QUEUE_SECONDS),
            )
            db.add(attempt)
            db.flush()
            archive.current_attempt_id = attempt.id
            archive.state = "queued"
            archive.renderer_sha256 = renderer_sha
            archive.updated_at = now
            archive.revision += 1
        db.add(
            OperatorIdempotencyKey(
                user_id=user_id,
                scope=scope,
                idempotency_key=key,
                request_sha256=digest,
                resource_type="report_pdf_attempt",
                resource_id=attempt.id,
            )
        )
        result = project_archive(report_id, archive, attempt)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
