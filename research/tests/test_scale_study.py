import numpy as np
from scale_study import run_cell, aggregate_cell, reliability_boundary, _meet_halfwidth, _ext_percentile, _cell_feasible, run_study

def test_run_cell_records_full_fields():
    # followup=36（admin_end=6，锚点约束下最小可行）：24 月单元几何不可行 → not_estimable
    # （v5.22 契约，见 test_cell_feasibility_and_not_estimable_unit）
    res = run_cell(n=150, followup_months=36, horizon_months=12, repeats=2, seeds=[1, 2])
    assert res["not_estimable"] is False
    for key in ["nominal_n", "n_events", "oof_events", "excluded_ratio",
                "overall_recovery", "partial_recovery", "excluded_breakdown",
                "unknown_landmark_rows", "model_patients", "model_landmarks",
                "evaluator_patients", "evaluator_landmarks"]:
        assert key in res["records"][0]
    # 角色表核对：模型全量 ⊇ evaluator 可评估（§5.5）
    rec = res["records"][0]
    assert rec["model_patients"] >= rec["evaluator_patients"]
    assert rec["model_landmarks"] >= rec["evaluator_landmarks"]

def test_cell_feasibility_and_not_estimable_unit():
    """几何不可行单元（Codex 二轮 P1-4 执行契约）：24 月/12 视界下 admin_end−hw=2 < 4
    → 路径组无可行确认锚点 → run_cell 显式 not_estimable（records 空、reason 标注），
    不产生 coverage=0 的假"规模退化"；36/60 月正常。"""
    assert not _cell_feasible(24, 12)
    res = run_cell(n=300, followup_months=24, horizon_months=12, repeats=2, seeds=[0, 1])
    assert res["not_estimable"] is True and res["reason"] == "no_feasible_path_anchor"
    assert res["records"] == []
    assert _cell_feasible(36, 12) and _cell_feasible(60, 24)
    res36 = run_cell(n=300, followup_months=36, horizon_months=12, repeats=2, seeds=[0, 1])
    assert res36["not_estimable"] is False and len(res36["records"]) == 2

def test_run_study_excludes_infeasible_unit():
    """run_study 显式过滤 24 月单元（不进聚合/精度统计/可靠性边界），36 月走正常流程
    （Codex 二轮 P1-4）。"""
    out = run_study(grid={"n": [300], "followup_months": [24, 36], "horizon_months": 12},
                    repeats=2)
    cell24 = out["cells"]["n300_f24"]
    assert cell24.get("not_estimable") is True and "overall_mean" not in cell24
    cell36 = out["cells"]["n300_f36"]
    # cell36 是 aggregate_cell 结果（无 not_estimable 键），正常流程断言"有聚合字段、无标记"
    assert "overall_mean" in cell36 and "not_estimable" not in cell36
    # f24：几何不可行 → 边界 not_estimable + reason=no_feasible_cells（run_study 单列）
    b24 = out["reliability_boundaries"]["f24"]
    assert b24.get("status") == "not_estimable" and b24.get("reason") == "no_feasible_cells"
    # f36：正常流程产生边界（样本不足可能 status=not_estimable，但**无 no_feasible_cells reason**）
    b36 = out["reliability_boundaries"]["f36"]
    assert b36.get("reason") != "no_feasible_cells"

def _excluded_fixture():
    import pandas as pd
    return pd.DataFrame({
        "patient_id": [0, 1, 2, 3],
        "unobservable": [True, False, False, False],
        "confirm_window": [2.0, 2.0, 2.0, np.nan],
        "event_window": [4.0, 4.0, 4.0, np.nan],
        "censored_window": [4.0, 4.0, 6.0, np.nan],   # 患者 0/1 同窗(4==4)→unknown；患者 2 正例
        "admin_end": [8, 8, 8, 8],
    })

def test_excluded_sets_mutually_exclusive_with_overlap():
    # 手工患者表（**重叠场景**）：患者 0 unobservable 且其确认窗口同窗 unknown——unobservable
    # 优先、不重复计 unknown；患者 1 unknown（同窗）；患者 2 evaluator；患者 3 no_feasible
    from scale_study import _excluded_patient_sets
    sets = _excluded_patient_sets(_excluded_fixture(), supplied_eval_ids=[2], hw=2)
    assert sets == {"n_unobservable": 1, "n_unknown_patients": 1,
                    "n_no_feasible": 1, "n_evaluator": 1}
    # 闭环由集合互斥保证（非 max 偶然）
    assert sets["n_unobservable"] + sets["n_unknown_patients"] + sets["n_no_feasible"] \
        + sets["n_evaluator"] == 4

def test_excluded_sets_evaluator_overlap_removed():
    # **evaluator ID 重叠**：调用者传入含 unobservable（0）与 unknown（1）患者的 evaluator ID
    # → helper 显式剔除（evaluator_ids = (supplied ∩ 患者全集) − unobs − unknown），只计真正的 evaluator（2）
    from scale_study import _excluded_patient_sets
    sets = _excluded_patient_sets(_excluded_fixture(), supplied_eval_ids=[0, 1, 2], hw=2)
    assert sets == {"n_unobservable": 1, "n_unknown_patients": 1,
                    "n_no_feasible": 1, "n_evaluator": 1}
    assert sets["n_unobservable"] + sets["n_unknown_patients"] + sets["n_no_feasible"] \
        + sets["n_evaluator"] == 4

def test_excluded_sets_ghost_eval_ids_ignored():
    # **外部 ID（幽灵患者）**：supplied 含不存在于患者表的 ID（99）→ evaluator_ids 先 ∩ 患者全集，
    # 幽灵 ID 不计入 n_evaluator、也不减少 no_feasible——四集合闭环仍成立
    from scale_study import _excluded_patient_sets
    sets = _excluded_patient_sets(_excluded_fixture(), supplied_eval_ids=[2, 99], hw=2)
    assert sets == {"n_unobservable": 1, "n_unknown_patients": 1,
                    "n_no_feasible": 1, "n_evaluator": 1}
    assert sets["n_unobservable"] + sets["n_unknown_patients"] + sets["n_no_feasible"] \
        + sets["n_evaluator"] == 4

def test_run_cell_excluded_patient_level_closure():
    """excluded_breakdown 是患者级明细，与 evaluator_patients/excluded_ratio 同一层级核对：
    unobservable + no_feasible_landmark + unknown_patients + evaluator_patients == nominal_n
    （患者级闭环；unknown_patients 来自 confirmation_subset 剔除的 unknown 行——每患者确认
    landmark 一行 → 行级 == 患者级）；qualifying_landmarks 的行级 unknown 单独字段放顶层，
    不参与 breakdown 求和。"""
    # v5.29：followup=36（24 月单元 not_estimable，records 空 → IndexError）
    res = run_cell(n=150, followup_months=36, horizon_months=12, repeats=1, seeds=[1])
    rec = res["records"][0]
    bd = rec["excluded_breakdown"]
    assert set(bd) == {"unobservable", "no_feasible_landmark", "unknown_patients"}
    assert bd["unobservable"] + bd["no_feasible_landmark"] + bd["unknown_patients"] \
        + rec["evaluator_patients"] == rec["nominal_n"]
    assert rec["unknown_landmark_rows"] >= 0
    assert 0 <= rec["excluded_ratio"] <= 1

def test_aggregate_interface():
    results = {"records": [
        {"overall_recovery": 1.0, "r1_recovered": True, "r2_recovered": True, "both_recovered": True},
        {"overall_recovery": 0.0, "r1_recovered": False, "r2_recovered": False, "both_recovered": False},
    ]}
    agg = aggregate_cell(results)
    assert agg["overall_mean"] == 0.5 and agg["both_freq"] == 0.5

def _records(specs, cohorts_per_bin=40):
    """specs: [(n_events, recovery), ...]，每箱 cohorts_per_bin 个独立队列（>= bin_min_cohorts=10，
    且 bootstrap 重采样时该箱极少被剔除，避免 isotonic clip 把网格点压低到 <50%）。"""
    out = []
    for e, r in specs:
        out.extend([{"n_events": e, "overall_recovery": r}] * cohorts_per_bin)
    return out

def _records_var(specs, cohorts_per_bin=40):
    """波动版：specs: [(n_events, mean_recovery, spread)]，箱内 recovery 在 [mean±spread] 线性铺开
    （clip 到 [0,1]），使 Bootstrap 下界明显低于箱均值（用于验证边情形只由 CI 下界曲线判定）。"""
    out = []
    for e, mean, spread in specs:
        vals = np.clip(np.linspace(mean - spread, mean + spread, cohorts_per_bin), 0.0, 1.0)
        out.extend([{"n_events": e, "overall_recovery": float(v)} for v in vals])
    return out

def test_boundary_observed():
    # event_bins=[0,10,20,30,...]；n_events 8/15/25 落入箱 [0,10)/[10,20)/[20,30)。
    # 统一网格 = **箱下界** [0,10,20]；箱均值 0.2@0 / 0.45@10 / 0.95@20（isotonic 保序不变）。
    # 跨 50% 在 grid 10 与 20 之间 → 边界 ≈ 11。point_boundary_events（原始）与
    # boundary_events（CI 下界，箱内全同值 → 2.5% 分位 = 均值）语义单列，本 fixture 下数值可相等。
    b = reliability_boundary(_records([(8, 0.2), (15, 0.45), (25, 0.95)]), followup_months=24)
    assert b["status"] == "observed"
    assert b["point_boundary_events"] is not None
    assert 10 < b["point_boundary_events"] < 20          # 原始曲线边界 ≈ 11（诊断单列）
    assert 10 < b["boundary_events"] < 20                # CI 下界曲线边界（规格主值）
    assert b["boundary_ci"][0] <= b["boundary_events"] <= b["boundary_ci"][1]

def test_boundary_not_estimable_few_bins():
    assert reliability_boundary(_records([(25, 0.9)]), 24)["status"] == "not_estimable"

def test_boundary_not_observed_all_above():
    assert reliability_boundary(_records([(15, 0.6), (25, 0.9)]), 24)["status"] == "not_observed"

def test_boundary_not_estimable_all_below():
    assert reliability_boundary(_records([(8, 0.2), (15, 0.3)]), 24)["status"] == "not_estimable"

def test_ext_percentile_with_inf():
    # 扩展实数分位数（boundary_ci 用，避开 np.percentile 对 inf 数组的不可靠行为）：
    # +inf 视为最大元素；中位 = 有限值；高上分位可达 +inf；空输入 → nan
    vals = [1.0, 2.0, 3.0, float("inf"), float("inf")]
    assert _ext_percentile(vals, 50) == 3.0
    assert np.isinf(_ext_percentile(vals, 97.5))
    assert np.isnan(_ext_percentile([], 50))

def test_ext_percentile_all_inf():
    # **单元级契约**："全 +inf 样本集保留为 (inf, inf)"发生在 _ext_percentile 层
    # （reliability_boundary 的 observed 分支不可达该情形——CI 下界全程达标会提前判 not_observed）
    infs = [float("inf")] * 10
    assert np.isinf(_ext_percentile(infs, 2.5))
    assert np.isinf(_ext_percentile(infs, 50))
    assert np.isinf(_ext_percentile(infs, 97.5))

def test_boundary_point_high_ci_lower_crosses():
    # 原始箱均值 0.55/0.95（低箱 recovery ∈ [0.05,1.05] clip 到 ≤1，seed=0 确定性）全程 ≥50%
    # → _point_boundary 判 "not_observed"（**诊断**）；
    # 但低箱波动大 → Bootstrap **CI 下界曲线**在低事件数箱 <50%（箱均值 2.5% 分位 ≈ 0.47 < 0.5）、
    # 高事件数箱 >50%（≈ 0.93）→ 跨 50% → status=observed。**不得提前用原始点短路**。
    b = reliability_boundary(_records_var([(8, 0.55, 0.5), (25, 0.95, 0.1)]), 24)
    assert b["point_boundary_events"] == "not_observed"   # 原始点达标（诊断）
    assert b["status"] == "observed"                       # CI 下界曲线跨 50% → observed
    assert 0 < b["boundary_events"] < 20                   # 边界在低箱(grid 0)与高箱(grid 20)之间
    # v5.29（Codex 批次 4 一轮 P1-2）：删失方向纠正——大部分 Bootstrap 样本全程 ≥50%
    # → **左删失**（边界 ≤ 最小网格，编码 -inf）；boundary_ci[0] = -inf 是正确的左删失标志
    # （旧实现把 ≥50% 误编码 +inf 会推高 CI）。boundary_ci[1] 有限（跨 50% 样本存在）。
    # boundary_events（CI 下界曲线首达点）与 boundary_ci（每次样本边界值分布）非同一量，
    # 不再断言嵌套包含。
    assert b["boundary_ci"][0] == -float("inf")
    assert np.isfinite(b["boundary_ci"][1])
