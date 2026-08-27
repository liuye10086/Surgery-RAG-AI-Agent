"""Validated structured result contract for longitudinal predictions."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.longitudinal_model_registry import ModelRuntimeStatus


class StageProjection(BaseModel):
    status: Literal["available", "not_estimated"]
    likely_next_stage: str | None = None
    stage_candidates: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def no_guess_when_unavailable(self):
        if self.status == "not_estimated" and (self.likely_next_stage or self.stage_candidates):
            raise ValueError("不可用阶段模型不能输出阶段猜测")
        return self


class OutcomePrediction(BaseModel):
    risk_band: str | None = None
    risk_score: float | None = None
    score_semantics: Literal["model_score"] = "model_score"
    stage_projection: StageProjection
    confidence: dict[str, Any] = Field(default_factory=dict)


class TrendForecast(BaseModel):
    direction: str | None = None
    status: Literal["direction_only", "not_estimable", "not_available"]
    window: str = "next_followup"
    projected_value: float | None = None
    prediction_interval: list[float] | None = None
    basis: str | None = None

    @model_validator(mode="after")
    def direction_only_has_no_value(self):
        if self.status == "direction_only" and (self.projected_value is not None or self.prediction_interval is not None):
            raise ValueError("direction_only 不能携带未来数值")
        return self


class TrendPrediction(BaseModel):
    indicator: str
    unit: str | None = None
    observed: dict[str, Any] = Field(default_factory=dict)
    reference: dict[str, Any] = Field(default_factory=dict)
    forecast: TrendForecast
    importance: dict[str, Any] = Field(default_factory=dict)


class PredictionModelStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: ModelRuntimeStatus
    stage: ModelRuntimeStatus
    trend: ModelRuntimeStatus


class LongitudinalSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator: str
    display_name: str
    unit: str | None = None
    first_value: float | None = None
    latest_value: float | None = None
    absolute_change: float | None = None
    relative_change: float | None = None
    observation_count: int = Field(ge=0)
    observation_span_days: int = Field(ge=0)
    observed_direction: Literal["rising", "falling", "stable", "unavailable"]
    disease_attention_direction: Literal["rising", "falling", "none"]
    reference_status: Literal[
        "within_range",
        "above_range",
        "below_range",
        "unit_missing",
        "unit_conflict",
        "unsupported_unit",
        "reference_unavailable",
        "reference_not_applicable",
    ]
    reference_rule_id: int | None = None
    reference_version_id: int | None = None
    attention_level: Literal["none", "attention", "priority"]
    reason_codes: list[str] = Field(default_factory=list)
    used_by_outcome_model: bool = False
    model_feature_names: list[str] = Field(default_factory=list)
    model_contribution_status: Literal["not_supported", "unavailable"]
    model_contribution: None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)


class SignalInterpretationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["longitudinal_signal_interpretation.v1"] = (
        "longitudinal_signal_interpretation.v1"
    )
    signals: list[LongitudinalSignal] = Field(default_factory=list)
    omitted_indicators: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class LongitudinalPredictionResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["longitudinal_prediction.v1"] = "longitudinal_prediction.v1"
    disease: dict[str, Any]
    observation: dict[str, Any]
    outcome_prediction: OutcomePrediction
    trend_predictions: list[TrendPrediction] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class LongitudinalPredictionResultV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["longitudinal_prediction.v2"] = "longitudinal_prediction.v2"
    disease: dict[str, Any]
    observation: dict[str, Any]
    outcome_prediction: OutcomePrediction
    trend_predictions: list[TrendPrediction] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    model_status: PredictionModelStatus
    progression_signals: SignalInterpretationResult = Field(
        default_factory=SignalInterpretationResult
    )

    @model_validator(mode="after")
    def unavailable_models_have_no_predictions(self):
        if self.model_status.outcome.status != "available" and (
            self.outcome_prediction.risk_score is not None
            or self.outcome_prediction.risk_band is not None
        ):
            raise ValueError("不可用 outcome 模型不能输出风险结果")
        stage = self.outcome_prediction.stage_projection
        if self.model_status.stage.status != "available" and (
            stage.likely_next_stage is not None or stage.stage_candidates
        ):
            raise ValueError("不可用 stage 模型不能输出阶段猜测")
        if self.model_status.trend.status != "available" and self.trend_predictions:
            raise ValueError("不可用 trend 模型不能输出未来趋势")
        return self


LongitudinalPredictionResult = LongitudinalPredictionResultV2


class LongitudinalReportRequest(BaseModel):
    model_options: dict[str, Any] = Field(default_factory=dict)
