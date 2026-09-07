from app.services.report_document_renderer import render_report_document, escape_text
from backend.tests.report_document_fixtures import document_payload
from app.schemas.report_document import ReportDocument


def test_report_has_eleven_sections_and_escaped_notes():
    text = render_report_document(ReportDocument.model_validate(document_payload()))
    assert sum(line.startswith("## ") for line in text.splitlines()) == 11
    assert "## 8. 参考标准和相似病例" in text
    assert "<script>" not in escape_text("<script>alert(1)</script>")
    assert "\\|" in escape_text("a|b")
    assert "\n## " not in escape_text("备注\n## 伪造章节")
