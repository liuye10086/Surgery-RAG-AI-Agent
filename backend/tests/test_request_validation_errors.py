"""Public contract for safe, localized request validation failures."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


def valid_case_payload(**overrides):
    payload = {
        "disease_id": 1,
        "age": 56,
        "sex": "male",
        "baseline_stage": "pre_cirrhosis",
        "notes": None,
        "visits": [
            {
                "visit_date": "2026-01-01",
                "indicators": [{"name": "ALT", "value": 42, "unit": "U/L"}],
            }
        ],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def client():
    from app.api.deps import get_db, require_ai_operator
    from app.main import app

    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    app.dependency_overrides[require_ai_operator] = lambda: SimpleNamespace(id=1)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


def test_request_validation_error_is_structured_chinese(client):
    response = client.post(
        "/api/v1/operator/longitudinal-cases",
        headers={"Idempotency-Key": str(uuid4())},
        json=valid_case_payload(age=121),
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "validation_error"
    assert detail["message"] == "输入数据无效"
    assert detail["issues"][0] == {
        "code": "less_than_equal",
        "field": "age",
        "message": "必须小于或等于 120",
    }
    assert "Input should" not in response.text
    assert "input" not in detail["issues"][0]


def test_request_validation_error_never_echoes_free_text_input(client):
    private_case_text = "PRIVATE_CASE_NARRATIVE_9F33" * 300
    response = client.post(
        "/api/v1/operator/longitudinal-cases",
        headers={"Idempotency-Key": str(uuid4())},
        json=valid_case_payload(notes=private_case_text),
    )

    assert response.status_code == 422
    assert private_case_text not in response.text
    assert "input" not in response.text


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        ({"type": "missing", "loc": ("body", "age")}, {"code": "missing", "field": "age", "message": "此字段为必填项"}),
        ({"type": "int_parsing", "loc": ("body", "age")}, {"code": "int_parsing", "field": "age", "message": "必须为整数"}),
        ({"type": "greater_than_equal", "loc": ("body", "age"), "ctx": {"ge": 0}}, {"code": "greater_than_equal", "field": "age", "message": "必须大于或等于 0"}),
        ({"type": "string_too_long", "loc": ("body", "notes"), "ctx": {"max_length": 5000}}, {"code": "string_too_long", "field": "notes", "message": "长度不能超过 5000 个字符"}),
        ({"type": "unknown_validation_type", "loc": ("body", "visits", 0)}, {"code": "unknown_validation_type", "field": "visits.0", "message": "输入内容格式不正确"}),
    ],
)
def test_localize_validation_issue_returns_safe_chinese_issue(item, expected):
    from app.core.validation_errors import localize_validation_issue

    assert localize_validation_issue(item) == expected
