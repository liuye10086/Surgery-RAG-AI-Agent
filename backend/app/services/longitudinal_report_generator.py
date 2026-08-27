"""Constrained longitudinal report streaming and persistence."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator, Any

from app.services.longitudinal_prediction import prediction_result_to_dict, run_longitudinal_prediction


SAFE_LONGITUDINAL_ERRORS = {
    "longitudinal_prediction_failed": "纵向预测暂时无法完成",
}

REASON_TEXT = {
    "directional_change": "总体变化方向符合该疾病的关注方向",
    "persistent_direction": "多次观察均朝同一方向变化",
    "latest_above_reference": "最新值高于适用参考范围",
    "latest_below_reference": "最新值低于适用参考范围",
    "reference_unavailable": "当前没有可用的正式参考范围",
    "reference_not_applicable": "现有标准仅作证据参考，未进行数值异常判断",
    "unit_missing": "缺少单位，未进行范围判断",
    "unit_conflict": "单位不一致，无法安全比较",
    "unsupported_unit": "单位不受当前标准支持",
    "insufficient_observations": "有效观察次数不足三次",
    "model_unavailable": "本次没有可用的结局模型",
    "feature_not_used": "该指标未进入本次结局模型特征",
    "contribution_unavailable": "暂无可靠的个体模型贡献信息",
}

_DIRECTION_TEXT = {
    "rising": "上升",
    "falling": "下降",
    "stable": "基本稳定",
    "unavailable": "无法判断",
}

_ATTENTION_TEXT = {
    "priority": "优先关注",
    "attention": "关注",
    "none": "未列为关键信号",
}


def safe_longitudinal_error(code: str) -> tuple[str, str]:
    stable_code = (
        code if code in SAFE_LONGITUDINAL_ERRORS else "longitudinal_prediction_failed"
    )
    return stable_code, SAFE_LONGITUDINAL_ERRORS[stable_code]


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _format_number(value: Any) -> str:
    if value is None:
        return "未估计"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _format_reference_range(source: dict[str, Any]) -> str:
    lower = source.get("lower")
    upper = source.get("upper")
    lower_mark = "[" if source.get("lower_inclusive", True) else "("
    upper_mark = "]" if source.get("upper_inclusive", True) else ")"
    if lower is None and upper is None:
        bounds = "范围未提供"
    elif lower is None:
        bounds = f"(-∞, {_format_number(upper)}{upper_mark}"
    elif upper is None:
        bounds = f"{lower_mark}{_format_number(lower)}, +∞)"
    else:
        bounds = f"{lower_mark}{_format_number(lower)}, {_format_number(upper)}{upper_mark}"
    unit = source.get("unit") or "单位未提供"
    return f"参考范围：{source.get('indicator', '未命名指标')}（{unit}），{bounds}（{source.get('provenance', 'reference')}）"


def _render_source(source: dict[str, Any]) -> str:
    if source.get("source_type") == "reference_range":
        return _format_reference_range(source)
    if source.get("source_type") == "standard_evidence":
        warning = f"；{source['applicability_warning']}" if source.get("applicability_warning") else ""
        return f"标准证据：{source.get('indicator', '未命名指标')}（仅供证据参考，未进入计算）{warning}"
    if source.get("source_type") == "standard_warning":
        return f"标准适用性提示：{source.get('message', '')}"
    if source.get("source_type") == "similar_case":
        features = "、".join(source.get("overlap_features") or []) or "未注明"
        warning = f"；{source['display_warning']}" if source.get("display_warning") else ""
        return f"相似病例：{source.get('patient_label') or '未标记病例'}；关联指标：{features}（{source.get('provenance', 'reference')}）{warning}"
    return f"参考病例：{source.get('patient_label', '未标记来源')}（{source.get('provenance', 'reference')}）"


def normalize_prediction_for_render(prediction: dict[str, Any]) -> dict[str, Any]:
    value = dict(prediction)
    if value.get("schema_version") == "longitudinal_prediction.v2" and isinstance(
        value.get("model_status"), dict
    ):
        return value
    value.setdefault("schema_version", "longitudinal_prediction.v1")
    value["model_status"] = None
    return value


def _model_status_lines(prediction: dict[str, Any]) -> list[str]:
    statuses = prediction.get("model_status")
    if not isinstance(statuses, dict):
        return []
    outcome = statuses.get("outcome") or {}
    stage = statuses.get("stage") or {}
    trend = statuses.get("trend") or {}
    if outcome.get("status") == "available":
        outcome_line = (
            f"365 天结局模型：已启用并参与本次推理；任务 {outcome.get('task')}，"
            f"版本 {outcome.get('model_version') or '未记录'}。"
        )
    elif outcome.get("status") == "disabled":
        outcome_line = "365 天结局模型：未启用，因此未计算风险分数。"
    elif outcome.get("status") == "missing":
        outcome_line = "365 天结局模型：尚未配置，因此未计算风险分数。"
    else:
        outcome_line = "365 天结局模型：与当前契约不兼容，因此未计算风险分数。"
    stage_line = (
        "阶段模型：尚未配置，因此未预测下一阶段。"
        if stage.get("status") != "available"
        else "阶段模型：已参与本次推理。"
    )
    trend_line = (
        "趋势模型：尚未配置，仅展示已观察到的指标变化。"
        if trend.get("status") != "available"
        else "趋势模型：已参与本次推理。"
    )
    return [outcome_line, stage_line, trend_line]


def _signal_lines(prediction: dict[str, Any]) -> list[str]:
    interpretation = prediction.get("progression_signals")
    if not isinstance(interpretation, dict):
        if prediction.get("schema_version") == "longitudinal_prediction.v1":
            return ["历史 v1 报告未保存结构化关键信号，未重新计算。"]
        return ["当前结果未包含结构化关键信号。"]
    signals = interpretation.get("signals")
    if not isinstance(signals, list) or not signals:
        return ["当前没有足够的关键进展信号。"]

    lines: list[str] = []
    for signal in signals:
        if not isinstance(signal, dict):
            continue
        display_name = signal.get("display_name") or signal.get("indicator") or "未命名指标"
        unit = f" {signal['unit']}" if signal.get("unit") else ""
        direction = _DIRECTION_TEXT.get(
            str(signal.get("observed_direction")), "无法判断"
        )
        level = _ATTENTION_TEXT.get(
            str(signal.get("attention_level")), "关注"
        )
        lines.append(
            f"- [{level}] {display_name}：首次 {_format_number(signal.get('first_value'))}{unit}，"
            f"最近 {_format_number(signal.get('latest_value'))}{unit}，总体{direction}；"
            f"共 {signal.get('observation_count', 0)} 次有效观察。"
        )
        reason_texts = [
            REASON_TEXT[code]
            for code in signal.get("reason_codes") or []
            if code in REASON_TEXT
        ]
        if reason_texts:
            lines.append(f"  - 判断依据：{'；'.join(reason_texts)}。")
        if signal.get("used_by_outcome_model"):
            features = "、".join(signal.get("model_feature_names") or []) or "未记录"
            lines.append(f"  - 模型关系：本次结局模型使用了派生特征 {features}。")
        else:
            lines.append("  - 模型关系：未确认本次结局模型使用了该指标。")
        if (
            signal.get("model_contribution_status") in {"unavailable", "not_supported"}
            and "contribution_unavailable" not in (signal.get("reason_codes") or [])
        ):
            lines.append("  - 暂无可靠的个体模型贡献信息。")
        for limitation in signal.get("limitations") or []:
            lines.append(f"  - 局限：{limitation}。")
    return lines or ["当前没有足够的关键进展信号。"]


def render_longitudinal_markdown(prediction: dict[str, Any], sources: list[dict[str, Any]] | None = None) -> str:
    prediction = normalize_prediction_for_render(prediction)
    outcome = prediction["outcome_prediction"]
    stage = outcome["stage_projection"]
    lines = [
        "# 纵向进展预测报告",
        "",
        "## 1. 报告摘要",
        f"模型风险等级：{outcome.get('risk_band') or '未估计'}。模型分数：{_format_number(outcome.get('risk_score'))}，不代表临床概率。",
        "",
        "## 2. 病例与数据概况",
        f"疾病：{prediction['disease'].get('name')}；访视次数：{prediction['observation'].get('visit_count')}；观察跨度：{prediction['observation'].get('observation_span_days')} 天。",
        "",
        "## 3. 已观察到的纵向变化",
    ]
    for name, item in prediction["observation"].get("indicators", {}).items():
        lines.append(f"- {name}: 首次 {_format_number(item.get('first'))}，最近 {_format_number(item.get('last'))}，变化 {_format_number(item.get('delta'))}，趋势斜率 {_format_number(item.get('slope'))}。")
    lines.extend(["", "## 4. 未来指标趋势预测"])
    for item in prediction.get("trend_predictions", []):
        forecast = item["forecast"]
        lines.append(f"- {item['indicator']}: {forecast.get('direction') or '不可估计'}（{forecast['status']}）。")
    lines.extend(["", "## 5. 疾病阶段与进展结局预测", f"阶段模型状态：{stage['status']}。", f"可能下一阶段：{stage.get('likely_next_stage') or '未估计'}。", "", "## 6. 关键进展信号"])
    lines[lines.index("## 5. 疾病阶段与进展结局预测") + 1:lines.index("## 5. 疾病阶段与进展结局预测") + 1] = _model_status_lines(prediction)
    lines.extend(_signal_lines(prediction))
    lines.extend(["", "## 7. 相似病例与参考依据"])
    for source in sources or []:
        lines.append(f"- {_render_source(source)}")
    lines.extend(["", "## 8. 不确定性与局限性"])
    lines.extend([f"- {warning}" for warning in prediction.get("warnings", [])])
    lines.extend(["", "## 9. 随访与人工复核建议", "建议由专业人员结合完整病史、检查结果和实际随访情况复核。", "", "## 10. 技术附录", "本报告由结构化模型结果生成；不构成诊断或治疗建议。"])
    return "\n".join(lines)


async def generate_longitudinal_report(db, report_id: int, case: dict[str, Any], visits: list[dict[str, Any]], adapter, model_registry: dict[str, Any] | None = None, sources: list[dict[str, Any]] | None = None) -> AsyncGenerator[str, None]:
    from app.db.models import AIReport
    try:
        yield _sse("stage", {"stage": "feature_extraction"})
        result = run_longitudinal_prediction(
            case,
            visits,
            adapter,
            model_registry,
            standard_sources=sources,
        )
        payload = prediction_result_to_dict(result)
        payload["evidence"] = {"sources": sources or []}
        yield _sse("prediction", payload)
        content = render_longitudinal_markdown(payload, sources)
        report = db.query(AIReport).filter(AIReport.id == report_id).first()
        if report is not None:
            report.prediction_result = payload
            report.sources = sources or []
            report.content = content
            report.status = "completed"
            report.analysis_type = "longitudinal_predictive"
            db.commit()
        for chunk in (content[i : i + 600] for i in range(0, len(content), 600)):
            yield _sse("delta", {"content": chunk})
        yield _sse("done", {"report_id": report_id, "status": "completed"})
    except (asyncio.CancelledError, GeneratorExit):
        report = db.query(AIReport).filter(AIReport.id == report_id).first()
        if report is not None and report.status == "generating":
            report.status = "cancelled"
            report.error_message = "用户取消生成"
            db.commit()
        return
    except Exception:
        code, message = safe_longitudinal_error("longitudinal_prediction_failed")
        report = db.query(AIReport).filter(AIReport.id == report_id).first()
        if report is not None:
            report.status = "failed"
            report.error_message = code
            db.commit()
        yield _sse("error", {"message": message, "code": code})
