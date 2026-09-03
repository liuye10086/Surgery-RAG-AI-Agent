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
