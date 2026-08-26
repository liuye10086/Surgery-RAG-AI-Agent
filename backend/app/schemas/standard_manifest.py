"""Strict, reviewable manifest contract for standard rule publication."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ManifestReviewState = Literal["pending", "approved"]
EntryReviewStatus = Literal["pending", "approved", "rejected"]
ManifestEntryKind = Literal["rule", "no_safe_rule"]
ManifestActionability = Literal["calculable", "evidence-only", "blocked"]
AbnormalDirection = Literal["high", "low", "ordinal_high", "ordinal_low", "contextual", "none"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceLocator(StrictModel):
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    column_index: int | None = None
    raw_text: str = Field(min_length=1)

    @model_validator(mode="after")
    def has_location(self):
        if self.paragraph_index is None and self.table_index is None:
            raise ValueError("源定位必须包含 paragraph_index 或 table_index")
        if self.table_index is not None and self.row_index is None:
            raise ValueError("表格定位必须包含 row_index")
        return self


class ManifestIndicator(StrictModel):
    canonical_key: str = Field(min_length=1, pattern=r"^[^\s]+$")
    name_en: str
    name_cn: str | None = None
    aliases: list[str] = Field(default_factory=list)
    domain: str
    specimen_or_modality: str | None = None
    data_type: Literal["numeric", "ordinal", "categorical", "qualitative"]
    scale_or_method: str | None = None
    default_unit: str | None = None
    clinical_dimension: str
    allows_numeric_comparison: bool
    abnormal_direction: AbnormalDirection


class ManifestRule(StrictModel):
    rule_type: Literal["numeric_range", "threshold", "qualitative_direction", "classification", "exclusion", "composite"]
    comparator: str | None = None
    lower: float | None = None
    upper: float | None = None
    lower_inclusive: bool = True
    upper_inclusive: bool = True
    unit: str | None = None
    sex: str | None = None
    category: str | None = None
    applicability: dict[str, Any] = Field(default_factory=dict)
    target_state_type: str
    target_state_value: str | None = None
    clinical_dimension: str
    evidence_type: str | None = None
    machine_actionability: ManifestActionability
    actionability_reason: str = Field(min_length=1)
    interpretation: str | None = None
    priority: int = 0
    conflict_group: str | None = None
    framework: str | None = None
    biomarker_axis: str | None = None
    biomarker_state: str | None = None
    stage: str | None = None
    clinical_function: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def applicability_does_not_use_reserved_keys(self):
        if any(str(key).startswith("_") for key in self.applicability):
            raise ValueError("applicability 不得使用下划线开头的保留键")
        return self


class StandardManifestEntry(StrictModel):
    entry_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    entry_kind: ManifestEntryKind
    review_status: EntryReviewStatus
    review_note: str | None = None
    source: SourceLocator
    indicator: ManifestIndicator
    rule: ManifestRule | None = None

    @model_validator(mode="after")
    def kind_matches_rule(self):
        if self.entry_kind == "rule" and self.rule is None:
            raise ValueError("rule 条目必须提供规则")
        if self.entry_kind == "no_safe_rule" and self.rule is not None:
            raise ValueError("no_safe_rule 条目不得提供规则")
        return self


class StandardManifest(StrictModel):
    schema_version: Literal["standard_manifest.v1"] = "standard_manifest.v1"
    dataset: Literal["fatty_liver", "ad"]
    disease_name: str
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_version_label: str = Field(min_length=1, max_length=100)
    review_state: ManifestReviewState
    reviewed_at: datetime | None = None
    entries: list[StandardManifestEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def review_and_ids_are_consistent(self):
        ids = [entry.entry_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("entry_id 必须唯一")
        if self.review_state == "approved":
            if self.reviewed_at is None:
                raise ValueError("approved manifest 必须包含 reviewed_at")
            if any(entry.review_status == "pending" for entry in self.entries):
                raise ValueError("approved manifest 不得包含 pending 条目")
        return self
