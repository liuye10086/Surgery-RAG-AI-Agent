"""Stable Chinese labels copied into the document at generation time."""

SECTION_TITLES = [
    "报告摘要",
    "病例与预测范围",
    "数据质量与适用性",
    "已观察到的纵向变化",
    "未来 365 天进展风险",
    "阶段模型和下一次随访趋势的可用状态",
    "关键进展信号",
    "参考标准和相似病例",
    "不确定性与局限性",
    "人工复核重点",
    "模型和数据技术附录",
]
LABELS = {
    "clinical": "临床记录",
    "none": "无",
    "unavailable": "不可用",
    "reference_unavailable": "标准暂不可用",
    "reference_not_applicable": "标准不适用",
    "unit_missing": "单位缺失",
    "unit_conflict": "单位不一致",
    "unsupported_unit": "不支持的单位",
    "canonical_unit_missing": "规范单位缺失",
    "canonical_unit_mismatch": "规范单位不一致",
    "explicit_cirrhosis": "明确肝硬化结局记录",
    "explicit_hcc": "明确肝癌结局记录",
    "explicit_cdr": "明确认知评估结局记录",
    "documented_ad_unspecified": "已记录的阿尔茨海默病结局",
    "event_date": "结局日期",
    "event_type": "结局类型",
    "horizon_days": "观察窗口（天）",
    "stage_task": "阶段与预测任务",
    "indicator_coverage": "指标覆盖",
    "latest_values": "末次值",
    "trend": "纵向趋势",
    "span_frequency": "跨度与频率",
    "context": "检测或量表条件",
    "consistent": "单位一致",
    "unit": "单位",
    "unit_state": "单位状态",
    "facility_name": "检测或评估机构",
    "assay_platform": "检测平台",
    "treatment_change": "治疗变化",
    "diagnosis_change": "诊断变化",
    "lab": "检验",
    "imaging": "影像",
    "assessment": "评估",
    "medical_record": "病历",
    "self_report": "自行报告",
    "other": "其他",
    "male": "男",
    "female": "女",
    "pre_cirrhosis": "未肝硬化阶段",
    "fatty_liver": "脂肪肝",
    "cirrhosis": "肝硬化",
    "hcc": "肝癌",
    "normal": "认知正常",
    "cn": "认知正常",
    "mci": "轻度认知障碍",
    "dementia": "痴呆",
    "available": "可用",
    "missing": "未记录",
    "disabled": "未启用",
    "incompatible": "不可用",
    "not_estimated": "未估计",
    "calculable": "可作数值解释",
    "evidence_only": "仅作为证据",
    "evidence-only": "仅作为证据",
    "missing_context": "缺少适用条件",
    "context_incomplete": "适用条件不完整",
    "not_applicable": "不适用",
    "conflict": "存在冲突",
    "blocked": "已阻断",
    "within_range": "在标准范围内",
    "above_range": "高于标准范围",
    "below_range": "低于标准范围",
    "matched": "条件满足",
    "mismatched": "条件不匹配",
    "positive": "已观察到结局",
    "negative": "未观察到结局",
    "unknown": "结局未知",
    "low": "低",
    "medium": "中",
    "high": "高",
    "no_eligible_cases": "无合格参考病例",
    "insufficient_comparability": "可比较信息不足",
    "reference_query_failed": "参考病例查询暂不可用",
    "reference_index_stale": "参考病例索引版本不可用",
    "rising": "上升",
    "stable": "稳定",
    "falling": "下降",
    "direction_only": "仅预测方向",
    "not_available": "不可用",
    "next_followup": "下一次随访",
    "next_visit": "下一次随访",
    "complete": "完整证据",
    "partial": "部分证据",
    "not_calibrated": "未校准",
    "calibrated": "已校准",
    "model_score": "模型分数",
    "calibrated_probability": "校准概率",
    "source_type": "资料来源",
    "is_baseline": "是否基线",
    "method": "检测方法",
    "specimen": "标本",
    "device_name": "设备名称",
    "assay_name": "检测项目或试剂",
    "scale_version": "量表版本",
    "assessment_language": "评估语言",
    "education_years": "教育年限",
    "education_adjusted": "是否教育校正",
    "imaging_type": "影像类型",
    "notes": "备注",
    "age": "年龄",
    "sex": "性别",
    "baseline_stage": "确定阶段",
    "visit_count": "访视次数",
    "observation_span_days": "观察跨度（天）",
    "days_since_previous_visit": "距前次访视（天）",
    "present": "已记录",
    "allowed_missing": "允许缺失",
    "required_missing": "必需输入缺失",
    "invalid": "无效输入",
    "median_add_indicator": "中位数插补并添加缺失标记",
    "most_frequent": "众数插补",
    "priority": "优先关注",
    "attention": "需要关注",
    "routine": "常规观察",
}


def display(value):
    if value is None or value == "":
        return "未记录"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, str):
        for prefix, label in (
            ("context_missing:", "缺少测量条件："),
            ("context_mismatch:", "测量条件不匹配："),
        ):
            if value.startswith(prefix):
                return label + display(value[len(prefix) :])
    return LABELS.get(str(value), str(value))


def stage_label(value):
    if isinstance(value, str) and value.startswith("stay_"):
        return "维持" + display(value[5:])
    return display(value)


def field_label(name, labels=None):
    if name in LABELS:
        return LABELS[name]
    code, _, stat = name.partition(".")
    stats = {
        "first": "首次值",
        "last": "末次值",
        "mean": "均值",
        "minimum": "最小值",
        "maximum": "最大值",
        "delta": "绝对变化",
        "missing_ratio": "缺失比例",
        "n_observations": "观察次数",
        "time_slope_per_day": "每日变化斜率",
        "recent_delta": "最近变化",
        "rises_count": "上升次数",
        "falls_count": "下降次数",
        "unit": "单位",
        "unit_state": "单位状态",
    }
    base = (labels or {}).get(code, code)
    return base + ("：" + stats.get(stat, stat) if stat else "")
