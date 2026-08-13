"""规模退化 Monte Carlo 实验（§8.2）。"""
from __future__ import annotations
import numpy as np
import config as cfg
from simulate_cohort import simulate, calibrate_gates
from features import qualifying_landmarks, confirmation_subset
from model import fit_and_oof
from rules import mine_rules
from evaluator import evaluate


_CAL_CACHE = {}          # v5.29：模块级校准缓存（calibrate_gates(50k) 单次 ~100s，
                         # Monte Carlo 循环里每次 run_cell 重新校准不可行——同 horizon 只校准一次）


def _calibrated_for(horizon_months):
    if horizon_months not in _CAL_CACHE:
        _CAL_CACHE[horizon_months] = calibrate_gates(horizon_months, cal_n=cfg.SIM["calibration_n"])
    return _CAL_CACHE[horizon_months]


def _cell_feasible(followup_months, horizon_months):
    """路径组有无可行确认锚点（v5.22，Codex 二轮 P1-4 执行契约）：锚点下界
    w_R1 ≥ max(3, w0+3)=4（w0=1 最坏）、w_A ≥ max(1, w0+2)=3 需 ≤ 上界
    admin_end−hw（R1）/ admin_end−hw−1（R2）→ 统一条件 admin_end−hw ≥ 4。
    followup=24/hw=2：4−2=2 < 4 不可行（几何，simulate(10k,24,12) 实测路径组
    全 no_feasible、per-rule coverage 全 0）；36/12：6−2=4 ✓；60/24：10−4=6 ✓。"""
    admin_end = followup_months // cfg.SIM["window_months"]
    hw = horizon_months // cfg.SIM["window_months"]
    return admin_end - hw >= 4


def run_cell(n, followup_months, horizon_months, repeats, seeds):
    hw = horizon_months // cfg.SIM["window_months"]
    cal = _calibrated_for(horizon_months)
    # v5.22（Codex 二轮 P1-4）：几何不可行单元 → **显式 not_estimable 返回结构**
    # （records 为空、reason 标注），不产生 coverage=0 的假"规模退化"；
    # 调用方（run_study）据此排除该单元，不进聚合与可靠性边界统计
    if not _cell_feasible(followup_months, horizon_months):
        return {"records": [], "not_estimable": True,
                "reason": "no_feasible_path_anchor"}
    records = []
    for seed in seeds[:repeats]:
        out = simulate(n=n, followup_months=followup_months, horizon_months=horizon_months,
                       seed=seed, gate=cal["gate"], _lambda_c=cal["lambda_base"])
        lm = qualifying_landmarks(out["patients"], out["obs"], hw)
        sub = confirmation_subset(out["patients"], out["obs"], hw)
        # 角色口径（§5.5）：**模型用全量合格 landmark**（lm，不做 unobservable 过滤——
        # unobservable 只排除于规则/校准/evaluator/coverage 等确认子集流程）；
        # **evaluator 统计从实际 evaluator 输入（confirmation_subset）统计**，不用 lm 过滤
        sub_eval = sub[~sub["unobservable"]]
        model_res = fit_and_oof(lm, 3, 1, [seed])           # 全量合格 landmark（§5.5 角色表）
        mined = mine_rules(sub, 2, [seed, seed + 1])
        ev = evaluate(mined, out["planted_rules"], sub, out["coverage"])
        model_patients = int(lm["patient_id"].nunique())       # 模型全量（§5.5 角色表）
        model_landmarks = len(lm)
        evaluator_patients = int(sub_eval["patient_id"].nunique())   # 确认子集 evaluator 可评估口径
        evaluator_landmarks = len(sub_eval)
        # n_events：有效确认/参考 landmark 且非不可观测、事件在视界内（confirm < event <= confirm+hw）
        p = out["patients"]
        valid = p["confirm_window"].notna() & (~p["unobservable"])
        n_events = int((valid & p["event_window"].notna()
                        & (p["event_window"] > p["confirm_window"])
                        & (p["event_window"] <= p["confirm_window"] + hw)).sum())
        # oof_events：fit_and_oof 的 OOF 验证正例唯一患者（实际跑模型，非确认子集 label 计数）
        oof_frame = model_res["oof_frame"]
        oof_events = int(oof_frame.loc[oof_frame["label"] == 1, "patient_id"].nunique()) \
            if len(oof_frame) else 0
        # excluded 明细（**唯一患者口径，同一层级可核对**）：
        # n_unobservable + n_no_feasible + n_unknown_patients + evaluator_patients == n_total。
        # unknown_patients = confirmation_subset 剔除的 unknown 行数（每患者确认 landmark 一行
        # → 行级 == 患者级）；qualifying_landmarks 的行级 unknown（每患者可能多行）仍单独字段
        # unknown_landmark_rows 放顶层，不混入患者级 breakdown。
        # 患者级互斥分配（unobservable → unknown → no_feasible → evaluator，集合互斥保证闭环）
        excluded = _excluded_patient_sets(out["patients"], sub_eval["patient_id"], hw)
        n_total = int(out["patients"]["patient_id"].nunique())
        excluded_breakdown = {"unobservable": excluded["n_unobservable"],
                              "no_feasible_landmark": excluded["n_no_feasible"],
                              "unknown_patients": excluded["n_unknown_patients"]}
        unknown_landmark_rows = int(lm.attrs.get("excluded_unknown", 0))
        records.append({
            "nominal_n": n,
            # 模型口径（全量合格 landmark，§5.5 角色表）
            "model_patients": model_patients, "model_landmarks": model_landmarks,
            # evaluator 可评估口径（confirmation_subset 中非 unobservable，实际 evaluator 输入）
            "evaluator_patients": evaluator_patients, "evaluator_landmarks": evaluator_landmarks,
            "n_events": n_events, "oof_events": oof_events,
            # excluded_ratio = 未进入 evaluator 确认子集流程的患者比例（唯一患者口径，
            # 含 unobservable/no_feasible/unknown）；**模型已用全量合格 landmark**，不代表"未进模型"
            "excluded_ratio": 1 - evaluator_patients / max(n_total, 1),
            "excluded_breakdown": excluded_breakdown,
            "unknown_landmark_rows": unknown_landmark_rows,
            "overall_recovery": ev["rule_level_recovery"]["full_hit_count"] / 2,
            "partial_recovery": ev["partial_recovery"],
            "r1_recovered": ev["rule_level_recovery"]["r1_hit"],
            "r2_recovered": ev["rule_level_recovery"]["r2_hit"],
            "both_recovered": ev["rule_level_recovery"]["full_hit_count"] == 2,
        })
    return {"records": records, "not_estimable": False, "reason": None}


def aggregate_cell(results):
    rec = results["records"]
    overall = np.array([r["overall_recovery"] for r in rec])
    rng = np.random.default_rng(0)
    boots = [np.mean(rng.choice(overall, size=len(overall), replace=True)) for _ in range(200)]
    ci = (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5)))
    return {"overall_mean": float(np.mean(overall)), "overall_ci": ci,
            "ci_halfwidth": (ci[1] - ci[0]) / 2,
            "r1_freq": float(np.mean([r["r1_recovered"] for r in rec])),
            "r2_freq": float(np.mean([r["r2_recovered"] for r in rec])),
            "both_freq": float(np.mean([r["both_recovered"] for r in rec])),
            "excluded_ratio_mean": float(np.mean([r.get("excluded_ratio", 0) for r in rec])),
            "repeats": len(rec)}


def _meet_halfwidth(agg):
    return agg["ci_halfwidth"] <= cfg.GRID["ci_halfwidth_target"]


def _excluded_patient_sets(patients, supplied_eval_ids, hw):
    """患者级**互斥分配**（优先级：unobservable → unknown → no_feasible → evaluator）：
    - unknown 患者 = 确认 landmark **合格**（confirm 有限且 `w ≥ 2` 且 `admin_end − w ≥ hw`，
      与 §5.5 资格一致）且 `label_for` == "unknown" 且**非 unobservable**——与 confirmation_subset
      剔除一致；unobservable 患者即使其确认窗口判定为 unknown 也只计 unobservable；
    - **evaluator_ids = 调用者提供的 ID 先与患者全集求交（& all_ids），再剔除 unobs_ids/
      unknown_ids**（外部"幽灵"ID 不计入、也不减少 no_feasible；即使调用者传入含
      unobservable/unknown 患者的 ID，四集合仍互斥，不依赖调用者输入干净）；
    - no_feasible_ids = 剩余。
    闭环 n_unobservable + n_unknown + n_no_feasible + n_evaluator == 患者总数（**集合互斥保证**）。"""
    from features import label_for
    p = patients
    unobs_ids = set(p.loc[p["unobservable"], "patient_id"])
    unknown_ids = set()
    for _, r in p.iterrows():
        if r["unobservable"] or not np.isfinite(r["confirm_window"]):
            continue
        w = int(r["confirm_window"])
        if w < 2 or r["admin_end"] - w < hw:      # 确认 landmark 资格（§5.5）
            continue
        if label_for(r, w, hw) == "unknown":
            unknown_ids.add(r["patient_id"])
    all_ids = set(p["patient_id"])
    # evaluator_ids 先 ∩ 患者全集（外部 ID 即"幽灵患者"不得计入——否则 no_feasible 不相应减少，
    # 四集合闭环失真），再剔除 unobs/unknown
    evaluator_ids = (set(supplied_eval_ids) & all_ids) - unobs_ids - unknown_ids
    no_feasible_ids = all_ids - unobs_ids - unknown_ids - evaluator_ids
    return {"n_unobservable": len(unobs_ids), "n_unknown_patients": len(unknown_ids),
            "n_no_feasible": len(no_feasible_ids), "n_evaluator": len(evaluator_ids)}


def _bin_structure(records):
    bins = cfg.THRESHOLDS["event_bins"]
    grouped = {i: [] for i in range(len(bins) - 1)}
    for r in records:
        e = r["n_events"]
        idx = next(i for i in range(len(bins) - 1) if bins[i] <= e < bins[i + 1])
        grouped[idx].append(r["overall_recovery"])
    return [(float(bins[i]), float(bins[i + 1]), np.array(v))
            for i, v in grouped.items() if len(v) >= cfg.THRESHOLDS["bin_min_cohorts"]]


def _point_boundary(bins, lo_bound):
    """原始样本点边界（诊断单列）：isotonic 拟合箱均值 → 跨 50% 的箱端点插值。
    返回 float / "not_observed" / None(全程<50%)。"""
    from sklearn.isotonic import IsotonicRegression
    if len(bins) < 2:
        return None
    xs = np.array([b[0] for b in bins]); ys = np.array([b[2].mean() for b in bins])
    iso = IsotonicRegression(out_of_bounds="clip").fit(xs, ys)
    fitted = iso.predict(xs)
    if fitted.min() >= lo_bound:
        return "not_observed"
    if fitted.max() < lo_bound:
        return None
    for i in range(len(xs) - 1):
        if fitted[i] < lo_bound <= fitted[i + 1]:
            t = (lo_bound - fitted[i]) / (fitted[i + 1] - fitted[i])
            return float(xs[i] + t * (xs[i + 1] - xs[i]))
    return None


def _ext_percentile(vals, q):
    """含 +inf 的**扩展实数分位数**：升序排序后线性插值，+inf 视为最大元素。
    `np.percentile` 对含 inf 的数组不可靠（可能 NaN）——此处确定性处理：
    返回有限值或 +inf；空输入 → nan。"""
    a = np.sort(np.asarray(vals, dtype=float))
    if a.size == 0:
        return float("nan")
    idx = (len(a) - 1) * q / 100.0
    lo_i, hi_i = int(np.floor(idx)), int(np.ceil(idx))
    if lo_i == hi_i:
        return float(a[lo_i])
    w_hi = idx - lo_i
    return float(a[lo_i] * (1 - w_hi) + a[hi_i] * w_hi)


def _cross_boundary(fitted, grid, lo_bound):
    """在拟合曲线上求跨 50% 的箱端点插值点（平台段天然由插值处理）。
    返回 float / "not_observed"（全程 ≥50%）/ None（全程 <50%）。"""
    if fitted.min() >= lo_bound:
        return "not_observed"
    if fitted.max() < lo_bound:
        return None
    for i in range(len(grid) - 1):
        if fitted[i] < lo_bound <= fitted[i + 1]:
            t = (lo_bound - fitted[i]) / (fitted[i + 1] - fitted[i])
            return float(grid[i] + t * (grid[i + 1] - grid[i]))
    return None


def reliability_boundary(records_all_cells, followup_months):
    """规格 §8.2（**唯一算法**，与 Task 11 说明一致）：
    1) 队列级 Bootstrap：每样本重采样队列 → 重做分箱 → isotonic 拟合到**统一网格**（箱下界）
       → 记录每网格点拟合值（**不是**仅对"每次边界值"取分位）；
    2) 每网格点 2.5% 分位 = **CI 下界曲线**；
    3) **boundary_events = CI 下界曲线首达 50% 的事件数**（跨箱线性插值；规格 492）；
    4) boundary_ci = 每次 Bootstrap 样本在其拟合曲线上求边界点的分布 (2.5, 97.5)；
       "not_observed" 样本编码 +inf（上界可为 inf，允许语义）；无效样本丢弃；
    5) 边情形**只用 CI 下界曲线判定**：有效箱 <2 / 有效样本比例 < 门槛 → not_estimable；
       CI 下界曲线全程 ≥50% → not_observed；全程 <50% → not_estimable；
    6) point_boundary_events = 原始样本 isotonic 曲线跨 50%（**仅诊断单列，不参与边情形判定**，
       ≠ 边界主值——原始点达标不代表 CI 下界达标）。"""
    from sklearn.isotonic import IsotonicRegression
    lo_bound = cfg.THRESHOLDS["boundary_threshold"]
    bins = _bin_structure(records_all_cells)
    if len(bins) < 2:
        return {"status": "not_estimable", "boundary_events": None,
                "boundary_ci": None, "point_boundary_events": None}
    # point 仅作诊断（point_boundary_events），**不得提前用它判定边情形**——
    # 规格要求边情形由 Bootstrap 后的 CI 下界曲线判定：原始点估计全程 ≥50% 时
    # CI 下界仍可能跨 50%（低事件数箱波动大），提前短路会把 observed 误判为 not_observed。
    point = _point_boundary(bins, lo_bound)
    grid = np.array([b[0] for b in bins])
    B = cfg.THRESHOLDS["boundary_bootstrap_b"]
    valid_min = cfg.THRESHOLDS["boundary_valid_ratio_min"]
    rng = np.random.default_rng(0)
    grid_vals = [[] for _ in grid]
    boundary_samples, valid = [], 0
    for _ in range(B):
        sample = [records_all_cells[i] for i in
                  rng.integers(0, len(records_all_cells), size=len(records_all_cells))]
        sb = _bin_structure(sample)
        if len(sb) < 2:
            continue                       # 无效样本（<2 有效箱）→ 丢弃
        xs = np.array([b[0] for b in sb]); ys = np.array([b[2].mean() for b in sb])
        iso = IsotonicRegression(out_of_bounds="clip").fit(xs, ys)
        fitted = iso.predict(grid)
        for gi, v in enumerate(fitted):
            grid_vals[gi].append(v)
        valid += 1
        cb = _cross_boundary(fitted, grid, lo_bound)
        if cb == "not_observed":
            boundary_samples.append(float("inf"))
        elif isinstance(cb, float):
            boundary_samples.append(cb)
    valid_ratio = valid / B
    if valid_ratio < valid_min:                 # 有效样本比例门槛（版本化）
        return {"status": "not_estimable", "boundary_events": None,
                "boundary_ci": None, "point_boundary_events": point}
    lo_curve = np.array([np.percentile(vs, 2.5) if len(vs) else np.nan for vs in grid_vals])
    finite = np.isfinite(lo_curve)
    if not finite.any():
        return {"status": "not_estimable", "boundary_events": None,
                "boundary_ci": None, "point_boundary_events": point}
    # 边情形判定基于 CI 下界曲线（规格 496-497）
    if lo_curve[finite].min() >= lo_bound:
        return {"status": "not_observed", "boundary_events": None,
                "boundary_ci": None, "point_boundary_events": point}
    if lo_curve[finite].max() < lo_bound:
        return {"status": "not_estimable", "boundary_events": None,
                "boundary_ci": None, "point_boundary_events": point}
    boundary = _cross_boundary(lo_curve[finite], grid[finite], lo_bound)
    if not isinstance(boundary, float):
        return {"status": "not_estimable", "boundary_events": None,
                "boundary_ci": None, "point_boundary_events": point}
    # 防御性保护（observed 分支下 boundary_samples 必然非空含有限值，实际不可达）
    if not boundary_samples:
        return {"status": "not_estimable", "boundary_events": None,
                "boundary_ci": None, "point_boundary_events": point}
    return {"status": "observed", "boundary_events": boundary, "point_boundary_events": point,
            "boundary_ci": (_ext_percentile(boundary_samples, 2.5),
                            _ext_percentile(boundary_samples, 97.5))}


def run_study(grid=None, repeats=None):
    grid = grid if grid is not None else cfg.GRID["scale_down"]
    repeats = repeats if repeats is not None else cfg.GRID["repeats"]
    out = {"cells": {}, "reliability_boundaries": {}}
    for f in grid["followup_months"]:
        cell_records = []
        for n in grid["n"]:
            res = run_cell(n=n, followup_months=f, horizon_months=grid["horizon_months"],
                           repeats=repeats, seeds=list(range(repeats)))
            if res.get("not_estimable"):          # v5.22：几何不可行单元 → 单列标记、
                out["cells"][f"n{n}_f{f}"] = {"not_estimable": True, "reason": res["reason"]}
                continue                          # **不进聚合与可靠性边界统计**（Codex 二轮 P1-4）
            agg = aggregate_cell(res)
            r = repeats
            while not _meet_halfwidth(agg) and r < cfg.GRID["repeats_max"]:
                r *= 2
                res = run_cell(n=n, followup_months=f, horizon_months=grid["horizon_months"],
                               repeats=r, seeds=list(range(r)))
                agg = aggregate_cell(res)
            agg["precision_not_met"] = not _meet_halfwidth(agg)   # 达 repeats_max 仍未满足半宽 → 标记
            out["cells"][f"n{n}_f{f}"] = agg
            cell_records.extend(res["records"])
        if cell_records:
            out["reliability_boundaries"][f"f{f}"] = reliability_boundary(cell_records, followup_months=f)
        else:                                     # 该随访档全部单元不可行 → 边界不可估计（单列）
            out["reliability_boundaries"][f"f{f}"] = {"status": "not_estimable",
                                                      "reason": "no_feasible_cells"}
    return out
