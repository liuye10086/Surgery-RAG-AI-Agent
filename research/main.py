"""CLI 编排：simulate→features→model→attribution→rules→evaluate→scale→report。"""
from __future__ import annotations
import argparse, json, os
import numpy as np        # _latent_risk_calibration 有限性检查（np.isfinite）
import config as cfg
from simulate_cohort import simulate, calibrate_gates, p_obs, _group_latent_risk
from features import qualifying_landmarks, confirmation_subset
from model import fit_and_oof, train_model
from attribution import lead_lag_analysis, lag_shap_analysis, lag_ablation_analysis
from rules import mine_rules
from evaluator import evaluate
from scale_study import run_study
from report import render_report

_CAL_CACHE = {}          # v5.29：校准缓存（calibrate_gates(50k) ~100s/次；acceptance 20 种子
                         # 循环 + 重复调用下必须共享，否则仅校准就 >30 分钟）


def _calibrated_for(horizon_months):
    if horizon_months not in _CAL_CACHE:
        _CAL_CACHE[horizon_months] = calibrate_gates(horizon_months, cal_n=cfg.SIM["calibration_n"])
    return _CAL_CACHE[horizon_months]


def _latent_risk_calibration(horizon_months, hw, cal):
    """潜在风险校准（规格 §5.3）：**独立 N=50,000 校准队列**（cal_n = cfg.SIM["calibration_n"]，
    种子 3）上估计四组**潜在真实事件风险**（`_group_latent_risk`，模拟器内部真值 g + 事件窗口，
    不受删失影响），与目标（cfg.CALIBRATION）比较给出误差，并给出 **ok = 四组 actual 均有限
    且 |误差| ≤ 0.03**（±3pp 验收口径；NaN actual/error 比较恒 False，必须显式要求有限值）。"""
    followup = 60 if horizon_months == 24 else 36
    out_cal = simulate(cfg.SIM["calibration_n"], followup, horizon_months, 3,
                       gate=cal["gate"], _lambda_c=cal["lambda_base"])
    targets = cfg.CALIBRATION[horizon_months]
    result = {"targets": {}, "actuals": {}, "errors": {}, "ok": True}
    for grp, target in targets.items():
        actual = _group_latent_risk(out_cal, grp, hw, obs=out_cal["obs"])
        err = float(actual) - target
        result["targets"][grp] = target
        result["actuals"][grp] = float(actual)
        result["errors"][grp] = err
        if not np.isfinite(actual) or abs(err) > 0.03:
            result["ok"] = False
    return result


def run_method_validation(seed=7, out_dir="outputs", scale=None):
    mv = cfg.GRID["method_validation"]
    hw = mv["horizon_months"] // cfg.SIM["window_months"]
    cal = _calibrated_for(mv["horizon_months"])
    out = simulate(n=mv["n"], followup_months=mv["followup_months"],
                   horizon_months=mv["horizon_months"], seed=seed,
                   gate=cal["gate"], _lambda_c=cal["lambda_base"])
    lm = qualifying_landmarks(out["patients"], out["obs"], hw)
    sub = confirmation_subset(out["patients"], out["obs"], hw)
    model_res = fit_and_oof(lm, cfg.THRESHOLDS["cv_folds"], cfg.THRESHOLDS["cv_repeats"],
                            seeds=list(range(seed, seed + cfg.THRESHOLDS["cv_repeats"])))
    calib = _latent_risk_calibration(mv["horizon_months"], hw, cal)
    # **信号门槛门控（规格 §6.3）**：最终平均 OOF 预测上 AUC 患者聚类 95% CI 下界 < 0.65
    # （或 CI 未估计 (nan,nan)）→ 归因与规则挖掘**直接停止并亮红灯**，报告标记失败状态
    auc_lo = model_res["auc_ci"][0]
    auc_gate_ok = np.isfinite(auc_lo) and auc_lo >= cfg.THRESHOLDS["auc_ci_lower_gate"]
    if not auc_gate_ok:
        report_md = render_report({"signal": model_res, "rules": [], "recovery": {},
                                   "timeline": {}, "shap": {}, "ablation": {},
                                   "calibration": calib, "scale": scale or {}, "p_obs": {},
                                   "limitations": ["信号门槛未达：AUC 患者聚类 95% CI 下界 < "
                                                   f"{cfg.THRESHOLDS['auc_ci_lower_gate']}，"
                                                   "归因与规则挖掘已停止（规格 §6.3）"]})
        os.makedirs(out_dir, exist_ok=True)
        with open(f"{out_dir}/report_method_validation.md", "w", encoding="utf-8") as f:
            f.write(report_md)
        return {"signal_gate": False, "auc_ci": model_res["auc_ci"],
                "auc_point": model_res["auc_point"], "calibration": calib,
                "report_md": report_md}
    clf = train_model(lm, seed=seed)
    lag_shap = lag_shap_analysis(lm, clf, cfg.THRESHOLDS["shap_lags"])
    ablation = lag_ablation_analysis(lm, cfg.THRESHOLDS["shap_lags"], seed=seed)
    mined = mine_rules(sub, cfg.THRESHOLDS["cv_repeats"],
                       seeds=list(range(seed, seed + cfg.THRESHOLDS["cv_repeats"])))
    ev = evaluate(mined, out["planted_rules"], sub, out["coverage"])
    ll = lead_lag_analysis(out["patients"], out["obs"])
    po = p_obs(out["patients"], out["obs"], hw)
    report_md = render_report({"signal": model_res, "rules": [r.__dict__ for r in mined["rules"]],
                               "recovery": ev, "timeline": ll, "shap": lag_shap,
                               "ablation": ablation, "calibration": calib,
                               "scale": scale or {}, "p_obs": po, "limitations": []})
    os.makedirs(out_dir, exist_ok=True)
    with open(f"{out_dir}/report_method_validation.md", "w", encoding="utf-8") as f:
        f.write(report_md)
    return {"signal_gate": True, "auc_ci": model_res["auc_ci"], "auc_point": model_res["auc_point"],
            "recovery": ev, "coverage": ev["coverage"], "lead_lag": ll,
            "lag_shap": lag_shap, "lag_ablation": ablation, "p_obs": po,
            "calibration": calib, "report_md": report_md,
            "rules_ci": [r.ci for r in mined["rules"]]}


def _small_scale_study():
    """缩小网格跑一次规模退化（供报告 §7；不覆盖全局配置）。"""
    return run_study(grid={"n": [150], "followup_months": [24], "horizon_months": 12}, repeats=2)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["method-validation", "scale-study", "full"], default="full")
    ap.add_argument("--out", default="outputs")
    args = ap.parse_args(argv)
    if args.mode == "full":
        scale = _small_scale_study()
        run_method_validation(out_dir=args.out, scale=scale)
        os.makedirs(args.out, exist_ok=True)
        with open(f"{args.out}/scale_study.json", "w", encoding="utf-8") as f:
            json.dump(scale, f, ensure_ascii=False, indent=2)
    elif args.mode == "method-validation":
        # 并入缩小规模退化，使报告 §9 第 7 节有内容（不输出"未运行规模退化实验"）
        run_method_validation(out_dir=args.out, scale=_small_scale_study())
    elif args.mode == "scale-study":
        os.makedirs(args.out, exist_ok=True)
        with open(f"{args.out}/scale_study.json", "w", encoding="utf-8") as f:
            json.dump(run_study(), f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
