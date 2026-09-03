"""Append-only audit helpers for operator case commands."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.db.models import OperatorCaseChangeLog


ALLOWED_ACTIONS = {
    "created",
    "profile_updated",
    "timeline_updated",
    "case_updated",
    "deleted",
}
CREATION_REASON = "系统：建立病例"
DELETION_REASON = "用户确认删除病例"


def append_case_change_log(
    db,
    *,
    case: Any,
    actor_id: int,
    action: str,
    reason: str,
    changes: dict[str, Any],
) -> OperatorCaseChangeLog:
    normalized_reason = reason.strip() if isinstance(reason, str) else ""
    if action not in ALLOWED_ACTIONS:
        raise ValueError("operator_case_audit_action_invalid")
    if not 1 <= len(normalized_reason) <= 500:
        raise ValueError("operator_case_audit_reason_invalid")
    if not isinstance(changes, dict):
        raise ValueError("operator_case_audit_changes_invalid")

    row = OperatorCaseChangeLog(
        case_id=case.id,
        case_id_snapshot=case.id,
        anonymous_case_code_snapshot=getattr(case, "anonymous_case_code", None),
        actor_id=actor_id,
        actor_id_snapshot=actor_id,
        action=action,
        reason=normalized_reason,
        changes=deepcopy(changes),
    )
    db.add(row)
    db.flush()
    return row


def build_creation_changes(case: Any, *, visit_count: int) -> dict[str, Any]:
    return {
        "created": {
            "disease_id": case.disease_id,
            "baseline_stage": case.baseline_stage,
            "visit_count": visit_count,
            "profile_fields": ["age", "sex", "baseline_stage", "notes"],
        }
    }


def build_deletion_changes() -> dict[str, Any]:
    return {"deleted": {"before": True, "after": False}}
