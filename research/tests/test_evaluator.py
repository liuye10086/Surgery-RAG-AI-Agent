import numpy as np
import pytest
from simulate_cohort import simulate
from features import confirmation_subset
from rules import mine_rules, MinedCondition, MinedRule
from evaluator import evaluate, typed_match, full_hit, partial_hit

OUT = simulate(n=1500, followup_months=60, horizon_months=24, seed=6)
SUB = confirmation_subset(OUT["patients"], OUT["obs"], horizon_windows=4)
PR = OUT["planted_rules"]

def test_typed_match_numeric_sex_and_tolerance():
    assert typed_match(MinedCondition("sex", "eq", 1.0), PR.r1.conditions[0]) is True
    assert typed_match(MinedCondition("age", "gt", 52.0), PR.r1.conditions[1]) is True
    # 次数容差 ±1（3 vs 2），lookback 需与 planted 一致（consecutive_rises lookback=2）
    assert typed_match(MinedCondition("HbA1c", "consecutive_rises", 3.0, lookback=2),
                       PR.r1.conditions[2]) is True
    # lookback 不一致 → False
    assert typed_match(MinedCondition("HbA1c", "consecutive_rises", 2.0, lookback=1),
                       PR.r1.conditions[2]) is False

def _full_rule(r1):
    return MinedRule(tuple(MinedCondition(c.indicator, c.op, c.value, c.lookback) for c in r1.conditions),
                     r1.horizon_windows, r1.lookback, r1.lag)

def test_full_hit_compares_horizon_lookback_lag():
    r1 = PR.r1
    assert full_hit(_full_rule(r1), r1) is True
    # horizon 不同 → False
    wrong_h = MinedRule(_full_rule(r1).conditions, r1.horizon_windows + 1, r1.lookback, r1.lag)
    assert full_hit(wrong_h, r1) is False
    # lookback 不同 → False
    wrong_lb = MinedRule(_full_rule(r1).conditions, r1.horizon_windows, 1, r1.lag)
    assert full_hit(wrong_lb, r1) is False
    # lag 不同 → False
    wrong_lag = MinedRule(_full_rule(r1).conditions, r1.horizon_windows, r1.lookback, 1)
    assert full_hit(wrong_lag, r1) is False

def test_partial_hit_uses_tolerance_and_proper_subset():
    # v5.29 修正计划测试与 Interfaces 的矛盾：partial_hit = typed 容差下的**非空真子集**
    # （Interfaces 定义）。typed 容差内全匹配（如 age 52 vs 50）→ 等价变体（full 的
    # 容差近似）→ **非真子集 → False**；1 个匹配条件也是非空真子集 → True。
    r1 = PR.r1
    full = _full_rule(r1)
    assert partial_hit(MinedRule(full.conditions[:3], r1.horizon_windows, r1.lookback, r1.lag), r1) is True
    # 一个匹配条件 = 非空真子集 → True
    assert partial_hit(MinedRule(full.conditions[:1], r1.horizon_windows, 1, 0), r1) is True
    # 容差内条件（age 52 vs 50）：typed_match 匹配 planted age50 → 4/4 全匹配 → 等价变体 → False
    close = MinedCondition("age", "gt", 52.0)
    other = tuple(MinedCondition(c.indicator, c.op, c.value, c.lookback) for c in r1.conditions if c.indicator != "age")
    assert partial_hit(MinedRule(other + (close,), r1.horizon_windows, r1.lookback, r1.lag), r1) is False

@pytest.mark.slow
def test_evaluate_instance_level_uses_only_r1r2_rules():
    # v5.29：内嵌 mine_rules(SUB)（Bootstrap 完整链路）→ slow；其余 typed/full/partial 纯函数测试默认跑
    res = evaluate(mine_rules(SUB, 2, [1, 2]), PR, SUB, OUT["coverage"])
    assert res["rule_level_recovery"]["denominator"] == 2
    assert res["instance_level_recovery"]["denominator"] == int(SUB[~SUB["unobservable"]]["patient_id"].nunique())
    assert 0 <= res["instance_level_recovery"]["rate"] <= 1
    # coverage 必须含 r1/r2 键（不接受 get(..., 0) 静默缺失）
    assert "r1" in res["coverage"] and "r2" in res["coverage"]

def test_partial_hit_rejects_unrelated_condition():
    """部分命中排除无关条件（Codex 批次 3 二轮 P2-1）：R1 条件 + 无关 AFP 条件
    → mined 条件集不是 planted 真子集 → False。"""
    r1 = PR.r1
    full = _full_rule(r1)
    unrelated = MinedCondition("AFP", "consecutive_rises", 2.0, lookback=2)
    mixed = MinedRule(full.conditions[:2] + (unrelated,),
                      r1.horizon_windows, r1.lookback, r1.lag)
    assert partial_hit(mixed, r1) is False
    # 对照：纯 planted 子集仍 True
    assert partial_hit(MinedRule(full.conditions[:2], r1.horizon_windows, r1.lookback, r1.lag), r1) is True

def test_partial_hit_time_window_out_of_tolerance():
    """时间窗未达容差（Codex 批次 3 三轮 P2-1，规格 §8.3）：indicator+op 一致但
    lookback 不同（consecutive_rises lookback=1 vs planted 2）→ typed_match False
    → 部分命中 True（时间窗未达容差）。"""
    r1 = PR.r1
    full = _full_rule(r1)
    # 全条件 indicator+op 一致，但 HbA1c lookback=1（planted 2）
    conds = []
    for c in full.conditions:
        if c.indicator == "HbA1c":
            conds.append(MinedCondition("HbA1c", "consecutive_rises", c.value, lookback=1))
        else:
            conds.append(c)
    r = MinedRule(tuple(conds), r1.horizon_windows, r1.lookback, r1.lag)
    assert partial_hit(r, r1) is True        # 时间窗未达容差 → 部分命中
    assert full_hit(r, r1) is False          # 非完整命中（lookback 不一致）

def test_partial_hit_count_tolerance():
    r1 = PR.r1
    full = _full_rule(r1)
    # v5.29：次数 3 vs 2 在 typed 容差（±1）下匹配 planted → 4/4 全匹配 = 等价变体
    # → 非真子集 → False（partial 只认"缺条件"的真子集；typed_match 本身覆盖容差）
    conds = [c for c in full.conditions if c.indicator != "HbA1c"]
    hba1c3 = MinedCondition("HbA1c", "consecutive_rises", 3.0, lookback=2)
    assert partial_hit(MinedRule(tuple(conds) + (hba1c3,), r1.horizon_windows, r1.lookback, r1.lag), r1) is False
