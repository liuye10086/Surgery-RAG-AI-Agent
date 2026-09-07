"""Append-only, lease-fenced checkpoints; no feature values or exception text."""

import json
import re
from uuid import UUID
from sqlalchemy import select

from app.db.models import ReportGenerationAuditRecord
from app.schemas.report_generation_audit import (
    GenerationAuditEvent,
    GenerationAuditSummary,
)
from app.services.report_generation_errors import safe_code

MAX_EVENTS = 256
MAX_EVENT_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
TERMINAL_RESERVE_BYTES = 4096


def encode_audit_event(event):
    event = GenerationAuditEvent.model_validate(event)
    if event.input_audit and len(event.input_audit.fields) > 1024:
        raise ValueError("audit_limit_exceeded")
    if event.input_audit:
        audit = event.input_audit
        tokens = [
            audit.reason_code,
            audit.numeric_imputation,
            audit.categorical_imputation,
        ]
        if any(
            value is not None and not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,120}", value)
            for value in tokens
        ):
            raise ValueError("audit_code_invalid")
        if any(
            not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,160}", field.name)
            for field in audit.fields
        ):
            raise ValueError("audit_field_invalid")
    payload = event.model_dump(mode="json")
    # Include JSONB's whitespace representation in the bound, not only compact IPC.
    size = len(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True).encode(
            "utf-8"
        )
    )
    if size > MAX_EVENT_BYTES:
        raise ValueError("audit_limit_exceeded")
    return payload, size


def append_locked_event(db, job, batch_id, event):
    payload, size = encode_audit_event(event)
    terminal = payload["kind"] == "terminal"
    count, total = job.audit_event_count or 0, job.audit_bytes or 0
    if count >= MAX_EVENTS - (
        0 if terminal else 1
    ) or total + size > MAX_TOTAL_BYTES - (0 if terminal else TERMINAL_RESERVE_BYTES):
        raise ValueError("audit_limit_exceeded")
    db.add(
        ReportGenerationAuditRecord(
            report_id=job.report_id,
            event_seq=count + 1,
            generation_batch_id=UUID(str(batch_id)),
            event_kind=payload["kind"],
            phase=payload["phase"],
            task=payload["task"],
            payload=payload,
            payload_bytes=size,
        )
    )
    job.audit_event_count = count + 1
    job.audit_bytes = total + size


def append_generation_audit(db, claim, event):
    from app.services.report_job_repository import (
        _job_lock,
        _report_lock,
        _valid,
        db_now,
    )

    try:
        event = GenerationAuditEvent.model_validate(event)
        if event.kind == "terminal":
            raise ValueError("execution_protocol_invalid")
        job = _job_lock(db, claim.report_id)
        if not _valid(job, claim, db_now(db)) or event.phase != job.phase:
            db.rollback()
            return False
        report = _report_lock(db, claim.report_id)
        if (
            not report
            or report.generation_batch_id != str(claim.batch_id)
            or report.user_id != job.user_id
            or not _valid(job, claim, db_now(db))
        ):
            db.rollback()
            return False
        append_locked_event(db, job, claim.batch_id, event)
        job.last_execution_phase = event.phase
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def read_generation_audit(db, job, batch_id):
    rows = (
        db.execute(
            select(ReportGenerationAuditRecord.__table__)
            .where(
                ReportGenerationAuditRecord.report_id == job["report_id"],
            )
            .order_by(ReportGenerationAuditRecord.event_seq)
            .limit(MAX_EVENTS)
        )
        .mappings()
        .all()
    )
    events, total = [], 0
    for seq, row in enumerate(rows, 1):
        if row["event_seq"] != seq or str(row["generation_batch_id"]) != batch_id:
            raise ValueError("audit_integrity_failed")
        event = GenerationAuditEvent.model_validate(row["payload"])
        _, size = encode_audit_event(event)
        total += size
        if (
            row["payload_bytes"] != size
            or row["event_kind"] != event.kind
            or row["phase"] != event.phase
            or row["task"] != event.task
        ):
            raise ValueError("audit_integrity_failed")
        events.append(event)
    if len(events) != job["audit_event_count"] or total != job["audit_bytes"]:
        raise ValueError("audit_integrity_failed")
    return GenerationAuditSummary(
        last_execution_phase=job["last_execution_phase"],
        failure_phase=job["failure_phase"],
        error_code=safe_code(job["error_code"]) if job["error_code"] else None,
        event_count=len(events),
        events=events,
        note=(
            "仅展示已确认记录；缺少结束事件不代表模型未调用。"
            if events
            else "历史报告未保存生成审计事件。"
        ),
    )
