"""Constrained longitudinal report streaming and persistence."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator, Any

from app.services.longitudinal_prediction import prediction_result_to_dict, run_longitudinal_prediction


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
    if source.get("source_type") == "similar_case":
        features = "、".join(source.get("overlap_features") or []) or "未注明"
        warning = f"；{source['display_warning']}" if source.get("display_warning") else ""
        return f"相似病例：{source.get('patient_label') or '未标记病例'}；关联指标：{features}（{source.get('provenance', 'reference')}）{warning}"
    return f"参考病例：{source.get('patient_label', '未标记来源')}（{source.get('provenance', 'reference')}）"


def render_longitudinal_markdown(prediction: dict[str, Any], sources: list[dict[str, Any]] | None = None) -> str:
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
    lines.extend([f"- {item['indicator']}: {item['importance'].get('role')}" for item in prediction.get("trend_predictions", [])])
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
        result = run_longitudinal_prediction(case, visits, adapter, model_registry)
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
    except Exception as exc:
        report = db.query(AIReport).filter(AIReport.id == report_id).first()
        if report is not None:
            report.status = "failed"
            report.error_message = str(exc)
            db.commit()
        yield _sse("error", {"message": str(exc)})
