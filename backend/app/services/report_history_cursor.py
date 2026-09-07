import base64
import binascii
import hashlib
import hmac
import json
from datetime import datetime


def encode_cursor(payload, key):
    if len(key) < 32:
        raise ValueError("history_cursor_key_unavailable")
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return body + "." + hmac.new(key, body.encode(), hashlib.sha256).hexdigest()


def decode_cursor(token, key, *, user_id, filters_sha256):
    if not isinstance(token, str) or len(token) > 2048 or len(key) < 32:
        raise ValueError("history_cursor_invalid")
    try:
        body, signature = token.split(".")
        expected = hmac.new(key, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        raw = base64.b64decode(
            body + "=" * (-len(body) % 4), altchars=b"-_", validate=True
        )
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {
            "v",
            "user_id",
            "filters_sha256",
            "created_at",
            "id",
        }:
            raise ValueError()
        if (
            type(payload["v"]) is not int
            or payload["v"] != 1
            or type(payload["user_id"]) is not int
            or payload["user_id"] != user_id
            or payload["filters_sha256"] != filters_sha256
        ):
            raise ValueError()
        if type(payload["id"]) is not int or payload["id"] < 1:
            raise ValueError()
        if datetime.fromisoformat(payload["created_at"]).tzinfo is None:
            raise ValueError()
        return payload
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error) as exc:
        raise ValueError("history_cursor_invalid") from exc
