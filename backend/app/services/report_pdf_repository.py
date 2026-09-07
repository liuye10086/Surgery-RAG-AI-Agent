"""Short PDF transactions. Lock order: global (if needed), report, archive, attempt."""

from app.db.models import AIReport, ReportPdfArchive, ReportPdfAttempt
from app.services.report_job_repository import bounded_transaction, db_now
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import text, func, or_
from app.core.config import settings
from app.schemas.report_pdf_archive import PdfClaim, PdfCandidate
from app.services.report_pdf_errors import safe_pdf_code, PdfError

PDF_PHASES = [
    "queued",
    "source_validation",
    "html",
    "browser_launch",
    "fonts",
    "print",
    "storage",
    "publish",
    "terminal",
]


def lock_pdf_rows(db, report_id, attempt_id=None, *, user_id=None, skip_locked=False):
    bounded_transaction(db)
    query = db.query(AIReport).filter_by(id=report_id)
    if user_id is not None:
        query = query.filter_by(user_id=user_id)
    report = query.populate_existing().with_for_update(skip_locked=skip_locked).first()
    if report is None:
        return None, None, None
    archive = (
        db.query(ReportPdfArchive)
        .filter_by(report_id=report_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    attempt = None
    if archive:
        target = attempt_id if attempt_id is not None else archive.current_attempt_id
        if target is not None:
            attempt = (
                db.query(ReportPdfAttempt)
                .filter_by(id=target, report_id=report_id)
                .populate_existing()
                .with_for_update()
                .first()
            )
    return report, archive, attempt


def claim_may_publish(report, archive, attempt, claim, now):
    return bool(
        report
        and report.status == "completed"
        and archive
        and archive.published_attempt_id is None
        and archive.current_attempt_id == claim.attempt_id
        and archive.source_sha256 == claim.source_sha256
        and archive.renderer_sha256 == claim.renderer_sha256
        and attempt
        and attempt.status == "running"
        and attempt.id == claim.attempt_id
        and attempt.object_key == claim.object_key
        and attempt.lease_token == claim.lease_token
        and attempt.lease_owner == claim.lease_owner
        and attempt.lease_expires_at > now
        and attempt.run_deadline > now
    )


def claim_pdf(db, owner):
    if not owner or len(owner) > 160:
        raise ValueError("pdf_worker_owner_invalid")
    try:
        bounded_transaction(db)
        db.execute(text("SELECT pg_advisory_xact_lock(73609)"))
        if (
            db.query(ReportPdfAttempt.id).filter_by(status="running").count()
            >= settings.REPORT_PDF_CONCURRENCY
        ):
            db.rollback()
            return None
        candidates = (
            db.query(ReportPdfAttempt.report_id, ReportPdfAttempt.id)
            .filter(
                ReportPdfAttempt.status == "queued",
                ReportPdfAttempt.queue_deadline > func.clock_timestamp(),
            )
            .order_by(ReportPdfAttempt.queued_at, ReportPdfAttempt.id)
            .limit(20)
            .all()
        )
        for report_id, attempt_id in candidates:
            report, archive, attempt = lock_pdf_rows(
                db, report_id, attempt_id, skip_locked=True
            )
            now = db_now(db)
            if not (
                report
                and report.status == "completed"
                and archive
                and archive.current_attempt_id == attempt_id
                and archive.published_attempt_id is None
                and attempt
                and attempt.status == "queued"
                and attempt.queue_deadline > now
            ):
                continue
            attempt.status = "running"
            attempt.phase = "source_validation"
            attempt.started_at = now
            attempt.heartbeat_at = now
            attempt.run_deadline = now + timedelta(
                seconds=settings.REPORT_PDF_RUN_SECONDS
            )
            attempt.lease_expires_at = min(
                now + timedelta(seconds=settings.REPORT_PDF_LEASE_SECONDS),
                attempt.run_deadline,
            )
            attempt.lease_owner = owner
            attempt.lease_token = uuid4()
            archive.state = "rendering"
            archive.revision += 1
            archive.updated_at = now
            claim = PdfClaim(
                report_id=report_id,
                attempt_id=attempt.id,
                lease_token=attempt.lease_token,
                lease_owner=owner,
                run_deadline=attempt.run_deadline,
                source_sha256=attempt.source_sha256,
                renderer_sha256=attempt.renderer_sha256,
                object_key=attempt.object_key,
            )
            db.commit()
            return claim
        db.rollback()
        return None
    except Exception:
        db.rollback()
        raise


def heartbeat_pdf(db, claim, phase=None):
    if phase is not None and phase not in PDF_PHASES[1:-1]:
        raise ValueError("pdf_protocol_invalid")
    try:
        report, archive, attempt = lock_pdf_rows(db, claim.report_id, claim.attempt_id)
        now = db_now(db)
        if not claim_may_publish(report, archive, attempt, claim, now):
            db.rollback()
            return False
        if phase is not None:
            if PDF_PHASES.index(phase) < PDF_PHASES.index(attempt.phase):
                db.rollback()
                return False
            if attempt.phase != phase:
                attempt.phase = phase
                archive.revision += 1
                archive.updated_at = now
        attempt.heartbeat_at = now
        attempt.lease_expires_at = min(
            now + timedelta(seconds=settings.REPORT_PDF_LEASE_SECONDS),
            attempt.run_deadline,
        )
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def enqueue_cleanup(db, attempt):
    db.execute(
        text(
            """INSERT INTO report_file_cleanup_tasks(report_id_snapshot,object_key,not_before_final_check)
        VALUES(:report,:key,GREATEST(clock_timestamp(),COALESCE(:deadline,clock_timestamp()))+interval '60 seconds')
        ON CONFLICT(object_key) DO UPDATE SET state='pending',completed_at=NULL,next_attempt_at=clock_timestamp(),
        not_before_final_check=GREATEST(report_file_cleanup_tasks.not_before_final_check,EXCLUDED.not_before_final_check)"""
        ),
        {
            "report": attempt.report_id,
            "key": attempt.object_key,
            "deadline": attempt.run_deadline,
        },
    )


def _failed(db, archive, attempt, code, now):
    attempt.status = "failed"
    attempt.finished_at = now
    attempt.error_code = safe_pdf_code(code)
    attempt.lease_token = None
    attempt.lease_owner = None
    attempt.lease_expires_at = None
    if (
        archive.current_attempt_id == attempt.id
        and archive.published_attempt_id is None
    ):
        archive.state = "failed"
        archive.revision += 1
        archive.updated_at = now
    enqueue_cleanup(db, attempt)


def fail_pdf(db, claim, code):
    try:
        report, archive, attempt = lock_pdf_rows(db, claim.report_id, claim.attempt_id)
        now = db_now(db)
        if not claim_may_publish(report, archive, attempt, claim, now):
            db.rollback()
            return False
        _failed(db, archive, attempt, code, now)
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def sweep_pdf(db):
    try:
        bounded_transaction(db)
        candidates = (
            db.query(ReportPdfAttempt.report_id, ReportPdfAttempt.id)
            .filter(
                or_(
                    (ReportPdfAttempt.status == "queued")
                    & (ReportPdfAttempt.queue_deadline <= func.clock_timestamp()),
                    (ReportPdfAttempt.status == "running")
                    & or_(
                        ReportPdfAttempt.lease_expires_at <= func.clock_timestamp(),
                        ReportPdfAttempt.run_deadline <= func.clock_timestamp(),
                    ),
                )
            )
            .order_by(ReportPdfAttempt.id)
            .limit(100)
            .all()
        )
        count = 0
        for report_id, attempt_id in candidates:
            report, archive, attempt = lock_pdf_rows(
                db, report_id, attempt_id, skip_locked=True
            )
            now = db_now(db)
            if not archive or not attempt or archive.published_attempt_id is not None:
                continue
            if attempt.status == "queued" and attempt.queue_deadline <= now:
                code = "pdf_queue_timeout"
            elif (
                attempt.status == "running"
                and min(attempt.lease_expires_at, attempt.run_deadline) <= now
            ):
                code = (
                    "pdf_render_timeout"
                    if attempt.run_deadline <= now
                    else "pdf_worker_interrupted"
                )
            else:
                continue
            _failed(db, archive, attempt, code, now)
            count += 1
        db.commit()
        return count
    except Exception:
        db.rollback()
        raise


def publish_pdf(db, claim, candidate, storage):
    from app.services.report_read_service import (
        read_owned_report,
        build_pdf_source,
        source_digest,
    )

    candidate = PdfCandidate.model_validate(candidate)
    if candidate.object_key != claim.object_key:
        raise PdfError("pdf_render_failed")
    # File IO and parsing happen before acquiring any database row lock.
    with storage.open_verified(
        candidate.object_key, candidate.pdf_sha256, candidate.size_bytes
    ) as stream:
        import fitz

        with fitz.open(stream=stream.read(), filetype="pdf") as document:
            if document.page_count != candidate.page_count:
                raise PdfError("pdf_original_corrupt")
        try:
            report, archive, attempt = lock_pdf_rows(
                db, claim.report_id, claim.attempt_id
            )
            if not claim_may_publish(report, archive, attempt, claim, db_now(db)):
                db.rollback()
                return False
            source = build_pdf_source(read_owned_report(db, report.user_id, report.id))
            if source_digest(source) != claim.source_sha256:
                raise PdfError("pdf_source_changed")
            now = db_now(db)
            if not claim_may_publish(report, archive, attempt, claim, now):
                db.rollback()
                return False
            attempt.status = "completed"
            attempt.phase = "terminal"
            attempt.finished_at = now
            attempt.lease_token = None
            attempt.lease_owner = None
            attempt.lease_expires_at = None
            archive.state = "ready"
            archive.published_attempt_id = attempt.id
            archive.pdf_sha256 = candidate.pdf_sha256
            archive.size_bytes = candidate.size_bytes
            archive.page_count = candidate.page_count
            archive.archived_at = now
            archive.updated_at = now
            archive.revision += 1
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise
