"""Persisted engineering source binding; hashes establish integrity, not authentication."""

from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.synthetic_numeric_prediction import (
    Identifier, NumericSourceIdentity, Sha, StrictNumericModel, SyntheticNumericInput,
)
from app.schemas.synthetic_prediction_cases import GenerationConfig


class SyntheticCaseSource(NumericSourceIdentity):
    schema_version: Literal['synthetic_case_source.v1'] = 'synthetic_case_source.v1'
    case_id: int = Field(gt=0, strict=True)
    user_id: int = Field(gt=0, strict=True)
    disease_id: int = Field(gt=0, strict=True)
    disease_code: Literal['ad', 'fatty_liver']
    subject_id: Identifier
    numeric_input: SyntheticNumericInput
    numeric_input_sha256: Sha
    display_projection_sha256: Sha

    @model_validator(mode='after')
    def same_input_source(self):
        source_fields = set(NumericSourceIdentity.model_fields)
        if self.model_dump(include=source_fields) != self.numeric_input.source.model_dump():
            raise ValueError('engineering_source_identity_mismatch')
        if (self.disease_code, self.subject_id) != (self.numeric_input.disease_code, self.numeric_input.subject_id):
            raise ValueError('engineering_source_subject_mismatch')
        return self


class PackageFile(StrictNumericModel):
    bytes: int = Field(ge=0, strict=True)
    sha256: Sha


class SyntheticPackageManifest(StrictNumericModel):
    schema_version: Literal['synthetic_prediction_cases.v1']
    generator_version: Literal['synthetic-prediction.v1']
    code_version: Identifier
    runtime: dict[str, str]
    run_id: Identifier
    run_identity_sha256: Sha
    config: GenerationConfig
    source_sha256: dict[str, Sha]
    files: dict[str, PackageFile]
    data_content_sha256: Sha
    counts: dict[str, int]
    quality_status: Literal['passed', 'failed', 'not_assessable']
    clinical_validity_claim: Literal[False]
    purpose: Literal['synthetic_software_verification_only']
    clinical_thresholds: None
    clinical_followup_tolerance: None
    created_at: Identifier

    @field_validator('clinical_validity_claim', mode='before')
    @classmethod
    def explicitly_nonclinical(cls, value):
        if value is not False:
            raise ValueError('engineering_only')
        return value
