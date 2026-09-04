"""Deterministic, outcome-blind ``reference_similarity.v1`` scoring."""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from app.schemas.longitudinal_evidence import (
    ReferenceCaseFeatureProfile,
    ReferenceCaseProfile,
    ReferenceCaseScoreBreakdown,
    ReferenceCaseSelection,
    ReferenceFeatureComparison,
)


ALGORITHM_VERSION = "reference_similarity.v1"
WEIGHTS = MappingProxyType({
    "stage_task": 20, "age": 10, "sex": 5, "indicator_coverage": 15,
    "latest_values": 20, "trend": 20, "span_frequency": 5, "context": 5,
})
AD_STAGE_ORDER = ("normal", "mci", "pre_dementia")
CORE_INDICATORS = MappingProxyType({
    "fatty_liver": frozenset({"alt", "ast", "ggt", "tbil", "alb", "plt", "afp", "hba1c", "bmi", "waist"}),
    "ad": frozenset({"mmse", "moca", "cdr", "nfl", "p-tau217", "aβ42/aβ40"}),
})
ALIASES = MappingProxyType({
    "plasma_nfl": "nfl", "plasma_ptau217": "p-tau217", "abeta_ratio": "aβ42/aβ40",
})
SCALE_RANGES = MappingProxyType({"mmse": (0.0, 30.0), "moca": (0.0, 30.0), "cdr": (0.0, 3.0)})
AD_BIOMARKERS = frozenset({"nfl", "p-tau217", "aβ42/aβ40"})
AD_SCALES = frozenset({"mmse", "moca", "cdr"})
BIOMARKER_CONTEXT_KEYS = ("specimen", "assay_platform", "method")
SCALE_CONTEXT_KEYS = ("scale_version", "assessment_language", "education_years", "education_adjusted")
EPSILON = 1e-9
MIN_COVERAGE = Decimal("0.60")
MIN_RANKING_SCORE = Decimal("50")
MAX_RESULTS = 5
MAX_CANDIDATES = 500
OUTCOME_RELIABILITY_RANK = {"low": 0, "medium": 1, "high": 2}

_CONFIG_PAYLOAD = {
    "algorithm_version": ALGORITHM_VERSION,
    "weights": dict(WEIGHTS),
    "ad_stage_order": AD_STAGE_ORDER,
    "core_indicators": {key: sorted(value) for key, value in CORE_INDICATORS.items()},
    "aliases": dict(ALIASES),
    "scale_ranges": dict(SCALE_RANGES),
    "ad_biomarkers": sorted(AD_BIOMARKERS),
    "ad_scales": sorted(AD_SCALES),
    "biomarker_context_keys": BIOMARKER_CONTEXT_KEYS,
    "scale_context_keys": SCALE_CONTEXT_KEYS,
    "epsilon": EPSILON,
    "minimum_coverage": str(MIN_COVERAGE),
    "minimum_ranking_score": str(MIN_RANKING_SCORE),
    "max_results": MAX_RESULTS,
    "max_candidates": MAX_CANDIDATES,
    "formulas": {
        "age": "max(0,1-abs(a-b)/20)",
        "relative": "max(0,1-abs(a-b)/max(abs(a),abs(b),epsilon))",
        "trend": "direction_then_equal_weight_normalized_slope",
        "span_frequency": "mean(min_span/max_span,min_visits/max_visits)",
        "ranking": "conditional_similarity*coverage",
    },
}
SIMILARITY_CONFIG_HASH = hashlib.sha256(json.dumps(
    _CONFIG_PAYLOAD, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
).encode("utf-8")).hexdigest()


def _disease(profile: ReferenceCaseFeatureProfile) -> str:
    return "ad" if profile.prediction_task.startswith("ad.") else "fatty_liver"


def canonical_indicator_name(name: str) -> str:
    normalized = str(name).strip().casefold()
    return ALIASES.get(normalized, normalized)


def _indicator_map(profile: ReferenceCaseFeatureProfile) -> dict[str, Mapping[str, Any]]:
    value = profile.feature_summary.get("indicators", {})
    if not isinstance(value, Mapping):
        return {}
    return {
        canonical_indicator_name(str(key)): item
        for key, item in value.items()
        if isinstance(item, Mapping)
    }


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _ratio(a: float, b: float) -> float:
    high = max(abs(a), abs(b))
    return 1.0 if high <= EPSILON else min(abs(a), abs(b)) / high


def _indicator_context(profile: ReferenceCaseFeatureProfile, indicator: str) -> Mapping[str, Any]:
    summary = profile.measurement_context_summary
    by_indicator = summary.get("by_indicator", {}) if isinstance(summary, Mapping) else {}
    value: Any = {}
    if isinstance(by_indicator, Mapping):
        value = by_indicator.get(indicator, {})
        if not value:
            value = next(
                (item for key, item in by_indicator.items() if canonical_indicator_name(str(key)) == indicator),
                {},
            )
    return value if isinstance(value, Mapping) else {}


def _context_compatible(
    disease: str,
    indicator: str,
    current: ReferenceCaseFeatureProfile,
    candidate: ReferenceCaseFeatureProfile,
) -> tuple[bool, str | None]:
    left, right = _indicator_context(current, indicator), _indicator_context(candidate, indicator)
    required: tuple[str, ...] = ()
    if disease == "ad" and indicator in AD_BIOMARKERS:
        required = BIOMARKER_CONTEXT_KEYS
    elif disease == "ad" and indicator in AD_SCALES:
        required = SCALE_CONTEXT_KEYS
    for key in required:
        if left.get(key) in (None, "") or right.get(key) in (None, ""):
            return False, f"context_missing:{key}"
    keys = set(left) & set(right)
    comparable_keys = set(BIOMARKER_CONTEXT_KEYS) | set(SCALE_CONTEXT_KEYS)
    for key in keys:
        if key in comparable_keys and left.get(key) != right.get(key):
            return False, f"context_mismatch:{key}"
    return True, None


def _comparable_indicators(
    current: ReferenceCaseFeatureProfile,
    candidate: ReferenceCaseFeatureProfile,
) -> tuple[list[str], dict[str, str]]:
    disease = _disease(current)
    left, right = _indicator_map(current), _indicator_map(candidate)
    comparable: list[str] = []
    excluded: dict[str, str] = {}
    for indicator in sorted(set(left) & set(right) & set(CORE_INDICATORS[disease])):
        left_unit = str(left[indicator].get("unit") or "").strip()
        right_unit = str(right[indicator].get("unit") or "").strip()
        if not left_unit or not right_unit:
            excluded[indicator] = "canonical_unit_missing"
            continue
        if left_unit != right_unit:
            excluded[indicator] = "canonical_unit_mismatch"
            continue
        compatible, reason = _context_compatible(disease, indicator, current, candidate)
        if not compatible:
            excluded[indicator] = reason or "measurement_context_incompatible"
            continue
        if _number(left[indicator].get("last")) is None or _number(right[indicator].get("last")) is None:
            excluded[indicator] = "latest_value_not_comparable"
            continue
        comparable.append(indicator)
    return comparable, excluded


def _context_candidates(
    current: ReferenceCaseFeatureProfile,
    candidate: ReferenceCaseFeatureProfile,
) -> list[str]:
    disease = _disease(current)
    left, right = _indicator_map(current), _indicator_map(candidate)
    result = []
    for indicator in sorted(set(left) & set(right) & set(CORE_INDICATORS[disease])):
        left_unit = str(left[indicator].get("unit") or "").strip()
        right_unit = str(right[indicator].get("unit") or "").strip()
        if (
            left_unit and left_unit == right_unit
            and _number(left[indicator].get("last")) is not None
            and _number(right[indicator].get("last")) is not None
        ):
            result.append(indicator)
    return result


def _latest_score(indicator: str, left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    a, b = float(left["last"]), float(right["last"])
    if indicator in SCALE_RANGES:
        low, high = SCALE_RANGES[indicator]
        scale = max(high - low, EPSILON)
    else:
        lower = _number(left.get("lower", left.get("reference_lower")))
        upper = _number(left.get("upper", left.get("reference_upper")))
        if lower is not None and upper is not None:
            scale = max(abs(upper - lower), EPSILON)
        elif lower is not None or upper is not None:
            boundary = lower if lower is not None else upper
            scale = max(abs(boundary or 0.0), 0.1 * max(abs(a), abs(b)), EPSILON)
        else:
            scale = max(abs(a), abs(b), EPSILON)
    return max(0.0, min(1.0, 1.0 - abs(a - b) / scale))


def _trend_score(left: Mapping[str, Any], right: Mapping[str, Any]) -> float | None:
    a, b = _number(left.get("time_slope_per_day")), _number(right.get("time_slope_per_day"))
    if a is None or b is None:
        return None
    direction_a = "stable" if abs(a) <= EPSILON else "rising" if a > 0 else "falling"
    direction_b = "stable" if abs(b) <= EPSILON else "rising" if b > 0 else "falling"
    if direction_a == direction_b == "stable":
        return 1.0
    if direction_a != direction_b:
        return 0.5 if "stable" in {direction_a, direction_b} else 0.0
    slope_closeness = max(0.0, 1.0 - abs(a - b) / max(abs(a), abs(b), EPSILON))
    return (1.0 + slope_closeness) / 2.0


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
    scores["age"] = None if current.age is None or candidate.age is None else max(0.0, 1.0 - abs(current.age - candidate.age) / 20.0)
    scores["sex"] = None if current.sex is None or candidate.sex is None else (1.0 if current.sex == candidate.sex else 0.0)

    disease = _disease(current)
    current_map, candidate_map = _indicator_map(current), _indicator_map(candidate)
    current_core = set(current_map) & set(CORE_INDICATORS[disease])
    comparable, _ = _comparable_indicators(current, candidate)
    scores["indicator_coverage"] = len(comparable) / len(current_core) if current_core else None
    latest = [_latest_score(name, current_map[name], candidate_map[name]) for name in comparable]
    trends = [score for name in comparable if (score := _trend_score(current_map[name], candidate_map[name])) is not None]
    scores["latest_values"] = sum(latest) / len(latest) if latest else None
    scores["trend"] = sum(trends) / len(trends) if trends else None
    if current.observation_span_days <= 0 or candidate.observation_span_days <= 0 or current.visit_count <= 0 or candidate.visit_count <= 0:
        scores["span_frequency"] = None
    else:
        scores["span_frequency"] = (
            _ratio(current.observation_span_days, candidate.observation_span_days)
            + _ratio(current.visit_count, candidate.visit_count)
        ) / 2.0
    context_candidates = _context_candidates(current, candidate)
    scores["context"] = (
        sum(
            1.0 if _context_compatible(disease, name, current, candidate)[0] else 0.0
            for name in context_candidates
        ) / len(context_candidates)
        if context_candidates else None
    )
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
        available_weight=available_weight,
        dimensions={key: round(float(value), 6) for key, value in scores.items() if value is not None},
    )


def _feature_comparisons(current: ReferenceCaseFeatureProfile, candidate: ReferenceCaseFeatureProfile) -> list[ReferenceFeatureComparison]:
    current_map, candidate_map = _indicator_map(current), _indicator_map(candidate)
    comparable, excluded = _comparable_indicators(current, candidate)
    comparisons: list[ReferenceFeatureComparison] = []
    for indicator in sorted(set(current_map) | set(candidate_map)):
        if indicator in comparable:
            comparisons.append(ReferenceFeatureComparison(
                indicator=indicator, status="comparable",
                score=_latest_score(indicator, current_map[indicator], candidate_map[indicator]),
            ))
        else:
            comparisons.append(ReferenceFeatureComparison(
                indicator=indicator, status="excluded",
                reason=excluded.get(indicator, "indicator_missing_or_not_core"),
            ))
    return comparisons


def score_reference_candidates(current: ReferenceCaseFeatureProfile, candidates: Sequence[ReferenceCaseProfile]) -> list[ReferenceCaseProfile]:
    scored: list[ReferenceCaseProfile] = []
    for candidate in list(candidates)[:MAX_CANDIDATES]:
        if candidate.features.prediction_task != current.prediction_task:
            continue
        comparable, _ = _comparable_indicators(current, candidate.features)
        if not comparable:
            continue
        score = score_reference_case(current, candidate.features)
        if score.coverage < float(MIN_COVERAGE) or score.ranking_score < float(MIN_RANKING_SCORE):
            continue
        scored.append(candidate.model_copy(update={
            "score": score,
            "comparisons": _feature_comparisons(current, candidate.features),
        }))
    scored.sort(key=lambda item: (
        -item.score.ranking_score, -item.score.coverage,
        -OUTCOME_RELIABILITY_RANK[item.outcome_reliability],
        item.anonymous_case_code, -item.features.as_of.toordinal(),
    ))
    return scored


def rank_reference_cases(current: ReferenceCaseFeatureProfile, candidates: Sequence[ReferenceCaseProfile], limit: int = MAX_RESULTS) -> ReferenceCaseSelection:
    scored = score_reference_candidates(current, candidates)
    return ReferenceCaseSelection(cases=list(scored[: max(0, min(limit, MAX_RESULTS))]))


__all__ = [
    "ALGORITHM_VERSION", "CORE_INDICATORS", "MAX_CANDIDATES", "MAX_RESULTS",
    "SIMILARITY_CONFIG_HASH", "WEIGHTS", "canonical_indicator_name", "rank_reference_cases",
    "score_reference_candidates", "score_reference_case",
]
