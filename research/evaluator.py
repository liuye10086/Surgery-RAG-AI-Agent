"""独立评分器（唯一接触 planted_rules）：类型化命中 + horizon/lookback/lag + 两层/部分恢复率。"""
from __future__ import annotations
import numpy as np
import config as cfg
from simulate_cohort import Condition
from rules import MinedCondition, MinedRule


def typed_match(a, b) -> bool:
    """a=MinedCondition，b=Condition。类型化容差 + lookback 分别比较。"""
    if a.indicator != b.indicator or a.op != b.op:
        return False
    if a.lookback != b.lookback:
        return False
    if a.op == "eq":
        return abs(a.value - b.value) < 1e-9
    if a.op in ("consecutive_rises",):
        return abs(a.value - b.value) <= 1
    if abs(b.value) < 1e-6:
        return abs(a.value - b.value) <= 0.1
    return abs(a.value - b.value) / abs(b.value) <= 0.10


def _conditions_match(mined_conds, planted_conds):
    if len(mined_conds) != len(planted_conds):
        return False
    used = set()
    for pc in planted_conds:
        found = False
        for i, mc in enumerate(mined_conds):
            if i in used:
                continue
            if typed_match(mc, pc):
                used.add(i); found = True; break
        if not found:
            return False
    return True


def full_hit(rule, planted_rule) -> bool:
    if rule.horizon_windows != planted_rule.horizon_windows:
        return False
    if rule.lookback != planted_rule.lookback:
        return False
    if rule.lag != planted_rule.lag:
        return False
    return _conditions_match(rule.conditions, planted_rule.conditions)


def _indicator_op_match(mc, pc):
    """indicator + 方向（op）一致（不看 value/lookback——§8.3 部分命中语义）。"""
    return mc.indicator == pc.indicator and mc.op == pc.op


def partial_hit(rule, planted_rule) -> bool:
    """部分命中（规格 §8.3）：**指标集 + 方向一致**，但时间窗（lookback/horizon/lag）
    或数值阈值未达 typed 容差，或条件为 planted 的非空真子集。
    v5.29（Codex 批次 3 三轮 P2-1）：按 indicator+op 维度匹配 planted；无关条件
    （indicator+op 均不在 planted）→ False；全 typed_match 且数量相等 → full → False。"""
    if not rule.conditions:
        return False
    planted = list(planted_rule.conditions)
    matched_planted = set()           # 被匹配的 planted 索引（indicator+op 维度）
    any_tolerance_fail = False        # 存在 indicator+op 一致但 typed 容差外（阈值/时间窗）
    for mc in rule.conditions:
        found = False
        for j, pc in enumerate(planted):
            if j in matched_planted:
                continue
            if _indicator_op_match(mc, pc):
                matched_planted.add(j)
                found = True
                if not typed_match(mc, pc):        # 时间窗/阈值未达容差
                    any_tolerance_fail = True
                break
        if not found:
            return False                # 无关条件（indicator+op 不在 planted）
    if len(matched_planted) < len(planted):
        return True                     # 条件子集命中（部分）
    return any_tolerance_fail           # 数量相等但阈值/时间窗容差外 → 部分；全匹配 → False


def _rule_hits(subset, rule):
    mask = np.ones(len(subset), dtype=bool)
    for c in rule.conditions:
        if c.op == "eq":
            mask &= (subset["sex_male"].to_numpy() == int(c.value))
        elif c.op == "consecutive_rises":
            mask &= (subset[f"{c.indicator}_rises"].to_numpy() >= c.value)
        elif c.op == "drop_pct":
            mask &= (subset[f"{c.indicator}_drop_pct"].to_numpy() <= -c.value)
        elif c.indicator == "age":
            mask &= (subset["age"].to_numpy() > c.value)
        else:
            mask &= (subset[f"{c.indicator}_cur"].to_numpy() > c.value)
    return mask


def evaluate(recovery, planted_rules, subset, coverage):
    mined = recovery["rules"]
    r1_rule = next((r for r in mined if full_hit(r, planted_rules.r1)), None)
    r2_rule = next((r for r in mined if full_hit(r, planted_rules.r2)), None)
    obs_sub = subset[~subset["unobservable"]]
    denom = int(obs_sub["patient_id"].nunique())
    covered = set()
    for rule in (r1_rule, r2_rule):
        if rule is not None:
            covered.update(obs_sub.loc[_rule_hits(obs_sub, rule), "patient_id"])
    return {
        "rule_level_recovery": {"denominator": 2, "full_hit_count": int(r1_rule is not None) + int(r2_rule is not None),
                                "r1_hit": r1_rule is not None, "r2_hit": r2_rule is not None},
        "instance_level_recovery": {"denominator": denom, "covered": len(covered),
                                    "rate": len(covered) / denom if denom else 0.0},
        "partial_recovery": {"r1_partial": any(partial_hit(r, planted_rules.r1) for r in mined),
                             "r2_partial": any(partial_hit(r, planted_rules.r2) for r in mined)},
        "coverage": coverage.get("per_rule", {}),
        "rule_ci_present": all(isinstance(r.ci, tuple) for r in mined),
        "n_rules": len(mined),
    }
