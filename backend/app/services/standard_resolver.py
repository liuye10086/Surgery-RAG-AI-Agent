"""Resolve rules from the currently approved standard version.

The resolver is deliberately read-only.  It never averages competing rules and
only selects a rule when its applicability predicates match the supplied case
context.  Rules that cannot be safely calculated are returned as evidence.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any


NON_CLINICAL_APPLICABILITY_KEYS = frozenset({
    "source_language",
    "approximate_boundary_policy",
    "_manifest_entry_id",
    "_manifest_sha256",
    "_manifest_reviewed_at",
})


@dataclass
class ResolvedStandardRules:
    version_id: int | None = None
    standard_id: int | None = None
    calculable_rules: list[Any] = field(default_factory=list)
    evidence_rules: list[Any] = field(default_factory=list)
    unmatched_rules: list[Any] = field(default_factory=list)
    conflicting_rules: list[Any] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def applicability_hash(applicability: dict[str, Any] | None) -> str:
    payload = json.dumps(applicability or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalise(value: Any) -> str:
    return str(value).strip().casefold()


def _indicator_matches(rule: Any, requested: str) -> bool:
    indicator = getattr(rule, "indicator", None)
    names = [getattr(indicator, "canonical_key", ""), *(getattr(indicator, "aliases", None) or [])]
    return _normalise(requested) in {_normalise(name) for name in names if name}


def _context_value(context: dict[str, Any], key: str) -> Any:
    aliases = {
        "platform": ("platform", "assay_platform", "modality"),
        "method": ("method", "assay", "analysis_method"),
        "sample": ("sample", "specimen", "sample_type"),
        "cohort": ("cohort", "study", "dataset"),
        "scale_version": ("scale_version", "assessment_version"),
        "education": ("education", "education_level"),
        "language": ("language", "assessment_language"),
        "tracer": ("tracer",),
        "device": ("device",),
        "age": ("age",),
        "framework": ("framework",),
    }
    for candidate in aliases.get(key, (key,)):
        if candidate in context and context[candidate] not in (None, ""):
            return context[candidate]
    return None


def _applicability_matches(rule: Any, context: dict[str, Any]) -> tuple[bool, list[str]]:
    applicability = getattr(rule, "applicability", None) or {}
    missing: list[str] = []
    for key, expected in applicability.items():
        if key in NON_CLINICAL_APPLICABILITY_KEYS:
            continue
        actual = _context_value(context, key)
        if actual is None:
            missing.append(str(key))
            continue
        expected_values = expected if isinstance(expected, list) else [expected]
        if _normalise(actual) not in {_normalise(item) for item in expected_values}:
            return False, []
    rule_sex = getattr(rule, "sex", None)
    context_sex = context.get("sex")
    if rule_sex and context_sex and _normalise(rule_sex) != _normalise(context_sex):
        return False, []
    if rule_sex and not context_sex:
        missing.append("sex")
    return not missing, missing


def _as_evidence(rule: Any, reason: str) -> Any:
    result = copy.copy(rule)
    result.machine_actionability = "evidence-only"
    result.resolution_warning = reason
    return result


def _load_current_standard(db: Any, disease_id: int) -> Any | None:
    from app.db.models import ReferenceStandard

    query = db.query(ReferenceStandard).filter(ReferenceStandard.disease_id == disease_id)
    return query.first()


def resolve_standard_rules(db: Any, disease_id: int, indicator_names: list[str], context: dict[str, Any] | None = None) -> ResolvedStandardRules:
    context = dict(context or {})
    standard = _load_current_standard(db, disease_id)
    version = getattr(standard, "current_version", None) if standard else None
    result = ResolvedStandardRules(version_id=getattr(version, "id", None), standard_id=getattr(standard, "id", None))
    if version is not None and getattr(version, "standard_id", getattr(standard, "id", None)) != getattr(standard, "id", None):
        result.version_id = None
        result.warnings.append("当前标准版本归属异常")
        return result
    if version is None or getattr(version, "status", None) != "approved":
        result.warnings.append("当前疾病没有已批准的标准版本")
        return result

    requested = [name for name in indicator_names if str(name).strip()]
    matched_calculable_by_conflict: dict[str, list[Any]] = {}
    for rule in getattr(version, "rules", None) or []:
        if not any(_indicator_matches(rule, name) for name in requested):
            continue
        matched, missing = _applicability_matches(rule, context)
        if not matched:
            if missing:
                result.evidence_rules.append(_as_evidence(rule, f"缺少适用条件：{', '.join(missing)}"))
                result.warnings.append(f"规则 {getattr(rule, 'id', '?')} 缺少适用条件：{', '.join(missing)}")
            else:
                result.unmatched_rules.append(rule)
            continue
        resolved = copy.copy(rule)
        resolved.standard_version_id = version.id
        resolved.standard_rule_id = getattr(rule, "id", None)
        resolved.applicability_hash = applicability_hash(getattr(rule, "applicability", None))
        if getattr(rule, "machine_actionability", "evidence-only") == "calculable":
            conflict_group = getattr(rule, "conflict_group", None)
            if conflict_group:
                matched_calculable_by_conflict.setdefault(conflict_group, []).append(resolved)
            else:
                result.calculable_rules.append(resolved)
        else:
            result.evidence_rules.append(resolved)
    for conflict_group, matches in matched_calculable_by_conflict.items():
        if len(matches) > 1:
            result.conflicting_rules.extend(matches)
            ids = ", ".join(str(getattr(item, "standard_rule_id", "?")) for item in sorted(matches, key=lambda item: getattr(item, "standard_rule_id", 0)))
            result.warnings.append(f"规则冲突（{conflict_group}）：未自动选择规则 {ids}")
        else:
            result.calculable_rules.extend(matches)
    return result


__all__ = ["ResolvedStandardRules", "applicability_hash", "resolve_standard_rules"]
