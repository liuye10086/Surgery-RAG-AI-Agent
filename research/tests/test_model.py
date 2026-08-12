import numpy as np
import pandas as pd
import pytest
from simulate_cohort import simulate
from features import qualifying_landmarks
from model import fit_and_oof, _feat_cols

def _lm():
    # followup=36（admin_end=6）：24 月随访下路径组全 no_feasible → 无事件 → 全负例 →
    # event_pat=0 → not_estimable（v5.24 锚点契约连锁，同 coverage/features 测试修正）
    out = simulate(n=600, followup_months=36, horizon_months=12, seed=3)
    return qualifying_landmarks(out["patients"], out["obs"], horizon_windows=2)

def test_oof_metrics_and_estimable():
    lm = _lm()
    res = fit_and_oof(lm, 3, 2, [1, 2])
    assert res["not_estimable"] is False
    assert len(res["oof_mean"]) == len(lm)
    assert res["auc_ci"][0] < res["auc_ci"][1]
    assert len(res["oof_frame"]) == len(lm)

def test_not_estimable_few_patients():
    res = fit_and_oof(_lm().iloc[:3], 3, 1, [1])
    assert res["not_estimable"] is True

def test_features_are_numeric():
    lm = _lm()
    X = lm[[c for c in lm.columns if c not in ("patient_id", "window", "label", "group", "unobservable")]]
    assert all(X.dtypes != object)

def test_n_repeats_must_match_seeds():
    """n_repeats 与 seeds 长度显式校验（Codex 批次 2 P2-1）：不一致/零重复
    显式 ValueError，不静默少跑、不在 vstack/seeds[0] 处崩溃。"""
    lm = _lm()
    with pytest.raises(ValueError):
        fit_and_oof(lm, 3, 5, [1])            # n_repeats=5 但 seeds 长度 1
    with pytest.raises(ValueError):
        fit_and_oof(lm, 3, 0, [])             # 零重复

def test_model_features_exclude_admin_end():
    """模型特征 = 指标派生 + age + sex_male，**不含 admin_end**（Codex 批次 2 P2-2：
    随访设计/资格元数据不进模型，避免合并队列时泄漏研究设计差异）。"""
    lm = _lm()
    cols = _feat_cols(lm)
    assert "admin_end" not in cols
    assert "age" in cols and "sex_male" in cols
    assert all(c in ("age", "sex_male")
               or c.endswith(("_cur", "_d6m", "_d12m", "_slope", "_rises", "_drop_pct"))
               for c in cols)

def test_empty_landmarks_not_estimable_chain():
    """空 landmark（完整 schema）→ fit_and_oof 返回 not_estimable，不 KeyError
    （Codex 批次 2 P1 下游链）。"""
    lm = _lm().iloc[0:0]
    assert "label" in lm.columns and "patient_id" in lm.columns
    res = fit_and_oof(lm, 3, 1, [1])
    assert res["not_estimable"] is True
