"""Deterministic, prefix-only reference-case profile construction."""

from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.longitudinal_evidence import ReferenceDataRelease
from app.services.longitudinal_features import sort_visits, summarize_fixed_window_history
from app.services.reference_case_eligibility import (
    REFERENCE_PROFILE_SCHEMA_VERSION,
    ReferenceEligibilityCandidate,
    evaluate_reference_candidate,
)


class ReferenceCaseWindowWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disease_code: str
    dataset_release_id: str
    anonymous_case_code: str
    as_of: str
    horizon_days: Literal[365] = 365
    profile_schema_version: str
    age: int | None = None
    sex: str | None = None
    baseline_stage: str | None = None
    visit_count: int = Field(ge=3)
    span_days: int = Field(ge=0)
    outcome_status: str = "unknown"
    outcome_value: dict[str, Any] = Field(default_factory=dict)
    source_trace: dict[str, Any]
    feature_summary: dict[str, Any]
    measurement_context_summary: dict[str, Any]
    exclusion_reasons: list[str] = Field(default_factory=list)
    timeline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    timeline_canonical_json: str


class WindowBuildResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profiles: tuple[ReferenceCaseWindowWrite, ...]
    total_windows: int
    eligible_windows: int
    exclusion_counts: dict[str, int]


_CONTEXT_KEYS = (
    "source_type", "facility_name", "device_name", "assay_platform", "method",
    "specimen", "scale_version", "assessment_language", "education_years",
    "education_adjusted", "imaging_type",
)


def _safe_context_summary(history: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values: dict[str, set[str]] = {key: set() for key in _CONTEXT_KEYS}
    changed: set[str] = set()
    previous: dict[str, str] = {}
    for visit in history:
        context = visit.get("visit_context") if isinstance(visit.get("visit_context"), Mapping) else {}
        for key in _CONTEXT_KEYS:
            value = context.get(key)
            if value in (None, ""):
                continue
            normalized = str(value).strip()[:200]
            values[key].add(normalized)
            if key in previous and previous[key] != normalized:
                changed.add(key)
            previous[key] = normalized
    return {"values": {key: sorted(items) for key, items in values.items() if items}, "changed": sorted(changed)}


def _safe_visit(visit: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "visit_date": str(visit.get("visit_date")),
        "indicators": [
            {key: item.get(key) for key in ("name", "value", "unit") if key in item}
            for item in (visit.get("indicators") or [])
            if isinstance(item, Mapping) and item.get("name")
        ],
        "visit_context": {
            key: visit.get("visit_context", {}).get(key)
            for key in _CONTEXT_KEYS
            if isinstance(visit.get("visit_context"), Mapping) and visit.get("visit_context", {}).get(key) not in (None, "")
        },
    }


def build_window_profiles(rows: Sequence[Mapping[str, Any]], disease_code: str, release: ReferenceDataRelease) -> WindowBuildResult:
    profiles: list[ReferenceCaseWindowWrite] = []
    exclusion_counts: dict[str, int] = {}
    total_windows = 0
    for row in rows:
        if str(row.get("disease_code", "")) != disease_code:
            continue
        ordered = sort_visits([dict(item) for item in (row.get("visits") or [])])
        for index in range(2, len(ordered)):
            total_windows += 1
            history = ordered[: index + 1]
            candidate = ReferenceEligibilityCandidate(
                disease_code=disease_code, expected_disease_code=disease_code,
                dataset_release_id=str(row.get("dataset_release_id", "")), expected_release_id=release.dataset_release_id,
                is_synthetic=bool(row.get("is_synthetic", False)), anonymous_case_code=row.get("anonymous_case_code"),
                visit_count=len(history), source_trace=dict(row.get("source_trace") or {}),
                outcome_source=str(row.get("outcome_source", "")), outcome_reliability=str(row.get("outcome_reliability", "low")),
                task_compatible=bool(row.get("task_compatible", True)), timeline_valid=bool(row.get("timeline_valid", True)),
            )
            decision = evaluate_reference_candidate(candidate)
            if not decision.eligible:
                for reason in decision.reasons:
                    exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
                continue
            as_of = str(history[-1]["visit_date"])
            safe_history = [_safe_visit(item) for item in history]
            canonical = json.dumps({"anonymous_case_code": candidate.anonymous_case_code, "as_of": as_of, "visits": safe_history}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            feature_summary = summarize_fixed_window_history([dict(item) for item in history])
            first = date.fromisoformat(str(history[0]["visit_date"]))
            last = date.fromisoformat(as_of)
            outcome = dict(row.get("outcome_value") or {})
            profiles.append(ReferenceCaseWindowWrite(
                disease_code=disease_code, dataset_release_id=release.dataset_release_id,
                anonymous_case_code=str(candidate.anonymous_case_code), as_of=as_of,
                profile_schema_version=REFERENCE_PROFILE_SCHEMA_VERSION,
                age=row.get("age"), sex=row.get("sex"), baseline_stage=row.get("baseline_stage"),
                visit_count=len(history), span_days=(last - first).days,
                outcome_status=str(row.get("outcome_status", "unknown")), outcome_value=outcome,
                source_trace=dict(candidate.source_trace), feature_summary=feature_summary,
                measurement_context_summary=_safe_context_summary(history),
                timeline_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                timeline_canonical_json=canonical,
            ))
    return WindowBuildResult(profiles=tuple(profiles), total_windows=total_windows, eligible_windows=len(profiles), exclusion_counts=exclusion_counts)


__all__ = ["ReferenceCaseWindowWrite", "WindowBuildResult", "build_window_profiles"]
