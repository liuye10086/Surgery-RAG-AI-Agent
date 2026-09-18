from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.schemas.longitudinal_model_registry import ModelRuntimeStatus
from app.schemas.synthetic_numeric_prediction import (
    CalendarDate, NumericSourceIdentity, StrictNumericModel,
    SyntheticNumericInput, SyntheticNumericPrediction,
)
from app.schemas.synthetic_report_context import SyntheticGenerationContext

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


class SyntheticReportIdentity(StrictNumericModel):
    report_id: int = Field(gt=0, strict=True)
    batch_id: UUID
    anonymous_case_code: str = Field(pattern=r"^CASE-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$")
    disease_code: Literal["ad", "fatty_liver"]
    disease_name: str = Field(min_length=1)
    age: int = Field(ge=0, le=120, strict=True)
    sex: Literal["male", "female"]
    baseline_stage: str = Field(min_length=1)
    created_at: datetime
    anchor_date: CalendarDate

    @model_validator(mode="after")
    def valid_identity(self):
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("report_time_requires_timezone")
        stages = {"ad": {"normal", "mci", "pre_dementia", "dementia"},
                  "fatty_liver": {"pre_cirrhosis", "suspected_cirrhosis", "cirrhosis", "hcc"}}
        if self.baseline_stage not in stages[self.disease_code]:
            raise ValueError("synthetic_report_stage_mismatch")
        return self


class SyntheticNumericReportDocument(StrictNumericModel):
    schema_version: Literal["synthetic_numeric_report_document.v1"] = "synthetic_numeric_report_document.v1"
    template_version: Literal["synthetic_numeric_report.zh-CN.v1"] = "synthetic_numeric_report.zh-CN.v1"
    identity: SyntheticReportIdentity
    generation_context: SyntheticGenerationContext
    numeric_input: SyntheticNumericInput
    prediction: SyntheticNumericPrediction

    @model_validator(mode="after")
    def same_generation(self):
        identity, context, numeric, result = self.identity, self.generation_context, self.numeric_input, self.prediction
        if len({identity.disease_code, context.disease_code, numeric.disease_code, result.disease_code}) != 1:
            raise ValueError("synthetic_report_disease_mismatch")
        if (identity.anchor_date, numeric.subject_id, numeric.dependency_group_id, numeric.source,
            context.numeric_input_sha256, context.algorithm, self.template_version) != (
            result.anchor_date, result.subject_id, result.dependency_group_id, result.source,
            result.input_sha256, result.algorithm, context.template_version
        ) or numeric.anchor_date != identity.anchor_date:
            raise ValueError("synthetic_report_generation_mismatch")
        return self


class SyntheticEvidenceSnapshot(StrictNumericModel):
    schema_version: Literal["synthetic_numeric_evidence.v1"] = "synthetic_numeric_evidence.v1"
    source_kind: Literal["synthetic"] = "synthetic"
    purpose: Literal["synthetic_software_verification_only"] = "synthetic_software_verification_only"
    clinical_validity_claim: Literal[False] = False
    production_enabled: Literal[False] = False
    standard_evidence_status: Literal["not_requested"] = "not_requested"
    reference_case_status: Literal["not_requested"] = "not_requested"
    batch_id: UUID
    disease_code: Literal["ad", "fatty_liver"]
    source: NumericSourceIdentity
    numeric_input_sha256: Sha
    engineering_source_sha256: Sha

    @field_validator("clinical_validity_claim", "production_enabled", mode="before")
    @classmethod
    def engineering_only(cls, value):
        if value is not False:
            raise ValueError("engineering_only")
        return value


class SyntheticPublication(StrictNumericModel):
    content: str
    prediction_result: dict
    sources: list[dict] = Field(max_length=0)
    evidence_snapshot: dict
    evidence_snapshot_sha256: Sha
    evidence_status: Literal["not_requested"]
    standard_evidence_status: Literal["not_requested"]
    reference_case_status: Literal["not_requested"]
    report_document: SyntheticNumericReportDocument
    report_document_sha256: Sha
    generation_fingerprint: Sha
    generation_fingerprint_version: Literal["v3"] = "v3"

    @model_validator(mode="after")
    def valid_saved_contract(self):
        prediction = SyntheticNumericPrediction.model_validate(self.prediction_result)
        evidence = SyntheticEvidenceSnapshot.model_validate(self.evidence_snapshot)
        document = self.report_document
        if prediction != document.prediction or (
            evidence.batch_id, evidence.disease_code, evidence.source,
            evidence.numeric_input_sha256, evidence.engineering_source_sha256
        ) != (
            document.identity.batch_id, document.identity.disease_code, document.numeric_input.source,
            document.generation_context.numeric_input_sha256,
            document.generation_context.engineering_source_sha256
        ):
            raise ValueError("synthetic_publication_contract_mismatch")
        return self


def parse_report_document(value) -> ReportDocument | SyntheticNumericReportDocument:
    raw = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    if not isinstance(raw, dict):
        raise ValueError("report_document_payload_invalid")
    schema = raw.get("schema_version")
    if schema == "report_document.v1":
        return ReportDocument.model_validate(raw)
    if schema == "synthetic_numeric_report_document.v1":
        return SyntheticNumericReportDocument.model_validate(raw)
    if schema == "numeric_report_document.v1":
        from app.schemas.numeric_report import NumericReportDocument
        return NumericReportDocument.model_validate(raw)
    if schema == "numeric_report_document.v2":
        from app.schemas.numeric_report_v2 import NumericReportDocumentV2
        return NumericReportDocumentV2.model_validate(raw)
    if schema == "numeric_report_document.v3":
        from app.schemas.numeric_report_v3 import NumericReportDocumentV3
        return NumericReportDocumentV3.model_validate(raw)
    raise ValueError("report_document_version_unknown")


def parse_publication(value) -> Publication | SyntheticPublication:
    raw = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    if not isinstance(raw, dict):
        raise ValueError("publication_payload_invalid")
    document = parse_report_document(raw.get("report_document"))
    from app.schemas.numeric_report_v3 import NumericReportDocumentV3, NumericPublicationV3
    if isinstance(document, NumericReportDocumentV3):
        return NumericPublicationV3.model_validate(raw)
    from app.schemas.numeric_report_v2 import NumericReportDocumentV2, NumericPublicationV2
    if isinstance(document, NumericReportDocumentV2):
        return NumericPublicationV2.model_validate(raw)
    from app.schemas.numeric_report import NumericReportDocument, NumericPublication
    if isinstance(document, NumericReportDocument):
        return NumericPublication.model_validate(raw)
    if isinstance(document, SyntheticNumericReportDocument):
        return SyntheticPublication.model_validate(raw)
    return Publication.model_validate(raw)
