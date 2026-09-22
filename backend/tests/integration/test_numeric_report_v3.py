"""S6 opt-in: real v6 publication and history transactions, controlled LLM adapter.

The module-level guard runs before the shared fixtures can connect/migrate/TRUNCATE.
These tests are authored during S4 and are not part of its executed validation.
"""
import os
from copy import deepcopy
from urllib.parse import urlparse

import pytest

_url = os.environ.get('TEST_DATABASE_URL')
if not _url:
    pytest.skip('dedicated test database is not configured', allow_module_level=True)
try:
    _target = urlparse(_url)
    _safe = (_target.scheme in ('postgresql', 'postgresql+psycopg', 'postgresql+psycopg2')
             and _target.hostname in ('localhost', '127.0.0.1', '::1')
             and _target.path == '/surgery_rag_test'
             and not _target.query and not _target.fragment
             and not any(os.environ.get(key) for key in ('PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE', 'PGOPTIONS')))
except ValueError:
    _safe = False
if not _safe:
    raise RuntimeError('test_database_target_rejected')

from sqlalchemy import text
from app.db.models import AIReport, ReportGenerationJob
from app.schemas.report_document import parse_publication
from app.services.report_job_repository import claim_next, publish_completed
from app.services.report_read_service import read_owned_report
from backend.tests.integration.test_numeric_report_v3_admission import environment, submit

pytestmark = pytest.mark.integration


@pytest.fixture
def execution_environment(environment, monkeypatch):
    import json
    from types import SimpleNamespace
    from app.services import numeric_report_narrative_v2 as narrative
    from app.workers import numeric_report_v3 as worker
    from backend.tests.test_numeric_report_v3 import good_content
    monkeypatch.setattr(worker, 'SessionLocal', environment[0])
    def invoke(messages):
        content = good_content()
        payload = json.loads(messages[1].content)
        if payload['retrieval_status'] == 'complete':
            content['sections'][1]['text'] = '参考记录仅用于说明输入，缺少指南证据。'
        elif payload['retrieval_status'] == 'partial':
            content['sections'][1]['text'] = '部分检索失败，参考不完整，缺少指南证据。'
        return SimpleNamespace(content=json.dumps(content, ensure_ascii=False),
            response_metadata={'model_name': 'controlled-integration-response'})
    monkeypatch.setattr(narrative, '_build_llm', lambda _: SimpleNamespace(invoke=invoke))
    return environment


def publication_for(environment, report_id):
    from app.workers.report_execution import execute_report
    with environment[0]() as db:
        row, job = db.get(AIReport, report_id), db.get(ReportGenerationJob, report_id)
        payload = dict(report_id=row.id, created_at=row.created_at.isoformat(), snapshot=row.input_snapshot,
            snapshot_sha256=row.input_snapshot_sha256, context=job.generation_context, context_sha256=job.context_sha256)
    messages = []
    execute_report(payload, messages.append)
    assert messages[-1]['kind'] == 'publication'
    return parse_publication(messages[-1]['publication'])


@pytest.mark.parametrize('disease_index', [0, 1])
def test_v6_real_transaction_publication_history_and_ownership(execution_environment, client, monkeypatch, disease_index):
    from app.core.config import settings
    accepted = submit(execution_environment, disease_index)
    publication = publication_for(execution_environment, accepted.report_id)
    with execution_environment[0]() as db:
        assert publish_completed(db, claim_next(db, 'phase4-s4-test'), publication)
        detail = read_owned_report(db, 1, accepted.report_id)
        assert detail.publication_status == 'published' and detail.integrity_status == 'valid'
        assert detail.generation_fingerprint_version == 'v6'
        assert detail.report_document['narrative']['response_model'] == 'controlled-integration-response'
        saved = deepcopy(detail.report_document)
    monkeypatch.setattr(settings, 'NUMERIC_MODEL_BUNDLE', 'changed-after-admission.json')
    with execution_environment[0]() as db:
        assert read_owned_report(db, 1, accepted.report_id).report_document == saved
    assert client(2).get(f'/api/v1/operator/reports/{accepted.report_id}').status_code == 404


@pytest.mark.parametrize('fence', ['cancel', 'lease', 'deadline'])
def test_v6_atomic_publication_respects_fences(execution_environment, fence):
    from app.services.report_generation_service import cancel_report_job
    accepted = submit(execution_environment)
    publication = publication_for(execution_environment, accepted.report_id)
    with execution_environment[0]() as db:
        claim = claim_next(db, 'phase4-s4-fence')
        if fence == 'cancel':
            cancel_report_job(db, 1, accepted.report_id)
        else:
            column = 'lease_expires_at' if fence == 'lease' else 'run_deadline'
            db.execute(text(f"UPDATE report_generation_jobs SET {column}=clock_timestamp()-interval '1 second' WHERE report_id=:id"), {'id': accepted.report_id})
            db.commit()
        assert publish_completed(db, claim, publication) is False
        assert db.get(AIReport, accepted.report_id).report_document is None


def test_v6_publication_rejects_tampered_candidate_in_transaction(execution_environment):
    accepted = submit(execution_environment)
    publication = publication_for(execution_environment, accepted.report_id)
    damaged = publication.model_copy(update={'content': publication.content + 'changed'})
    with execution_environment[0]() as db:
        claim = claim_next(db, 'phase4-s4-invalid')
        assert publish_completed(db, claim, damaged) is False
        assert db.get(AIReport, accepted.report_id).report_document is None


def test_v6_saved_corruption_is_redacted(execution_environment):
    accepted = submit(execution_environment)
    publication = publication_for(execution_environment, accepted.report_id)
    with execution_environment[0]() as db:
        assert publish_completed(db, claim_next(db, 'phase4-s4-corrupt'), publication)
        report = db.get(AIReport, accepted.report_id)
        document = deepcopy(report.report_document)
        document['narrative']['response_text'] = '{}'
        report.report_document = document
        db.commit()
        detail = read_owned_report(db, 1, accepted.report_id)
        assert detail.publication_status == 'invalid' and detail.integrity_status == 'invalid'
        assert not detail.content and detail.report_document is None
