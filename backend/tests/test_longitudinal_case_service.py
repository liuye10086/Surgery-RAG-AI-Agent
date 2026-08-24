"""Contracts for operator-owned longitudinal case and visit workflow."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError


def _case(user_id=7, case_id=3):
    return SimpleNamespace(
        id=case_id,
        user_id=user_id,
        disease_id=11,
        patient_label="case-A",
        sex="female",
        baseline_stage="S1",
        notes="internal note",
        status="active",
        disease=SimpleNamespace(name="脂肪肝"),
    )


def _visit(day, visit_index=1, visit_id=None):
    return SimpleNamespace(
        id=visit_id,
        case_id=3,
        visit_date=date.fromisoformat(day),
        visit_index=visit_index,
        indicators=[{"name": "ALT", "value": 42, "unit": "U/L"}],
        notes=None,
    )


def test_visit_rejects_empty_indicators_and_non_finite_values():
    from app.schemas.longitudinal_case import VisitCreate

    with pytest.raises(ValidationError):
        VisitCreate(visit_date="2024-01-01", indicators=[])
    with pytest.raises(ValidationError):
        VisitCreate(
            visit_date="2024-01-01",
            indicators=[{"name": "ALT", "value": float("nan"), "unit": "U/L"}],
        )


def test_case_schema_normalizes_label_and_validates_sex():
    from app.schemas.longitudinal_case import OperatorCaseCreate

    payload = OperatorCaseCreate(disease_id=11, patient_label="  case-A  ", sex="female")
    assert payload.patient_label == "case-A"
    with pytest.raises(ValidationError):
        OperatorCaseCreate(disease_id=11, patient_label="case-A", sex="unknown")


def test_snapshot_contains_sorted_visits_without_user_identity():
    from app.services.longitudinal_case_service import build_input_snapshot

    case = _case()
    case.user = SimpleNamespace(id=7, real_name="should-not-copy")
    snapshot = build_input_snapshot(case, [_visit("2024-06-01", 2), _visit("2024-01-01")])

    assert [v["visit_date"] for v in snapshot["visits"]] == [
        "2024-01-01",
        "2024-06-01",
    ]
    assert [v["visit_index"] for v in snapshot["visits"]] == [1, 2]
    assert "real_name" not in snapshot
    assert "user_id" not in snapshot


def test_add_visit_rejects_case_owned_by_another_user():
    from app.services.longitudinal_case_service import CaseNotFoundError, add_visit
    from app.schemas.longitudinal_case import VisitCreate

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    with pytest.raises(CaseNotFoundError):
        add_visit(db, user_id=99, case_id=3, payload=VisitCreate(
            visit_date="2024-01-01",
            indicators=[{"name": "ALT", "value": 42, "unit": "U/L"}],
        ))


def test_add_visit_rejects_duplicate_date():
    from app.services.longitudinal_case_service import DuplicateVisitDateError, add_visit
    from app.schemas.longitudinal_case import VisitCreate

    case = _case()
    existing = _visit("2024-01-01", visit_id=9)
    db = MagicMock()
    # First owner lookup, then duplicate-date lookup.
    db.query.return_value.filter.return_value.first.side_effect = [case, existing]
    with pytest.raises(DuplicateVisitDateError):
        add_visit(db, user_id=7, case_id=3, payload=VisitCreate(
            visit_date="2024-01-01",
            indicators=[{"name": "ALT", "value": 42, "unit": "U/L"}],
        ))


def test_visit_schema_limits_timeline_to_ten_rows():
    from app.schemas.longitudinal_case import OperatorCaseCreate, VisitCreate

    assert OperatorCaseCreate.model_fields["patient_label"].is_required()
    with pytest.raises(ValidationError):
        VisitCreate(
            visit_date="2024-01-01",
            indicators=[{"name": "ALT", "value": 42, "unit": "U/L"}],
            notes="x" * 5001,
        )


def test_longitudinal_crud_routes_are_registered_and_protected():
    from app.api.operator import router

    paths = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}
    assert ("/operator/longitudinal-cases", ("POST",)) in paths
    assert ("/operator/longitudinal-cases", ("GET",)) in paths
    assert ("/operator/longitudinal-cases/{case_id}", ("GET",)) in paths
    assert ("/operator/longitudinal-cases/{case_id}/visits", ("POST",)) in paths
    assert (
        "/operator/longitudinal-cases/{case_id}/visits/{visit_id}",
        ("DELETE",),
    ) in paths

    for route in router.routes:
        if route.path.startswith("/operator/longitudinal-cases"):
            dependency_names = {
                getattr(dependency.call, "__name__", "")
                for dependency in route.dependant.dependencies
            }
            assert "require_ai_operator" in dependency_names
