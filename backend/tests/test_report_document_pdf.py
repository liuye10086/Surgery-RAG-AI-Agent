from backend.tests.report_document_fixtures import build_demo_document
from app.services.pdf_generator import (
    _markdown_to_safe_html,
    _document_observation_charts,
)
from app.services.report_document_renderer import render_report_document


def test_pdf_reads_saved_document_chart_dates_and_values():
    doc = build_demo_document()
    charts = _document_observation_charts(doc.model_dump(mode="json"))
    assert charts
    assert charts[0]["dots"][1]["x"] - charts[0]["dots"][0]["x"] < 2
    text = _markdown_to_safe_html(
        render_report_document(doc), report_document=doc.model_dump(mode="json")
    )
    assert "CASE-ABCD-2345" in text
    assert "谷丙转氨酶" in text
    assert "<svg" in text
    assert "2025-01-01" in text
