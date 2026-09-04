"""Strict, immutable evidence contract for operator longitudinal reports."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictEvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _quantize_score(value: float) -> float:
    decimal = Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return float(decimal)


def _finite_score(value: Any) -> float:
    decimal = Decimal(str(value))
    if not decimal.is_finite():
        raise ValueError("score must be finite")
    return _quantize_score(float(decimal))


class EvidenceIntegrity(StrictEvidenceModel):
    canonicalization_version: Literal["v1"] = "v1"
    hash_algorithm: Literal["sha256"] = "sha256"
    evidence_snapshot_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class EvidenceSourceLocator(StrictEvidenceModel):
    segment_id: int
    section_title: str | None = None
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    column_index: int | None = None
    page_number: int | None = Field(default=None, gt=0)
    raw_text: str = Field(min_length=1, max_length=1000)


class EvidenceDocument(StrictEvidenceModel):
    document_id: int
    title: str
    filename: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    issuer: str | None = None
    publication_date: date | None = None
    external_identifier: str | None = None
    source_url: str | None = None


class EvidenceVersion(StrictEvidenceModel):
    version_id: int
    version_label: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_version: str
    approved_at: datetime | None = None
    effective_from: datetime | None = None


class EvidenceConditionDecision(StrictEvidenceModel):
    status: Literal["matched", "missing", "mismatched"]
    satisfied: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    mismatched: list[str] = Field(default_factory=list)


class StandardRuleEvidence(StrictEvidenceModel):
    rule_id: int
    indicator: str
    display_name: str
    status: Literal["calculable", "evidence_only", "missing_context", "not_applicable", "conflict"]
    machine_actionability: Literal["calculable", "evidence-only", "blocked"]
    unit: str | None = None
    lower: float | None = None
    upper: float | None = None
    lower_inclusive: bool = True
    upper_inclusive: bool = True
    latest_value: float | None = None
    numeric_interpretation: Literal["within_range", "above_range", "below_range"] | None = None
    interpretation: str | None = None
    applicability: dict[str, Any] = Field(default_factory=dict)
    applicability_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    conditions: EvidenceConditionDecision
    source: EvidenceSourceLocator

    @model_validator(mode="after")
    def enforce_numeric_safety(self):
        if self.status != "calculable" or self.machine_actionability != "calculable":
            if self.numeric_interpretation is not None:
                raise ValueError("non-calculable evidence cannot have numeric interpretation")
        return self


class StandardEvidence(StrictEvidenceModel):
    status: Literal["available", "context_incomplete", "not_applicable", "conflict"]
    document: EvidenceDocument
    version: EvidenceVersion
    rules: list[StandardRuleEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ReferenceDataRelease(StrictEvidenceModel):
    logical_dataset: str
    dataset_release_id: str | None = None
    data_content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ReferenceFeatureComparison(StrictEvidenceModel):
    indicator: str
    status: Literal["comparable", "excluded"]
    score: float | None = Field(default=None, ge=0, le=1)
    reason: str | None = None

    @field_validator("score")
    @classmethod
    def quantize_score(cls, value: float | None) -> float | None:
        return None if value is None else _finite_score(value)


class ReferenceCaseScoreBreakdown(StrictEvidenceModel):
    conditional_similarity: float = Field(ge=0, le=100)
    coverage: float = Field(ge=0, le=1)
    ranking_score: float = Field(ge=0, le=100)
    available_weight: int = Field(ge=0, le=100)
    dimensions: dict[str, float] = Field(default_factory=dict)

    @field_validator("conditional_similarity", "coverage", "ranking_score")
    @classmethod
    def quantize_scores(cls, value: float) -> float:
        return _finite_score(value)

    @field_validator("dimensions")
    @classmethod
    def quantize_dimensions(cls, value: dict[str, float]) -> dict[str, float]:
        normalized = {str(key): _finite_score(item) for key, item in value.items()}
        if any(item < 0 or item > 1 for item in normalized.values()):
            raise ValueError("dimension scores must be between 0 and 1")
        return normalized


class ReferenceCaseFeatureProfile(StrictEvidenceModel):
    baseline_stage: str
    prediction_task: str
    age: int | None = Field(default=None, ge=0, le=120)
    sex: Literal["male", "female"] | None = None
    as_of: date
    visit_count: int = Field(ge=0)
    observation_span_days: int = Field(ge=0)
    feature_summary: dict[str, Any] = Field(default_factory=dict)
    measurement_context_summary: dict[str, Any] = Field(default_factory=dict)


class ReferenceCaseProfile(StrictEvidenceModel):
    anonymous_case_code: str = Field(pattern=r"^CASE-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$")
    features: ReferenceCaseFeatureProfile
    score: ReferenceCaseScoreBreakdown
    comparisons: list[ReferenceFeatureComparison] = Field(default_factory=list)
    outcome_status: Literal["positive", "negative", "unknown"]
    outcome_value: dict[str, Any] = Field(default_factory=dict)
    outcome_source: str
    outcome_reliability: Literal["low", "medium", "high"]
    source_trace: dict[str, Any] = Field(default_factory=dict)


class ReferencePoolStatistics(StrictEvidenceModel):
    total_windows: int = Field(ge=0)
    eligible_windows: int = Field(ge=0)
    comparable_windows: int = Field(ge=0)
    returned_windows: int = Field(ge=0, le=5)
    exclusion_counts: dict[str, int] = Field(default_factory=dict)


class ReferenceCaseSelection(StrictEvidenceModel):
    cases: list[ReferenceCaseProfile] = Field(default_factory=list, max_length=5)


class ReferenceCaseEvidence(StrictEvidenceModel):
    status: Literal["available", "no_eligible_cases", "insufficient_comparability", "reference_query_failed", "reference_index_stale"]
    data_release: ReferenceDataRelease
    algorithm_version: Literal["reference_similarity.v1"]
    configuration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    pool_statistics: ReferencePoolStatistics
    cases: list[ReferenceCaseProfile] = Field(default_factory=list, max_length=5)
    warnings: list[str] = Field(default_factory=list)


class EvidenceBundle(StrictEvidenceModel):
    schema_version: Literal["longitudinal_evidence_bundle.v1"] = "longitudinal_evidence_bundle.v1"
    evidence_bundle_id: UUID
    generation_batch_id: UUID
    disease_code: Literal["fatty_liver", "ad"]
    created_at: datetime
    standard: StandardEvidence
    reference_cases: ReferenceCaseEvidence
    warnings: list[str] = Field(default_factory=list)
    integrity: EvidenceIntegrity = Field(default_factory=EvidenceIntegrity)

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include timezone")
        return value


__all__ = [
    "EvidenceBundle",
    "EvidenceConditionDecision",
    "EvidenceDocument",
    "EvidenceIntegrity",
    "EvidenceSourceLocator",
    "EvidenceVersion",
    "ReferenceCaseEvidence",
    "ReferenceCaseFeatureProfile",
    "ReferenceCaseProfile",
    "ReferenceCaseScoreBreakdown",
    "ReferenceCaseSelection",
    "ReferenceDataRelease",
    "ReferenceFeatureComparison",
    "ReferencePoolStatistics",
    "StandardEvidence",
    "StandardRuleEvidence",
]
