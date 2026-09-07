from app.services.report_read_service import project_report, build_pdf_source
from app.services.report_pdf_archive_service import source_digest
from backend.tests.test_report_read_service import saved_row


def test_source_digest_covers_saved_content_and_report_identity():
    source = build_pdf_source(project_report(saved_row()))
    original = source_digest(source)
    assert source_digest(source.model_copy(update={"report_id": 99})) != original
    assert (
        source_digest(source.model_copy(update={"content": source.content + "changed"}))
        != original
    )
