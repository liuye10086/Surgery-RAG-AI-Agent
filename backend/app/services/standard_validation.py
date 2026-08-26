"""Validation rules for parsed and manually reviewed standard rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas.standard import ValidationFinding, ValidationReport
from app.db.models import ReferenceStandardVersion, StandardRuleCondition


AD_DIRECTIONS = {
    "mmse": "ordinal_low",
    "moca": "ordinal_low",
    "cdr": "ordinal_high",
    "nfl": "high",
    "p-tau217": "high",
    "aβ42/aβ40": "low",
}
AD_CONTEXT_REQUIRED = {
    "mmse": {"education", "language", "scale_version"},
    "moca": {"education", "language", "scale_version"},
    "nfl": {"sample", "platform", "method"},
    "p-tau217": {"sample", "platform", "method"},
    "aβ42/aβ40": {"sample", "platform", "method"},
}


@dataclass(frozen=True)
class RuleValidation:
    errors: list[ValidationFinding] = field(default_factory=list)
    warnings: list[ValidationFinding] = field(default_factory=list)
    infos: list[ValidationFinding] = field(default_factory=list)
    actionability: str = "evidence-only"


def _finding(level: str, code: str, message: str) -> ValidationFinding:
    return ValidationFinding(level=level, code=code, message=message)


def validate_rule(rule: Any, *, disease_key: str | None = None) -> RuleValidation:
    errors: list[ValidationFinding] = []
    warnings: list[ValidationFinding] = []
    infos: list[ValidationFinding] = []
    actionability = getattr(rule, "machine_actionability", "evidence-only")
    rule_type = getattr(rule, "rule_type", "")
    numeric = rule_type in {"numeric_range", "threshold"}
    if numeric and getattr(rule, "lower", None) is None and getattr(rule, "upper", None) is None:
        errors.append(_finding("error", "missing_numeric_boundary", "数值规则必须至少提供一个边界"))
    if numeric and not getattr(rule, "unit", None):
        actionability = "evidence-only"
        warnings.append(_finding("warning", "missing_unit", "缺少单位，不能进入兼容投影"))
    applicability = getattr(rule, "applicability", {}) or {}
    indicator = getattr(rule, "indicator", None)
    canonical_key = getattr(indicator, "canonical_key", None)
    if disease_key == "ad" and canonical_key in AD_DIRECTIONS:
        expected = AD_DIRECTIONS[canonical_key]
        if getattr(indicator, "abnormal_direction", None) != expected:
            errors.append(_finding("error", "invalid_ad_direction", f"{canonical_key} 的异常方向必须为 {expected}"))
        required = AD_CONTEXT_REQUIRED.get(canonical_key, set()) if numeric else set()
        missing = sorted(key for key in required if not applicability.get(key))
        if missing and actionability == "calculable":
            errors.append(_finding("error", "ad_biomarker_applicability_missing", f"缺少 AD 适用条件：{', '.join(missing)}"))
    source_segment = getattr(rule, "source_segment", None)
    if actionability == "calculable" and source_segment is not None:
        raw_text = str(getattr(source_segment, "raw_text", ""))
        if any(token in raw_text for token in ("约", "常见为", "常作正常参考", "大约", "通常为")):
            errors.append(_finding("error", "approximate_calculable_rule", "近似医学文本不能直接作为 calculable 规则"))
    if rule_type == "threshold" and not applicability:
        actionability = "evidence-only"
        warnings.append(_finding("warning", "missing_applicability", "研究或平台阈值缺少适用条件"))
    if getattr(rule, "clinical_dimension", None) == "steatosis":
        dimensions = (getattr(rule, "conditions", {}) or {}).get("child_dimensions", [])
        if "fibrosis_risk" in dimensions:
            errors.append(_finding("error", "mixed_clinical_dimensions", "脂肪变性规则不能混用纤维化风险维度"))
    if getattr(rule, "framework", None) is None and (getattr(rule, "biomarker_axis", None) or getattr(rule, "stage", None)):
        warnings.append(_finding("warning", "missing_diagnostic_framework", "AD 阶段或 A/T/N 规则必须声明诊断框架"))
    if rule_type in {"qualitative_direction", "classification", "exclusion", "composite"}:
        if actionability == "calculable" and not getattr(rule, "conditions", None):
            actionability = "evidence-only"
        infos.append(_finding("info", "non_numeric_rule", "非普通数值规则默认作为证据或组合规则处理"))
    return RuleValidation(errors=errors, warnings=warnings, infos=infos, actionability=actionability)


def _validate_condition(node: dict[str, Any], seen: set[int], errors: list[ValidationFinding], path: str = "root") -> None:
    marker = id(node)
    if marker in seen:
        errors.append(_finding("error", "condition_cycle", f"条件树 {path} 存在循环引用"))
        return
    seen.add(marker)
    node_type = node.get("node_type")
    children = node.get("children") or []
    if node_type not in {"all", "any", "not", "at_least_n", "at_most_n", "leaf"}:
        errors.append(_finding("error", "invalid_condition_type", f"未知条件节点类型：{node_type}"))
    if node_type == "not" and len(children) != 1:
        errors.append(_finding("error", "invalid_not_arity", "not 条件必须只有一个子条件"))
    if node_type in {"at_least_n", "at_most_n"}:
        n = (node.get("payload") or {}).get("n")
        if not isinstance(n, int) or n < 1 or n > len(children):
            errors.append(_finding("error", "invalid_cardinality", f"{node_type} 的 n 必须在 1 到子条件数量之间"))
    for index, child in enumerate(children):
        _validate_condition(child, seen, errors, f"{path}.{index}")
    seen.remove(marker)


def validate_condition_payload(payload: dict[str, Any]) -> ValidationReport:
    errors: list[ValidationFinding] = []
    _validate_condition(payload, set(), errors)
    return ValidationReport(errors=errors)


def build_condition_tree(payload: dict[str, Any], *, rule_id: int | None = None, parent_id: int | None = None, position: int = 0):
    node = StandardRuleCondition(
        rule_id=rule_id,
        parent_id=parent_id,
        node_type=payload["node_type"],
        position=position,
        payload=payload.get("payload") or {},
    )
    node.children = [
        build_condition_tree(child, rule_id=rule_id, parent_id=None, position=index)
        for index, child in enumerate(payload.get("children") or [])
    ]
    return node


def validate_version(db: Any, version_id: int) -> ValidationReport:
    version = db.query(ReferenceStandardVersion).filter(ReferenceStandardVersion.id == version_id).first()
    if version is None:
        raise ValueError("标准版本不存在")
    return validate_version_rules(list(version.rules or []))


def is_projection_eligible(rule: Any) -> bool:
    indicator = getattr(rule, "indicator", None)
    return (
        getattr(rule, "machine_actionability", None) == "calculable"
        and getattr(rule, "rule_type", None) in {"numeric_range", "threshold"}
        and (getattr(rule, "lower", None) is not None or getattr(rule, "upper", None) is not None)
        and bool(getattr(rule, "unit", None))
        and bool(getattr(indicator, "allows_numeric_comparison", False))
    )


def validate_version_rules(
    rules: list[Any],
    *,
    disease_key: str | None = None,
    require_calculable: bool = True,
) -> ValidationReport:
    errors: list[ValidationFinding] = []
    warnings: list[ValidationFinding] = []
    infos: list[ValidationFinding] = []
    projection_count = 0
    calculable_rule_count = 0
    blocked_rule_count = 0
    if not rules:
        errors.append(_finding("error", "formal_rules_missing", "标准版本没有正式规则"))
    for rule in rules:
        result = validate_rule(rule, disease_key=disease_key)
        errors.extend(result.errors)
        warnings.extend(result.warnings)
        infos.extend(result.infos)
        if result.actionability == "calculable" and not result.errors:
            calculable_rule_count += 1
        if getattr(rule, "machine_actionability", None) == "blocked":
            blocked_rule_count += 1
        if is_projection_eligible(rule) and not result.errors:
            projection_count += 1
    if require_calculable and calculable_rule_count == 0:
        errors.append(_finding("error", "calculable_rules_missing", "标准版本没有可计算的正式规则"))
    return ValidationReport(
        errors=errors,
        warnings=warnings,
        infos=infos,
        projection_count=projection_count,
        calculable_rule_count=calculable_rule_count,
        blocked_rule_count=blocked_rule_count,
    )
