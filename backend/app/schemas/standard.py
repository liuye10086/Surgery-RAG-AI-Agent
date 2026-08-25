"""Pydantic contracts for the versioned standard rules layer."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NumericExpression(BaseModel):
    lower: float | None = None
    upper: float | None = None
    lower_inclusive: bool = True
    upper_inclusive: bool = True
    unit: str = ""
    raw_text: str = ""


class StandardSegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version_id: int
    section_title: str | None = None
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    column_index: int | None = None
    raw_text: str
    segment_type: str
    parse_status: str
    review_status: str
    source_metadata: dict[str, Any] = {}


class RulePatch(BaseModel):
    indicator_id: int | None = None
    rule_type: str | None = None
    comparator: str | None = None
    lower: float | None = None
    upper: float | None = None
    lower_inclusive: bool | None = None
    upper_inclusive: bool | None = None
    unit: str | None = None
    sex: str | None = None
    category: str | None = None
    applicability: dict[str, Any] | None = None
    target_state_type: str | None = None
    target_state_value: str | None = None
    clinical_dimension: str | None = None
    evidence_type: str | None = None
    machine_actionability: Literal["calculable", "evidence-only", "blocked"] | None = None
    interpretation: str | None = None
    priority: int | None = None
    conflict_group: str | None = None
    framework: str | None = None
    biomarker_axis: str | None = None
    biomarker_state: str | None = None
    stage: str | None = None
    clinical_function: str | None = None
    conditions: dict[str, Any] | None = None


class RuleOut(RulePatch):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version_id: int
    source_segment_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class StandardParseCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version_id: int
    segment_id: int
    source_type: str
    parser_version: str
    model_name: str | None = None
    prompt_version: str | None = None
    raw_output: str | None = None
    candidate_json: dict[str, Any] = {}
    confidence: float | None = None
    status: str
    created_at: datetime | None = None


class ConditionPayload(BaseModel):
    node_type: Literal["all", "any", "not", "at_least_n", "at_most_n", "leaf"]
    payload: dict[str, Any] = {}
    children: list["ConditionPayload"] = []


class ValidationFinding(BaseModel):
    level: Literal["error", "warning", "info"]
    code: str
    message: str
    entity_type: str | None = None
    entity_id: int | None = None


class ValidationReport(BaseModel):
    errors: list[ValidationFinding] = []
    warnings: list[ValidationFinding] = []
    infos: list[ValidationFinding] = []
    projection_count: int = 0

    @property
    def can_publish(self) -> bool:
        return not self.errors


class StandardCreate(BaseModel):
    disease_id: int


class StandardVersionCreate(BaseModel):
    standard_document_id: int
    version_label: str = Field(..., min_length=1, max_length=100)
    parser_version: str = Field("v1", min_length=1, max_length=100)

    @field_validator("version_label")
    @classmethod
    def strip_version_label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("版本标签不能为空")
        return value


class StandardChangeRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("修改原因不能为空")
        return value


class StandardVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    standard_id: int
    standard_document_id: int
    version_label: str
    content_hash: str
    parser_version: str
    status: str
    supersedes_version_id: int | None = None
    effective_from: datetime | None = None
    retired_at: datetime | None = None
    created_by: int | None = None
    approved_by: int | None = None
    approved_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class StandardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    disease_id: int
    name: str
    description: str | None = None
    status: str
    current_version_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


ConditionPayload.model_rebuild()
