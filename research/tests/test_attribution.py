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

def test_relative_lead_same_for_different_event_windows():
    """相对 lead 对齐（Codex 批次 3 二轮 P1-4）：不同 event_window 但相同相对 lead
    （ev−fd 相同）的进展者 → per_path 中位数相同（绝对窗口混合会被事件时点驱动）。"""
    import pandas as pd
    patients = pd.DataFrame([
        # 患者 0：ev=5、PLT w2 首偏 → lead 3；患者 1：ev=8、PLT w5 首偏 → lead 3（相对相同）
        {"patient_id": 0, "z": "r1", "age": 60, "sex": "male", "group": "r1_only",
         "confirm_window": 2, "w_r1": 2, "w_a": np.nan, "g": 1, "event_window": 5,
         "censored": False, "censored_window": np.nan, "admin_end": 8, "unobservable": False},
        {"patient_id": 1, "z": "r1", "age": 60, "sex": "male", "group": "r1_only",
         "confirm_window": 2, "w_r1": 2, "w_a": np.nan, "g": 1, "event_window": 8,
         "censored": False, "censored_window": np.nan, "admin_end": 8, "unobservable": False},
        # 对照 2 个（平缓）
        {"patient_id": 2, "z": "none", "age": 60, "sex": "male", "group": "neither",
         "confirm_window": 2, "w_r1": np.nan, "w_a": np.nan, "g": np.nan, "event_window": np.nan,
         "censored": False, "censored_window": np.nan, "admin_end": 8, "unobservable": False},
        {"patient_id": 3, "z": "none", "age": 60, "sex": "male", "group": "neither",
         "confirm_window": 2, "w_r1": np.nan, "w_a": np.nan, "g": np.nan, "event_window": np.nan,
         "censored": False, "censored_window": np.nan, "admin_end": 8, "unobservable": False},
    ])
    rows = []
    for pid, plt in ((0, [100, 100, 50, 30, 20, 15, 15, 15, 15]),   # w2 首偏
                     (1, [100, 100, 100, 100, 100, 50, 30, 20, 15]), # w5 首偏
                     (2, [100] * 9), (3, [100] * 9)):                # 对照平缓
        for w, v in enumerate(plt):
            row = {"patient_id": pid, "window": w, "PLT": v}
            for ind in ("ALT", "AST", "GGT", "TBIL", "ALB", "HbA1c", "AFP", "WAIST", "BMI"):
                row[ind] = 50.0
            rows.append(row)
    obs = pd.DataFrame(rows)
    res = lead_lag_analysis(patients, obs)
    # 连续两窗偏离判定下 fd=3/6（绝对不同）→ 相对 lead = ev−fd = 2/2（相同）
    # → per_path r1_only PLT 中位 = 2（绝对窗口混合会被事件时点驱动，相对对齐后一致）
    assert abs(res["per_path"]["r1_only"]["PLT"]["median"] - 2.0) < 1e-9
    # 对照在 cutoff 内无偏离 → 配对差有限（进展者更早 → fd − ctrl < 0）
    assert np.isfinite(res["control_delta"]["PLT"])
    assert res["control_delta"]["PLT"] < 0
    # 接口键
    assert set(res["unmatched_by_group"]) == {"r1_only", "r2_only", "r1_and_r2"}

def test_unmatched_group_gates_and_analysis_set_consistency():
    """路径级 unmatched 门槛 + 分析集一致（Codex 批次 3 三轮 P1-4）：
    某路径组进展者无匹配对照（年龄分箱无对照）→ unmatched_by_group 该组=1.0 →
    max > 20% → not_estimable；非相关路径患者的极端首偏不影响该指标 control_delta。"""
    import pandas as pd
    # r1_only 进展者 age=95（分箱 9，无同箱对照）→ 无匹配；neither 对照 age=60（分箱 6）
    patients = pd.DataFrame([
        {"patient_id": 0, "z": "r1", "age": 95, "sex": "male", "group": "r1_only",
         "confirm_window": 2, "w_r1": 2, "w_a": np.nan, "g": 1, "event_window": 5,
         "censored": False, "censored_window": np.nan, "admin_end": 8, "unobservable": False},
        {"patient_id": 1, "z": "none", "age": 60, "sex": "male", "group": "neither",
         "confirm_window": 2, "w_r1": np.nan, "w_a": np.nan, "g": np.nan, "event_window": np.nan,
         "censored": False, "censored_window": np.nan, "admin_end": 8, "unobservable": False},
    ])
    rows = []
    for pid, plt in ((0, [100, 100, 50, 30, 20, 15, 15, 15, 15]),
                     (1, [100, 100, 100, 100, 100, 100, 100, 100, 100])):
        for w, v in enumerate(plt):
            row = {"patient_id": pid, "window": w, "PLT": v}
            for ind in ("ALT", "AST", "GGT", "TBIL", "ALB", "HbA1c", "AFP", "WAIST", "BMI"):
                row[ind] = 50.0
            rows.append(row)
    obs = pd.DataFrame(rows)
    res = lead_lag_analysis(patients, obs)
    # r1_only 进展者无同箱对照 → unmatched_by_group["r1_only"] == 1.0 → not_estimable
    assert res["unmatched_by_group"]["r1_only"] == 1.0
    assert res["not_estimable"] is True

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
