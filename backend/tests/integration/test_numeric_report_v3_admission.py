"""S6 opt-in: real S3 transactions and constraints, never external LLM calls.

The module-level guard runs before the shared fixtures can connect/migrate/TRUNCATE.
These tests are authored during S3 and are not part of its executed validation.
"""
import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier
from urllib.parse import urlparse
from uuid import uuid4

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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from app.db.models import AIReport, OperatorCase, ReportGenerationJob
from app.services.report_generation_service import submit_report_job, ReportJobError

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]
REQUEST = {'report_kind': 'numeric_prediction', 'model_options': {}}


@pytest.fixture
def environment(db, integration_engine, monkeypatch):
    from app.core.config import settings
    from app.services.synthetic_case_source import seed_synthetic_cases
    import json
    bundle = ROOT / 'outputs/numeric-history-integration/2026-09-16-v1/bundle.json'
    package = ROOT / 'outputs/synthetic-prediction-cases/2026-09-14-v1'
    if not bundle.is_file() or not (package / 'patients.jsonl').is_file():
        pytest.skip('sealed S3 model/input artifacts are unavailable')
    monkeypatch.setattr(settings, 'NUMERIC_MODEL_BUNDLE', str(bundle))
    for flag in ('NUMERIC_REPORTS_ENABLED', 'REPORT_JOBS_ENABLED', 'REPORT_JOBS_ACCEPTING'):
        monkeypatch.setattr(settings, flag, True)
    factory = sessionmaker(bind=integration_engine, expire_on_commit=False)
    patients = [json.loads(line) for line in (package / 'patients.jsonl').read_text(encoding='utf-8').splitlines()]
    subjects = [next(row['subject_id'] for row in patients if row['disease'] == disease)
                for disease in ('ad', 'fatty_liver')]
    ids = seed_synthetic_cases(factory, package, 1, subjects)
    return factory, ids


def submit(environment, index=0, key=None, user=1):
    return submit_report_job(user, environment[1][index], key or str(uuid4()), REQUEST, environment[0], '.')


@pytest.mark.parametrize('index', [0, 1])
def test_real_transaction_saves_strict_v3(environment, index):
    from app.schemas.numeric_report_v3 import NumericGenerationContextV3
    from app.services.report_job_repository import context_hash
    accepted = submit(environment, index)
    with environment[0]() as db:
        report = db.get(AIReport, accepted.report_id)
        job = db.get(ReportGenerationJob, accepted.report_id)
        context = NumericGenerationContextV3.model_validate(job.generation_context)
        assert context.numeric_input.model_dump(mode='json') == report.input_snapshot['numeric_input']
        assert len(context.task_algorithms) == 4
        assert job.context_sha256 == context_hash(job.generation_context)
        assert report.analysis_type == 'numeric_prediction' and job.status == 'queued'


def test_concurrent_idempotency_and_saved_context_survive_configuration_change(environment, monkeypatch):
    from app.core.config import settings
    barrier, key = Barrier(2), str(uuid4())
    def run():
        barrier.wait(10)
        return submit(environment, key=key).report_id
    with ThreadPoolExecutor(2) as executor:
        a, b = executor.submit(run), executor.submit(run)
        report_id = a.result()
        assert report_id == b.result()
    with environment[0]() as db:
        saved = deepcopy(db.get(ReportGenerationJob, report_id).generation_context)
        assert db.query(ReportGenerationJob).count() == 1
    monkeypatch.setattr(settings, 'NUMERIC_MODEL_BUNDLE', 'missing.json')
    assert submit(environment, key=key).report_id == report_id
    with environment[0]() as db:
        assert db.get(ReportGenerationJob, report_id).generation_context == saved


@pytest.mark.parametrize('change,code', [('owner', 'case_not_found'), ('role', 'auth_expired'), ('disease', 'disease_disabled')])
def test_real_permissions_leave_no_rows(environment, change, code):
    with environment[0]() as db:
        if change == 'role': db.execute(text("UPDATE users SET role='patient' WHERE id=1"))
        if change == 'disease': db.execute(text('UPDATE diseases SET operator_enabled=false'))
        db.commit()
    with pytest.raises(ReportJobError) as failure:
        submit(environment, user=2 if change == 'owner' else 1)
    assert failure.value.code == code
    with environment[0]() as db:
        assert db.query(AIReport).count() == db.query(ReportGenerationJob).count() == 0


@pytest.mark.parametrize('change,code', [('context', 'generation_context_changed'), ('case', 'case_changed')])
def test_real_double_capture_rolls_back(environment, monkeypatch, change, code):
    from app.services import numeric_model_dispatch as dispatch
    from app.core.config import settings
    original = dispatch.capture_configured_numeric_context
    def capture(snapshot, db):
        context = original(snapshot, db)
        if change == 'context': monkeypatch.setattr(settings, 'DEEPSEEK_MODEL', 'changed-model')
        else:
            from app.services.synthetic_case_source import build_engineering_binding
            # Simulate an independently authorized source revision, keeping its binding valid.
            with environment[0]() as other:
                case = other.get(OperatorCase, environment[1][0])
                numeric = deepcopy(case.engineering_source['numeric_input'])
                case.age = case.age - 1
                case.engineering_source = None
                case.engineering_source = build_engineering_binding(case, numeric)
                other.commit()
        return context
    monkeypatch.setattr(dispatch, 'capture_configured_numeric_context', capture)
    with pytest.raises(ReportJobError) as failure: submit(environment)
    assert failure.value.code == code
    with environment[0]() as db:
        assert db.query(AIReport).count() == db.query(ReportGenerationJob).count() == 0


def migration():
    path = ROOT / 'backend/alembic/versions/0031_numeric_history_publication.py'
    spec = importlib.util.spec_from_file_location('phase4_migration', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.mark.parametrize('state', ['queued', 'cancelled', 'failed'])
def test_real_downgrade_refuses_any_v3_job_state(environment, monkeypatch, state):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.services.report_generation_service import cancel_report_job
    accepted = submit(environment)
    with environment[0]() as db:
        if state != 'queued':
            cancel_report_job(db, 1, accepted.report_id)
            if state == 'failed':
                db.execute(text("UPDATE report_generation_jobs SET status='failed' WHERE report_id=:id"), {'id': accepted.report_id})
                db.commit()
        revision = migration()
        monkeypatch.setattr(revision, 'op', Operations(MigrationContext.configure(db.connection())))
        with pytest.raises(RuntimeError, match='discard_saved_facts'): revision.downgrade()
        assert db.execute(text("SELECT count(*) FROM pg_constraint WHERE conname='ck_ai_reports_numeric_history_publication'")).scalar_one() == 1


@pytest.mark.parametrize('change', ['valid', 'legacy_v5', 'missing_schema', 'null_schema', 'old_schema', 'null_fp', 'old_fp',
    'generating', 'wrong_kind', 'missing_snapshot', 'missing_evidence', 'missing_document_hash'])
def test_postgres_v6_constraint_nulls_and_compatibility(environment, monkeypatch, change):
    payload = dict(user_id=1, disease_id=1, query='fictional constraint fixture', status='completed',
        analysis_type='numeric_prediction', generation_fingerprint_version='v6', generation_fingerprint='a'*64,
        input_snapshot={}, input_snapshot_sha256='b'*64, evidence_snapshot={}, evidence_snapshot_sha256='c'*64,
        report_document={'schema_version': 'numeric_report_document.v3'}, report_document_sha256='d'*64,
        evidence_status='complete', standard_evidence_status='not_requested', reference_case_status='no_eligible_cases')
    if change == 'legacy_v5':
        payload['generation_fingerprint_version'] = 'v5'
        payload['report_document'] = {'schema_version': 'numeric_report_document.v2'}
    elif change == 'missing_schema': payload['report_document'] = {}
    elif change == 'null_schema': payload['report_document'] = {'schema_version': None}
    elif change == 'old_schema': payload['report_document'] = {'schema_version': 'numeric_report_document.v2'}
    elif change == 'null_fp': payload['generation_fingerprint_version'] = None
    elif change == 'old_fp': payload['generation_fingerprint_version'] = 'v5'
    elif change == 'generating': payload['status'] = 'generating'
    elif change == 'wrong_kind': payload['analysis_type'] = 'predictive'
    elif change == 'missing_snapshot': payload['input_snapshot_sha256'] = None
    elif change == 'missing_evidence': payload['evidence_snapshot_sha256'] = None
    elif change == 'missing_document_hash': payload['report_document_sha256'] = None
    with environment[0]() as db:
        db.add(AIReport(**payload))
        if change in ('valid', 'legacy_v5'):
            db.commit()
            assert db.query(AIReport).filter_by(generation_fingerprint_version=payload['generation_fingerprint_version']).count() == 1
            if change == 'valid':
                from alembic.migration import MigrationContext
                from alembic.operations import Operations
                revision = migration()
                monkeypatch.setattr(revision, 'op', Operations(MigrationContext.configure(db.connection())))
                with pytest.raises(RuntimeError, match='discard_saved_facts'): revision.downgrade()
        else:
            with pytest.raises(IntegrityError): db.commit()
            db.rollback()
            assert db.query(AIReport).count() == 0
