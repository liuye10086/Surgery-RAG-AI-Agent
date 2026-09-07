from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import hashlib
import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.services.report_pdf_archive_service import prepare_pdf_archive
from app.services.report_pdf_repository import claim_pdf, publish_pdf
from app.services.report_pdf_delivery import prepare_delivery, delivery_chunks
from app.services.report_archive_storage import ArchiveStorage
from app.services.report_pdf_errors import PdfError
from backend.tests.integration.test_report_pdf_admission import completed_report


@pytest.fixture
def archived(db, completed_report, tmp_path, monkeypatch):
    import fitz

    monkeypatch.setattr(settings, "REPORT_ARCHIVE_ROOT", str(tmp_path))
    db.execute(text("UPDATE ai_reports SET download_count=3"))
    db.commit()
    prepare_pdf_archive(db, 1, completed_report, str(uuid4()))
    claim = claim_pdf(db, "archive-test")
    pdf = fitz.open()
    pdf.new_page()
    raw = pdf.tobytes()
    pdf.close()
    storage = ArchiveStorage(tmp_path)
    candidate = storage.write_candidate(claim.object_key, raw)
    assert publish_pdf(db, claim, candidate, storage)
    return completed_report, storage, candidate


def test_twenty_concurrent_deliveries_are_exact_and_counted_once(
    db, integration_engine, archived, monkeypatch
):
    report_id, storage, candidate = archived
    monkeypatch.setattr(
        "app.services.pdf_generator.generate_pdf",
        lambda *args, **kwargs: pytest.fail("download must not render"),
    )
    before = db.execute(text("SELECT updated_at,download_count FROM ai_reports")).one()
    db.rollback()
    factory = sessionmaker(bind=integration_engine, expire_on_commit=False)

    def download(_):
        with factory() as session:
            delivery = prepare_delivery(session, 1, report_id, storage)
            return hashlib.sha256(b"".join(delivery_chunks(delivery))).hexdigest()

    with ThreadPoolExecutor(max_workers=20) as pool:
        hashes = list(pool.map(download, range(20)))
    assert set(hashes) == {candidate.pdf_sha256}
    assert (
        db.execute(text("SELECT delivery_count FROM report_pdf_archives")).scalar_one()
        == 20
    )
    assert (
        db.execute(text("SELECT updated_at,download_count FROM ai_reports")).one()
        == before
    )


def test_download_authorization_headers_and_original_health(db, client, archived):
    report_id, storage, candidate = archived
    response = client(1).get(f"/api/v1/operator/reports/{report_id}/download")
    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == candidate.pdf_sha256
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert (
        client(1)
        .get(
            f"/api/v1/operator/reports/{report_id}/download",
            headers={"Range": "bytes=0-10"},
        )
        .status_code
        == 416
    )
    assert (
        client(2).get(f"/api/v1/operator/reports/{report_id}/download").status_code
        == 404
    )
    storage.candidate_path(candidate.object_key).write_bytes(b"corrupt")
    with pytest.raises(PdfError, match="pdf_original_corrupt"):
        prepare_delivery(db, 1, report_id, storage)
    assert (
        db.execute(text("SELECT state FROM report_pdf_archives")).scalar_one()
        == "corrupt"
    )


def test_changed_source_blocks_cached_original(db, archived):
    report_id, storage, candidate = archived
    db.execute(text("UPDATE ai_reports SET content='changed'"))
    db.commit()
    with pytest.raises(PdfError, match="pdf_source_changed"):
        prepare_delivery(db, 1, report_id, storage)
    assert (
        db.execute(text("SELECT delivery_count FROM report_pdf_archives")).scalar_one()
        == 0
    )
