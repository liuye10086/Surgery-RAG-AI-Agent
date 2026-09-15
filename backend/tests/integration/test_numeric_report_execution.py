from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import text, null

from backend.tests.integration.test_numeric_report_admission import environment, submit
from app.db.models import AIReport, ReportGenerationJob
from app.services.model_paths import MODEL_DIR
from app.services.report_read_service import read_owned_report, build_pdf_source
from app.workers.report_worker import run_worker_once


@pytest.mark.parametrize('case_index', [0, 1])
def test_http_to_real_worker_to_fixed_history(environment, client, monkeypatch, case_index):
    response = client(1).post(
        f'/api/v1/operator/longitudinal-cases/{environment[1][case_index]}/report-jobs',
        headers={'Idempotency-Key': str(uuid4())}, json={'report_kind': 'numeric_prediction'},
    )
    assert response.status_code == 202
    report_id = response.json()['report_id']
    assert run_worker_once(environment[0], MODEL_DIR, 'synthetic-worker') is True
    with environment[0]() as db:
        report = db.get(AIReport, report_id)
        job = db.get(ReportGenerationJob, report_id)
        assert (report.status, job.status) == ('completed', 'completed')
        assert report.generation_fingerprint_version == 'v4'
        assert report.evidence_status == report.standard_evidence_status == report.reference_case_status == 'not_requested'
        detail = read_owned_report(db, 1, report_id)
        assert detail.publication_status == 'published'
        assert detail.integrity_status == detail.context_integrity == 'valid'
        assert len(detail.prediction_result['predictions']) == 2
        assert {r['horizon_months'] for r in detail.prediction_result['predictions']} == {6, 12}
        assert all(r['status'] == 'available' for r in detail.prediction_result['predictions'])
        assert any(e['kind'] == 'evidence_resolved' and e['result_state'] == 'not_requested'
                   for e in detail.generation_audit['events'])
        saved = deepcopy(detail.model_dump(mode='json'))
        source = build_pdf_source(detail)
        assert source.report_document == saved['report_document']
        assert source.content == saved['content']
        assert source.generation_fingerprint_version == 'v4'
        db.execute(text('DELETE FROM operator_cases WHERE id=:id'), {'id': environment[1][case_index]})
        db.commit()
    from app.services import numeric_prediction as numeric
    def no_current_code(*a, **kw):
        raise AssertionError('historical read must not run current algorithm')
    monkeypatch.setattr(numeric, 'numeric_algorithm_identity', no_current_code)
    monkeypatch.setattr(numeric, 'predict_numeric', no_current_code)
    with environment[0]() as db:
        detail = read_owned_report(db, 1, report_id)
        assert detail.publication_status == 'published'
        assert detail.report_document == saved['report_document']
        assert detail.content == saved['content']
        from app.services.report_history_query import read_history
        from app.schemas.report_history import HistoryFilters
        history = read_history(db, 1, HistoryFilters(), key='test-history-key')
        assert [item.id for item in history.items] == [report_id]
        assert '数值预测报告' in history.items[0].title
        assert history.items[0].model_version_summary is not None
    assert client(2).get(f'/api/v1/operator/reports/{report_id}').status_code == 404
    response = client(1).get(f'/api/v1/operator/reports/{report_id}')
    assert response.status_code == 200
    assert response.json()['publication_status'] == 'published'


def test_cancelled_synthetic_report_exposes_verified_input_audit(environment):
    from app.services.report_generation_service import cancel_report_job
    accepted = submit(environment)
    with environment[0]() as db:
        cancel_report_job(db, 1, accepted.report_id)
        detail = read_owned_report(db, 1, accepted.report_id)
        assert detail.status == 'cancelled'
        assert detail.context_integrity == detail.snapshot_integrity == 'valid'
        assert detail.generation_context['schema_version'] == 'numeric_generation_context.v1'
        assert detail.input_snapshot['report_kind'] == 'numeric_prediction'
        assert detail.content == '' and detail.report_document is None


def publication_for(environment, report_id):
    from app.schemas.report_document import parse_publication
    from app.services.report_job_repository import context_hash
    from app.workers.report_execution import execute_report
    with environment[0]() as db:
        report = db.get(AIReport, report_id)
        job = db.get(ReportGenerationJob, report_id)
        payload = dict(report_id=report.id, created_at=report.created_at.isoformat(),
                       snapshot=deepcopy(report.input_snapshot), snapshot_sha256=report.input_snapshot_sha256,
                       context=deepcopy(job.generation_context), context_sha256=context_hash(job.generation_context),
                       registry_root=str(MODEL_DIR))
    messages = []
    execute_report(payload, messages.append)
    assert messages[-1]['kind'] == 'publication', messages[-1]
    return parse_publication(messages[-1]['publication'])


@pytest.mark.parametrize('fence', ['cancel', 'lease', 'timeout', 'commit_failure'])
def test_synthetic_publication_respects_transaction_and_fences(environment, monkeypatch, fence):
    from app.services.report_job_repository import claim_next, publish_completed, reap_expired
    from app.services.report_generation_service import cancel_report_job
    accepted = submit(environment)
    publication = publication_for(environment, accepted.report_id)
    with environment[0]() as db:
        claim = claim_next(db, 'fenced-worker')
        if fence == 'cancel':
            cancel_report_job(db, 1, accepted.report_id)
        elif fence in ('lease', 'timeout'):
            field = 'lease_expires_at' if fence == 'lease' else 'run_deadline'
            db.execute(text(f"UPDATE report_generation_jobs SET {field}=clock_timestamp()-interval '1 second' WHERE report_id=:id"), {'id': accepted.report_id})
            db.commit()
        if fence == 'commit_failure':
            def fail():
                db.flush()
                raise RuntimeError('test_commit_failure')
            monkeypatch.setattr(db, 'commit', fail)
            with pytest.raises(RuntimeError, match='test_commit_failure'):
                publish_completed(db, claim, publication)
        else:
            assert publish_completed(db, claim, publication) is False
            if fence != 'cancel':
                assert reap_expired(db) == 1
    with environment[0]() as db:
        report = db.get(AIReport, accepted.report_id)
        job = db.get(ReportGenerationJob, accepted.report_id)
        assert report.report_document is None and report.generation_fingerprint is None
        assert (report.status, job.status) == ({'cancel': ('cancelled','cancelled'),
                                               'lease': ('failed','failed'), 'timeout': ('failed','failed'),
                                               'commit_failure': ('generating','running')}[fence])


@pytest.mark.parametrize('field', ['content', 'prediction_result', 'evidence_snapshot', 'report_document', 'context', 'row_owner', 'row_disease', 'row_time', 'context_hash', 'context_version', 'legacy_downgrade'])
def test_saved_synthetic_corruption_is_hidden(environment, field):
    accepted = submit(environment)
    assert run_worker_once(environment[0], MODEL_DIR, 'saved-worker')
    with environment[0]() as db:
        report = db.get(AIReport, accepted.report_id)
        assert report.status == 'completed'
        if field in ('context_hash', 'context_version'):
            from app.services.report_job_repository import context_hash
            job = db.get(ReportGenerationJob, accepted.report_id)
            if field == 'context_hash':
                job.context_sha256 = '0' * 64
            else:
                context = deepcopy(job.generation_context)
                context['schema_version'] = 'numeric_generation_context.v99'
                job.generation_context = context
                job.context_sha256 = context_hash(context)
        elif field == 'context':
            from app.services.report_job_repository import context_hash
            job = db.get(ReportGenerationJob, accepted.report_id)
            context = deepcopy(job.generation_context)
            context['algorithm']['implementation_sha256'] = '0' * 64
            job.generation_context = context
            job.context_sha256 = context_hash(context)
        elif field == 'row_owner':
            report.user_id = 2
        elif field == 'row_disease':
            report.disease_id = 1 if report.disease_id == 2 else 2
        elif field == 'row_time':
            from datetime import timedelta
            report.created_at += timedelta(seconds=1)
        elif field == 'legacy_downgrade':
            report.generation_fingerprint_version = None
            report.generation_fingerprint = None
            report.report_document = null()
            report.report_document_sha256 = None
            report.evidence_snapshot = null()
            report.evidence_snapshot_sha256 = None
            report.evidence_status = report.standard_evidence_status = report.reference_case_status = None
        elif field == 'content':
            report.content += '\nchanged'
        else:
            value = deepcopy(getattr(report, field))
            value['unexpected'] = True
            setattr(report, field, value)
        db.commit()
        detail = read_owned_report(db, 2 if field == 'row_owner' else 1, accepted.report_id)
        assert detail.publication_status == detail.integrity_status == 'invalid'
        assert detail.content == '' and detail.report_document is None and detail.prediction_result == {}


def test_changed_pinned_algorithm_fails_real_worker(environment):
    from app.services.report_job_repository import context_hash
    accepted = submit(environment)
    with environment[0]() as db:
        job = db.get(ReportGenerationJob, accepted.report_id)
        context = deepcopy(job.generation_context)
        context['algorithm']['implementation_sha256'] = '0' * 64
        job.generation_context = context
        job.context_sha256 = context_hash(context)
        db.commit()
    assert run_worker_once(environment[0], MODEL_DIR, 'drift-worker')
    with environment[0]() as db:
        report = db.get(AIReport, accepted.report_id)
        job = db.get(ReportGenerationJob, accepted.report_id)
        assert report.status == job.status == 'failed'
        assert job.error_code == 'generation_context_changed'
        assert report.report_document is None


def test_cancelled_context_must_match_saved_input(environment):
    from app.services.report_generation_service import cancel_report_job
    from app.services.report_job_repository import context_hash
    accepted = submit(environment)
    with environment[0]() as db:
        cancel_report_job(db, 1, accepted.report_id)
        job = db.get(ReportGenerationJob, accepted.report_id)
        context = deepcopy(job.generation_context)
        context['numeric_input_sha256'] = '0' * 64
        job.generation_context = context
        job.context_sha256 = context_hash(context)
        db.commit()
        detail = read_owned_report(db, 1, accepted.report_id)
        assert detail.context_integrity == 'invalid'
        assert detail.generation_context is None


@pytest.mark.parametrize('part', ['batch', 'report_id', 'task', 'date', 'unit', 'source', 'value'])
def test_parent_publication_rejects_wrong_identity_or_result(environment, part):
    from app.schemas.report_document import parse_publication
    from app.services.report_job_repository import claim_next, publish_completed
    accepted = submit(environment)
    publication = publication_for(environment, accepted.report_id)
    raw = publication.model_dump(mode='json')
    if part in ('batch', 'report_id'):
        field = 'batch_id' if part == 'batch' else 'report_id'
        raw['report_document']['identity'][field] = str(uuid4()) if part == 'batch' else 999
        if part == 'batch':
            raw['evidence_snapshot']['batch_id'] = raw['report_document']['identity']['batch_id']
    elif part == 'source':
        raw['prediction_result']['source']['manifest_sha256'] = '0' * 64
    else:
        field, value = {'task': ('task_id', 'ad_mmse_12m'), 'date': ('target_date', '2099-01-01'),
                        'unit': ('unit', 'U/L'), 'value': ('value', 0.0)}[part]
        raw['prediction_result']['predictions'][0][field] = value
    with environment[0]() as db:
        claim = claim_next(db, 'reject-worker')
        try:
            result = publish_completed(db, claim, parse_publication(raw))
        except ValueError:
            db.rollback()
        else:
            assert result is False
    with environment[0]() as db:
        assert db.get(AIReport, accepted.report_id).report_document is None
        assert db.get(ReportGenerationJob, accepted.report_id).status == 'running'


def test_database_forbids_engineering_evidence_in_legacy_rows(environment):
    from sqlalchemy.exc import IntegrityError
    accepted = submit(environment)
    with environment[0]() as db:
        with pytest.raises(IntegrityError):
            db.execute(text("UPDATE ai_reports SET evidence_status='not_requested' WHERE id=:id"), {'id': accepted.report_id})
            db.commit()
        db.rollback()
        assert db.get(AIReport, accepted.report_id).evidence_status is None


def test_migration_refuses_discarding_published_synthetic_identity(environment, monkeypatch):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    accepted = submit(environment)
    assert run_worker_once(environment[0], MODEL_DIR, 'migration-worker')
    path = Path(__file__).resolve().parents[2] / 'alembic/versions/0029_unified_numeric_prediction.py'
    spec = importlib.util.spec_from_file_location('synthetic_publication_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with environment[0]() as db:
        monkeypatch.setattr(migration, 'op', Operations(MigrationContext.configure(db.connection())))
        with pytest.raises(RuntimeError, match='discard_saved_facts'):
            migration.downgrade()
        assert db.get(AIReport, accepted.report_id).generation_fingerprint_version == 'v4'


@pytest.mark.parametrize('state', ['queued', 'cancelled'])
def test_migration_preserves_unpublished_numeric_facts(environment, monkeypatch, state):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.services.report_generation_service import cancel_report_job
    accepted = submit(environment)
    path = Path(__file__).resolve().parents[2] / 'alembic/versions/0029_unified_numeric_prediction.py'
    spec = importlib.util.spec_from_file_location('numeric_unpublished_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with environment[0]() as db:
        if state == 'cancelled':
            cancel_report_job(db, 1, accepted.report_id)
        monkeypatch.setattr(migration, 'op', Operations(MigrationContext.configure(db.connection())))
        with pytest.raises(RuntimeError, match='discard_saved_facts'):
            migration.downgrade()
        assert db.get(AIReport, accepted.report_id).input_snapshot['report_kind'] == 'numeric_prediction'
