from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import pytest


def v3_inputs(disease='ad', history_state='observed', failure=None):
    from test_numeric_report_publication import fixture
    from test_numeric_prediction import numeric_fixture
    from test_numeric_history_bundle import history_bundle_fixture
    from app.schemas.numeric_prediction import NumericInput
    from app.schemas.numeric_history_bundle import NumericHistoryBundle
    from app.schemas.numeric_report_v3 import NumericGenerationContextV3, numeric_v3_algorithms
    from app.schemas.numeric_report_evidence import NumericReferenceContext, NumericRagEvidence
    from app.services.numeric_history_bundle import predict_numeric_history_bundle
    from app.services.numeric_report_narrative_v2 import PROMPT
    from app.services.numeric_report_v2_admission import current_numeric_retrieval_settings
    from app.services.numeric_report_evidence import _query
    from app.services.numeric_report_publication import _sha, _saved_input_sha256
    from app.services.report_integrity import compute_input_snapshot_sha256
    snapshot, _ = fixture(disease)
    raw = numeric_fixture(disease)
    if history_state != 'observed':
        for packet in raw['packets']:
            packet['input_observations'] = [r for r in packet['input_observations'] if r['observation_id'] == packet['anchor_observation_id']]
            packet.update(history_state=history_state, history_coverage='complete')
    numeric = NumericInput.model_validate(raw)
    snapshot['numeric_input'] = numeric.model_dump(mode='json')
    snapshot['visits'] = [dict(visit_date=r.measured_on.isoformat(), visit_index=i,
        indicators=[dict(name=r.indicator, value=r.value, unit=r.unit)], notes=None, visit_context={'method':r.method})
        for i,r in enumerate(sorted(numeric.packets[0].input_observations,key=lambda r:(r.measured_on,r.observation_id)),1)]
    snapshot['input_snapshot_sha256'] = compute_input_snapshot_sha256(snapshot)
    raw_bundle = history_bundle_fixture()
    if failure in ('bounds', 'standardization', 'nonfinite'):
        from test_numeric_history_bundle import rehash_model, evidence_fixture
        model = raw_bundle['history_model']
        if failure == 'standardization':
            model['std'][0] = model['scale'][0] = 1e-300
        else:
            for tree in model['trees']:
                tree['nodes'][0]['value'] = 50.0 if failure == 'bounds' else 1.7e308
        rehash_model(model)
        raw_bundle['history_evidence'] = evidence_fixture(model)
    bundle = NumericHistoryBundle.model_validate(raw_bundle)
    digest = _saved_input_sha256(numeric)
    refs = NumericReferenceContext(input_sha256=digest,disease_code=disease,anchor_date=numeric.anchor_date,
        catalog_sha256=_sha([]),candidates=[])
    algorithm,tasks = numeric_v3_algorithms(bundle)
    context = NumericGenerationContextV3(disease_code=disease,numeric_input=numeric,numeric_input_sha256=digest,
        source_binding_sha256=snapshot['source_binding_sha256'],model_bundle=bundle,algorithm=algorithm,
        task_algorithms=tasks,references=refs,llm_model='deepseek-chat',prompt_text=PROMPT,
        prompt_sha256=hashlib.sha256(PROMPT.encode()).hexdigest(),retrieval_settings=current_numeric_retrieval_settings())
    evidence = NumericRagEvidence(input_sha256=digest,context_sha256=_sha(refs),status='empty',vector_status='not_run',
        fulltext_status='not_run',embedding_model=context.retrieval_settings.embedding_model,
        collection_name=context.retrieval_settings.collection_name,rrf_k=context.retrieval_settings.rrf_k,query=_query(numeric),items=[])
    return snapshot,context,predict_numeric_history_bundle(numeric,bundle),evidence


def good_content():
    return dict(sections=[dict(title='结果阅读说明',text='请按计算表逐项查看有效结果及不可用原因，末次值对照仅供比较。',citation_ids=[]),
        dict(title='参考证据说明',text='当前缺少符合条件的参考，缺少指南证据。',citation_ids=[])],
        limitations=['不能据此判断临床效能。','未来实测结果仍待随访确认。'])


def saved_narrative(context,prediction,evidence,content=None):
    from app.schemas.numeric_report_v3 import NumericNarrativeV2
    from app.services.numeric_report_narrative_v2 import _payload
    from app.services.numeric_report_publication import _sha
    content = content or good_content()
    response = json.dumps(content,ensure_ascii=False)
    return NumericNarrativeV2(**content,model=context.llm_model,response_model='saved-response-model',
        response_text=response,prompt_sha256=context.prompt_sha256,
        input_sha256=_sha(_payload(context.numeric_input,prediction,evidence)),prediction_sha256=_sha(prediction),
        evidence_sha256=_sha(evidence),output_sha256=hashlib.sha256(response.encode()).hexdigest())


def v3_fixture(disease='ad',history_state='observed'):
    from app.services.numeric_report_v3 import build_numeric_v3_document,build_numeric_v3_publication
    snapshot,context,prediction,evidence = v3_inputs(disease,history_state)
    doc = build_numeric_v3_document(7,datetime(2026,9,14,tzinfo=timezone.utc),snapshot,context,prediction,evidence,
        saved_narrative(context,prediction,evidence))
    return snapshot,build_numeric_v3_publication(snapshot,prediction,doc)


def verify(snapshot,raw):
    from app.services.report_integrity import verify_report_integrity
    return verify_report_integrity(snapshot,snapshot['input_snapshot_sha256'],raw['generation_fingerprint'],
        raw['prediction_result'],raw['content'],raw['evidence_snapshot'],raw['evidence_snapshot_sha256'],
        saved_sources=raw['sources'],report_document=raw['report_document'],report_document_sha256=raw['report_document_sha256'],
        generation_fingerprint_version=raw['generation_fingerprint_version']).status


@pytest.mark.parametrize('disease,state',[('ad','observed'),('ad','confirmed_none'),('fatty_liver','observed')])
def test_publication_roundtrip_independent_states(disease,state):
    from app.schemas.report_document import parse_publication
    snapshot,pub = v3_fixture(disease,state)
    assert parse_publication(pub.model_dump(mode='json')) == pub
    assert pub.generation_fingerprint_version == 'v6'
    assert verify(snapshot,pub.model_dump(mode='json')) == 'valid'
    result=pub.report_document.prediction
    if disease == 'ad':
        assert result.predictions[1].status == ('available' if state=='observed' else 'abstain')
        assert result.baseline_predictions[1].status == 'available'
        assert '随机森林' in pub.content and '历史不足' in pub.content if state!='observed' else '随机森林' in pub.content
    assert 'synthetic' not in pub.content and '合成' not in pub.content
    assert '末次值基线' in pub.content


@pytest.mark.parametrize('part',['snapshot','source','context','prompt','algorithm','prediction','baseline','raw_prediction','evidence','response','document','content','sources'])
def test_tampering_is_rejected(part):
    snapshot,pub=v3_fixture()
    raw=pub.model_dump(mode='json'); doc=raw['report_document']
    if part=='snapshot': snapshot['age']+=1
    elif part=='source': doc['numeric_input']['source']['dataset_version']='changed'
    elif part=='context': doc['generation_context']['model_bundle']['history_model']['trees'][0]['nodes'][0]['value']+=1
    elif part=='prompt': doc['generation_context']['prompt_text']+='changed'
    elif part=='algorithm': doc['prediction']['predictions'][1]['algorithm']=doc['prediction']['predictions'][0]['algorithm']
    elif part=='prediction': raw['prediction_result']['predictions'][0]['value']+=1
    elif part=='baseline': doc['prediction']['baseline_predictions'][0]['value']+=1
    elif part=='raw_prediction': doc['prediction']['predictions'][1]['raw_prediction']=100.
    elif part=='evidence': raw['evidence_snapshot']['query']='changed'
    elif part=='response': doc['narrative']['response_text']='{}'
    elif part=='document': doc['identity']['age']+=1
    elif part=='content': raw['content']+='changed'
    else: raw['sources']=[{'chunk_id':1}]
    assert verify(snapshot,raw)=='invalid'


def test_history_has_no_live_dependencies(monkeypatch):
    snapshot,pub=v3_fixture()
    from app.services import numeric_history_bundle as model,numeric_report_evidence as evidence,numeric_report_narrative_v2 as narrative
    def forbidden(*a,**kw): raise AssertionError('live dependency called')
    for name in ('load_numeric_history_bundle','predict_numeric_history_bundle','verify_numeric_history_runtime'):
        monkeypatch.setattr(model,name,forbidden)
    monkeypatch.setattr(evidence,'retrieve_numeric_evidence',forbidden)
    monkeypatch.setattr(narrative,'generate_numeric_narrative_v2',forbidden)
    monkeypatch.setattr(narrative,'filter_output',forbidden)
    monkeypatch.setattr(narrative,'PROMPT','future prompt')
    assert verify(snapshot,pub.model_dump(mode='json'))=='valid'


def saved_row_and_job():
    snapshot,pub=v3_fixture()
    from app.services.report_job_repository import context_hash
    row=dict(id=7,user_id=snapshot['user_id'],disease_id=snapshot['disease_id'],operator_case_id=snapshot['case_id'],
        title='private',query='private',status='completed',error_message=None,download_count=0,
        created_at=pub.report_document.identity.created_at,updated_at=pub.report_document.identity.created_at,
        input_snapshot=snapshot,input_snapshot_sha256=snapshot['input_snapshot_sha256'],
        generation_batch_id=snapshot['generation_batch_id'],analysis_type='numeric_prediction',**pub.model_dump(mode='json'))
    context=pub.report_document.generation_context.model_dump(mode='json')
    job=dict(generation_context=context,context_sha256=context_hash(context),source_case_id=snapshot['case_id'])
    return row,job


@pytest.mark.parametrize('status',['completed','generating','failed','cancelled'])
def test_history_projection_and_terminal_context(status):
    from app.services.report_read_service import project_report
    row,job=saved_row_and_job();row['status']=status
    detail=project_report(row,job)
    assert detail.context_integrity=='valid'
    assert detail.generation_context['schema_version']=='numeric_generation_context.v3'
    assert detail.publication_status==('published' if status=='completed' else 'not_published')
    if status=='completed': assert detail.integrity_status=='valid' and detail.content
    else: assert detail.content=='' and detail.input_snapshot==row['input_snapshot']


def run_worker(monkeypatch,state='confirmed_none',failure=None):
    from app.workers import numeric_report_v3 as worker
    from app.workers.report_execution import execute_report
    from app.services.report_job_repository import context_hash
    from app.core.config import settings
    snapshot,context,prediction,evidence=v3_inputs(history_state=state,failure=failure)
    calls=[]
    class ReadOnlySession:
        def __enter__(self): calls.append('session');return self
        def __exit__(self,*args): pass
        def execute(self,sql):
            assert str(sql)=='SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'
    def runtime(bundle):
        calls.append('runtime')
        assert bundle==context.model_bundle
        if failure=='runtime': raise ValueError('numeric_history_implementation_mismatch')
    def retrieve(db,numeric,refs):
        calls.append('retrieval')
        assert refs==context.references
        if failure=='retrieval': raise ValueError('numeric_retrieval_failed')
        return evidence
    def narrative(numeric,prediction,evidence,*,llm_model):
        calls.append('narrative')
        if failure=='narrative': raise ValueError('numeric_narrative_llm_failed')
        return saved_narrative(context,prediction,evidence)
    monkeypatch.setattr(worker,'SessionLocal',ReadOnlySession)
    monkeypatch.setattr(worker,'verify_numeric_history_runtime',runtime)
    monkeypatch.setattr(worker,'retrieve_numeric_evidence',retrieve)
    monkeypatch.setattr(worker,'generate_numeric_narrative_v2',narrative)
    monkeypatch.setattr(settings,'NUMERIC_MODEL_BUNDLE','not-the-saved-model.json')
    raw=context.model_dump(mode='json')
    if failure=='context': raw['model_bundle']['history_model']['trees'][0]['nodes'][0]['value']+=1
    if failure=='unknown_algorithm': raw['task_algorithms']['ad.mmse.12m']['model_id']='unknown:algorithm'
    if failure=='prompt':
        import app.services.numeric_report_narrative_v2 as prompts
        monkeypatch.setattr(prompts,'PROMPT','different prompt')
    if failure=='retrieval_settings': monkeypatch.setattr(settings,'RETRIEVER_FUSION_K',context.retrieval_settings.rrf_k+1)
    messages=[]
    execute_report(dict(snapshot=snapshot,context=raw,snapshot_sha256=snapshot['input_snapshot_sha256'],
        context_sha256=context_hash(raw),report_id=7,created_at='2026-09-14T00:00:00+00:00'),messages.append)
    return messages,calls


def test_worker_uses_saved_bundle_and_maps_audit(monkeypatch):
    from app.schemas.report_document import parse_publication
    messages,calls=run_worker(monkeypatch)
    assert [m['kind'] for m in messages][-1]=='publication'
    pub=parse_publication(messages[-1]['publication'])
    assert pub.report_document.prediction.predictions[1].status=='abstain'
    audit=[m['audit'] for m in messages if m['kind']=='audit' and m['audit'].get('task')=='ad.mmse.12m'][0]
    assert (audit['result_state'],audit['reason_code'])==('unavailable','history_not_observed')
    assert calls==['runtime','session','retrieval','narrative']


@pytest.mark.parametrize('failure',['runtime','context','unknown_algorithm','prompt','retrieval_settings','retrieval','narrative'])
def test_worker_hard_failures_do_not_publish(monkeypatch,failure):
    messages,calls=run_worker(monkeypatch,failure=failure)
    assert messages[-1]['kind']=='error'
    assert not any(m['kind']=='publication' for m in messages)
    if failure in ('context','unknown_algorithm','runtime','prompt','retrieval_settings'): assert 'retrieval' not in calls
    if failure=='unknown_algorithm': assert calls==[]
    if failure=='retrieval': assert 'narrative' not in calls


def test_recomputed_envelope_cannot_hide_wrong_saved_prediction():
    from app.services.numeric_report_v3 import build_numeric_v3_document
    from app.schemas.numeric_history_prediction import NumericPredictionV3
    snapshot,context,prediction,evidence=v3_inputs()
    for target in ('predictions','baseline_predictions'):
        raw=prediction.model_dump(mode='json');raw[target][0]['value']+=1
        wrong=NumericPredictionV3.model_validate(raw)
        # Valid schema and newly hashed narrative still cannot make incorrect values publishable.
        with pytest.raises(ValueError,match='value_mismatch'):
            build_numeric_v3_document(7,datetime(2026,9,14,tzinfo=timezone.utc),snapshot,context,wrong,evidence,
                saved_narrative(context,wrong,evidence))


def test_model_copy_cannot_bypass_strict_prediction_validation():
    from app.services.numeric_report_v3 import build_numeric_v3_document
    snapshot,context,prediction,evidence=v3_inputs()
    narrative=saved_narrative(context,prediction,evidence)
    wrong=prediction.model_copy(update={'predictions':[]})
    with pytest.raises(ValueError):
        build_numeric_v3_document(7,datetime(2026,9,14,tzinfo=timezone.utc),snapshot,context,wrong,evidence,narrative)


@pytest.mark.parametrize('mutation',['context','fingerprint','document','status','owner','job_case'])
def test_history_projection_rejects_mismatched_saved_facts(mutation):
    from app.services.report_read_service import project_report
    row,job=saved_row_and_job()
    if mutation=='context': job['generation_context']['prompt_text']='changed'
    elif mutation=='fingerprint': row['generation_fingerprint_version']='v5'
    elif mutation=='document': row['report_document']['schema_version']='numeric_report_document.v2'
    elif mutation=='status': row['reference_case_status']='available'
    elif mutation=='owner': row['user_id']+=1
    else: job['source_case_id']+=1
    detail=project_report(row,job)
    assert detail.publication_status=='invalid' and not detail.content and detail.report_document is None


@pytest.mark.parametrize('failure,reason',[('bounds','prediction_out_of_bounds'),('standardization','standardization_error'),('nonfinite','nonfinite_prediction')])
def test_worker_error_results_publish_with_independent_baseline(monkeypatch,failure,reason):
    from app.schemas.report_document import parse_publication
    from app.schemas.report_generation_audit import GenerationAuditEvent
    messages,_=run_worker(monkeypatch,state='observed',failure=failure)
    assert messages[-1]['kind']=='publication'
    pub=parse_publication(messages[-1]['publication'])
    candidate=pub.report_document.prediction.predictions[1]
    baseline=pub.report_document.prediction.baseline_predictions[1]
    assert (candidate.status,candidate.reason,candidate.value)==('error',reason,None)
    assert baseline.status=='available' and baseline.value==22.
    assert candidate.raw_prediction==(50. if failure=='bounds' else None)
    for message in messages:
        if message['kind']=='audit': GenerationAuditEvent.model_validate(message['audit'])
    audit=[m['audit'] for m in messages if m['kind']=='audit' and m['audit'].get('task')=='ad.mmse.12m'][0]
    assert (audit['result_state'],audit['reason_code'])==('unavailable',reason)
    assert '50' not in pub.content if failure=='bounds' else '计算失败' in pub.content


@pytest.mark.parametrize('status',['complete','partial'])
def test_bounded_saved_references_and_citations(status):
    from test_numeric_report_evidence import DB,chunk
    from app.services.numeric_report_evidence import capture_numeric_references
    from app.schemas.numeric_report_v3 import NumericGenerationContextV3
    from app.schemas.numeric_report_evidence import NumericRagEvidence,NumericRetrievedEvidence
    from app.services.numeric_report_v3 import build_numeric_v3_document,build_numeric_v3_publication
    from app.services.numeric_report_publication import _sha
    snapshot,context,prediction,evidence=v3_inputs()
    refs=capture_numeric_references(DB([chunk()]),context.numeric_input)
    raw=context.model_dump(mode='json');raw['references']=refs.model_dump(mode='json')
    context=NumericGenerationContextV3.model_validate(raw)
    item=NumericRetrievedEvidence(**refs.candidates[0].model_dump(),score=1/(context.retrieval_settings.rrf_k+1),
        vector_score=0.8,vector_rank=1)
    raw=evidence.model_dump(mode='json');raw.update(context_sha256=_sha(refs),status=status,vector_status='complete',
        fulltext_status='failed' if status=='partial' else 'complete',items=[item.model_dump(mode='json')])
    evidence=NumericRagEvidence.model_validate(raw)
    content=good_content();content['sections'][1].update(text='参考仅描述已有输入，缺少指南证据。' if status=='complete'
        else '部分检索失败，参考不完整，缺少指南证据。',citation_ids=[item.chunk_id])
    doc=build_numeric_v3_document(7,datetime(2026,9,14,tzinfo=timezone.utc),snapshot,context,prediction,evidence,
        saved_narrative(context,prediction,evidence,content))
    pub=build_numeric_v3_publication(snapshot,prediction,doc)
    assert len(pub.sources)==1 and pub.sources[0]['content']==item.content
    assert pub.reference_case_status=='available' and pub.evidence_status==status
    assert verify(snapshot,pub.model_dump(mode='json'))=='valid'
    damaged=pub.model_dump(mode='json');damaged['sources'][0]['score']+=0.1
    assert verify(snapshot,damaged)=='invalid'


def test_sources_accept_strict_dict_and_reject_invalid_evidence():
    from app.services.numeric_report_v3 import numeric_v3_sources
    _,_,_,evidence=v3_inputs()
    assert numeric_v3_sources(evidence.model_dump(mode='json'))==[]
    invalid=evidence.model_dump(mode='json');invalid['unknown']=True
    with pytest.raises(ValueError): numeric_v3_sources(invalid)
