"""Transaction-neutral import planning for owner-approved manifests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.db.models import (
    ReferenceStandardVersion,
    StandardChangeLog,
    StandardIndicator,
    StandardRule,
)
from app.services.standard_validation import build_condition_tree


@dataclass(frozen=True)
class ManifestImportPlan:
    indicator_keys: list[str] = field(default_factory=list)
    rule_entry_ids: list[str] = field(default_factory=list)
    skipped_entry_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ManifestImportResult:
    created_rule_entry_ids: list[str] = field(default_factory=list)
    existing_rule_entry_ids: list[str] = field(default_factory=list)
    skipped_entry_ids: list[str] = field(default_factory=list)


def _approved_rule_entries(manifest):
    return [
        entry for entry in manifest.entries
        if entry.entry_kind == "rule" and entry.review_status == "approved"
    ]


def _require_approved(manifest) -> None:
    if manifest.review_state != "approved":
        raise ValueError("manifest 必须为 approved")
    if any(entry.review_status == "pending" for entry in manifest.entries):
        raise ValueError("approved manifest 不得包含 pending 条目")


def plan_manifest_import(db: Any, *, manifest, version_id: int) -> ManifestImportPlan:
    _require_approved(manifest)
    entries = _approved_rule_entries(manifest)
    return ManifestImportPlan(
        indicator_keys=sorted({entry.indicator.canonical_key for entry in entries}),
        rule_entry_ids=[entry.entry_id for entry in entries],
        skipped_entry_ids=[entry.entry_id for entry in manifest.entries if entry not in entries],
    )


def import_manifest_rules(db: Any, *, manifest, version_id: int, admin_id: int) -> ManifestImportResult:
    _require_approved(manifest)
    version = db.query(ReferenceStandardVersion).filter(
        ReferenceStandardVersion.id == version_id
    ).with_for_update().first()
    if version is None:
        raise ValueError("标准版本不存在")
    if version.status not in {"draft", "review"}:
        raise ValueError("只有 draft 或 review 版本可以导入 manifest")

    existing_ids = set()
    for rule in getattr(version, "rules", None) or []:
        existing_ids.add((getattr(rule, "applicability", {}) or {}).get("_manifest_entry_id"))
    indicators_by_key: dict[str, Any] = {}
    for entry in _approved_rule_entries(manifest):
        key = entry.indicator.canonical_key
        existing = db.query(StandardIndicator).filter(StandardIndicator.canonical_key == key).first()
        if existing is None:
            existing = StandardIndicator(
                canonical_key=key,
                name_en=entry.indicator.name_en,
                name_cn=entry.indicator.name_cn,
                aliases=entry.indicator.aliases,
                domain=entry.indicator.domain,
                specimen_or_modality=entry.indicator.specimen_or_modality,
                data_type=entry.indicator.data_type,
                scale_or_method=entry.indicator.scale_or_method,
                default_unit=entry.indicator.default_unit,
                clinical_dimension=entry.indicator.clinical_dimension,
                allows_numeric_comparison=entry.indicator.allows_numeric_comparison,
                abnormal_direction=entry.indicator.abnormal_direction,
            )
            db.add(existing)
            if hasattr(db, "flush"):
                db.flush()
        elif getattr(existing, "abnormal_direction", None) != entry.indicator.abnormal_direction:
            raise ValueError(
                f"canonical indicator {key} abnormal_direction 与 approved manifest 冲突"
            )
        indicators_by_key[key] = existing

    created: list[str] = []
    existing_entry_ids: list[str] = []
    for entry in _approved_rule_entries(manifest):
        if entry.entry_id in existing_ids:
            existing_entry_ids.append(entry.entry_id)
            continue
        rule_data = entry.rule.model_dump()
        applicability = dict(rule_data.pop("applicability") or {})
        applicability["_manifest_entry_id"] = entry.entry_id
        applicability["_manifest_sha256"] = manifest.source_document_sha256
        applicability["_manifest_reviewed_at"] = manifest.reviewed_at.isoformat()
        conditions = rule_data.pop("conditions") or {}
        rule = StandardRule(
            version_id=version_id,
            indicator_id=getattr(indicators_by_key[entry.indicator.canonical_key], "id", None),
            source_segment_id=None,
            applicability=applicability,
            conditions=conditions,
            **{key: value for key, value in rule_data.items() if key != "actionability_reason"},
        )
        db.add(rule)
        if hasattr(db, "flush"):
            db.flush()
        if conditions and hasattr(rule, "condition_nodes"):
            rule.condition_nodes.append(build_condition_tree(conditions, rule_id=getattr(rule, "id", None)))
        db.add(StandardChangeLog(
            version_id=version_id,
            entity_type="standard_rule",
            entity_id=getattr(rule, "id", 0),
            action="manifest_import",
            before_json={},
            after_json={"manifest_entry_id": entry.entry_id},
            reason=entry.review_note or "manifest 审核导入",
            actor_id=admin_id,
        ))
        created.append(entry.entry_id)
    return ManifestImportResult(
        created_rule_entry_ids=created,
        existing_rule_entry_ids=existing_entry_ids,
        skipped_entry_ids=[entry.entry_id for entry in manifest.entries if entry not in _approved_rule_entries(manifest)],
    )
