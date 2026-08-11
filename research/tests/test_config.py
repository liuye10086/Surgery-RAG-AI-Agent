import config as cfg

def test_indicators_and_ranges():
    assert len(cfg.INDICATORS) == 10
    assert set(cfg.INDICATORS) == {"ALT", "AST", "GGT", "TBIL", "ALB", "PLT", "HbA1c", "AFP", "WAIST", "BMI"}
    assert set(cfg.REFERENCE_RANGES) == set(cfg.INDICATORS)

def test_sim_constants():
    assert cfg.SIM["window_months"] == 6
    assert cfg.SIM["censoring_rate"] == 0.2
    assert cfg.SIM["kappa"] >= 2.0
    assert cfg.SIM["delta_choices"] == [1, 2]
    assert cfg.SIM["calibration_n"] == 50_000
    # 信号强度（可观测条件成立 >=95% 的前提）
    assert cfg.SIM["hba1c_rise_per_window"] >= 2 * 0.1 * (cfg.REFERENCE_RANGES["HbA1c"][1] - cfg.REFERENCE_RANGES["HbA1c"][0])
    assert 0 < cfg.SIM["plt_decline_per_window"] < 1

def test_calibration_both_horizons():
    assert cfg.CALIBRATION[24] == {"neither": 0.12, "r1_only": 0.60, "r2_only": 0.40, "r1_and_r2": 0.73}
    assert cfg.CALIBRATION[12] == {"neither": 0.06, "r1_only": 0.40, "r2_only": 0.25, "r1_and_r2": 0.52}

def test_grid_and_thresholds():
    assert cfg.GRID["method_validation"] == {"n": 1500, "followup_months": 60, "horizon_months": 24}
    assert cfg.GRID["scale_down"]["n"] == [150, 300, 600, 1500]
    assert cfg.THRESHOLDS["auc_ci_lower_gate"] == 0.65
    assert cfg.THRESHOLDS["coverage_gate"] == 0.80
    assert cfg.THRESHOLDS["per_indicator_ll_min"] == 20
    assert cfg.THRESHOLDS["method_acceptance_seeds"] == 20
    assert cfg.THRESHOLDS["event_bins"] == [0, 10, 20, 30, 40, 50, 75, 100, 150, 10 ** 9]
    assert cfg.THRESHOLDS["bin_min_cohorts"] == 10
    # 通用候选网格（无 planted 语义优先）与边界 Bootstrap 参数
    assert cfg.THRESHOLDS["candidate_grid"]["age"] == [50, 40, 60]
    assert cfg.THRESHOLDS["candidate_grid"]["drop_pct"] == [0.20, 0.10, 0.30]
    assert cfg.THRESHOLDS["boundary_bootstrap_b"] == 200
    assert cfg.THRESHOLDS["boundary_valid_ratio_min"] == 0.5

def test_planted_conditions():
    assert ("sex", "eq", "male") in cfg.PLANTED_CONDITIONS["r1"]
    assert ("HbA1c", "consecutive_rises", 2.0) in cfg.PLANTED_CONDITIONS["r1"]
    assert ("AFP", "consecutive_rises", 2.0) in cfg.PLANTED_CONDITIONS["r2"]
