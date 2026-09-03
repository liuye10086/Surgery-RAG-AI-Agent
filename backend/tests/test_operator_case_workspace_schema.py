"""Schema contracts for the operator-owned case workspace."""

from copy import deepcopy

import pytest
from pydantic import ValidationError


def _visit() -> dict:
    return {
        "visit_date": "2026-09-03",
        "indicators": [{"name": "ALT", "value": 42, "unit": "U/L"}],
        "notes": None,
    }


def _create_payload() -> dict:
    return {
        "disease_id": 1,
        "age": 56,
        "sex": "male",
        "baseline_stage": "pre_cirrhosis",
        "notes": None,
        "visits": [_visit()],
    }


@pytest.mark.parametrize("missing", ["age", "sex", "baseline_stage", "visits"])
def test_create_requires_complete_profile_and_first_visit(missing: str):
    from app.schemas.longitudinal_case import OperatorCaseCreate

    payload = _create_payload()
    payload.pop(missing)

    with pytest.raises(ValidationError):
        OperatorCaseCreate.model_validate(payload)


def test_create_rejects_empty_timeline():
    from app.schemas.longitudinal_case import OperatorCaseCreate

    payload = _create_payload()
    payload["visits"] = []

    with pytest.raises(ValidationError):
        OperatorCaseCreate.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("patient_label", "legacy-name"),
        ("anonymous_case_code", "OC-12345678"),
        ("status", "active"),
        ("user_id", 7),
    ],
)
def test_create_rejects_server_owned_and_legacy_fields(field: str, value):
    from app.schemas.longitudinal_case import OperatorCaseCreate

    payload = _create_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        OperatorCaseCreate.model_validate(payload)


def test_visit_rejects_client_visit_index():
    from app.schemas.longitudinal_case import VisitCreate

    payload = _visit()
    payload["visit_index"] = 1

    with pytest.raises(ValidationError):
        VisitCreate.model_validate(payload)


def test_create_normalizes_required_text():
    from app.schemas.longitudinal_case import OperatorCaseCreate

    payload = _create_payload()
    payload["baseline_stage"] = "  pre_cirrhosis  "
    payload["notes"] = "   "

    value = OperatorCaseCreate.model_validate(payload)

    assert value.baseline_stage == "pre_cirrhosis"
    assert value.notes is None


def test_aggregate_save_is_complete_and_trims_reason():
    from app.schemas.operator_case_workspace import OperatorCaseSave

    value = OperatorCaseSave.model_validate(
        {
            "age": 57,
            "sex": "male",
            "baseline_stage": "pre_cirrhosis",
            "notes": " 定期复核 ",
            "visits": [_visit()],
            "change_reason": "  更正年龄  ",
        }
    )

    assert value.notes == "定期复核"
    assert value.change_reason == "更正年龄"


@pytest.mark.parametrize("missing", ["age", "sex", "baseline_stage", "visits"])
def test_aggregate_save_rejects_missing_complete_snapshot_field(missing: str):
    from app.schemas.operator_case_workspace import OperatorCaseSave

    payload = {
        "age": 57,
        "sex": "female",
        "baseline_stage": "mci",
        "notes": None,
        "visits": [_visit()],
    }
    payload.pop(missing)

    with pytest.raises(ValidationError):
        OperatorCaseSave.model_validate(payload)


def test_aggregate_save_allows_missing_reason_for_noop_service_decision():
    from app.schemas.operator_case_workspace import OperatorCaseSave

    value = OperatorCaseSave.model_validate(
        {
            "age": 57,
            "sex": "female",
            "baseline_stage": "mci",
            "notes": None,
            "visits": [_visit()],
        }
    )

    assert value.change_reason is None


def test_case_response_does_not_expose_patient_label():
    from app.schemas.longitudinal_case import OperatorCaseOut

    assert "patient_label" not in OperatorCaseOut.model_fields


def test_case_list_response_has_explicit_page_metadata():
    from app.schemas.longitudinal_case import OperatorCaseListOut

    assert {"cases", "total", "skip", "limit"}.issubset(
        OperatorCaseListOut.model_fields
    )


def test_report_readiness_contract_preserves_server_blockers():
    from app.schemas.operator_case_workspace import OperatorCaseReportReadiness

    value = OperatorCaseReportReadiness.model_validate(
        {
            "ready": False,
            "case_ready": True,
            "timeline_ready": False,
            "model_ready": True,
            "visit_count": 2,
            "minimum_visits": 3,
            "blockers": [
                {
                    "code": "insufficient_visits",
                    "message": "当前有 2 次有效访视，活动模型至少需要 3 次",
                }
            ],
        }
    )

    assert value.minimum_visits == 3
    assert value.blockers[0].code == "insufficient_visits"


def test_all_workspace_request_models_forbid_extra_fields():
    from app.schemas.longitudinal_case import OperatorCaseCreate, VisitCreate
    from app.schemas.operator_case_workspace import OperatorCaseSave

    create_payload = _create_payload()
    create_payload["unexpected"] = True
    save_payload = deepcopy(_create_payload())
    save_payload.pop("disease_id")
    save_payload["unexpected"] = True

    with pytest.raises(ValidationError):
        OperatorCaseCreate.model_validate(create_payload)
    with pytest.raises(ValidationError):
        VisitCreate.model_validate({**_visit(), "unexpected": True})
    with pytest.raises(ValidationError):
        OperatorCaseSave.model_validate(save_payload)
