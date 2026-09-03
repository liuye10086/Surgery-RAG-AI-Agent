"""FastAPI boundary contracts for the operator case workspace."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


def _blocked_readiness():
    from app.schemas.operator_case_workspace import (
        OperatorCaseReadinessBlocker,
        OperatorCaseReportReadiness,
    )

    return OperatorCaseReportReadiness(
        ready=False,
        case_ready=True,
        timeline_ready=False,
        model_ready=True,
        visit_count=2,
        minimum_visits=3,
        blockers=[
            OperatorCaseReadinessBlocker(
                code="insufficient_visits",
                message="当前有 2 次有效访视，活动模型至少需要 3 次",
            )
        ],
    )


def test_report_readiness_route_is_registered_and_operator_protected():
    from app.api.operator import router

    route = next(
        route
        for route in router.routes
        if route.path == "/operator/longitudinal-cases/{case_id}/report-readiness"
    )
    assert route.methods == {"GET"}
    dependency_names = {
        getattr(dependency.call, "__name__", "")
        for dependency in route.dependant.dependencies
    }
    assert "require_ai_operator" in dependency_names


def test_report_creation_rechecks_readiness_before_inserting_report():
    from app.api.operator import create_longitudinal_report

    db = MagicMock()
    case = SimpleNamespace(id=3, status="active")
    with patch("app.api.operator.get_operator_case", return_value=case), patch(
        "app.api.operator.evaluate_operator_case_readiness",
        return_value=_blocked_readiness(),
    ):
        with pytest.raises(HTTPException) as caught:
            asyncio.run(
                create_longitudinal_report(
                    3,
                    None,
                    db,
                    SimpleNamespace(id=7),
                )
            )

    assert caught.value.status_code == 409
    db.add.assert_not_called()
    db.commit.assert_not_called()


def _create_payload():
    from app.schemas.longitudinal_case import OperatorCaseCreate

    return OperatorCaseCreate(
        disease_id=11,
        age=56,
        sex="male",
        baseline_stage="pre_cirrhosis",
        visits=[
            {
                "visit_date": "2026-01-01",
                "indicators": [{"name": "ALT", "value": 42, "unit": "U/L"}],
            }
        ],
    )


def _save_payload():
    from app.schemas.operator_case_workspace import OperatorCaseSave

    return OperatorCaseSave(
        age=57,
        sex="male",
        baseline_stage="pre_cirrhosis",
        visits=[
            {
                "visit_date": "2026-01-01",
                "indicators": [{"name": "ALT", "value": 42, "unit": "U/L"}],
            }
        ],
        change_reason="更正年龄",
    )


def test_router_exposes_one_case_mutation_boundary_and_no_reference_case_crud():
    from app.api.operator import router

    paths = {(route.path, frozenset(route.methods or ())) for route in router.routes}

    assert ("/operator/longitudinal-cases", frozenset({"POST"})) in paths
    assert ("/operator/longitudinal-cases", frozenset({"GET"})) in paths
    assert ("/operator/longitudinal-cases/{case_id}", frozenset({"PUT"})) in paths
    assert ("/operator/longitudinal-cases/{case_id}", frozenset({"DELETE"})) in paths
    assert not any(path == "/operator/cases" or path.startswith("/operator/cases/") for path, _ in paths)
    assert not any("/visits" in path for path, _ in paths)


def test_create_requires_idempotency_header_and_calls_command_service():
    from app.api.operator import create_longitudinal_case

    expected = SimpleNamespace(id=3)
    db = MagicMock()
    user = SimpleNamespace(id=7)
    with patch(
        "app.api.operator.create_operator_case_command", return_value=expected
    ) as command:
        result = create_longitudinal_case(
            _create_payload(),
            idempotency_key="5f0a6f11-7a08-47dc-9ac8-f7961962bd9d",
            db=db,
            current_user=user,
        )

    assert result is expected
    command.assert_called_once_with(
        db,
        7,
        _create_payload(),
        "5f0a6f11-7a08-47dc-9ac8-f7961962bd9d",
    )


def test_missing_idempotency_key_returns_stable_400_detail():
    from app.api.operator import create_longitudinal_case

    with pytest.raises(HTTPException) as caught:
        create_longitudinal_case(
            _create_payload(),
            idempotency_key=None,
            db=MagicMock(),
            current_user=SimpleNamespace(id=7),
        )

    assert caught.value.status_code == 400
    assert caught.value.detail == {
        "code": "idempotency_key_missing",
        "message": "缺少 Idempotency-Key",
    }


def test_update_calls_one_aggregate_command():
    from app.api.operator import update_longitudinal_case

    expected = SimpleNamespace(id=3)
    db = MagicMock()
    user = SimpleNamespace(id=7)
    payload = _save_payload()
    with patch(
        "app.api.operator.save_operator_case_command", return_value=expected
    ) as command:
        result = update_longitudinal_case(3, payload, db, user)

    assert result is expected
    command.assert_called_once_with(db, 7, 3, payload)


def test_list_returns_total_and_page_metadata_and_passes_search_filters():
    from app.api.operator import list_longitudinal_cases
    from app.schemas.operator_case_status import OperatorCaseStatus

    cases = [
        SimpleNamespace(
            id=3,
            user_id=7,
            disease_id=11,
            anonymous_case_code="CASE-23",
            age=56,
            sex="male",
            baseline_stage="pre_cirrhosis",
            notes=None,
            status="active",
            visits=[],
            created_at=None,
            updated_at=None,
            disease=SimpleNamespace(
                id=11,
                code="fatty_liver",
                name="脂肪肝",
                operator_enabled=True,
            ),
        )
    ]
    db = MagicMock()
    with patch("app.api.operator.list_operator_cases", return_value=(cases, 21)) as query:
        result = list_longitudinal_cases(
            q="CASE-23",
            disease_id=11,
            status_filter=OperatorCaseStatus.ACTIVE,
            skip=20,
            limit=10,
            db=db,
            current_user=SimpleNamespace(id=7),
        )

    assert [item.id for item in result.cases] == [3]
    assert result.total == 21
    assert result.skip == 20
    assert result.limit == 10
    query.assert_called_once_with(
        db,
        7,
        q="CASE-23",
        disease_id=11,
        status="active",
        skip=20,
        limit=10,
    )


def test_domain_errors_map_to_stable_safe_details():
    from app.api.operator import _longitudinal_error
    from app.services.operator_case_commands import OperatorCaseCommandError
    from app.services.operator_case_idempotency import IdempotencyConflictError
    from app.services.operator_case_validation import OperatorCaseValidationError

    cases = [
        (OperatorCaseCommandError("change_reason_required", "请填写变更原因"), 422),
        (IdempotencyConflictError("idempotency_key_reused", "幂等键冲突"), 409),
        (OperatorCaseValidationError("age_invalid", "年龄无效", field="age"), 422),
    ]
    for error, expected_status in cases:
        response = _longitudinal_error(error)
        assert response.status_code == expected_status
        assert response.detail["code"] == error.code
        assert response.detail["message"] == error.message
        assert "secret" not in str(response.detail)


def test_invalid_visit_error_keeps_stable_nested_field_path():
    from app.api.operator import _longitudinal_error
    from app.services.operator_case_validation import OperatorCaseValidationError

    response = _longitudinal_error(
        OperatorCaseValidationError(
            "indicator_value_missing",
            "指标数值不能为空",
            field="visits.0.indicators.0.value",
        )
    )

    assert response.status_code == 422
    assert response.detail["field"] == "visits.0.indicators.0.value"


def test_validation_error_includes_only_safe_structured_issue_fields():
    from app.api.operator import _longitudinal_error
    from app.services.operator_case_validation import OperatorCaseValidationError

    response = _longitudinal_error(
        OperatorCaseValidationError(
            "visits_invalid",
            "访视输入无效",
            issues=[
                {
                    "code": "indicator_value_missing",
                    "message": "指标数值不能为空",
                    "field": "visits.0.indicators.0.value",
                    "internal": "must-not-leak",
                }
            ],
        )
    )

    assert response.detail["issues"] == [
        {
            "code": "indicator_value_missing",
            "message": "指标数值不能为空",
            "field": "visits.0.indicators.0.value",
        }
    ]


def test_case_write_maps_catalog_failure_to_safe_503():
    from app.api.operator import create_longitudinal_case
    from app.services.operator_indicator_catalog import IndicatorCatalogUnavailableError

    with patch(
        "app.api.operator.create_operator_case_command",
        side_effect=IndicatorCatalogUnavailableError("private manifest path"),
    ):
        with pytest.raises(HTTPException) as caught:
            create_longitudinal_case(
                _create_payload(),
                idempotency_key="5f0a6f11-7a08-47dc-9ac8-f7961962bd9d",
                db=MagicMock(),
                current_user=SimpleNamespace(id=7),
            )

    assert caught.value.status_code == 503
    assert caught.value.detail["code"] == "indicator_catalog_unavailable"
    assert "private manifest path" not in str(caught.value.detail)
