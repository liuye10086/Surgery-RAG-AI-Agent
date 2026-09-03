"""Idempotency parsing, hashing, replay, and persistence for case creation."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from app.db.models import OperatorCase, OperatorIdempotencyKey


CREATE_CASE_SCOPE = "create_longitudinal_case"
CASE_RESOURCE_TYPE = "operator_case"


class IdempotencyError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class IdempotencyKeyError(IdempotencyError):
    pass


class IdempotencyConflictError(IdempotencyError):
    pass


def parse_idempotency_key(raw: str | UUID | None) -> UUID:
    if isinstance(raw, UUID):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        raise IdempotencyKeyError(
            "idempotency_key_missing",
            "缺少 Idempotency-Key",
        )
    try:
        return UUID(raw.strip())
    except (ValueError, AttributeError) as exc:
        raise IdempotencyKeyError(
            "idempotency_key_invalid",
            "Idempotency-Key 必须是 UUID",
        ) from exc


def hash_case_create(payload) -> str:
    normalized = payload.model_dump(mode="json")
    normalized["visits"] = sorted(
        normalized["visits"],
        key=lambda item: item["visit_date"],
    )
    body = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def get_idempotency_replay(
    db,
    user_id: int,
    key: str | UUID,
    request_sha256: str,
) -> OperatorCase | None:
    parsed_key = parse_idempotency_key(key)
    row = (
        db.query(OperatorIdempotencyKey)
        .filter(
            OperatorIdempotencyKey.user_id == user_id,
            OperatorIdempotencyKey.scope == CREATE_CASE_SCOPE,
            OperatorIdempotencyKey.idempotency_key == parsed_key,
        )
        .first()
    )
    if row is None:
        return None
    if row.request_sha256 != request_sha256:
        raise IdempotencyConflictError(
            "idempotency_key_reused",
            "该 Idempotency-Key 已用于不同的病例请求",
        )
    case = (
        db.query(OperatorCase)
        .filter(
            OperatorCase.id == row.resource_id,
            OperatorCase.user_id == user_id,
        )
        .first()
    )
    if case is None:
        raise IdempotencyConflictError(
            "idempotency_resource_missing",
            "该幂等请求对应的病例已不存在",
        )
    return case


def add_idempotency_result(
    db,
    *,
    user_id: int,
    key: str | UUID,
    request_sha256: str,
    resource_id: int,
) -> OperatorIdempotencyKey:
    row = OperatorIdempotencyKey(
        user_id=user_id,
        scope=CREATE_CASE_SCOPE,
        idempotency_key=parse_idempotency_key(key),
        request_sha256=request_sha256,
        resource_type=CASE_RESOURCE_TYPE,
        resource_id=resource_id,
    )
    db.add(row)
    db.flush()
    return row
