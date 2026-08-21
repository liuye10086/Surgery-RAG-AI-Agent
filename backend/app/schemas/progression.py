"""Schemas for longitudinal progression prediction."""

from datetime import date

from pydantic import BaseModel, Field

from app.schemas.prediction import IndicatorInput


class VisitInput(BaseModel):
    visit_date: date
    indicators: list[IndicatorInput] = Field(..., min_length=1, max_length=30)


class LongitudinalPredictRequest(BaseModel):
    disease_id: int
    visits: list[VisitInput] = Field(..., min_length=1, max_length=10)


class ProgressionFeatureSummary(BaseModel):
    indicator: str
    first: float
    last: float
    slope: float | None
    rises_count: int


class ProgressionModelMeta(BaseModel):
    trained_on: int
    cv_auc_mean: float
    cv_auc_std: float


class ProgressionPredictionOut(BaseModel):
    risk_band: str
    risk_score: float
    feature_summary: list[ProgressionFeatureSummary]
    model_meta: ProgressionModelMeta
    disclaimer: str
    model_caveat: str
