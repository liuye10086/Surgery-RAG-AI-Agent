"""Project complete evidence into saved text; no diagnosis or live lookups."""

from app.schemas.report_document import ReportSection, ReportTable
from app.services.report_display_labels import display, stage_label, field_label


def _table(title, rows):
    return ReportTable(
        title=title,
        headers=["项目", "记录"],
        rows=[[str(k), display(v)] for k, v in rows],
    )


def build_evidence_section(bundle):
    standard = bundle.standard
    doc, version = standard.document, standard.version
    tables = [
        _table(
            "标准来源与版本",
            [
                ("标准状态", standard.status),
                ("标题", doc.title),
                ("文件名", doc.filename),
                ("发布机构", doc.issuer),
                ("发布日期", doc.publication_date),
                ("外部标识", doc.external_identifier),
                ("来源网址", doc.source_url),
                ("版本", version.version_label),
                ("批准时间", version.approved_at),
                ("生效时间", version.effective_from),
                ("解析器版本", version.parser_version),
                ("文档标识", doc.document_id),
                ("版本标识", version.version_id),
                ("文档哈希", doc.content_sha256),
                ("版本哈希", version.content_sha256),
            ],
        )
    ]
    for rule in standard.rules:
        source = rule.source
        tables.append(
            _table(
                "标准规则：" + rule.display_name,
                [
                    ("规则编号", rule.rule_id),
                    ("状态", rule.status),
                    ("机器处理范围", rule.machine_actionability),
                    ("单位", rule.unit),
                    ("下限", rule.lower),
                    ("下限是否包含", rule.lower_inclusive),
                    ("上限", rule.upper),
                    ("上限是否包含", rule.upper_inclusive),
                    ("末次值", rule.latest_value),
                    ("数值解释", rule.numeric_interpretation),
                    ("解释说明", rule.interpretation),
                    ("条件状态", rule.conditions.status),
                    (
                        "满足条件",
                        "、".join(map(display, rule.conditions.satisfied)) or "未记录",
                    ),
                    (
                        "缺少条件",
                        "、".join(map(display, rule.conditions.missing)) or "无",
                    ),
                    (
                        "不匹配条件",
                        "、".join(map(display, rule.conditions.mismatched)) or "无",
                    ),
                    ("章节", source.section_title),
                    ("页码", source.page_number),
                    ("段落", source.paragraph_index),
                    ("表", source.table_index),
                    ("行", source.row_index),
                    ("列", source.column_index),
                    ("原文片段", source.raw_text),
                    ("适用规则哈希", rule.applicability_hash),
                ],
            )
        )
    ref = bundle.reference_cases
    pool = ref.pool_statistics
    tables.append(
        _table(
            "参考病例检索范围",
            [
                ("状态", ref.status),
                ("数据集", ref.data_release.logical_dataset),
                ("数据版本", ref.data_release.dataset_release_id),
                ("数据哈希", ref.data_release.data_content_sha256),
                ("算法", ref.algorithm_version),
                ("配置哈希", ref.configuration_hash),
                ("总窗口数", pool.total_windows),
                ("合格窗口数", pool.eligible_windows),
                ("可比窗口数", pool.comparable_windows),
                ("返回数", pool.returned_windows),
                *[
                    ("排除原因：" + display(k), v)
                    for k, v in sorted(pool.exclusion_counts.items())
                ],
            ],
        )
    )
    for case in ref.cases:
        f, score = case.features, case.score
        age_band = (
            f"{f.age // 10 * 10}～{f.age // 10 * 10 + 9} 岁"
            if f.age is not None
            else None
        )
        tables.append(
            _table(
                "参考病例：" + case.anonymous_case_code,
                [
                    ("年龄段", age_band),
                    ("性别", f.sex),
                    ("确定阶段", stage_label(f.baseline_stage)),
                    ("窗口锚点", f.as_of),
                    ("访视次数", f.visit_count),
                    ("观察跨度（天）", f.observation_span_days),
                    ("覆盖度", f"{score.coverage:.2%}"),
                    ("条件相似度", f"{score.conditional_similarity:.2f} / 100"),
                    ("排序分数", f"{score.ranking_score:.2f} / 100"),
                    ("可用权重", score.available_weight),
                    *[
                        ("比较维度：" + display(k), f"{v:.2%}")
                        for k, v in sorted(score.dimensions.items())
                    ],
                    *[
                        ("结局记录：" + display(k), v)
                        for k, v in sorted(case.outcome_value.items())
                        if isinstance(v, (str, int, float, bool))
                    ],
                    ("观察结局", case.outcome_status),
                    ("结局来源", case.outcome_source),
                    ("结局可靠性", case.outcome_reliability),
                ],
            )
        )
        indicators = f.feature_summary.get("indicators", {})
        context = f.measurement_context_summary
        context_rows = []
        allowed = {
            "source_type",
            "device_name",
            "assay_platform",
            "method",
            "specimen",
            "scale_version",
            "assessment_language",
            "education_years",
            "education_adjusted",
            "imaging_type",
        }
        values = context.get("values", {})
        if isinstance(values, dict):
            for key, items in sorted(values.items()):
                if key in allowed and isinstance(items, list):
                    context_rows.append(
                        (
                            display(key),
                            "、".join(
                                display(item)
                                for item in items
                                if isinstance(item, (str, int, float, bool))
                            ),
                        )
                    )
        per_indicator = context.get("by_indicator", {})
        if isinstance(per_indicator, dict):
            for indicator, fields in sorted(per_indicator.items()):
                if isinstance(fields, dict):
                    context_rows.extend(
                        (indicator + " · " + display(key), value)
                        for key, value in sorted(fields.items())
                        if key in allowed and isinstance(value, (str, int, float, bool))
                    )
        if context_rows:
            tables.append(
                _table("参考测量条件：" + case.anonymous_case_code, context_rows)
            )
        for indicator, features in sorted(indicators.items()):
            if not isinstance(features, dict):
                continue
            tables.append(
                _table(
                    "参考指标记录：" + case.anonymous_case_code + " · " + indicator,
                    [
                        (field_label(indicator + "." + key), value)
                        for key, value in sorted(features.items())
                        if key
                        in {
                            "first",
                            "last",
                            "mean",
                            "minimum",
                            "maximum",
                            "delta",
                            "n_observations",
                            "missing_ratio",
                            "time_slope_per_day",
                            "unit",
                            "unit_state",
                        }
                    ],
                )
            )
        tables.append(
            ReportTable(
                title="逐指标可比性：" + case.anonymous_case_code,
                headers=["指标", "可比状态", "相似度", "原因"],
                rows=[
                    [
                        c.indicator,
                        "可比较" if c.status == "comparable" else "已排除",
                        f"{c.score:.2%}" if c.score is not None else "未记录",
                        display(c.reason),
                    ]
                    for c in case.comparisons
                ],
            )
        )
    return ReportSection(
        number=8,
        title="参考标准和相似病例",
        tables=tables,
        paragraphs=[
            "以下内容来自本次保存的标准与参考病例证据。相似病例不代表当前病例将发生相同结局。",
            *standard.warnings,
            *ref.warnings,
            *bundle.warnings,
        ],
    )
