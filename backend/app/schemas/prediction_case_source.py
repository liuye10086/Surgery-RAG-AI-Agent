"""Server-owned case binding and explicit filesystem package format."""

from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.numeric_prediction import NumericInput, PredictionPacketSource, PredictionSource
from app.schemas.synthetic_numeric_prediction import Identifier, Sha, StrictNumericModel
from app.schemas.synthetic_case_source import PackageFile


class PredictionCaseSource(PredictionSource):
    schema_version: Literal['prediction_case_source.v1'] = 'prediction_case_source.v1'
    case_id: int = Field(gt=0, strict=True)
    user_id: int = Field(gt=0, strict=True)
    disease_id: int = Field(gt=0, strict=True)
    disease_code: Literal['ad', 'fatty_liver']
    subject_id: Identifier
    numeric_input: NumericInput
    numeric_input_sha256: Sha
    display_projection_sha256: Sha

    @model_validator(mode='after')
    def same_input_source(self):
        if self.model_dump(include=set(PredictionSource.model_fields)) != self.numeric_input.source.model_dump():
            raise ValueError('prediction_source_identity_mismatch')
        if (self.disease_code, self.subject_id) != (self.numeric_input.disease_code, self.numeric_input.subject_id):
            raise ValueError('prediction_source_subject_mismatch')
        return self


class PredictionPackageManifest(StrictNumericModel):
    schema_version: Literal['prediction_case_package.v1']
    source: PredictionPacketSource
    records: PackageFile
    record_count: int = Field(gt=0, strict=True)
    clinical_validity_claim: Literal[False]

    @field_validator('clinical_validity_claim', mode='before')
    @classmethod
    def explicitly_nonclinical(cls, value):
        if value is not False:
            raise ValueError('clinical_validity_not_established')
        return value


class PredictionPackageRecord(StrictNumericModel):
    age: int = Field(ge=0, le=120, strict=True)
    sex: Literal['male', 'female']
    baseline_stage: Identifier
    numeric_input: dict
