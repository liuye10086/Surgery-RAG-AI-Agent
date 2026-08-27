"""Structured longitudinal prediction pipeline; no LLM-generated facts."""

from __future__ import annotations

from datetime import date
from dataclasses import dataclass
import math
from typing import Any

from app.schemas.longitudinal_model_registry import (
    BaselineStageRoute,
    LoadedModelEntry,
    LongitudinalModelRegistry,
    ModelRuntimeStatus,
)
from app.schemas.longitudinal_report import LongitudinalPredictionResult, StageProjection
from app.services.disease_progression import DiseaseProgressionAdapter, predict_indicator_trends
from app.services.longitudinal_features import (
    InferenceContractError,
    build_feature_vector,
    build_fixed_window_inference_features,
    summarize_observation,
)
from app.services.longitudinal_model_registry import empty_optional_model_status
from app.services.longitudinal_signal_interpreter import interpret_observation_signals
from app.services.longitudinal_task_routing import route_outcome_task


@dataclass(frozen=True)
class OutcomeInferenceResult:
    status: ModelRuntimeStatus
    risk_score: float | None = None
    risk_band: str | None = None


def _inference_status(
    entry: LoadedModelEntry,
    status: str,
    reason_code: str,
) -> ModelRuntimeStatus:
    metadata = entry.metadata
    return ModelRuntimeStatus(
        artifact_type="outcome",
        task=metadata.task if metadata else entry.status.task,
        status=status,
        reason_code=reason_code,
        lifecycle_status=entry.status.lifecycle_status,
        model_id=metadata.model_contract.model_id if metadata else None,
        model_name=metadata.model_contract.model_name if metadata else None,
        model_version=metadata.model_contract.model_version if metadata else None,
        artifact_sha256=metadata.model_contract.artifact_sha256 if metadata else None,
        target=metadata.target if metadata else None,
        horizon_days=metadata.horizon_days if metadata else None,
        feature_version=metadata.feature_contract.feature_version if metadata else None,
        score_semantics=metadata.score_contract.semantics if metadata else None,
        calibration_status=metadata.calibration.status if metadata else None,
    )


def _risk_band(score: float, threshold: float) -> str:
    if score >= 0.8:
        return "极高"
    if score >= threshold:
        return "高"
    if score >= 0.3:
        return "中"
    return "低"


def _run_outcome_model(
    route: BaselineStageRoute,
    entry: LoadedModelEntry,
    case: dict[str, Any],
    visits: list[dict[str, Any]],
) -> OutcomeInferenceResult:
    if route.routing_status != "selected" or route.task is None:
        return OutcomeInferenceResult(
            _inference_status(entry, "disabled", route.reason_code)
        )
    if entry.metadata is None or entry.model is None or entry.status.status != "available":
        reason = entry.status.reason_code
        if entry.metadata is not None and entry.metadata.task != route.task:
            reason = "task_mismatch"
        return OutcomeInferenceResult(
            _inference_status(entry, entry.status.status, reason)
        )
    metadata = entry.metadata
    if metadata.task != route.task or entry.status.task != route.task:
        return OutcomeInferenceResult(
            _inference_status(entry, "incompatible", "task_mismatch")
        )
    if len(visits) < 3:
        return OutcomeInferenceResult(
            _inference_status(entry, "disabled", "insufficient_visits")
        )
    try:
        frame = build_fixed_window_inference_features(case, visits, metadata)
    except InferenceContractError as error:
        return OutcomeInferenceResult(
            _inference_status(entry, "incompatible", error.code)
        )
    try:
        probabilities = entry.model.predict_proba(frame)
        classes = list(entry.model.classes_)
        positive_index = classes.index(metadata.score_contract.positive_class)
        score = float(probabilities[0][positive_index])
    except Exception:
        return OutcomeInferenceResult(
            _inference_status(entry, "incompatible", "prediction_failed")
        )
    if not math.isfinite(score) or not (
        metadata.score_contract.minimum
        <= score
        <= metadata.score_contract.maximum
    ):
        return OutcomeInferenceResult(
            _inference_status(entry, "incompatible", "prediction_score_invalid")
        )
    return OutcomeInferenceResult(
        status=entry.status,
        risk_score=score,
        risk_band=_risk_band(score, metadata.score_contract.threshold),
    )


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


def _empty_registry(dataset: str) -> LongitudinalModelRegistry:
    from app.schemas.longitudinal_model_registry import TASK_CONTRACTS

    outcomes = {
        task: LoadedModelEntry(
            status=ModelRuntimeStatus(
                artifact_type="outcome",
                task=task,
                status="missing",
                reason_code="release_record_missing",
            )
        )
        for task, contract in TASK_CONTRACTS.items()
        if contract.dataset == dataset
    }
    return LongitudinalModelRegistry(
        dataset=dataset,
        outcomes=outcomes,
        stage=empty_optional_model_status("stage", "stage_model_missing"),
        trend=empty_optional_model_status("trend", "trend_model_missing"),
    )


def _registry_v2(dataset: str, value: Any) -> LongitudinalModelRegistry:
    if isinstance(value, LongitudinalModelRegistry):
        return value
    return _empty_registry(dataset)


def _routing_status(route: BaselineStageRoute) -> ModelRuntimeStatus:
    return ModelRuntimeStatus(
        artifact_type="outcome",
        task=route.task,
        status="disabled",
        reason_code=route.reason_code,
    )


def run_longitudinal_prediction(
    case: dict[str, Any],
    visits: list[dict[str, Any]],
    adapter: DiseaseProgressionAdapter,
    model_registry: LongitudinalModelRegistry | dict[str, Any] | None = None,
    *,
    standard_sources: list[dict[str, Any]] | None = None,
) -> LongitudinalPredictionResult:
    observation = summarize_observation(visits)
    registry = _registry_v2(adapter.dataset, model_registry)
    route = route_outcome_task(adapter.dataset, case.get("baseline_stage"))
    if route.routing_status == "selected" and route.task is not None:
        entry = registry.outcomes[route.task]
        outcome_result = _run_outcome_model(route, entry, case, visits)
        outcome_status = outcome_result.status
        score = outcome_result.risk_score
        band = outcome_result.risk_band
        outcome_feature_names = (
            entry.metadata.feature_contract.feature_names if entry.metadata else None
        )
    else:
        outcome_status = _routing_status(route)
        score = band = None
        outcome_feature_names = None
    progression_signals = interpret_observation_signals(
        dataset=adapter.dataset,
        visits=visits,
        standard_sources=standard_sources,
        outcome_status=outcome_status,
        feature_names=outcome_feature_names,
    )
    stage = StageProjection(status="not_estimated")
    warnings = [adapter.synthetic_data_warning]
    if score is not None and outcome_status.calibration_status == "not_calibrated":
        warnings.append("模型分数未校准，不代表临床概率")
    if outcome_status.status != "available":
        warnings.append("未来365天结局模型未参与本次推理")
    if any(value > 0 for value in observation["missingness_summary"].values()):
        warnings.append("部分指标存在缺失")
    result = LongitudinalPredictionResult(
        disease={"dataset": adapter.dataset, "name": adapter.disease_name},
        observation=observation,
        outcome_prediction={"risk_band": band, "risk_score": score, "stage_projection": stage, "confidence": {"calibration_status": outcome_status.calibration_status}},
        trend_predictions=[],
        model_status={
            "outcome": outcome_status,
            "stage": registry.stage,
            "trend": registry.trend,
        },
        progression_signals=progression_signals,
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
