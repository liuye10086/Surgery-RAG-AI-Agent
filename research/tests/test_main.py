import numpy as np
import pandas as pd
import pytest
import config as cfg
import main as m
from main import run_method_validation, main

@pytest.mark.slow
def test_full_pipeline_fields():
    res = run_method_validation(seed=7)
    for key in ["signal_gate", "auc_ci", "lag_shap", "lag_ablation", "p_obs",
                "recovery", "calibration", "report_md"]:
        assert key in res
    assert res["signal_gate"] is True
    assert set(res["calibration"]) == {"targets", "actuals", "errors", "ok"}
    assert set(res["calibration"]["targets"]) == {"neither", "r1_only", "r2_only", "r1_and_r2"}
    # ±3pp 硬断言（规格 §5.3，独立 N=50,000 校准队列）：四组 |误差| ≤ 0.03
    assert res["calibration"]["ok"] is True
    for grp, e in res["calibration"]["errors"].items():
        assert abs(e) <= 0.03, (grp, e)

def test_calibration_ok_fails_on_nan(monkeypatch):
    # actual/error 为 NaN 时 abs(NaN) > 0.03 比较为 False——若不做有限性检查会错误保留 ok=True；
    # 必须显式要求 actual 有限且 |误差| ≤ 0.03（monkeypatch 校准潜在风险为 NaN）
    monkeypatch.setattr(m, "_group_latent_risk", lambda *a, **k: float("nan"))
    cal = m.calibrate_gates(24, cal_n=1000)
    res = m._latent_risk_calibration(24, 4, cal)
    assert res["ok"] is False
    for grp in res["actuals"]:
        assert np.isnan(res["actuals"][grp])

def test_signal_gate_stops_downstream(monkeypatch):
    # 规格 §6.3：最终平均 OOF 预测上 AUC 患者聚类 95% CI 下界 < 0.65
    # → 归因与规则挖掘**直接停止并亮红灯**（确定性：monkeypatch fit_and_oof 返回低 AUC CI）
    def low_signal(lm, n_folds, n_repeats, seeds):
        return {"not_estimable": False, "oof_mean": np.zeros(len(lm)),
                "auc_ci": (0.5, 0.6), "auc_point": 0.55, "pr_auc": 0.5,
                "brier": 0.5, "auc_median_across_repeats": 0.55,
                "oof_frame": pd.DataFrame()}
    monkeypatch.setattr(m, "fit_and_oof", low_signal)
    res = m.run_method_validation(seed=7)
    assert res["signal_gate"] is False
    assert res["auc_ci"][0] < cfg.THRESHOLDS["auc_ci_lower_gate"]
    assert "recovery" not in res and "lead_lag" not in res and "lag_shap" not in res
    assert "信号门槛未达" in res["report_md"]                 # 报告亮红灯（停止原因可见）

@pytest.mark.slow
def test_cli_writes_files(tmp_path):
    main(["--mode", "method-validation", "--out", str(tmp_path)])
    assert (tmp_path / "report_method_validation.md").exists()
