"""Markdown 规律报告（§9 固定 8 节结构）。

契约：规则列表 = list[dict]（main 用 MinedRule.__dict__ 转换；测试直接传 dict）。
字段访问统一走 _rget，兼容 dict 与 MinedRule 对象（后续若改传对象无需改渲染）。
"""
from __future__ import annotations
import numpy as np
import config as cfg    # _calibration_block 渲染校准队列规模（cfg.SIM["calibration_n"]）

_SECTIONS = ["摘要", "信号验证", "挖回规则列表", "植入规则对照表",
             "证据时间线", "时间滞后 SHAP/消融摘要", "规模退化表", "局限与下一步"]


def _rget(rule, key, default=None):
    """统一字段访问：兼容 dict（rule[key]）与 MinedRule 对象（getattr）。"""
    if isinstance(rule, dict):
        return rule.get(key, default)
    return getattr(rule, key, default)


def _fmt_num(v):
    try:
        f = float(v)
        return f"{f:.3f}" if np.isfinite(f) else "NA"
    except (TypeError, ValueError):
        return "NA"


def _cond_str(c):
    if isinstance(c, (tuple, list)):
        return f"{c[0]} {c[1]} {c[2]}"
    return f"{c.indicator} {c.op} {c.value}"


def render_report(sections: dict) -> str:
    md = ["# 疾病进展规律挖掘 · 端到端最小闭环 报告", ""]
    signal = sections.get("signal", {})
    md.append(f"## 1. 摘要\n\n- 方法：模拟纵向队列，含植入规律。\n"
              f"- 信号：AUC 点估计 {_fmt_num(signal.get('auc_point'))}，"
              f"95% CI {_fmt_ci(signal.get('auc_ci'))}。\n")
    md.append("## 2. 信号验证\n\n"
              f"- 最终平均 OOF 预测 AUC：{_fmt_num(signal.get('auc_point'))}"
              f"（患者聚类 95% CI {_fmt_ci(signal.get('auc_ci'))}）\n"
              f"- 跨重复 AUC 中位数：{_fmt_num(signal.get('auc_median_across_repeats'))}\n"
              f"- PR-AUC：{_fmt_num(signal.get('pr_auc'))}；"
              f"Brier：{_fmt_num(signal.get('brier'))}\n"
              + _signal_gate_line(signal)
              + _calibration_block(sections.get("calibration", {})))
    md.append("## 3. 挖回规则列表\n\n" + _rules_table(sections.get("rules", [])))
    md.append("## 4. 植入规则对照表\n\n" + _recovery_block(sections.get("recovery", {}))
              + _p_obs_block(sections.get("p_obs", {})))
    md.append("## 5. 证据时间线\n\n" + _timeline_block(sections.get("timeline", {})))
    md.append("## 6. 时间滞后 SHAP/消融摘要\n\n" + _shap_block(sections.get("shap", {}))
              + _ablation_block(sections.get("ablation", {})))
    md.append("## 7. 规模退化表\n\n" + _scale_block(sections.get("scale", {})))
    md.append("## 8. 局限与下一步\n\n" + _limitations_block(sections.get("limitations", [])))
    return "\n".join(md)


def _signal_gate_line(signal):
    """信号门槛状态（规格 §9"信号门槛通过与否"）：从 AUC CI 下界与版本化门槛判定。
    有限下界 ≥ 门槛 → 通过；否则（未达/CI 未估计 NaN）→ 未达。"""
    ci = signal.get("auc_ci")
    try:
        auc_lo = float(ci[0]) if ci is not None else float("nan")
    except (TypeError, ValueError, IndexError):
        auc_lo = float("nan")
    gate = cfg.THRESHOLDS["auc_ci_lower_gate"]
    ok = np.isfinite(auc_lo) and auc_lo >= gate
    status = "**通过**" if ok else "**未达**（归因与规则挖掘已停止）"
    return f"- 信号门槛：AUC 患者聚类 95% CI 下界 ≥ {gate} → {status}\n"


def _limitations_block(limitations):
    """局限与下一步：limitations 非空 → 逐条列出（门控/失败场景的停止原因必须可见）；
    空 → 默认文本。"""
    items = list(limitations) if limitations else \
        ["模拟数据非临床结论；现实事件数约束；后续子系统见规格 §12。"]
    return "\n".join(f"- {x}" for x in items) + "\n"


def _fmt_ci(ci):
    """CI 渲染（确定性）：None / (nan,nan) → "[NA, NA]"（CI 未估计，不得渲染成 "[nan, nan]"）；
    有限数值 → "[lo, hi]"；(finite, +inf) → "[lo, +inf]"（可靠性边界上界允许 inf，不得误报为 [NA, NA]）。"""
    try:
        if ci is None:
            return "[NA, NA]"
        lo, hi = float(ci[0]), float(ci[1])
        if np.isnan(lo) or np.isnan(hi):
            return "[NA, NA]"
        lo_s = f"{lo:.3f}" if np.isfinite(lo) else "-inf"
        hi_s = f"{hi:.3f}" if np.isfinite(hi) else "+inf"
        return f"[{lo_s}, {hi_s}]"
    except Exception:
        return "[NA, NA]"


def _rules_table(rules):
    if not rules:
        return "- 未挖出规则\n"
    # v5.29（Codex 批次 4 一轮 P2-1）：只渲染 top 20 + 汇总（v18"报告只渲染 top 20"）；
    # 规则表展示 horizon/lookback/lag（§9 挖回规则列表要求）
    lines = ["| 条件 | horizon | lookback | lag | lift 中位 | 支持事件 | 总支持 | 选中频率 | CI |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    shown = rules[:20]
    for r in shown:
        conds = "; ".join(_cond_str(c) for c in _rget(r, "conditions", []))   # 兼容 tuple 与 MinedCondition
        ci = _rget(r, "ci")
        ci_s = "CI 未估计" if isinstance(ci, str) else _fmt_ci(ci)
        lines.append(f"| {conds} | {_rget(r, 'horizon_windows', 0)} | {_rget(r, 'lookback', 0)} "
                     f"| {_rget(r, 'lag', 0)} | {_rget(r, 'lift_median', 0):.2f} | {_rget(r, 'event_support', 0)} "
                     f"| {_rget(r, 'total_support', 0)} | {_rget(r, 'selection_frequency', 0):.2f} | {ci_s} |")
    if len(rules) > len(shown):
        lifts = [_rget(r, 'lift_median', float('nan')) for r in rules]
        lifts = [x for x in lifts if isinstance(x, (int, float))]
        extra = len(rules) - len(shown)
        if lifts:
            lines.append(f"\n- 另有 {extra} 条规则未列出（lift 中位范围 "
                         f"[{min(lifts):.2f}, {max(lifts):.2f}]）。")
        else:
            lines.append(f"\n- 另有 {extra} 条规则未列出。")
    return "\n".join(lines) + "\n"


def _cov_rate(cov, key):
    """coverage 兼容契约：evaluate 传 `per_rule`（嵌套 dict，`{"r1": {"coverage": ...}}`）；
    防御旧格式（纯 float）。缺失 → NaN，绝不把 dict 当 float 格式化。"""
    v = cov.get(key, {})
    if isinstance(v, dict):
        return v.get("coverage", float("nan"))
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def _recovery_block(rec):
    rl = rec.get("rule_level_recovery", {})
    il = rec.get("instance_level_recovery", {})
    cov = rec.get("coverage", {})
    return (f"- 规则级恢复率：完整命中 {rl.get('full_hit_count', 0)}/{rl.get('denominator', 2)}"
            f"（R1={rl.get('r1_hit')}、R2={rl.get('r2_hit')}）\n"
            f"- 实例级恢复率：覆盖 {il.get('covered', 0)}/{il.get('denominator', 0)}"
            f"（rate {_fmt_num(il.get('rate'))}）\n"
            f"- 部分恢复：R1={rec.get('partial_recovery', {}).get('r1_partial')}、"
            f"R2={rec.get('partial_recovery', {}).get('r2_partial')}\n"
            f"- 可评估覆盖率：R1={_fmt_num(_cov_rate(cov, 'r1'))}、R2={_fmt_num(_cov_rate(cov, 'r2'))}\n"
            f"- 规则 CI 齐全：{rec.get('rule_ci_present')}\n")


def _calibration_block(cal):
    """潜在风险校准（规格 §5.3）：独立 N=50,000 队列上各组目标 / 实际潜在风险（模拟器内部
    真值 g + 事件窗口，不受删失影响）/ 误差；**ok = 四组 |误差| ≤ 0.03（±3pp 验收）**。"""
    if not cal or not cal.get("targets"):
        return ""
    ok = cal.get("ok", True)
    status = "**校准达标**（四组 |误差| ≤ ±3pp）" if ok else "**校准未达标**（存在 |误差| > 3pp）"
    lines = [f"\n**潜在风险校准（独立 N={cfg.SIM['calibration_n']:,} 队列，内部真值，不受删失影响；"
             f"{status}）：**",
             "| 组 | 目标 | 实际 | 误差 |", "| --- | --- | --- | --- |"]
    for grp in ("neither", "r1_only", "r2_only", "r1_and_r2"):
        if grp in cal["targets"]:
            lines.append(f"| {grp} | {_fmt_num(cal['targets'][grp])} "
                         f"| {_fmt_num(cal['actuals'][grp])} | {_fmt_num(cal['errors'][grp])} |")
    return "\n".join(lines) + "\n"


def _p_obs_block(po):
    if not po:
        return "- P_obs（观测标签风险，排除 unknown，不参与 §10 验收）：未提供\n"
    lines = ["- P_obs（观测标签风险 = positive/(positive+negative)，排除 unknown，不参与 §10 验收）："]
    for grp, d in po.items():
        lines.append(f"  - {grp}: {d.get('positive', 0)}/{d.get('denominator', 0)}"
                     f" = {_fmt_num(d.get('rate'))}")
    return "\n".join(lines) + "\n"


def _timeline_block(tt):
    order = tt.get("order", {}) if tt else {}
    lines = [f"- early_median：{order.get('early_median')}；afp_median：{order.get('afp_median')}",
             f"- afp_after_early：{order.get('afp_after_early')}；tiebreak：{order.get('tiebreak_by_event_count')}",
             f"- 交集患者：{tt.get('n_intersection')}；unmatched：{_fmt_num(tt.get('unmatched_rate'))}"]
    # v5.29（Codex 批次 3 六轮 P2）：路径级 unmatched_by_group（空组 NaN → NA）
    ubg = (tt or {}).get("unmatched_by_group", {})
    if ubg:
        parts = ", ".join(f"{grp}={_fmt_num(v)}" for grp, v in ubg.items())
        lines.append(f"- 路径级 unmatched（空组 NA）：{parts}")
    # v5.29（Codex 批次 4 一轮 P2-1）：进展组 vs 匹配对照差异（control_delta）及配对差异 CI
    cd = (tt or {}).get("control_delta", {})
    cd_ci = (tt or {}).get("control_delta_ci", {})
    if cd:
        parts = []
        for ind, v in cd.items():
            ci_s = _fmt_ci(cd_ci.get(ind)) if ind in cd_ci else "NA"
            parts.append(f"{ind}={_fmt_num(v)}（CI {ci_s}）")
        lines.append(f"- 进展组 vs 匹配对照首次偏离差（负=进展者更早）：{'; '.join(parts)}")
    return "\n".join(lines) + "\n"


def _shap_block(shap):
    if not shap:
        return "- 未运行时间滞后 SHAP\n"
    lines = []
    for ind, lags in shap.items():
        lines.append(f"- {ind}: " + ", ".join(f"lag{lag}={v:.3f}" for lag, v in lags.items()))
    return "\n".join(lines) + "\n"


def _ablation_block(abl):
    """整组滞后消融（§7.2 佐证）：移除该指标滞后观测组后的 OOF AUC（含患者 Bootstrap CI）。"""
    if not abl:
        return ""
    lines = ["\n**整组滞后消融（移除该指标滞后观测组 → 重训 OOF AUC；描述性，非因果）：**",
             "| 指标 | 基线 AUC | 移除组后 AUC | AUC 下降 |", "| --- | --- | --- | --- |"]
    for ind, d in abl.items():
        lines.append(f"| {ind} | {_fmt_num(d.get('baseline_auc'))} ({_fmt_ci(d.get('baseline_ci'))}) "
                     f"| {_fmt_num(d.get('without_auc'))} ({_fmt_ci(d.get('without_ci'))}) "
                     f"| {_fmt_num(d.get('auc_drop'))} |")
    return "\n".join(lines) + "\n"


def _scale_block(scale):
    if not scale:
        return "- 未运行规模退化实验\n"
    cells = scale.get("cells", {})
    lines = ["| 单元 | 重复 | 总体恢复率(CI) | 排除比例 | R1 频率 | R2 频率 | 双命中 | 精度 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for k, agg in cells.items():
        if agg.get("not_estimable"):
            # v5.29（Codex 批次 4 一轮 P1-4）：不可估单元单列"不可估 + reason"，
            # 不得渲染成 NaN/0.00/达标（误导）
            lines.append(f"| {k} | 不可估 | — | — | — | — | — | **不可估**（{agg.get('reason', '')}） |")
            continue
        prec = "**精度目标未达到**" if agg.get("precision_not_met") else "达标"
        lines.append(f"| {k} | {agg.get('repeats')} | {agg.get('overall_mean', float('nan')):.2f} "
                     f"({_fmt_ci(agg.get('overall_ci'))}) | {agg.get('excluded_ratio_mean', float('nan')):.2f} "
                     f"| {agg.get('r1_freq', 0):.2f} | {agg.get('r2_freq', 0):.2f} "
                     f"| {agg.get('both_freq', 0):.2f} | {prec} |")
    rb = scale.get("reliability_boundaries", {})
    for k, b in rb.items():
        status = b.get("status")
        ev = b.get("boundary_events")
        ev_s = f"{ev:.1f}" if ev is not None else "NA"
        lines.append(f"- 可靠性边界 {k}：status={status}；边界事件数={ev_s}；边界 CI={_fmt_ci(b.get('boundary_ci'))}")
    return "\n".join(lines) + "\n"
