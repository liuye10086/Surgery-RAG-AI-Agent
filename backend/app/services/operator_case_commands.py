"""Transaction-owning commands for operator case creation and editing."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.db.models import OperatorCase, OperatorCaseVisit
from app.services.anonymous_case_code import generate_anonymous_case_code
from app.services.disease_catalog import require_operator_disease
from app.services.longitudinal_case_service import (
    get_operator_case_for_write,
    replace_case_visits_in_session,
)
from app.services.operator_case_audit import (
    CREATION_REASON,
    DELETION_REASON,
    append_case_change_log,
    build_creation_changes,
    build_deletion_changes,
)
from app.services.operator_case_diff import build_case_diff, classify_case_action
from app.services.operator_case_idempotency import (
    add_idempotency_result,
    get_idempotency_replay,
    hash_case_create,
    parse_idempotency_key,
)
from app.services.operator_case_validation import (
    normalize_operator_timeline,
    validate_operator_case_profile,
)


class OperatorCaseCommandError(ValueError):
    def __init__(self, code: str, message: str, *, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


def require_change_reason(value: str | None) -> str:
    reason = value.strip() if isinstance(value, str) else ""
    if not 1 <= len(reason) <= 500:
        raise OperatorCaseCommandError(
            "change_reason_required",
            "实际修改病例时必须填写 1–500 个字符的变更原因",
            field="change_reason",
        )
    return reason


def _generate_unique_anonymous_case_code(db) -> str:
    for _ in range(5):
        candidate = generate_anonymous_case_code()
        exists = (
            db.query(OperatorCase)
            .filter(OperatorCase.anonymous_case_code == candidate)
            .first()
        )
        if exists is None:
            return candidate
    raise OperatorCaseCommandError(
        "anonymous_case_code_generation_failed",
        "暂时无法生成匿名病例编号，请重试",
    )


def create_operator_case_command(db, user_id: int, payload, idempotency_key):
    key = parse_idempotency_key(idempotency_key)
    request_sha256 = hash_case_create(payload)
    existing = get_idempotency_replay(db, user_id, key, request_sha256)
    if existing is not None:
        return existing

    try:
        disease = require_operator_disease(db, payload.disease_id, for_update=True)
        normalized_stage = validate_operator_case_profile(
            disease.code,
            payload.age,
            payload.sex,
            payload.baseline_stage,
        )
        timeline = normalize_operator_timeline(disease.code, payload.visits)
        anonymous_code = _generate_unique_anonymous_case_code(db)
        case = OperatorCase(
            user_id=user_id,
            disease_id=disease.id,
            patient_label=anonymous_code,
            anonymous_case_code=anonymous_code,
            age=payload.age,
            sex=payload.sex,
            baseline_stage=normalized_stage,
            notes=payload.notes,
            status="active",
        )
        db.add(case)
        db.flush()
        for visit in timeline:
            db.add(
                OperatorCaseVisit(
                    case_id=case.id,
                    **visit.as_orm_kwargs(),
                )
            )
        db.flush()
        append_case_change_log(
            db,
            case=case,
            actor_id=user_id,
            action="created",
            reason=CREATION_REASON,
            changes=build_creation_changes(case, visit_count=len(timeline)),
        )
        add_idempotency_result(
            db,
            user_id=user_id,
            key=key,
            request_sha256=request_sha256,
            resource_id=case.id,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        replay = get_idempotency_replay(db, user_id, key, request_sha256)
        if replay is not None:
            return replay
        raise OperatorCaseCommandError(
            "case_write_conflict",
            "病例保存发生冲突，请重试",
        )
    except Exception:
        db.rollback()
        raise
    db.refresh(case)
    return case


def save_operator_case_command(db, user_id: int, case_id: int, payload):
    case = get_operator_case_for_write(db, user_id, case_id)
    normalized_stage = validate_operator_case_profile(
        case.disease.code,
        payload.age,
        payload.sex,
        payload.baseline_stage,
    )
    timeline = normalize_operator_timeline(case.disease.code, payload.visits)
    changes = build_case_diff(case, payload, timeline)
    if not changes:
        return case
    reason = require_change_reason(payload.change_reason)

    try:
        case.age = payload.age
        case.sex = payload.sex
        case.baseline_stage = normalized_stage
        case.notes = payload.notes
        # Timeline-only changes must also advance the aggregate's list timestamp.
        case.updated_at = func.now()
        replace_case_visits_in_session(db, case, timeline)
        append_case_change_log(
            db,
            case=case,
            actor_id=user_id,
            action=classify_case_action(changes),
            reason=reason,
            changes=changes,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(case)
    return case


def delete_operator_case_command(db, user_id: int, case_id: int) -> None:
    case = get_operator_case_for_write(db, user_id, case_id)
    try:
        append_case_change_log(
            db,
            case=case,
            actor_id=user_id,
            action="deleted",
            reason=DELETION_REASON,
            changes=build_deletion_changes(),
        )
        db.delete(case)
        db.commit()
    except Exception:
        db.rollback()
        raise
