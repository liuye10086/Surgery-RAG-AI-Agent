import os
from uuid import uuid4
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from app.core.config import settings
from app.db.models import ReportPdfArchive
from app.services.report_pdf_archive_service import prepare_pdf_archive
from app.services.report_pdf_renderer_manifest import load_renderer_manifest
from app.services.report_pdf_repository import (
    claim_pdf,
    heartbeat_pdf,
    publish_pdf,
    sweep_pdf,
)
from app.services.report_archive_storage import ArchiveStorage
from app.workers.report_pdf_worker import run_pdf_worker_once
from backend.tests.integration.test_report_pdf_admission import completed_report


def test_real_chromium_worker_publishes_original_without_report_mutation(
    db, integration_engine, completed_report, monkeypatch, tmp_path
):
    manifest = os.environ["REPORT_TEST_RENDERER_MANIFEST"]
    monkeypatch.setattr(
        "app.services.report_pdf_archive_service.load_renderer_manifest",
        load_renderer_manifest,
    )
    monkeypatch.setattr(settings, "REPORT_PDF_RENDERER_MANIFEST", manifest)
    monkeypatch.setattr(settings, "REPORT_ARCHIVE_ROOT", str(tmp_path))
    db.execute(
        text(
            "UPDATE ai_reports SET content='# 中文报告\n\n脂肪肝与阿尔茨海默病。\n\n|指标|数值|\n|---|---|\n|测试|0|'"
        )
    )
    db.commit()
    before = db.execute(
        text("SELECT content,updated_at,download_count FROM ai_reports")
    ).one()
    accepted = prepare_pdf_archive(db, 1, completed_report, str(uuid4()))
    factory = sessionmaker(bind=integration_engine, expire_on_commit=False)
    assert run_pdf_worker_once(factory, "real-pdf-worker")
    db.expire_all()
    archive = db.get(ReportPdfArchive, completed_report)
    assert archive.state == "ready"
    assert archive.published_attempt_id == accepted.attempt_id
    after = db.execute(
        text("SELECT content,updated_at,download_count FROM ai_reports")
    ).one()
    assert before == after
    import fitz

    key = db.execute(text("SELECT object_key FROM report_pdf_attempts")).scalar_one()
    with ArchiveStorage(tmp_path).open_verified(
        key, archive.pdf_sha256, archive.size_bytes
    ) as stream:
        with fitz.open(stream=stream.read(), filetype="pdf") as document:
            assert "脂肪肝" in "".join(page.get_text() for page in document)


def test_expired_pdf_claim_cannot_publish_or_renew(db, completed_report, tmp_path):
    import fitz

    prepare_pdf_archive(db, 1, completed_report, str(uuid4()))
    claim = claim_pdf(db, "worker-a")
    pdf = fitz.open()
    pdf.new_page()
    raw = pdf.tobytes()
    pdf.close()
    storage = ArchiveStorage(tmp_path)
    candidate = storage.write_candidate(claim.object_key, raw)
    db.execute(
        text(
            "UPDATE report_pdf_attempts SET lease_expires_at=clock_timestamp()-interval '1 second'"
        )
    )
    db.commit()
    assert not heartbeat_pdf(db, claim)
    assert not publish_pdf(db, claim, candidate, storage)
    assert sweep_pdf(db) == 1
    assert (
        db.execute(text("SELECT state FROM report_pdf_archives")).scalar_one()
        == "failed"
    )
    assert (
        db.execute(text("SELECT count(*) FROM report_file_cleanup_tasks")).scalar_one()
        == 1
    )


def test_worker_resolves_published_original_after_lost_publication_reply(
    db, integration_engine, completed_report, monkeypatch, tmp_path
):
    from types import SimpleNamespace
    import fitz
    from app.schemas.report_pdf_archive import PdfClaim

    monkeypatch.setattr(settings, "REPORT_ARCHIVE_ROOT", str(tmp_path))
    accepted = prepare_pdf_archive(db, 1, completed_report, str(uuid4()))
    factory = sessionmaker(bind=integration_engine, expire_on_commit=False)
    calls = []

    def supervisor(target, payload, **kwargs):
        calls.append(target)
        if len(calls) == 1:
            with fitz.open() as document:
                document.new_page()
                candidate = ArchiveStorage(tmp_path).write_candidate(
                    payload["object_key"], document.tobytes()
                )
            return SimpleNamespace(candidate=candidate, code=None)
        from app.schemas.report_pdf_archive import PdfCandidate

        with factory() as session:
            assert publish_pdf(
                session,
                PdfClaim.model_validate(payload["claim"]),
                PdfCandidate.model_validate(payload["candidate"]),
                ArchiveStorage(tmp_path),
            )
        raise OSError("publication_reply_lost")

    monkeypatch.setattr("app.workers.report_pdf_worker.supervise_pdf", supervisor)
    assert run_pdf_worker_once(factory, "reply-loss-worker")
    db.expire_all()
    archive = db.get(ReportPdfArchive, completed_report)
    assert archive.state == "ready"
    assert archive.published_attempt_id == accepted.attempt_id
    assert len(calls) == 2
    assert (
        db.execute(text("SELECT count(*) FROM report_pdf_attempts")).scalar_one() == 1
    )
    assert (
        db.execute(text("SELECT count(*) FROM report_file_cleanup_tasks")).scalar_one()
        == 0
    )
