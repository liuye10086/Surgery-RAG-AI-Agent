"""Version state transitions and auditable draft rule edits."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from app.db.models import (
    ReferenceRange,
    ReferenceStandard,
    ReferenceStandardVersion,
    StandardParseCandidate,
    StandardChangeLog,
    StandardRule,
)
from app.schemas.standard import RulePatch
from app.services.standard_validation import (
    is_projection_eligible,
    normalize_disease_key,
    validate_version_rules,
)
import hashlib
from pathlib import Path
import json


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
    rule_probe = db.query(StandardRule).get(rule_id)
    if rule_probe is None:
        raise ValueError("规则不存在")
    version = (
        db.query(ReferenceStandardVersion)
        .filter(ReferenceStandardVersion.id == rule_probe.version_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if getattr(version, "status", None) not in {"draft", "review"}:
        raise ImmutableVersionError("已批准或已退役版本不可编辑")
    rule = (
        db.query(StandardRule)
        .filter(
            StandardRule.id == rule_id,
            StandardRule.version_id == rule_probe.version_id,
        )
        .populate_existing()
        .first()
    )
    if rule is None:
        raise ValueError("规则不存在")
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
    version = (
        db.query(ReferenceStandardVersion)
        .filter(ReferenceStandardVersion.id == version_id)
        .with_for_update()
        .first()
    )
    if version is None:
        raise ValueError("标准版本不存在")
    allowed = {"draft": {"review"}, "review": {"approved"}, "approved": {"retired"}, "retired": set()}
    if target_status not in allowed.get(version.status, set()):
        raise ValueError(f"不允许从 {version.status} 转换到 {target_status}")
    if target_status == "approved":
        disease_key = getattr(
            getattr(getattr(version, "standard", None), "disease", None),
            "name",
            None,
        )
        report = _validation_for_publish(
            list(version.rules or []),
            disease_key=disease_key,
        )
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


def _projection_hash(rule: Any) -> str:
    payload = json.dumps(getattr(rule, "applicability", {}) or {}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _projection_from_rule(version: Any, rule: Any) -> Any:
    return ReferenceRange(
        standard_id=version.standard_id,
        standard_version_id=version.id,
        standard_rule_id=rule.id,
        indicator_name=getattr(getattr(rule, "indicator", None), "name_en", None) or getattr(getattr(rule, "indicator", None), "canonical_key", ""),
        name_cn=getattr(getattr(rule, "indicator", None), "name_cn", None),
        unit=rule.unit,
        lower=rule.lower,
        upper=rule.upper,
        lower_inclusive=rule.lower_inclusive,
        upper_inclusive=rule.upper_inclusive,
        sex=rule.sex,
        category=rule.category,
        applicability_hash=_projection_hash(rule),
        is_current_projection=True,
    )


def _flush_if_available(db: Any) -> None:
    if hasattr(db, "flush"):
        db.flush()


def materialize_candidate(db: Any, *, candidate_id: int, admin_id: int, reason: str) -> Any:
    """Materialize one accepted candidate and its audit event in one transaction."""
    candidate_probe = db.query(StandardParseCandidate).get(candidate_id)
    if candidate_probe is None:
        raise ValueError("解析候选不存在")
    version = (
        db.query(ReferenceStandardVersion)
        .filter(ReferenceStandardVersion.id == candidate_probe.version_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if version is None:
        raise ValueError("标准版本不存在")
    if version.status not in {"draft", "review"}:
        raise ValueError("已批准或已退役版本不可物化候选")
    candidate = (
        db.query(StandardParseCandidate)
        .filter(StandardParseCandidate.id == candidate_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if candidate is None:
        raise ValueError("解析候选不存在")
    if candidate.status != "accepted":
        raise ValueError("只有 accepted 候选可以转为规则")

    payload = getattr(candidate, "candidate_json", {}) or {}
    numeric = payload.get("numeric") or {}
    from app.db.models import StandardIndicator

    indicator = None
    indicator_name = payload.get("indicator_name")
    if indicator_name:
        indicator = db.query(StandardIndicator).filter(
            StandardIndicator.canonical_key.ilike(str(indicator_name))
        ).first()
    rule = StandardRule(
        version_id=candidate.version_id,
        indicator_id=getattr(indicator, "id", None),
        source_segment_id=candidate.segment_id,
        rule_type=payload.get("rule_type") or "qualitative_direction",
        lower=numeric.get("lower"),
        upper=numeric.get("upper"),
        lower_inclusive=numeric.get("lower_inclusive", True),
        upper_inclusive=numeric.get("upper_inclusive", True),
        unit=numeric.get("unit") or payload.get("unit"),
        sex=payload.get("sex"),
        category=payload.get("category"),
        applicability=payload.get("applicability") or {},
        target_state_type=payload.get("target_state_type") or "evidence",
        target_state_value=payload.get("target_state_value"),
        evidence_type=payload.get("evidence_type"),
        machine_actionability=payload.get("machine_actionability") or "evidence-only",
        interpretation=payload.get("interpretation"),
        conditions=payload.get("conditions") or {},
    )
    db.add(rule)
    _flush_if_available(db)
    db.add(StandardChangeLog(
        version_id=candidate.version_id,
        entity_type="standard_rule",
        entity_id=getattr(rule, "id", None),
        action="materialize_candidate",
        before_json={},
        after_json={"candidate_id": candidate.id, "rule_type": rule.rule_type},
        reason=reason.strip(),
        actor_id=admin_id,
    ))
    candidate.status = "materialized"
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    if hasattr(db, "refresh"):
        db.refresh(rule)
    return rule


def _validation_for_publish(rules: list[Any], *, disease_key: str | None = None) -> Any:
    disease_key = normalize_disease_key(disease_key)
    try:
        return validate_version_rules(
            rules,
            disease_key=disease_key,
            require_calculable=disease_key != "ad",
        )
    except TypeError:
        return validate_version_rules(rules)


def publish_review_version(db: Any, *, version_id: int, admin_id: int, commit: bool = True) -> Any:
    """Approve a review version, replace current projections, and update the pointer atomically."""
    version_probe = db.query(ReferenceStandardVersion).filter(
        ReferenceStandardVersion.id == version_id
    ).first()
    if version_probe is None:
        raise ValueError("标准版本不存在")
    standard = (
        db.query(ReferenceStandard)
        .filter(ReferenceStandard.id == version_probe.standard_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    version = (
        db.query(ReferenceStandardVersion)
        .filter(ReferenceStandardVersion.id == version_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if standard is None or version is None:
        raise ValueError("标准版本不存在")
    if version.standard_id != standard.id:
        raise ValueError("标准版本归属异常")
    if version.status != "review":
        raise ValueError("只有 review 版本可以批准")
    disease = getattr(getattr(standard, "disease", None), "name", None)
    report = _validation_for_publish(list(version.rules or []), disease_key=disease)
    if not report.can_publish:
        raise ValueError("标准版本存在阻止发布的校验错误")

    projections: list[Any] = []
    try:
        previous = getattr(standard, "current_version", None)
        if previous is not None and previous.id != version.id:
            previous.status = "retired"
            previous.retired_at = datetime.now(timezone.utc)
            old_query = db.query(ReferenceRange).filter(
                ReferenceRange.standard_version_id == previous.id
            )
            old_query.update({"is_current_projection": False}, synchronize_session=False)
        version.status = "approved"
        version.approved_by = admin_id
        version.approved_at = datetime.now(timezone.utc)
        version.effective_from = version.approved_at
        for rule in version.rules or []:
            if not is_projection_eligible(rule):
                continue
            projection = _projection_from_rule(version, rule)
            db.add(projection)
            projections.append(projection)
        standard.current_version = version
        standard.current_version_id = version.id
        db.add(StandardChangeLog(
            version_id=version.id,
            entity_type="reference_standard_version",
            entity_id=version.id,
            action="publish",
            before_json={"status": "review", "current_version_id": getattr(standard, "current_version_id", None)},
            after_json={"status": "approved", "current_version_id": version.id, "projection_count": len(projections)},
            reason="发布审核通过标准版本",
            actor_id=admin_id,
        ))
        _flush_if_available(db)
        if commit:
            db.commit()
    except Exception:
        if commit:
            db.rollback()
        raise
    if commit and hasattr(db, "refresh"):
        db.refresh(version)
    return SimpleNamespace(version=version, projections=projections)


def retire_current_version(db: Any, *, version_id: int, admin_id: int) -> Any:
    standard = (
        db.query(ReferenceStandard)
        .filter(ReferenceStandard.current_version_id == version_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    version = (
        db.query(ReferenceStandardVersion)
        .filter(ReferenceStandardVersion.id == version_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if standard is None or version is None:
        raise ValueError("只有当前 approved 版本可以退役")
    if version.standard_id != standard.id or version.status != "approved":
        raise ValueError("只有当前 approved 版本可以退役")
    try:
        version.status = "retired"
        version.retired_at = datetime.now(timezone.utc)
        db.query(ReferenceRange).filter(
            ReferenceRange.standard_version_id == version.id
        ).update({"is_current_projection": False}, synchronize_session=False)
        standard.current_version = None
        standard.current_version_id = None
        db.add(StandardChangeLog(
            version_id=version.id,
            entity_type="reference_standard_version",
            entity_id=version.id,
            action="retire",
            before_json={"status": "approved", "current_version_id": version.id},
            after_json={"status": "retired", "current_version_id": None},
            reason="退役当前标准版本",
            actor_id=admin_id,
        ))
        _flush_if_available(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    if hasattr(db, "refresh"):
        db.refresh(version)
    return version


def publish_approved_version(db, admin_id: int, version_id: int):
    version_probe = (
        db.query(ReferenceStandardVersion)
        .filter(ReferenceStandardVersion.id == version_id)
        .first()
    )
    if version_probe is None:
        raise ValueError("标准版本不存在")
    standard = (
        db.query(ReferenceStandard)
        .filter(ReferenceStandard.id == version_probe.standard_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    version = (
        db.query(ReferenceStandardVersion)
        .filter(ReferenceStandardVersion.id == version_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if standard is None or version is None:
        raise ValueError("标准版本不存在")
    if version.status != "review":
        raise ValueError("只有 review 版本可以批准")
    disease_key = getattr(getattr(standard, "disease", None), "name", None)
    report = _validation_for_publish(
        list(version.rules or []),
        disease_key=disease_key,
    )
    if not report.can_publish:
        raise ValueError("标准版本存在阻止发布的校验错误")
    try:
        previous = getattr(standard, "current_version", None)
        if previous is not None and previous.id != version.id:
            previous.status = "retired"
            previous.retired_at = datetime.now(timezone.utc)
            old_query = db.query(ReferenceRange).filter(ReferenceRange.standard_version_id == previous.id)
            if hasattr(old_query, "update"):
                old_query.update({"is_current_projection": False}, synchronize_session=False)
        version.status = "approved"
        version.approved_by = admin_id
        version.approved_at = datetime.now(timezone.utc)
        version.effective_from = version.approved_at
        projections = []
        for rule in version.rules or []:
            if validate_rule_actionability(rule) != "calculable":
                continue
            projection = _projection_from_rule(version, rule)
            db.add(projection)
            projections.append(projection)
        standard.current_version = version
        standard.current_version_id = version.id
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(version)
    return SimpleNamespace(version=version, projections=projections)


def validate_rule_actionability(rule: Any) -> str:
    from app.services.standard_validation import validate_rule
    return validate_rule(rule).actionability


def materialize_candidate_rule(db, candidate: Any, admin_id: int, reason: str):
    """Turn an accepted parse candidate into an editable StandardRule."""
    if getattr(candidate, "status", None) != "accepted":
        raise ValueError("只有 accepted 候选可以转为规则")
    payload = getattr(candidate, "candidate_json", {}) or {}
    numeric = payload.get("numeric") or {}
    from app.db.models import StandardChangeLog
    from app.db.models import StandardIndicator

    indicator_name = payload.get("indicator_name")
    indicator = None
    if indicator_name:
        indicator = db.query(StandardIndicator).filter(StandardIndicator.canonical_key.ilike(str(indicator_name))).first()

    rule = StandardRule(
        version_id=candidate.version_id,
        indicator_id=getattr(indicator, "id", None),
        source_segment_id=candidate.segment_id,
        rule_type=payload.get("rule_type") or "qualitative_direction",
        lower=numeric.get("lower"),
        upper=numeric.get("upper"),
        lower_inclusive=numeric.get("lower_inclusive", True),
        upper_inclusive=numeric.get("upper_inclusive", True),
        unit=numeric.get("unit") or payload.get("unit"),
        category=payload.get("category"),
        applicability=payload.get("applicability") or {},
        target_state_type=payload.get("target_state_type") or "evidence",
        target_state_value=payload.get("target_state_value"),
        evidence_type=payload.get("evidence_type"),
        machine_actionability=payload.get("machine_actionability") or "evidence-only",
        interpretation=payload.get("interpretation"),
        conditions=payload.get("conditions") or {},
    )
    db.add(rule)
    if hasattr(db, "flush"):
        db.flush()
    db.add(StandardChangeLog(
        version_id=candidate.version_id,
        entity_type="standard_rule",
        entity_id=rule.id,
        action="materialize_candidate",
        before_json={},
        after_json={"candidate_id": candidate.id, "rule_type": rule.rule_type},
        reason=reason.strip(),
        actor_id=admin_id,
    ))
    db.commit()
    db.refresh(rule)
    return rule


def seed_standard_draft(db, disease_id: int, standard_document_id: int, version_label: str, *, admin_id: int | None = None, parser_version: str = "v1"):
    """Create or reuse an unapproved draft for a DOCX document."""
    from app.db.models import Disease, ReferenceStandard, ReferenceStandardVersion, StandardDocument

    disease = (
        db.query(Disease)
        .filter(Disease.id == disease_id)
        .with_for_update()
        .first()
    )
    if disease is None:
        raise ValueError("疾病不存在")
    document = (
        db.query(StandardDocument)
        .filter(StandardDocument.id == standard_document_id)
        .with_for_update()
        .first()
    )
    if document is None:
        raise ValueError("标准文档不存在")
    if (document.file_type or "").lower().lstrip(".") != "docx":
        raise ValueError("标准源文件只支持 DOCX")
    path = Path(document.file_path or "")
    if not path.is_file():
        raise ValueError("标准文件不存在")
    if document.version is not None:
        associated_standard = getattr(document.version, "standard", None)
        if getattr(associated_standard, "disease_id", None) == disease_id:
            return document.version
        raise ValueError("标准文档已关联其他版本")
    standard = db.query(ReferenceStandard).filter(ReferenceStandard.disease_id == disease_id).first()
    if standard is None:
        standard = ReferenceStandard(disease_id=disease_id, name=f"{disease.name}标准")
        db.add(standard)
        db.flush()
    version = ReferenceStandardVersion(
        standard_id=standard.id,
        standard_document_id=document.id,
        version_label=version_label,
        content_hash=document.content_hash,
        parser_version=parser_version,
        created_by=admin_id,
        status="draft",
        supersedes_version_id=getattr(standard, "current_version_id", None),
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version
