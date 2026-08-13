from report import render_report, _fmt_ci

def _sec(**kw):
    base = {"signal": {}, "rules": [], "recovery": {}, "timeline": {},
            "shap": {}, "scale": {}, "p_obs": {}, "limitations": []}
    base.update(kw)
    return base

def test_8_sections():
    md = render_report(_sec())
    for i, title in enumerate(["摘要", "信号验证", "挖回规则列表", "植入规则对照表",
                               "证据时间线", "时间滞后 SHAP/消融摘要", "规模退化表", "局限与下一步"], start=1):
        assert f"## {i}. {title}" in md, title

def test_ci_unestimated_marked():
    md = render_report(_sec(rules=[{"conditions": [("sex", "eq", 1.0)], "ci": "CI 未估计"}]))
    assert "CI 未估计" in md

def test_p_obs_reported():
    md = render_report(_sec(p_obs={"r1_only": {"rate": 0.5}}))
    assert "P_obs" in md

def test_recovery_nested_coverage():
    # evaluate 的 coverage 是嵌套 per_rule（{"r1": {"eligible_total":..., "coverage":...}}）——
    # 报告必须按嵌套契约取数（_cov_rate），不能用 float 格式直接格式化 dict
    rec = {"rule_level_recovery": {"full_hit_count": 2, "denominator": 2,
                                   "r1_hit": True, "r2_hit": True},
           "instance_level_recovery": {"covered": 30, "denominator": 40, "rate": 0.75},
           "partial_recovery": {"r1_partial": False, "r2_partial": False},
           "coverage": {"r1": {"eligible_total": 100, "eligible_observed": 95, "coverage": 0.95},
                        "r2": {"eligible_total": 100, "eligible_observed": 98, "coverage": 0.98}},
           "rule_ci_present": True}
    md = render_report(_sec(recovery=rec))
    assert "0.95" in md and "0.98" in md

def test_ablation_block_renders():
    md = render_report(_sec(ablation={"PLT": {"baseline_auc": 0.9, "baseline_ci": (0.85, 0.95),
                                              "without_auc": 0.7, "without_ci": (0.6, 0.8),
                                              "auc_drop": 0.2}}))
    assert "整组滞后消融" in md and "0.200" in md

def test_ablation_block_nan_ci_renders_na():
    # CI 未估计（(nan,nan)）→ 报告显示 [NA, NA]，不得渲染为数值或 "[nan, nan]"
    md = render_report(_sec(ablation={"PLT": {"baseline_auc": 0.9,
                                              "baseline_ci": (float("nan"), float("nan")),
                                              "without_auc": 0.8, "without_ci": (0.7, 0.9),
                                              "auc_drop": 0.1}}))
    assert "[NA, NA]" in md
    assert "nan" not in md.replace("[NA, NA]", "")

def test_fmt_ci_inf_and_nan_contract():
    # _fmt_ci 确定性契约：(finite, +inf) → "[lo, +inf]"（可靠性边界上界允许 inf，不误报 [NA, NA]）；
    # (nan, nan) → "[NA, NA]"（CI 未估计不伪装数值）
    assert _fmt_ci((0.5, float("inf"))) == "[0.500, +inf]"
    assert _fmt_ci((float("nan"), float("nan"))) == "[NA, NA]"
    assert _fmt_ci(None) == "[NA, NA]"

def test_limitations_rendered():
    # 门控/失败场景的停止原因必须实际渲染进第 8 节（不得硬编码忽略 sections["limitations"]）
    md = render_report(_sec(limitations=["信号门槛未达：AUC CI 下界 < 0.65，归因与规则挖掘已停止"]))
    assert "信号门槛未达" in md
    # 空 limitations → 默认文本
    md2 = render_report(_sec())
    assert "模拟数据非临床结论" in md2

def test_scale_block_precision_rendered():
    # 达 R_max 仍不满足 CI 半宽 → precision_not_met=True → 报告渲染"精度目标未达到"
    scale = {"cells": {"n150_f24": {"repeats": 200, "overall_mean": 0.5, "overall_ci": (0.4, 0.6),
                                    "excluded_ratio_mean": 0.1, "r1_freq": 0.5, "r2_freq": 0.5,
                                    "both_freq": 0.25, "precision_not_met": True}}}
    md = render_report(_sec(scale=scale))
    assert "精度目标未达到" in md

def test_calibration_block_renders():
    cal = {"targets": {"neither": 0.12, "r1_only": 0.60, "r2_only": 0.40, "r1_and_r2": 0.73},
           "actuals": {"neither": 0.11, "r1_only": 0.61, "r2_only": 0.39, "r1_and_r2": 0.72},
           "errors": {"neither": -0.01, "r1_only": 0.01, "r2_only": -0.01, "r1_and_r2": -0.01},
           "ok": True}
    md = render_report(_sec(calibration=cal))
    assert "潜在风险校准" in md and "校准达标" in md
    assert "0.600" in md and "-0.010" in md
    cal_bad = dict(cal, ok=False)
    md_bad = render_report(_sec(calibration=cal_bad))
    assert "校准未达标" in md_bad

def test_scale_block_not_estimable_cell():
    """不可估单元单列"不可估 + reason"（Codex 批次 4 一轮 P1-4）：不得渲染成
    NaN/0.00/达标（默认 CLI 唯一规模单元的实际报告内容）。"""
    scale = {"cells": {"n150_f24": {"not_estimable": True, "reason": "no_feasible_path_anchor"}}}
    md = render_report(_sec(scale=scale))
    assert "不可估" in md and "no_feasible_path_anchor" in md
    assert "nan" not in md

def test_rules_table_top20_and_time_fields():
    """规则表 top 20 + horizon/lookback/lag 列（Codex 批次 4 一轮 P2-1，v18 报告契约）。"""
    rules = [{"conditions": [("sex", "eq", 1.0)], "horizon_windows": 4, "lookback": 1,
              "lag": 0, "lift_median": 2.0, "event_support": 10, "total_support": 30,
              "selection_frequency": 1.0, "ci": (1.5, 2.5)}] * 25   # 25 条 → top 20 + 汇总
    md = render_report(_sec(rules=rules))
    assert "horizon" in md and "lookback" in md and "lag" in md
    assert "另有 5 条规则未列出" in md

def test_timeline_control_delta_ci_rendered():
    """第 5 节展示进展组 vs 匹配对照差异 + control_delta_ci（Codex 批次 4 一轮 P2-1）。"""
    md = render_report(_sec(timeline={
        "order": {"early_median": 2.0, "afp_median": 1.0, "afp_after_early": True,
                  "tiebreak_by_event_count": 0},
        "n_intersection": 30, "unmatched_rate": 0.0,
        "control_delta": {"PLT": -2.0}, "control_delta_ci": {"PLT": (-3.0, -1.0)}}))
    assert "首次偏离差" in md and "-2.000" in md and "-3.000" in md

def test_signal_gate_and_auc_median_rendered():
    """信号验证契约（Codex 批次 4 二轮 P2）：报告渲染跨重复 AUC 中位数 + 信号门槛状态
    （通过/未达 + 门槛值），区分"门槛已通过"和"尚未判断"。"""
    md = render_report(_sec(signal={"auc_point": 0.8, "auc_ci": (0.75, 0.85),
                                    "auc_median_across_repeats": 0.79, "pr_auc": 0.7, "brier": 0.2}))
    assert "跨重复 AUC 中位数" in md and "0.790" in md
    assert "信号门槛" in md and "通过" in md and "0.65" in md
    # 低 AUC → 未达
    md_low = render_report(_sec(signal={"auc_point": 0.6, "auc_ci": (0.5, 0.6),
                                        "auc_median_across_repeats": 0.55, "pr_auc": 0.5, "brier": 0.4}))
    assert "未达" in md_low

def test_timeline_unmatched_by_group_rendered():
    """路径级 unmatched 展示（Codex 批次 3 六轮 P2，关闭文档风险）：报告须展示
    unmatched_by_group（路径级），空组 NaN → NA（不得渲染成 100% unmatched）。"""
    md = render_report(_sec(timeline={
        "order": {"early_median": 2.0, "afp_median": 1.0, "afp_after_early": True,
                  "tiebreak_by_event_count": 0},
        "n_intersection": 30, "unmatched_rate": 0.0,
        "unmatched_by_group": {"r1_only": 0.0, "r2_only": float("nan"), "r1_and_r2": float("nan")}}))
    assert "unmatched_by_group" in md or "r1_only" in md
    assert "NA" in md                      # 空组 NaN → NA
