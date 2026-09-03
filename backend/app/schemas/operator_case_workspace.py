"""Request and readiness contracts for the operator case workspace."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.longitudinal_case import VisitCreate


class OperatorCaseSave(BaseModel):
    """A complete editable case snapshot saved in one transaction."""

    model_config = ConfigDict(extra="forbid")

    age: int = Field(..., ge=0, le=120, strict=True)
    sex: Literal["male", "female"]
    baseline_stage: str = Field(..., min_length=1, max_length=100)
    notes: str | None = Field(None, max_length=5000)
    visits: list[VisitCreate] = Field(..., min_length=1, max_length=10)
    change_reason: str | None = Field(None, max_length=500)

    @field_validator("baseline_stage", mode="before")
    @classmethod
    def normalize_stage(cls, value):
        if not isinstance(value, str):
            return value
        return value.strip()

    @field_validator("notes", "change_reason", mode="before")
    @classmethod
    def normalize_optional_text(cls, value):
        if value is None or not isinstance(value, str):
            return value
        return value.strip() or None


class OperatorCaseReadinessBlocker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=500)


class OperatorCaseReportReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ready: bool
    case_ready: bool
    timeline_ready: bool
    model_ready: bool
    visit_count: int = Field(..., ge=0)
    minimum_visits: int | None = Field(None, ge=1)
    blockers: list[OperatorCaseReadinessBlocker] = Field(default_factory=list)
