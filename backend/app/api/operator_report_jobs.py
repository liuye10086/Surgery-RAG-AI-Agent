"""Report job endpoints. Streams observe persisted state and never own work."""

import asyncio
import json
import time
from uuid import uuid4
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import require_ai_operator, oauth2_scheme
from app.core.config import settings
from app.core.security import decode_token
from app.db.session import get_db
from app.db.models import User, AIReport
from app.services.model_paths import MODEL_DIR
from app.services.report_generation_service import (
    submit_report_job,
    get_generation_status,
    cancel_report_job,
)
from app.services.report_generation_errors import ReportJobError

router = APIRouter(prefix="/operator", tags=["operator"])


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_options: dict = Field(default_factory=dict)

    @field_validator("model_options")
    @classmethod
    def no_options(cls, value):
        if value:
            raise ValueError("unsupported_report_options")
        return value


def http_error(error):
    detail = {"code": error.code, "message": error.message}
    if error.report_id is not None:
        detail["report_id"] = error.report_id
    return HTTPException(
        error.status_code,
        detail=detail,
        headers={"Retry-After": "10"} if error.status_code == 429 else None,
    )


def session_factory(db):
    return sessionmaker(bind=db.get_bind(), expire_on_commit=False)


def encode_state(state):
    body = json.dumps(
        state.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
    )
    identity = (
        str(state.batch_id) if state.batch_id else f"legacy-report-{state.report_id}"
    )
    return f"id: {identity}:{state.revision}\nevent: state\ndata: {body}\n\n"


def _event(kind, body):
    return f"event: {kind}\ndata: {json.dumps(body, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _read_state(factory, user_id, report_id):
    with factory() as db:
        user = db.get(User, user_id)
        if user is None or user.role not in ("ai_operator", "admin"):
            raise ReportJobError("auth_expired", 401)
        return get_generation_status(db, user_id, report_id)


def _read_completed(factory, user_id, report_id):
    from app.services.report_integrity import verify_report_integrity

    with factory() as db:
        report = db.query(AIReport).filter_by(id=report_id, user_id=user_id).first()
        if not report or report.status != "completed":
            raise ReportJobError("report_not_found", 404)
        integrity = verify_report_integrity(
            report.input_snapshot,
            report.input_snapshot_sha256,
            report.generation_fingerprint,
            report.prediction_result,
            report.content,
            report.evidence_snapshot,
            report.evidence_snapshot_sha256,
            report_document=report.report_document,
            report_document_sha256=report.report_document_sha256,
            generation_fingerprint_version=report.generation_fingerprint_version,
            saved_sources=report.sources,
        )
        if integrity.status != "valid":
            raise ReportJobError("report_generation_contract_mismatch")
        return report.prediction_result, report.evidence_snapshot, report.content


async def stream_states(factory, user_id, report_id, expires_at, *, legacy=False):
    last = None
    heartbeat = time.monotonic()
    while True:
        if time.time() >= expires_at:
            yield _event(
                "error", {"code": "auth_expired", "message": "登录已过期，请重新登录"}
            )
            return
        try:
            state = await asyncio.to_thread(_read_state, factory, user_id, report_id)
        except ReportJobError as exc:
            yield _event("error", {"code": exc.code, "message": exc.message})
            return
        except Exception:
            yield _event(
                "error",
                {
                    "code": "generation_status_unavailable",
                    "message": "生成状态暂不可用，请重新连接",
                },
            )
            return
        identity = (state.batch_id, state.revision)
        if identity != last:
            last = identity
            yield encode_state(state)
        if state.status in ("completed", "failed", "cancelled"):
            if legacy and state.status == "completed":
                try:
                    prediction, evidence, content = await asyncio.to_thread(
                        _read_completed, factory, user_id, report_id
                    )
                except ReportJobError as exc:
                    yield _event("error", {"code": exc.code, "message": exc.message})
                    return
                yield _event("prediction", prediction)
                if evidence:
                    yield _event("evidence", evidence)
                for index in range(0, len(content), 600):
                    yield _event("delta", {"content": content[index : index + 600]})
                yield _event("done", {"report_id": report_id, "status": "completed"})
            elif legacy:
                yield _event(
                    "error",
                    {
                        "code": state.error_code or state.status,
                        "message": state.message,
                    },
                )
            return
        if time.monotonic() - heartbeat >= 15:
            yield ": heartbeat\n\n"
            heartbeat = time.monotonic()
        await asyncio.sleep(1)


def stream_response(
    factory, user_id, report_id, token, *, legacy=False, deprecated=False
):
    expires = decode_token(token, settings.JWT_SECRET, settings.JWT_ALGORITHM)["exp"]
    headers = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    if deprecated:
        headers["Deprecation"] = "true"
    return StreamingResponse(
        stream_states(factory, user_id, report_id, expires, legacy=legacy),
        media_type="text/event-stream",
        headers=headers,
    )


@router.post("/longitudinal-cases/{case_id}/report-jobs", status_code=202)
def submit(
    case_id: int,
    request: JobRequest,
    idempotency_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    user_id = current_user.id
    factory = session_factory(db)
    db.rollback()
    try:
        return submit_report_job(
            user_id, case_id, idempotency_key, request.model_dump(), factory, MODEL_DIR
        )
    except ReportJobError as exc:
        raise http_error(exc) from exc


@router.get("/reports/{report_id}/generation-status")
def get_status(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    try:
        return get_generation_status(db, current_user.id, report_id)
    except ReportJobError as exc:
        raise http_error(exc) from exc


@router.post("/reports/{report_id}/cancel")
def cancel(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    user_id = current_user.id
    db.rollback()
    try:
        return cancel_report_job(db, user_id, report_id)
    except ReportJobError as exc:
        raise http_error(exc) from exc


@router.get("/reports/{report_id}/events")
def events(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
    token: str = Depends(oauth2_scheme),
):
    user_id = current_user.id
    try:
        get_generation_status(db, user_id, report_id)
    except ReportJobError as exc:
        raise http_error(exc) from exc
    factory = session_factory(db)
    db.rollback()
    return stream_response(factory, user_id, report_id, token)


def legacy_submit(case_id, request, db, current_user, key, token):
    if not settings.REPORT_LEGACY_SSE_ENABLED:
        raise HTTPException(
            410,
            detail={
                "code": "legacy_report_route_retired",
                "message": "请使用报告任务接口",
            },
        )
    user_id = current_user.id
    factory = session_factory(db)
    db.rollback()
    try:
        accepted = submit_report_job(
            user_id, case_id, key or str(uuid4()), request, factory, MODEL_DIR
        )
    except ReportJobError as exc:
        raise http_error(exc) from exc
    return stream_response(
        factory, user_id, accepted.report_id, token, legacy=True, deprecated=True
    )
