"""Deterministic engineering publication and historical verification; no inference."""

import hashlib
import html
import json

from app.schemas.report_document import (
    SyntheticEvidenceSnapshot, SyntheticNumericReportDocument,
    SyntheticPublication, SyntheticReportIdentity,
)
from app.schemas.synthetic_numeric_prediction import SyntheticNumericInput, SyntheticNumericPrediction
from app.schemas.synthetic_report_context import SyntheticGenerationContext
from app.services.report_integrity import compute_input_snapshot_sha256


def _raw(value):
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def _sha(value):
    return hashlib.sha256(json.dumps(_raw(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _saved_input_sha256(numeric):
    # Frozen v1 input canonicalization. Importing the live adapter reads source files.
    value = numeric.model_dump(mode="json")
    value["packets"].sort(key=lambda packet: packet["horizon_months"])
    for packet in value["packets"]:
        packet["input_observations"].sort(key=lambda row: (row["measured_on"], row["observation_id"]))
    return _sha(value)


def _validate_saved_prediction(prediction, numeric, context):
    """Validate the saved last-value contract; never execute or load an algorithm."""
    result = SyntheticNumericPrediction.model_validate(_raw(prediction))
    if (result.disease_code, result.subject_id, result.dependency_group_id, result.anchor_date,
        result.source, result.input_sha256, result.algorithm) != (
        numeric.disease_code, numeric.subject_id, numeric.dependency_group_id, numeric.anchor_date,
        numeric.source, _saved_input_sha256(numeric), context.algorithm
    ):
        raise ValueError("numeric_prediction_identity_mismatch")
    packets = {packet.task_id: packet for packet in numeric.packets}
    for task in result.predictions:
        packet = packets[task.task_id]
        anchor = next((row for row in packet.input_observations
            if row.observation_id == packet.anchor_observation_id), None)
        expected_value = anchor.value if packet.input_status == "available" else None
        if (task.status, task.value, task.reason) != (packet.input_status, expected_value, packet.input_reason):
            raise ValueError("numeric_prediction_value_mismatch")
    return result


def validate_synthetic_snapshot(snapshot, context) -> tuple[SyntheticGenerationContext, SyntheticNumericInput]:
    """Validate pinned input facts independently of inference or a saved result."""
    context = SyntheticGenerationContext.model_validate(_raw(context))
    numeric = SyntheticNumericInput.model_validate(snapshot["numeric_input"])
    if (snapshot.get("schema_version"), snapshot.get("report_kind"), snapshot.get("canonicalization_version"),
        snapshot.get("hash_algorithm"), snapshot.get("disease_code"),
        snapshot.get("engineering_source_sha256"), _saved_input_sha256(numeric)) != (
        "synthetic_numeric_report_input.v1", "synthetic_numeric", "v1", "sha256",
        context.disease_code, context.engineering_source_sha256, context.numeric_input_sha256
    ) or numeric.disease_code != context.disease_code:
        raise ValueError("synthetic_snapshot_context_mismatch")
    if snapshot.get("input_snapshot_sha256") != compute_input_snapshot_sha256(snapshot):
        raise ValueError("synthetic_snapshot_hash_mismatch")
    if any(type(snapshot.get(name)) is not int or snapshot[name] <= 0
           for name in ("case_id", "user_id", "disease_id")) or snapshot.get("model_options") != {}:
        raise ValueError("synthetic_snapshot_identity_invalid")
    # Compare measured facts directly, without a current catalog, source files, or DB.
    observations = sorted(numeric.packets[0].input_observations,
        key=lambda row: (row.measured_on, row.observation_id))
    expected_visits = [{"visit_date": row.measured_on.isoformat(), "visit_index": index,
        "indicators": [{"name": row.indicator, "value": row.value, "unit": row.unit}],
        "notes": None, "visit_context": {"method": row.method}}
        for index, row in enumerate(observations, start=1)]
    if snapshot.get("visits") != expected_visits:
        raise ValueError("synthetic_display_input_mismatch")
    return context, numeric


def _validate_snapshot(snapshot, context, prediction):
    context, numeric = validate_synthetic_snapshot(snapshot, context)
    result = _validate_saved_prediction(prediction, numeric, context)
    return context, numeric, result


def build_synthetic_document(report_id, created_at, snapshot, context, prediction):
    context, numeric, prediction = _validate_snapshot(snapshot, context, prediction)
    return SyntheticNumericReportDocument(
        identity=SyntheticReportIdentity(report_id=report_id, created_at=created_at,
            batch_id=snapshot["generation_batch_id"], anonymous_case_code=snapshot["anonymous_case_code"],
            disease_code=snapshot["disease_code"], disease_name=snapshot["disease"],
            age=snapshot["age"], sex=snapshot["sex"], baseline_stage=snapshot["baseline_stage"],
            anchor_date=numeric.anchor_date),
        generation_context=context, numeric_input=numeric, prediction=prediction,
    )


_REASONS = {
    "anchor_unavailable": "锚点实测值不可用",
    "population_not_confirmed": "人群条件尚未确认",
    "population_not_known_at_anchor": "锚点时尚未知晓人群条件",
    "conflicting_history": "历史记录存在冲突",
}
_STAGES = {"normal": "正常阶段", "mci": "轻度认知障碍", "pre_dementia": "痴呆前期",
    "dementia": "痴呆阶段", "pre_cirrhosis": "肝硬化前期", "suspected_cirrhosis": "疑似肝硬化",
    "cirrhosis": "肝硬化", "hcc": "肝细胞癌"}


def _text(value):
    return html.escape(str(value), quote=True).replace("\\", "&#92;").replace("|", "&#124;").replace("\n", " ").replace("\r", " ").replace("`", "&#96;").replace("[", "&#91;").replace("]", "&#93;").replace("*", "&#42;").replace("_", "&#95;")


def render_synthetic_document(document):
    document = SyntheticNumericReportDocument.model_validate(_raw(document))
    identity, numeric = document.identity, document.numeric_input
    disease = "阿尔茨海默病" if identity.disease_code == "ad" else "脂肪肝"
    rows = ["# 合成数值报告", "", "合成数据 · 末次值保持基线 · 尚无临床有效性结论", "",
        "本报告仅用于合成数据的软件工程验证，未启用生产用途。末次值保持仅把锚点实测值作为两个时距的比较基线，不表示病情一定不变。", "",
        "## 匿名病例与输入锚点", "",
        f"匿名编号：{identity.anonymous_case_code}；病种：{disease}；年龄：{identity.age}；性别：{'女' if identity.sex == 'female' else '男'}；已录入基线阶段：{_STAGES[identity.baseline_stage]}。",
        f"输入锚点：{identity.anchor_date.isoformat()}。", "", "## 历史实测输入", "",
        "| 测量日期 | 已知日期 | 指标 | 实测值 | 单位 | 方法 |",
        "| --- | --- | --- | --- | --- | --- |"]
    for observation in sorted(numeric.packets[0].input_observations, key=lambda row: (row.measured_on, row.observation_id)):
        rows.append(f"| {observation.measured_on} | {observation.known_on} | {observation.indicator.upper()} | {observation.value:g} | {observation.unit} | {_text(observation.method)} |")
    if not numeric.packets[0].input_observations:
        rows.append("| — | — | — | 无可用实测输入 | — | — |")
    rows.extend(["", "## 6／12 月基线结果", "",
        "| 时距 | 目标日期 | 指标 | 状态 | 基线值 | 单位 | 原因 |",
        "| --- | --- | --- | --- | --- | --- | --- |"])
    for result in sorted(document.prediction.predictions, key=lambda row: row.horizon_months):
        value = f"{result.value:g}" if result.value is not None else "—"
        rows.append(f"| {result.horizon_months} 月 | {result.target_date} | {result.indicator.upper()} | {'可用' if result.status == 'available' else '不可用'} | {value} | {result.unit} | {_REASONS.get(result.reason, '—')} |")
    packet = numeric.packets[0]
    history = {"observed": "已观察到历史", "confirmed_none": "已确认无历史", "unknown": "历史情况未知"}[packet.history_state]
    rows.extend(["", "## 输入与证据说明", "", f"历史状态：{history}。本基线仅使用可用的锚点值，不根据历史变化外推。",
        "未执行临床标准评价，未检索临床参考病例。不可用结果保留缺失或拒绝原因，不填补数值。", "",
        "## 算法与合成来源", "", "算法：末次值保持（last_value），无拟合比较基线。",
        f"算法版本：{_text(document.generation_context.algorithm.algorithm_version)}。",
        f"合成来源批次：{_text(numeric.source.run_id)}。", ""])
    return "\n".join(rows)


def fingerprint_v3(snapshot, context, prediction, content, evidence, document):
    return _sha({"version": "v3", "input_snapshot_sha256": compute_input_snapshot_sha256(snapshot),
        "generation_context": _raw(context), "prediction_result": _raw(prediction),
        "content": content, "evidence_snapshot": _raw(evidence), "report_document": _raw(document)})


def build_synthetic_publication(snapshot, prediction, document):
    document = SyntheticNumericReportDocument.model_validate(_raw(document))
    rebuilt = build_synthetic_document(document.identity.report_id, document.identity.created_at,
        snapshot, document.generation_context, prediction)
    if rebuilt != document:
        raise ValueError("synthetic_document_contract_mismatch")
    evidence = SyntheticEvidenceSnapshot(batch_id=document.identity.batch_id,
        disease_code=document.identity.disease_code, source=document.numeric_input.source,
        numeric_input_sha256=document.generation_context.numeric_input_sha256,
        engineering_source_sha256=document.generation_context.engineering_source_sha256).model_dump(mode="json")
    prediction = document.prediction.model_dump(mode="json")
    content = render_synthetic_document(document)
    return SyntheticPublication(content=content, prediction_result=prediction, sources=[],
        evidence_snapshot=evidence, evidence_snapshot_sha256=_sha(evidence),
        evidence_status="not_requested", standard_evidence_status="not_requested", reference_case_status="not_requested",
        report_document=document, report_document_sha256=_sha(document),
        generation_fingerprint=fingerprint_v3(snapshot, document.generation_context, prediction, content, evidence, document))


def verify_synthetic_integrity(snapshot, snapshot_sha256, fingerprint, prediction, content,
    evidence, evidence_sha256, document, document_sha256, saved_sources):
    try:
        if not isinstance(snapshot, dict) or snapshot_sha256 != compute_input_snapshot_sha256(snapshot):
            return False
        rebuilt = build_synthetic_publication(snapshot, prediction, document)
        return (rebuilt.generation_fingerprint == fingerprint and rebuilt.content == content
            and rebuilt.prediction_result == prediction and rebuilt.evidence_snapshot == evidence
            and rebuilt.evidence_snapshot_sha256 == evidence_sha256
            and rebuilt.report_document_sha256 == document_sha256 and rebuilt.sources == saved_sources)
    except (ValueError, TypeError, AttributeError, KeyError):
        return False
