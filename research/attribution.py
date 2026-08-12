"""lead-lag 时间对齐（主证据；描述性）。无 planted_rules。观察进展者口径。"""
from __future__ import annotations
import numpy as np
import pandas as pd
import config as cfg
from splitters import patient_bootstrap_ci
from model import fit_and_oof


def _observed_progressors(patients):
    """g==1 且事件在删失前被观察到的患者（观察进展者）。"""
    p = patients[(patients["g"] == 1) & (~patients["unobservable"])]
    return p[(p["event_window"].notna()) &
             (p["censored_window"].isna() | (p["censored_window"] > p["event_window"]))]


def _deviation(series, runin_mean, sigma):
    flags = {w: abs(v - runin_mean) > cfg.SIM["kappa"] * sigma + cfg.SIM["tau"] for w, v in series.items()}
    return {w: flags.get(w, False) and flags.get(w - 1, False) for w in sorted(series)}


def _first_deviation(series, runin_mean, sigma):
    dev = _deviation(series, runin_mean, sigma)
    flagged = [w for w, d in dev.items() if d]
    return min(flagged) if flagged else np.nan


def _indicator_first_dev_ci(progressors, obs, ind, sigma):
    rows = []
    for _, p in progressors.iterrows():
        by_w = {r["window"]: r for r in obs[obs["patient_id"] == p["patient_id"]].to_dict("records")}
        ev = p["event_window"]
        runin = np.mean([by_w[t][ind] for t in (0, 1) if t in by_w])
        full = {w: r[ind] for w, r in by_w.items() if w < ev}
        if len(full) < 3 or not np.isfinite(runin):
            continue
        fd = _first_deviation(full, runin, sigma[ind])
        if np.isfinite(fd):
            rows.append({"patient_id": p["patient_id"], "first_dev": fd})
    if not rows:
        return float("nan"), (float("nan"), float("nan")), 0
    frame = pd.DataFrame(rows)
    med = float(np.median(frame["first_dev"]))
    lo, hi = patient_bootstrap_ci(frame, lambda d: np.median(d["first_dev"]), b=200, seed=0)
    return med, (lo, hi), int(frame["patient_id"].nunique())


def _risk_set_match(patients, progressors):
    """风险集匹配（§7.1 + §10）：为进展患者匹配 1 名**在 index time（事件时间）尚未事件、
    随访覆盖 ≥ index time 且 index time 前未删失**的未进展患者（年龄分箱 × 性别，允许替换）。
    —— 对照在 index time 前已删失（censored_window <= idx）不算合格对照（随访未覆盖 index time）。"""
    matched = {}
    for _, p in progressors.iterrows():
        idx = p["event_window"]
        pool = patients[(patients["g"] != 1) & (patients["admin_end"] >= idx) &
                        ((patients["event_window"].isna()) | (patients["event_window"] > idx)) &
                        (patients["censored_window"].isna() | (patients["censored_window"] > idx))]
        eligible = pool[(pool["sex"] == p["sex"]) & ((pool["age"] // 10) == (p["age"] // 10))]
        if len(eligible):
            matched[p["patient_id"]] = eligible["patient_id"].iloc[0]
    return matched


def _first_dev_by_patient(progressors, obs, ind, sigma, cutoff=None):
    """{patient_id: 首次偏离窗口}；cutoff 缺省 = 该患者事件窗口（观察进展者）；
    匹配对照无事件窗口 → 传入显式 cutoff = 匹配的进展者事件时间（§7.1 伪零点）。"""
    out = {}
    for _, p in progressors.iterrows():
        by_w = {r["window"]: r for r in obs[obs["patient_id"] == p["patient_id"]].to_dict("records")}
        ev = cutoff if cutoff is not None else p["event_window"]
        if not np.isfinite(ev):
            continue
        runin = np.mean([by_w[t][ind] for t in (0, 1) if t in by_w])
        fd = _first_deviation({w: r[ind] for w, r in by_w.items() if w < ev}, runin, sigma)  # sigma 标量（调用方传 sigma[ind]）
        if np.isfinite(fd):
            out[p["patient_id"]] = fd
    return out


def lead_lag_analysis(patients, obs):
    sigma = {i: 0.1 * (cfg.REFERENCE_RANGES[i][1] - cfg.REFERENCE_RANGES[i][0]) for i in cfg.INDICATORS}
    prog = _observed_progressors(patients)
    matched = _risk_set_match(patients, prog)          # 匹配对照（§7.1，参与偏离比较）
    unmatched_rate = 1 - len(matched) / max(len(prog), 1)

    # 每指标可分析患者（§10 口径）：**该指标相关路径组**进展者中、**有匹配合格对照**且
    # 有限首偏的唯一患者（不是所有观察进展者）——门槛与 §10 第 3 条一致
    dev_by_ind = {ind: _first_dev_by_patient(prog, obs, ind, sigma[ind])
                  for ind in ("PLT", "HbA1c", "AFP")}
    ind_paths = {"PLT": ("r1_only", "r1_and_r2"), "HbA1c": ("r1_only", "r1_and_r2"),
                 "AFP": ("r2_only", "r1_and_r2")}
    per_indicator_n = {}
    for ind, grps in ind_paths.items():
        gids = set(prog[prog["group"].isin(grps)]["patient_id"]) & set(matched)
        per_indicator_n[ind] = len({pid for pid in gids if pid in dev_by_ind[ind]})

    per_path = {}
    for grp, inds in (("r1_only", ("PLT", "HbA1c")), ("r2_only", ("AFP",)),
                      ("r1_and_r2", ("PLT", "HbA1c", "AFP"))):
        gids = set(prog[prog["group"] == grp]["patient_id"])
        per_path[grp] = {}
        for ind in inds:
            rows = [(pid, v) for pid, v in dev_by_ind[ind].items() if pid in gids]
            if rows:
                frame = pd.DataFrame(rows, columns=["patient_id", "first_dev"])
                per_path[grp][ind] = {
                    "median": float(np.median(frame["first_dev"])),
                    "ci": patient_bootstrap_ci(frame, lambda d: np.median(d["first_dev"]), b=200, seed=0),
                }
            else:
                per_path[grp][ind] = {"median": np.nan, "ci": (np.nan, np.nan)}

    inter = prog[prog["group"] == "r1_and_r2"]
    n_inter = int(inter["patient_id"].nunique())
    # 逐患者比较：afp_dev vs 该患者 min(plt_dev, hba1c_dev)（真实破平）
    pairs = []
    for _, p in inter.iterrows():
        pid = p["patient_id"]
        e = np.nanmin([dev_by_ind["PLT"].get(pid, np.nan), dev_by_ind["HbA1c"].get(pid, np.nan)])
        a = dev_by_ind["AFP"].get(pid, np.nan)
        if np.isfinite(e) and np.isfinite(a):
            pairs.append((pid, e, a))
    early_med = float(np.median([e for _, e, _ in pairs])) if pairs else np.nan
    afp_med = float(np.median([a for _, _, a in pairs])) if pairs else np.nan

    afp_after_early = None
    tiebreak = 0
    tol = 1
    if pairs:
        n_afp_later = sum(1 for _, e, a in pairs if a > e + tol)
        n_afp_earlier = sum(1 for _, e, a in pairs if a <= e + tol)
        afp_after_early = afp_med > early_med + tol
        if not afp_after_early:
            tiebreak = n_afp_later - n_afp_earlier
            afp_after_early = tiebreak >= 0

    # 匹配对照比较（§7.1）：进展者 vs 对照 首偏中位数差（进展者应更早 → 差为负）
    # 对照无事件窗口 → 用匹配进展者的事件时间作显式 cutoff（伪零点）；
    # 对照在 cutoff 内无偏离 → 取 cutoff 端点（"未更早偏离"），保证 control_delta 有限
    prog_event = dict(zip(prog["patient_id"], prog["event_window"]))
    control_delta = {}
    for ind in ("PLT", "HbA1c", "AFP"):
        prog_vals, ctrl_vals = [], []
        for pid, fd in dev_by_ind[ind].items():
            cpid = matched.get(pid)
            if cpid is None or pid not in prog_event:
                continue
            cutoff_w = prog_event[pid]
            ctrl = _first_dev_by_patient(patients[patients["patient_id"] == cpid], obs, ind, sigma[ind],
                                         cutoff=cutoff_w).get(cpid, cutoff_w)   # 无偏离 → cutoff 端点
            if np.isfinite(fd) and np.isfinite(ctrl):
                prog_vals.append(fd); ctrl_vals.append(ctrl)
        control_delta[ind] = float(np.median(prog_vals) - np.median(ctrl_vals)) if prog_vals else np.nan

    not_estimable = (n_inter < cfg.THRESHOLDS["r1r2_intersection_min"]
                     or unmatched_rate > cfg.THRESHOLDS["unmatched_max"]
                     or any(per_indicator_n.get(i, 0) < cfg.THRESHOLDS["per_indicator_ll_min"]
                            for i in ("PLT", "HbA1c", "AFP")))
    return {"per_path": per_path,
            "order": {"early_median": early_med if np.isfinite(early_med) else None,
                      "afp_median": afp_med if np.isfinite(afp_med) else None,
                      "afp_after_early": afp_after_early,
                      "tiebreak_by_event_count": tiebreak},
            "control_delta": control_delta,
            "per_indicator_n": per_indicator_n, "n_intersection": n_inter,
            "unmatched_rate": unmatched_rate, "not_estimable": not_estimable}


def lag_shap_analysis(landmarks, clf, lags):
    import shap
    feat = [c for c in landmarks.columns if c not in ("patient_id", "window", "label", "group", "unobservable")]
    X = landmarks[feat].to_numpy()
    vals = shap.TreeExplainer(clf).shap_values(X)
    if isinstance(vals, list):
        vals = vals[1]
    out = {}
    for ind in ("PLT", "HbA1c", "AFP"):
        out[ind] = {}
        for lag in lags:
            suffix = {0: "_cur", 1: "_d6m", 2: "_d12m"}[lag]
            col = f"{ind}{suffix}"
            out[ind][lag] = float(np.mean(np.abs(vals[:, feat.index(col)]))) if col in feat else 0.0
    return out


def lag_ablation_analysis(landmarks, lags, seed=0):
    """整组滞后消融（§7.2）：**消融组 = 该指标在 `lags` 中对应的滞后观测列**
    （lags=[0,1,2] → _cur/_d6m/_d12m；slope/rises/drop_pct 为派生特征，不属滞后组、保留）。
    移除该组后重训患者级 OOF → 比较 AUC；**基线/移除后均报告患者 Bootstrap CI**
    （§7.2 滞后预测贡献分布带 CI）。与 SHAP 佐证互补（分摊下 SHAP 大小不可单独证明
    时间先后）；措辞限定为"模型预测贡献的时间滞后一致性（描述性）"，不解释为因果先后。"""
    feat = [c for c in landmarks.columns
            if c not in ("patient_id", "window", "label", "group", "unobservable")]
    suffixes = {0: "_cur", 1: "_d6m", 2: "_d12m"}
    base_res = fit_and_oof(landmarks, cfg.THRESHOLDS["cv_folds"], 1, [seed])
    base_auc, base_ci = base_res["auc_point"], base_res["auc_ci"]
    out = {}
    for ind in ("PLT", "HbA1c", "AFP"):
        drop_cols = [f"{ind}{suffixes[lag]}" for lag in lags if f"{ind}{suffixes[lag]}" in feat]
        res_d = fit_and_oof(landmarks.drop(columns=drop_cols),
                            cfg.THRESHOLDS["cv_folds"], 1, [seed])
        out[ind] = {"baseline_auc": float(base_auc), "baseline_ci": tuple(base_ci),
                    "without_auc": float(res_d["auc_point"]), "without_ci": tuple(res_d["auc_ci"]),
                    "auc_drop": float(base_auc - res_d["auc_point"])}
    return out
