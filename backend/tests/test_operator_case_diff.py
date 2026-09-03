"""Deterministic, minimal operator-case change diff contracts."""

from datetime import date
from types import SimpleNamespace


def _indicator(name="ALT", value=42, unit="U/L"):
    return {"name": name, "value": value, "unit": unit}


def _visit(
    day="2026-01-01",
    *,
    indicators=None,
    notes=None,
    visit_context=None,
    row_id=1,
    index=1,
):
    return SimpleNamespace(
        id=row_id,
        visit_date=date.fromisoformat(day),
        visit_index=index,
        indicators=indicators or [_indicator()],
        notes=notes,
        visit_context=visit_context or {},
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
            "notes": {"changed": True},
        }
    }
    assert "复查" not in str(changes)
    assert classify_case_action(changes) == "profile_updated"


def test_timeline_diff_is_redacted_to_counts_fields_and_hash():
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
                "notes": "敏感复查内容 9876",
                "visit_context": {"facility_name": "敏感医院"},
            },
            {
                "visit_date": "2026-03-01",
                "indicators": [_indicator("AST", 31)],
                "notes": None,
            },
        ]
    )

    changes = build_case_diff(case, _profile(), submitted)

    timeline = changes["timeline"]
    assert timeline["added_count"] == 1
    assert timeline["removed_count"] == 1
    assert timeline["updated_fields"] == ["notes", "visit_context"]
    assert len(timeline["timeline_sha256"]) == 64
    assert set(timeline) == {
        "added_count",
        "removed_count",
        "updated_fields",
        "timeline_sha256",
    }

    import json

    serialized = json.dumps(timeline, ensure_ascii=False)
    for forbidden in ("9876", "敏感医院", "2026-01-01", "2026-02-01", "2026-03-01", "42"):
        assert forbidden not in serialized
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
