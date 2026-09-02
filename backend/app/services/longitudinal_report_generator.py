"""Constrained longitudinal report streaming and persistence."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import AsyncGenerator, Any

from app.services.longitudinal_prediction import prediction_result_to_dict, run_longitudinal_prediction
from app.services.indicator_validation import validate_visits


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

_STAGE_TEXT = {
    "fatty_liver": "未肝硬化阶段",
    "pre_cirrhosis": "未肝硬化阶段",
    "stay_pre_cirrhosis": "维持未肝硬化阶段",
    "cirrhosis": "肝硬化阶段",
    "stay_cirrhosis": "维持肝硬化阶段",
    "hcc": "肝细胞癌阶段",
    "normal": "正常认知阶段",
    "stay_normal": "维持正常认知阶段",
    "mci": "轻度认知障碍阶段",
    "stay_mci": "维持轻度认知障碍阶段",
    "pre_dementia": "痴呆前阶段",
    "dementia": "痴呆阶段",
}


@dataclass(frozen=True)
class IndicatorDisplay:
    name: str
    render_mode: str
    observation_count: int
    unit: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ReportView:
    prediction: dict[str, Any]
    sources: list[dict[str, Any]] = field(default_factory=list)
    input_snapshot: dict[str, Any] = field(default_factory=dict)
    indicator_table: dict[str, IndicatorDisplay] = field(default_factory=dict)


def build_report_view(
    prediction: dict[str, Any],
    sources: list[dict[str, Any]] | None = None,
    input_snapshot: dict[str, Any] | None = None,
) -> ReportView:
    """Build a presentation-only view from persisted structured results."""
    observation = prediction.get("observation") or {}
    indicators = observation.get("indicators") or {}
    snapshot_visits = (input_snapshot or {}).get("visits") or []
    units_by_name: dict[str, set[str]] = {}
    missing_units: set[str] = set()
    for visit in snapshot_visits:
        for raw_indicator in (visit or {}).get("indicators") or []:
            if not isinstance(raw_indicator, dict):
                continue
            raw_name = str(raw_indicator.get("name") or "").strip().lower()
            if not raw_name:
                continue
            unit = str(raw_indicator.get("unit") or "").strip()
            units_by_name.setdefault(raw_name, set())
            if unit:
                units_by_name[raw_name].add(unit)
            else:
                missing_units.add(raw_name)
    displays: dict[str, IndicatorDisplay] = {}
    for name, item in indicators.items():
        if not isinstance(item, dict):
            continue
        count = int(item.get("n_observations") or 0)
        normalized_name = str(name).strip().lower()
        persisted_unit_state = str(item.get("unit_state") or "").strip().lower()
        units = units_by_name.get(normalized_name, set())
        unit_problem = persisted_unit_state in {"conflict", "missing"} or len(units) > 1 or normalized_name in missing_units
        unit = item.get("unit") if item.get("unit") else (next(iter(units), None) if len(units) == 1 else None)
        displays[str(name)] = IndicatorDisplay(
            name=str(name),
            observation_count=count,
            render_mode=(
                "table_only_unit_problem"
                if unit_problem
                else "chart_and_table"
                if count >= 3
                else "table_only_insufficient_observations"
            ),
            unit=unit,
            reason=("单位不一致或缺失" if unit_problem else None),
        )
    return ReportView(
        prediction=dict(prediction),
        sources=list(sources or []),
        input_snapshot=dict(input_snapshot or {}),
        indicator_table=displays,
    )


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


def _markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


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
    if value.get("schema_version") in {
        "longitudinal_prediction.v2",
        "longitudinal_prediction.v3",
    } and isinstance(
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
            "365 天结局模型：已启用并参与本次推理；"
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


def _observed_direction(item: dict[str, Any]) -> str:
    delta = item.get("delta")
    try:
        numeric = float(delta)
    except (TypeError, ValueError):
        return "unavailable"
    if numeric > 0:
        return "rising"
    if numeric < 0:
        return "falling"
    return "stable"


def _stage_prediction_lines(stage: dict[str, Any]) -> list[str]:
    if stage.get("status") != "available" or not stage.get("likely_next_stage"):
        return ["阶段模型暂不可用，未生成下一疾病阶段预测。"]
    likely = _STAGE_TEXT.get(
        str(stage.get("likely_next_stage")), "未识别的阶段类别"
    )
    lines = [f"模型预测的下一疾病阶段：{likely}。"]
    candidates = stage.get("stage_candidates") or []
    if candidates:
        lines.extend(
            [
                "",
                "| 候选阶段 | 模型分数 |",
                "| --- | ---: |",
            ]
        )
        for candidate in candidates:
            raw_stage = str((candidate or {}).get("stage") or "")
            label = _STAGE_TEXT.get(
                raw_stage,
                _DIRECTION_TEXT.get(raw_stage, "未识别的阶段类别"),
            )
            lines.append(
                f"| {_markdown_cell(label)} | {_format_number((candidate or {}).get('model_score'))} |"
            )
        lines.append("候选分数是模型分数，不代表临床概率。")
    return lines


def _trend_prediction_lines(prediction: dict[str, Any]) -> list[str]:
    trends = prediction.get("trend_predictions") or []
    if not trends:
        return ["当前没有已保存的下一次访视指标趋势预测。"]
    lines = [
        "| 指标 | 已观察方向 | 模型预测方向 | 模型状态 |",
        "| --- | --- | --- | --- |",
    ]
    for trend in trends:
        observed = trend.get("observed") or {}
        forecast = trend.get("forecast") or {}
        status = trend.get("model_status") or {}
        available = (
            status.get("status") == "available"
            and forecast.get("status") == "direction_only"
            and forecast.get("basis") == "next_visit_trend_model"
        )
        predicted = (
            _DIRECTION_TEXT.get(str(forecast.get("direction")), "无法估计")
            if available
            else "无法估计"
        )
        status_text = "模型已参与" if available else "模型未参与或推理失败"
        lines.append(
            "| "
            + " | ".join(
                _markdown_cell(value)
                for value in (
                    trend.get("indicator") or "未命名指标",
                    _DIRECTION_TEXT.get(_observed_direction(observed), "无法判断"),
                    predicted,
                    status_text,
                )
            )
            + " |"
        )
    lines.append("已观察方向只描述既往事实；模型预测方向只来自下一次访视趋势模型。")
    return lines


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


def render_longitudinal_markdown(
    prediction: dict[str, Any],
    sources: list[dict[str, Any]] | None = None,
    input_snapshot: dict[str, Any] | None = None,
) -> str:
    view = build_report_view(prediction, sources, input_snapshot)
    prediction = normalize_prediction_for_render(prediction)
    outcome = prediction["outcome_prediction"]
    stage = outcome["stage_projection"]
    observation = prediction.get("observation") or {}
    disease = prediction.get("disease") or {}
    model_status = prediction.get("model_status") or {}
    signal_result = prediction.get("progression_signals") or {}
    signal_count = len(signal_result.get("signals") or []) if isinstance(signal_result, dict) else 0
    model_lines = _model_status_lines(prediction)
    lines = [
        "# 纵向进展预测报告",
        "",
        "## 1. 报告摘要",
        f"数据够用性：已有 {observation.get('visit_count', 0)} 次访视，当前可用于描述已观察变化。",
        (
            "模型是否可用：365 天风险模型已可用。"
            if (model_status.get("outcome") or {}).get("status") == "available"
            else "模型是否可用：365 天风险模型暂不可用，因此未计算未来风险分数。"
        ),
        f"实际看到的信号：当前有 {signal_count} 个关键进展信号。",
        "以上内容分别对应数据事实、模型状态和结构化信号；不构成诊断或治疗建议。",
        "",
        "## 2. 病例与预测范围",
        f"疾病：{disease.get('name') or '未注明'}；访视次数：{observation.get('visit_count', 0)}；观察跨度：{observation.get('observation_span_days', 0)} 天；预测范围：未来 365 天。",
        "",
        "## 3. 数据质量与适用性",
        f"数据质量概况：共记录 {observation.get('visit_count', 0)} 次访视；已纳入 {len(view.indicator_table)} 个指标。",
        "",
        "## 4. 已观察到的纵向变化",
        "下表只描述已经发生的观察事实，不是模型对未来的预测。",
        "",
        "| 指标 | 首次值 | 最近值 | 变化 | 有效观察 | 单位 | 展示说明 |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for name, item in observation.get("indicators", {}).items():
        display = view.indicator_table.get(name)
        if display and display.render_mode == "table_only_unit_problem":
            delta_text = "无法安全比较"
            unit_text = "单位不一致或缺失"
            mode_text = "仅表格：单位问题，未绘制趋势或判断异常"
        elif display and display.render_mode == "chart_and_table":
            delta_text = _format_number(item.get("delta"))
            unit_text = display.unit or "单位未提供"
            mode_text = "可绘制已观察变化图"
        else:
            delta_text = _format_number(item.get("delta"))
            unit_text = (display.unit if display else None) or "单位未提供"
            mode_text = "仅表格：有效观察不足 3 次"
        lines.append(
            "| "
            + " | ".join(
                _markdown_cell(value)
                for value in (
                    name,
                    _format_number(item.get("first")),
                    _format_number(item.get("last")),
                    delta_text,
                    f"{item.get('n_observations', 0)} 次",
                    unit_text,
                    mode_text,
                )
            )
            + " |"
        )
    lines.extend(["", "## 5. 未来 365 天进展风险", "（兼容旧版标题：未来指标趋势预测）"])
    lines.extend(model_lines or [f"模型风险等级：{outcome.get('risk_band') or '当前未提供'}。模型分数：{_format_number(outcome.get('risk_score'))}，不代表临床概率。"])
    if outcome.get("risk_score") is not None and not any("模型分数" in line for line in lines[-4:]):
        lines.append(f"模型风险等级：{outcome.get('risk_band') or '当前未提供'}。模型分数：{_format_number(outcome.get('risk_score'))}；这是模型分数，不代表临床概率。")
    lines.extend(["", "## 6. 阶段模型和下一次随访趋势的可用状态", "（兼容旧版标题：疾病阶段与进展结局预测）"])
    lines.extend([
        "阶段模型：已参与本次推理。" if stage.get("status") == "available" else "阶段模型：尚未配置，因此未预测下一阶段。",
        "趋势模型：已参与本次推理。" if (model_status.get("trend") or {}).get("status") == "available" else "趋势模型：尚未配置，仅展示已观察到的指标变化。",
        "",
        "### 6.1 下一疾病阶段预测",
    ])
    lines.extend(_stage_prediction_lines(stage))
    lines.extend(["", "### 6.2 下一次访视指标趋势预测"])
    lines.extend(_trend_prediction_lines(prediction))
    lines.extend(["", "## 7. 关键进展信号"])
    lines.extend(_signal_lines(prediction))
    lines.extend(["", "## 8. 参考标准和相似病例"])
    source_items = list(sources or [])
    has_reference_range = any(
        source.get("source_type") == "reference_range"
        for source in source_items
        if isinstance(source, dict)
    )
    has_standard_evidence = any(
        source.get("source_type") == "standard_evidence"
        for source in source_items
        if isinstance(source, dict)
    )
    if not has_reference_range:
        lines.append(
            "- 当前来源仅有标准证据，没有可用于数值判断的正式参考范围。"
            if has_standard_evidence
            else "- 当前没有可用的正式参考标准；未进行参考范围异常判断。"
        )
    for source in sources or []:
        lines.append(f"- {_render_source(source)}")
    lines.extend(["", "## 9. 不确定性与局限性"])
    lines.extend([f"- {warning}" for warning in prediction.get("warnings", [])])
    if not prediction.get("warnings"):
        lines.append("- 当前未记录额外限制；仍需结合原始病历进行人工复核。")
    lines.extend(["", "## 10. 人工复核重点", "- 请结合原始病历核对观察条件、单位和标准适用性。", "", "## 11. 模型和数据技术附录", "（兼容旧版标题：技术附录）"])
    release_set = prediction.get("release_set") or {}
    if release_set.get("release_set_id"):
        lines.append(
            "本报告固定使用模型组版本："
            f"{_markdown_cell(release_set.get('release_set_id'))}；"
            f"数据版本：{_markdown_cell(release_set.get('data_release_id') or '未记录')}。"
        )
    lines.append("本报告由结构化模型结果和已保存观察数据生成；不构成诊断或治疗建议。")
    return "\n".join(lines)


async def generate_longitudinal_report(db, report_id: int, case: dict[str, Any], visits: list[dict[str, Any]], adapter, model_registry: dict[str, Any] | None = None, sources: list[dict[str, Any]] | None = None) -> AsyncGenerator[str, None]:
    from app.db.models import AIReport
    try:
        validate_visits(adapter.dataset, visits)
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
        content = render_longitudinal_markdown(payload, sources, case)
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
