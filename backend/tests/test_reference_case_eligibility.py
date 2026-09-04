import pytest

from app.services.reference_case_eligibility import (
    ReferenceEligibilityCandidate,
    evaluate_reference_candidate,
)


@pytest.fixture
def valid_candidate():
    return ReferenceEligibilityCandidate(
        disease_code="fatty_liver", expected_disease_code="fatty_liver",
        dataset_release_id="fatty-2026", expected_release_id="fatty-2026",
        is_synthetic=False, anonymous_case_code="CASE-ABCD-2345", visit_count=3,
        source_trace={"source": "registry", "row_id": "r1"},
        outcome_source="explicit_cirrhosis", outcome_reliability="high",
        task_compatible=True, timeline_valid=True,
    )


@pytest.mark.parametrize(("change", "reason"), [
    ({"is_synthetic": True}, "synthetic_source"),
    ({"anonymous_case_code": None}, "anonymous_code_missing"),
    ({"anonymous_case_code": "P151"}, "anonymous_code_invalid"),
    ({"outcome_source": "generated_stage_assignment"}, "outcome_source_not_allowed"),
    ({"source_trace": {}}, "source_trace_missing"),
])
def test_reference_candidate_is_excluded_by_one_stable_reason(valid_candidate, change, reason):
    decision = evaluate_reference_candidate(valid_candidate.model_copy(update=change))
    assert decision.eligible is False
    assert reason in decision.reasons


def test_reference_candidate_reasons_are_deterministically_ordered(valid_candidate):
    candidate = valid_candidate.model_copy(update={"is_synthetic": True, "visit_count": 1, "task_compatible": False})
    decision = evaluate_reference_candidate(candidate)
    assert decision.reasons[:3] == ("synthetic_source", "insufficient_visits", "task_incompatible")

