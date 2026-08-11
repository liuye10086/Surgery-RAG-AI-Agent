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
    最小锚点处降幅须达 >=44% 才留 >=2σ 余量）→ w_R1 >= w0+3、w_A >= w0+3
    （confirm = w_A+1 >= w0+4）。w_A 下界同步提高使 r1_and_r2 的 PLT 条件
    在共同确认 landmark 处同样有足够信号余量。"""
    w_a, w_r1 = np.nan, np.nan
    for _ in range(cfg.SIM["resample_max"]):
        if z in ("r2", "r1_and_r2"):
            lo, hi = max(1, w0 + 3), admin_end - hw - 1
            if hi < lo: return np.nan, np.nan
            w_a = int(rng.integers(lo, hi + 1))
        if z == "r1":
            lo, hi = max(3, w0 + 3), admin_end - hw
            if hi < lo: return np.nan, np.nan
            w_r1 = int(rng.integers(lo, hi + 1))
        elif z == "r1_and_r2":
            lo, hi = w0 + 2, w_a - 1
            if hi < lo: return np.nan, np.nan
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
    admin_end = followup_months // cfg.SIM["window_months"]
    hw = horizon_months // cfg.SIM["window_months"]
    cal = cfg.CALIBRATION[horizon_months]
    if gate is None:
        gate = dict(cal)
    lambda_c = 0.0 if _lambda_c is None else _lambda_c

    paths, ages, sexes = _sample_z_covariates(rng, n)
    sigma = {i: 0.1 * (cfg.REFERENCE_RANGES[i][1] - cfg.REFERENCE_RANGES[i][0]) for i in cfg.INDICATORS}
    n_win = admin_end + 1

    rows, obs_rows = [], []
    for pid in range(n):
        patient_rows = []
        z, age, sex = paths[pid], ages[pid], sexes[pid]
        w0 = int(rng.integers(0, 2))
        w_a, w_r1 = _sample_anchors(rng, z, w0, admin_end, hw)

        # 删失（独立，先于 neither 参考 landmark）
        censored = rng.random() < cfg.SIM["censoring_rate"]
        censored_window = float(rng.integers(1, n_win)) if censored else np.nan

        # 事件
        g, event_window = np.nan, np.nan
        if z != "none":
            confirm = (w_a + 1) if z in ("r2", "r1_and_r2") else w_r1
            if np.isfinite(confirm):
                grp = "r1_and_r2" if z == "r1_and_r2" else ("r1_only" if z == "r1" else "r2_only")
                g = int(rng.random() < gate[grp])
                if g == 1:
                    event_window = confirm + int(rng.choice(cfg.SIM["delta_choices"]))
        else:
            ref = _first_qualifying_landmark(admin_end, hw, censored_window)
            if np.isfinite(ref):
                # 从 ref+1 起视界内触发（ref 本身无事件；上界 = admin_end）
                for t in range(int(ref) + 1, min(int(ref) + hw, admin_end) + 1):
                    if rng.random() < _neither_hazard(lambda_c, age, sex):
                        event_window = t
                        break

        # 指标观测（基线 + 信号 + 噪声）；观测截断（规格 5.4 第 9 步）：
        # T = min(事件, 删失, 行政随访终点)，**其后窗口观测截断**——T 窗口本身有观测，
        # T+1 起无观测（杜绝事件/删失后的"未来观测"，避免 lead-lag 对已删失对照使用未来值）。
        # **观测按 patient_rows 收集**（截断后每患者行数 ≠ n_win，不能用全局 obs_rows 尾部切片，
        # 否则会混入上一患者窗口——条件判定 by_w 必须只用当前患者行）
        baseline = {i: rng.normal((cfg.REFERENCE_RANGES[i][0] + cfg.REFERENCE_RANGES[i][1]) / 2,
                                  (cfg.REFERENCE_RANGES[i][1] - cfg.REFERENCE_RANGES[i][0]) / 6)
                    for i in cfg.INDICATORS}
        trunc = admin_end
        if np.isfinite(event_window):
            trunc = min(trunc, int(event_window))
        if np.isfinite(censored_window):
            trunc = min(trunc, int(censored_window))
        for t in range(trunc + 1):
            row = {"patient_id": pid, "window": t}
            for ind in cfg.INDICATORS:
                sig = 0.0
                if z in ("r1", "r1_and_r2") and ind == "HbA1c" and t >= w0:
                    sig = cfg.SIM["hba1c_rise_per_window"] * (t - w0)
                if z in ("r1", "r1_and_r2") and ind == "PLT" and t >= w0:
                    row[ind] = baseline[ind] * (cfg.SIM["plt_decline_per_window"] ** max(t - w0, 0)) \
                        + rng.normal(0, sigma[ind])
                    continue
                if z in ("r2", "r1_and_r2") and ind == "AFP" and np.isfinite(w_a) and t >= w_a:
                    sig = cfg.SIM["afp_rise_per_window"] * (t - w_a + 1)
                row[ind] = baseline[ind] + sig + rng.normal(0, sigma[ind])
            patient_rows.append(row)
        obs_rows.extend(patient_rows)

        # 组归属 / 确认 landmark / unobservable（完整判定 + 原因分解；路径组逻辑收敛到纯函数）
        if z == "none":
            confirm = _first_qualifying_landmark(admin_end, hw, censored_window)
            group, unobservable, unobservable_reason = "neither", False, None
        else:
            cls = _classify_observable(z, age, sex, w_a, w_r1, event_window, censored_window,
                                       {r["window"]: r for r in patient_rows}, hw)
            confirm, group = cls["confirm_window"], cls["group"]
            unobservable, unobservable_reason = cls["unobservable"], cls["unobservable_reason"]

        rows.append({"patient_id": pid, "z": z, "age": age, "sex": sex, "group": group,
                     "confirm_window": confirm, "w_r1": w_r1, "w_a": w_a, "g": g,
                     "event_window": event_window, "censored": censored,
                     "censored_window": censored_window, "admin_end": admin_end,
                     "unobservable": unobservable,
                     "unobservable_reason": unobservable_reason})

    return {"patients": pd.DataFrame(rows), "obs": pd.DataFrame(obs_rows),
            "planted_rules": _build_planted_rules(horizon_months),
            "coverage": {"per_group": {}, "per_rule": {}, "neither_false_positive_rate": np.nan},
            "meta": {"horizon_windows": hw, "admin_end": admin_end}}


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
