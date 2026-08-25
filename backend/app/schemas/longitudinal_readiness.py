"""Strict contract for longitudinal report readiness checks."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ReadinessStatus = Literal["ready", "degraded", "blocked"]
CheckStatus = Literal["available", "degraded", "blocked", "not_applicable"]
ArtifactStatus = Literal[
    "available", "missing", "incompatible", "disabled", "not_configured"
]
ReasonSeverity = Literal["degraded", "blocked"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadinessReason(StrictModel):
    code: str
    message: str
    severity: ReasonSeverity
    next_task: str
    details: dict[str, object] = Field(default_factory=dict)


class DataReadiness(StrictModel):
    status: CheckStatus
    patient_count: int = 0
    visit_count: int = 0
    all_prefix_count: int = 0
    estimable_prefix_count: int = 0
    positive_count: int = 0
    negative_count: int = 0
    unknown_count: int = 0
    source_datasets: list[str] = Field(default_factory=list)
    real_patient_count: int = 0
    synthetic_patient_count: int = 0
    unknown_provenance_patient_count: int = 0

    @model_validator(mode="after")
    def counts_are_consistent(self):
        if (
            self.positive_count + self.negative_count + self.unknown_count
            != self.all_prefix_count
        ):
            raise ValueError("前缀标签统计不一致")
        if self.estimable_prefix_count != self.positive_count + self.negative_count:
            raise ValueError("可估计前缀统计不一致")
        return self


class StandardReadiness(StrictModel):
    status: CheckStatus
    standard_id: int | None = None
    current_version_id: int | None = None
    version_label: str | None = None
    version_status: str | None = None
    content_hash: str | None = None
    rule_count: int = 0
    calculable_rule_count: int = 0


class ArtifactReadiness(StrictModel):
    status: ArtifactStatus
    artifact_type: Literal["outcome", "stage", "trend"]
    indicator: str | None = None
    model_file: str | None = None
    metadata_file: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)


class ModelReadiness(StrictModel):
    outcome: ArtifactReadiness
    stage: ArtifactReadiness
    trends: list[ArtifactReadiness] = Field(default_factory=list)


class CapabilityReadiness(StrictModel):
    key: str
    required: bool
    status: CheckStatus
    message: str
    next_task: str | None = None


class ReportContractReadiness(StrictModel):
    status: CheckStatus
    capabilities: list[CapabilityReadiness] = Field(default_factory=list)


class DiseaseReadiness(StrictModel):
    dataset: Literal["fatty_liver", "ad"]
    disease_name: str
    status: ReadinessStatus
    data: DataReadiness
    standard: StandardReadiness
    models: ModelReadiness
    report_contract: ReportContractReadiness
    available_capabilities: list[str] = Field(default_factory=list)
    reasons: list[ReadinessReason] = Field(default_factory=list)
    next_tasks: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def status_matches_reasons(self):
        expected = status_from_reasons(self.reasons)
        if self.status != expected:
            raise ValueError("疾病状态与原因严重级别不一致")
        expected_tasks = list(
            dict.fromkeys(reason.next_task for reason in self.reasons)
        )
        if self.next_tasks != expected_tasks:
            raise ValueError("next_tasks 必须由 reasons 按顺序去重生成")
        return self


class EnvironmentReadiness(StrictModel):
    database_check: Literal["available"]
    alembic_revision: str | None = None
    code_heads: list[str] = Field(default_factory=list)
    revision_matches: bool | None = None


class LongitudinalReadinessReport(StrictModel):
    schema_version: Literal["longitudinal_readiness.v1"] = (
        "longitudinal_readiness.v1"
    )
    generated_at: datetime
    overall_status: ReadinessStatus
    environment: EnvironmentReadiness
    diseases: dict[Literal["fatty_liver", "ad"], DiseaseReadiness]

    @model_validator(mode="after")
    def diseases_and_status_are_consistent(self):
        if set(self.diseases) != {"fatty_liver", "ad"}:
            raise ValueError("readiness 报告必须分别包含 fatty_liver 和 ad")
        severity = {"ready": 0, "degraded": 1, "blocked": 2}
        expected = max(
            (item.status for item in self.diseases.values()),
            key=severity.__getitem__,
        )
        if self.overall_status != expected:
            raise ValueError("overall_status 必须等于疾病状态中的最高严重度")
        return self


def status_from_reasons(reasons: list[ReadinessReason]) -> ReadinessStatus:
    if any(reason.severity == "blocked" for reason in reasons):
        return "blocked"
    if reasons:
        return "degraded"
    return "ready"
