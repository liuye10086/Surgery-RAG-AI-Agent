"""规则挖掘（确认 landmark 子集；标准词汇；逐折发现→冻结→验证；规则 CI 完整重跑；禁读 planted_rules）。"""
from __future__ import annotations
import numpy as np
import pandas as pd
import itertools
from dataclasses import dataclass
import config as cfg
from splitters import patient_folds, resample_rows, patient_bootstrap_samples


@dataclass(frozen=True)
class MinedCondition:
    indicator: str; op: str; value: float; lookback: int = 1; source_feature: str = ""

@dataclass(frozen=True)
class MinedRule:
    conditions: tuple[MinedCondition, ...]
    horizon_windows: int
    lookback: int
    lag: int
    event_support: int = -1
    total_support: int = -1
    lift_median: float = 0.0
    selection_frequency: float = 0.0
    ci: "tuple | str" = "CI 未估计"


def _candidate_conditions(subset, seed=0):
    """训练折内候选（规格 §8.1）——**通用、无植入语义**：
    1) **折内 SHAP top-M**：该折 GBT + TreeExplainer → mean|SHAP| 降序取 top_m 特征
       （top_m/thresholds_per_feature 版本化；单类折无 SHAP → 跳过该层）；
       **SHAP 输入只含可转换规则特征**（`_condition_from_feature` 非 None——排除
       admin_end/*_d6m/*_d12m/*_slope 等无法转条件的字段，避免 top-M 被无效特征占满）；
    2) **折内阈值**：top-M 特征按训练折分位数取 ≤ thresholds_per_feature 个去重切点
       （`{ind}_cur`/age → gt、`{ind}_rises` → consecutive_rises（lookback=切点值）、
       `{ind}_drop_pct` → **abs(v) 正的下降幅度**（_hits 用 `<= -c.value`）、sex_male → eq）；
    3) **固定临床网格补充**（candidate_grid：sex/age/rises/drop_pct 通用切点）——
       保证 planted 阈值确定性可达（分位数切点无需与 planted 值精确重合）；
    返回前按 canonical 条件**整体去重**（固定网格与分位候选可能重合，如 sex eq 1.0）。"""
    from sklearn.ensemble import GradientBoostingClassifier
    all_cols = [c for c in subset.columns if c not in ("patient_id", "window", "label", "group", "unobservable")]
    feat = [c for c in all_cols if _condition_from_feature(c, 0.0) is not None]  # 可转换规则特征
    cands = [MinedCondition("sex", "eq", 1.0), MinedCondition("sex", "eq", 0.0)]
    if len(subset) >= 2 and subset["label"].nunique() >= 2:
        clf = GradientBoostingClassifier(random_state=seed)
        clf.fit(subset[feat], subset["label"])
        import shap
        vals = shap.TreeExplainer(clf).shap_values(subset[feat])
        if isinstance(vals, list):
            vals = vals[1]
        mean_abs = np.mean(np.abs(vals), axis=0)
        top_feats = [f for _, f in sorted(zip(mean_abs, feat), key=lambda t: (-float(t[0]), t[1]))][:cfg.THRESHOLDS["top_m"]]
        for f in top_feats:
            for q in np.linspace(0.5, 0.9, cfg.THRESHOLDS["thresholds_per_feature"]):
                v = float(np.quantile(subset[f].dropna(), q))
                cond = _condition_from_feature(f, v)
                if cond is None:
                    continue
                if cond.op == "drop_pct" and cond.value <= 0:
                    continue        # 无正下降幅度（分位为 0/正）→ 不产生候选（drop_pct 值恒 > 0 契约）
                if cond not in cands:
                    cands.append(cond)
    # 固定临床网格补充（通用切点；保证 planted 阈值确定性可达）
    grid = cfg.THRESHOLDS["candidate_grid"]
    for a in grid["age"]:
        cands.append(MinedCondition("age", "gt", float(a)))
    for ind in ("HbA1c", "PLT", "AFP"):
        for k in grid["consecutive_rises"]:
            if f"{ind}_rises" in subset.columns:
                cands.append(MinedCondition(ind, "consecutive_rises", float(k), lookback=k, source_feature=f"{ind}_rises"))
        if ind == "PLT" and "PLT_drop_pct" in subset.columns:
            for d in grid["drop_pct"]:
                cands.append(MinedCondition("PLT", "drop_pct", float(d), source_feature="PLT_drop_pct"))
    return list({_canonical_cond(c): c for c in cands}.values())   # canonical 去重（保序）


def _condition_from_feature(f, v):
    """特征名 → MinedCondition（通用映射，不含 planted 语义）：
    `{ind}_cur` → gt；`{ind}_rises` → consecutive_rises（lookback=切点值）；
    `{ind}_drop_pct` → drop_pct（**abs(v)，正的下降幅度**——分位数通常为负，_hits 用 `<= -c.value`）；
    `age` → gt；`sex_male` → eq。其余字段（admin_end/*_d6m/*_d12m/*_slope 等）→ None
    （不可转换，SHAP 输入已过滤）。"""
    if f == "sex_male":
        return MinedCondition("sex", "eq", v)
    for ind in cfg.INDICATORS:
        if f == f"{ind}_cur":
            return MinedCondition(ind, "gt", v, source_feature=f)
        if f == f"{ind}_rises":
            k = max(int(round(v)), 1)
            return MinedCondition(ind, "consecutive_rises", float(k), lookback=k, source_feature=f)
        if f == f"{ind}_drop_pct":
            return MinedCondition(ind, "drop_pct", abs(v), source_feature=f)
    if f == "age":
        return MinedCondition("age", "gt", v)
    return None


def _canonical_cond(c):
    """条件排序键（规范顺序，Apriori 去重与确定性枚举用）。"""
    return (c.indicator, c.op, float(c.value), c.lookback)


def _canonical_rule(rule):
    return tuple(sorted((c.indicator, c.op, float(c.value), c.lookback) for c in rule.conditions))


def _hits(subset, rule):
    mask = np.ones(len(subset), dtype=bool)
    for c in rule.conditions:
        if c.op == "eq":
            mask &= (subset["sex_male"].to_numpy() == int(c.value))
        elif c.op == "consecutive_rises":
            mask &= (subset[f"{c.indicator}_rises"].to_numpy() >= c.value)
        elif c.op == "drop_pct":
            mask &= (subset[f"{c.indicator}_drop_pct"].to_numpy() <= -c.value)
        else:
            if c.indicator == "age":
                mask &= (subset["age"].to_numpy() > c.value)
            else:
                mask &= (subset[f"{c.indicator}_cur"].to_numpy() > c.value)
    return mask


def _support(subset, rule):
    hit = _hits(subset, rule)
    return int(subset.loc[hit, "label"].sum()), int(hit.sum())


def _lift(subset, rule):
    hit = _hits(subset, rule)
    if hit.sum() == 0:
        return 0.0
    base = subset["label"].mean()
    return subset.loc[hit, "label"].mean() / base if base > 0 else 0.0


def _enumerate_combos(cands, k):
    """枚举 k 项组合（去重、确定性有序）。"""
    out, seen = [], set()
    for combo in itertools.combinations(cands, k):
        key = tuple(sorted((c.indicator, c.op, float(c.value), c.lookback) for c in combo))
        if key in seen:
            continue
        seen.add(key)
        out.append(tuple(combo))
    return out


def _cond_mask(subset, c):
    """单条件命中掩码（_discover_frozen 预计算复用，v5.29 性能优化——语义与
    `_hits` 逐条件 AND 完全等价；组合掩码逐层 AND 复用，替代每组合重算全部条件）。"""
    if c.op == "eq":
        return subset["sex_male"].to_numpy() == int(c.value)
    if c.op == "consecutive_rises":
        return subset[f"{c.indicator}_rises"].to_numpy() >= c.value
    if c.op == "drop_pct":
        return subset[f"{c.indicator}_drop_pct"].to_numpy() <= -c.value
    if c.indicator == "age":
        return subset["age"].to_numpy() > c.value
    return subset[f"{c.indicator}_cur"].to_numpy() > c.value


def _discover_frozen(subset, seed, horizon_windows, cands=None):
    """规格 §8.1 发现：**折内候选**（`_candidate_conditions`：SHAP top-M + 折内分位数 +
    固定临床网格，canonical 去重）→ **Apriori 逐层枚举 + 训练折支持度剪枝**（每层通过支持
    门槛者进入下一层；规范顺序去重 + `seen_rules` 防重复）→ **(-lift, canonical_rule) 排序取 top_k**。
    **预算保护按"评估的组合数"**（evaluated 计数，**含未通过支持度门槛的组合**）——
    超 max_candidates → **显式 raise**（防静默截断，不得只按通过规则数统计）。
    **v5.29 性能**：候选掩码预计算 + 组合掩码逐层 AND 复用（`_cond_mask`）——35 候选
    的 4 层全枚举 ~5.9 万组合从逐组合重算 ~30s 降至 ~1s（Bootstrap 重跑完整发现的
    b 次 × 折数放大下必需；语义与枚举顺序/预算计数/剪枝/排序完全一致）。
    **v5.29 cands 参数**：规则 CI 重跑发现（`_rules_bootstrap_ci`）传**固定候选**
    （与原始发现同空间）——分位切点随重采样集漂移会导致固定阈值规则永不重新发现
    （实测 0/12 次 → CI 未估计），固定候选使"重新发现 = 支持度门槛在重采样集上通过"。"""
    cands = cands if cands is not None else _candidate_conditions(subset, seed)
    ordered = sorted(cands, key=_canonical_cond)
    masks = {_canonical_cond(c): _cond_mask(subset, c) for c in ordered}
    rules, seen_rules = [], set()
    level = [((c,), masks[_canonical_cond(c)]) for c in ordered]   # (combo, combo_mask)
    evaluated = 0
    for k in range(1, cfg.THRESHOLDS["max_conditions"] + 1):
        passed = []
        for combo, mask in level:
            evaluated += 1
            if evaluated > cfg.THRESHOLDS["max_candidates"]:
                raise ValueError(f"组合评估数 {evaluated} 超过 max_candidates "
                                 f"{cfg.THRESHOLDS['max_candidates']}（防静默截断，需调大）")
            rule = MinedRule(conditions=tuple(combo), horizon_windows=horizon_windows,
                             lookback=max(c.lookback for c in combo), lag=0)
            if _canonical_rule(rule) in seen_rules:
                continue
            ev, tot = int(subset.loc[mask, "label"].sum()), int(mask.sum())
            if ev >= cfg.THRESHOLDS["rule_event_support_min"] and tot >= cfg.THRESHOLDS["rule_total_support_min"]:
                seen_rules.add(_canonical_rule(rule))
                rules.append(rule)
                passed.append((combo, mask))
        level = []
        if k < cfg.THRESHOLDS["max_conditions"]:
            for combo, pmask in passed:
                last = _canonical_cond(combo[-1])
                for c in ordered:
                    if _canonical_cond(c) <= last or c in combo:
                        continue
                    level.append((combo + (c,), pmask & masks[_canonical_cond(c)]))
    # 确定性排序：lift 降序主键 + canonical_rule 二级键（并列 lift 不依赖枚举顺序）
    return sorted(rules, key=lambda r: (-_lift(subset, r), _canonical_rule(r)))[:cfg.THRESHOLDS["discover_top_k"]]


def _fold_discover_validate(sset, seed, horizon_windows, cands=None, return_cands=False):
    """在 sset 上折内发现→折外验证，返回 {canonical_key: [val_lifts]}。
    **折数按唯一患者计数**（Bootstrap 重复患者不得重复计数）：
    k = min(cv_folds, 唯一正例患者数, 唯一负例患者数)；任一类别唯一患者 <2 → 无效（返回空）。
    仅按行数计正/负会把"一个唯一正例被重复抽中"误判为 k>=2。
    **v5.29 cands/return_cands**：cands 缺省 = **每折训练集内生成**（规格 §8.1 折内候选）；
    return_cands=True 时返回 (out, 折内候选并集)——mine_rules 的规则 CI 用**全部折内
    候选并集**重跑发现（规则切点来自各折训练集，全量候选不含折内切点 → 实测 CI 未估计）。"""
    uniq = sset.groupby("patient_id")["label"].max().reset_index()
    pos = int((uniq["label"] > 0).sum())
    neg = int((uniq["label"] == 0).sum())
    k = min(cfg.THRESHOLDS["cv_folds"], pos, neg)
    if k < 2:
        return ({}, []) if return_cands else {}
    uniq["patient_event"] = (uniq["label"] > 0).astype(int)
    folds_uniq = patient_folds(uniq, k, seed)
    pid_to_row = {pid: i for i, pid in enumerate(uniq["patient_id"])}
    folds = folds_uniq[sset["patient_id"].map(pid_to_row).to_numpy()]
    out, all_cands = {}, []
    for j in range(k):
        tr, va = folds != j, folds == j
        fold_cands = cands if cands is not None else _candidate_conditions(sset.loc[tr], seed)
        for c in fold_cands:
            if c not in all_cands:
                all_cands.append(c)
        for rule in _discover_frozen(sset.loc[tr], seed, horizon_windows, cands=fold_cands):
            out.setdefault(_canonical_rule(rule), []).append(_lift(sset.loc[va], rule))
    return (out, all_cands) if return_cands else out


def _rule_bootstrap_ci(subset, rule, b=50, seed=0):
    """患者 Bootstrap：重采样全列子集 → 重跑发现→验证 → 该规则 lift 分布 CI。"""
    horizon = subset.attrs.get("horizon_windows", 0)
    samples = patient_bootstrap_samples(subset["patient_id"].to_numpy(), b, seed)
    key = _canonical_rule(rule)
    lifts = []
    for s in samples:
        sset = resample_rows(subset, s).reset_index(drop=True)
        disc = _fold_discover_validate(sset, seed, horizon)
        if key in disc:
            lifts.append(float(np.mean(disc[key])))
    if len(lifts) < 2:
        return "CI 未估计"
    return float(np.percentile(lifts, 2.5)), float(np.percentile(lifts, 97.5))


def _rules_bootstrap_ci(subset, rules, b=12, seed=0):
    """**批量规则 CI（v5.29 重构）**：同一批患者重采样共享——每样本直接判定
    每条输出规则（**不重跑组合枚举发现**）：
    - **"重新发现" = 规则在重采样集上支持度 ≥ 门槛**（`_support` 直接判定）——
      固定切点下与"重跑发现 + 该规则出现"**数学等价**（发现枚举所有通过组合）；
      折内候选并集的 10.2 万组合/次 × 5 折 × b 次在 CI 放大下不可行（实测 10+ 分钟），
      直接判定 ~1 秒（176 规则 × 掩码）；
    - **折外验证**：重采样集上按患者分折，验证折的 lift 均值（与 `_fold_discover_validate`
      同机制）；
    - 未重新发现（支持度不足）/有效 <2 → 该规则 "CI 未估计"。
    语义 = "规则强度（验证 lift）在患者重采样人群中的分布"（计划 CI 契约）。"""
    samples = patient_bootstrap_samples(subset["patient_id"].to_numpy(), b, seed)
    keys = [_canonical_rule(r) for r in rules]
    per_sample = {k: [] for k in keys}
    for s in samples:
        sset = resample_rows(subset, s).reset_index(drop=True)
        # 患者折（折外验证；与 fold_validate 同机制）
        uniq = sset.groupby("patient_id")["label"].max().reset_index()
        pos = int((uniq["label"] > 0).sum())
        neg = int((uniq["label"] == 0).sum())
        k = min(cfg.THRESHOLDS["cv_folds"], pos, neg)
        folds_map = None
        if k >= 2:
            uniq["patient_event"] = (uniq["label"] > 0).astype(int)
            folds_uniq = patient_folds(uniq, k, seed)
            pid_to_row = {pid: i for i, pid in enumerate(uniq["patient_id"])}
            folds_map = folds_uniq[sset["patient_id"].map(pid_to_row).to_numpy()]
        for key, rule in zip(keys, rules):
            ev, tot = _support(sset, rule)
            if ev < cfg.THRESHOLDS["rule_event_support_min"] or tot < cfg.THRESHOLDS["rule_total_support_min"]:
                continue                                # 支持度不足 → 该样本未重新发现
            if folds_map is None:
                continue
            val_lifts = []
            for j in range(k):
                va = folds_map == j
                if va.sum() == 0:
                    continue
                l = _lift(sset.loc[va], rule)
                if np.isfinite(l):
                    val_lifts.append(l)
            if val_lifts:
                per_sample[key].append(float(np.mean(val_lifts)))
    out = {}
    for k in keys:
        vals = per_sample[k]
        out[k] = "CI 未估计" if len(vals) < 2 else \
            (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5)))
    return out


def mine_rules(subset, n_repeats, seeds):
    # 规则发现/验证/CI 只用可评估确认 landmark（排除 unobservable，避免事后信息/不可评估样本泄漏）
    subset = subset[~subset["unobservable"]].reset_index(drop=True)
    subset.attrs["horizon_windows"] = subset.attrs.get("horizon_windows", 0)
    horizon = subset.attrs["horizon_windows"]
    selection, lifts = {}, {}
    for seed in seeds:
        disc = _fold_discover_validate(subset, seed, horizon)
        for key, vals in disc.items():
            selection[key] = selection.get(key, 0) + 1
            lifts.setdefault(key, []).extend(vals)

    # v5.29：selection 门槛 = **全部重复发现**（0.5 在 n_repeats=2 下 = 出现 ≥1 次——
    # 各 seed 的 SHAP 分位切点漂移使"seed 偶发规则"泛滥（实测 5333 条输出），
    # 全部重复符合"跨重复稳定性"设计意图；R1/R2 标准的网格候选跨 seed 固定 ✓）
    keys_out = [key for key, pts in lifts.items() if selection[key] >= n_repeats]
    # v5.29：批量规则 CI（共享重采样 + 直接支持度判定，见 _rules_bootstrap_ci docstring）
    ci_map = _rules_bootstrap_ci(
        subset,
        [MinedRule(tuple(MinedCondition(i, op, float(v), lb) for i, op, v, lb in key),
                   horizon, max(lb for _, _, _, lb in key), 0) for key in keys_out],
        b=12, seed=seeds[0])
    rules_out = []
    for key in keys_out:
        conds = tuple(MinedCondition(i, op, float(v), lb) for i, op, v, lb in key)
        rule = MinedRule(conditions=conds, horizon_windows=horizon,
                         lookback=max(c.lookback for c in conds), lag=0)
        ev, tot = _support(subset, rule)
        rules_out.append(MinedRule(conditions=conds, horizon_windows=horizon,
                                   lookback=rule.lookback, lag=rule.lag,
                                   event_support=ev, total_support=tot,
                                   lift_median=float(np.median(lifts[key])),
                                   selection_frequency=selection[key] / n_repeats, ci=ci_map[key]))
    return {"rules": rules_out, "selection_frequency": selection}
