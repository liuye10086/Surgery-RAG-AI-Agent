"""Contracts for operator-owned longitudinal case and visit workflow."""

import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError


def _case(user_id=7, case_id=3, age=65):
    return SimpleNamespace(
        id=case_id,
        user_id=user_id,
        disease_id=11,
        patient_label="case-A",
        sex="female",
        age=age,
        baseline_stage="S1",
        notes="internal note",
        status="active",
        disease=SimpleNamespace(
            id=11,
            code="fatty_liver",
            name="脂肪肝",
            operator_enabled=True,
        ),
        visits=[],
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

    payload = OperatorCaseCreate(
        disease_id=11,
        patient_label="  case-A  ",
        age=65,
        sex="female",
    )
    assert payload.patient_label == "case-A"
    with pytest.raises(ValidationError):
        OperatorCaseCreate(
            disease_id=11,
            patient_label="case-A",
            age=65,
            sex="unknown",
        )


def test_case_age_is_required_strict_integer_and_bounded():
    from app.schemas.longitudinal_case import OperatorCaseCreate

    assert OperatorCaseCreate(disease_id=11, patient_label="case-0", age=0).age == 0
    assert OperatorCaseCreate(disease_id=11, patient_label="case-120", age=120).age == 120
    for age in (-1, 121, 1.5, 65.0, "65", None):
        with pytest.raises(ValidationError):
            OperatorCaseCreate(disease_id=11, patient_label="case-invalid", age=age)


def test_case_update_age_may_be_omitted_but_not_cleared():
    from app.schemas.longitudinal_case import OperatorCaseUpdate

    assert OperatorCaseUpdate(patient_label="renamed").model_dump(exclude_unset=True) == {
        "patient_label": "renamed"
    }
    assert OperatorCaseUpdate(age=0).age == 0
    with pytest.raises(ValidationError):
        OperatorCaseUpdate(age=None)


def test_case_update_rejects_disease_id_even_from_old_client():
    from app.schemas.longitudinal_case import OperatorCaseUpdate

    with pytest.raises(ValidationError):
        OperatorCaseUpdate.model_validate({"disease_id": 12})


def test_case_output_exposes_nested_disease_identity():
    from app.schemas.longitudinal_case import OperatorCaseOut

    output = OperatorCaseOut.model_validate(_case())

    assert output.disease.model_dump() == {
        "id": 11,
        "code": "fatty_liver",
        "name": "脂肪肝",
        "operator_enabled": True,
    }


def test_case_schema_trims_canonical_or_legacy_baseline_stage():
    from app.schemas.longitudinal_case import OperatorCaseCreate

    canonical = OperatorCaseCreate(
        disease_id=11,
        patient_label="case-A",
        age=65,
        baseline_stage="  pre_cirrhosis  ",
    )
    legacy = OperatorCaseCreate(
        disease_id=11,
        patient_label="case-B",
        age=65,
        baseline_stage="  S1  ",
    )
    assert canonical.baseline_stage == "pre_cirrhosis"
    assert legacy.baseline_stage == "S1"


def test_snapshot_contains_sorted_visits_without_user_identity():
    from app.services.longitudinal_case_service import build_input_snapshot

    case = _case(age=0)
    case.user = SimpleNamespace(id=7, real_name="should-not-copy")
    snapshot = build_input_snapshot(case, [_visit("2024-06-01", 2), _visit("2024-01-01")])

    assert [v["visit_date"] for v in snapshot["visits"]] == [
        "2024-01-01",
        "2024-06-01",
    ]
    assert [v["visit_index"] for v in snapshot["visits"]] == [1, 2]
    assert snapshot["age"] == 0
    assert "real_name" not in snapshot
    assert "user_id" not in snapshot


def test_snapshot_contains_stable_disease_code():
    from app.services.longitudinal_case_service import build_input_snapshot

    case = _case()
    case.disease = SimpleNamespace(
        id=11,
        code="fatty_liver",
        name="脂肪肝新名称",
        operator_enabled=True,
    )

    snapshot = build_input_snapshot(case, [])

    assert snapshot["disease_id"] == 11
    assert snapshot["disease"] == "脂肪肝新名称"
    assert snapshot["disease_code"] == "fatty_liver"


def test_create_operator_case_persists_age():
    from app.schemas.longitudinal_case import OperatorCaseCreate
    from app.services.longitudinal_case_service import create_operator_case

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=11,
        code="fatty_liver",
        operator_enabled=True,
    )
    result = create_operator_case(
        db,
        user_id=7,
        payload=OperatorCaseCreate(
            disease_id=11,
            patient_label="case-age",
            age=67,
        ),
    )

    persisted = db.add.call_args.args[0]
    assert result is persisted
    assert persisted.age == 67


def test_create_operator_case_rejects_disabled_disease():
    from app.schemas.longitudinal_case import OperatorCaseCreate
    from app.services.disease_catalog import DiseaseDisabledError
    from app.services.longitudinal_case_service import create_operator_case

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=11,
        code="fatty_liver",
        operator_enabled=False,
    )

    with pytest.raises(DiseaseDisabledError):
        create_operator_case(
            db,
            user_id=7,
            payload=OperatorCaseCreate(
                disease_id=11,
                patient_label="case-disabled",
                age=67,
            ),
        )

    db.add.assert_not_called()


def test_report_generation_rejects_legacy_case_without_age_before_insert():
    from app.api.operator import create_longitudinal_report

    db = MagicMock()
    legacy_case = SimpleNamespace(
        age=None,
        disease=SimpleNamespace(
            id=11,
            code="fatty_liver",
            name="脂肪肝",
            operator_enabled=True,
        ),
        visits=[],
    )
    with patch(
        "app.api.operator.get_operator_case",
        return_value=legacy_case,
    ):
        with pytest.raises(HTTPException) as error:
            asyncio.run(
                create_longitudinal_report(
                    case_id=3,
                    request=None,
                    db=db,
                    current_user=SimpleNamespace(id=7),
                )
            )

    assert error.value.status_code == 422
    assert error.value.detail == "请先补录患者年龄（0–120岁）"
    db.add.assert_not_called()
    db.commit.assert_not_called()


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


@pytest.mark.parametrize(
    "operation_name",
    [
        "update_operator_case",
        "delete_operator_case",
        "add_visit",
        "replace_visits",
        "update_visit",
        "delete_visit",
    ],
)
def test_disabled_disease_blocks_every_case_mutation(operation_name):
    from app.schemas.longitudinal_case import (
        OperatorCaseUpdate,
        VisitCreate,
        VisitUpdate,
    )
    from app.services import longitudinal_case_service as service
    from app.services.disease_catalog import DiseaseDisabledError

    case = _case()
    case.disease.operator_enabled = False
    db = MagicMock()
    arguments = {
        "update_operator_case": (
            db,
            7,
            3,
            OperatorCaseUpdate(patient_label="renamed"),
        ),
        "delete_operator_case": (db, 7, 3),
        "add_visit": (
            db,
            7,
            3,
            VisitCreate(
                visit_date="2024-01-01",
                indicators=[{"name": "ALT", "value": 42, "unit": "U/L"}],
            ),
        ),
        "replace_visits": (db, 7, 3, []),
        "update_visit": (db, 7, 3, 9, VisitUpdate(notes="changed")),
        "delete_visit": (db, 7, 3, 9),
    }

    with patch.object(service, "get_operator_case", return_value=case):
        with pytest.raises(DiseaseDisabledError):
            getattr(service, operation_name)(*arguments[operation_name])

    db.add.assert_not_called()
    db.delete.assert_not_called()
    db.commit.assert_not_called()


def test_visit_schema_limits_timeline_to_ten_rows():
    from app.schemas.longitudinal_case import OperatorCaseCreate, VisitCreate

    assert OperatorCaseCreate.model_fields["patient_label"].is_required()
    assert OperatorCaseCreate.model_fields["age"].is_required()
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
    assert ("/operator/longitudinal-cases/{case_id}/visits", ("PUT",)) in paths
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
