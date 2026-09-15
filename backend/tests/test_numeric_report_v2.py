from copy import deepcopy
import pytest
from app.schemas.numeric_report_v2 import NumericReportDocumentV2
from app.services.numeric_report_v2 import verify_numeric_v2_integrity


def v2_fixture(disease='ad'):
    import hashlib
    import json
    from datetime import datetime, timezone
    from test_numeric_report_publication import fixture
    from test_numeric_model_bundle import bundle_fixture
    from app.schemas.numeric_prediction import NumericInput
    from app.schemas.numeric_report_v2 import NumericGenerationContextV2
    from app.schemas.numeric_report_evidence import NumericReferenceContext, NumericRagEvidence, NumericNarrative
    from app.services.numeric_model_bundle import predict_numeric_bundle, trained_numeric_algorithm
    from app.services.numeric_report_narrative import PROMPT, _payload
    from app.services.numeric_report_evidence import _query
    from app.services.numeric_report_v2_admission import current_numeric_retrieval_settings
    from app.services.numeric_report_publication import _sha, _saved_input_sha256
    from app.services.numeric_report_v2 import build_numeric_v2_document, build_numeric_v2_publication
    snapshot, _ = fixture(disease)
    numeric, bundle = NumericInput.model_validate(snapshot['numeric_input']), bundle_fixture()
    digest = _saved_input_sha256(numeric)
    references = NumericReferenceContext(input_sha256=digest, disease_code=disease, anchor_date=numeric.anchor_date,
        catalog_sha256=_sha([]), candidates=[])
    context = NumericGenerationContextV2(disease_code=disease, numeric_input_sha256=digest,
        source_binding_sha256=snapshot['source_binding_sha256'], model_bundle=bundle,
        algorithm=trained_numeric_algorithm(bundle), references=references, llm_model='deepseek-chat',
        prompt_text=PROMPT,prompt_sha256=hashlib.sha256(PROMPT.encode()).hexdigest(),
        retrieval_settings=current_numeric_retrieval_settings())
    prediction = predict_numeric_bundle(numeric, bundle)
    evidence = NumericRagEvidence(input_sha256=digest, context_sha256=_sha(references), status='empty',
        vector_status='not_run', fulltext_status='not_run', embedding_model='BAAI/bge-m3',
        collection_name='surgery_docs', rrf_k=30,
        query=_query(numeric), items=[])
    content = dict(sections=[dict(title='预测说明', text='计算表显示模型结果及末次值对照。', citation_ids=[])],
        limitations=['缺少符合条件的参考与指南证据，不能据此判断临床效能。'])
    response = json.dumps(content, ensure_ascii=False)
    narrative = NumericNarrative(**content, model='deepseek-chat', response_text=response,
        prompt_sha256=hashlib.sha256(PROMPT.encode()).hexdigest(),
        input_sha256=_sha(_payload(numeric,prediction,evidence)), prediction_sha256=_sha(prediction),
        evidence_sha256=_sha(evidence), output_sha256=hashlib.sha256(response.encode()).hexdigest())
    document = build_numeric_v2_document(7, datetime(2026,9,14,tzinfo=timezone.utc), snapshot, context, prediction, evidence, narrative)
    return snapshot, build_numeric_v2_publication(snapshot, prediction, document)


@pytest.mark.parametrize('disease', ['ad', 'fatty_liver'])
def test_v2_saved_trained_values_narrative_and_baseline(disease):
    from app.schemas.report_document import parse_publication
    from app.services.report_integrity import verify_report_integrity
    snapshot, pub = v2_fixture(disease)
    raw = pub.model_dump(mode='json')
    assert parse_publication(raw) == pub
    assert pub.generation_fingerprint_version == 'v5'
    assert all(p.value != b.value for p,b in zip(pub.report_document.prediction.predictions, pub.report_document.prediction.baseline_predictions))
    assert '计算表显示模型结果' in pub.content and '末次值基线' in pub.content
    assert '合成' not in pub.content and 'synthetic' not in pub.content
    assert pub.report_document.numeric_input.source.is_synthetic is True
    check = verify_report_integrity(snapshot, snapshot['input_snapshot_sha256'],pub.generation_fingerprint,
        pub.prediction_result,pub.content,pub.evidence_snapshot,pub.evidence_snapshot_sha256,saved_sources=pub.sources,
        report_document=raw['report_document'],report_document_sha256=pub.report_document_sha256,generation_fingerprint_version='v5')
    assert check.status == 'valid'


@pytest.mark.parametrize('part', ['prediction','baseline','context','narrative','evidence','sources','identity','version'])
def test_v2_saved_facts_reject_tampering(part):
    snapshot, pub = v2_fixture()
    raw = pub.model_dump(mode='json')
    doc = raw['report_document']
    if part == 'prediction': raw['prediction_result']['predictions'][0]['value'] += 1
    elif part == 'baseline': doc['prediction']['baseline_predictions'][0]['value'] += 1
    elif part == 'context': doc['generation_context']['model_bundle']['models'][0]['coef'][0] += 1
    elif part == 'narrative': doc['narrative']['sections'][0]['text'] = 'changed'
    elif part == 'evidence': raw['evidence_snapshot']['status'] = 'complete'
    elif part == 'sources': raw['sources'] = [{'chunk_id': 99}]
    elif part == 'identity': doc['identity']['age'] += 1
    else: doc['schema_version'] = 'numeric_report_document.v99'
    assert not verify_numeric_v2_integrity(snapshot,snapshot['input_snapshot_sha256'],raw['generation_fingerprint'],
        raw['prediction_result'],raw['content'],raw['evidence_snapshot'],raw['evidence_snapshot_sha256'],
        raw['report_document'],raw['report_document_sha256'],raw['sources'])


def test_saved_v2_does_not_use_current_model_or_retrieval(monkeypatch):
    snapshot, pub = v2_fixture()
    from app.services import numeric_model_bundle as models, numeric_report_evidence as evidence, numeric_report_narrative as narrative
    def forbidden(*args, **kwargs): raise AssertionError('live_service_called')
    for name in ('predict_numeric_bundle','load_numeric_model_bundle','verify_numeric_bundle_runtime'):
        monkeypatch.setattr(models,name,forbidden)
    monkeypatch.setattr(evidence,'retrieve_numeric_evidence',forbidden)
    monkeypatch.setattr(narrative,'generate_numeric_narrative',forbidden)
    monkeypatch.setattr(narrative,'PROMPT','different future prompt')
    monkeypatch.setattr(narrative,'filter_output',forbidden)
    assert verify_numeric_v2_integrity(snapshot,snapshot['input_snapshot_sha256'],pub.generation_fingerprint,
        pub.prediction_result,pub.content,pub.evidence_snapshot,pub.evidence_snapshot_sha256,
        pub.report_document.model_dump(mode='json'),pub.report_document_sha256,pub.sources)


def test_v2_pdf_uses_saved_trained_document():
    from app.services.pdf_generator import _markdown_to_safe_html
    _, pub = v2_fixture()
    html = _markdown_to_safe_html(pub.content,pub.prediction_result,pub.evidence_snapshot,
        report_document=pub.report_document.model_dump(mode='json'))
    assert '模型预测' in html and '计算表显示模型结果' in html
    with pytest.raises(ValueError):
        _markdown_to_safe_html(pub.content+'changed',pub.prediction_result,pub.evidence_snapshot,
            report_document=pub.report_document.model_dump(mode='json'))


def test_new_contract_does_not_accept_saved_baseline_document():
    from test_numeric_report_publication import fixture
    _, publication = fixture()
    with pytest.raises(ValueError):
        NumericReportDocumentV2.model_validate(publication.report_document.model_dump(mode='json'))


def test_malformed_saved_publication_never_falls_back_to_baseline():
    from test_numeric_report_publication import fixture
    snapshot, publication = fixture()
    saved = publication.model_dump(mode='json')
    assert not verify_numeric_v2_integrity(snapshot, snapshot['input_snapshot_sha256'],
        saved['generation_fingerprint'],saved['prediction_result'],saved['content'],
        saved['evidence_snapshot'],saved['evidence_snapshot_sha256'],saved['report_document'],
        saved['report_document_sha256'],[])
