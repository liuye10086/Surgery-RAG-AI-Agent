"""Deterministic source-segment binding for approved manifest rules."""

from __future__ import annotations

from typing import Any

from app.db.models import StandardSegment


class StandardSourceBindingError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def normalize_source_text(value: str) -> str:
    return "\n".join(
        line.rstrip() for line in str(value).replace("\r\n", "\n").split("\n")
    ).strip()


def resolve_manifest_source_segment(
    db: Any,
    *,
    version_id: int,
    source: Any,
) -> StandardSegment:
    query = db.query(StandardSegment).filter(StandardSegment.version_id == version_id)
    for field in ("paragraph_index", "table_index", "row_index", "column_index"):
        value = getattr(source, field, None)
        if value is not None:
            query = query.filter(getattr(StandardSegment, field) == value)
    expected = normalize_source_text(source.raw_text or "")
    matches = [
        item
        for item in query.all()
        if normalize_source_text(item.raw_text) == expected
    ]
    if not matches:
        raise StandardSourceBindingError("source_segment_missing")
    if len(matches) != 1:
        raise StandardSourceBindingError("source_segment_ambiguous")
    return matches[0]
