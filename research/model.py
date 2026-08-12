"""进展二分类 + 患者级 OOF（患者聚合分层 + 全数值特征）。"""
from __future__ import annotations
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
import config as cfg
from splitters import patient_folds, patient_bootstrap_ci

# 模型特征 = 指标派生特征 + age + sex_male（规格 §6.1）。
# admin_end 是随访设计/资格元数据，**不进入模型**（v5.26，Codex 批次 2 P2-2：
# 单网格单元内恒常量，但合并不同随访队列时会泄漏研究设计差异）
_META_COLS = ("patient_id", "window", "label", "group", "unobservable", "admin_end")


def _feat_cols(lm):
    return [c for c in lm.columns if c not in _META_COLS]


def train_model(lm, seed=0):
    clf = GradientBoostingClassifier(random_state=seed)
    clf.fit(lm[_feat_cols(lm)], lm["label"])
    return clf


def fit_and_oof(lm, n_folds, n_repeats, seeds):
    # v5.26（Codex 批次 2 P2-1）：显式校验 n_repeats 与 seeds 长度一致，
    # 避免静默少跑/空 seeds 在 vstack/seeds[0] 处崩溃
    if n_repeats < 1 or len(seeds) != n_repeats:
        raise ValueError(f"n_repeats={n_repeats} 与 seeds 长度 {len(seeds)} 不一致（需 >=1 且相等）")
    y = lm["label"].to_numpy()
    # 唯一患者聚合（患者级结局）→ splitter → 映射回 landmark 行
    uniq = lm.groupby("patient_id")["label"].max().reset_index()
    uniq["patient_event"] = (uniq["label"] > 0).astype(int)
    event_pat = int((uniq["patient_event"] == 1).sum())
    nonevent_pat = int((uniq["patient_event"] == 0).sum())
    k = min(n_folds, event_pat, nonevent_pat)
    if min(event_pat, nonevent_pat) < 2 or k < 2:
        return {"not_estimable": True, "oof_mean": np.full(len(lm), np.nan),
                "auc_ci": (np.nan, np.nan), "auc_point": np.nan, "pr_auc": np.nan,
                "brier": np.nan, "auc_median_across_repeats": np.nan, "oof_frame": pd.DataFrame()}
    pid_to_row = {pid: i for i, pid in enumerate(uniq["patient_id"])}
    patient_row = lm["patient_id"].map(pid_to_row).to_numpy()
    oofs = []
    for seed in seeds:
        folds_uniq = patient_folds(uniq, k, seed)
        folds = folds_uniq[patient_row]
        oof = np.full(len(lm), np.nan)
        for j in range(k):
            tr, va = folds != j, folds == j
            clf = GradientBoostingClassifier(random_state=seed)
            clf.fit(lm.loc[tr, _feat_cols(lm)], y[tr])
            oof[va] = clf.predict_proba(lm.loc[va, _feat_cols(lm)])[:, 1]
        oofs.append(oof)
    oof_mean = np.nanmean(np.vstack(oofs), axis=0)
    valid = np.isfinite(oof_mean)
    auc_point = roc_auc_score(y[valid], oof_mean[valid])
    auc_lo, auc_hi = patient_bootstrap_ci(
        pd.DataFrame({"patient_id": lm["patient_id"].to_numpy()[valid],
                      "label": y[valid], "oof": oof_mean[valid]}),
        lambda d: roc_auc_score(d["label"], d["oof"]),
        b=cfg.THRESHOLDS["bootstrap_b"], seed=seeds[0])
    return {"not_estimable": False, "oof_mean": oof_mean, "auc_ci": (auc_lo, auc_hi),
            "auc_point": auc_point,
            "pr_auc": average_precision_score(y[valid], oof_mean[valid]),
            "brier": brier_score_loss(y[valid], oof_mean[valid]),
            "auc_median_across_repeats": float(np.median(
                [roc_auc_score(y[np.isfinite(o)], o[np.isfinite(o)]) for o in oofs])),
            "oof_frame": pd.DataFrame({"patient_id": lm["patient_id"].to_numpy()[valid],
                                       "label": y[valid], "oof": oof_mean[valid]})}
