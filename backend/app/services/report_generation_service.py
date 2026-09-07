"""Idempotent admission and durable state queries, independent of SSE clients."""

from datetime import timedelta
from uuid import uuid4
from sqlalchemy import text
from app.core.config import settings
from app.db.models import (
    AIReport,
    ReportGenerationJob,
    OperatorIdempotencyKey,
    ReferenceStandardVersion,
)
from app.schemas.report_generation import JobAccepted, GenerationStatus
from app.services.report_generation_errors import ReportJobError, MESSAGES, safe_code
from app.services.report_generation_idempotency import REPORT_SCOPE, hash_report_request
from app.services.operator_case_idempotency import (
    parse_idempotency_key,
    IdempotencyKeyError,
)
from app.services.longitudinal_case_service import (
    get_operator_case,
    get_operator_case_for_write,
    build_input_snapshot,
    CaseNotFoundError,
    ArchivedCaseError,
)
from app.services.operator_case_readiness import evaluate_operator_case_readiness
from app.services.report_generation_context import capture_generation_context
from app.services.report_standard_identity import standard_rules_hash
from app.services.longitudinal_release_set import read_active_pointer
from app.services.report_integrity import compute_input_snapshot_sha256
from app.services.report_job_repository import (
    db_now,
    context_hash,
    _job_lock,
    _report_lock,
    _terminal,
)


def _accepted(report, job):
    return JobAccepted(
        report_id=report.id,
        batch_id=report.generation_batch_id,
        status=job.status,
        status_url=f"/api/v1/operator/reports/{report.id}/generation-status",
        events_url=f"/api/v1/operator/reports/{report.id}/events",
    )


def _replay(db, user_id, key, digest):
    row = (
        db.query(OperatorIdempotencyKey)
        .filter_by(user_id=user_id, scope=REPORT_SCOPE, idempotency_key=key)
        .first()
    )
    if not row:
        return None
    if row.request_sha256 != digest:
        raise ReportJobError("idempotency_conflict")
    result = (
        db.query(AIReport, ReportGenerationJob)
        .join(ReportGenerationJob, ReportGenerationJob.report_id == AIReport.id)
        .filter(AIReport.id == row.resource_id, AIReport.user_id == user_id)
        .first()
    )
    if result is None:
        raise ReportJobError("idempotency_resource_missing")
    return _accepted(*result)


def submit_report_job(user_id, case_id, key, request, session_factory, registry_root):
    try:
        key = parse_idempotency_key(key)
    except IdempotencyKeyError as exc:
        raise ReportJobError(exc.code, 422) from exc
    try:
        digest = hash_report_request(case_id, request)
    except ValueError as exc:
        raise ReportJobError("unsupported_report_options", 422) from exc
    with session_factory() as db:
        replay = _replay(db, user_id, key, digest)
        if replay:
            return replay
    if not settings.REPORT_JOBS_ENABLED or not settings.REPORT_JOBS_ACCEPTING:
        raise ReportJobError("report_jobs_unavailable", 503)
    try:
        with session_factory() as db:
            case = get_operator_case(db, user_id, case_id)
            readiness = evaluate_operator_case_readiness(
                case, registry_root, load_runtime=False
            )
            if not readiness.ready:
                codes = {b.code for b in getattr(readiness, "blockers", [])}
                code = next(
                    (
                        c
                        for c in (
                            "disease_disabled",
                            "case_archived",
                            "case_incomplete",
                            "invalid_timeline",
                            "model_unavailable",
                        )
                        if c in codes
                    ),
                    "report_not_ready",
                )
                raise ReportJobError(code, 503 if code == "model_unavailable" else 409)
            snapshot = build_input_snapshot(case, case.visits, {})
        context = capture_generation_context(snapshot, session_factory, registry_root)
        with session_factory() as db:
            # Only the final comparison and insert are serialized.
            db.execute(text("SET LOCAL statement_timeout = '5000ms'"))
            db.execute(text("SELECT pg_advisory_xact_lock(73606)"))
            replay = _replay(db, user_id, key, digest)
            if replay:
                return replay
            case = get_operator_case_for_write(db, user_id, case_id)
            current_snapshot = build_input_snapshot(case, case.visits, {})
            if compute_input_snapshot_sha256(
                current_snapshot
            ) != compute_input_snapshot_sha256(snapshot):
                raise ReportJobError("case_changed")
            pointer = read_active_pointer(registry_root, context.disease_code)
            if (pointer.release_set_id, pointer.release_set_sha256) != (
                context.release_set_id,
                context.release_set_sha256,
            ):
                raise ReportJobError("generation_context_changed")
            pinned = context.evidence_token.standard
            version = (
                db.query(ReferenceStandardVersion)
                .filter_by(id=pinned.version_id)
                .with_for_update()
                .first()
            )
            if not version or version.status != "approved":
                raise ReportJobError("standard_not_approved", 503)
            if (
                version.standard_id != pinned.standard_id
                or version.standard_document_id != pinned.document_id
                or version.content_hash != pinned.version_sha256
                or version.standard_document.content_hash != pinned.document_sha256
            ):
                raise ReportJobError("standard_integrity_failed", 503)
            if (
                standard_rules_hash(db, pinned.version_id)
                != context.standard_rules_sha256
            ):
                raise ReportJobError("standard_integrity_failed", 503)
            active = db.query(ReportGenerationJob).filter(
                ReportGenerationJob.status.in_(["queued", "running"])
            )
            same_case = active.filter_by(
                user_id=user_id, source_case_id=case_id
            ).first()
            if same_case:
                raise ReportJobError("active_report_exists", 409, same_case.report_id)
            if (
                active.filter_by(user_id=user_id).count()
                >= settings.REPORT_JOB_USER_ACTIVE_LIMIT
                or db.query(ReportGenerationJob).filter_by(status="queued").count()
                >= settings.REPORT_JOB_QUEUED_LIMIT
            ):
                raise ReportJobError("report_capacity_exceeded", 429)
            batch = str(uuid4())
            snapshot["generation_batch_id"] = batch
            snapshot["input_snapshot_sha256"] = compute_input_snapshot_sha256(snapshot)
            report = AIReport(
                user_id=user_id,
                operator_case_id=case.id,
                disease_id=case.disease_id,
                query=snapshot.get("anonymous_case_code") or "纵向进展预测报告",
                title="纵向进展预测报告",
                analysis_type="longitudinal_predictive",
                status="generating",
                input_snapshot=snapshot,
                input_snapshot_sha256=snapshot["input_snapshot_sha256"],
                generation_batch_id=batch,
            )
            db.add(report)
            db.flush()
            context_payload = context.model_dump(mode="json")
            job = ReportGenerationJob(
                report_id=report.id,
                user_id=user_id,
                source_case_id=case_id,
                generation_context=context_payload,
                context_sha256=context_hash(context_payload),
                status="queued",
                queue_deadline=db_now(db)
                + timedelta(seconds=settings.REPORT_JOB_QUEUE_SECONDS),
            )
            db.add(job)
            db.add(
                OperatorIdempotencyKey(
                    user_id=user_id,
                    scope=REPORT_SCOPE,
                    idempotency_key=key,
                    request_sha256=digest,
                    resource_type="ai_report",
                    resource_id=report.id,
                )
            )
            accepted = _accepted(report, job)
            db.commit()
            return accepted
    except ReportJobError:
        raise
    except ArchivedCaseError as exc:
        raise ReportJobError("case_archived", 409) from exc
    except CaseNotFoundError as exc:
        raise ReportJobError("case_not_found", 404) from exc
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code is None and isinstance(exc, ValueError) and len(exc.args) == 1:
            code = exc.args[0]
        raise ReportJobError(safe_code(code), 503) from exc


def get_generation_status(db, user_id, report_id):
    row = (
        db.query(AIReport, ReportGenerationJob)
        .outerjoin(ReportGenerationJob, ReportGenerationJob.report_id == AIReport.id)
        .filter(AIReport.id == report_id, AIReport.user_id == user_id)
        .populate_existing()
        .first()
    )
    if not row:
        raise ReportJobError("report_not_found", 404)
    report, job = row
    if job is None:
        if report.status == "generating":
            raise ReportJobError("legacy_generation_unmanaged")
        code = (None if report.status == "completed" else "cancelled_by_user"
                if report.status == "cancelled" else safe_code(getattr(report, "error_message", None)))
        return GenerationStatus(
            report_id=report.id,
            batch_id=report.generation_batch_id,
            status=report.status,
            report_status=report.status,
            phase="terminal",
            revision=1,
            updated_at=report.updated_at,
            message=MESSAGES[code] if code else "历史报告",
            error_code=code,
            legacy=True,
        )
    code = safe_code(job.error_code) if job.error_code else None
    return GenerationStatus(
        report_id=report.id,
        batch_id=report.generation_batch_id,
        status=job.status,
        report_status=report.status,
        phase=job.phase,
        revision=job.revision,
        updated_at=job.updated_at,
        error_code=code,
        message=MESSAGES[code]
        if code
        else {
            "queued": "报告已排队",
            "running": "报告生成中",
            "completed": "报告已完成",
            "failed": "报告生成失败",
            "cancelled": "报告已取消",
        }[job.status],
        cancel_requested=job.cancel_requested_at is not None,
        failure_phase=getattr(job, "failure_phase", None),
    )


def cancel_report_job(db, user_id, report_id):
    try:
        job = _job_lock(db, report_id)
        report = _report_lock(db, report_id)
        if report is None or report.user_id != user_id:
            raise ReportJobError("report_not_found", 404)
        if job and job.status in ("queued", "running"):
            now = db_now(db)
            job.cancel_requested_at = now
            _terminal(job, report, "cancelled", "cancelled_by_user", now)
        elif job is None and report.status == "generating":
            raise ReportJobError("legacy_generation_unmanaged")
        db.commit()
        return get_generation_status(db, user_id, report_id)
    except Exception:
        db.rollback()
        raise


def delete_report_job(db, user_id, report_id):
    try:
        job = _job_lock(db, report_id)
        report = _report_lock(db, report_id)
        if report is None or report.user_id != user_id:
            raise ReportJobError("report_not_found", 404)
        if report.status == "generating" or (
            job and job.status in ("queued", "running")
        ):
            raise ReportJobError("active_report_delete_forbidden")
        from app.db.models import ReportPdfArchive, ReportPdfAttempt
        db.query(ReportPdfArchive).filter_by(report_id=report_id).with_for_update().first()
        db.query(ReportPdfAttempt).filter_by(report_id=report_id).order_by(ReportPdfAttempt.id).with_for_update().all()
        db.delete(report)
        db.commit()
    except Exception:
        db.rollback()
        raise
