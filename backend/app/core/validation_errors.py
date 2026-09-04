"""Safe, localized FastAPI request-validation responses."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def _field_from_location(location: Any) -> str | None:
    if not isinstance(location, (list, tuple)):
        return None
    parts = location[1:] if location and location[0] == "body" else location
    field_parts = [str(part) for part in parts]
    return ".".join(field_parts) or None


def _safe_number(context: Mapping[str, Any], key: str) -> int | float | None:
    value = context.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return None


def _message_for_validation_type(error_type: str, context: Mapping[str, Any]) -> str:
    if error_type == "missing":
        return "此字段为必填项"
    if error_type in {"int_parsing", "int_type"}:
        return "必须为整数"
    if error_type == "greater_than_equal":
        minimum = _safe_number(context, "ge")
        return f"必须大于或等于 {minimum}" if minimum is not None else "必须大于或等于允许下限"
    if error_type == "less_than_equal":
        maximum = _safe_number(context, "le")
        return f"必须小于或等于 {maximum}" if maximum is not None else "必须小于或等于允许上限"
    if error_type == "string_too_long":
        maximum_length = _safe_number(context, "max_length")
        return (
            f"长度不能超过 {maximum_length} 个字符"
            if maximum_length is not None
            else "长度超过允许上限"
        )
    return "输入内容格式不正确"


def localize_validation_issue(item: Mapping[str, Any]) -> dict[str, str]:
    """Return only stable, non-sensitive validation metadata for one error."""
    error_type = item.get("type")
    code = error_type if isinstance(error_type, str) else "validation_error"
    context = item.get("ctx")
    safe_context = context if isinstance(context, Mapping) else {}
    issue = {
        "code": code,
        "message": _message_for_validation_type(code, safe_context),
    }
    field = _field_from_location(item.get("loc"))
    if field:
        issue["field"] = field
    return issue


def request_validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "code": "validation_error",
                "message": "输入数据无效",
                "issues": [localize_validation_issue(item) for item in exc.errors()],
            }
        },
    )
