"""Version state transitions and auditable draft rule edits."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from app.db.models import ReferenceStandardVersion, StandardChangeLog, StandardRule
from app.schemas.standard import RulePatch
from app.services.standard_validation import validate_version_rules


class ImmutableVersionError(ValueError):
    pass


def _rule_snapshot(rule: Any) -> dict[str, Any]:
    fields = (
        "indicator_id", "rule_type", "comparator", "lower", "upper", "lower_inclusive",
        "upper_inclusive", "unit", "sex", "category", "applicability", "target_state_type",
        "target_state_value", "clinical_dimension", "evidence_type", "machine_actionability",
        "interpretation", "priority", "conflict_group", "framework", "biomarker_axis",
        "biomarker_state", "stage", "clinical_function", "conditions",
    )
    return {field: getattr(rule, field, None) for field in fields}


def update_draft_rule(db, admin_id: int, rule_id: int, patch: RulePatch, reason: str):
    rule = db.query(StandardRule).get(rule_id)
    if rule is None:
        raise ValueError("规则不存在")
    if getattr(getattr(rule, "version", None), "status", None) not in {"draft", "review"}:
        raise ImmutableVersionError("已批准或已退役版本不可编辑")
    before = _rule_snapshot(rule)
    for field, value in patch.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    after = _rule_snapshot(rule)
    db.add(
        StandardChangeLog(
            version_id=rule.version_id,
            entity_type="standard_rule",
            entity_id=rule.id,
            action="edit",
            before_json=before,
            after_json=after,
            reason=reason.strip(),
            actor_id=admin_id,
        )
    )
    db.commit()
    db.refresh(rule)
    return rule


def transition_version(db, admin_id: int, version_id: int, target_status: str):
    version = db.query(ReferenceStandardVersion).get(version_id)
    if version is None:
        raise ValueError("标准版本不存在")
    allowed = {"draft": {"review"}, "review": {"approved"}, "approved": {"retired"}, "retired": set()}
    if target_status not in allowed.get(version.status, set()):
        raise ValueError(f"不允许从 {version.status} 转换到 {target_status}")
    if target_status == "approved":
        report = validate_version_rules(list(version.rules or []))
        if not report.can_publish:
            raise ValueError("标准版本存在阻止发布的校验错误")
    version.status = target_status
    if target_status == "approved":
        version.approved_by = admin_id
        version.approved_at = datetime.now(timezone.utc)
        version.effective_from = version.approved_at
    if target_status == "retired":
        version.retired_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(version)
    return version
