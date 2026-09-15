"""Pydantic contracts for operator-owned longitudinal cases."""

import math
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.operator_case_status import OperatorCaseStatus
from app.schemas.operator_visit_context import VisitContext


class IndicatorValue(BaseModel):
    """One measured indicator in a visit."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=100)
    value: float | None = None
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
    def require_finite_value(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value):
            raise ValueError("指标值必须是有限数字")
        return value


class OperatorCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disease_id: int = Field(..., gt=0)
    age: int = Field(..., ge=0, le=120, strict=True)
    sex: Literal["male", "female"]
    baseline_stage: str = Field(..., min_length=1, max_length=100)
    notes: str | None = Field(None, max_length=5000)
    visits: list["VisitCreate"] = Field(..., min_length=1, max_length=10)

    @field_validator("baseline_stage", mode="before")
    @classmethod
    def normalize_required_text(cls, value):
        if not isinstance(value, str):
            return value
        return value.strip()

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value):
        if value is None or not isinstance(value, str):
            return value
        return value.strip() or None


class OperatorCaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    age: int | None = Field(None, ge=0, le=120, strict=True)
    sex: str | None = Field(None, pattern=r"^(male|female)$")
    baseline_stage: str | None = Field(None, max_length=100)
    notes: str | None = Field(None, max_length=5000)

    @field_validator("baseline_stage", "notes", mode="before")
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
    model_config = ConfigDict(extra="forbid")

    visit_date: date
    indicators: list[IndicatorValue] = Field(..., min_length=1, max_length=30)
    notes: str | None = Field(None, max_length=5000)
    visit_context: VisitContext = Field(default_factory=VisitContext)

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value):
        if value is None:
            return value
        if not isinstance(value, str):
            return value
        return value.strip() or None


OperatorCaseCreate.model_rebuild()


class VisitUpdate(BaseModel):
    visit_date: date | None = None
    indicators: list[IndicatorValue] | None = Field(None, min_length=1, max_length=30)
    notes: str | None = Field(None, max_length=5000)
    visit_context: VisitContext | None = None

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

    visits: list[VisitCreate] = Field(default_factory=list, min_length=1, max_length=10)


class VisitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int
    visit_date: date
    visit_index: int
    indicators: list[IndicatorValue]
    notes: str | None = None
    visit_context: VisitContext = Field(default_factory=VisitContext)
    created_at: datetime | None = None


class OperatorCaseDiseaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    operator_enabled: bool


class EngineeringCaseCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verified: bool
    input_readonly: Literal[True] = True
    report_kind: Literal["synthetic_numeric"] | None
    enabled: bool


class PredictionCaseCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verified: bool
    input_readonly: Literal[True] = True
    report_kind: Literal["numeric_prediction"] | None
    enabled: bool


class OperatorCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    disease_id: int
    anonymous_case_code: str | None = None
    age: int | None = None
    sex: str | None = None
    baseline_stage: str | None = None
    notes: str | None = None
    status: OperatorCaseStatus
    visits: list[VisitOut] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    disease: OperatorCaseDiseaseOut
    engineering: EngineeringCaseCapability | None = None
    prediction: PredictionCaseCapability | None = None

    @model_validator(mode="before")
    @classmethod
    def project_engineering_capability(cls, value):
        if isinstance(value, cls):
            return value
        source = value.get("engineering_source") if isinstance(value, dict) else getattr(value, "engineering_source", None)
        data = ({key: item for key, item in value.items() if key in cls.model_fields}
                if isinstance(value, dict) else
                {key: getattr(value, key) for key in cls.model_fields if key != "engineering" and hasattr(value, key)})
        data["engineering"] = None
        data["prediction"] = None
        prediction_source = value.get("prediction_source") if isinstance(value, dict) else getattr(value, "prediction_source", None)
        if prediction_source is not None or source is not None:
            from app.core.config import settings
            from app.services.prediction_case_source import validate_prediction_case
            verified = False
            try:
                validate_prediction_case(value)
                verified = True
            except (ValueError, TypeError, AttributeError, KeyError):
                pass
            data["prediction"] = dict(verified=verified, input_readonly=True,
                report_kind="numeric_prediction" if verified else None,
                enabled=bool(verified and settings.NUMERIC_REPORTS_ENABLED
                             and settings.REPORT_JOBS_ENABLED and settings.REPORT_JOBS_ACCEPTING))
        if source is not None:
            from app.core.config import settings
            from app.services.synthetic_case_source import validate_engineering_case
            verified = False
            try:
                validate_engineering_case(value)
                verified = True
            except (ValueError, TypeError, AttributeError, KeyError):
                pass
            data["engineering"] = dict(verified=verified, input_readonly=True,
                report_kind="synthetic_numeric" if verified else None,
                enabled=bool(verified and settings.SYNTHETIC_REPORTS_ENABLED
                             and settings.REPORT_JOBS_ENABLED and settings.REPORT_JOBS_ACCEPTING))
        return data


class OperatorCaseListOut(BaseModel):
    cases: list[OperatorCaseOut]
    total: int
    skip: int
    limit: int
