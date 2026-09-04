"""Deterministic, outcome-blind similarity for audited reference windows."""

from __future__ import annotations

from decimal import Decimal
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from app.schemas.longitudinal_evidence import (
    ReferenceCaseFeatureProfile,
    ReferenceCaseProfile,
    ReferenceCaseScoreBreakdown,
    ReferenceCaseSelection,
    ReferenceFeatureComparison,
)


WEIGHTS = MappingProxyType({
    "stage_task": 20, "age": 10, "sex": 5, "indicator_coverage": 15,
    "latest_values": 20, "trend": 20, "span_frequency": 5, "context": 5,
})
AD_STAGE_ORDER = ("normal", "mci", "pre_dementia")
MIN_COVERAGE = Decimal("0.60")
MIN_RANKING_SCORE = Decimal("50")
MAX_RESULTS = 5
MAX_CANDIDATES = 500
OUTCOME_RELIABILITY_RANK = {"low": 0, "medium": 1, "high": 2}


def _indicator_map(profile: ReferenceCaseFeatureProfile) -> Mapping[str, Mapping[str, Any]]:
    value = profile.feature_summary.get("indicators", {})
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _dimension_scores(current: ReferenceCaseFeatureProfile, candidate: ReferenceCaseFeatureProfile) -> dict[str, float | None]:
    scores: dict[str, float | None] = {}
    stage_a, stage_b = current.baseline_stage.casefold(), candidate.baseline_stage.casefold()
    if current.prediction_task != candidate.prediction_task:
        scores["stage_task"] = None
    elif stage_a == stage_b:
        scores["stage_task"] = 1.0
    elif stage_a in AD_STAGE_ORDER and stage_b in AD_STAGE_ORDER and abs(AD_STAGE_ORDER.index(stage_a) - AD_STAGE_ORDER.index(stage_b)) == 1:
        scores["stage_task"] = 0.5
    else:
        scores["stage_task"] = 0.0
    if current.age is None or candidate.age is None:
        scores["age"] = None
    else:
        scores["age"] = max(0.0, 1.0 - abs(current.age - candidate.age) / 20.0)
    scores["sex"] = None if current.sex is None or candidate.sex is None else (1.0 if current.sex == candidate.sex else 0.0)
    current_map, candidate_map = _indicator_map(current), _indicator_map(candidate)
    common = set(current_map) & set(candidate_map)
    scores["indicator_coverage"] = (len(common) / len(current_map)) if current_map else None
    latest: list[float] = []
    trend: list[float] = []
    for name in common:
        left, right = current_map[name], candidate_map[name]
        a, b = _number(left.get("last")), _number(right.get("last"))
        if a is not None and b is not None:
            scale = max(abs(a), abs(b), 1.0)
            latest.append(max(0.0, 1.0 - abs(a - b) / scale))
        sa, sb = _number(left.get("time_slope_per_day")), _number(right.get("time_slope_per_day"))
        if sa is not None and sb is not None:
            scale = max(abs(sa), abs(sb), 0.01)
            trend.append(max(0.0, 1.0 - abs(sa - sb) / scale))
    scores["latest_values"] = sum(latest) / len(latest) if latest else None
    scores["trend"] = sum(trend) / len(trend) if trend else None
    if current.observation_span_days <= 0 or candidate.observation_span_days <= 0:
        scores["span_frequency"] = None
    else:
        span = max(current.observation_span_days, candidate.observation_span_days)
        freq_a = current.visit_count / current.observation_span_days
        freq_b = candidate.visit_count / candidate.observation_span_days
        scores["span_frequency"] = max(0.0, 1.0 - (abs(current.observation_span_days - candidate.observation_span_days) / span + abs(freq_a - freq_b) / max(freq_a, freq_b, 1e-9)) / 2)
    left_context = current.measurement_context_summary.get("values", {}) if isinstance(current.measurement_context_summary, Mapping) else {}
    right_context = candidate.measurement_context_summary.get("values", {}) if isinstance(candidate.measurement_context_summary, Mapping) else {}
    context_keys = set(left_context) & set(right_context)
    scores["context"] = (sum(1.0 if left_context[key] == right_context[key] else 0.0 for key in context_keys) / len(context_keys)) if context_keys else None
    return scores


def score_reference_case(current: ReferenceCaseFeatureProfile, candidate: ReferenceCaseFeatureProfile) -> ReferenceCaseScoreBreakdown:
    scores = _dimension_scores(current, candidate)
    available_weight = sum(weight for key, weight in WEIGHTS.items() if scores.get(key) is not None)
    weighted_sum = sum(WEIGHTS[key] * float(scores[key]) for key in WEIGHTS if scores.get(key) is not None)
    conditional = round(100 * weighted_sum / available_weight, 6) if available_weight else 0.0
    coverage = round(available_weight / 100, 6)
    ranking = round(conditional * coverage, 6)
    return ReferenceCaseScoreBreakdown(
        conditional_similarity=conditional, coverage=coverage, ranking_score=ranking,
        available_weight=available_weight, dimensions={key: round(float(value), 6) for key, value in scores.items() if value is not None},
    )


def _feature_comparisons(
    current: ReferenceCaseFeatureProfile,
    candidate: ReferenceCaseFeatureProfile,
) -> list[ReferenceFeatureComparison]:
    current_map, candidate_map = _indicator_map(current), _indicator_map(candidate)
    comparisons: list[ReferenceFeatureComparison] = []
    for indicator in sorted(set(current_map) | set(candidate_map)):
        if indicator not in current_map or indicator not in candidate_map:
            comparisons.append(ReferenceFeatureComparison(
                indicator=indicator,
                status="excluded",
                reason="indicator_missing_on_one_side",
            ))
            continue
        left = _number(current_map[indicator].get("last"))
        right = _number(candidate_map[indicator].get("last"))
        if left is None or right is None:
            comparisons.append(ReferenceFeatureComparison(
                indicator=indicator,
                status="excluded",
                reason="latest_value_not_comparable",
            ))
            continue
        scale = max(abs(left), abs(right), 1.0)
        comparisons.append(ReferenceFeatureComparison(
            indicator=indicator,
            status="comparable",
            score=max(0.0, 1.0 - abs(left - right) / scale),
        ))
    return comparisons


def rank_reference_cases(current: ReferenceCaseFeatureProfile, candidates: Sequence[ReferenceCaseProfile], limit: int = MAX_RESULTS):
    scored: list[ReferenceCaseProfile] = []
    for candidate in list(candidates)[:MAX_CANDIDATES]:
        if candidate.features.prediction_task != current.prediction_task:
            continue
        score = score_reference_case(current, candidate.features)
        if score.coverage < float(MIN_COVERAGE) or score.ranking_score < float(MIN_RANKING_SCORE):
            continue
        scored.append(candidate.model_copy(update={
            "score": score,
            "comparisons": _feature_comparisons(current, candidate.features),
        }))
    scored.sort(key=lambda item: (-item.score.ranking_score, -item.score.coverage, -OUTCOME_RELIABILITY_RANK[item.outcome_reliability], item.anonymous_case_code, -item.features.as_of.toordinal()))
    return ReferenceCaseSelection(cases=list(scored[: max(0, min(limit, MAX_RESULTS))]))


__all__ = ["WEIGHTS", "score_reference_case", "rank_reference_cases"]
