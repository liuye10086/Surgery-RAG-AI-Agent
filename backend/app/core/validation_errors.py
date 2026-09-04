"""Safe, localized FastAPI request-validation responses."""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


_SAFE_BODY_FIELDS: dict[str, object] = {
    "disease_id": None,
    "age": None,
    "sex": None,
    "baseline_stage": None,
    "notes": None,
    "change_reason": None,
    "visits": {
        "visit_date": None,
        "indicators": {"name": None, "value": None, "unit": None},
        "notes": None,
        "visit_context": {
            "source_type": None,
            "facility_name": None,
            "device_name": None,
            "assay_platform": None,
            "method": None,
            "specimen": None,
            "is_baseline": None,
            "treatment_change": None,
            "diagnosis_change": None,
            "scale_version": None,
            "assessment_language": None,
            "education_years": None,
            "education_adjusted": None,
            "imaging_type": None,
        },
    },
}
_SAFE_NUMERIC_CONTEXT_KEYS = frozenset({"ge", "le", "min_length", "max_length"})
_LIST_FIELD_NAMES = frozenset({"visits", "indicators"})


def _field_from_location(location: Any, *, error_type: str) -> str | None:
    """Return only declared operator-payload paths and list indices.

    Pydantic includes an untrusted extra JSON key in ``loc`` for
    ``extra_forbidden``.  Do not surface any path for that error type; for
    other errors, traverse a fixed schema-derived allowlist.
    """
    if error_type == "extra_forbidden" or not isinstance(location, (list, tuple)):
        return None
    parts = location[1:] if location and location[0] == "body" else location
    node: object = _SAFE_BODY_FIELDS
    field_parts: list[str] = []
    for part in parts:
        if isinstance(part, int) and not isinstance(part, bool):
            if (
                not isinstance(node, dict)
                or not field_parts
                or field_parts[-1] not in _LIST_FIELD_NAMES
            ):
                return None
            field_parts.append(str(part))
            continue
        if not isinstance(part, str) or not isinstance(node, dict) or part not in node:
            return None
        field_parts.append(part)
        node = node[part]
    return ".".join(field_parts) or None


def _safe_number(context: Mapping[str, Any], key: str) -> int | float | None:
    if key not in _SAFE_NUMERIC_CONTEXT_KEYS:
        return None
    value = context.get(key)
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    ):
        return value
    return None


def _message_for_validation_type(error_type: str, context: Mapping[str, Any]) -> str:
    if error_type == "missing":
        return "此字段为必填项"
    if error_type == "literal_error":
        return "请选择有效选项"
    if error_type == "extra_forbidden":
        return "不允许包含未定义字段"
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
    if error_type == "string_too_short":
        minimum_length = _safe_number(context, "min_length")
        return (
            f"长度不能少于 {minimum_length} 个字符"
            if minimum_length is not None
            else "长度低于允许下限"
        )
    if error_type == "too_short":
        minimum_length = _safe_number(context, "min_length")
        return (
            f"至少需要 {minimum_length} 项"
            if minimum_length is not None
            else "列表项数低于允许下限"
        )
    if error_type == "too_long":
        maximum_length = _safe_number(context, "max_length")
        return (
            f"不能超过 {maximum_length} 项"
            if maximum_length is not None
            else "列表项数超过允许上限"
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
    field = _field_from_location(item.get("loc"), error_type=code)
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
