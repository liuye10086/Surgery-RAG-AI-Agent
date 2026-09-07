import fitz
import pytest

from app.services.report_pdf_errors import PdfError


def test_lower_configured_pdf_limits_reject_without_truncation():
    from app.workers.report_pdf_execution import validate_pdf_limits

    with fitz.open() as document:
        document.new_page()
        document.new_page()
        data = document.tobytes()
    with pytest.raises(PdfError, match="pdf_render_failed"):
        validate_pdf_limits(data, max_bytes=len(data) - 1, max_pages=2)
    with pytest.raises(PdfError, match="pdf_render_failed"):
        validate_pdf_limits(data, max_bytes=len(data), max_pages=1)
    validate_pdf_limits(data, max_bytes=len(data), max_pages=2)
