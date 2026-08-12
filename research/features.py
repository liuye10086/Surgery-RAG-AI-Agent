"""窗口特征 + landmark 化 + sex 编码（无未来泄漏；分角色口径）。"""
from __future__ import annotations
import numpy as np
import pandas as pd
import config as cfg

# 固定输出列 schema（v5.26，Codex 批次 2 P1：空数据集必须保留完整列，
# 否则下游 model.py 访问 lm["label"] / mine_rules 访问 sub["unobservable"] KeyError）
_FEATURE_BASE_COLS = ["patient_id", "window", "age", "sex_male", "group", "admin_end"]
_FEATURE_METRIC_COLS = [f"{ind}_{s}" for ind in cfg.INDICATORS
                        for s in ("cur", "d6m", "d12m", "slope", "rises", "drop_pct")]
FEATURE_SCHEMA = _FEATURE_BASE_COLS + _FEATURE_METRIC_COLS + ["label"]


def _empty_frame(extra_cols=()):
    """带完整固定列 schema 的空 DataFrame（无行）。"""
    return pd.DataFrame(columns=list(FEATURE_SCHEMA) + list(extra_cols))


def derive_window_features(obs_rows, ind, window, runin=2):
    series = {r["window"]: r[ind] for r in obs_rows if ind in r}
    base = np.mean([series.get(t, np.nan) for t in range(runin) if t in series])
    cur = series.get(window, np.nan)
    d6 = cur - series.get(window - 1, np.nan) if window - 1 in series else np.nan
    d12 = cur - series.get(window - 2, np.nan) if window - 2 in series else np.nan
    slope = series.get(window - 1, np.nan) - series.get(window - 2, np.nan) if window - 2 in series else np.nan
    rises = 0
    if window - 2 in series and window - 1 in series and window in series:
        rises = int((series[window] > series[window - 1]) + (series[window - 1] > series[window - 2]))
    drop = 0.0
    if np.isfinite(base) and base != 0 and np.isfinite(cur):
        drop = (cur - base) / base
    return {f"{ind}_cur": cur, f"{ind}_d6m": d6, f"{ind}_d12m": d12,
            f"{ind}_slope": slope, f"{ind}_rises": rises, f"{ind}_drop_pct": drop}


def label_for(patient, window, horizon_windows):
    ev, cw = patient["event_window"], patient["censored_window"]
    if np.isfinite(ev) and ev <= window + horizon_windows and (not np.isfinite(cw) or cw > ev):
        return 1
    # **事件时间 == 删失时间（同窗）**：事件未在删失前被观察到（删失即终止观察）→ unknown，
    # 不得落入负例（`ev >= cw` 而非 `ev > cw`）
    if np.isfinite(cw) and cw <= window + horizon_windows and (not np.isfinite(ev) or ev >= cw):
        return "unknown"
    return 0


def _feature_row(patient, obs_by_w, window, runin=2):
    row = {"patient_id": patient["patient_id"], "window": window,
           "age": patient["age"], "sex_male": int(patient["sex"] == "male"),
           "group": patient["group"], "admin_end": patient["admin_end"]}
    for ind in cfg.INDICATORS:
        row.update(derive_window_features(obs_by_w, ind, window, runin))
    return row


def qualifying_landmarks(patients, obs, horizon_windows):
    obs_by_pid = {pid: g.to_dict("records") for pid, g in obs.groupby("patient_id")}
    rows, excluded = [], 0
    for _, p in patients.iterrows():
        by_w = obs_by_pid[p["patient_id"]]
        for w in range(2, p["admin_end"] - horizon_windows + 1):
            if np.isfinite(p["event_window"]) and w >= p["event_window"]: break
            if np.isfinite(p["censored_window"]) and w >= p["censored_window"]: break
            lab = label_for(p, w, horizon_windows)
            if lab == "unknown":
                excluded += 1
                continue
            r = _feature_row(p, by_w, w)
            r["label"] = lab
            rows.append(r)
    df = _empty_frame() if not rows else pd.DataFrame(rows)   # 空结果保留完整 schema（v5.26）
    df.attrs["excluded_unknown"] = excluded
    return df


def confirmation_subset(patients, obs, horizon_windows):
    obs_by_pid = {pid: g.to_dict("records") for pid, g in obs.groupby("patient_id")}
    rows, excluded = [], 0
    for _, p in patients.iterrows():
        w = p["confirm_window"]
        if not np.isfinite(w):
            continue
        lab = label_for(p, int(w), horizon_windows)
        if lab == "unknown":
            excluded += 1
            continue
        r = _feature_row(p, obs_by_pid[p["patient_id"]], int(w))
        r["label"] = lab
        r["unobservable"] = bool(p["unobservable"])
        rows.append(r)
    df = _empty_frame(extra_cols=("unobservable",)) if not rows else pd.DataFrame(rows)
    df.attrs["horizon_windows"] = horizon_windows
    df.attrs["excluded_unknown"] = excluded
    return df
