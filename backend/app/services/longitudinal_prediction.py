"""Structured longitudinal prediction pipeline; no LLM-generated facts."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.schemas.longitudinal_report import LongitudinalPredictionResult, StageProjection
from app.services.disease_progression import DiseaseProgressionAdapter, predict_indicator_trends
from app.services.longitudinal_features import build_feature_vector, summarize_observation


def _risk_from_registry(visits, registry):
    info = registry.get("outcome") if isinstance(registry, dict) else None
    if not info or info.get("model") is None:
        return None, None
    meta = info.get("meta", {})
    vector = build_feature_vector(visits, meta.get("feature_names", []))
    model = info["model"]
    probabilities = model.predict_proba([vector])[0]
    classes = list(model.classes_)
    score = float(probabilities[classes.index(1)]) if 1 in classes else None
    band = "极高" if score is not None and score >= 0.8 else "高" if score is not None and score >= 0.6 else "中" if score is not None and score >= 0.3 else "低" if score is not None else None
    return score, band


def run_longitudinal_prediction(case: dict[str, Any], visits: list[dict[str, Any]], adapter: DiseaseProgressionAdapter, model_registry: dict[str, Any] | None = None) -> LongitudinalPredictionResult:
    if len(visits) < adapter.minimum_visits:
        raise ValueError(f"至少需要 {adapter.minimum_visits} 次访视")
    observation = summarize_observation(visits)
    registry = model_registry or {}
    score, band = _risk_from_registry(visits, registry)
    stage_info = registry.get("stage") if isinstance(registry, dict) else None
    stage = StageProjection(status="not_estimated")
    if stage_info and stage_info.get("model") is not None:
        stage = StageProjection(status="available", likely_next_stage=stage_info.get("likely_next_stage"), stage_candidates=stage_info.get("stage_candidates", []))
    warnings = [adapter.synthetic_data_warning, "模型分数未校准，不代表临床概率"]
    if not registry.get("outcome") and not registry.get("stage"):
        warnings.append("未加载可用的纵向结局或阶段模型，仅提供观察趋势方向")
    if any(value > 0 for value in observation["missingness_summary"].values()):
        warnings.append("部分指标存在缺失")
    result = LongitudinalPredictionResult(
        disease={"dataset": adapter.dataset, "name": adapter.disease_name},
        observation=observation,
        outcome_prediction={"risk_band": band, "risk_score": score, "stage_projection": stage, "confidence": {"calibration_status": "not_calibrated"}},
        trend_predictions=predict_indicator_trends(visits, adapter, registry.get("trends", {})),
        evidence={}, warnings=warnings,
    )
    return validate_prediction_result(result)


def validate_prediction_result(result: LongitudinalPredictionResult | dict[str, Any]) -> LongitudinalPredictionResult:
    validated = result if isinstance(result, LongitudinalPredictionResult) else LongitudinalPredictionResult.model_validate(result)
    if validated.outcome_prediction.risk_score is not None and not 0 <= validated.outcome_prediction.risk_score <= 1:
        raise ValueError("risk_score 必须位于 0 到 1")
    return validated


def prediction_result_to_dict(result: LongitudinalPredictionResult | dict[str, Any]) -> dict[str, Any]:
    return validate_prediction_result(result).model_dump(mode="json")
