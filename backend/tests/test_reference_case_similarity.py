from datetime import date

from app.schemas.longitudinal_evidence import ReferenceCaseFeatureProfile, ReferenceCaseProfile, ReferenceCaseScoreBreakdown
from app.services.reference_case_similarity import rank_reference_cases, score_reference_case


def _features(*, sex="female", task="progression", stage="mci", alt_last=22, include_context=True):
    return ReferenceCaseFeatureProfile(
        baseline_stage=stage, prediction_task=task, age=60, sex=sex, as_of=date(2025, 6, 1),
        visit_count=3, observation_span_days=151,
        feature_summary={"indicators": {"alt": {"last": alt_last, "time_slope_per_day": 0.01, "n_observations": 3}}},
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

