import json
from types import SimpleNamespace

import pytest

from test_numeric_report_evidence import DB, chunk, numeric


def facts(monkeypatch):
    from app.services import numeric_report_evidence as service
    from app.services.numeric_prediction import predict_numeric
    from app.rag.pipeline import RetrievedChunk
    c, n = chunk(), numeric()
    monkeypatch.setattr(service, '_vector_search', lambda *a, **kw: [RetrievedChunk(c, 0, vector_score=0.8, vector_rank=1)])
    monkeypatch.setattr(service, '_fulltext_search', lambda *a, **kw: [])
    ctx = service.capture_numeric_references(DB([c]), n)
    return n, predict_numeric(n), service.retrieve_numeric_evidence(DB([c]), n, ctx)


@pytest.mark.parametrize('mutation', ['citation', 'number', 'fullwidth_number', 'chinese_number', 'wrong_algorithm', 'source_label', 'medical', 'error'])
def test_narrative_rejects_unknown_facts_or_failed_call(monkeypatch, mutation):
    from app.services import numeric_report_narrative as service
    n, prediction, evidence = facts(monkeypatch)
    payload = {'sections': [{'title': '预测说明', 'text': '预测表反映固定模型的计算结果。', 'citation_ids': [1]}],
               'limitations': ['缺少指南证据，不能推断疗效。']}
    if mutation == 'citation': payload['sections'][0]['citation_ids'] = [99]
    if mutation == 'number': payload['sections'][0]['text'] = '预测评分为99分。'
    if mutation == 'fullwidth_number': payload['sections'][0]['text'] = '预测评分为９９分。'
    if mutation == 'chinese_number': payload['sections'][0]['text'] = '模型预测值为二十五。'
    if mutation == 'wrong_algorithm': payload['sections'][0]['text'] = '预测由测量序列外推得到。'
    if mutation == 'source_label': payload['sections'][0]['text'] = '这是合成数据。'
    if mutation == 'medical': payload['sections'][0]['text'] = '你患有严重认知病。'
    class LLM:
        def invoke(self, messages):
            if mutation == 'error': raise RuntimeError('secret')
            return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
    monkeypatch.setattr(service, '_build_llm', lambda model: LLM())
    with pytest.raises(ValueError, match='numeric_narrative_'):
        service.generate_numeric_narrative(n, prediction, evidence, llm_model='deepseek-chat')


@pytest.mark.parametrize('source_kind', ['synthetic', 'real'])
def test_narrative_records_response_and_input_hashes(monkeypatch, source_kind):
    from app.services import numeric_report_narrative as service
    n, prediction, evidence = facts(monkeypatch)
    if source_kind == 'real':
        from app.schemas.numeric_prediction import NumericInput
        from app.services.numeric_prediction import predict_numeric, numeric_input_sha256
        from test_numeric_prediction import numeric_fixture
        n = NumericInput.model_validate(numeric_fixture(kind='real'))
        prediction = predict_numeric(n)
        evidence.input_sha256 = numeric_input_sha256(n)
    payload = {'sections': [{'title': '预测说明', 'text': '预测表反映固定模型的计算结果。', 'citation_ids': [1]}],
               'limitations': ['缺少指南证据，不能推断疗效。']}
    class LLM:
        def invoke(self, messages):
            assert 'source_kind' not in messages[1].content
            return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
    monkeypatch.setattr(service, '_build_llm', lambda model: LLM())
    result = service.generate_numeric_narrative(n, prediction, evidence, llm_model='deepseek-chat')
    assert result.status == 'completed'
    assert result.model == 'deepseek-chat'
    assert result.prompt_version == service.PROMPT_VERSION
    assert result.sections[0].citation_ids == [1]
    assert len(result.output_sha256) == len(result.input_sha256) == 64
