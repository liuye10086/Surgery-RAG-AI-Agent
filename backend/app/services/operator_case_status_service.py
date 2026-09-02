"""Transactional status changes for operator-owned longitudinal cases."""

from __future__ import annotations

from app.db.models import OperatorCase, OperatorCaseStatusLog
from app.schemas.operator_case_status import (
    OperatorCaseStatus,
    OperatorCaseStatusChangeRequest,
)
from app.services.disease_catalog import require_enabled_case_disease


class OperatorCaseStatusError(ValueError):
    """Base error for status changes."""


class CaseStatusNotFoundError(OperatorCaseStatusError):
    pass


class CaseStatusConflictError(OperatorCaseStatusError):
    pass


class CaseStatusReasonError(OperatorCaseStatusError):
    pass


def change_operator_case_status(
    db,
    user_id: int,
    case_id: int,
    payload: OperatorCaseStatusChangeRequest,
) -> OperatorCase:
    """Change a case status while serializing concurrent writers.

    The case row is locked for the duration of the transaction.  Repeating an
    already-applied target status is intentionally idempotent and creates no
    audit row.
    """

    case = (
        db.query(OperatorCase)
        .filter(OperatorCase.id == case_id, OperatorCase.user_id == user_id)
        .with_for_update()
        .first()
    )
    if case is None:
        raise CaseStatusNotFoundError("病例不存在")

    try:
        current = OperatorCaseStatus(case.status)
    except ValueError as exc:
        raise OperatorCaseStatusError("病例状态不是受支持的状态") from exc
    target = payload.status
    expected = payload.expected_status

    if current == target:
        return case
    if current != expected:
        raise CaseStatusConflictError(
            f"病例状态已变化，当前为 {current.value}，请求期望 {expected.value}"
        )

    reason = payload.reason
    if reason is None or not reason.strip():
        raise CaseStatusReasonError("实际变更必须提供原因")
    reason = reason.strip()

    # Restoring a case requires the disease to remain available.  Archiving is
    # deliberately allowed even after a disease has been disabled.
    if target == OperatorCaseStatus.ACTIVE:
        require_enabled_case_disease(case)

    from_status = current.value
    case.status = target.value
    db.add(
        OperatorCaseStatusLog(
            case_id=case.id,
            case_id_snapshot=case.id,
            actor_id=user_id,
            actor_id_snapshot=user_id,
            from_status=from_status,
            to_status=target.value,
            reason=reason,
        )
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return case
