"""Reference evidence selection with explicit synthetic-data provenance."""

from __future__ import annotations

from typing import Any


def mark_synthetic_source(source: dict[str, Any]) -> dict[str, Any]:
    result = dict(source)
    synthetic = bool(result.get("is_synthetic")) or str(result.get("source_dataset", "")).endswith("_300") and str(result.get("patient_label", ""))[1:].isdigit() and int(str(result.get("patient_label", "0"))[1:]) >= 151
    result["is_synthetic"] = synthetic
    result["provenance"] = "synthetic" if synthetic else result.get("provenance", "reference")
    if synthetic:
        result["display_warning"] = "该参考病例来自合成或规则重组数据"
    return result


def build_reference_range_sources(db, indicator_names: list[str], patient_sex: str | None = None, disease_id: int | None = None, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if disease_id is not None:
        from app.services.standard_resolver import resolve_standard_rules

        resolution = resolve_standard_rules(db, disease_id, indicator_names, {**(context or {}), "sex": patient_sex} if patient_sex else context or {})
        sources: list[dict[str, Any]] = []
        for rule in [*resolution.calculable_rules, *resolution.evidence_rules]:
            indicator = getattr(rule, "indicator", None)
            sources.append({
                "source_type": "reference_range" if getattr(rule, "machine_actionability", "evidence-only") == "calculable" else "standard_evidence",
                "indicator": getattr(indicator, "name_en", None) or getattr(indicator, "canonical_key", None),
                "unit": getattr(rule, "unit", None),
                "lower": getattr(rule, "lower", None),
                "upper": getattr(rule, "upper", None),
                "lower_inclusive": getattr(rule, "lower_inclusive", True),
                "upper_inclusive": getattr(rule, "upper_inclusive", True),
                "sex": getattr(rule, "sex", None),
                "machine_actionability": getattr(rule, "machine_actionability", "evidence-only"),
                "standard_version_id": getattr(rule, "standard_version_id", resolution.version_id),
                "standard_rule_id": getattr(rule, "standard_rule_id", getattr(rule, "id", None)),
                "applicability_hash": getattr(rule, "applicability_hash", None),
                "applicability": getattr(rule, "applicability", {}) or {},
                "applicability_warning": getattr(rule, "resolution_warning", None),
                "provenance": "reference_standard",
            })
        for warning in resolution.warnings:
            sources.append({"source_type": "standard_warning", "message": warning, "standard_version_id": resolution.version_id, "standard_rule_id": None, "provenance": "reference_standard"})
        for rule in resolution.unmatched_rules:
            sources.append({"source_type": "standard_unmatched", "standard_version_id": resolution.version_id, "standard_rule_id": getattr(rule, "id", None), "applicability": getattr(rule, "applicability", {}) or {}, "provenance": "reference_standard"})
        for rule in resolution.conflicting_rules:
            sources.append({"source_type": "standard_conflict", "standard_version_id": resolution.version_id, "standard_rule_id": getattr(rule, "id", None), "applicability": getattr(rule, "applicability", {}) or {}, "provenance": "reference_standard"})
        if sources or resolution.version_id is not None:
            return sources
    from app.db.models import ReferenceRange
    from sqlalchemy import func

    normalized_names = {str(name).strip().lower() for name in indicator_names if str(name).strip()}
    query = db.query(ReferenceRange).filter(func.lower(ReferenceRange.indicator_name).in_(normalized_names))
    rows = query.all()
    sources = []
    for row in rows:
        if row.sex and (not patient_sex or row.sex != patient_sex):
            continue
        sources.append({"source_type": "reference_range", "indicator": row.indicator_name, "unit": row.unit, "lower": row.lower, "upper": row.upper, "lower_inclusive": row.lower_inclusive, "upper_inclusive": row.upper_inclusive, "standard_version_id": getattr(row, "standard_version_id", None), "standard_rule_id": getattr(row, "standard_rule_id", None), "applicability_hash": getattr(row, "applicability_hash", None), "provenance": "reference_standard"})
    return sources


def select_similar_longitudinal_cases(db, disease_id: int, visits: list[dict[str, Any]], adapter, limit: int = 5) -> list[dict[str, Any]]:
    from app.db.models import CaseRecord
    rows = db.query(CaseRecord).filter(CaseRecord.disease_id == disease_id, CaseRecord.confirmed.is_(True)).limit(max(limit * 10, limit)).all()
    requested = {str(item.get("name", "")).lower() for visit in visits for item in visit.get("indicators", [])}
    results_by_label: dict[str, dict[str, Any]] = {}
    for row in rows:
        observed = {str(item.get("name", "")).lower() for item in (row.indicators or [])}
        overlap = sorted(requested & observed)
        if not overlap:
            continue
        label = str(row.patient_label or "").strip()
        key = label.casefold()
        source = results_by_label.get(key)
        if source is None:
            source = {
                "source_type": "similar_case",
                "patient_label": label,
                "source_dataset": (row.case_metadata or {}).get("source_dataset"),
                "final_outcome": bool(row.confirmed),
                "overlap_features": [],
            }
            results_by_label[key] = source
        source["overlap_features"] = sorted(
            set(source["overlap_features"]) | set(overlap)
        )
    return [mark_synthetic_source(source) for source in list(results_by_label.values())[:limit]]


def build_document_sources(db, disease_id: int, indicator_names: list[str]) -> list[dict[str, Any]]:
    return []
