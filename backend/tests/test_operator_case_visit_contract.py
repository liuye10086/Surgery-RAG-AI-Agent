import pytest


def test_empty_numeric_input_is_rejected_with_stable_field_path():
    from app.services.operator_case_validation import (
        OperatorCaseValidationError,
        normalize_operator_timeline,
    )

    with pytest.raises(OperatorCaseValidationError) as caught:
        normalize_operator_timeline(
            "fatty_liver",
            [
                {
                    "visit_date": "2026-01-01",
                    "indicators": [{"name": "ALT", "value": None, "unit": "U/L"}],
                }
            ],
        )
    assert caught.value.field == "visits.0.indicators.0.value"


def test_indicator_alias_and_unit_alias_are_canonicalized():
    from app.services.operator_case_validation import normalize_operator_timeline

    visits = normalize_operator_timeline(
        "fatty_liver",
        [
            {
                "visit_date": "2026-01-01",
                "indicators": [{"name": "谷丙转氨酶", "value": 42, "unit": "u/l"}],
                "visit_context": {"source_type": "lab"},
            }
        ],
    )
    assert visits[0].indicators[0] == {
        "name": "alt",
        "value": 42.0,
        "unit": "U/L",
    }
    assert visits[0].visit_context == {"source_type": "lab"}


def test_duplicate_aliases_are_rejected_after_canonicalization():
    from app.services.operator_case_validation import (
        OperatorCaseValidationError,
        normalize_operator_timeline,
    )

    with pytest.raises(OperatorCaseValidationError, match="重复"):
        normalize_operator_timeline(
            "fatty_liver",
            [
                {
                    "visit_date": "2026-01-01",
                    "indicators": [
                        {"name": "ALT", "value": 42, "unit": "U/L"},
                        {"name": "谷丙转氨酶", "value": 43, "unit": "U/L"},
                    ],
                }
            ],
        )
