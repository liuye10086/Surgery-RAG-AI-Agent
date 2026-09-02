"""Focused contracts for visit numbering and visit-count integrity."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError


def _visit_payload(day: str):
    return {
        "visit_date": day,
        "indicators": [{"name": "ALT", "value": 42, "unit": "U/L"}],
    }


def test_appendix5_replace_visits_requires_at_least_one_visit():
    from app.schemas.longitudinal_case import VisitReplaceRequest

    with pytest.raises(ValidationError):
        VisitReplaceRequest(visits=[])


def test_appendix5_replace_visits_accepts_ten_but_rejects_eleven():
    from app.schemas.longitudinal_case import VisitReplaceRequest

    ten = [_visit_payload(f"2026-01-{day:02d}") for day in range(1, 11)]
    assert len(VisitReplaceRequest(visits=ten).visits) == 10
    with pytest.raises(ValidationError):
        VisitReplaceRequest(visits=ten + [_visit_payload("2026-02-01")])


def test_appendix5_case_create_requires_initial_visit():
    from app.schemas.longitudinal_case import OperatorCaseCreate

    with pytest.raises(ValidationError):
        OperatorCaseCreate(disease_id=11, patient_label="case", age=65)


def test_appendix5_case_create_persists_initial_visits_atomically():
    from app.schemas.longitudinal_case import OperatorCaseCreate
    from app.services.longitudinal_case_service import create_operator_case

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=11, code="fatty_liver", operator_enabled=True
    )
    payload = OperatorCaseCreate(
        disease_id=11,
        patient_label="case",
        age=65,
        visits=[_visit_payload("2026-01-01")],
    )

    result = create_operator_case(db, user_id=7, payload=payload)

    assert result is db.add.call_args_list[0].args[0]
    persisted_visit = db.add.call_args_list[1].args[0]
    assert persisted_visit.case is result
    assert persisted_visit.visit_index == 1


def test_appendix4_visit_output_exposes_integer_server_index_only():
    from app.schemas.longitudinal_case import VisitOut

    visit = SimpleNamespace(
        id=1,
        case_id=2,
        visit_date=date(2026, 1, 1),
        visit_index=1,
        indicators=[{"name": "ALT", "value": 42, "unit": "U/L"}],
        notes=None,
        created_at=None,
    )
    output = VisitOut.model_validate(visit)
    assert output.visit_index == 1
    assert isinstance(output.visit_index, int)


def test_appendix4_client_payload_with_visit_index_is_forbidden_by_replace_schema():
    from app.schemas.longitudinal_case import VisitReplaceRequest

    payload = {"visits": [{**_visit_payload("2026-01-01"), "visit_index": 99}]}
    request = VisitReplaceRequest.model_validate(payload)
    assert "visit_index" not in request.visits[0].model_dump()


def test_appendix4_orm_declares_positive_and_unique_visit_index_constraints():
    from app.db.models import OperatorCaseVisit

    constraints = {constraint.name: constraint for constraint in OperatorCaseVisit.__table__.constraints}
    assert "ck_operator_case_visits_visit_index_positive" in constraints
    assert "uq_operator_case_visits_case_id_visit_index" in constraints
    assert str(constraints["ck_operator_case_visits_visit_index_positive"].sqltext) == "visit_index >= 1"


def test_appendix5_service_rejects_empty_replacement():
    from app.services import longitudinal_case_service as service

    db = MagicMock()
    case = SimpleNamespace(status="active", disease=SimpleNamespace(operator_enabled=True), visits=[])
    with patch.object(service, "get_operator_case_for_write", return_value=case):
        with pytest.raises(service.VisitLimitError, match="至少"):
            service.replace_visits(db, user_id=7, case_id=3, payloads=[])


def test_appendix5_service_rejects_deleting_the_only_visit():
    from app.services import longitudinal_case_service as service

    db = MagicMock()
    only_visit = SimpleNamespace(id=9, case_id=3, visit_date="2026-01-01")
    case = SimpleNamespace(status="active", disease=SimpleNamespace(operator_enabled=True), visits=[only_visit])
    with patch.object(service, "_owned_visit_query", return_value=(case, only_visit)):
        with pytest.raises(service.VisitLimitError, match="至少"):
            service.delete_visit(db, user_id=7, case_id=3, visit_id=9)
    db.delete.assert_not_called()


def test_reindex_visits_uses_two_phase_update_for_unique_index_swaps():
    from app.services import longitudinal_case_service as service

    visits = [
        SimpleNamespace(id=1, case_id=3, visit_date=date(2026, 1, 1), visit_index=2),
        SimpleNamespace(id=2, case_id=3, visit_date=date(2026, 2, 1), visit_index=1),
    ]
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = visits

    result = service._reindex_visits(db, 3)

    assert result == visits
    assert [visit.visit_index for visit in visits] == [1, 2]
    assert db.flush.call_count == 2


def test_create_case_rolls_back_when_initial_visit_insert_fails():
    from sqlalchemy.exc import IntegrityError
    from app.schemas.longitudinal_case import OperatorCaseCreate
    from app.services import longitudinal_case_service as service

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=11, code="fatty_liver", operator_enabled=True
    )
    db.commit.side_effect = IntegrityError("duplicate", {}, Exception("duplicate"))
    payload = OperatorCaseCreate(
        disease_id=11,
        patient_label="case",
        age=65,
        visits=[_visit_payload("2026-01-01")],
    )

    with pytest.raises(service.DuplicateVisitDateError):
        service.create_operator_case(db, user_id=7, payload=payload)

    db.rollback.assert_called_once()


def test_create_case_validates_initial_timeline_before_staging_case():
    from app.schemas.longitudinal_case import OperatorCaseCreate
    from app.services import longitudinal_case_service as service

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=11, code="fatty_liver", operator_enabled=True
    )
    payload = OperatorCaseCreate(
        disease_id=11,
        patient_label="case",
        age=65,
        visits=[_visit_payload("2026-01-01"), _visit_payload("2026-01-01")],
    )

    with pytest.raises(service.DuplicateVisitDateError):
        service.create_operator_case(db, user_id=7, payload=payload)

    db.add.assert_not_called()


def test_delete_visit_route_maps_last_visit_limit_to_conflict():
    from app.api.operator import _longitudinal_error
    from app.services.longitudinal_case_service import VisitLimitError

    error = _longitudinal_error(VisitLimitError("至少需要 1 次访视"))

    assert error.status_code == 409
