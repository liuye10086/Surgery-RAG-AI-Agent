"""Versioned numeric publication facts; source provenance stays in saved metadata."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import Field, field_validator, model_validator
from app.schemas.synthetic_numeric_prediction import StrictNumericModel, Sha, CalendarDate
from app.schemas.numeric_prediction import NumericInput, NumericPrediction, NumericAlgorithm, PredictionSource

class NumericGenerationContext(StrictNumericModel):
    schema_version: Literal["numeric_generation_context.v1"] = "numeric_generation_context.v1"
    disease_code: Literal["ad", "fatty_liver"]
    numeric_input_sha256: Sha
    source_binding_sha256: Sha
    algorithm: NumericAlgorithm
    template_version: Literal["numeric_report.zh-CN.v1"] = "numeric_report.zh-CN.v1"


class NumericReportIdentity(StrictNumericModel):
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


class NumericReportDocument(StrictNumericModel):
    schema_version: Literal["numeric_report_document.v1"] = "numeric_report_document.v1"
    template_version: Literal["numeric_report.zh-CN.v1"] = "numeric_report.zh-CN.v1"
    identity: NumericReportIdentity
    generation_context: NumericGenerationContext
    numeric_input: NumericInput
    prediction: NumericPrediction

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


class NumericEvidenceSnapshot(StrictNumericModel):
    schema_version: Literal["numeric_evidence.v1"] = "numeric_evidence.v1"
    clinical_validity_claim: Literal[False] = False
    production_enabled: Literal[False] = False
    standard_evidence_status: Literal["not_requested"] = "not_requested"
    reference_case_status: Literal["not_requested"] = "not_requested"
    batch_id: UUID
    disease_code: Literal["ad", "fatty_liver"]
    source: PredictionSource
    numeric_input_sha256: Sha
    source_binding_sha256: Sha

    @field_validator("clinical_validity_claim", "production_enabled", mode="before")
    @classmethod
    def engineering_only(cls, value):
        if value is not False:
            raise ValueError("engineering_only")
        return value


class NumericPublication(StrictNumericModel):
    content: str
    prediction_result: dict
    sources: list[dict] = Field(max_length=0)
    evidence_snapshot: dict
    evidence_snapshot_sha256: Sha
    evidence_status: Literal["not_requested"]
    standard_evidence_status: Literal["not_requested"]
    reference_case_status: Literal["not_requested"]
    report_document: NumericReportDocument
    report_document_sha256: Sha
    generation_fingerprint: Sha
    generation_fingerprint_version: Literal["v4"] = "v4"

    @model_validator(mode="after")
    def valid_saved_contract(self):
        prediction = NumericPrediction.model_validate(self.prediction_result)
        evidence = NumericEvidenceSnapshot.model_validate(self.evidence_snapshot)
        document = self.report_document
        if prediction != document.prediction or (
            evidence.batch_id, evidence.disease_code, evidence.source,
            evidence.numeric_input_sha256, evidence.source_binding_sha256
        ) != (
            document.identity.batch_id, document.identity.disease_code, document.numeric_input.source,
            document.generation_context.numeric_input_sha256,
            document.generation_context.source_binding_sha256
        ):
            raise ValueError("synthetic_publication_contract_mismatch")
        return self
