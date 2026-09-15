"""Real isolated admission/publication/history transactions; bounded fake external adapters."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from backend.tests.integration.test_numeric_report_admission import environment, submit
from app.db.models import AIReport, ReportGenerationJob
from app.services.report_job_repository import claim_next, publish_completed
from app.services.report_read_service import read_owned_report


@pytest.fixture
def full_environment(environment, monkeypatch, tmp_path):
    from app.core.config import settings
    from app.services import numeric_report_v2_admission as admission, numeric_report_narrative as narrative
    from app.workers import numeric_report_v2 as worker
    from backend.tests.test_numeric_model_bundle import bundle_fixture
    path = tmp_path / 'bundle.json'
    path.write_text(json.dumps(bundle_fixture()),encoding='utf-8')
    monkeypatch.setattr(settings,'NUMERIC_MODEL_BUNDLE',str(path))
    monkeypatch.setattr(admission,'verify_numeric_bundle_runtime',lambda bundle: None)
    monkeypatch.setattr(worker,'verify_numeric_bundle_runtime',lambda bundle: None)
    monkeypatch.setattr(worker,'SessionLocal',environment[0])
    content = {'sections':[{'title':'预测说明','text':'计算表展示模型结果与末次值对照。','citation_ids':[]}],
        'limitations':['缺少符合条件的参考与指南证据，不能判断临床效能。']}
    monkeypatch.setattr(narrative,'_build_llm',lambda model: SimpleNamespace(invoke=lambda messages:
        SimpleNamespace(content=json.dumps(content,ensure_ascii=False),response_metadata={'model_name':'test-response-model'})))
    return environment


def publication_for(environment, report_id):
    from app.workers.report_execution import execute_report
    from app.schemas.report_document import parse_publication
    with environment[0]() as db:
        row, job = db.get(AIReport,report_id), db.get(ReportGenerationJob,report_id)
        payload = dict(report_id=row.id,created_at=row.created_at.isoformat(),snapshot=row.input_snapshot,
            snapshot_sha256=row.input_snapshot_sha256,context=job.generation_context,context_sha256=job.context_sha256)
    messages=[]
    execute_report(payload,messages.append)
    assert messages[-1]['kind']=='publication',messages[-1]
    assert any(m.get('audit',{}).get('task')=='report_narrative' for m in messages)
    return parse_publication(messages[-1]['publication'])


@pytest.mark.parametrize('disease_index',[0,1])
def test_v5_publication_and_history_use_saved_facts(full_environment,client,monkeypatch,disease_index):
    from app.core.config import settings
    environment=full_environment
    key=str(uuid4())
    accepted=submit(environment,disease_index,key=key)
    publication=publication_for(environment,accepted.report_id)
    with environment[0]() as db:
        claim=claim_next(db,'v5-test-worker')
        assert publish_completed(db,claim,publication)
        detail=read_owned_report(db,1,accepted.report_id)
        assert detail.publication_status=='published'
        assert detail.generation_fingerprint_version=='v5'
        assert detail.report_document['narrative']['response_model']=='test-response-model'
        saved=deepcopy(detail.report_document)
    monkeypatch.setattr(settings,'NUMERIC_MODEL_BUNDLE','missing-new-bundle.json')
    assert submit(environment,disease_index,key=key).report_id==accepted.report_id
    with environment[0]() as db:
        assert read_owned_report(db,1,accepted.report_id).report_document==saved
    assert client(2).get(f'/api/v1/operator/reports/{accepted.report_id}').status_code==404


@pytest.mark.parametrize('fence',['cancel','lease'])
def test_v5_publication_respects_cancel_and_lease(full_environment,fence):
    from app.services.report_generation_service import cancel_report_job
    accepted=submit(full_environment)
    publication=publication_for(full_environment,accepted.report_id)
    with full_environment[0]() as db:
        claim=claim_next(db,'v5-fence')
        if fence=='cancel': cancel_report_job(db,1,accepted.report_id)
        else:
            db.execute(text("UPDATE report_generation_jobs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE report_id=:id"),{'id':accepted.report_id})
            db.commit()
        assert publish_completed(db,claim,publication) is False
        assert db.get(AIReport,accepted.report_id).report_document is None


@pytest.mark.parametrize('state',['queued','cancelled','completed'])
def test_v5_downgrade_cannot_discard_pinned_context(full_environment,monkeypatch,state):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.services.report_generation_service import cancel_report_job
    accepted=submit(full_environment)
    if state=='completed':
        publication=publication_for(full_environment,accepted.report_id)
    path=Path(__file__).resolve().parents[2]/'alembic/versions/0030_numeric_full_publication.py'
    spec=importlib.util.spec_from_file_location('migration0030',path)
    migration=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with full_environment[0]() as db:
        if state=='cancelled': cancel_report_job(db,1,accepted.report_id)
        if state=='completed': assert publish_completed(db,claim_next(db,'v5-downgrade'),publication)
        monkeypatch.setattr(migration,'op',Operations(MigrationContext.configure(db.connection())))
        with pytest.raises(RuntimeError,match='discard_saved_facts'): migration.downgrade()


def test_llm_failure_never_publishes_fake_success(full_environment,monkeypatch):
    from app.services import numeric_report_narrative as narrative
    from app.workers.report_execution import execute_report
    def failed(model): raise RuntimeError('private provider failure')
    monkeypatch.setattr(narrative,'_build_llm',failed)
    accepted=submit(full_environment)
    with full_environment[0]() as db:
        row,job=db.get(AIReport,accepted.report_id),db.get(ReportGenerationJob,accepted.report_id)
        payload=dict(report_id=row.id,created_at=row.created_at.isoformat(),snapshot=row.input_snapshot,
            snapshot_sha256=row.input_snapshot_sha256,context=job.generation_context,context_sha256=job.context_sha256)
    messages=[]
    execute_report(payload,messages.append)
    assert messages[-1]['kind']=='error' and messages[-1]['phase']=='rendering'
    assert not any(m['kind']=='publication' for m in messages)
    assert 'private provider failure' not in str(messages)


@pytest.mark.parametrize('change',['prompt','retrieval'])
def test_queued_configuration_change_rejected_before_invocation(full_environment,monkeypatch,change):
    from app.core.config import settings
    from app.services import numeric_report_narrative as narrative
    from app.workers.report_execution import execute_report
    accepted=submit(full_environment)
    if change=='prompt': monkeypatch.setattr(narrative,'PROMPT','new generation prompt')
    else: monkeypatch.setattr(settings,'VECTOR_COLLECTION_NAME','different_collection')
    with full_environment[0]() as db:
        row,job=db.get(AIReport,accepted.report_id),db.get(ReportGenerationJob,accepted.report_id)
        payload=dict(report_id=row.id,created_at=row.created_at.isoformat(),snapshot=row.input_snapshot,
            snapshot_sha256=row.input_snapshot_sha256,context=job.generation_context,context_sha256=job.context_sha256)
    messages=[]
    execute_report(payload,messages.append)
    assert messages[-1]=={'kind':'error','phase':'model_loading','code':'generation_context_changed'}
    assert not any(m.get('audit',{}).get('kind')=='invocation_started' for m in messages)


@pytest.mark.parametrize('part',['narrative','status','context'])
def test_saved_v5_corruption_is_hidden(full_environment,part):
    accepted=submit(full_environment)
    publication=publication_for(full_environment,accepted.report_id)
    with full_environment[0]() as db:
        assert publish_completed(db,claim_next(db,'v5-corrupt'),publication)
        row=db.get(AIReport,accepted.report_id)
        if part=='status':
            # Reference fixtures may already be indexed in the isolated database.
            # Always alter the saved state; assigning 'available' can be a no-op.
            saved_status=publication.reference_case_status
            assert row.reference_case_status==saved_status
            row.reference_case_status='no_eligible_cases' if saved_status=='available' else 'available'
            assert row.reference_case_status!=saved_status
        elif part=='narrative':
            document=deepcopy(row.report_document)
            document['narrative']['sections'][0]['text']='changed'
            row.report_document=document
        else:
            job=db.get(ReportGenerationJob,accepted.report_id)
            context=deepcopy(job.generation_context)
            context['prompt_sha256']='0'*64
            job.generation_context=context
        db.commit()
        detail=read_owned_report(db,1,accepted.report_id)
        assert detail.publication_status==detail.integrity_status=='invalid'
        assert not detail.content and detail.report_document is None
