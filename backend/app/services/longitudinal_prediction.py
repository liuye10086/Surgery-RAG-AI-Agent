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
    LoadedDiseaseModelSuite,
    ModelRuntimeStatus,
)
from app.schemas.longitudinal_report import (
    LongitudinalPredictionResult,
    LongitudinalPredictionResultV2,
    LongitudinalPredictionResultV3,
    StageProjection,
)
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


def _suite_status(entry, status: str, reason_code: str) -> ModelRuntimeStatus:
    metadata = entry.metadata
    return ModelRuntimeStatus(
        artifact_type=entry.status.artifact_type,
        task=metadata.task if metadata else entry.status.task,
        status=status,
        reason_code=reason_code,
        lifecycle_status=entry.status.lifecycle_status,
        model_id=metadata.model_contract.model_id if metadata else entry.status.model_id,
        model_name=metadata.model_contract.model_name if metadata else entry.status.model_name,
        model_version=metadata.model_contract.model_version if metadata else entry.status.model_version,
        artifact_sha256=(
            metadata.model_contract.artifact_sha256
            if metadata
            else entry.status.artifact_sha256
        ),
        target=metadata.target if metadata else entry.status.target,
        horizon_days=(
            metadata.horizon.value if metadata else entry.status.horizon_days
        ),
        feature_version=(
            metadata.feature_contract.feature_version
            if metadata
            else entry.status.feature_version
        ),
        score_semantics=(
            metadata.output_contract.score_semantics
            if metadata
            else entry.status.score_semantics
        ),
        calibration_status=(
            metadata.calibration.status
            if metadata
            else entry.status.calibration_status
        ),
    )


def _suite_frame(
    case: dict[str, Any], visits: list[dict[str, Any]], metadata
):
    import pandas as pd

    summary = summarize_observation(visits)
    age = case.get("age")
    fixed = {
        "age": case.get("patient_age") if age is None else age,
        "sex": case.get("sex"),
        "current_stage": case.get("baseline_stage"),
        "visit_count": summary.get("visit_count", len(visits)),
        "observation_span_days": summary.get("observation_span_days", 0),
        "days_since_previous_visit": summary.get("days_since_previous_visit", 0),
    }
    indicators = summary.get("indicators") or {}
    values = {}
    for name in metadata.feature_contract.feature_names:
        if name in fixed:
            values[name] = fixed[name]
            continue
        try:
            indicator, statistic = name.rsplit(".", 1)
        except ValueError:
            values[name] = None
            continue
        values[name] = (indicators.get(indicator) or {}).get(statistic)
    return pd.DataFrame([values], columns=metadata.feature_contract.feature_names)


def _run_suite_outcome(route, entry, case, visits) -> OutcomeInferenceResult:
    if route.routing_status != "selected" or route.task is None:
        return OutcomeInferenceResult(
            _suite_status(entry, "disabled", route.reason_code)
        )
    if (
        entry.metadata is None
        or entry.model is None
        or entry.status.status != "available"
    ):
        return OutcomeInferenceResult(entry.status)
    if entry.metadata.task != route.task:
        return OutcomeInferenceResult(
            _suite_status(entry, "incompatible", "task_mismatch")
        )
    if len(visits) < 3:
        return OutcomeInferenceResult(
            _suite_status(entry, "disabled", "insufficient_visits")
        )
    try:
        probabilities = entry.model.predict_proba(
            _suite_frame(case, visits, entry.metadata)
        )
        classes = list(getattr(entry.model, "classes_", []))
        positive = entry.metadata.output_contract.positive_class
        if positive in classes:
            index = classes.index(positive)
        elif 1 in classes:
            index = classes.index(1)
        else:
            index = 1
        score = float(probabilities[0][index])
    except Exception:
        return OutcomeInferenceResult(
            _suite_status(entry, "incompatible", "prediction_failed")
        )
    if not math.isfinite(score) or not 0 <= score <= 1:
        return OutcomeInferenceResult(
            _suite_status(entry, "incompatible", "prediction_score_invalid")
        )
    threshold = entry.metadata.output_contract.threshold or 0.5
    return OutcomeInferenceResult(entry.status, score, _risk_band(score, threshold))


def _stage_order(adapter: DiseaseProgressionAdapter) -> tuple[str, ...]:
    if adapter.dataset == "fatty_liver":
        return ("pre_cirrhosis", "cirrhosis", "hcc")
    return tuple(adapter.stage_order)


def _stage_value(label: str) -> str:
    value = label[5:] if label.startswith("stay_") else label
    return "pre_cirrhosis" if value == "fatty_liver" else value


def _monotonic_stage_projection(
    adapter: DiseaseProgressionAdapter,
    current_stage: object,
    likely: str,
    candidates: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    order = _stage_order(adapter)
    current = _stage_value(str(current_stage or order[0]))
    if current not in order:
        current = order[0]
    current_rank = order.index(current)
    allowed = [
        item
        for item in candidates
        if _stage_value(str(item.get("stage", ""))) in order
        and order.index(_stage_value(str(item["stage"]))) >= current_rank
    ]
    likely_stage = _stage_value(likely)
    if likely_stage in order and order.index(likely_stage) >= current_rank:
        normalized_likely = (
            f"stay_{current}"
            if likely_stage == current and not likely.startswith("stay_")
            else likely
        )
        return normalized_likely, allowed
    if allowed:
        return str(allowed[0]["stage"]), allowed
    return f"stay_{current}", allowed


def _run_suite_stage(entry, case, visits, adapter: DiseaseProgressionAdapter):
    if (
        entry.metadata is None
        or entry.model is None
        or entry.status.status != "available"
    ):
        return StageProjection(status="not_estimated"), entry.status
    try:
        frame = _suite_frame(case, visits, entry.metadata)
        likely = str(entry.model.predict(frame)[0])
        candidates = []
        if callable(getattr(entry.model, "predict_proba", None)):
            probabilities = entry.model.predict_proba(frame)[0]
            classes = list(getattr(entry.model, "classes_", []))
            if len(classes) == len(probabilities):
                candidates = [
                    {"stage": str(stage), "model_score": float(score)}
                    for stage, score in sorted(
                        zip(classes, probabilities),
                        key=lambda item: float(item[1]),
                        reverse=True,
                    )
                ]
        likely, candidates = _monotonic_stage_projection(
            adapter,
            case.get("baseline_stage"),
            likely,
            candidates,
        )
        return (
            StageProjection(
                status="available",
                likely_next_stage=likely,
                stage_candidates=candidates,
            ),
            entry.status,
        )
    except Exception:
        return (
            StageProjection(status="not_estimated"),
            _suite_status(entry, "incompatible", "prediction_failed"),
        )


def _run_suite_trend(indicator, entry, case, visits, observation):
    observed = observation.get("indicators", {}).get(indicator, {})
    if (
        entry.metadata is None
        or entry.model is None
        or entry.status.status != "available"
    ):
        return {
            "indicator": indicator,
            "observed": observed,
            "reference": {},
            "forecast": {
                "direction": None,
                "status": "not_available",
                "window": "next_followup",
                "projected_value": None,
                "prediction_interval": None,
                "basis": None,
            },
            "importance": {},
            "model_status": entry.status,
        }
    try:
        direction = str(
            entry.model.predict(_suite_frame(case, visits, entry.metadata))[0]
        )
        if direction not in {"rising", "stable", "falling"}:
            raise ValueError("invalid direction")
        status = entry.status
        forecast_status = "direction_only"
        basis = "next_visit_trend_model"
    except Exception:
        direction = None
        status = _suite_status(entry, "incompatible", "prediction_failed")
        forecast_status = "not_available"
        basis = None
    return {
        "indicator": indicator,
        "observed": observed,
        "reference": {},
        "forecast": {
            "direction": direction,
            "status": forecast_status,
            "window": "next_followup",
            "projected_value": None,
            "prediction_interval": None,
            "basis": basis,
        },
        "importance": {},
        "model_status": status,
    }


def _run_suite_prediction(
    case,
    visits,
    adapter,
    suite: LoadedDiseaseModelSuite,
    standard_sources,
):
    observation = summarize_observation(visits)
    route = route_outcome_task(adapter.dataset, case.get("baseline_stage"))
    if route.routing_status == "selected" and route.task is not None:
        entry = suite.outcomes.get(route.task)
        if entry is None:
            outcome_status = ModelRuntimeStatus(
                artifact_type="outcome",
                task=route.task,
                status="missing",
                reason_code="release_set_task_missing",
            )
            outcome_result = OutcomeInferenceResult(outcome_status)
            outcome_feature_names = None
        else:
            outcome_result = _run_suite_outcome(route, entry, case, visits)
            outcome_status = outcome_result.status
            outcome_feature_names = (
                entry.metadata.feature_contract.feature_names
                if entry.metadata
                else None
            )
    else:
        outcome_result = OutcomeInferenceResult(_routing_status(route))
        outcome_status = outcome_result.status
        outcome_feature_names = None
    stage_projection, stage_status = _run_suite_stage(
        suite.stage, case, visits, adapter
    )
    trend_predictions = [
        _run_suite_trend(indicator, entry, case, visits, observation)
        for indicator, entry in sorted(suite.trends.items())
    ]
    available_trends = [
        item["model_status"]
        for item in trend_predictions
        if item["model_status"].status == "available"
    ]
    trend_status = (
        available_trends[0]
        if available_trends
        else ModelRuntimeStatus(
            artifact_type="trend",
            status="incompatible",
            reason_code="trend_models_unavailable",
        )
    )
    progression_signals = interpret_observation_signals(
        dataset=adapter.dataset,
        visits=visits,
        standard_sources=standard_sources,
        outcome_status=outcome_status,
        feature_names=outcome_feature_names,
    )
    warnings = [adapter.synthetic_data_warning]
    if (
        outcome_result.risk_score is not None
        and outcome_status.calibration_status == "not_calibrated"
    ):
        warnings.append("模型分数未校准，不代表临床概率")
    return LongitudinalPredictionResultV3(
        disease={"dataset": adapter.dataset, "name": adapter.disease_name},
        release_set={
            "dataset": suite.dataset,
            "release_set_id": suite.release_set_id,
            "release_set_sha256": suite.release_set_sha256,
            "data_release_id": suite.data_release_id,
            "split_sha256": suite.split_sha256,
        },
        observation=observation,
        outcome_prediction={
            "risk_band": outcome_result.risk_band,
            "risk_score": outcome_result.risk_score,
            "stage_projection": stage_projection,
            "confidence": {
                "calibration_status": outcome_status.calibration_status
            },
        },
        trend_predictions=trend_predictions,
        model_status={
            "outcome": outcome_status,
            "stage": stage_status,
            "trend": trend_status,
        },
        progression_signals=progression_signals,
        evidence={},
        warnings=warnings,
    )


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
    model_registry: LoadedDiseaseModelSuite | LongitudinalModelRegistry | dict[str, Any] | None = None,
    *,
    standard_sources: list[dict[str, Any]] | None = None,
) -> LongitudinalPredictionResult:
    if isinstance(model_registry, LoadedDiseaseModelSuite):
        return _run_suite_prediction(
            case,
            visits,
            adapter,
            model_registry,
            standard_sources,
        )
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
    result = LongitudinalPredictionResultV2(
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
    if isinstance(result, (LongitudinalPredictionResultV2, LongitudinalPredictionResultV3)):
        validated = result
    elif isinstance(result, dict) and result.get("schema_version") == "longitudinal_prediction.v3":
        validated = LongitudinalPredictionResultV3.model_validate(result)
    else:
        validated = LongitudinalPredictionResultV2.model_validate(result)
    if validated.outcome_prediction.risk_score is not None and not 0 <= validated.outcome_prediction.risk_score <= 1:
        raise ValueError("risk_score 必须位于 0 到 1")
    return validated


def prediction_result_to_dict(result: LongitudinalPredictionResult | dict[str, Any]) -> dict[str, Any]:
    return validate_prediction_result(result).model_dump(mode="json")
