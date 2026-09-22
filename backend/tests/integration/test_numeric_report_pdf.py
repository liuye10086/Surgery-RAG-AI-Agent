"""Real saved v3 publication through Chromium, archive and original delivery."""

import hashlib
import os
from pathlib import Path
from uuid import uuid4

import fitz
import pytest

from backend.tests.integration.test_numeric_report_admission import environment, submit
from app.core.config import settings
from app.db.models import AIReport, ReportPdfArchive, ReportPdfAttempt
from app.services.model_paths import MODEL_DIR
from app.services.report_archive_recovery import restore_pdf_original
from app.services.report_archive_storage import ArchiveStorage
from app.services.report_pdf_archive_service import prepare_pdf_archive
from app.workers.report_worker import run_worker_once
from app.workers.report_pdf_worker import run_pdf_worker_once


@pytest.mark.parametrize('source_kind', ['synthetic', 'real'])
@pytest.mark.parametrize('case_index,disease', [(0, 'ad'), (1, 'fatty_liver')])
def test_numeric_original_archive_delivery_and_recovery(environment, client, monkeypatch, tmp_path, case_index, disease, source_kind):
    manifest = os.environ.get('REPORT_TEST_RENDERER_MANIFEST')
    if not manifest:
        pytest.skip('REPORT_TEST_RENDERER_MANIFEST is required for real Chromium acceptance')
    for flag in ('REPORT_PDF_ENABLED', 'REPORT_PDF_ACCEPTING'):
        monkeypatch.setattr(settings, flag, True)
    monkeypatch.setattr(settings, 'REPORT_PDF_RENDERER_MANIFEST', manifest)
    monkeypatch.setattr(settings, 'REPORT_ARCHIVE_ROOT', str(tmp_path / 'archive'))
    factory, cases = environment
    from test_prediction_case_source import package_fixture
    from app.services.prediction_case_source import seed_prediction_cases
    imported = seed_prediction_cases(factory, package_fixture(tmp_path, source_kind, disease), 1)
    cases = list(cases)
    cases[case_index] = imported[0]
    environment = (factory, cases)
    capability = client(1).get(f'/api/v1/operator/longitudinal-cases/{cases[case_index]}').json()
    assert capability['prediction'] == dict(verified=True, input_readonly=True, report_kind='numeric_prediction', enabled=True)
    assert 'engineering_source' not in capability
    accepted = submit(environment, case_index)
    report_id = accepted.report_id
    assert run_worker_once(factory, MODEL_DIR, 'numeric-pdf-report')
    with factory() as db:
        report = db.get(AIReport, report_id)
        assert report.input_snapshot['numeric_input']['source']['source_kind'] == source_kind
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
        for phrase in ('数值预测报告', '未执行临床标准评价', '6', '12'):
            assert phrase in content
        assert '合成' not in content and 'synthetic' not in content.lower()
        assert ('MMSE' if disease == 'ad' else 'ALT') in content.upper()
        for result in before[1]['prediction']['predictions']:
            assert result['target_date'] in content
            assert f"{result['value']:g}" in content and result['unit'] in content
        assert '历史报告未记录' not in content
        artifact_dir = os.environ.get('NUMERIC_PDF_ACCEPTANCE_OUTPUT')
        if artifact_dir:
            output = Path(artifact_dir) / source_kind
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


class TestHistoryNumericPdf:
    """S6-only real archive acceptance; guard precedes shared database fixtures.

    The original module's tests retain their own database scope. New tests request
    environment/client dynamically only after the dedicated test database guard passes.
    """

    @pytest.fixture(autouse=True)
    def isolated_test_database_guard(self):
        from urllib.parse import urlparse
        from backend.tests.integration.conftest import TEST_DATABASE_URL
        if not TEST_DATABASE_URL:
            pytest.skip('dedicated test database is not configured')
        try:
            target = urlparse(TEST_DATABASE_URL)
            safe = (target.scheme in ('postgresql', 'postgresql+psycopg', 'postgresql+psycopg2')
                and target.hostname in ('localhost', '127.0.0.1', '::1')
                and target.path == '/surgery_rag_test'
                and not target.query and not target.fragment
                and not any(os.environ.get(key) for key in ('PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE', 'PGOPTIONS')))
        except ValueError:
            safe = False
        if not safe:
            raise RuntimeError('test_database_target_rejected')

    @pytest.mark.parametrize('case_index,disease', [(0, 'ad'), (1, 'fatty_liver')])
    def test_v3_archive_original_and_owned_delivery(self, request, monkeypatch, tmp_path, case_index, disease):
        from copy import deepcopy
        from datetime import datetime, timezone
        from app.services.report_job_repository import claim_next, publish_completed
        from app.services.numeric_history_bundle import predict_numeric_history_bundle
        from app.services.numeric_report_v3 import build_numeric_v3_document, build_numeric_v3_publication
        from app.db.models import ReportGenerationJob
        from app.schemas.numeric_report_v3 import NumericGenerationContextV3
        from app.schemas.numeric_report_evidence import NumericRagEvidence
        from app.services.numeric_report_publication import _sha
        from app.services.numeric_report_evidence import _query
        from backend.tests.test_numeric_report_v3 import saved_narrative
        manifest = os.environ.get('REPORT_TEST_RENDERER_MANIFEST')
        if not manifest:
            pytest.skip('REPORT_TEST_RENDERER_MANIFEST is required for real Chromium acceptance')
        bundle = Path(__file__).resolve().parents[3] / 'outputs/numeric-history-integration/2026-09-16-v1/bundle.json'
        if not bundle.is_file():
            pytest.skip('sealed history bundle is unavailable')
        monkeypatch.setattr(settings, 'NUMERIC_MODEL_BUNDLE', str(bundle))
        environment = request.getfixturevalue('environment')
        client = request.getfixturevalue('client')
        factory, cases = environment
        from backend.tests.test_numeric_history_print_presentation import history_package_fixture
        from app.services.prediction_case_source import seed_prediction_cases
        # A separate fictional package creates fresh visits and binds a new case
        # once. Existing seeded inputs and their source identities stay intact.
        imported = seed_prediction_cases(factory, history_package_fixture(tmp_path, disease), 1)
        cases = list(cases)
        cases[case_index] = imported[0]
        environment = factory, cases
        accepted = submit(environment, case_index)
        report_id = accepted.report_id
        # No external LLM: this archive-specific test publishes a valid controlled
        # narrative; the actual API/worker/RAG/LLM chain is a separate S6 case.
        with factory() as db:
            report = db.get(AIReport, report_id)
            context = NumericGenerationContextV3.model_validate(db.get(ReportGenerationJob, report_id).generation_context)
            prediction = predict_numeric_history_bundle(context.numeric_input, context.model_bundle)
            evidence = NumericRagEvidence(input_sha256=context.numeric_input_sha256, context_sha256=_sha(context.references),
                status='empty', vector_status='not_run', fulltext_status='not_run',
                embedding_model=context.retrieval_settings.embedding_model, collection_name=context.retrieval_settings.collection_name,
                rrf_k=context.retrieval_settings.rrf_k, query=_query(context.numeric_input), items=[])
            document = build_numeric_v3_document(report_id, report.created_at or datetime.now(timezone.utc), report.input_snapshot,
                context, prediction, evidence, saved_narrative(context, prediction, evidence))
            publication = build_numeric_v3_publication(report.input_snapshot, prediction, document)
            assert publish_completed(db, claim_next(db, 'phase4-pdf-publication'), publication)
        for flag in ('REPORT_PDF_ENABLED', 'REPORT_PDF_ACCEPTING'):
            monkeypatch.setattr(settings, flag, True)
        monkeypatch.setattr(settings, 'REPORT_PDF_RENDERER_MANIFEST', manifest)
        monkeypatch.setattr(settings, 'REPORT_ARCHIVE_ROOT', str(tmp_path / 'phase4-archive'))
        with factory() as db:
            before = deepcopy(db.get(AIReport, report_id).report_document)
            archive_request = prepare_pdf_archive(db, 1, report_id, str(uuid4()))
        assert run_pdf_worker_once(factory, 'phase4-pdf')
        with factory() as db:
            archive = db.get(ReportPdfArchive, report_id)
            assert archive.state == 'ready', archive.last_error_code
            assert archive.published_attempt_id == archive_request.attempt_id
            digest = archive.pdf_sha256
            object_key = db.get(ReportPdfAttempt, archive.published_attempt_id).object_key
        endpoint = f'/api/v1/operator/reports/{report_id}/download'
        assert client(2).get(endpoint).status_code == 404
        original = client(1).get(endpoint)
        assert original.status_code == 200 and original.headers['cache-control'] == 'private, no-store'
        assert hashlib.sha256(original.content).hexdigest() == digest
        with fitz.open(stream=original.content, filetype='pdf') as pdf:
            text = ''.join(''.join(page.get_text() for page in pdf).split())
            assert ('MMSE' if disease == 'ad' else 'ALT') in text
            assert '模型状态与原因' in text and '基线状态与原因' in text
            if disease == 'ad':
                assert '历史不足' in text and '随机森林' in text
                assert before['prediction']['predictions'][1]['status'] == 'abstain'
                assert before['prediction']['baseline_predictions'][1]['status'] == 'available'
            assert 'raw_prediction' not in text and 'source_binding' not in text
        monkeypatch.setattr('app.services.pdf_generator.generate_pdf', lambda *a, **kw: pytest.fail('original delivery must not render'))
        monkeypatch.setattr(settings, 'NUMERIC_MODEL_BUNDLE', 'unavailable-after-publication.json')
        assert client(1).get(endpoint).content == original.content
        storage = ArchiveStorage(settings.REPORT_ARCHIVE_ROOT)
        storage.candidate_path(object_key).write_bytes(b'corrupt')
        assert client(1).get(endpoint).status_code == 409
        backup = tmp_path / 'original.pdf'; backup.write_bytes(original.content)
        with factory() as db:
            assert restore_pdf_original(db, report_id, backup, storage.root, apply=True)['applied'] is True
        assert client(1).get(endpoint).content == original.content
        with factory() as db:
            assert db.get(AIReport, report_id).report_document == before
