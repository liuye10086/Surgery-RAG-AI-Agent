import pytest
from pydantic import ValidationError
from app.schemas.report_pdf_archive import PdfCandidate


@pytest.mark.parametrize(
    "override",
    [
        {"object_key": "../private"},
        {"size_bytes": 67108865},
        {"page_count": 201},
        {"page_count": True},
        {"object_key": "reports/17/------------------------------------/document.pdf"},
        {"pdf_sha256": "not-a-hash"},
    ],
)
def test_candidate_rejects_invalid_or_unbounded_metadata(override):
    data = dict(
        object_key="reports/17/11111111-1111-4111-8111-111111111111/document.pdf",
        pdf_sha256="a" * 64,
        size_bytes=1,
        page_count=1,
    )
    with pytest.raises(ValidationError):
        PdfCandidate(**{**data, **override})
