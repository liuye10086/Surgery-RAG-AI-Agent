"""Domain validation for operator-owned longitudinal cases."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _visit(day: str, *, indicator="ALT", value=42, unit="U/L"):
    return {
        "visit_date": day,
        "indicators": [{"name": indicator, "value": value, "unit": unit}],
        "notes": None,
    }


@pytest.mark.parametrize(
    "stage",
    ["pre_cirrhosis", "suspected_cirrhosis", "cirrhosis", "hcc"],
)
def test_fatty_liver_accepts_all_definite_stable_stages(stage: str):
    from app.services.operator_case_validation import validate_operator_case_profile

    assert validate_operator_case_profile("fatty_liver", 56, "male", stage) == stage


@pytest.mark.parametrize("stage", ["normal", "mci", "pre_dementia", "dementia"])
def test_ad_accepts_all_definite_stable_stages(stage: str):
    from app.services.operator_case_validation import validate_operator_case_profile

    assert validate_operator_case_profile("ad", 72, "female", stage) == stage


@pytest.mark.parametrize(
    ("disease", "stage", "code"),
    [
        ("fatty_liver", "mci", "baseline_stage_disease_conflict"),
        ("ad", "cirrhosis", "baseline_stage_disease_conflict"),
        ("fatty_liver", "脂肪肝", "baseline_stage_stable_code_required"),
        ("ad", None, "baseline_stage_missing"),
    ],
)
def test_profile_rejects_cross_disease_alias_and_missing_stages(
    disease: str, stage, code: str
):
    from app.services.operator_case_validation import (
        OperatorCaseValidationError,
        validate_operator_case_profile,
    )

    with pytest.raises(OperatorCaseValidationError) as caught:
        validate_operator_case_profile(disease, 60, "female", stage)

    assert caught.value.code == code
    assert caught.value.field == "baseline_stage"


@pytest.mark.parametrize(
    ("age", "sex", "field"),
    [
        (None, "male", "age"),
        (True, "male", "age"),
        (121, "male", "age"),
        (60, None, "sex"),
        (60, "unknown", "sex"),
    ],
)
def test_profile_requires_current_complete_age_and_sex(age, sex, field: str):
    from app.services.operator_case_validation import (
        OperatorCaseValidationError,
        validate_operator_case_profile,
    )

    with pytest.raises(OperatorCaseValidationError) as caught:
        validate_operator_case_profile("fatty_liver", age, sex, "pre_cirrhosis")

    assert caught.value.field == field


def test_timeline_sorts_dates_normalizes_indicators_and_assigns_indexes():
    from app.services.operator_case_validation import normalize_operator_timeline

    normalized = normalize_operator_timeline(
        "fatty_liver",
        [_visit("2026-03-01", indicator="AST"), _visit("2026-01-01")],
    )

    assert [item.visit_date for item in normalized] == [
        date(2026, 1, 1),
        date(2026, 3, 1),
    ]
    assert [item.visit_index for item in normalized] == [1, 2]
    assert normalized[0].indicators == (
        {"name": "alt", "value": 42.0, "unit": "U/L"},
    )


@pytest.mark.parametrize(
    ("visits", "code"),
    [
        ([], "visit_count_invalid"),
        ([_visit(f"2026-01-{day:02d}") for day in range(1, 12)], "visit_count_invalid"),
        ([_visit("2026-01-01"), _visit("2026-01-01")], "duplicate_visit_date"),
    ],
)
def test_timeline_rejects_count_and_duplicate_date_invariants(visits, code: str):
    from app.services.operator_case_validation import (
        OperatorCaseValidationError,
        normalize_operator_timeline,
    )

    with pytest.raises(OperatorCaseValidationError) as caught:
        normalize_operator_timeline("fatty_liver", visits)

    assert caught.value.code == code


def test_timeline_wraps_indicator_errors_with_stable_field_location():
    from app.services.operator_case_validation import (
        OperatorCaseValidationError,
        normalize_operator_timeline,
    )

    with pytest.raises(OperatorCaseValidationError) as caught:
        normalize_operator_timeline(
            "fatty_liver",
            [_visit("2026-01-01", indicator="MMSE", value=20, unit="分")],
        )

    assert caught.value.code == "invalid_indicators"
    assert caught.value.field == "visits.0.indicators"


def test_replace_case_visits_in_session_never_commits():
    from app.services.longitudinal_case_service import replace_case_visits_in_session
    from app.services.operator_case_validation import normalize_operator_timeline

    db = MagicMock()
    case = SimpleNamespace(id=3)
    timeline = normalize_operator_timeline("fatty_liver", [_visit("2026-01-01")])

    replace_case_visits_in_session(db, case, timeline)

    db.query.return_value.filter.return_value.delete.assert_called_once_with(
        synchronize_session=False
    )
    persisted = db.add.call_args.args[0]
    assert persisted.case_id == 3
    assert persisted.visit_index == 1
    assert persisted.indicators == [{"name": "alt", "value": 42.0, "unit": "U/L"}]
    db.flush.assert_called_once()
    db.commit.assert_not_called()
    db.rollback.assert_not_called()
