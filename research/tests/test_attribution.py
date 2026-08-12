import numpy as np
from simulate_cohort import simulate
from attribution import lead_lag_analysis

OUT = simulate(n=1500, followup_months=60, horizon_months=24, seed=5)

def test_no_planted_rules():
    import inspect
    assert "planted_rules" not in inspect.signature(lead_lag_analysis).parameters

def test_nested_structure_and_fields_always_present():
    res = lead_lag_analysis(OUT["patients"], OUT["obs"])
    for grp in ("r1_only", "r2_only", "r1_and_r2"):
        assert grp in res["per_path"]
        for ind, meta in res["per_path"][grp].items():
            assert set(meta) == {"median", "ci"}
            lo, hi = meta["ci"]
            assert lo <= hi
    for ind in ("PLT", "HbA1c", "AFP"):
        assert ind in res["per_indicator_n"]
        assert ind in res["control_delta"]
        assert ind in res["control_delta_ci"]           # v5.29：配对差异 CI（§7.1）
        lo, hi = res["control_delta_ci"][ind]
        assert lo <= hi
    # 匹配对照参与：至少一个指标有有限 control_delta（进展者更早 → 为负）
    assert any(np.isfinite(v) for v in res["control_delta"].values())
    # 有匹配对照的指标应有配对差异 CI 有限（进展者更早 → 负中位）
    assert any(all(np.isfinite(v) for v in res["control_delta_ci"][i])
               for i in ("PLT", "HbA1c", "AFP"))
    for k in ("early_median", "afp_median", "afp_after_early", "tiebreak_by_event_count"):
        assert k in res["order"]

def test_estimable_case_order_and_thresholds():
    res = lead_lag_analysis(OUT["patients"], OUT["obs"])
    # 大 N 确定性 fixture（N=1500、60 月、24 月视界）应可估计——不允许无条件跳过
    assert res["not_estimable"] is False
    assert res["n_intersection"] >= 30
    assert all(n >= 20 for n in res["per_indicator_n"].values())
    assert res["unmatched_rate"] <= 0.20
    assert res["order"]["afp_after_early"] is True
    # 匹配对照方向：进展者首偏更早 → 至少一个指标 control_delta < 0
    assert any(v < 0 for v in res["control_delta"].values() if np.isfinite(v))

def test_control_delta_deterministic_fixture():
    """手工 fixture（不依赖随机模拟）：进展者 PLT 于 w2 偏离、对照平缓 → cutoff 被使用、
    control_delta 有限且为负（进展者更早）。"""
    import pandas as pd
    patients = pd.DataFrame([
        {"patient_id": 0, "z": "r1", "age": 60, "sex": "male", "group": "r1_only",
         "confirm_window": 2, "w_r1": 2, "w_a": np.nan, "g": 1, "event_window": 5,
         "censored": False, "censored_window": np.nan, "admin_end": 8, "unobservable": False},
        {"patient_id": 1, "z": "none", "age": 60, "sex": "male", "group": "neither",
         "confirm_window": 2, "w_r1": np.nan, "w_a": np.nan, "g": np.nan, "event_window": np.nan,
         "censored": False, "censored_window": np.nan, "admin_end": 8, "unobservable": False},
    ])
    rows = []
    for pid, plt in ((0, [100, 100, 50, 30, 20, 15, 15, 15, 15]),      # w2 起偏离
                     (1, [100, 100, 100, 100, 100, 100, 100, 100, 100])):  # 对照平缓
        for w, v in enumerate(plt):
            row = {"patient_id": pid, "window": w, "PLT": v}
            for ind in ("ALT", "AST", "GGT", "TBIL", "ALB", "HbA1c", "AFP", "WAIST", "BMI"):
                row[ind] = 50.0
            rows.append(row)
    obs = pd.DataFrame(rows)
    res = lead_lag_analysis(patients, obs)
    # 对照在 cutoff（w5）内无偏离 → 取 cutoff 端点 → control_delta 有限且为负
    assert np.isfinite(res["control_delta"]["PLT"])
    assert res["control_delta"]["PLT"] < 0
