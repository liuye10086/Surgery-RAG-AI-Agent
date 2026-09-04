"""Validated, privacy-bounded context attached to one operator visit."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VisitContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal["lab", "imaging", "assessment", "clinical", "other"] | None = None
    facility_name: str | None = Field(None, max_length=200)
    device_name: str | None = Field(None, max_length=200)
    assay_platform: str | None = Field(None, max_length=200)
    method: str | None = Field(None, max_length=200)
    specimen: str | None = Field(None, max_length=100)
    is_baseline: bool | None = None
    treatment_change: str | None = Field(None, max_length=2000)
    diagnosis_change: str | None = Field(None, max_length=2000)
    scale_version: str | None = Field(None, max_length=100)
    assessment_language: str | None = Field(None, max_length=50)
    education_years: int | None = Field(None, ge=0, le=30, strict=True)
    education_adjusted: bool | None = None
    imaging_type: str | None = Field(None, max_length=100)

    @field_validator(
        "facility_name",
        "device_name",
        "assay_platform",
        "method",
        "specimen",
        "treatment_change",
        "diagnosis_change",
        "scale_version",
        "assessment_language",
        "imaging_type",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value):
        if value is None or not isinstance(value, str):
            return value
        return value.strip() or None
