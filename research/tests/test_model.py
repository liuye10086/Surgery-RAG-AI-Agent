import numpy as np
import pandas as pd
from simulate_cohort import simulate
from features import qualifying_landmarks
from model import fit_and_oof

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
