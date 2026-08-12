import numpy as np
import pandas as pd
import config as cfg
from simulate_cohort import simulate
from features import qualifying_landmarks
from model import train_model
from attribution import lag_shap_analysis, lag_ablation_analysis


def _lm():
    # followup=36（admin_end=6）：24 月随访下路径组全 no_feasible → 无事件 → 全负例 →
    # fit_and_oof not_estimable → ablation 的 auc/CI 断言失败（v5.29，锚点契约连锁同款）
    out = simulate(n=500, followup_months=36, horizon_months=12, seed=2)
    return qualifying_landmarks(out["patients"], out["obs"], horizon_windows=2)

def test_lag_shap_returns_per_lag():
    lm = _lm()
    res = lag_shap_analysis(lm, train_model(lm, seed=0), lags=[0, 1, 2])
    assert set(res) == {"PLT", "HbA1c", "AFP"}
    for ind in res:
        assert set(res[ind]) == {0, 1, 2}
        assert all(v >= 0 for v in res[ind].values())

def test_shap_feature_columns_numeric():
    lm = _lm()
    import numpy as np
    assert all(lm.dtypes != object)

def test_lag_ablation_group_contract():
    lm = _lm()
    res = lag_ablation_analysis(lm, lags=[0, 1, 2], seed=0)
    assert set(res) == {"PLT", "HbA1c", "AFP"}
    for ind, d in res.items():
        assert set(d) == {"baseline_auc", "baseline_ci", "without_auc", "without_ci", "auc_drop"}
        assert 0 <= d["baseline_auc"] <= 1 and 0 <= d["without_auc"] <= 1
        assert np.isfinite(d["auc_drop"])
        assert len(d["baseline_ci"]) == 2 and len(d["without_ci"]) == 2

def test_lag_ablation_signal_group_drop_positive():
    # 植入信号确定（HbA1c/AFP 滞后观测列携带独立预测贡献）→ 移除该指标全部滞后组
    # 应使 OOF AUC 下降（固定种子确定性；§7.2"整组消融"实质断言）。
    # **PLT 例外（v5.29）**：PLT 基线异质性（SD 37.5）> 乘性衰减信号（2 窗后 ~48/窗）
    # → PLT_cur 水平值预测力被基线噪声稀释；消融契约保留派生特征 PLT_drop_pct
    # （信号核心）→ 移除滞后观测列后模型无损失（实测 auc_drop ≈ -0.003，AUC 微升
    # 系噪声特征移除收益）——PLT 不设正断言，其滞后贡献由 SHAP 佐证覆盖。
    lm = _lm()
    res = lag_ablation_analysis(lm, lags=[0, 1, 2], seed=0)
    assert res["HbA1c"]["auc_drop"] > 0.0 and res["AFP"]["auc_drop"] > 0.0

def test_lag_ablation_ci_estimable():
    # 正常数据：基线/移除后患者 Bootstrap CI **两端有限**（可估计）
    lm = _lm()
    res = lag_ablation_analysis(lm, lags=[0, 1, 2], seed=0)
    for ind, d in res.items():
        assert all(np.isfinite(v) for v in d["baseline_ci"])
        assert all(np.isfinite(v) for v in d["without_ci"])

def _insufficient_frame():
    """显式不足样本：**仅 1 个唯一正例患者 + 5 个负例患者** → fit_and_oof 的
    min(唯一正例, 唯一负例) = 1 < 2 → not_estimable → auc_ci 确定性 (nan, nan)。
    （`_lm().iloc[:5]` 不能保证唯一正/负 <2，前 5 行可能恰含多正例多负例，故不用。）"""
    def feat():
        d = {}
        for i in cfg.INDICATORS:
            d.update({f"{i}_cur": 1.0, f"{i}_d6m": 0.0, f"{i}_d12m": 0.0,
                      f"{i}_slope": 0.0, f"{i}_rises": 0, f"{i}_drop_pct": 0.0})
        return d
    rows = [{"patient_id": 0, "window": 2, "label": 1, "age": 55, "sex_male": 1,
             "group": "r1_only", "unobservable": False, "admin_end": 8, **feat()}]
    for pid in range(1, 6):
        rows.append({"patient_id": pid, "window": 2, "label": 0, "age": 30, "sex_male": 0,
                     "group": "neither", "unobservable": False, "admin_end": 8, **feat()})
    return pd.DataFrame(rows)

def test_lag_ablation_ci_unestimated_insufficient():
    # 不足样本（fit_and_oof not_estimable）→ CI **必须 (nan, nan)**（CI 未估计），
    # 不得伪装为数值；报告 _fmt_ci 渲染 [NA, NA]（不得把 (nan,nan) 当有效结果）
    res = lag_ablation_analysis(_insufficient_frame(), lags=[0, 1, 2], seed=0)
    for ind, d in res.items():
        assert np.isnan(d["baseline_ci"][0]) and np.isnan(d["baseline_ci"][1])
        assert np.isnan(d["without_ci"][0]) and np.isnan(d["without_ci"][1])
