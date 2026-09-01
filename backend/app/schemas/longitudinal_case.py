"""Pydantic contracts for operator-owned longitudinal cases."""

import math
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class IndicatorValue(BaseModel):
    """One measured indicator in a visit."""

    name: str = Field(..., min_length=1, max_length=100)
    value: float
    unit: str = Field(..., min_length=1, max_length=50)

    @field_validator("name", "unit", mode="before")
    @classmethod
    def normalize_text(cls, value):
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            raise ValueError("指标名称和单位不能为空")
        return value

    @field_validator("value")
    @classmethod
    def require_finite_value(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("指标值必须是有限数字")
        return value


class OperatorCaseCreate(BaseModel):
    disease_id: int = Field(..., gt=0)
    patient_label: str = Field(..., min_length=1, max_length=100)
    age: int = Field(..., ge=0, le=120, strict=True)
    sex: str | None = Field(None, pattern=r"^(male|female)$")
    baseline_stage: str | None = Field(None, max_length=100)
    notes: str | None = Field(None, max_length=5000)

    @field_validator("patient_label", "baseline_stage", mode="before")
    @classmethod
    def normalize_optional_text(cls, value):
        if value is None:
            return value
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value and cls.__name__ == "OperatorCaseCreate":
            raise ValueError("文本字段不能为空")
        return value


class OperatorCaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_label: str | None = Field(None, min_length=1, max_length=100)
    age: int | None = Field(None, ge=0, le=120, strict=True)
    sex: str | None = Field(None, pattern=r"^(male|female)$")
    baseline_stage: str | None = Field(None, max_length=100)
    notes: str | None = Field(None, max_length=5000)
    status: str | None = Field(None, pattern=r"^(active|archived)$")

    @field_validator("patient_label", "baseline_stage", "notes", "status", mode="before")
    @classmethod
    def normalize_update_text(cls, value):
        if value is None:
            return value
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value and cls.__name__ == "OperatorCaseUpdate":
            raise ValueError("文本字段不能为空")
        return value

    @model_validator(mode="after")
    def reject_explicit_null_age(self):
        if "age" in self.model_fields_set and self.age is None:
            raise ValueError("年龄不能置空")
        return self


class VisitCreate(BaseModel):
    visit_date: date
    indicators: list[IndicatorValue] = Field(..., min_length=1, max_length=30)
    notes: str | None = Field(None, max_length=5000)

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value):
        if value is None:
            return value
        if not isinstance(value, str):
            return value
        return value.strip() or None


class VisitUpdate(BaseModel):
    visit_date: date | None = None
    indicators: list[IndicatorValue] | None = Field(None, min_length=1, max_length=30)
    notes: str | None = Field(None, max_length=5000)

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value):
        if value is None:
            return value
        if not isinstance(value, str):
            return value
        return value.strip() or None


class VisitReplaceRequest(BaseModel):
    """Complete timeline submitted by the editor in one atomic operation."""

    visits: list[VisitCreate] = Field(default_factory=list, max_length=10)


class VisitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int
    visit_date: date
    visit_index: int
    indicators: list[IndicatorValue]
    notes: str | None = None
    created_at: datetime | None = None


class OperatorCaseDiseaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    operator_enabled: bool


class OperatorCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    disease_id: int
    patient_label: str
    age: int | None = None
    sex: str | None = None
    baseline_stage: str | None = None
    notes: str | None = None
    status: str
    visits: list[VisitOut] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    disease: OperatorCaseDiseaseOut


class OperatorCaseListOut(BaseModel):
    cases: list[OperatorCaseOut]
    total: int
