"""Typed applicability evaluation and per-indicator standard context."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from app.core.config import settings
from app.services.longitudinal_features import sort_visits
from app.services.standard_manifest import load_standard_manifest
from app.services.standard_source_binding import (
    StandardSourceBindingError,
    approved_manifest_path,
    validate_rule_source_binding,
)
from app.schemas.longitudinal_evidence import (
    EvidenceConditionDecision,
    EvidenceDocument,
    EvidenceSourceLocator,
    EvidenceVersion,
    StandardEvidence,
    StandardRuleEvidence,
)


NON_CLINICAL_APPLICABILITY_KEYS = frozenset(
    {
        "source_language",
        "approximate_boundary_policy",
        "_manifest_entry_id",
        "_manifest_sha256",
        "_manifest_reviewed_at",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class StandardVersionToken:
    standard_id: int
    version_id: int
    document_id: int
    document_sha256: str
    version_sha256: str


class StandardEvidenceError(RuntimeError):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code


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
        "cohort": ("cohort", "study", "dataset"),
        "tracer": ("tracer",),
        "device": ("device_name", "device"),
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


def build_effective_applicability(rule: Any) -> AllNode:
    base = adapt_v1_applicability(getattr(rule, "applicability", None))
    sex = getattr(rule, "sex", None)
    if not sex:
        return base
    return AllNode(children=(*base.children, EqualsNode("sex", sex)))


def effective_applicability_hash(rule: Any) -> str:
    payload = {
        "applicability": getattr(rule, "applicability", None) or {},
        "sex": getattr(rule, "sex", None),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
    signatures: dict[str, set[tuple[Any, ...]]] = {}
    for visit in sort_visits([dict(item) for item in visits]):
        for indicator in visit.get("indicators") or []:
            if not isinstance(indicator, Mapping) or not str(indicator.get("name") or "").strip():
                continue
            context = _context_from_visit(case, indicator, visit)
            signature = (
                context.unit, context.assay_platform, context.method, context.specimen,
                context.scale_version, context.assessment_language,
                context.education_years, context.education_adjusted,
            )
            observed = signatures.setdefault(context.canonical_code, set())
            observed.add(signature)
            contexts[context.canonical_code] = replace(
                context, measurement_context_changed=len(observed) > 1,
            )
    return contexts


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _query_standard(db: Any, disease_id: int) -> Any:
    from app.db.models import ReferenceStandard, ReferenceStandardVersion, StandardRule
    from sqlalchemy.orm import selectinload

    query = db.query(ReferenceStandard).filter(ReferenceStandard.disease_id == disease_id)
    try:
        query = query.options(
            selectinload(ReferenceStandard.current_version).selectinload(ReferenceStandardVersion.standard_document),
            selectinload(ReferenceStandard.current_version).selectinload(ReferenceStandardVersion.rules).selectinload(StandardRule.indicator),
            selectinload(ReferenceStandard.current_version).selectinload(ReferenceStandardVersion.rules).selectinload(StandardRule.source_segment),
        )
    except (TypeError, AttributeError):
        pass
    return query.first()


def _set_local_timeout(db: Any, milliseconds: int) -> bool:
    execute = getattr(db, "execute", None)
    if not callable(execute):
        return False
    from sqlalchemy import text

    execute(text(f"SET LOCAL statement_timeout = {max(1, int(milliseconds))}"))
    return True


def _close_read_transaction(db: Any, timeout_was_set: bool) -> None:
    if timeout_was_set and callable(getattr(db, "rollback", None)):
        db.rollback()


def preflight_standard(db: Any, disease_id: int, disease_code: str) -> StandardVersionToken:
    should_close_transaction = callable(getattr(db, "rollback", None))
    try:
        _set_local_timeout(db, settings.STANDARD_EVIDENCE_QUERY_TIMEOUT_MS)
        standard = _query_standard(db, disease_id)
        if standard is None:
            raise StandardEvidenceError("standard_missing")
        if getattr(standard, "disease_id", disease_id) != disease_id:
            raise StandardEvidenceError("standard_integrity_failed")
        linked_disease = getattr(getattr(standard, "disease", None), "code", None)
        if linked_disease and str(linked_disease) != str(disease_code):
            raise StandardEvidenceError("standard_integrity_failed")
        version = getattr(standard, "current_version", None)
        if version is None or getattr(version, "status", None) != "approved":
            raise StandardEvidenceError("standard_not_approved")
        if getattr(version, "standard_id", getattr(standard, "id", None)) != getattr(standard, "id", None):
            raise StandardEvidenceError("standard_integrity_failed")
        document = getattr(version, "standard_document", None)
        if document is None:
            raise StandardEvidenceError("standard_integrity_failed")
        document_hash = str(getattr(document, "content_hash", ""))
        version_hash = str(getattr(version, "content_hash", ""))
        if not _SHA256_RE.fullmatch(document_hash) or not _SHA256_RE.fullmatch(version_hash):
            raise StandardEvidenceError("standard_integrity_failed")
        file_path = Path(str(getattr(document, "file_path", "")))
        if not file_path.is_file() or _sha256_file(file_path) != document_hash:
            raise StandardEvidenceError("standard_integrity_failed")
        if version_hash != document_hash:
            raise StandardEvidenceError("standard_integrity_failed")
        try:
            manifest = load_standard_manifest(approved_manifest_path(str(disease_code)))
            if (
                getattr(manifest, "review_state", None) != "approved"
                or getattr(manifest, "dataset", None) != str(disease_code)
                or getattr(manifest, "target_version_label", None) != getattr(version, "version_label", None)
                or getattr(manifest, "source_document_sha256", None) != document_hash
            ):
                raise StandardSourceBindingError("standard_integrity_failed")
            entries_by_id = {
                entry.entry_id: entry
                for entry in getattr(manifest, "entries", ())
                if getattr(entry, "entry_kind", None) == "rule"
                and getattr(entry, "review_status", None) == "approved"
            }
        except (OSError, UnicodeError, ValueError, StandardSourceBindingError) as exc:
            raise StandardEvidenceError("standard_integrity_failed") from exc
        for rule in getattr(version, "rules", None) or ():
            manifest_hash = (getattr(rule, "applicability", None) or {}).get("_manifest_sha256")
            if not _SHA256_RE.fullmatch(str(manifest_hash or "")) or str(manifest_hash) != document_hash:
                raise StandardEvidenceError("standard_integrity_failed")
            entry_id = (getattr(rule, "applicability", None) or {}).get("_manifest_entry_id")
            entry = entries_by_id.get(entry_id)
            try:
                validate_rule_source_binding(rule, version_id=version.id, manifest_entry=entry)
            except StandardSourceBindingError as exc:
                raise StandardEvidenceError("standard_integrity_failed") from exc
        return StandardVersionToken(
            standard_id=int(standard.id), version_id=int(version.id), document_id=int(document.id),
            document_sha256=document_hash, version_sha256=version_hash,
        )
    except StandardEvidenceError:
        raise
    except Exception as exc:
        raise StandardEvidenceError("standard_query_failed") from exc
    finally:
        _close_read_transaction(db, should_close_transaction)


def _indicator_matches(rule: Any, requested: str) -> bool:
    indicator = getattr(rule, "indicator", None)
    names = [getattr(indicator, "canonical_key", ""), getattr(indicator, "name_en", ""), *(getattr(indicator, "aliases", None) or [])]
    return str(requested).strip().casefold() in {str(name).strip().casefold() for name in names if name}


def _numeric_interpretation(value: Any, rule: Any, disease_code: str) -> str | None:
    if disease_code != "fatty_liver" or getattr(rule, "machine_actionability", None) != "calculable":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    lower, upper = getattr(rule, "lower", None), getattr(rule, "upper", None)
    if lower is not None and (number < lower or (number == lower and not getattr(rule, "lower_inclusive", True))):
        return "below_range"
    if upper is not None and (number > upper or (number == upper and not getattr(rule, "upper_inclusive", True))):
        return "above_range"
    return "within_range"


def _build_standard_evidence_in_transaction(db: Any, token: StandardVersionToken, snapshot: Mapping[str, Any]) -> StandardEvidence:
    try:
        from app.db.models import ReferenceStandardVersion

        version = db.query(ReferenceStandardVersion).filter(ReferenceStandardVersion.id == token.version_id).first()
    except Exception as exc:
        raise StandardEvidenceError("standard_query_failed") from exc
    if version is None:
        raise StandardEvidenceError("standard_missing")
    if getattr(version, "current_version", None) is not None:
        version = version.current_version
    document = getattr(version, "standard_document", None)
    case = snapshot.get("case") if isinstance(snapshot.get("case"), Mapping) else snapshot
    visits = snapshot.get("visits") if isinstance(snapshot.get("visits"), Sequence) else []
    contexts = build_indicator_contexts(case, visits)
    requested = list(contexts)
    for value in snapshot.get("indicators", []) if isinstance(snapshot.get("indicators"), list) else []:
        if isinstance(value, Mapping) and value.get("name"):
            requested.append(str(value["name"]).casefold())
    requested = list(dict.fromkeys(requested))
    rules: list[StandardRuleEvidence] = []
    matched_calculable: dict[str, list[int]] = {}
    for rule in getattr(version, "rules", None) or ():
        if requested and not any(_indicator_matches(rule, name) for name in requested):
            continue
        indicator = getattr(rule, "indicator", None)
        indicator_name = str(getattr(indicator, "canonical_key", None) or getattr(indicator, "name_en", None) or "unknown")
        context = contexts.get(indicator_name.casefold(), {})
        decision = evaluate_condition(build_effective_applicability(rule), context.__dict__ if isinstance(context, IndicatorContext) else context)
        actionability = getattr(rule, "machine_actionability", "evidence-only")
        if actionability not in {"calculable", "evidence-only", "blocked"}:
            actionability = "blocked"
        if str(case.get("disease_code", "")) == "ad" and actionability == "calculable":
            actionability = "evidence-only"
        if decision.status == "mismatched":
            status = "not_applicable"
        elif decision.status == "missing":
            status = "missing_context"
        elif actionability != "calculable":
            status = "evidence_only"
        else:
            status = "calculable"
            if getattr(rule, "conflict_group", None):
                matched_calculable.setdefault(str(rule.conflict_group), []).append(len(rules))
        source = getattr(rule, "source_segment", None)
        locator = EvidenceSourceLocator(
            segment_id=int(getattr(source, "id", 0) or 0), section_title=getattr(source, "section_title", None),
            paragraph_index=getattr(source, "paragraph_index", None), table_index=getattr(source, "table_index", None),
            row_index=getattr(source, "row_index", None), column_index=getattr(source, "column_index", None),
            page_number=getattr(source, "page_number", None), raw_text=str(getattr(source, "raw_text", "source unavailable"))[:1000] or "source unavailable",
        )
        latest_value = None
        if isinstance(context, IndicatorContext):
            for visit in visits:
                for item in visit.get("indicators") or []:
                    if isinstance(item, Mapping) and str(item.get("name", "")).casefold() == indicator_name.casefold() and visit.get("visit_date") == context.observed_at.isoformat():
                        latest_value = item.get("value")
        try:
            latest_value = float(latest_value) if latest_value is not None else None
        except (TypeError, ValueError):
            latest_value = None
        rules.append(StandardRuleEvidence(
            rule_id=int(getattr(rule, "id", 0)), indicator=indicator_name,
            display_name=str(getattr(indicator, "name_en", None) or indicator_name), status=status,
            machine_actionability=actionability, unit=getattr(rule, "unit", None), lower=getattr(rule, "lower", None), upper=getattr(rule, "upper", None),
            lower_inclusive=getattr(rule, "lower_inclusive", True), upper_inclusive=getattr(rule, "upper_inclusive", True),
            latest_value=latest_value,
            numeric_interpretation=(
                _numeric_interpretation(latest_value, rule, str(case.get("disease_code", "")))
                if status == "calculable" else None
            ),
            interpretation=getattr(rule, "interpretation", None), applicability=getattr(rule, "applicability", None) or {},
            applicability_hash=effective_applicability_hash(rule),
            conditions=EvidenceConditionDecision(status=decision.status, satisfied=list(decision.satisfied), missing=list(decision.missing), mismatched=list(decision.mismatched)), source=locator,
        ))
    for indexes in matched_calculable.values():
        if len(indexes) > 1:
            for index in indexes:
                rules[index] = rules[index].model_copy(update={"status": "conflict", "numeric_interpretation": None})
    statuses = {rule.status for rule in rules}
    overall = (
        "conflict" if "conflict" in statuses
        else "context_incomplete" if "missing_context" in statuses
        else "not_applicable" if not rules or statuses <= {"not_applicable"}
        else "available"
    )
    return StandardEvidence(
        status=overall,
        document=EvidenceDocument(document_id=token.document_id, title=str(getattr(document, "title", None) or getattr(document, "filename", "standard")), filename=str(getattr(document, "filename", "standard")), content_sha256=token.document_sha256, issuer=getattr(document, "issuer", None), publication_date=getattr(document, "publication_date", None), external_identifier=getattr(document, "external_identifier", None), source_url=getattr(document, "source_url", None)),
        version=EvidenceVersion(version_id=token.version_id, version_label=str(getattr(version, "version_label", "")), content_sha256=token.version_sha256, parser_version=str(getattr(version, "parser_version", "")), approved_at=getattr(version, "approved_at", None), effective_from=getattr(version, "effective_from", None)),
        rules=rules,
        warnings=[],
    )


def build_standard_evidence(db: Any, token: StandardVersionToken, snapshot: Mapping[str, Any]) -> StandardEvidence:
    should_close_transaction = callable(getattr(db, "rollback", None))
    try:
        _set_local_timeout(db, settings.STANDARD_EVIDENCE_QUERY_TIMEOUT_MS)
        return _build_standard_evidence_in_transaction(db, token, snapshot)
    finally:
        _close_read_transaction(db, should_close_transaction)


__all__ = [
    "AllNode", "AnyNode", "ConditionDecision", "ConditionNode", "EqualsNode",
    "IndicatorContext", "InNode", "NotNode", "PresentNode", "RangeNode",
    "StandardVersionToken", "StandardEvidenceError", "adapt_v1_applicability", "build_effective_applicability", "effective_applicability_hash", "build_indicator_contexts", "evaluate_condition", "preflight_standard", "build_standard_evidence",
]
