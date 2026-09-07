"""Short PostgreSQL transactions, database-clock leases and fenced publication.

Lock order is always job then report. Callers provide an otherwise clean session.
"""

from datetime import timedelta
import hashlib
import json
from uuid import uuid4, UUID

from sqlalchemy import text, or_, and_, func
from app.core.config import settings
from app.services.report_generation_errors import safe_code
from app.db.models import AIReport, ReportGenerationJob
from app.schemas.report_generation import JobClaim
from app.schemas.report_document import Publication
from app.services.report_integrity import compute_input_snapshot_sha256

PHASES = [
    "queued",
    "model_loading",
    "prediction",
    "standard_evidence",
    "rendering",
    "persistence",
    "terminal",
]


def context_hash(context):
    return hashlib.sha256(
        json.dumps(
            context,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def db_now(db):
    return db.execute(text("SELECT clock_timestamp()")).scalar_one()


def bounded_transaction(db):
    # Never let a lock waiter stall lease supervision indefinitely.
    db.execute(text("SET LOCAL statement_timeout = '5000ms'"))
    db.execute(text("SET LOCAL lock_timeout = '3000ms'"))


def _job_lock(db, report_id):
    bounded_transaction(db)
    return (
        db.query(ReportGenerationJob)
        .filter_by(report_id=report_id)
        .populate_existing()
        .with_for_update()
        .first()
    )


def _report_lock(db, report_id):
    return (
        db.query(AIReport)
        .filter_by(id=report_id)
        .populate_existing()
        .with_for_update()
        .first()
    )


def _valid(job, claim, now):
    return bool(
        job
        and job.status == "running"
        and job.lease_token == claim.lease_token
        and job.lease_owner == claim.lease_owner
        and job.cancel_requested_at is None
        and job.lease_expires_at > now
        and job.run_deadline > now
    )


def claim_next(db, owner):
    if not owner or len(owner) > 160:
        raise ValueError("worker_owner_invalid")
    try:
        bounded_transaction(db)
        # Enforce the approved single-execution resource budget across workers.
        db.execute(text("SELECT pg_advisory_xact_lock(73607)"))
        if (
            db.query(ReportGenerationJob).filter_by(status="running").count()
            >= settings.REPORT_JOB_CONCURRENCY
        ):
            db.rollback()
            return None
        job = (
            db.query(ReportGenerationJob)
            .filter(
                ReportGenerationJob.status == "queued",
                ReportGenerationJob.queue_deadline > func.clock_timestamp(),
                ReportGenerationJob.cancel_requested_at.is_(None),
            )
            .order_by(ReportGenerationJob.queued_at, ReportGenerationJob.report_id)
            .with_for_update(skip_locked=True)
            .first()
        )
        if job is None:
            db.rollback()
            return None
        report = _report_lock(db, job.report_id)
        if (
            report is None
            or report.status != "generating"
            or report.user_id != job.user_id
        ):
            db.rollback()
            return None
        now = db_now(db)
        if job.queue_deadline <= now:
            db.rollback()
            return None
        job.status = "running"
        job.phase = "model_loading"
        job.started_at = now
        job.updated_at = now
        job.heartbeat_at = now
        job.revision += 1
        job.run_deadline = now + timedelta(seconds=settings.REPORT_JOB_RUN_SECONDS)
        job.lease_expires_at = now + timedelta(
            seconds=settings.REPORT_JOB_LEASE_SECONDS
        )
        job.lease_owner = owner
        job.lease_token = uuid4()
        claim = JobClaim(
            report_id=report.id,
            batch_id=UUID(report.generation_batch_id),
            lease_token=job.lease_token,
            lease_owner=owner,
            run_deadline=job.run_deadline,
        )
        db.commit()
        return claim
    except Exception:
        db.rollback()
        raise


def heartbeat(db, claim):
    try:
        job = _job_lock(db, claim.report_id)
        now = db_now(db)
        if not _valid(job, claim, now):
            db.rollback()
            return False
        job.heartbeat_at = now
        job.updated_at = now
        job.lease_expires_at = min(
            now + timedelta(seconds=settings.REPORT_JOB_LEASE_SECONDS), job.run_deadline
        )
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def update_phase(db, claim, phase):
    if phase not in PHASES[1:-1]:
        raise ValueError("execution_protocol_invalid")
    try:
        job = _job_lock(db, claim.report_id)
        now = db_now(db)
        if not _valid(job, claim, now) or PHASES.index(phase) < PHASES.index(job.phase):
            db.rollback()
            return False
        if job.phase != phase:
            job.phase = phase
            job.revision += 1
            job.updated_at = now
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def _terminal(job, report, status, code, now):
    job.status = status
    job.phase = "terminal"
    job.error_code = safe_code(code) if code is not None else None
    job.finished_at = now
    job.updated_at = now
    job.revision += 1
    job.lease_token = None
    job.lease_owner = None
    job.lease_expires_at = None
    report.status = status
    report.updated_at = now
    report.error_stage = None if status == "completed" else "generation"
    report.error_message = None if status == "completed" else job.error_code


def finish_job(db, claim, status, code):
    if status not in ("failed", "cancelled"):
        raise ValueError("invalid_terminal_status")
    try:
        job = _job_lock(db, claim.report_id)
        now = db_now(db)
        if not _valid(job, claim, now):
            db.rollback()
            return False
        report = _report_lock(db, claim.report_id)
        if (
            not report
            or report.status != "generating"
            or report.user_id != job.user_id
            or report.generation_batch_id != str(claim.batch_id)
        ):
            db.rollback()
            return False
        now = db_now(db)
        if not _valid(job, claim, now):
            db.rollback()
            return False
        _terminal(job, report, status, code, now)
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def publish_completed(db, claim, publication):
    from app.schemas.longitudinal_evidence import EvidenceBundle
    from app.services.evidence_bundle import EvidenceBuildResult
    from app.services.report_publication import build_publication

    try:
        db.execute(text("SET LOCAL statement_timeout = '5000ms'"))
        job = _job_lock(db, claim.report_id)
        now = db_now(db)
        if not _valid(job, claim, now):
            db.rollback()
            return False
        report = _report_lock(db, claim.report_id)
        publication = Publication.model_validate(publication.model_dump(mode="json"))
        doc = publication.report_document
        if (
            not report
            or report.status != "generating"
            or report.user_id != job.user_id
            or report.generation_batch_id != str(claim.batch_id)
            or doc.identity.report_id != claim.report_id
            or str(doc.identity.batch_id) != report.generation_batch_id
            or context_hash(job.generation_context) != job.context_sha256
            or doc.generation_context.model_dump(mode="json") != job.generation_context
            or compute_input_snapshot_sha256(report.input_snapshot)
            != report.input_snapshot_sha256
        ):
            db.rollback()
            return False
        rebuilt = build_publication(
            report.input_snapshot,
            publication.prediction_result,
            EvidenceBuildResult(
                EvidenceBundle.model_validate(publication.evidence_snapshot),
                publication.evidence_status,
                tuple(publication.sources),
            ),
            doc,
        )
        if rebuilt.model_dump(mode="json") != publication.model_dump(mode="json"):
            db.rollback()
            return False
        # Recheck the DB clock after validation before publishing.
        now = db_now(db)
        if not _valid(job, claim, now):
            db.rollback()
            return False
        for key, value in publication.model_dump(mode="json").items():
            setattr(report, key, value)
        _terminal(job, report, "completed", None, now)
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def reap_expired(db):
    try:
        bounded_transaction(db)
        now = db_now(db)
        jobs = (
            db.query(ReportGenerationJob)
            .filter(
                or_(
                    and_(
                        ReportGenerationJob.status == "queued",
                        ReportGenerationJob.queue_deadline <= now,
                    ),
                    and_(
                        ReportGenerationJob.status == "running",
                        or_(
                            ReportGenerationJob.lease_expires_at <= now,
                            ReportGenerationJob.run_deadline <= now,
                        ),
                    ),
                )
            )
            .order_by(ReportGenerationJob.report_id)
            .with_for_update(skip_locked=True)
            .all()
        )
        count = 0
        for job in jobs:
            report = _report_lock(db, job.report_id)
            if not report or report.status != "generating":
                continue
            code = (
                "queue_timeout"
                if job.status == "queued"
                else "run_timeout"
                if job.run_deadline <= now
                else "worker_interrupted"
            )
            _terminal(
                job,
                report,
                "cancelled" if job.cancel_requested_at else "failed",
                "cancelled_by_user" if job.cancel_requested_at else code,
                now,
            )
            count += 1
        db.commit()
        return count
    except Exception:
        db.rollback()
        raise
