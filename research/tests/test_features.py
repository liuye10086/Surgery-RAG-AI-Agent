import numpy as np
import config as cfg
from simulate_cohort import simulate
from features import qualifying_landmarks, confirmation_subset, label_for, derive_window_features

def test_derived_features_hand():
    rows = [{"window": 0, "ALT": 30.0}, {"window": 1, "ALT": 33.0}, {"window": 2, "ALT": 36.0}]
    f = derive_window_features(rows, "ALT", window=2, runin=2)
    assert f["ALT_cur"] == 36.0 and f["ALT_d6m"] == 3.0 and f["ALT_d12m"] == 6.0 and f["ALT_rises"] == 2

def test_qualifying_uses_all_landmarks():
    # followup=36（admin_end=6、hw=2 → 每患者 3 个合格窗口）：followup=24 下每患者
    # 至多 1 窗、len(lm) > nunique 数学上不可能（v5.24 锚点契约连锁，同 coverage 测试）
    out = simulate(n=300, followup_months=36, horizon_months=12, seed=1)
    lm = qualifying_landmarks(out["patients"], out["obs"], horizon_windows=2)
    assert len(lm) > out["patients"]["patient_id"].nunique()
    assert "label" in lm.columns and "sex_male" in lm.columns
    assert "sex" not in lm.columns   # 无字符串列

def test_confirmation_subset_contract():
    out = simulate(n=300, followup_months=36, horizon_months=12, seed=1)
    sub = confirmation_subset(out["patients"], out["obs"], horizon_windows=2)
    assert sub["patient_id"].is_unique
    for col in ["group", "unobservable", "admin_end", "sex_male", "label"]:
        assert col in sub.columns
    assert (sub["admin_end"] - sub["window"] >= 2).all()
    assert set(sub["label"]) <= {0, 1}   # unknown 已剔除
    assert sub.attrs["horizon_windows"] == 2

def test_label_semantics():
    out = simulate(n=300, followup_months=24, horizon_months=12, seed=1)
    p = out["patients"].iloc[0]
    assert label_for(p, 2, 2) in (0, 1, "unknown")

def test_label_same_window_event_censor_unknown():
    # 事件窗口 == 删失窗口（同窗）：事件未在删失前被观察到 → **unknown**（不得落入负例 0）
    same = {"event_window": 4.0, "censored_window": 4.0}
    assert label_for(same, 2, 2) == "unknown"          # 同窗且都在视界内
    assert label_for(same, 0, 4) == "unknown"          # 同窗、窗口更早视界更宽
    # 对照：删失在事件后（cw > ev）→ 正例；事件在删失后（ev > cw）→ unknown
    assert label_for({"event_window": 4.0, "censored_window": 6.0}, 2, 4) == 1
    assert label_for({"event_window": 6.0, "censored_window": 4.0}, 2, 4) == "unknown"
    # 同窗但在视界外 → 无事件无删失在视界内 → 负例
    assert label_for({"event_window": 8.0, "censored_window": 8.0}, 2, 2) == 0
