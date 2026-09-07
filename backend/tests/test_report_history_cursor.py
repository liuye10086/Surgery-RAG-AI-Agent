import pytest
from app.services.report_history_cursor import encode_cursor, decode_cursor
from app.schemas.report_history import HistoryFilters

KEY = b"x" * 32
PAYLOAD = {
    "v": 1,
    "user_id": 1,
    "filters_sha256": "a" * 64,
    "created_at": "2026-09-07T00:00:00+00:00",
    "id": 30,
}


def test_cursor_is_bound_to_owner_and_filters():
    token = encode_cursor(PAYLOAD, KEY)
    assert decode_cursor(token, KEY, user_id=1, filters_sha256="a" * 64)["id"] == 30
    for owner, digest in ((2, "a" * 64), (1, "b" * 64)):
        with pytest.raises(ValueError):
            decode_cursor(token, KEY, user_id=owner, filters_sha256=digest)


@pytest.mark.parametrize("token", ["x" * 2049, "", "a.b", "a.b.c", "中文"])
def test_invalid_cursor_is_bounded_public_error(token):
    with pytest.raises(ValueError, match="history_cursor_invalid"):
        decode_cursor(token, KEY, user_id=1, filters_sha256="a" * 64)


@pytest.mark.parametrize(
    "change",
    [{"id": True}, {"v": True}, {"created_at": "2026-09-07"}, {"extra": "private"}],
)
def test_signed_invalid_payload_still_rejected(change):
    with pytest.raises(ValueError, match="history_cursor_invalid"):
        decode_cursor(
            encode_cursor({**PAYLOAD, **change}, KEY),
            KEY,
            user_id=1,
            filters_sha256="a" * 64,
        )


def test_filters_reject_unknown_and_reversed_or_naive_dates():
    for payload in (
        {"private": "secret"},
        {"created_from": "2026-09-07"},
        {
            "created_from": "2026-09-08T00:00:00Z",
            "created_before": "2026-09-07T00:00:00Z",
        },
    ):
        with pytest.raises(ValueError):
            HistoryFilters.model_validate(payload)
