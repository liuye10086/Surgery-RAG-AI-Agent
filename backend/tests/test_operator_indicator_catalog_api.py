"""Operator indicator catalog API contracts."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


def test_catalog_route_is_registered_and_operator_protected():
    from app.api.operator import router

    route = next(
        route
        for route in router.routes
        if route.path == "/operator/diseases/{disease_code}/indicators"
    )

    assert route.methods == {"GET"}
    dependency_names = {
        getattr(dependency.call, "__name__", "")
        for dependency in route.dependant.dependencies
    }
    assert "require_ai_operator" in dependency_names


def test_operator_can_read_enabled_disease_indicator_catalog():
    from app.api.operator import get_operator_indicator_catalog

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=11,
        code="fatty_liver",
        operator_enabled=True,
    )

    result = get_operator_indicator_catalog(
        "fatty_liver",
        db=db,
        current_user=SimpleNamespace(id=7),
    )

    assert result.disease_code == "fatty_liver"
    assert len(result.catalog_version) == 64
    assert any(item.code == "alt" for item in result.items)


def test_catalog_load_failure_is_a_stable_503():
    from app.api.operator import get_operator_indicator_catalog
    from app.services.operator_indicator_catalog import (
        IndicatorCatalogUnavailableError,
    )

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=11,
        code="fatty_liver",
        operator_enabled=True,
    )
    with patch(
        "app.api.operator.load_operator_indicator_catalog",
        side_effect=IndicatorCatalogUnavailableError("secret path"),
    ):
        with pytest.raises(HTTPException) as caught:
            get_operator_indicator_catalog(
                "fatty_liver",
                db=db,
                current_user=SimpleNamespace(id=7),
            )

    assert caught.value.status_code == 503
    assert caught.value.detail == {
        "code": "indicator_catalog_unavailable",
        "message": "指标目录暂时不可用，请稍后重试",
    }
    assert "secret path" not in str(caught.value.detail)
