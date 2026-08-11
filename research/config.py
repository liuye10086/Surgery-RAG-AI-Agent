"""版本化配置（自包含，不依赖生产 DB）。规格 v16。"""
INDICATORS = ["ALT", "AST", "GGT", "TBIL", "ALB", "PLT", "HbA1c", "AFP", "WAIST", "BMI"]
REFERENCE_RANGES = {
    "ALT": (9, 50, True, True, "U/L"), "AST": (13, 40, True, True, "U/L"),
    "GGT": (10, 60, True, True, "U/L"), "TBIL": (5, 21, True, True, "umol/L"),
    "ALB": (40, 55, True, True, "g/L"), "PLT": (125, 350, True, True, "x10^9/L"),
    "HbA1c": (4.0, 6.5, True, True, "%"), "AFP": (0, 7, True, True, "ng/mL"),
    "WAIST": (0, 90, True, True, "cm"), "BMI": (18.5, 24.0, True, True, "kg/m2"),
}
SIM = {"window_months": 6, "censoring_rate": 0.20, "kappa": 2.0, "tau": 0.0,
       "delta_choices": [1, 2], "delta_default": 1, "resample_max": 100,
       "calibration_n": 50_000, "calibration_tol_pp": 3.0,
       "observability_gate": 0.95, "calibration_group_min": 200,
       "hba1c_rise_per_window": 1.0,     # >= 2*sigma(HbA1c)=0.5 → 两窗连续上升 ~0.995（K=20 余量）
       "plt_decline_per_window": 0.80,   # 乘性 20%/窗下降；w>=w0+3 时较基线降 >=44% >> 20%（噪声 sd ~12pp，锚点推迟后余量 >=2σ）
       "afp_rise_per_window": 6.0}
CALIBRATION = {
    24: {"neither": 0.12, "r1_only": 0.60, "r2_only": 0.40, "r1_and_r2": 0.73},
    12: {"neither": 0.06, "r1_only": 0.40, "r2_only": 0.25, "r1_and_r2": 0.52},
}
GRID = {"method_validation": {"n": 1500, "followup_months": 60, "horizon_months": 24},
        "scale_down": {"n": [150, 300, 600, 1500],
                       "followup_months": [24, 36, 60], "horizon_months": 12},
        "repeats": 50, "repeats_max": 200, "ci_halfwidth_target": 0.10}
THRESHOLDS = {"auc_ci_lower_gate": 0.65, "coverage_gate": 0.80,
              "r1r2_intersection_min": 30, "per_indicator_ll_min": 20,
              "unmatched_max": 0.20, "rule_event_support_min": 5,
              "rule_total_support_min": 20, "max_conditions": 4, "top_m": 8,
              "thresholds_per_feature": 3, "lift_min": 1.5,
              # Apriori 逐层 + 训练折支持度剪枝的**评估组合数预算**：每层所有被评估的组合
              # （含未通过支持度门槛者）累计超限即 raise（防静默截断，需调大）
              "max_candidates": 10000,
              "method_acceptance_seeds": 20, "method_acceptance_pass_rate": 0.90,
              "bootstrap_b": 1000, "cv_folds": 5, "cv_repeats": 5, "shap_lags": [0, 1, 2],
              "calibrate_tol": 0.005, "calibrate_bisect_iters": 40, "calibrate_hi_max": 128.0,
              "event_bins": [0, 10, 20, 30, 40, 50, 75, 100, 150, 10 ** 9],
              "bin_min_cohorts": 10, "boundary_threshold": 0.50,
              # 规则候选临床阈值网格（通用、确定性；§8.1 折内 SHAP top-M/分位数的固定网格补充）
              "candidate_grid": {"age": [50, 40, 60],
                                 "consecutive_rises": [2, 1],
                                 "drop_pct": [0.20, 0.10, 0.30]},
              # 规则发现：Apriori 逐层 + 训练折支持度剪枝 + (-lift, canonical) 排序取 top_k（无植入语义优先）
              "discover_top_k": 20,
              # 可靠性边界 Bootstrap（版本化）
              "boundary_bootstrap_b": 200, "boundary_valid_ratio_min": 0.5}
PLANTED_CONDITIONS = {
    "r1": [("sex", "eq", "male"), ("age", "gt", 50.0),
           ("HbA1c", "consecutive_rises", 2.0), ("PLT", "drop_pct", 20.0)],
    "r2": [("AFP", "consecutive_rises", 2.0)],
}
