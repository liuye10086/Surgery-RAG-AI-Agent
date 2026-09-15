"""Real saved v3 publication through Chromium, archive and original delivery."""

import hashlib
import os
from pathlib import Path
from uuid import uuid4

import fitz
import pytest

from backend.tests.integration.test_synthetic_report_admission import environment, submit
from app.core.config import settings
from app.db.models import AIReport, ReportPdfArchive, ReportPdfAttempt
from app.services.model_paths import MODEL_DIR
from app.services.report_archive_recovery import restore_pdf_original
from app.services.report_archive_storage import ArchiveStorage
from app.services.report_pdf_archive_service import prepare_pdf_archive
from app.workers.report_worker import run_worker_once
from app.workers.report_pdf_worker import run_pdf_worker_once


@pytest.mark.parametrize('case_index,disease', [(0, 'ad'), (1, 'fatty_liver')])
def test_numeric_original_archive_delivery_and_recovery(environment, client, monkeypatch, tmp_path, case_index, disease):
    manifest = os.environ.get('REPORT_TEST_RENDERER_MANIFEST')
    if not manifest:
        pytest.skip('REPORT_TEST_RENDERER_MANIFEST is required for real Chromium acceptance')
    for flag in ('REPORT_PDF_ENABLED', 'REPORT_PDF_ACCEPTING'):
        monkeypatch.setattr(settings, flag, True)
    monkeypatch.setattr(settings, 'REPORT_PDF_RENDERER_MANIFEST', manifest)
    monkeypatch.setattr(settings, 'REPORT_ARCHIVE_ROOT', str(tmp_path / 'archive'))
    factory, cases = environment
    capability = client(1).get(f'/api/v1/operator/longitudinal-cases/{cases[case_index]}').json()
    assert capability['engineering'] == dict(verified=True, input_readonly=True, report_kind='synthetic_numeric', enabled=True)
    assert 'engineering_source' not in capability
    accepted = submit(environment, case_index)
    report_id = accepted.report_id
    assert run_worker_once(factory, MODEL_DIR, 'numeric-pdf-report')
    with factory() as db:
        report = db.get(AIReport, report_id)
        before = (report.content, report.report_document, report.generation_fingerprint, report.updated_at, report.download_count)
        request = prepare_pdf_archive(db, 1, report_id, str(uuid4()))
    assert run_pdf_worker_once(factory, 'numeric-real-pdf')
    with factory() as db:
        archive = db.get(ReportPdfArchive, report_id)
        assert archive.state == 'ready', archive.last_error_code
        assert archive.published_attempt_id == request.attempt_id
        digest = archive.pdf_sha256
        key = db.get(ReportPdfAttempt, archive.published_attempt_id).object_key
    endpoint = f'/api/v1/operator/reports/{report_id}/download'
    assert client(2).get(endpoint).status_code == 404
    original = client(1).get(endpoint)
    assert original.status_code == 200
    assert original.headers['cache-control'] == 'private, no-store'
    assert hashlib.sha256(original.content).hexdigest() == digest
    assert client(1).get(endpoint).content == original.content
    with fitz.open(stream=original.content, filetype='pdf') as document:
        # PDF extraction inserts layout line breaks inside Chinese phrases.
        content = ''.join(''.join(page.get_text() for page in document).split())
        for phrase in ('合成数值报告', '尚无临床有效性结论', '未执行临床标准评价', '6', '12'):
            assert phrase in content
        assert ('MMSE' if disease == 'ad' else 'ALT') in content.upper()
        for result in before[1]['prediction']['predictions']:
            assert result['target_date'] in content
            assert f"{result['value']:g}" in content and result['unit'] in content
        assert '历史报告未记录' not in content
        artifact_dir = os.environ.get('SYNTHETIC_PDF_ACCEPTANCE_OUTPUT')
        if artifact_dir:
            output = Path(artifact_dir)
            output.mkdir(parents=True, exist_ok=True)
            (output / f'{disease}.pdf').write_bytes(original.content)
            for index, page in enumerate(document):
                page.get_pixmap(matrix=fitz.Matrix(1.25, 1.25)).save(output / f'{disease}-{index + 1}.png')
    monkeypatch.setattr('app.services.pdf_generator.generate_pdf', lambda *a, **kw: pytest.fail('delivery must not render'))
    storage = ArchiveStorage(settings.REPORT_ARCHIVE_ROOT)
    storage.candidate_path(key).write_bytes(b'corrupt')
    assert client(1).get(endpoint).status_code == 409
    backup = tmp_path / 'original-backup.pdf'
    backup.write_bytes(original.content)
    with factory() as db:
        assert restore_pdf_original(db, report_id, backup, storage.root)['matches'] is True
        assert restore_pdf_original(db, report_id, backup, storage.root, apply=True)['applied'] is True
    assert client(1).get(endpoint).content == original.content
    with factory() as db:
        report = db.get(AIReport, report_id)
        assert (report.content, report.report_document, report.generation_fingerprint, report.updated_at, report.download_count) == before
