import json
from types import SimpleNamespace
import pytest
from test_numeric_report_v3 import v3_inputs,good_content


def generate(monkeypatch,content=None,state='observed',failure=None):
    import app.services.numeric_report_narrative_v2 as service
    _,context,prediction,evidence=v3_inputs(history_state=state)
    calls=[]
    def invoke(messages):
        calls.append(messages)
        if failure: raise RuntimeError('private error')
        return SimpleNamespace(content=content or json.dumps(good_content(),ensure_ascii=False),response_metadata={'model_name':'saved-model'})
    monkeypatch.setattr(service,'_build_llm',lambda _: SimpleNamespace(invoke=invoke))
    result=service.generate_numeric_narrative_v2(context.numeric_input,prediction,evidence,llm_model=context.llm_model)
    return result,calls


def test_one_bounded_call_with_descriptors_without_forest(monkeypatch):
    result,calls=generate(monkeypatch,state='confirmed_none')
    assert len(calls)==1 and result.response_model=='saved-model'
    payload=json.loads(calls[0][1].content)
    assert payload['predictions'][1]['status']=='abstain'
    assert payload['baseline_predictions'][1]['status']=='available'
    assert payload['predictions'][1]['algorithm']['model_id']=='random_forest:history_v1:value_history'
    assert 'trees' not in calls[0][1].content and 'training_subject_ids' not in calls[0][1].content


@pytest.mark.parametrize('text,code',[
    ('使用Ridge读取结果。','algorithm_mismatch'),('使用RF读取结果。','algorithm_mismatch'),
    ('使用随机森林。','algorithm_mismatch'),('采用历史斜率。','algorithm_mismatch'),
    ('预测值为22。','numeric_text_forbidden'),('属于合成资料。','source_label_forbidden'),
    ('全部预测成功。','status_mismatch')])
def test_invalid_claims_fail(monkeypatch,text,code):
    content=good_content();content['sections'][0]['text']=text
    with pytest.raises(ValueError,match=code): generate(monkeypatch,json.dumps(content,ensure_ascii=False),state='confirmed_none')


def test_unknown_citation_and_invalid_json_fail(monkeypatch):
    content=good_content();content['sections'][0]['citation_ids']=[99]
    with pytest.raises(ValueError,match='unknown_citation'): generate(monkeypatch,json.dumps(content,ensure_ascii=False))
    with pytest.raises(ValueError,match='response_invalid'): generate(monkeypatch,'not json')


def test_llm_failure_is_not_retried(monkeypatch):
    with pytest.raises(ValueError,match='llm_failed'): generate(monkeypatch,failure=True)


@pytest.mark.parametrize('direction',['input','output'])
def test_content_filter_rejection(monkeypatch,direction):
    import app.services.numeric_report_narrative_v2 as service
    monkeypatch.setattr(service,'filter_'+direction,lambda _:SimpleNamespace(blocked=True,flagged=True))
    with pytest.raises(ValueError,match='filter_rejected'): generate(monkeypatch)


@pytest.mark.parametrize('text',[
    '报告完成不表示全部预测成功。请按计算表查看未预测原因。',
    '本次部分预测成功，其余未预测。',
    '不能认为所有结果均可用。',
])
def test_partial_results_allow_truthful_qualified_explanation(monkeypatch,text):
    content=good_content();content['sections'][0]['text']=text
    result,_=generate(monkeypatch,json.dumps(content,ensure_ascii=False),state='confirmed_none')
    assert result.sections[0].text==text


@pytest.mark.parametrize('text',[
    '缺失结果已由末次值对照替代。',
    '弃权任务已成功预测。',
    '报告完成不表示全部预测成功，但是全部预测成功。',
])
def test_contradictory_replacement_and_separate_assertion_rejected(monkeypatch,text):
    content=good_content();content['sections'][0]['text']=text
    with pytest.raises(ValueError,match='status_mismatch'):
        generate(monkeypatch,json.dumps(content,ensure_ascii=False),state='confirmed_none')


def test_llm_payload_excludes_out_of_bounds_audit_value():
    from app.services.numeric_report_narrative_v2 import _payload
    _,context,prediction,evidence=v3_inputs(failure='bounds')
    assert prediction.predictions[1].raw_prediction==50.
    payload=_payload(context.numeric_input,prediction,evidence)
    assert 'raw_prediction' not in payload['predictions'][1]
    assert payload['predictions'][1]['value'] is None


@pytest.mark.parametrize('path',['generation','history'])
@pytest.mark.parametrize('text',[
    '弃权任务已完成预测。',
    '弃权任务预测完成。',
    '失败任务已完成预测。',
    '未预测结果已由末次值对照替代。',
    '不可用结果已由末次值对照替代。',
    '未预测结果已补齐。',
    '不可用结果已补齐。',
    '全部结果有效。',
])
def test_unavailable_completion_claims_rejected_after_response_rehash(monkeypatch,path,text):
    from test_numeric_report_v3 import saved_narrative
    from app.services.numeric_report_narrative_v2 import validate_numeric_narrative_v2
    content=good_content();content['sections'][0]['text']=text
    with pytest.raises(ValueError,match='numeric_narrative_status_mismatch'):
        if path=='generation':
            generate(monkeypatch,json.dumps(content,ensure_ascii=False),state='confirmed_none')
        else:
            _,context,prediction,evidence=v3_inputs(history_state='confirmed_none')
            # Rebuild both the saved raw response and its matching hash: the
            # semantic validator must reject this, not only the hash checker.
            narrative=saved_narrative(context,prediction,evidence,content)
            validate_numeric_narrative_v2(narrative,context.numeric_input,prediction,evidence)


@pytest.mark.parametrize('path',['generation','history'])
@pytest.mark.parametrize('text',[
    '报告完成不表示弃权任务已完成预测。',
    '不能认为未预测结果已由末次值对照替代。',
    '本次部分预测成功，其余未预测。',
    '不能认为全部结果有效。',
])
def test_unavailable_completion_negations_and_partial_success_remain_valid(monkeypatch,path,text):
    from test_numeric_report_v3 import saved_narrative
    from app.services.numeric_report_narrative_v2 import validate_numeric_narrative_v2
    content=good_content();content['sections'][0]['text']=text
    if path=='generation':
        result,_=generate(monkeypatch,json.dumps(content,ensure_ascii=False),state='confirmed_none')
    else:
        _,context,prediction,evidence=v3_inputs(history_state='confirmed_none')
        narrative=saved_narrative(context,prediction,evidence,content)
        result=validate_numeric_narrative_v2(narrative,context.numeric_input,prediction,evidence)
    assert result.sections[0].text==text
