"""患者级 splitter + 聚类 Bootstrap（保留 multiplicity）。"""
from __future__ import annotations
import numpy as np
import pandas as pd


def patient_folds(patients, n_folds, seed):
    rng = np.random.default_rng(seed)
    out = np.full(len(patients), -1, dtype=int)
    ids = patients["patient_id"].to_numpy()
    for ev in (0, 1):
        pid = np.unique(ids[patients["patient_event"].to_numpy() == ev])
        perm = rng.permutation(pid)
        for i, p in enumerate(perm):
            out[ids == p] = i % n_folds
    return out


def patient_bootstrap_samples(patient_ids, b, seed):
    rng = np.random.default_rng(seed)
    uniq = np.unique(patient_ids)
    return [rng.choice(uniq, size=len(uniq), replace=True) for _ in range(b)]


def resample_rows(frame, sampled_ids):
    return frame.set_index("patient_id").loc[sampled_ids].reset_index()


def patient_bootstrap_ci(frame, stat_fn, b=1000, seed=0):
    """患者聚类 Bootstrap CI（无效重采样契约）：
    - 单类样本（如 AUC 不可定义抛 ValueError）→ 丢弃该样本；
    - 非有限统计值（NaN/inf）→ 丢弃；
    - 有效样本 <2 → 返回 (nan, nan)（**CI 未估计**，调用方必须处理，不得静默视为数值 CI）。
    绝不因单个 Bootstrap 样本的异常而中断整个 CI。"""
    samples = patient_bootstrap_samples(frame["patient_id"].to_numpy(), b, seed)
    vals = []
    for s in samples:
        try:
            v = stat_fn(resample_rows(frame, s))
        except ValueError:
            continue                        # 单类样本（AUC 不可定义）→ 丢弃该样本
        if np.isfinite(v):
            vals.append(v)
    if len(vals) < 2:
        return float("nan"), float("nan")   # 有效样本不足 → CI 未估计
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))
