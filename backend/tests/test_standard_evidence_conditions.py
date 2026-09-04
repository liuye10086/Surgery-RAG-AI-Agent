import pytest


def test_required_means_present_and_not_literal_required():
    from app.services.standard_evidence import adapt_v1_applicability, evaluate_condition

    node = adapt_v1_applicability({"platform": "required"})
    decision = evaluate_condition(node, {"assay_platform": "Roche cobas"})
    assert decision.status == "matched"


def test_missing_and_mismatched_conditions_are_distinct():
    from app.services.standard_evidence import adapt_v1_applicability, evaluate_condition

    node = adapt_v1_applicability({"sex": "female", "education": "required"})
    missing = evaluate_condition(node, {"sex": "female"})
    mismatched = evaluate_condition(node, {"sex": "male", "education_years": 12})
    assert missing.status == "missing"
    assert "education" in missing.missing
    assert mismatched.status == "mismatched"
    assert "sex" in mismatched.mismatched


@pytest.mark.parametrize(
    ("value", "context", "expected"),
    [
        ({"sex": ["female", "male"]}, {"sex": "female"}, "matched"),
        ({"age": {"min": 18, "max": 65}}, {"age": 40}, "matched"),
        ({"age": {"min": 18, "max": 65}}, {"age": 70}, "mismatched"),
        ({"all": [{"sex": "female"}, {"age": {"min": 18}}]}, {"sex": "female", "age": 20}, "matched"),
    ],
)
def test_v1_adapter_supports_collection_and_range_predicates(value, context, expected):
    from app.services.standard_evidence import adapt_v1_applicability, evaluate_condition

    decision = evaluate_condition(adapt_v1_applicability(value), context)
    assert decision.status == expected


def test_latest_indicator_uses_its_own_visit_context():
    from app.services.standard_evidence import build_indicator_contexts

    contexts = build_indicator_contexts(
        {"age": 67, "sex": "female", "baseline_stage": "mci", "disease_code": "ad"},
        [
            {
                "visit_date": "2025-01-01",
                "visit_context": {"assay_platform": "A"},
                "indicators": [{"name": "nfl", "value": 20, "unit": "pg/mL"}],
            },
            {
                "visit_date": "2025-06-01",
                "visit_context": {"assay_platform": "B"},
                "indicators": [{"name": "mmse", "value": 24, "unit": "分"}],
            },
        ],
    )
    assert contexts["nfl"].assay_platform == "A"
    assert contexts["mmse"].assay_platform == "B"
