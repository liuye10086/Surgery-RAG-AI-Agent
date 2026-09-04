"""Explicit production admission policy for anonymized reference cases."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ANONYMOUS_CODE = re.compile(r"^CASE-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$")
OUTCOME_ALLOWLIST = {
    "fatty_liver": frozenset({"explicit_cirrhosis", "explicit_hcc"}),
    "ad": frozenset({"explicit_cdr", "documented_ad_unspecified"}),
}
REASON_ORDER = (
    "disease_mismatch", "release_mismatch", "synthetic_source",
    "anonymous_code_missing", "anonymous_code_invalid", "insufficient_visits",
    "source_trace_missing", "outcome_source_not_allowed",
    "outcome_reliability_insufficient", "task_incompatible", "timeline_invalid",
)
ELIGIBILITY_CONFIG_VERSION = "reference_eligibility.v1"
ELIGIBILITY_CONFIG_HASH = hashlib.sha256(json.dumps(
    {"version": ELIGIBILITY_CONFIG_VERSION, "anonymous_pattern": ANONYMOUS_CODE.pattern,
     "outcome_allowlist": {key: sorted(value) for key, value in OUTCOME_ALLOWLIST.items()},
     "minimum_visits": 3, "outcome_reliability": "high"},
    ensure_ascii=False, sort_keys=True, separators=(",", ":"),
).encode("utf-8")).hexdigest()
REFERENCE_PROFILE_SCHEMA_VERSION = f"reference_case_profile.v1+{ELIGIBILITY_CONFIG_HASH[:12]}"


class ReferenceEligibilityCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disease_code: Literal["fatty_liver", "ad"]
    expected_disease_code: Literal["fatty_liver", "ad"]
    dataset_release_id: str
    expected_release_id: str
    is_synthetic: bool
    anonymous_case_code: str | None
    visit_count: int = Field(ge=0)
    source_trace: dict[str, Any]
    outcome_source: str
    outcome_reliability: Literal["low", "medium", "high"]
    task_compatible: bool
    timeline_valid: bool


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    reasons: tuple[str, ...]


def evaluate_reference_candidate(candidate: ReferenceEligibilityCandidate) -> EligibilityDecision:
    reasons: list[str] = []
    if candidate.disease_code != candidate.expected_disease_code:
        reasons.append("disease_mismatch")
    if candidate.dataset_release_id != candidate.expected_release_id:
        reasons.append("release_mismatch")
    if candidate.is_synthetic:
        reasons.append("synthetic_source")
    if candidate.anonymous_case_code is None:
        reasons.append("anonymous_code_missing")
    elif not ANONYMOUS_CODE.fullmatch(candidate.anonymous_case_code):
        reasons.append("anonymous_code_invalid")
    if candidate.visit_count < 3:
        reasons.append("insufficient_visits")
    if not candidate.source_trace:
        reasons.append("source_trace_missing")
    if candidate.outcome_source not in OUTCOME_ALLOWLIST.get(candidate.disease_code, frozenset()):
        reasons.append("outcome_source_not_allowed")
    if candidate.outcome_reliability != "high":
        reasons.append("outcome_reliability_insufficient")
    if not candidate.task_compatible:
        reasons.append("task_incompatible")
    if not candidate.timeline_valid:
        reasons.append("timeline_invalid")
    ordered = tuple(reason for reason in REASON_ORDER if reason in reasons)
    return EligibilityDecision(eligible=not ordered, reasons=ordered)


__all__ = [
    "ANONYMOUS_CODE", "ELIGIBILITY_CONFIG_HASH", "ELIGIBILITY_CONFIG_VERSION",
    "EligibilityDecision", "REFERENCE_PROFILE_SCHEMA_VERSION", "ReferenceEligibilityCandidate",
    "evaluate_reference_candidate",
]
