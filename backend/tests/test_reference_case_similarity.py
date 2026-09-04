from datetime import date

from app.schemas.longitudinal_evidence import ReferenceCaseFeatureProfile, ReferenceCaseProfile, ReferenceCaseScoreBreakdown
from app.services.reference_case_similarity import (
    SIMILARITY_CONFIG_HASH,
    rank_reference_cases,
    score_reference_case,
)


def _features(*, sex="female", task="progression", stage="mci", alt_last=22, include_context=True):
    return ReferenceCaseFeatureProfile(
        baseline_stage=stage, prediction_task=task, age=60, sex=sex, as_of=date(2025, 6, 1),
        visit_count=3, observation_span_days=151,
        feature_summary={"indicators": {"alt": {"last": alt_last, "unit": "U/L", "time_slope_per_day": 0.01, "n_observations": 3}}},
        measurement_context_summary={"values": {"assay_platform": ["A"]}} if include_context else {},
    )


def test_ranking_score_penalizes_missing_dimensions():
    current = _features()
    candidate = _features(sex=None)
    scored = score_reference_case(current, candidate)
    assert scored.available_weight == 95
    assert scored.coverage == 0.95
    assert scored.ranking_score == round(scored.conditional_similarity * 0.95, 6)


def test_outcome_is_not_an_input_to_similarity():
    current = _features()
    assert score_reference_case(current, _features()) == score_reference_case(current, _features(alt_last=22))


def test_ties_use_stable_privacy_safe_order():
    current = _features()
    base = ReferenceCaseScoreBreakdown(conditional_similarity=0, coverage=0, ranking_score=0, available_weight=0)
    candidates = [
        ReferenceCaseProfile(anonymous_case_code=code, features=_features(), score=base, outcome_status="unknown", outcome_source="explicit_cirrhosis", outcome_reliability="high")
        for code in ("CASE-ABCD-2345", "CASE-ABCD-2346")
    ]
    selected = rank_reference_cases(current, list(reversed(candidates)))
    assert [item.anonymous_case_code for item in selected.cases] == ["CASE-ABCD-2345", "CASE-ABCD-2346"]
    assert selected.cases[0].comparisons[0].indicator == "alt"
    assert selected.cases[0].comparisons[0].status == "comparable"


def test_unit_mismatch_excludes_indicator_and_fails_core_gate():
    current = _features()
    candidate = _features()
    candidate = candidate.model_copy(update={
        "feature_summary": {"indicators": {"alt": {"last": 22, "unit": "mg/L", "time_slope_per_day": 0.01}}},
    })
    base = ReferenceCaseScoreBreakdown(conditional_similarity=0, coverage=0, ranking_score=0, available_weight=0)
    profile = ReferenceCaseProfile(
        anonymous_case_code="CASE-ABCD-2345", features=candidate, score=base,
        outcome_status="unknown", outcome_source="explicit_cirrhosis", outcome_reliability="high",
    )

    selected = rank_reference_cases(current, [profile])

    assert selected.cases == []


def test_span_frequency_uses_span_and_visit_count_ratios():
    current = _features().model_copy(update={"visit_count": 4, "observation_span_days": 100})
    candidate = _features().model_copy(update={"visit_count": 2, "observation_span_days": 200})

    score = score_reference_case(current, candidate)

    assert score.dimensions["span_frequency"] == 0.5


def test_latest_value_uses_approved_two_sided_range_width_when_supplied():
    current = _features(alt_last=40).model_copy(update={
        "feature_summary": {"indicators": {
            "alt": {
                "last": 40, "unit": "U/L", "time_slope_per_day": 0.01,
                "lower": 10, "upper": 50,
            }
        }},
    })
    candidate = _features(alt_last=20)

    score = score_reference_case(current, candidate)

    assert score.dimensions["latest_values"] == 0.5


def test_ad_scale_range_and_required_context_are_enforced():
    context = {
        "by_indicator": {
            "mmse": {
                "scale_version": "MMSE-30", "assessment_language": "zh-CN",
                "education_years": 12, "education_adjusted": True,
            }
        }
    }
    current = ReferenceCaseFeatureProfile(
        baseline_stage="mci", prediction_task="ad.pre_dementia_to_dementia",
        age=60, sex="female", as_of=date(2025, 6, 1), visit_count=3,
        observation_span_days=151,
        feature_summary={"indicators": {"mmse": {"last": 30, "unit": "分", "time_slope_per_day": -0.01}}},
        measurement_context_summary=context,
    )
    candidate = current.model_copy(update={
        "feature_summary": {"indicators": {"mmse": {"last": 15, "unit": "分", "time_slope_per_day": -0.01}}},
    })
    score = score_reference_case(current, candidate)
    assert score.dimensions["latest_values"] == 0.5

    incompatible = candidate.model_copy(update={"measurement_context_summary": {}})
    incompatible_score = score_reference_case(current, incompatible)
    assert "latest_values" not in incompatible_score.dimensions


def test_non_core_overlap_does_not_pass_reference_selection():
    current = _features().model_copy(update={
        "feature_summary": {"indicators": {"crp": {"last": 2, "unit": "mg/L"}}},
    })
    candidate = current.model_copy()
    base = ReferenceCaseScoreBreakdown(conditional_similarity=0, coverage=0, ranking_score=0, available_weight=0)
    profile = ReferenceCaseProfile(
        anonymous_case_code="CASE-ABCD-2345", features=candidate, score=base,
        outcome_status="unknown", outcome_source="explicit_cirrhosis", outcome_reliability="high",
    )
    assert rank_reference_cases(current, [profile]).cases == []


def test_similarity_configuration_has_versioned_sha256_identity():
    assert len(SIMILARITY_CONFIG_HASH) == 64
    assert SIMILARITY_CONFIG_HASH.islower()
