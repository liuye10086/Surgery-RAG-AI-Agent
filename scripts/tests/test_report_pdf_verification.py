import fitz
from scripts.verify_operator_report_pdf import pdf_layout_findings


def test_pdf_layout_checker_checks_every_page():
    with fitz.open() as doc:
        doc.new_page().insert_text((50, 50), "first page")
        doc.new_page().insert_text((50, 50), "second page")
        assert pdf_layout_findings(doc.tobytes()) == []
