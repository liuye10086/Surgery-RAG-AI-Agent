"""AI 操作者预测分析相关 Pydantic Schema。"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class DiseaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class DiseaseUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None


class DiseaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str] = None
    case_count: int = 0
    created_at: datetime


class IndicatorInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    value: float
    unit: str = Field(..., min_length=1, max_length=50)


class PredictRequest(BaseModel):
    disease_id: int
    indicators: list[IndicatorInput] = Field(..., min_length=1, max_length=30)
    patient_summary: Optional[str] = Field(None, max_length=2000)


class CaseRecordIn(BaseModel):
    disease_id: int
    patient_label: Optional[str] = Field(None, max_length=100)
    indicators: list[IndicatorInput] = Field(..., min_length=1, max_length=30)
    confirmed: bool = True
    metadata: dict = Field(default_factory=dict)


class CaseRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    disease_id: int
    patient_label: Optional[str]
    indicators: list[dict]
    confirmed: bool
    # ORM 属性是 case_metadata（DB 列 metadata），用 validation_alias 桥接，
    # 响应 JSON 键名仍为 metadata，前端无需感知。
    metadata: dict = Field(default_factory=dict, validation_alias="case_metadata")
    created_at: datetime


class ReferenceRangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    indicator_name: str
    name_cn: Optional[str]
    unit: Optional[str]
    lower: Optional[float]
    upper: Optional[float]
    # 暴露 inclusive，前端才能区分 "<21" 与 "≤21" 的展示
    lower_inclusive: bool = True
    upper_inclusive: bool = True
    category: Optional[str]
    document_id: Optional[int]


class ReferenceRangeSyncIn(BaseModel):
    document_id: int
