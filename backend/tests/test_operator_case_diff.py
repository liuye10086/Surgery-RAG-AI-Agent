"""Deterministic, minimal operator-case change diff contracts."""

from datetime import date
from types import SimpleNamespace


def _indicator(name="ALT", value=42, unit="U/L"):
    return {"name": name, "value": value, "unit": unit}


def _visit(day="2026-01-01", *, indicators=None, notes=None, row_id=1, index=1):
    return SimpleNamespace(
        id=row_id,
        visit_date=date.fromisoformat(day),
        visit_index=index,
        indicators=indicators or [_indicator()],
        notes=notes,
    )


def _case(*, age=56, sex="male", stage="pre_cirrhosis", notes=None, visits=None):
    return SimpleNamespace(
        id=3,
        user_id=7,
        patient_label="private-legacy-label",
        anonymous_case_code="CASE-2345-6789",
        age=age,
        sex=sex,
        baseline_stage=stage,
        notes=notes,
        visits=visits or [_visit()],
    )


def _profile(**overrides):
    values = {
        "age": 56,
        "sex": "male",
        "baseline_stage": "pre_cirrhosis",
        "notes": None,
    }
    values.update(overrides)
    return values


def _normalized(visits):
    from app.services.operator_case_validation import normalize_operator_timeline

    return normalize_operator_timeline("fatty_liver", visits)


def test_noop_diff_ignores_derived_indexes_row_ids_and_indicator_order():
    from app.services.operator_case_diff import build_case_diff

    case = _case(
        visits=[
            _visit(
                indicators=[_indicator("AST", 30), _indicator("ALT", 42)],
                row_id=99,
                index=8,
            )
        ]
    )
    submitted = _normalized(
        [
            {
                "visit_date": "2026-01-01",
                "indicators": [_indicator("ALT", 42), _indicator("AST", 30)],
            }
        ]
    )

    assert build_case_diff(case, _profile(), submitted) == {}


def test_profile_diff_contains_only_changed_fields():
    from app.services.operator_case_diff import build_case_diff, classify_case_action

    changes = build_case_diff(_case(), _profile(age=57, notes="复查"), _normalized([_visit()]))

    assert changes == {
        "profile": {
            "age": {"before": 56, "after": 57},
            "notes": {"before": None, "after": "复查"},
        }
    }
    assert classify_case_action(changes) == "profile_updated"


def test_timeline_diff_has_stable_added_removed_and_updated_sections():
    from app.services.operator_case_diff import build_case_diff, classify_case_action

    case = _case(
        visits=[
            _visit("2026-01-01", notes=None),
            _visit("2026-02-01", row_id=2, index=2),
        ]
    )
    submitted = _normalized(
        [
            {
                "visit_date": "2026-01-01",
                "indicators": [_indicator()],
                "notes": "复查",
            },
            {
                "visit_date": "2026-03-01",
                "indicators": [_indicator("AST", 31)],
                "notes": None,
            },
        ]
    )

    changes = build_case_diff(case, _profile(), submitted)

    assert changes["timeline"]["added"] == [
        {
            "visit_date": "2026-03-01",
            "indicators": [{"name": "ast", "value": 31.0, "unit": "U/L"}],
            "notes": None,
        }
    ]
    assert changes["timeline"]["removed"] == [
        {
            "visit_date": "2026-02-01",
            "indicators": [{"name": "alt", "value": 42.0, "unit": "U/L"}],
            "notes": None,
        }
    ]
    assert changes["timeline"]["updated"] == [
        {
            "visit_date": "2026-01-01",
            "fields": {"notes": {"before": None, "after": "复查"}},
        }
    ]
    assert classify_case_action(changes) == "timeline_updated"


def test_combined_action_and_diff_never_expose_identity_or_orm_ids():
    import json

    from app.services.operator_case_diff import build_case_diff, classify_case_action

    changes = build_case_diff(
        _case(),
        _profile(sex="female"),
        _normalized([{"visit_date": "2026-04-01", "indicators": [_indicator()]}]),
    )
    serialized = json.dumps(changes, ensure_ascii=False)

    assert classify_case_action(changes) == "case_updated"
    for forbidden in ("patient_label", "user_id", "anonymous_case_code", '"id"', "visit_index"):
        assert forbidden not in serialized
