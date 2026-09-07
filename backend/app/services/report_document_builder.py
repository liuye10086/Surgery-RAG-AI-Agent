"""Pure projection of saved inputs, actual model audits and pinned evidence."""

from datetime import date, timedelta
import math

from app.schemas.report_document import (
    ReportDocument,
    ReportIdentity,
    ReportSection,
    ReportSummary,
    ReportTable,
    QualityIssue,
    ObservedChart,
    ChartPoint,
)
from app.services.report_display_labels import (
    SECTION_TITLES,
    display,
    field_label,
    stage_label,
)
from app.services.report_evidence_presentation import build_evidence_section
from app.services.report_review_items import build_review_items


def relative_change_text(first, ratio, unit_state):
    if unit_state != "consistent":
        return "单位不可比较，未计算"
    if first == 0:
        return "首次值为 0，不计算百分比"
    if type(ratio) not in (int, float) or not math.isfinite(ratio):
        return "未记录"
    return f"{ratio * 100:+.2f}%"


def calendar_positions(dates):
    values = [date.fromisoformat(value).toordinal() for value in dates]
    span = max(values) - min(values)
    return [(value - min(values)) / span if span else 0.0 for value in values]


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _table(title, headers, rows):
    return ReportTable(
        title=title, headers=headers, rows=[[display(v) for v in row] for row in rows]
    )


def _context_text(context):
    # The normalized snapshot schema defines these fields. Preserve zero/False.
    return (
        "；".join(
            f"{display(k)}：{display(v)}"
            for k, v in context.items()
            if v is not None and isinstance(v, (str, int, float, bool))
        )
        or "未记录"
    )


def build_report_document(
    report_id, created_at, snapshot, context, prediction, model_runs, evidence
):
    visits = sorted(snapshot["visits"], key=lambda v: str(v["visit_date"]))
    anchor = date.fromisoformat(str(visits[-1]["visit_date"]))
    labels = {item.code: item.label for item in context.indicator_labels}
    identity = ReportIdentity(
        report_id=report_id,
        batch_id=snapshot["generation_batch_id"],
        anonymous_case_code=snapshot.get("anonymous_case_code"),
        disease_code=snapshot["disease_code"],
        disease_name=snapshot.get("disease")
        or snapshot.get("disease_name")
        or display(snapshot["disease_code"]),
        age=snapshot["age"],
        sex=snapshot["sex"],
        baseline_stage=snapshot["baseline_stage"],
        baseline_stage_label=stage_label(snapshot["baseline_stage"]),
        created_at=created_at,
        anchor_date=anchor,
        horizon_days=365,
        prediction_end_date=anchor + timedelta(days=365),
    )

    def issue_location(item):
        if item.indicator:
            label = labels.get(item.indicator, item.indicator)
            return f"访视 {item.visit_index}：{label}" if item.visit_index else label
        if item.field:
            return field_label(item.field, labels)
        return "模型任务" if item.task else "参考病例"

    issues = []

    def issue(code, severity, source, message, impact, action, **location):
        issues.append(
            QualityIssue(
                code=code,
                severity=severity,
                source=source,
                message=message,
                impact=impact,
                action=action,
                **location,
            )
        )

    # Collapse repeated derived-feature warnings to their source indicator.
    # Each task's complete ordered input audit remains in the technical appendix.
    missing_groups = {}
    for run in model_runs:
        for field in run.input_audit.fields:
            if field.state != "present":
                source_field = field.name.split(".")[0]
                missing_groups.setdefault((source_field, field.state), set()).add(
                    run.task
                )
    for (source_field, state), tasks in missing_groups.items():
        allowed = state == "allowed_missing"
        code = (
            "allowed_feature_missing"
            if allowed
            else "required_feature_missing"
            if state == "required_missing"
            else "non_finite_feature"
        )
        issue(
            code,
            "info" if allowed else "warning",
            "input",
            field_label(source_field, labels) + "：" + display(state),
            f"涉及 {len(tasks)} 个模型任务；"
            + ("按配置由模型管道处理" if allowed else "对应任务未参与本次预测"),
            "核对该指标的原始记录；各任务输入状态及插补配置见技术附录",
            indicator=source_field if source_field in labels else None,
            field=source_field,
        )
    for run in model_runs:
        if run.runtime.status != "available":
            issue(
                "prediction_failed"
                if run.input_audit.model_invoked
                else run.runtime.reason_code,
                "warning",
                "model",
                "对应模型未生成有效结果"
                if run.input_audit.model_invoked
                else "对应模型未参与本次预测",
                "不展示该任务预测结果",
                "核查输入并在服务恢复后生成新报告",
                task=run.task,
            )
    observations = prediction["observation"].get("indicators", {})
    charts = []
    for name, obs in observations.items():
        if obs.get("unit_state") != "consistent":
            issue(
                "observation_unit_not_comparable",
                "warning",
                "observation",
                labels.get(name, name) + "：观察单位不能安全比较",
                "不计算可比变化、不绘制连线",
                "核对原始检验单位",
                indicator=name,
            )
        points = []
        for visit in visits:
            indicator = next(
                (i for i in visit["indicators"] if i["name"].lower() == name.lower()),
                None,
            )
            if indicator and _finite(indicator.get("value")):
                points.append(
                    ChartPoint(visit_date=visit["visit_date"], value=indicator["value"])
                )
        if len(points) < context.minimum_signal_observations:
            issue(
                "insufficient_observations",
                "info",
                "observation",
                labels.get(name, name) + "：有效观察次数不足",
                "仅展示已记录数值",
                "按实际随访补充观察",
                indicator=name,
            )
        elif obs.get("unit_state") == "consistent":
            charts.append(
                ObservedChart(
                    indicator=name,
                    label=labels.get(name, name),
                    unit=obs.get("unit") or "",
                    points=points,
                )
            )
    for rule in evidence.bundle.standard.rules:
        matching_visits = [
            index
            for index, visit in enumerate(visits, 1)
            if any(
                i["name"].casefold() == rule.indicator.casefold()
                for i in visit["indicators"]
            )
        ]
        rule_visit = matching_visits[-1] if matching_visits else None
        for missing in rule.conditions.missing:
            issue(
                "standard_context_missing",
                "warning",
                "standard",
                rule.display_name + "：缺少" + display(missing),
                "不能进行该项标准数值解释",
                "核对所列访视检测或量表条件",
                indicator=rule.indicator,
                field=missing,
                visit_index=rule_visit,
            )
        for mismatched in rule.conditions.mismatched:
            issue(
                "standard_not_applicable",
                "info",
                "standard",
                rule.display_name + "：条件不匹配 " + display(mismatched),
                "仅保留证据与不适用说明",
                "核对检测条件与选用标准",
                indicator=rule.indicator,
                field=mismatched,
                visit_index=rule_visit,
            )
    ref_status = evidence.bundle.reference_cases.status
    if ref_status != "available":
        technical = ref_status in ("reference_query_failed", "reference_index_stale")
        issue(
            ref_status,
            "warning" if technical else "info",
            "reference",
            display(ref_status),
            "本次为部分证据" if technical else "不提供相似病例对照",
            "服务恢复后按需生成新报告" if technical else "结合正式标准人工复核",
        )
    signal_data = prediction.get("progression_signals") or {}
    signals = signal_data.get("signals") or []
    for omitted in signal_data.get("omitted_indicators") or []:
        name = omitted.get("indicator") or omitted.get("name")
        if name:
            issue(
                omitted.get("reason_code")
                or omitted.get("reason")
                or "signal_unavailable",
                "info",
                "observation",
                labels.get(name, name) + "：本次未形成进展信号",
                "不据此推断进展方向",
                "核对原始记录、观察次数及单位",
                indicator=name,
            )
    limitations = list(
        dict.fromkeys(
            [
                "模型结果不构成医学诊断依据；未声明临床有效性的模型仅用于研究或演示。",
                "模型分数不代表临床概率；阶段分类和下一次随访方向不能解释为具体日期或未来数值。",
                *prediction.get("warnings", []),
                *(
                    [
                        "本次模型正式评估含合成数据，不能据此声明临床有效性；各模型披露见技术附录。"
                    ]
                    if any(r.training.synthetic_in_formal_metrics for r in model_runs)
                    else []
                ),
            ]
        )
    )
    invoked = sum(r.input_audit.model_invoked for r in model_runs)
    available = sum(r.runtime.status == "available" for r in model_runs)
    satisfied = sum(bool(r.input_audit.frame_sha256) for r in model_runs)
    summary = ReportSummary(
        observation_status="available"
        if len(visits) >= context.minimum_signal_observations
        else "limited",
        model_input_status="satisfied"
        if satisfied == len(model_runs) and model_runs
        else "partial"
        if satisfied
        else "unavailable",
        selected_model_count=len(model_runs),
        invoked_model_count=invoked,
        available_model_count=available,
        signal_count=len(signals),
        evidence_status=evidence.evidence_status,
        limitations=limitations,
    )
    sections = [
        ReportSection(number=i, title=t, paragraphs=[], tables=[])
        for i, t in enumerate(SECTION_TITLES, 1)
    ]
    sections[0].paragraphs = [
        f"本报告保存 {len(visits)} 次访视；选择 {len(model_runs)} 个模型任务，输入满足 {satisfied} 个，实际调用 {invoked} 个，结果可用 {available} 个。",
        f"形成 {len(signals)} 条进展信号；{display(evidence.evidence_status)}。",
        *limitations,
    ]
    sections[1].tables = [
        _table(
            "病例与生成身份",
            ["项目", "记录"],
            [
                ("报告编号", report_id),
                ("生成批次", identity.batch_id),
                ("匿名病例编号", identity.anonymous_case_code),
                ("疾病", identity.disease_name),
                ("年龄（病例录入时）", identity.age),
                ("性别", identity.sex),
                ("当前确定阶段", identity.baseline_stage_label),
                ("生成时间", identity.created_at.isoformat()),
                ("末次访视锚点", anchor),
                ("预测窗口（天）", 365),
                ("窗口截止日期", identity.prediction_end_date),
                ("病例备注", snapshot.get("case_notes", snapshot.get("notes"))),
            ],
        )
    ]
    sections[2].paragraphs = [
        f"活动模型准入要求已固化：至少 {context.minimum_visits} 次访视；观察信号至少 {context.minimum_signal_observations} 次有效观察。输入满足、实际调用和结果可用分别统计。"
    ]
    sections[2].tables = [
        _table(
            "数据质量与适用性问题",
            ["位置", "问题", "影响", "行动"],
            [(issue_location(i), i.message, i.impact, i.action) for i in issues],
        )
    ]
    sections[3].paragraphs = [
        "以下为已观察到的记录。未测量的指标不填零、不前向填充；只有单位可比较时解释变化。"
    ]
    sections[3].tables = [
        _table(
            "全指标变化总览",
            ["指标", "首次值", "末次值", "绝对变化", "相对变化", "单位", "观察次数"],
            [
                (
                    labels.get(name, name),
                    obs.get("first"),
                    obs.get("last"),
                    obs.get("delta")
                    if obs.get("unit_state") == "consistent"
                    else "单位不可比较",
                    relative_change_text(
                        obs.get("first"), obs.get("delta_pct"), obs.get("unit_state")
                    ),
                    obs.get("unit"),
                    obs.get("n_observations"),
                )
                for name, obs in sorted(observations.items())
            ],
        )
    ]
    names = sorted({i["name"] for v in visits for i in v["indicators"]})
    for index, visit in enumerate(visits, 1):
        by_name = {i["name"]: i for i in visit["indicators"]}
        rows = []
        for name in names:
            indicator = by_name.get(name)
            rows.append(
                (
                    labels.get(name, name),
                    indicator.get("value") if indicator else "本次未记录",
                    indicator.get("unit") if indicator else "本次未记录",
                    _context_text(
                        {
                            k: v
                            for k, v in indicator.items()
                            if k not in ("name", "value", "unit")
                        }
                    )
                    if indicator
                    else "本次未记录",
                )
            )
        sections[3].tables.append(
            _table(
                f"访视 {index}：{visit['visit_date']}",
                ["指标", "原值", "单位", "检测或量表条件"],
                rows,
            )
        )
        sections[3].tables.append(
            _table(
                f"本次资料 {index}",
                ["项目", "记录"],
                [
                    ("访视条件", _context_text(visit.get("visit_context") or {})),
                    ("本次备注", visit.get("notes")),
                ],
            )
        )
    outcome = prediction["outcome_prediction"]
    outcome_run = next(
        (r for r in model_runs if r.runtime.artifact_type == "outcome"), None
    )
    sections[4].paragraphs = [
        "以末次访视为锚点，解释未来 365 天的模型结果。模型分数不是临床概率。"
    ]
    sections[4].tables = [
        _table(
            "结局模型",
            ["项目", "记录"],
            [
                ("预测目标", outcome_run.target_label if outcome_run else None),
                ("分数", outcome.get("risk_score")),
                ("风险分层", outcome.get("risk_band")),
                ("实际阈值", outcome_run.score_threshold if outcome_run else None),
                (
                    "分层规则",
                    "依次判定：分数 ≥ 0.8 为极高；否则 ≥ 阈值为高；否则 ≥ 0.3 为中；否则为低。",
                ),
                ("可用状态", prediction["model_status"]["outcome"]["status"]),
            ],
        )
    ]
    stage = outcome["stage_projection"]
    sections[5].paragraphs = [
        "阶段模型与各指标趋势模型分别判定可用性；不输出未来具体数值或预测区间。"
    ]
    sections[5].tables = [
        _table(
            "阶段模型",
            ["状态", "最可能阶段"],
            [(stage["status"], stage_label(stage.get("likely_next_stage")))],
        ),
        _table(
            "下一次随访指标趋势",
            ["指标", "状态", "方向"],
            [
                (
                    labels.get(t["indicator"], t["indicator"]),
                    t["forecast"]["status"],
                    t["forecast"]["direction"],
                )
                for t in prediction["trend_predictions"]
            ],
        ),
    ]
    if stage.get("stage_candidates"):
        sections[5].tables.append(
            _table(
                "阶段候选及分类分数",
                ["候选阶段", "分类分数（非临床概率）"],
                [
                    (stage_label(candidate.get("stage")), candidate.get("model_score"))
                    for candidate in stage["stage_candidates"]
                ],
            )
        )
    sections[6].paragraphs = [
        "关键进展信号直接来自本次观察解释结果，信号数量不作为模型有效性的证明。"
        if signals
        else "本次没有满足规则的关键进展信号；不据此排除疾病进展。"
    ]
    sections[6].tables = [
        _table(
            "观察进展信号",
            [
                "指标",
                "观察方向",
                "关注等级",
                "首值",
                "末值",
                "观察次数",
                "是否用于结局模型",
                "局限",
            ],
            [
                (
                    s["display_name"],
                    s["observed_direction"],
                    s["attention_level"],
                    s["first_value"],
                    s["latest_value"],
                    s["observation_count"],
                    s["used_by_outcome_model"],
                    "；".join(s["limitations"]),
                )
                for s in signals
            ],
        )
    ]
    for signal in signals:
        sections[6].tables.append(
            _table(
                "信号解释：" + signal["display_name"],
                ["项目", "记录"],
                [
                    ("单位", signal.get("unit")),
                    ("绝对变化", signal.get("absolute_change")),
                    (
                        "相对变化",
                        relative_change_text(
                            signal.get("first_value"),
                            signal.get("relative_change"),
                            "consistent",
                        ),
                    ),
                    ("观察跨度（天）", signal.get("observation_span_days")),
                    ("疾病关注方向", signal.get("disease_attention_direction")),
                    ("参考状态", signal.get("reference_status")),
                    ("参考规则编号", signal.get("reference_rule_id")),
                    ("参考版本编号", signal.get("reference_version_id")),
                ],
            )
        )
    sections[7] = build_evidence_section(evidence.bundle)
    sections[8].paragraphs = limitations
    review = build_review_items(issues)
    sections[9].paragraphs = [
        "请逐项核对以下具体资料；任何补录都应生成新报告，保留原报告。"
        if review
        else "未发现需要单独列出的数据问题，仍需结合原始资料人工复核模型适用性。"
    ]
    sections[9].tables = [
        _table(
            "人工复核清单",
            ["位置", "问题", "影响", "建议核对"],
            [(issue_location(i), i.message, i.impact, i.action) for i in review],
        )
    ]
    sections[10].paragraphs = [
        "以下身份、配置及任务原因代码随报告固化，供追溯本次生成过程。"
    ]
    sections[10].tables = [
        _table(
            "版本身份",
            ["项目", "记录"],
            [
                ("模型组", context.release_set_id),
                ("模型组哈希", context.release_set_sha256),
                ("数据版本", context.data_release_id),
                ("数据清单哈希", context.dataset_manifest_sha256),
                ("数据划分哈希", context.split_sha256),
                ("指标目录哈希", context.indicator_catalog_sha256),
                ("标准规则和来源绑定哈希", context.standard_rules_sha256),
                ("模板版本", context.template_version),
                ("证据批次", evidence.bundle.evidence_bundle_id),
            ],
        )
    ]
    input_layouts = {}
    for run in model_runs:
        layout_key = tuple(
            (field.name, field.state) for field in run.input_audit.fields
        )
        new_layout = layout_key not in input_layouts
        layout_number = input_layouts.setdefault(layout_key, len(input_layouts) + 1)
        sections[10].tables.append(
            _table(
                "模型任务：" + run.task,
                ["项目", "记录"],
                [
                    ("目标", run.target_label),
                    (
                        "时间范围",
                        "下一次随访"
                        if run.horizon_kind == "next_visit"
                        else str(run.horizon_days) + " 天",
                    ),
                    ("模型标识", run.runtime.model_id),
                    ("模型名称", run.runtime.model_name),
                    ("模型版本", run.runtime.model_version),
                    ("模型文件哈希", run.runtime.artifact_sha256),
                    ("特征版本", run.runtime.feature_version),
                    ("模型状态", run.runtime.status),
                    ("原因代码", run.runtime.reason_code),
                    ("已实际调用", run.input_audit.model_invoked),
                    ("输入列序表", f"输入列序表 {layout_number}"),
                    ("实际输入哈希", run.input_audit.frame_sha256),
                    ("数值插补", run.input_audit.numeric_imputation),
                    ("类别插补", run.input_audit.categorical_imputation),
                    ("校准状态", run.runtime.calibration_status),
                    ("分数语义", run.runtime.score_semantics),
                    ("实际阈值", run.score_threshold),
                    ("风险分层规则版本", run.risk_band_rule_version),
                    ("正式指标含合成数据", run.training.synthetic_in_formal_metrics),
                    ("临床有效性声明", run.training.clinical_validity_claim),
                    ("模型生产启用声明", run.training.production_enabled),
                    ("训练文件哈希", run.training.training_file_sha256),
                    ("训练数据构成", run.training.composition_note),
                ],
            )
        )
        if new_layout:
            sections[10].tables.append(
                _table(
                    f"输入列序表 {layout_number}",
                    ["列序", "特征", "输入状态"],
                    [
                        (
                            index,
                            field_label(field.name, labels) + " (" + field.name + ")",
                            field.state,
                        )
                        for index, field in enumerate(run.input_audit.fields, 1)
                    ],
                )
            )

    return ReportDocument(
        identity=identity,
        generation_context=context,
        summary=summary,
        data_quality=issues,
        model_runs=model_runs,
        evidence={
            "evidence_bundle_id": evidence.bundle.evidence_bundle_id,
            "evidence_snapshot_sha256": evidence.bundle.integrity.evidence_snapshot_sha256,
        },
        review_items=review,
        charts=charts,
        sections=sections,
    )
