import numpy as np
import pytest
import config as cfg
from simulate_cohort import simulate, calibrate_gates, p_obs

def test_calibrate_gates_contract():
    cal = calibrate_gates(24, cal_n=30_000)
    assert set(cal) == {"gate", "lambda_base", "neither_risk"}
    assert set(cal["gate"]) == {"r1_only", "r2_only", "r1_and_r2"}

def test_bisection_endpoints_bracket_neither_target():
    from simulate_cohort import _group_latent_risk, _neither_hazard
    target = cfg.CALIBRATION[24]["neither"]
    # 下界：λ_c=0 → 潜在风险 0 < 目标
    assert _neither_hazard(0.0, 40, "female") == 0.0
    out0 = simulate(3000, 60, 24, 3, _lambda_c=0.0)
    assert _group_latent_risk(out0, "neither", 4, obs=out0["obs"]) <= target
    # 上界：λ_c 取扩展上限（calibrate_hi_max，可 >1）→ 潜在风险 > 目标 → 端点真实包围
    out_hi = simulate(3000, 60, 24, 3, _lambda_c=cfg.THRESHOLDS["calibrate_hi_max"])
    assert _group_latent_risk(out_hi, "neither", 4, obs=out_hi["obs"]) > target

def test_bisection_endpoints_bracket_path_groups():
    from simulate_cohort import _group_latent_risk
    grps = ("r1_only", "r2_only", "r1_and_r2")
    gate0 = {g: 0.0 for g in grps}
    gate1 = {g: 1.0 for g in grps}
    for grp in grps:
        target = cfg.CALIBRATION[24][grp]
        out0 = simulate(3000, 60, 24, 3, gate=gate0, _lambda_c=0.0)
        assert _group_latent_risk(out0, grp, 4, obs=out0["obs"]) <= target   # g=0 → 风险 0
        out1 = simulate(3000, 60, 24, 3, gate=gate1, _lambda_c=0.0)
        assert _group_latent_risk(out1, grp, 4, obs=out1["obs"]) >= target   # g=1 → 风险 1

def test_bisect_raises_when_not_bracketed():
    from simulate_cohort import _bisect
    # 风险恒 < 目标（扩展至 calibrate_hi_max 仍不达）→ 显式 ValueError，绝不静默返回伪端点
    with pytest.raises(ValueError):
        _bisect(0.5, lambda x: 0.3)
    # 下界即超目标 → ValueError
    with pytest.raises(ValueError):
        _bisect(0.2, lambda x: 0.8)

def test_calibrated_latent_risk_both_horizons():
    from simulate_cohort import _group_latent_risk
    for horizon, followup in ((24, 60), (12, 36)):
        cal = calibrate_gates(horizon, cal_n=30_000)
        out = simulate(n=30_000, followup_months=followup, horizon_months=horizon,
                       seed=3, gate=cal["gate"], _lambda_c=cal["lambda_base"])
        p = out["patients"]
        for grp, target in out["planted_rules"].calibration.items():
            # 与 calibrate_gates 同一分母逻辑（含 neither 误报排除）
            risk = _group_latent_risk(out, grp, horizon // 6, obs=out["obs"])
            assert abs(risk - target) <= 0.03, (horizon, grp, risk, target)

def test_p_obs_formula():
    out = simulate(n=3000, followup_months=24, horizon_months=12, seed=4)
    po = p_obs(out["patients"], out["obs"], 2)
    for grp in ("r1_only", "r2_only", "r1_and_r2", "neither"):
        assert po[grp]["denominator"] == po[grp]["positive"] + po[grp]["negative"]

def test_coverage_contract_and_gate_reachable():
    # followup=36（admin_end=6）：确认锚点需 >=3 窗信号累积（w_r1 >= w0+3），
    # followup=24（admin_end=4）下 w_r1 ∈ [3, admin_end-hw=2] 为空 → 路径组全
    # no_feasible_anchor → per_rule coverage=0（v5.20 与锚点约束同步的参数修正）
    out = simulate(n=2000, followup_months=36, horizon_months=12, seed=5,
                   gate=calibrate_gates(12, cal_n=10_000)["gate"])
    cov = out["coverage"]
    assert set(cov["per_group"]) == {"r1_only", "r2_only", "r1_and_r2", "neither"}
    assert set(cov["per_rule"]) == {"r1", "r2"}
    for g in ("r1_only", "r2_only", "r1_and_r2", "neither"):
        d = cov["per_group"][g]
        assert set(d) == {"eligible_total", "eligible_observed", "excluded", "coverage"}
        assert d["eligible_total"] == d["eligible_observed"] + d["excluded"]
    # 观测验收（§5.3）由条件成立率测试覆盖（test_conditions_hold_at_confirmation_landmark，
    # 分母 = 可评估患者）；per_group coverage 是描述性统计，**不设高门槛**
    # ——独立删失 20% 客观拉低"组覆盖率"，与"删失不设门槛"一致。
    # §10 规则覆盖率门槛：per_rule coverage（按唯一患者）>= 0.80
    assert cov["per_rule"]["r1"]["coverage"] >= cfg.THRESHOLDS["coverage_gate"]
    assert cov["per_rule"]["r2"]["coverage"] >= cfg.THRESHOLDS["coverage_gate"]
    assert 0 <= cov["neither_false_positive_rate"] <= 1

def test_neither_false_positive_denominator_fixture():
    """手工 fixture 明确区分三类 neither 患者：误报 / 有参考非误报 / 无参考。
    误报率分母 = **全部 neither 候选患者**（3）→ 1/3；
    若分母误用"有合格参考 landmark"（2）会得 1/2——本断言可识别分母写错。"""
    import pandas as pd
    from simulate_cohort import _compute_coverage
    patients = pd.DataFrame({
        "patient_id": [0, 1, 2], "z": ["none"] * 3,
        "age": [55, 30, 30], "sex": ["male", "female", "female"],
        "group": ["neither"] * 3, "confirm_window": [2.0, 2.0, np.nan],
        "w_r1": [np.nan] * 3, "w_a": [np.nan] * 3, "g": [np.nan] * 3,
        "event_window": [np.nan] * 3, "censored": [False, False, True],
        "censored_window": [np.nan, np.nan, 1.0],
        "admin_end": [8, 8, 8], "unobservable": [False] * 3,
        "unobservable_reason": [None] * 3})
    obs = pd.DataFrame([
        # 患者 0：参考 landmark w=2 命中 R1（男>50、HbA1c 连续上升、PLT 降 >20%）→ 误报
        {"patient_id": 0, "window": 0, "HbA1c": 2.0, "PLT": 300.0, "AFP": 1.0},
        {"patient_id": 0, "window": 1, "HbA1c": 2.5, "PLT": 280.0, "AFP": 1.0},
        {"patient_id": 0, "window": 2, "HbA1c": 3.0, "PLT": 230.0, "AFP": 1.0},
        # 患者 1：参考 landmark w=2 未命中（女性、无信号）→ 有参考非误报
        {"patient_id": 1, "window": 0, "HbA1c": 5.0, "PLT": 200.0, "AFP": 1.0},
        {"patient_id": 1, "window": 1, "HbA1c": 5.1, "PLT": 201.0, "AFP": 1.0},
        {"patient_id": 1, "window": 2, "HbA1c": 5.0, "PLT": 200.0, "AFP": 1.0},
    ])
    cov = _compute_coverage(patients, obs, {})
    assert abs(cov["neither_false_positive_rate"] - 1 / 3) < 1e-9
