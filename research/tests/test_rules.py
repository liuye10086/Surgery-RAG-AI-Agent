import numpy as np
import pytest
import config as cfg
from simulate_cohort import simulate
from features import confirmation_subset
from rules import (mine_rules, MinedCondition, MinedRule, _candidate_conditions,
                   _fold_discover_validate, _rule_bootstrap_ci,
                   _discover_frozen, _canonical_rule, _canonical_cond,
                   _lift, _support, _enumerate_combos, _hits)

OUT = simulate(n=1500, followup_months=60, horizon_months=24, seed=6)
SUB = confirmation_subset(OUT["patients"], OUT["obs"], horizon_windows=4)

# v5.29：SUB 上的 mine_rules 重测试标 slow（Bootstrap CI 对每条规则重跑完整发现——
# 规则数 × b × 折数的本质成本；计划 pytest.ini 的 slow 分层，Task 14 同款）。
# 验收时显式 `pytest -m slow` 一次性运行。

def test_no_planted_rules():
    import inspect
    assert "planted_rules" not in inspect.signature(mine_rules).parameters

def test_candidates_standard_include_age():
    cands = _candidate_conditions(SUB, seed=1)   # 折内 SHAP top-M + 分位数 + 固定临床网格
    ops = {c.op for c in cands}
    assert {"eq", "gt", "consecutive_rises", "drop_pct"} <= ops
    assert any(c.indicator == "age" and c.op == "gt" for c in cands)
    assert all(isinstance(c.value, float) for c in cands)   # 数值保类型

def test_candidate_contract():
    cands = _candidate_conditions(SUB, seed=1)
    # 1) 元数据/派生特征排除：source_feature 不含 admin_end/*_d6m/*_d12m/*_slope
    for c in cands:
        if c.source_feature:
            assert c.source_feature != "admin_end"
            assert not c.source_feature.endswith(("_d6m", "_d12m", "_slope")), c.source_feature
    # 2) drop_pct 值恒为正（下降幅度；_hits 用 <= -c.value，方向不得反转）
    assert all(c.value > 0 for c in cands if c.op == "drop_pct")
    # 3) sex 条件恒 eq（分位数/网格不得产生 sex gt）
    assert all(c.op == "eq" for c in cands if c.indicator == "sex")
    # 4) top-M 上限：SHAP 分位特征数 ≤ top_m，每特征切点数 ≤ thresholds_per_feature
    #    （_cur 分位特征；固定网格的 rises/drop/age 另行计数）
    from collections import Counter
    cnt = Counter(c.source_feature for c in cands if c.source_feature)
    quant_feats = {f for f in cnt if f.endswith("_cur")}
    assert len(quant_feats) <= cfg.THRESHOLDS["top_m"], len(quant_feats)
    for f in quant_feats:
        assert cnt[f] <= cfg.THRESHOLDS["thresholds_per_feature"], (f, cnt[f])
    # 5) 候选无重复（canonical 唯一）
    keys = [(c.indicator, c.op, float(c.value), c.lookback) for c in cands]
    assert len(keys) == len(set(keys))

@pytest.mark.slow
def test_mine_rules_returns_minedrule_with_real_ci():
    res = mine_rules(SUB, 2, [1, 2])
    assert len(res["rules"]) > 0
    for r in res["rules"]:
        assert isinstance(r, MinedRule)
        assert r.event_support >= 5 and r.total_support >= 20
        assert r.selection_frequency > 0
    # v5.29：低支持规则（ev 5-30）在 b=12 重采样中重新发现 <2 次 → "CI 未估计"
    # 是统计现实（正确行为）；断言改为**高支持规则（ev ≥ 30）携带数值 CI**——
    # 方法验证意图（主要规则可估计；R1/R2 标准 ev 151/125 在此列）
    high = [r for r in res["rules"] if r.event_support >= 30]
    assert high, "大 N fixture 下应存在高支持规则"
    assert all(isinstance(r.ci, tuple) and r.ci[0] <= r.ci[1] for r in high)

@pytest.mark.slow
def test_at_least_one_r1_and_r2_full_hit_rule():
    """确定性：挖回规则包含与植入 R1/R2 标准语义精确一致的规则（drop_pct 比例单位 0.20）。"""
    from rules import _canonical_rule, MinedCondition, MinedRule
    from evaluator import full_hit
    r1_std = MinedRule(tuple([
        MinedCondition("sex", "eq", 1.0),
        MinedCondition("age", "gt", 50.0),
        MinedCondition("HbA1c", "consecutive_rises", 2.0, lookback=2),
        MinedCondition("PLT", "drop_pct", 0.20),
    ]), horizon_windows=4, lookback=2, lag=0)
    r2_std = MinedRule(tuple([MinedCondition("AFP", "consecutive_rises", 2.0, lookback=2)]),
                       horizon_windows=4, lookback=2, lag=0)
    mined = mine_rules(SUB, 2, [1, 2])
    keys = {_canonical_rule(r) for r in mined["rules"]}
    assert _canonical_rule(r1_std) in keys
    assert _canonical_rule(r2_std) in keys
    # 直接对植入规律做 full_hit（含 horizon/lookback/lag + 类型化条件）
    assert any(full_hit(r, OUT["planted_rules"].r1) for r in mined["rules"])
    assert any(full_hit(r, OUT["planted_rules"].r2) for r in mined["rules"])

def _unique_pos_neg_frame():
    """确定性 fixture：唯一正例患者（重复 20 行）+ 唯一负例患者（重复 10 行）。
    按行数正 20/负 10（旧实现会误判 k>=2），按唯一患者正 1/负 1 → 折数不足。"""
    import pandas as pd
    rows = ([{"patient_id": 0, "label": 1, "age": 55, "sex_male": 1,
              "HbA1c_rises": 2, "PLT_drop_pct": -0.25, "AFP_rises": 0,
              **{f"{i}_cur": 1.0 for i in cfg.INDICATORS}} for _ in range(20)]
            + [{"patient_id": 1, "label": 0, "age": 30, "sex_male": 0,
                "HbA1c_rises": 0, "PLT_drop_pct": 0.0, "AFP_rises": 0,
                **{f"{i}_cur": 1.0 for i in cfg.INDICATORS}} for _ in range(10)])
    sub = pd.DataFrame(rows)
    sub.attrs["horizon_windows"] = 4
    return sub

def test_fold_validate_unique_patient_denominator():
    # 唯一正例被 Bootstrap 重复抽中 → 按唯一患者仍仅 1 正例 → 折数不足 → 返回空
    assert _fold_discover_validate(_unique_pos_neg_frame(), 1, 4) == {}

def test_discover_no_duplicate_rules():
    # Apriori 逐层 + seen_rules：重复候选（固定网格与分位候选可能重合）不得产生重复规则
    rules = _discover_frozen(SUB, 1, 4)
    keys = [_canonical_rule(r) for r in rules]
    assert len(keys) == len(set(keys))

def test_discover_budget_raises(monkeypatch):
    # 预算保护按**评估的组合数**（含未通过支持度门槛的组合）——max_candidates 极小 → 显式 raise
    monkeypatch.setitem(cfg.THRESHOLDS, "max_candidates", 5)
    with pytest.raises(ValueError):
        _discover_frozen(SUB, 1, 4)

def test_discover_sorted_by_lift_then_canonical():
    # 确定性契约：lift 降序主键 + canonical_rule 二级键（并列 lift 不依赖组合枚举顺序）
    rules = _discover_frozen(SUB, 1, 4)
    lifts = [_lift(SUB, r) for r in rules]
    keys = [_canonical_rule(r) for r in rules]
    assert lifts == sorted(lifts, reverse=True)                       # lift 非升
    for i in range(len(rules) - 1):
        if abs(lifts[i] - lifts[i + 1]) < 1e-12:
            assert keys[i] <= keys[i + 1], (keys[i], keys[i + 1])     # 并列段内 canonical 升序
    # 同输入两次运行逐位一致（枚举顺序无关）
    again = _discover_frozen(SUB, 1, 4)
    assert [_canonical_rule(r) for r in again] == keys

def test_support_unique_patient_in_resample():
    """支持度按唯一患者（Codex 批次 3 P1-2）：Bootstrap 重采样保留重复患者行，
    事件/总支持不重复计（行级会是 10/10，唯一患者 1/1）。"""
    import pandas as pd
    from rules import _support
    rows = ([{"patient_id": 0, "label": 1, "sex_male": 1, "HbA1c_rises": 2,
              "age": 55, "PLT_drop_pct": -0.25, "AFP_rises": 0,
              **{f"{i}_cur": 1.0 for i in cfg.INDICATORS}}] * 10
            + [{"patient_id": 1, "label": 0, "sex_male": 0, "HbA1c_rises": 0,
                "age": 30, "PLT_drop_pct": 0.0, "AFP_rises": 0,
                **{f"{i}_cur": 1.0 for i in cfg.INDICATORS}}] * 10)
    sub = pd.DataFrame(rows)
    rule = MinedRule((MinedCondition("sex", "eq", 1.0),), 4, 1, 0)
    ev, tot = _support(sub, rule)
    assert (ev, tot) == (1, 1)          # 唯一患者：1 正例 1 总（行级会是 10/10）

def test_rules_ci_preserves_multiplicity(monkeypatch):
    """CI 保留 multiplicity（Codex 批次 4 三轮 P2-1）：monkeypatch resample_rows 记录
    _rules_bootstrap_ci 实际传入的样本，断言其**含重复患者行**（未 drop_duplicates）——
    锁定的是 CI 函数内部行为，而非 resample_rows 本身。"""
    import pandas as pd
    import rules as rules_mod
    from rules import _rules_bootstrap_ci
    rows = []
    for pid, label in ((0, 1), (1, 1), (2, 0), (3, 0)):
        rows.append({"patient_id": pid, "label": label, "sex_male": 1, "age": 55,
                     "HbA1c_rises": 2 if label else 0, "PLT_drop_pct": -0.25 if label else 0.0,
                     "AFP_rises": 0, "admin_end": 8,
                     **{f"{ind}_cur": 1.0 for ind in cfg.INDICATORS}})
    sub = pd.DataFrame(rows)
    sub.attrs["horizon_windows"] = 4
    rule = MinedRule((MinedCondition("sex", "eq", 1.0),), 4, 1, 0)
    # 记录 CI 内部对 resample_rows 结果的后续处理：monkeypatch 让 resample_rows 返回
    # 含重复患者的样本，并在返回前记录"该样本是否被 drop_duplicates 过"
    observed = {"saw_duplicate": False, "called": 0}
    real_resample = rules_mod.resample_rows
    def spy_resample(frame, sampled_ids):
        out = real_resample(frame, sampled_ids)
        observed["called"] += 1
        if not out["patient_id"].is_unique:
            observed["saw_duplicate"] = True      # resample_rows 返回含重复患者的样本
        return out
    monkeypatch.setattr(rules_mod, "resample_rows", spy_resample)
    # 若 CI 内部 drop_duplicates，则后续 groupby/计数会基于去重后；此处断言 resample_rows
    # 返回的含重复样本确实被传入（未在 CI 入口被 drop）。用确定性 b 保证至少一个重复样本。
    _rules_bootstrap_ci(sub, [rule], b=20, seed=0)
    assert observed["called"] == 20              # 20 次重采样都走 spy
    assert observed["saw_duplicate"] is True     # 至少一个样本含重复患者（multiplicity 保留）

def test_unique_patient_consistency_across_paths():
    """全链路唯一患者一致性（Codex 批次 3 三轮 P1-3）：_support/_lift/_discover_frozen
    在含重复患者的子集上，与"先 drop_duplicates 再行级"**严格等价**——发现路径的
    nunique 与 CI 路径的去重后行级是同一唯一患者口径（行顺序变化也不变）。"""
    import pandas as pd
    from rules import _support, _lift, _discover_frozen, _canonical_rule
    # 正例患者 0（重复 3 行）+ 负例患者 1/2/3（各 1 行）+ 打乱行序
    base = []
    for pid, label, sex, hba1c, drop in ((0, 1, 1, 2, -0.25), (1, 0, 0, 0, 0.0),
                                          (2, 0, 1, 2, -0.25), (3, 0, 0, 0, 0.0)):
        base.append({"patient_id": pid, "label": label, "sex_male": sex,
                     "age": 55 if label else 30, "HbA1c_rises": hba1c,
                     "PLT_drop_pct": drop, "AFP_rises": 0,
                     **{f"{i}_cur": 1.0 for i in cfg.INDICATORS}})
    dup = base[:1] * 3 + base[1:]                # 患者 0 重复 3 行
    dup = pd.DataFrame(dup[::-1]).reset_index(drop=True)   # 行序倒转
    dedup = dup.drop_duplicates("patient_id").reset_index(drop=True)
    rule = MinedRule((MinedCondition("HbA1c", "consecutive_rises", 2.0, lookback=2),
                      MinedCondition("sex", "eq", 1.0)), 4, 2, 0)
    # _support/_lift 唯一患者 == 去重后行级
    assert _support(dup, rule) == _support(dedup, rule)
    assert abs(_lift(dup, rule) - _lift(dedup, rule)) < 1e-12
    # _discover_frozen 的通过规则集（canonical 键）在 dup 与 dedup 上一致
    # （dup 无 horizon attrs → 直接传显式 horizon；用固定候选避免 SHAP seed 漂移）
    from rules import _candidate_conditions
    cands = _candidate_conditions(dedup, seed=1)
    keys_dup = {_canonical_rule(r) for r in _discover_frozen(dup, 1, 4, cands=cands)}
    keys_dedup = {_canonical_rule(r) for r in _discover_frozen(dedup, 1, 4, cands=cands)}
    assert keys_dup == keys_dedup

def test_rules_ci_requires_fold_train_support():
    """CI 折内发现判定（Codex 批次 3 P1-1 反例）：规则须在**每个训练折**支持度 ≥ 门槛
    ——全体事件支持达标（ev=6 ≥ 5）但 3 折训练集各 8 人（正例 ~4 < 5）→ 折内不发现
    → CI 未估计（旧实现按全体支持度判定会给数值 CI——estimand 错误）。"""
    import pandas as pd
    from rules import _rules_bootstrap_ci
    rows = []
    for i in range(6):
        rows.append({"patient_id": i, "label": 1, "age": 55, "sex_male": 1,
                     "HbA1c_rises": 2, "PLT_drop_pct": -0.25, "AFP_rises": 0,
                     **{f"{ind}_cur": 1.0 for ind in cfg.INDICATORS}})
    for i in range(6, 12):
        rows.append({"patient_id": i, "label": 0, "age": 30, "sex_male": 0,
                     "HbA1c_rises": 0, "PLT_drop_pct": 0.0, "AFP_rises": 0,
                     **{f"{ind}_cur": 1.0 for ind in cfg.INDICATORS}})
    sub = pd.DataFrame(rows)
    sub.attrs["horizon_windows"] = 4
    rule = MinedRule(tuple([MinedCondition("sex", "eq", 1.0),
                            MinedCondition("HbA1c", "consecutive_rises", 2.0, lookback=2)]), 4, 2, 0)
    assert _support(sub, rule)[0] == 6          # 全体事件支持达标
    ci = _rules_bootstrap_ci(sub, [rule], b=5, seed=0)
    assert ci[_canonical_rule(rule)] == "CI 未估计"

def test_discover_returns_all_passing():
    """top_k 全量不截断（Codex 批次 3 P1-3）：输出 = 全部通过支持度的组合
    （无静默截断——硬截断会丢弃 planted 规则）。"""
    rules = _discover_frozen(SUB, 1, 4)
    cands = _candidate_conditions(SUB, 1)
    passing = 0
    for k in range(1, cfg.THRESHOLDS["max_conditions"] + 1):
        for combo in _enumerate_combos(cands, k):
            rule = MinedRule(tuple(combo), 4, max(c.lookback for c in combo), 0)
            ev, tot = _support(SUB, rule)
            if ev >= cfg.THRESHOLDS["rule_event_support_min"] \
                    and tot >= cfg.THRESHOLDS["rule_total_support_min"]:
                passing += 1
    assert len(rules) == passing

def test_candidate_stability_across_seeds():
    """候选跨 seed 稳定性（v5.29，Codex P2-3 风险记录）：SHAP top-M 特征随 seed
    漂移是已知限制（规则身份由 canonical 精确值承载、selection=全部重复过滤
    seed 偶发规则）；**planted 语义条件（固定网格）跨 seed 恒在**。"""
    c1 = {_canonical_cond(c) for c in _candidate_conditions(SUB, 1)}
    c2 = {_canonical_cond(c) for c in _candidate_conditions(SUB, 2)}
    for c in (("sex", "eq", 1.0, 1), ("age", "gt", 50.0, 1),
              ("HbA1c", "consecutive_rises", 2.0, 2), ("PLT", "drop_pct", 0.2, 1)):
        assert c in c1 and c in c2, c
    assert len(c1 & c2) >= 0.4 * min(len(c1), len(c2)), (len(c1), len(c2))

def test_selection_uses_full_subset_consensus(monkeypatch):
    """重复内共识（Codex 批次 3 三轮 P1-2，规格 §8.1）：**合并验证折列联表
    （= 完整 subset，每患者 1 行）重算 support**——单折发现的规则若完整 subset
    support 达标仍计入（替代二轮"≥2 折发现"heuristic）。"""
    import pandas as pd
    import rules as rules_mod
    # 25 正例（male）+ 20 负例（female）：sex eq 1.0 → ev=25 tot=25 达标；sex eq 0.0 → ev=0 不足
    rows = []
    for i in range(25):
        rows.append({"patient_id": i, "label": 1, "sex_male": 1, "age": 55,
                     "unobservable": False, "HbA1c_rises": 2, "PLT_drop_pct": -0.25,
                     "AFP_rises": 0, "admin_end": 8,
                     **{f"{ind}_cur": 1.0 for ind in cfg.INDICATORS}})
    for i in range(25, 45):
        rows.append({"patient_id": i, "label": 0, "sex_male": 0, "age": 30,
                     "unobservable": False, "HbA1c_rises": 0, "PLT_drop_pct": 0.0,
                     "AFP_rises": 0, "admin_end": 8,
                     **{f"{ind}_cur": 1.0 for ind in cfg.INDICATORS}})
    sub = pd.DataFrame(rows)
    sub.attrs["horizon_windows"] = 4
    # 单折发现（各 1 个 lift）——但完整 subset support 才是共识判定
    fake = {(("sex", "eq", 1.0, 1),): [1.0], (("sex", "eq", 0.0, 1),): [1.0]}
    monkeypatch.setattr(rules_mod, "_fold_discover_validate", lambda *a, **k: fake)
    res = rules_mod.mine_rules(sub, 1, [1])
    # sex eq 1.0 完整 subset ev=25 tot=25 达标 → 计入（尽管单折发现）
    assert (("sex", "eq", 1.0, 1),) in res["selection_frequency"]
    # sex eq 0.0 完整 subset ev=0 tot=20（ev<5）不足 → 不计入
    assert (("sex", "eq", 0.0, 1),) not in res["selection_frequency"]

def test_rule_ci_failure_mode():
    # 确定性失败契约：唯一正例重复抽中 → 全部样本无效 → **必然** "CI 未估计"
    # （不允许 tuple 兜底模糊——用确定性 fixture 验证失败路径，而非"小样本可退化"）
    rule = MinedRule((MinedCondition("sex", "eq", 1.0),), 4, 1, 0)
    ci = _rule_bootstrap_ci(_unique_pos_neg_frame(), rule, b=5, seed=0)
    assert ci == "CI 未估计"

def test_synthetic_fixture_discovers_r1_full_hit():
    """确定性 synthetic fixture（不依赖模拟器）：**40 正例（满足 R1 四条件，唯一患者）+
    20 确定性负例（不满足任何条件，唯一患者）+ 4 困难负例**——负例保证
    `_fold_discover_validate` 折数可用；折内候选（SHAP top-M + 分位数 + 固定网格）→
    **Apriori 逐层 + 支持度剪枝**（R1 四条件组合各层支持度均通过 → 必然被枚举）+
    **(-lift, canonical) 排序**保证 R1 四条件组合（正例全命中、lift 唯一最高）确定性进入
    top_k → full_hit 确定性成立。"""
    from rules import mine_rules
    from evaluator import full_hit
    sub = _synthetic_fixture()
    res = mine_rules(sub, 1, [1])
    assert any(full_hit(r, OUT["planted_rules"].r1) for r in res["rules"])

def test_synthetic_fixture_r1_rule_in_top_k():
    # 验收 n_rules 依赖链：**R1 canonical 规则必须确定性进入 _discover_frozen 的 top_k**
    # （"候选全集存在" ≠ "最终结果一定包含"——并列 lift 由 canonical 二级键稳定；
    # 若规则未进 top-k，Task 14 验收的 n_rules/full_hit 前提即失败，本断言兜底）
    from rules import _discover_frozen
    disc = _discover_frozen(_synthetic_fixture(), 1, 4)
    keys = {_canonical_rule(r) for r in disc}
    r1_std = MinedRule(tuple([
        MinedCondition("sex", "eq", 1.0), MinedCondition("age", "gt", 50.0),
        MinedCondition("HbA1c", "consecutive_rises", 2.0, lookback=2),
        MinedCondition("PLT", "drop_pct", 0.20),
    ]), horizon_windows=4, lookback=2, lag=0)
    assert _canonical_rule(r1_std) in keys

def test_synthetic_fixture_r1_rule_is_unique_max_lift():
    # R1 四条件组合是 lift **最高**的规则（困难负例覆盖论证的可执行证明）：
    # 枚举全部候选组合（1..max_conditions，满足支持门槛）后，最大 lift 集合
    # **包含 R1 标准**且**所有最大 lift 规则都与 R1 命中相同正例集**（等价变体）。
    # v5.29：允许 SHAP 分位切点的**等价阈值变体并列**（fixture 的 PLT_drop 分位
    # 全为 -0.25 → 切点 drop 0.25，与网格 0.20 命中相同正例集、lift 完全相同）——
    # canonical 排序（0.20 < 0.25）保证 R1 标准仍在变体前、确定性进 top_k
    # （test_synthetic_fixture_r1_rule_in_top_k 已断言）；"唯一"过强（分位切点
    # 的合法产物），改为"包含 R1 + 全等价"。
    sub = _synthetic_fixture()
    cands = _candidate_conditions(sub, seed=1)
    lifts = {}
    for k in range(1, cfg.THRESHOLDS["max_conditions"] + 1):
        for combo in _enumerate_combos(cands, k):
            rule = MinedRule(tuple(combo), 4, max(c.lookback for c in combo), 0)
            ev, tot = _support(sub, rule)
            if ev >= cfg.THRESHOLDS["rule_event_support_min"] and tot >= cfg.THRESHOLDS["rule_total_support_min"]:
                lifts[_canonical_rule(rule)] = _lift(sub, rule)
    best = max(lifts.values())
    max_keys = [k for k, v in lifts.items() if v == best]
    r1_std = MinedRule(tuple([
        MinedCondition("sex", "eq", 1.0), MinedCondition("age", "gt", 50.0),
        MinedCondition("HbA1c", "consecutive_rises", 2.0, lookback=2),
        MinedCondition("PLT", "drop_pct", 0.20),
    ]), horizon_windows=4, lookback=2, lag=0)
    assert _canonical_rule(r1_std) in max_keys          # 最大 lift 包含 R1 标准
    # 所有最大 lift 规则命中同一正例集（与 R1 等价：困难负例覆盖论证的实质）
    hits_r1 = _hits(sub, r1_std)
    for k in max_keys:
        rule = MinedRule(tuple(MinedCondition(i, op, float(v), lb) for i, op, v, lb in k),
                         4, max(lb for _, _, _, lb in k), 0)
        assert np.array_equal(_hits(sub, rule), hits_r1), k

def _synthetic_fixture():
    """40 正例（满足 R1 四条件，唯一患者）+ 20 简单负例（不满足任何条件）+
    **4 个困难负例**（R1 四条件各缺一个，其余条件保持正例值）——确定性可发现 R1。

    正例特征（age 55, sex_male 1, HbA1c_rises 2, PLT_drop_pct -0.25）同时蕴含宽松条件
    age>40 / HbA1c_rises≥1 / PLT_drop≤-0.10，因此正例满足 7 个候选条件；
    若无困难负例，这 7 个条件的 1–4 组合共 98 条 lift 并列最高，R1 四条件按 canonical 排序
    约第 60 位，进不了 top_k=20。困难负例使**只有 R1 四条件组合是 lift 严格唯一最高**：
    任意非 R1 组合至少缺一个 R1 条件（sex1/age50/HbA1c2/PLTdrop0.2），对应困难负例
    恰好满足"除该条件外其余全部候选条件"→ 命中该组合且不命中 R1。恢复 Apriori 逐层 +
    确定性排序的验证，**不引入 planted-rule 优先排序**。"""
    import pandas as pd
    rows = []
    for i in range(40):                       # 正例：满足 R1 四条件
        rows.append({
            "patient_id": i, "window": 2, "age": 55, "sex_male": 1,
            "group": "r1_only", "unobservable": False, "admin_end": 8, "label": 1,
            "HbA1c_rises": 2, "PLT_drop_pct": -0.25, "AFP_rises": 0,
            **{f"{ind}_cur": 1.0 for ind in cfg.INDICATORS},
        })
    for i in range(40, 60):                   # 简单负例：不满足任何条件
        rows.append({
            "patient_id": i, "window": 2, "age": 30, "sex_male": 0,
            "group": "neither", "unobservable": False, "admin_end": 8, "label": 0,
            "HbA1c_rises": 0, "PLT_drop_pct": 0.0, "AFP_rises": 0,
            **{f"{ind}_cur": 1.0 for ind in cfg.INDICATORS},
        })
    # 困难负例：R1 四条件各缺一个（其余 = 正例值），覆盖所有非 R1 组合
    hard = [(60, 55, 0, 2, -0.25),     # 缺 sex1
            (61, 45, 1, 2, -0.25),     # 缺 age50（45 满足 age>40、不满足 >50）
            (62, 55, 1, 1, -0.25),     # 缺 HbA1c_rises≥2（rises1 满足 ≥1、不满足 ≥2）
            (63, 55, 1, 2, -0.15)]     # 缺 PLT_drop≤-0.20（-0.15 满足 ≤-0.10、不满足 ≤-0.20）
    for pid, age, sex, hba1c, drop in hard:
        rows.append({
            "patient_id": pid, "window": 2, "age": age, "sex_male": sex,
            "group": "neither", "unobservable": False, "admin_end": 8, "label": 0,
            "HbA1c_rises": hba1c, "PLT_drop_pct": drop, "AFP_rises": 0,
            **{f"{ind}_cur": 1.0 for ind in cfg.INDICATORS},
        })
    sub = pd.DataFrame(rows)
    sub.attrs["horizon_windows"] = 4
    return sub
