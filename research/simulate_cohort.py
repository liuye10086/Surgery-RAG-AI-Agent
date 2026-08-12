"""模拟纵向数据生成器（Z 路径 + 前向生成）。planted_rules 只流向 evaluator。"""
from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass
import config as cfg


@dataclass(frozen=True)
class Condition:
    indicator: str; op: str; value: float; lookback: int = 1

@dataclass(frozen=True)
class PlantedRule:
    name: str; horizon_months: int; conditions: tuple[Condition, ...]
    group: str; target_risk: float; lag: int = 0
    @property
    def horizon_windows(self): return self.horizon_months // cfg.SIM["window_months"]
    @property
    def lookback(self): return max((c.lookback for c in self.conditions), default=1)

@dataclass(frozen=True)
class PlantedRules:
    horizon_months: int; r1: PlantedRule; r2: PlantedRule; calibration: dict[str, float]


def _to_condition(ind, op, val):
    if ind == "sex":
        val = 1.0 if val == "male" else 0.0
    if op == "drop_pct":
        val = float(val) / 100.0          # 标准语义统一为比例（特征 drop_pct 是 -0.20 量级）
    lookback = int(val) if op == "consecutive_rises" else 1   # 连续上升的 lookback = 上升次数
    return Condition(ind, op, float(val), lookback=lookback)


def _build_planted_rules(horizon_months):
    cal = cfg.CALIBRATION[horizon_months]
    r1 = PlantedRule("r1", horizon_months,
                     tuple(_to_condition(i, o, v) for i, o, v in cfg.PLANTED_CONDITIONS["r1"]),
                     "r1_only", cal["r1_only"])
    r2 = PlantedRule("r2", horizon_months,
                     tuple(_to_condition(i, o, v) for i, o, v in cfg.PLANTED_CONDITIONS["r2"]),
                     "r2_only", cal["r2_only"])
    return PlantedRules(horizon_months, r1, r2, cal)


def _sample_z_covariates(rng, n):
    paths = rng.choice(["none", "r1", "r2", "r1_and_r2"], n, p=[0.70, 0.15, 0.10, 0.05])
    ages, sexes = np.empty(n, int), np.empty(n, object)
    for i, z in enumerate(paths):
        if z in ("r1", "r1_and_r2"):
            sexes[i], ages[i] = "male", int(rng.integers(51, 80))
        else:
            sexes[i], ages[i] = rng.choice(["male", "female"]), int(rng.integers(20, 70))
    return paths, ages, sexes


def _sample_anchors(rng, z, w0, admin_end, hw):
    """确认锚点需 >=3 窗信号累积（PLT 乘性 ×0.80、HbA1c 上升；噪声 sd ~12pp，
    最小锚点处降幅须达 >=44% 才留 >=2σ 余量）→ w_R1 >= w0+3、w_A >= w0+2
    （confirm = w_A+1 >= w0+3：PLT 累积 3 窗 → 降 48.8% → 成立率 99.3% ✓；
     AFP 信号自 w_A 起立即生效，无需额外累积。v5.19 曾用 w_A >= w0+3，
     12 月视界（admin_end=6）下 w0=1 患者 hi<lo 全部 no_feasible → 可观测样本
     减半 → 校准 mean(g) 抽样噪声 3.4% > bisection tol 0.5% → ±3pp 断言不可达；
     w0+2 使 w0=1 患者恢复（w_A=3），样本翻倍、噪声 <1.5%）。"""
    w_a, w_r1 = np.nan, np.nan
    for _ in range(cfg.SIM["resample_max"]):
        if z in ("r2", "r1_and_r2"):
            lo, hi = max(1, w0 + 2), admin_end - hw - 1
            if hi < lo: return np.nan, np.nan
            w_a = int(rng.integers(lo, hi + 1))
        if z == "r1":
            lo, hi = max(3, w0 + 3), admin_end - hw
            if hi < lo: return np.nan, np.nan
            w_r1 = int(rng.integers(lo, hi + 1))
        elif z == "r1_and_r2":
            lo, hi = w0 + 2, w_a - 1
            if hi < lo:
                w_r1 = np.nan        # w_r1 仅记录字段；R1 条件在 confirm=w_A+1 检查，不牵连 w_A
            else:
                w_r1 = int(rng.integers(lo, hi + 1))
        return w_a, w_r1


def _first_qualifying_landmark(admin_end, hw, censored_window):
    for w in range(2, admin_end - hw + 1):
        if np.isfinite(censored_window) and w >= censored_window:
            continue
        return w
    return np.nan


def _neither_hazard(lambda_c, age, sex):
    """可缩放基线 hazard = λ_c * λ0(age, sex)；λ_c=0 时风险为 0（bisection 可向下收敛）。"""
    lambda0 = 0.02 * (1 + 0.01 * (age - 40)) * (1.2 if sex == "male" else 1.0)
    return lambda_c * lambda0


def simulate(n, followup_months, horizon_months, seed, gate=None, _lambda_c=None):
    rng = np.random.default_rng(seed)
    # CRN（v5.21 二轮）：患者级派生 rng——每患者从主 rng 派生独立子 rng `rng_i`
    # （锚点/删失/δ/观测/neither hazard 全部患者内），患者间完全独立 → 患者构成
    # （z 之外的一切）与 gate 无关；g 用 rng_gate 独立流，**每患者固定消耗 1 个
    # uniform（含 z=none）** → u_i 固定 → g_i(mid)=1{u_i<mid} 严格单调 → 校准
    # r(mid)=mean(g) 严格单调（v5.21 一轮仅拆分 rng_gate/rng_delta 不彻底：事件窗口
    # 改变 n_t → 下一患者主 rng 流偏移 → w_a/w_r1/删失漂移，n=30 实测非单调反例）。
    rng_gate = np.random.default_rng(seed + 1)
    rng_delta = np.random.default_rng(seed + 2)
    admin_end = followup_months // cfg.SIM["window_months"]
    hw = horizon_months // cfg.SIM["window_months"]
    cal = cfg.CALIBRATION[horizon_months]
    if gate is None:
        gate = dict(cal)
    lambda_c = 0.0 if _lambda_c is None else _lambda_c

    paths, ages, sexes = _sample_z_covariates(rng, n)
    # 向量化索引：σ_meas = 0.1·范围（测量噪声）、基线 SD = 范围/6（患者间异质性，
    # 与逐指标定义一致；v5.20 曾误用 0.1·范围 → PLT 基线 SD 37.5→22.5，已修复）
    inds = cfg.INDICATORS
    n_ind = len(inds)
    lo_hi = np.array([cfg.REFERENCE_RANGES[i][:2] for i in inds], dtype=float)
    mid = (lo_hi[:, 0] + lo_hi[:, 1]) / 2
    sigma = 0.1 * (lo_hi[:, 1] - lo_hi[:, 0])
    baseline_sd = (lo_hi[:, 1] - lo_hi[:, 0]) / 6
    i_hba1c, i_plt, i_afp = inds.index("HbA1c"), inds.index("PLT"), inds.index("AFP")
    n_win = admin_end + 1

    rows, obs_rows, obs_wins, obs_pids = [], [], [], []
    for pid in range(n):
        patient_rows = []
        rng_i = np.random.default_rng(int(rng.integers(0, 2 ** 31)))   # 患者级派生（主 rng 固定消耗 1 个整数）
        z, age, sex = paths[pid], ages[pid], sexes[pid]
        w0 = int(rng_i.integers(0, 2))
        w_a, w_r1 = _sample_anchors(rng_i, z, w0, admin_end, hw)

        # 删失（独立，先于 neither 参考 landmark；患者内 rng）
        censored = rng_i.random() < cfg.SIM["censoring_rate"]
        censored_window = float(rng_i.integers(1, n_win)) if censored else np.nan

        # 事件：g 用 rng_gate 独立流（**每患者固定消耗 1 个 uniform，含 z=none** →
        # u_i 固定、患者构成不随 gate 漂移 → CRN 严格单调）；δ 用 rng_delta 独立流
        # （不消耗 rng_i → 患者内观测流固定）；neither hazard 用患者内 rng
        u_g = rng_gate.random()
        g, event_window = np.nan, np.nan
        if z != "none":
            confirm = (w_a + 1) if z in ("r2", "r1_and_r2") else w_r1
            if np.isfinite(confirm):
                grp = "r1_and_r2" if z == "r1_and_r2" else ("r1_only" if z == "r1" else "r2_only")
                g = int(u_g < gate[grp])
                if g == 1:
                    event_window = confirm + int(rng_delta.choice(cfg.SIM["delta_choices"]))
        else:
            ref = _first_qualifying_landmark(admin_end, hw, censored_window)
            if np.isfinite(ref):
                # 从 ref+1 起视界内触发（ref 本身无事件；上界 = admin_end）
                for t in range(int(ref) + 1, min(int(ref) + hw, admin_end) + 1):
                    if rng_i.random() < _neither_hazard(lambda_c, age, sex):
                        event_window = t
                        break

        # 指标观测（基线 + 信号 + 噪声）；观测截断（规格 5.4 第 9 步）：
        # T = min(事件, 删失, 行政随访终点)，**其后窗口观测截断**——T 窗口本身有观测，
        # T+1 起无观测（杜绝事件/删失后的"未来观测"，避免 lead-lag 对已删失对照使用未来值）。
        # **观测按患者矩阵收集**（截断后每患者行数 ≠ n_win，不能用全局 obs 尾部切片，
        # 否则会混入上一患者窗口——条件判定 by_w 必须只用当前患者行）。
        # **向量化（v5.20）**：每患者一次批量噪声 rng.normal(0,1,size=(n_t,n_ind))*σ，
        # 信号叠加用 numpy 掩码——与逐指标逐窗调用分布完全相同（iid 同分布），
        # 但避免 330 万次 rng 调用与 dict 构造（simulate(30k)：13.65s → ~2s，Task 11/14 受益）。
        baseline = mid + rng_i.normal(0, 1, size=n_ind) * baseline_sd
        # 噪声**全窗口一次性生成**（rng_i 固定消耗 n_win×n_ind）后按截断截取——
        # n_t 依赖 event_window（随 gate 变），若按 n_t 生成则 rng_i 消耗偏移 →
        # 观测随 gate 变 → condition_not_held 边界漂移 → CRN 单调性被破坏（v5.21 二轮）
        noise_all = rng_i.normal(0, 1, size=(n_win, n_ind)) * sigma
        trunc = admin_end
        if np.isfinite(event_window):
            trunc = min(trunc, int(event_window))
        if np.isfinite(censored_window):
            trunc = min(trunc, int(censored_window))
        n_t = trunc + 1
        obs_mat = np.empty((n_t, n_ind))
        noise = noise_all[:n_t]
        obs_mat[:] = baseline + noise
        t_arr = np.arange(n_t)
        if z in ("r1", "r1_and_r2"):
            sel = t_arr >= w0
            obs_mat[sel, i_hba1c] = baseline[i_hba1c] \
                + cfg.SIM["hba1c_rise_per_window"] * (t_arr[sel] - w0) + noise[sel, i_hba1c]
            obs_mat[sel, i_plt] = baseline[i_plt] \
                * (cfg.SIM["plt_decline_per_window"] ** np.maximum(t_arr[sel] - w0, 0)) + noise[sel, i_plt]
        if z in ("r2", "r1_and_r2") and np.isfinite(w_a):
            sel = t_arr >= w_a
            obs_mat[sel, i_afp] = baseline[i_afp] \
                + cfg.SIM["afp_rise_per_window"] * (t_arr[sel] - w_a + 1) + noise[sel, i_afp]
        obs_rows.append(obs_mat)
        obs_wins.append(t_arr)
        obs_pids.append(np.full(n_t, pid))

        # 组归属 / 确认 landmark / unobservable（完整判定 + 原因分解；路径组逻辑收敛到纯函数）
        if z == "none":
            confirm = _first_qualifying_landmark(admin_end, hw, censored_window)
            group, unobservable, unobservable_reason = "neither", False, None
        else:
            by_w = {t: {ind: obs_mat[t, j] for j, ind in enumerate(inds)} for t in range(n_t)}
            cls = _classify_observable(z, age, sex, w_a, w_r1, event_window, censored_window,
                                       by_w, hw)
            confirm, group = cls["confirm_window"], cls["group"]
            unobservable, unobservable_reason = cls["unobservable"], cls["unobservable_reason"]

        rows.append({"patient_id": pid, "z": z, "age": age, "sex": sex, "group": group,
                     "confirm_window": confirm, "w_r1": w_r1, "w_a": w_a, "g": g,
                     "event_window": event_window, "censored": censored,
                     "censored_window": censored_window, "admin_end": admin_end,
                     "unobservable": unobservable,
                     "unobservable_reason": unobservable_reason})

    patients = pd.DataFrame(rows)
    obs_mat_all = np.vstack(obs_rows)
    obs_df = pd.DataFrame({
        "patient_id": np.concatenate(obs_pids), "window": np.concatenate(obs_wins),
        **{ind: obs_mat_all[:, j] for j, ind in enumerate(inds)}})
    meta = {"horizon_windows": hw, "admin_end": admin_end}
    return {"patients": patients, "obs": obs_df,
            "planted_rules": _build_planted_rules(horizon_months),
            "coverage": _compute_coverage(patients, obs_df, meta),
            "meta": meta}


def _classify_observable(z, age, sex, w_a, w_r1, event_window, censored_window, by_w, hw):
    """确认 landmark / 组归属 / unobservable / 原因——**纯函数**（路径组；z=="none" 由调用方处理）。
    `by_w` = 当前患者观测字典（{window: row}），**只由当前患者行构造**——跨患者污染（旧
    `obs_rows[-n_win:]` 在截断后混入上一患者窗口）会在此被回归检测。
    原因归因确定性顺序：no_feasible_anchor → censored → event_before_confirm → condition_not_held。"""
    expected = "r1_and_r2" if z == "r1_and_r2" else ("r1_only" if z == "r1" else "r2_only")
    confirm = (w_a + 1) if z in ("r2", "r1_and_r2") else w_r1
    r1_ok = _r1_holds(by_w, confirm, age, sex) if z in ("r1", "r1_and_r2") else False
    r2_ok = _r2_holds(by_w, confirm) if z in ("r2", "r1_and_r2") else False
    valid = (np.isfinite(confirm)
             and (not np.isfinite(event_window) or confirm < event_window)
             and (not np.isfinite(censored_window) or confirm < censored_window))
    if not valid or (z in ("r1", "r1_and_r2") and not r1_ok) or (z in ("r2", "r1_and_r2") and not r2_ok):
        if not np.isfinite(confirm):
            reason = "no_feasible_anchor"
        elif np.isfinite(censored_window) and confirm >= censored_window:
            reason = "censored"
        elif np.isfinite(event_window) and confirm >= event_window:
            reason = "event_before_confirm"
        else:
            reason = "condition_not_held"
        return {"confirm_window": confirm, "group": expected, "unobservable": True,
                "unobservable_reason": reason}
    group = "r1_and_r2" if (r1_ok and r2_ok) else ("r1_only" if r1_ok else "r2_only")
    return {"confirm_window": confirm, "group": group, "unobservable": False,
            "unobservable_reason": None}


def _r1_holds(by_w, w, age, sex):
    if sex != "male" or age <= 50: return False
    if not _consecutive_rises(by_w, "HbA1c", w, 2): return False
    base = np.mean([by_w[t]["PLT"] for t in (0, 1) if t in by_w])
    if not np.isfinite(base) or base == 0: return False
    cur = by_w.get(w, {}).get("PLT", np.nan)     # 容错缺失窗口（截断/观测不足）
    return np.isfinite(cur) and (cur - base) / base <= -0.20


def _r2_holds(by_w, w):
    return _consecutive_rises(by_w, "AFP", w, 2)


def _consecutive_rises(by_w, ind, w, k):
    if w < k: return False
    vals = [by_w.get(w - i, {}).get(ind, np.nan) for i in range(k + 1)]
    if any(not np.isfinite(v) for v in vals): return False
    return all(vals[i] > vals[i + 1] for i in range(k))


def _patient_order(pids):
    """稳定排序索引：`order` 使 pids[order] 有序（任意输入行序 → 患者块连续）。
    一次 O(N log N)，调用方每观测集构建一次；_by_w_slice 不再假设全局排序
    （v5.21 二轮：Codex 复现全局 shuffle 后 neither 误报率 0.152→0.001）。"""
    return np.argsort(pids, kind="stable")


def _by_w_slice(sorted_pids, order, wins, vals, cols, pid, w):
    """判定所需窄窗口 by_w（{w-2, w-1, w, 0, 1} ∩ 患者观测，PLT 基线取窗口 0,1）。
    按稳定排序索引定位患者块（`order` 由 _patient_order 构建），块内**按实际 window
    列匹配**：全局乱序/块内乱序/缺窗/非零起始窗口均正确，与输入行序无关。
    与全量 by_w 语义等价：_r1_holds/_r2_holds 只读这些窗口，缺失键即无观测。"""
    s = np.searchsorted(sorted_pids, pid, side="left")
    e = np.searchsorted(sorted_pids, pid, side="right")
    by_w = {}
    for i in range(s, e):
        r = order[i]
        k = int(wins[r])
        if k in (w, w - 1, w - 2, 0, 1):
            by_w[k] = {cols[j]: vals[r, j] for j in range(len(cols))}
    return by_w


def _group_latent_risk(out, grp, hw, obs=None):
    """潜在风险（不受删失影响）。neither：排除"参考 landmark 命中 R1/R2"的误报患者。
    **校准分母** = 有合格参考 landmark 且非误报的 neither 患者（规格 §5.3 明确定义；
    与 coverage 的**误报率分母 = 全部 neither 候选患者**是两个不同口径，勿混淆）。"""
    p = out["patients"]
    sub = p[(p["group"] == grp) & (~p["unobservable"])]
    if grp == "neither":
        if obs is None:
            raise ValueError("neither 校准需传入 obs 以检查参考 landmark 误报")
        cols = [c for c in cfg.INDICATORS if c in obs.columns]
        pids = obs["patient_id"].to_numpy()
        wins = obs["window"].to_numpy()
        vals = obs[cols].to_numpy()
        order = _patient_order(pids)
        sorted_pids = pids[order]
        ok_mask = sub["confirm_window"].notna().to_numpy()
        fp_mask = np.zeros(len(sub), dtype=bool)
        for i, row in enumerate(sub.itertuples()):
            if not np.isfinite(row.confirm_window):
                continue
            by_w = _by_w_slice(sorted_pids, order, wins, vals, cols, row.patient_id, int(row.confirm_window))
            w = int(row.confirm_window)
            if _r1_holds(by_w, w, row.age, row.sex) or _r2_holds(by_w, w):
                fp_mask[i] = True
        valid = ok_mask & (~fp_mask)                       # 误报患者排除出 neither 校准分母
        ev = sub["event_window"].notna().to_numpy() \
             & (sub["event_window"] > sub["confirm_window"]).to_numpy() \
             & (sub["event_window"] <= sub["confirm_window"] + hw).to_numpy()
        return ev[valid].mean() if valid.any() else np.nan
    return sub["g"].mean()


def _bisect(target, risk_fn, lo=0.0, hi=1.0):
    """bisection（端点包围强制检查 + 上界自适应扩展）。

    - 检查 risk(lo) <= target <= risk(hi)；**不包围 → 上界倍增扩展**（λ_c 允许 >1，
      neither 基线 hazard 可缩放语义），扩展超 `calibrate_hi_max` 仍不达 → 显式
      `ValueError`（**绝不静默返回伪校准端点值**）。
    - risk(lo) > target → 直接 `ValueError`（下界即超目标，参数错误）。"""
    risk_lo = risk_fn(lo)
    if risk_lo > target:
        raise ValueError(f"bisection 下界风险 {risk_lo:.4f} > 目标 {target:.4f}")
    risk_hi = risk_fn(hi)
    while risk_hi < target and hi < cfg.THRESHOLDS["calibrate_hi_max"]:
        hi *= 2.0
        risk_hi = risk_fn(hi)
    if risk_hi < target:
        raise ValueError(f"bisection 上界风险 {risk_hi:.4f} < 目标 {target:.4f}（扩展至 hi={hi:.1f} 仍不包围）")
    for _ in range(cfg.THRESHOLDS["calibrate_bisect_iters"]):
        mid = (lo + hi) / 2
        r = risk_fn(mid)
        if abs(r - target) <= cfg.THRESHOLDS["calibrate_tol"]:
            return mid
        if r < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def calibrate_gates(horizon_months, cal_n=cfg.SIM["calibration_n"]):
    followup = 60 if horizon_months == 24 else 36
    hw = horizon_months // cfg.SIM["window_months"]
    cal = cfg.CALIBRATION[horizon_months]
    gates = {}
    for grp, target in cal.items():
        if grp == "neither":
            continue
        def risk(mid, grp=grp, target=target):
            g = {g_: (mid if g_ == grp else t) for g_, t in cal.items() if g_ != "neither"}
            out = simulate(cal_n, followup, horizon_months, 3, gate=g, _lambda_c=0.0)
            return _group_latent_risk(out, grp, hw, obs=out["obs"])
        # 端点包围：g=0 → 风险 0 < 目标；g=1 → 风险 1 ≥ 目标（事件=confirm+δ ≤ confirm+hw）→ 必有解
        gates[grp] = _bisect(target, risk)

    def neither_risk(c):
        out = simulate(cal_n, followup, horizon_months, 3, gate=gates, _lambda_c=c)
        return _group_latent_risk(out, "neither", hw, obs=out["obs"])
    # λ_c=0 → 风险 0 < 目标；λ_c 可能需 >1（视界内 λ0 累积不足目标时自动扩展上界）
    lambda_base = _bisect(cal["neither"], neither_risk, lo=0.0, hi=1.0)
    return {"gate": gates, "lambda_base": lambda_base,
            "neither_risk": {horizon_months: float(neither_risk(lambda_base))}}


def p_obs(patients, obs, horizon_windows):
    result = {}
    for grp in ("neither", "r1_only", "r2_only", "r1_and_r2"):
        pos = neg = 0
        for _, p in patients[(patients["group"] == grp) & (~patients["unobservable"])].iterrows():
            if not np.isfinite(p["confirm_window"]):
                continue                                # 无可行确认/参考 landmark → not_estimable（规格 §5.5），不进 P_obs 分母
            ev, cw = p["event_window"], p["censored_window"]
            win = p["confirm_window"] + horizon_windows
            if np.isfinite(ev) and ev <= win and (not np.isfinite(cw) or cw > ev):
                pos += 1
            elif (not np.isfinite(ev) or ev > win) and (not np.isfinite(cw) or cw > win):
                neg += 1
        result[grp] = {"positive": pos, "negative": neg, "denominator": pos + neg,
                       "rate": pos / (pos + neg) if pos + neg else float("nan")}
    return result


def _compute_coverage(patients, obs, meta):
    """coverage 口径（唯一）：每互斥组/规则输出
    {"eligible_total", "eligible_observed", "excluded", "coverage"}。
    eligible_total = 该组全部患者；eligible_observed = 确认/参考 landmark 合格、无事件、条件成立的患者；
    excluded = eligible_total - eligible_observed；coverage = eligible_observed / eligible_total。
    per_rule 按规则路径组聚合，**按唯一患者去重**（避免 landmark 行数混入患者口径）。
    neither 误报分母 = **全部 neither 候选患者**（规格 §5.3：误报率分母 = 全部 neither 候选患者）；
    无合格参考 landmark 的患者无法判定误报、不计入分子，但仍在分母中。"""
    p = patients
    per_group = {}
    for grp in ("r1_only", "r2_only", "r1_and_r2", "neither"):
        sub = p[p["group"] == grp]
        total = int(len(sub))
        observed = int((sub["confirm_window"].notna() & (~sub["unobservable"])).sum())
        per_group[grp] = {"eligible_total": total, "eligible_observed": observed,
                          "excluded": total - observed,
                          "coverage": observed / total if total else float("nan")}
    per_rule = {}
    for rule, groups in (("r1", ("r1_only", "r1_and_r2")), ("r2", ("r2_only", "r1_and_r2"))):
        sub = p[p["group"].isin(groups)]
        total = int(sub["patient_id"].nunique())                          # 唯一患者
        observed_ids = sub[(sub["confirm_window"].notna()) & (~sub["unobservable"])]["patient_id"].nunique()
        per_rule[rule] = {"eligible_total": total, "eligible_observed": observed_ids,
                          "excluded": total - observed_ids,
                          "coverage": observed_ids / total if total else float("nan")}
    ne = p[p["group"] == "neither"]                    # 分母 = 全部 neither 候选患者（规格 §5.3）
    cols = [c for c in cfg.INDICATORS if c in obs.columns]
    pids = obs["patient_id"].to_numpy()
    wins = obs["window"].to_numpy()
    vals = obs[cols].to_numpy()
    order = _patient_order(pids)
    sorted_pids = pids[order]
    fp = 0
    for _, row in ne.iterrows():
        if not np.isfinite(row["confirm_window"]):
            continue                                    # 无合格参考 landmark → 无法判定，不计入分子
        by_w = _by_w_slice(sorted_pids, order, wins, vals, cols, row["patient_id"], int(row["confirm_window"]))
        w = int(row["confirm_window"])
        if _r1_holds(by_w, w, row["age"], row["sex"]) or _r2_holds(by_w, w):
            fp += 1
    neither_fp = fp / len(ne) if len(ne) else float("nan")
    return {"per_group": per_group, "per_rule": per_rule,
            "neither_false_positive_rate": float(neither_fp)}
