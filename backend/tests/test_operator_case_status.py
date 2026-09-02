import pytest
from pydantic import ValidationError
from types import SimpleNamespace
from unittest.mock import MagicMock


def test_status_enum_has_only_two_stable_keys():
    from app.schemas.operator_case_status import OperatorCaseStatus

    assert {item.value for item in OperatorCaseStatus} == {"active", "archived"}


def test_status_change_request_trims_reason_and_rejects_unknown_values():
    from app.schemas.operator_case_status import OperatorCaseStatusChangeRequest

    request = OperatorCaseStatusChangeRequest(
        expected_status="active", status="archived", reason="  随访结束  "
    )
    assert request.reason == "随访结束"
    with pytest.raises(ValidationError):
        OperatorCaseStatusChangeRequest(
            expected_status="active", status="paused", reason="原因"
        )


def test_status_change_request_allows_missing_reason_for_idempotent_requests():
    from app.schemas.operator_case_status import OperatorCaseStatusChangeRequest

    request = OperatorCaseStatusChangeRequest(
        expected_status="active", status="active", reason=None
    )
    assert request.reason is None


def test_normal_case_update_rejects_status_field():
    from app.schemas.longitudinal_case import OperatorCaseUpdate

    with pytest.raises(ValidationError):
        OperatorCaseUpdate.model_validate({"status": "archived"})


def _case(status="active", enabled=True):
    return SimpleNamespace(
        id=3,
        user_id=7,
        status=status,
        disease=SimpleNamespace(code="fatty_liver", operator_enabled=enabled),
    )


def test_change_status_archives_and_writes_audit_log():
    from app.schemas.operator_case_status import OperatorCaseStatusChangeRequest
    from app.services.operator_case_status_service import change_operator_case_status

    db = MagicMock()
    case = _case()
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = case

    result = change_operator_case_status(
        db,
        7,
        3,
        OperatorCaseStatusChangeRequest(
            expected_status="active", status="archived", reason="随访结束"
        ),
    )

    assert result is case
    assert case.status == "archived"
    log = db.add.call_args.args[0]
    assert log.case_id_snapshot == 3
    assert log.actor_id_snapshot == 7
    assert log.from_status == "active"
    assert log.to_status == "archived"
    assert log.reason == "随访结束"
    db.commit.assert_called_once()


def test_change_status_is_idempotent_without_audit():
    from app.schemas.operator_case_status import OperatorCaseStatusChangeRequest
    from app.services.operator_case_status_service import change_operator_case_status

    db = MagicMock()
    case = _case()
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = case

    result = change_operator_case_status(
        db,
        7,
        3,
        OperatorCaseStatusChangeRequest(
            expected_status="active", status="active", reason=None
        ),
    )

    assert result is case
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_change_status_rejects_stale_expected_status():
    from app.schemas.operator_case_status import OperatorCaseStatusChangeRequest
    from app.services.operator_case_status_service import CaseStatusConflictError, change_operator_case_status

    db = MagicMock()
    case = _case(status="archived")
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = case

    with pytest.raises(CaseStatusConflictError):
        change_operator_case_status(
            db,
            7,
            3,
            OperatorCaseStatusChangeRequest(
                expected_status="active", status="active", reason=None
            ),
        )


def test_change_status_requires_reason_for_actual_change():
    from app.schemas.operator_case_status import OperatorCaseStatusChangeRequest
    from app.services.operator_case_status_service import CaseStatusReasonError, change_operator_case_status

    db = MagicMock()
    case = _case()
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = case

    with pytest.raises(CaseStatusReasonError):
        change_operator_case_status(
            db,
            7,
            3,
            OperatorCaseStatusChangeRequest(
                expected_status="active", status="archived", reason=None
            ),
        )


def test_disabled_disease_allows_archive_but_rejects_restore():
    from app.schemas.operator_case_status import OperatorCaseStatusChangeRequest
    from app.services.disease_catalog import DiseaseDisabledError
    from app.services.operator_case_status_service import change_operator_case_status

    db = MagicMock()
    archived = _case(status="active", enabled=False)
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = archived
    change_operator_case_status(
        db,
        7,
        3,
        OperatorCaseStatusChangeRequest(
            expected_status="active", status="archived", reason="停用整理"
        ),
    )
    assert archived.status == "archived"

    restoring = _case(status="archived", enabled=False)
    db = MagicMock()
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = restoring
    with pytest.raises(DiseaseDisabledError):
        change_operator_case_status(
            db,
            7,
            3,
            OperatorCaseStatusChangeRequest(
                expected_status="archived", status="active", reason="恢复"
            ),
        )
