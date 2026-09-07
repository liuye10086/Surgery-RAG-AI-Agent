from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas.longitudinal_model_registry import ModelRuntimeStatus

Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class StrictReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PinnedStandard(StrictReportModel):
    standard_id: int
    version_id: int
    document_id: int
    document_sha256: Sha
    version_sha256: Sha


class PinnedEvidenceToken(StrictReportModel):
    standard: PinnedStandard
    dataset_release_id: str | None
    data_content_sha256: Sha | None
    eligibility_config_hash: Sha
    similarity_config_hash: Sha
    logical_dataset: str | None
    reference_status: (
        Literal["reference_query_failed", "reference_index_stale"] | None
    ) = None


class IndicatorLabel(StrictReportModel):
    code: str
    label: str
    allowed_units: list[str]
    context_requirements: list[str]


class ReportGenerationContext(StrictReportModel):
    schema_version: Literal["report_generation_context.v1"] = (
        "report_generation_context.v1"
    )
    disease_code: Literal["fatty_liver", "ad"]
    release_set_id: str
    release_set_sha256: Sha
    data_release_id: str
    dataset_manifest_sha256: Sha
    split_sha256: Sha
    indicator_catalog_sha256: Sha
    indicator_labels: list[IndicatorLabel]
    minimum_visits: int = Field(ge=1, le=10)
    minimum_signal_observations: int = Field(ge=1)
    standard_rules_sha256: Sha
    evidence_token: PinnedEvidenceToken
    template_version: Literal["operator_report.zh-CN.v1"] = "operator_report.zh-CN.v1"


class ReportIdentity(StrictReportModel):
    report_id: int = Field(gt=0)
    batch_id: UUID
    anonymous_case_code: str | None
    disease_code: Literal["fatty_liver", "ad"]
    disease_name: str
    age: int = Field(ge=0, le=120, strict=True)
    sex: Literal["male", "female"]
    baseline_stage: str
    baseline_stage_label: str
    created_at: datetime
    anchor_date: date
    horizon_days: int = Field(ge=1)
    prediction_end_date: date

    @model_validator(mode="after")
    def validate_identity(self):
        import re

        if self.anonymous_case_code is not None and not re.fullmatch(
            r"CASE-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}", self.anonymous_case_code
        ):
            raise ValueError("invalid_anonymous_case_code")
        if self.created_at.tzinfo is None:
            raise ValueError("report_time_requires_timezone")
        if self.prediction_end_date != self.anchor_date + timedelta(
            days=self.horizon_days
        ):
            raise ValueError("prediction_anchor_mismatch")
        return self


class InputFieldAudit(StrictReportModel):
    name: str
    state: Literal["present", "allowed_missing", "required_missing", "invalid"]


class InputAudit(StrictReportModel):
    task: str
    fields: list[InputFieldAudit]
    frame_sha256: Sha | None = None
    numeric_imputation: str | None = None
    categorical_imputation: str | None = None
    model_invoked: bool = False
    reason_code: str | None = None

    @model_validator(mode="after")
    def validate_invocation(self):
        if len({f.name for f in self.fields}) != len(self.fields):
            raise ValueError("duplicate_audit_field")
        if self.model_invoked and (
            self.frame_sha256 is None
            or any(f.state in {"required_missing", "invalid"} for f in self.fields)
        ):
            raise ValueError("invalid_model_invocation_audit")
        return self


class TrainingDisclosure(StrictReportModel):
    synthetic_in_formal_metrics: bool | None
    clinical_validity_claim: bool | None
    production_enabled: bool | None
    training_file_sha256: Sha | None
    composition_note: str


class ModelRunAudit(StrictReportModel):
    task: str
    target_label: str
    horizon_kind: Literal["days", "next_visit"]
    horizon_days: int | None
    runtime: ModelRuntimeStatus
    input_audit: InputAudit
    training: TrainingDisclosure
    score_threshold: float | None = None
    risk_band_rule_version: str | None = None


class QualityIssue(StrictReportModel):
    code: str
    severity: Literal["blocking", "warning", "info"]
    source: Literal["input", "model", "standard", "reference", "observation"]
    task: str | None = None
    visit_index: int | None = Field(default=None, ge=1)
    indicator: str | None = None
    field: str | None = None
    message: str
    impact: str
    action: str


class ReportSummary(StrictReportModel):
    observation_status: Literal["available", "limited"]
    model_input_status: Literal["satisfied", "partial", "unavailable"]
    selected_model_count: int = Field(ge=0)
    invoked_model_count: int = Field(ge=0)
    available_model_count: int = Field(ge=0)
    signal_count: int = Field(ge=0)
    evidence_status: Literal["complete", "partial"]
    limitations: list[str]


class ChartPoint(StrictReportModel):
    visit_date: date
    value: float = Field(strict=True)


class ObservedChart(StrictReportModel):
    indicator: str
    label: str
    unit: str
    points: list[ChartPoint]


class ReportTable(StrictReportModel):
    title: str
    headers: list[str]
    rows: list[list[str]]

    @model_validator(mode="after")
    def same_width(self):
        if not self.headers or any(len(row) != len(self.headers) for row in self.rows):
            raise ValueError("report_table_width_mismatch")
        return self


class ReportSection(StrictReportModel):
    number: int = Field(ge=1, le=11)
    title: str
    paragraphs: list[str]
    tables: list[ReportTable]


class EvidenceReference(StrictReportModel):
    evidence_bundle_id: UUID
    evidence_snapshot_sha256: Sha


class ReportDocument(StrictReportModel):
    schema_version: Literal["report_document.v1"] = "report_document.v1"
    template_version: Literal["operator_report.zh-CN.v1"] = "operator_report.zh-CN.v1"
    identity: ReportIdentity
    generation_context: ReportGenerationContext
    summary: ReportSummary
    data_quality: list[QualityIssue]
    model_runs: list[ModelRunAudit]
    evidence: EvidenceReference
    review_items: list[QualityIssue]
    charts: list[ObservedChart]
    sections: list[ReportSection]

    @model_validator(mode="after")
    def same_generation(self):
        if [s.number for s in self.sections] != list(range(1, 12)):
            raise ValueError("report_sections_invalid")
        if self.identity.disease_code != self.generation_context.disease_code:
            raise ValueError("report_disease_mismatch")
        if self.template_version != self.generation_context.template_version:
            raise ValueError("report_template_mismatch")
        return self


class Publication(StrictReportModel):
    content: str
    prediction_result: dict
    sources: list[dict]
    evidence_snapshot: dict
    evidence_snapshot_sha256: Sha
    evidence_status: Literal["complete", "partial"]
    standard_evidence_status: str
    reference_case_status: str
    report_document: ReportDocument
    report_document_sha256: Sha
    generation_fingerprint: Sha
    generation_fingerprint_version: Literal["v2"] = "v2"
