import numpy as np
import pandas as pd
from splitters import patient_folds, patient_bootstrap_samples, resample_rows, patient_bootstrap_ci

def _mk(n=100, p_event=0.3, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"patient_id": np.arange(n), "patient_event": rng.random(n) < p_event})

def test_patient_never_split():
    folds = patient_folds(_mk(), 5, 1)
    assert set(folds) <= {0, 1, 2, 3, 4}

def test_folds_stratified():
    df = _mk(400, p_event=0.3)
    folds = patient_folds(df, 5, 2)
    for k in range(5):
        assert abs(df.loc[folds == k, "patient_event"].mean() - 0.3) < 0.08

def test_resample_preserves_multiplicity():
    df = pd.DataFrame({"patient_id": [0, 1], "value": [10.0, 20.0]})
    rows = resample_rows(df, np.array([0, 0]))
    assert len(rows) == 2 and rows["value"].sum() == 20.0

def test_bootstrap_samples_keep_length():
    samples = patient_bootstrap_samples(np.array([0, 1, 2]), b=50, seed=0)
    assert all(len(s) == 3 for s in samples)

def test_patient_bootstrap_ci():
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({"patient_id": np.repeat(np.arange(20), 5), "value": rng.normal(size=100)})
    lo, hi = patient_bootstrap_ci(frame, lambda d: d["value"].mean(), b=200, seed=0)
    assert lo < frame["value"].mean() < hi

def test_bootstrap_ci_single_class_dropped():
    # 全正例患者 → 任何重采样都单类 → AUC 抛 ValueError → 全部样本丢弃
    # → 有效样本 <2 → (nan, nan)（CI 未估计），**不抛异常**
    from sklearn.metrics import roc_auc_score
    frame = pd.DataFrame({"patient_id": np.zeros(10, dtype=int),
                          "label": np.ones(10, dtype=int), "x": np.arange(10.0)})
    lo, hi = patient_bootstrap_ci(frame, lambda d: roc_auc_score(d["label"], d["x"]),
                                  b=30, seed=0)
    assert np.isnan(lo) and np.isnan(hi)

def test_bootstrap_ci_nan_stats_dropped():
    # 非有限统计值被丢弃；其余样本正常 → CI 有限
    frame = pd.DataFrame({"patient_id": np.repeat(np.arange(10), 5),
                          "value": np.repeat([1.0, 2.0, 3.0, 4.0, 5.0], 10)})
    def stat(d):
        v = d["value"].mean()
        return v if v < 4.0 else float("nan")      # 部分样本 NaN → 丢弃
    lo, hi = patient_bootstrap_ci(frame, stat, b=100, seed=0)
    assert np.isfinite(lo) and np.isfinite(hi)
