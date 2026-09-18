"""Deterministic v6 publication. Historical reads use only saved facts."""

from app.schemas.numeric_report_v3 import NumericGenerationContextV3, NumericReportDocumentV3, NumericPublicationV3
from app.schemas.numeric_report import NumericReportIdentity
from app.schemas.numeric_prediction import NumericInput
from app.schemas.numeric_history_prediction import NumericPredictionV3
from app.schemas.numeric_report_evidence import NumericRagEvidence
from app.schemas.numeric_report_v3 import NumericNarrativeV2
from app.services.numeric_report_publication import _raw, _sha, _saved_input_sha256, _text, _STAGES, _REASONS
from app.services.report_integrity import compute_input_snapshot_sha256


def validate_numeric_v3_snapshot(snapshot, context):
    context = NumericGenerationContextV3.model_validate(_raw(context))
    numeric = NumericInput.model_validate(snapshot['numeric_input'])
    if (snapshot.get('schema_version'), snapshot.get('report_kind'), snapshot.get('canonicalization_version'),
            snapshot.get('hash_algorithm'), snapshot.get('disease_code'), snapshot.get('source_binding_sha256'),
            _saved_input_sha256(numeric)) != ('numeric_report_input.v1', 'numeric_prediction', 'v1', 'sha256',
            context.disease_code, context.source_binding_sha256, context.numeric_input_sha256):
        raise ValueError('numeric_snapshot_context_mismatch')
    if numeric != context.numeric_input:
        raise ValueError('numeric_snapshot_input_mismatch')
    if (numeric.disease_code != context.disease_code or numeric.anchor_date != context.references.anchor_date
            or snapshot.get('input_snapshot_sha256') != compute_input_snapshot_sha256(snapshot)):
        raise ValueError('numeric_snapshot_hash_mismatch')
    if (any(type(snapshot.get(k)) is not int or snapshot[k] <= 0 for k in ('case_id', 'user_id', 'disease_id'))
            or snapshot.get('model_options') != {}):
        raise ValueError('numeric_snapshot_identity_invalid')
    observations = sorted(numeric.packets[0].input_observations, key=lambda r: (r.measured_on, r.observation_id))
    visits = [{'visit_date': r.measured_on.isoformat(), 'visit_index': i,
        'indicators': [{'name': r.indicator, 'value': r.value, 'unit': r.unit}],
        'notes': None, 'visit_context': {'method': r.method}} for i, r in enumerate(observations, 1)]
    if snapshot.get('visits') != visits:
        raise ValueError('numeric_display_input_mismatch')
    if any(c.subject_id == numeric.subject_id or c.dependency_group_id == numeric.dependency_group_id
           for c in context.references.candidates):
        raise ValueError('numeric_reference_subject_leakage')
    return context, numeric


def validate_saved_history_prediction(prediction, numeric, context):
    numeric = NumericInput.model_validate(_raw(numeric))
    context = NumericGenerationContextV3.model_validate(_raw(context))
    result = NumericPredictionV3.model_validate(_raw(prediction))
    if (result.disease_code, result.subject_id, result.dependency_group_id, result.anchor_date,
            result.source, result.input_sha256, result.algorithm) != (numeric.disease_code, numeric.subject_id,
            numeric.dependency_group_id, numeric.anchor_date, numeric.source, _saved_input_sha256(numeric), context.algorithm):
        raise ValueError('numeric_prediction_identity_mismatch')
    # Check saved values using only the saved version's arithmetic and parameters.
    # This never loads the active bundle, verifies current runtime, or replaces results.
    import math
    from app.services.numeric_history_features import project_numeric_history_features
    from app.services.numeric_history_bundle import predict_forest_json, _descriptor
    models = {m.task_id: m for m in context.model_bundle.legacy_bundle.models}
    packets = {p.task_id: p for p in numeric.packets}
    baseline = {p.task_id: p for p in result.baseline_predictions}
    for task in result.predictions:
        packet = packets[task.task_id]
        history = task.task_id == 'ad.mmse.12m'
        model = context.model_bundle.history_model if history else models[task.task_id]
        if task.algorithm != context.task_algorithms[task.task_id]:
            raise ValueError('numeric_prediction_algorithm_mismatch')
        anchor = next((r for r in packet.input_observations if r.observation_id == packet.anchor_observation_id), None)
        status = 'available' if packet.input_status == 'available' else 'abstain'
        reason, value, raw = packet.input_reason, None, None
        anchor_value = anchor.value if status == 'available' else None
        base = baseline[task.task_id]
        if (base.status, base.reason, base.value, base.raw_prediction, base.algorithm) != (
                status, reason, anchor_value, None, _descriptor('last_value', _sha({}))):
            raise ValueError('numeric_baseline_value_mismatch')
        if history:
            features = project_numeric_history_features(packet)
            status, reason = features.status, features.reason
        if status == 'available':
            try:
                value = (predict_forest_json([features.anchor_value, features.prior_value, features.slope_per_day], model)
                    if history else (anchor_value-model.mean[0])/model.scale[0]*model.coef[0]+model.intercept)
                if not math.isfinite(value):
                    status, reason, value = 'error', 'nonfinite_prediction', None
                elif value < 0 or task.indicator == 'mmse' and value > 30:
                    status, reason, raw, value = 'error', 'prediction_out_of_bounds', value, None
            except (ArithmeticError, ValueError) as exc:
                reason = str(exc) if str(exc) in ('standardization_error', 'nonfinite_prediction') else 'prediction_calculation_error'
                status, value = 'error', None
        if (task.status, task.reason, task.value, task.raw_prediction) != (status, reason, value, raw):
            raise ValueError('numeric_prediction_value_mismatch')
    return result


def build_numeric_v3_document(report_id, created_at, snapshot, context, prediction, evidence, narrative):
    # Saved-fact checks never use current model selection, retrieval or LLM calls.
    from app.services.numeric_report_evidence import validate_numeric_evidence
    from app.services.numeric_report_narrative_v2 import validate_numeric_narrative_v2
    context, numeric = validate_numeric_v3_snapshot(snapshot, context)
    prediction = validate_saved_history_prediction(prediction, numeric, context)
    evidence = NumericRagEvidence.model_validate(_raw(evidence))
    narrative = NumericNarrativeV2.model_validate(_raw(narrative))
    validate_numeric_evidence(evidence, context.references, numeric)
    validate_numeric_narrative_v2(narrative, numeric, prediction, evidence)
    return NumericReportDocumentV3(identity=NumericReportIdentity(report_id=report_id, created_at=created_at,
        batch_id=snapshot['generation_batch_id'], anonymous_case_code=snapshot['anonymous_case_code'],
        disease_code=snapshot['disease_code'], disease_name=snapshot['disease'], age=snapshot['age'],
        sex=snapshot['sex'], baseline_stage=snapshot['baseline_stage'], anchor_date=numeric.anchor_date),
        generation_context=context, numeric_input=numeric, prediction=prediction, evidence=evidence, narrative=narrative)


def numeric_v3_sources(evidence):
    evidence = NumericRagEvidence.model_validate(_raw(evidence))
    return [{'chunk_id': item.chunk_id, 'document_id': item.document_id, 'title': item.title,
        'content': item.content, 'score': item.score} for item in evidence.items]


_V3_REASONS = {
    **_REASONS,
    'history_coverage_incomplete': '历史不足，历史覆盖不完整，未预测',
    'history_not_observed': '历史不足，缺少已观察历史，未预测',
    'comparable_history_required': '历史不足，缺少可比历史记录，未预测',
    'history_calculation_error': '历史特征计算失败',
    'standardization_error': '特征标准化失败',
    'prediction_calculation_error': '预测计算失败',
    'nonfinite_prediction': '预测计算失败，结果非有限值',
    'prediction_out_of_bounds': '预测计算失败，结果超出允许范围',
}


def _result_description(result):
    if result.status == 'available':
        return '可用'
    prefix = '未预测' if result.status == 'abstain' else '计算失败'
    return prefix + '：' + _V3_REASONS[result.reason]


def render_numeric_v3_document(document):
    doc = NumericReportDocumentV3.model_validate(_raw(document))
    identity = doc.identity
    rows = ['# 数值预测报告', '', '## 匿名病例与输入锚点', '',
        f'匿名编号：{identity.anonymous_case_code}；病种：{"阿尔茨海默病" if identity.disease_code == "ad" else "脂肪肝"}；年龄：{identity.age}；性别：{"女" if identity.sex == "female" else "男"}；已录入基线阶段：{_STAGES[identity.baseline_stage]}。',
        f'输入锚点：{identity.anchor_date.isoformat()}。', '', '## 历史实测输入', '',
        '| 测量日期 | 已知日期 | 指标 | 实测值 | 单位 |', '| --- | --- | --- | --- | --- |']
    for r in sorted(doc.numeric_input.packets[0].input_observations, key=lambda r: (r.measured_on, r.observation_id)):
        rows.append(f'| {r.measured_on} | {r.known_on} | {r.indicator.upper()} | {r.value:g} | {r.unit} |')
    if not doc.numeric_input.packets[0].input_observations:
        rows.append('| — | — | — | 无可用实测输入 | — |')
    rows.extend(['', '## 6／12 月数值预测', '', '| 时距 | 目标日期 | 指标 | 模型预测 | 模型状态与原因 | 末次值基线 | 基线状态与原因 | 单位 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |'])
    baselines = {p.task_id: p for p in doc.prediction.baseline_predictions}
    for p in sorted(doc.prediction.predictions, key=lambda p: p.horizon_months):
        value = '—' if p.value is None else f'{p.value:g}'
        base = baselines[p.task_id].value
        base = '—' if base is None else f'{base:g}'
        rows.append(f'| {p.horizon_months} 月 | {p.target_date} | {p.indicator.upper()} | {value} | {_result_description(p)} | {base} | {_result_description(baselines[p.task_id])} | {p.unit} |')
    rows.extend(['', '末次值基线保持最近实测值，用于比较。模型结果不等同于未来实测结果。', '', '## 报告说明', ''])
    for section in doc.narrative.sections:
        citations = ' '.join(f'〔参考 {c}〕' for c in section.citation_ids)
        rows.extend([f'### {_text(section.title)}', '', f'{_text(section.text)} {citations}'.rstrip(), ''])
    rows.extend(['### 局限与待补充信息', ''])
    rows.extend(f'- {_text(line)}' for line in doc.narrative.limitations)
    rows.extend(['', '## 检索参考', '', {'complete': '检索完成。', 'partial': '部分检索分支失败，以下仅显示实际取得的参考。',
        'empty': '未找到符合条件的参考。'}[doc.evidence.status], '未执行临床标准评价。', ''])
    for item in doc.evidence.items:
        rows.extend([f'### 参考 {item.chunk_id}：{_text(item.title)}', '', _text(item.content), ''])
    rows.extend(['## 模型与生成版本', '', '报告保存完成不表示全部任务预测可用。',
        f'算法版本：{_text(doc.generation_context.algorithm.algorithm_version)}。',
        f'说明生成模型：{_text(doc.narrative.response_model or doc.narrative.model)}。', ''])
    for p in sorted(doc.prediction.predictions, key=lambda p: p.horizon_months):
        method = '随机森林（锚点实测值、最近历史实测值、历史斜率）' if p.algorithm.model_id == 'random_forest:history_v1:value_history' else 'Ridge（锚点实测值）'
        rows.extend([f'{p.horizon_months} 月任务：{method}；{_result_description(p)}。',
            f'任务算法版本：{_text(p.algorithm.algorithm_version)}；特征版本：{_text(p.algorithm.feature_version)}；资格版本：{_text(p.algorithm.eligibility_version)}。', ''])
    return '\n'.join(rows)


def build_numeric_v3_publication(snapshot, prediction, document):
    doc = NumericReportDocumentV3.model_validate(_raw(document))
    rebuilt = build_numeric_v3_document(doc.identity.report_id, doc.identity.created_at, snapshot,
        doc.generation_context, prediction, doc.evidence, doc.narrative)
    if rebuilt != doc:
        raise ValueError('numeric_document_contract_mismatch')
    evidence, prediction = _raw(doc.evidence), _raw(doc.prediction)
    content, sources = render_numeric_v3_document(doc), numeric_v3_sources(doc.evidence)
    fingerprint = _sha({'version': 'v6', 'input_snapshot_sha256': compute_input_snapshot_sha256(snapshot),
        'generation_context': _raw(doc.generation_context), 'prediction_result': prediction, 'content': content,
        'evidence_snapshot': evidence, 'report_document': _raw(doc), 'sources': sources})
    return NumericPublicationV3(content=content, prediction_result=prediction, sources=sources,
        evidence_snapshot=evidence, evidence_snapshot_sha256=_sha(evidence),
        evidence_status='complete' if doc.evidence.status == 'complete' else 'partial',
        reference_case_status='available' if doc.evidence.items else 'reference_query_failed' if doc.evidence.status == 'partial' else 'no_eligible_cases',
        report_document=doc, report_document_sha256=_sha(doc), generation_fingerprint=fingerprint)


def verify_numeric_v3_integrity(snapshot, snapshot_sha256, fingerprint, prediction, content,
        evidence, evidence_sha256, document, document_sha256, saved_sources):
    try:
        if not isinstance(snapshot, dict) or snapshot_sha256 != compute_input_snapshot_sha256(snapshot):
            return False
        rebuilt = build_numeric_v3_publication(snapshot, prediction, document)
        return (rebuilt.generation_fingerprint == fingerprint and rebuilt.content == content
            and rebuilt.prediction_result == prediction and rebuilt.evidence_snapshot == evidence
            and rebuilt.evidence_snapshot_sha256 == evidence_sha256
            and rebuilt.report_document_sha256 == document_sha256 and rebuilt.sources == saved_sources)
    except (ValueError, TypeError, AttributeError, KeyError):
        return False
