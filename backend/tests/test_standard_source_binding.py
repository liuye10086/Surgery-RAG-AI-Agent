from types import SimpleNamespace

import pytest

from app.schemas.standard_manifest import SourceLocator
from app.services.standard_source_binding import (
    StandardSourceBindingError,
    normalize_source_text,
    resolve_manifest_source_segment,
)


def segment(identifier, *, version_id=4, raw_text="CDR 原文"):
    return SimpleNamespace(
        id=identifier,
        version_id=version_id,
        paragraph_index=None,
        table_index=3,
        row_index=3,
        column_index=None,
        raw_text=raw_text,
    )


class SegmentQuery:
    def __init__(self, segments):
        self._segments = list(segments)

    def filter(self, *criteria):
        for criterion in criteria:
            field = criterion.left.key
            expected = criterion.right.value
            self._segments = [
                item for item in self._segments
                if getattr(item, field) == expected
            ]
        return self

    def all(self):
        return list(self._segments)


class SegmentSession:
    def __init__(self, segments):
        self.segments = segments

    def query(self, _model):
        return SegmentQuery(self.segments)


def db_with_segments(segments):
    return SegmentSession(segments)


def test_resolve_manifest_source_segment_requires_one_same_version_match():
    source = SourceLocator(table_index=3, row_index=3, raw_text="CDR 原文")
    matched = segment(12)

    resolved = resolve_manifest_source_segment(
        db_with_segments([matched]), version_id=4, source=source
    )

    assert resolved.id == 12


@pytest.mark.parametrize(
    ("segments", "code"),
    [
        ([], "source_segment_missing"),
        ([segment(1), segment(2)], "source_segment_ambiguous"),
    ],
)
def test_resolve_manifest_source_segment_fails_closed(segments, code):
    with pytest.raises(StandardSourceBindingError) as caught:
        resolve_manifest_source_segment(
            db_with_segments(segments),
            version_id=4,
            source=SourceLocator(table_index=3, row_index=3, raw_text="CDR 原文"),
        )

    assert caught.value.code == code


def test_resolve_manifest_source_segment_excludes_other_versions():
    resolved = resolve_manifest_source_segment(
        db_with_segments([segment(12), segment(13, version_id=5)]),
        version_id=4,
        source=SourceLocator(table_index=3, row_index=3, raw_text="CDR 原文"),
    )

    assert resolved.id == 12


def test_normalize_source_text_normalizes_windows_newlines_and_trailing_space():
    assert normalize_source_text("  CDR 原文  \r\n下一行  \r\n") == "CDR 原文\n下一行"
