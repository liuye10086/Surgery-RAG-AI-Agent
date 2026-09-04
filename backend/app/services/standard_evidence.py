"""Typed applicability evaluation and per-indicator standard context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Sequence

from app.services.longitudinal_features import sort_visits


NON_CLINICAL_APPLICABILITY_KEYS = frozenset(
    {
        "source_language",
        "approximate_boundary_policy",
        "_manifest_entry_id",
        "_manifest_sha256",
        "_manifest_reviewed_at",
    }
)


@dataclass(frozen=True)
class PresentNode:
    field: str


@dataclass(frozen=True)
class EqualsNode:
    field: str
    value: Any


@dataclass(frozen=True)
class InNode:
    field: str
    values: tuple[Any, ...]


@dataclass(frozen=True)
class RangeNode:
    field: str
    minimum: float | None = None
    maximum: float | None = None
    minimum_inclusive: bool = True
    maximum_inclusive: bool = True


@dataclass(frozen=True)
class AllNode:
    children: tuple["ConditionNode", ...] = ()


@dataclass(frozen=True)
class AnyNode:
    children: tuple["ConditionNode", ...] = ()


@dataclass(frozen=True)
class NotNode:
    child: "ConditionNode"


ConditionNode = PresentNode | EqualsNode | InNode | RangeNode | AllNode | AnyNode | NotNode


@dataclass(frozen=True)
class ConditionDecision:
    status: str
    satisfied: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    mismatched: tuple[str, ...] = ()


@dataclass(frozen=True)
class IndicatorContext:
    indicator: str
    canonical_code: str
    unit: str | None
    observed_at: date
    age: int | None
    sex: str | None
    baseline_stage: str | None
    disease_code: str | None
    source_type: str | None = None
    facility_name: str | None = None
    device_name: str | None = None
    assay_platform: str | None = None
    method: str | None = None
    specimen: str | None = None
    scale_version: str | None = None
    assessment_language: str | None = None
    education_years: int | None = None
    education_adjusted: bool | None = None
    imaging_type: str | None = None
    measurement_context_changed: bool = False


def _normalise(value: Any) -> str:
    return str(value).strip().casefold()


def _context_value(context: Mapping[str, Any], field: str) -> Any:
    aliases = {
        "platform": ("assay_platform", "platform", "modality"),
        "method": ("method", "assay", "analysis_method"),
        "sample": ("specimen", "sample", "sample_type"),
        "scale_version": ("scale_version", "assessment_version"),
        "education": ("education_years", "education", "education_level"),
        "language": ("assessment_language", "language"),
    }
    for key in aliases.get(field, (field,)):
        value = context.get(key)
        if value not in (None, ""):
            return value
    return None


def _leaf_decision(node: PresentNode | EqualsNode | InNode | RangeNode, context: Mapping[str, Any]) -> ConditionDecision:
    actual = _context_value(context, node.field)
    if actual is None:
        return ConditionDecision("missing", missing=(node.field,))
    if isinstance(node, PresentNode):
        return ConditionDecision("matched", satisfied=(node.field,))
    if isinstance(node, EqualsNode):
        matched = _normalise(actual) == _normalise(node.value)
    elif isinstance(node, InNode):
        matched = _normalise(actual) in {_normalise(item) for item in node.values}
    else:
        try:
            number = float(actual)
        except (TypeError, ValueError):
            matched = False
        else:
            matched = True
            if node.minimum is not None:
                matched &= number >= node.minimum if node.minimum_inclusive else number > node.minimum
            if node.maximum is not None:
                matched &= number <= node.maximum if node.maximum_inclusive else number < node.maximum
    if matched:
        return ConditionDecision("matched", satisfied=(node.field,))
    return ConditionDecision("mismatched", mismatched=(node.field,))


def evaluate_condition(node: ConditionNode, context: Mapping[str, Any]) -> ConditionDecision:
    if isinstance(node, (PresentNode, EqualsNode, InNode, RangeNode)):
        return _leaf_decision(node, context)
    if isinstance(node, AllNode):
        decisions = [evaluate_condition(child, context) for child in node.children]
        missing = tuple(item for decision in decisions for item in decision.missing)
        mismatched = tuple(item for decision in decisions for item in decision.mismatched)
        satisfied = tuple(item for decision in decisions for item in decision.satisfied)
        status = "mismatched" if mismatched else "missing" if missing else "matched"
        return ConditionDecision(status, satisfied, missing, mismatched)
    if isinstance(node, AnyNode):
        decisions = [evaluate_condition(child, context) for child in node.children]
        if any(decision.status == "matched" for decision in decisions):
            return ConditionDecision("matched", satisfied=tuple(item for decision in decisions if decision.status == "matched" for item in decision.satisfied))
        missing = tuple(item for decision in decisions for item in decision.missing)
        mismatched = tuple(item for decision in decisions for item in decision.mismatched)
        return ConditionDecision("missing" if missing and not mismatched else "mismatched", missing=missing, mismatched=mismatched)
    child = evaluate_condition(node.child, context)
    if child.status == "missing":
        return child
    return ConditionDecision("matched" if child.status == "mismatched" else "mismatched", satisfied=child.mismatched, mismatched=child.satisfied)


def _adapt_node(field: str, expected: Any) -> ConditionNode:
    if expected == "required":
        return PresentNode(field)
    if isinstance(expected, list):
        return InNode(field, tuple(expected))
    if isinstance(expected, dict) and ({"min", "max", "minimum", "maximum"} & set(expected)):
        return RangeNode(
            field,
            expected.get("min", expected.get("minimum")),
            expected.get("max", expected.get("maximum")),
            expected.get("min_inclusive", True),
            expected.get("max_inclusive", True),
        )
    return EqualsNode(field, expected)


def adapt_v1_applicability(value: Mapping[str, Any] | None) -> AllNode:
    children: list[ConditionNode] = []
    for field, expected in sorted((value or {}).items()):
        if field in NON_CLINICAL_APPLICABILITY_KEYS:
            continue
        if field == "all":
            for item in expected:
                if isinstance(item, Mapping):
                    children.extend(adapt_v1_applicability(item).children)
            continue
        if field == "any":
            children.append(AnyNode(tuple(adapt_v1_applicability(item) for item in expected if isinstance(item, Mapping))))
            continue
        children.append(_adapt_node(field, expected))
    return AllNode(tuple(children))


def _context_from_visit(case: Mapping[str, Any], indicator: Mapping[str, Any], visit: Mapping[str, Any]) -> IndicatorContext:
    raw_name = str(indicator.get("name") or "").strip()
    context = visit.get("visit_context") if isinstance(visit.get("visit_context"), Mapping) else {}
    return IndicatorContext(
        indicator=raw_name,
        canonical_code=raw_name.casefold(),
        unit=str(indicator.get("unit") or "").strip() or None,
        observed_at=date.fromisoformat(str(visit["visit_date"])),
        age=case.get("age"),
        sex=case.get("sex"),
        baseline_stage=case.get("baseline_stage"),
        disease_code=case.get("disease_code"),
        **{key: context.get(key) for key in (
            "source_type", "facility_name", "device_name", "assay_platform", "method",
            "specimen", "scale_version", "assessment_language", "education_years",
            "education_adjusted", "imaging_type",
        )},
    )


def build_indicator_contexts(case: Mapping[str, Any], visits: Sequence[Mapping[str, Any]]) -> dict[str, IndicatorContext]:
    contexts: dict[str, IndicatorContext] = {}
    for visit in sort_visits([dict(item) for item in visits]):
        for indicator in visit.get("indicators") or []:
            if not isinstance(indicator, Mapping) or not str(indicator.get("name") or "").strip():
                continue
            context = _context_from_visit(case, indicator, visit)
            contexts[context.canonical_code] = context
    return contexts


__all__ = [
    "AllNode", "AnyNode", "ConditionDecision", "ConditionNode", "EqualsNode",
    "IndicatorContext", "InNode", "NotNode", "PresentNode", "RangeNode",
    "adapt_v1_applicability", "build_indicator_contexts", "evaluate_condition",
]
