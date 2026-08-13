import numpy as np
import pytest
import config as cfg
from main import run_method_validation
from scale_study import run_cell


@pytest.mark.slow
def test_end_to_end_deterministic_regression():
    res = run_method_validation(seed=7)
    assert res["recovery"]["rule_level_recovery"]["full_hit_count"] == 2
    assert res["lead_lag"]["not_estimable"] is False
    assert res["lead_lag"]["order"]["afp_after_early"] is True


@pytest.mark.acceptance
def test_method_acceptance_monte_carlo():
    k = cfg.THRESHOLDS["method_acceptance_seeds"]
    passes = 0
    for seed in range(k):
        res = run_method_validation(seed=seed)
        if not res.get("signal_gate", True):
            continue                          # 信号门槛未达（AUC CI 下界 <0.65）→ 下游已停止 → 种子不通过
        auc_ok = res["auc_ci"][0] >= cfg.THRESHOLDS["auc_ci_lower_gate"]
        hit_ok = res["recovery"]["rule_level_recovery"]["full_hit_count"] == 2
        rules_nonempty = res["recovery"]["n_rules"] > 0
        ci_ok = res["recovery"]["rule_ci_present"]
        ll = res["lead_lag"]
        # v5.29（Codex 批次 3 五轮 P2-1）：验收读**路径级 unmatched_by_group**
        # （max(有限组)，空组 NaN 忽略）——全局 unmatched_rate 会被其他路径组稀释、
        # 绕过"某具体路径组 >20% unmatched"的失败门槛（规格 §10）
        finite_unmatched = [v for v in ll.get("unmatched_by_group", {}).values() if np.isfinite(v)]
        ll_ok = (not ll["not_estimable"]) and ll["order"]["afp_after_early"] \
                and ll["n_intersection"] >= cfg.THRESHOLDS["r1r2_intersection_min"] \
                and all(n >= cfg.THRESHOLDS["per_indicator_ll_min"] for n in ll["per_indicator_n"].values()) \
                and (not finite_unmatched or max(finite_unmatched) <= cfg.THRESHOLDS["unmatched_max"])
        cov = res["coverage"]
        cov_ok = ("r1" in cov and "r2" in cov                      # 键必须存在（防 get(...,0) 静默缺失）
                  and cov["r1"]["coverage"] >= cfg.THRESHOLDS["coverage_gate"]
                  and cov["r2"]["coverage"] >= cfg.THRESHOLDS["coverage_gate"])
        ci_ok = (rules_nonempty and ci_ok
                 and len(res["rules_ci"]) == res["recovery"]["n_rules"]
                 and all(isinstance(ci, tuple) and len(ci) == 2
                         and np.isfinite(ci[0]) and np.isfinite(ci[1]) and ci[0] <= ci[1]
                         for ci in res["rules_ci"]))
        if auc_ok and hit_ok and rules_nonempty and ci_ok and ll_ok and cov_ok:
            passes += 1
    assert passes / k >= cfg.THRESHOLDS["method_acceptance_pass_rate"]


@pytest.mark.slow
@pytest.mark.parametrize("n,f", [(150, 24), (150, 36), (300, 24), (300, 36)])
def test_realistic_scale_pipeline_runs(n, f):
    res = run_cell(n=n, followup_months=f, horizon_months=12, repeats=2, seeds=[1, 2])
    for rec in res["records"]:
        rl = rec["overall_recovery"]
        assert np.isfinite(rl) and rl in (0.0, 0.5, 1.0)
        # 交叉核对：r1/r2/both 与总体恢复率一致
        n_hit = int(rec["r1_recovered"]) + int(rec["r2_recovered"])
        assert rl == n_hit / 2
        assert rec["both_recovered"] == (n_hit == 2)
        assert rec["evaluator_landmarks"] > 0
        assert rec["evaluator_patients"] <= rec["nominal_n"]
        assert rec["evaluator_landmarks"] >= rec["evaluator_patients"]
        # 角色表（§5.5）：模型全量 ⊇ evaluator 可评估；OOF 事件来自全量模型
        assert rec["model_patients"] >= rec["evaluator_patients"]
        assert rec["model_landmarks"] >= rec["evaluator_landmarks"]
        assert rec["oof_events"] <= rec["model_patients"]
        assert rec["n_events"] >= 0
        assert isinstance(rec["partial_recovery"], dict)


@pytest.mark.slow
def test_reproducible_same_seed_same_report():
    assert run_method_validation(seed=7)["report_md"] == run_method_validation(seed=7)["report_md"]
