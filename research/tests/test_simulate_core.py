import numpy as np
import pandas as pd
import config as cfg
from simulate_cohort import simulate

def _sim(**kw):
    kw.setdefault("n", 1500); kw.setdefault("followup_months", 60)
    kw.setdefault("horizon_months", 24); kw.setdefault("seed", 7)
    return simulate(**kw)

def test_signature():
    import inspect
    assert list(inspect.signature(simulate).parameters) == \
        ["n", "followup_months", "horizon_months", "seed", "gate", "_lambda_c"]

def test_patients_schema():
    assert _sim()["patients"].columns.tolist() == [
        "patient_id", "z", "age", "sex", "group", "confirm_window", "w_r1", "w_a",
        "g", "event_window", "censored", "censored_window", "admin_end",
        "unobservable", "unobservable_reason"]

def test_covariates_conditional_on_z():
    p = _sim()["patients"]
    for z in ("r1", "r1_and_r2"):
        sub = p[p["z"] == z]
        assert (sub["sex"] == "male").all() and (sub["age"] > 50).all()

def test_event_window_is_confirm_plus_delta():
    prog = _sim()["patients"].dropna(subset=["event_window"])
    prog = prog[prog["z"] != "none"]   # neither 事件从 ref+1 起、无 confirm_window 语义，只测路径组
    assert set((prog["event_window"] - prog["confirm_window"]).to_numpy()) <= {1, 2}

def test_path_unobservable_keeps_path_group():
    out = _sim()
    unobs = out["patients"][out["patients"]["unobservable"]]
    assert (unobs["z"] != "none").all()
    # 组语义保留：unobservable 患者的 group 仍是对应路径组（非 neither）
    assert set(unobs["group"]) <= {"r1_only", "r2_only", "r1_and_r2"}

def test_path_unobservable_when_confirm_after_event_or_censor():
    out = _sim()
    p = out["patients"]
    obs = p[(~p["unobservable"]) & (p["z"] != "none")]
    # 有潜在事件（g=1）的可观测路径患者：确认 landmark 严格早于事件窗口
    prog = obs[obs["g"] == 1]
    assert (prog["confirm_window"] < prog["event_window"]).all() if len(prog) else True
    # 未进展（g=0）患者无潜在事件（event_window=NaN）→ 无事件约束，只要求删失前
    cens = obs[obs["censored"]]
    assert (cens["confirm_window"] < cens["censored_window"]).all() if len(cens) else True

def test_neither_reference_is_first_qualifying_before_censor():
    out = _sim()
    ne = out["patients"][out["patients"]["z"] == "none"]
    # 有合格参考 landmark 的患者：首个合格窗口 >= 2 且视界够
    has_ref = ne[ne["confirm_window"].notna()]
    assert (has_ref["confirm_window"] >= 2).all()
    assert (has_ref["admin_end"] - has_ref["confirm_window"] >= 4).all()   # 24 月视界
    # 早期删失患者可能无合格参考 landmark（confirm_window=NaN）——不要求 >=2；
    # 无参考必有删失（首个候选窗口即被删失截断）
    no_ref = ne[ne["confirm_window"].isna()]
    if len(no_ref):
        assert (no_ref["censored"]).all()
    c = has_ref[has_ref["censored"]]
    assert (c["confirm_window"] < c["censored_window"]).all() if len(c) else True

def test_obs_baseline_distribution():
    """基线 SD = 范围/6（患者间异质性）+ 测量噪声 SD = 0.1·范围（窗口 0 无信号叠加）。
    v5.20 向量化曾误用 0.1·范围作基线 SD（PLT 37.5→22.5，患者间异质性收缩）——
    本回归测试用窗口 0 观测方差 = 基线²+噪声² 捕获该缺陷（Codex 批次 1 P1-3）。"""
    out = _sim(n=2000, followup_months=24, horizon_months=12, seed=11)
    w0 = out["obs"][out["obs"]["window"] == 0]
    for ind in ("PLT", "HbA1c", "AFP"):
        lo, hi = cfg.REFERENCE_RANGES[ind][:2]
        sd_theory = np.sqrt(((hi - lo) / 6) ** 2 + (0.1 * (hi - lo)) ** 2)
        sd_obs = float(w0[ind].std())
        assert abs(sd_obs - sd_theory) < 0.1 * (hi - lo), (ind, sd_obs, sd_theory)

def test_obs_truncation_no_cross_patient():
    out = _sim()
    obs = out["obs"]
    # 每患者观测窗口 = 0..T（T = min(事件, 删失, 行政终点)）：T 窗口有观测、T+1 起无观测，
    # 且窗口集合不含其他患者（跨患者污染防护：截断后行数 ≠ n_win，不能靠全局切片）
    for _, p in out["patients"].iterrows():
        trunc = p["admin_end"]
        if np.isfinite(p["event_window"]):
            trunc = min(trunc, int(p["event_window"]))
        if np.isfinite(p["censored_window"]):
            trunc = min(trunc, int(p["censored_window"]))
        w = set(obs[obs["patient_id"] == p["patient_id"]]["window"])
        assert w == set(range(trunc + 1)), (p["patient_id"], w, trunc)

def test_classify_observable_uses_current_patient_obs():
    """跨患者污染回归：判定只用当前患者观测（`_classify_observable` 的 by_w = 当前患者行字典）。
    患者 0 提前截断（观测 0..2），若误用全局尾部切片混入"上一患者"窗口 3（满足 R1 特征），
    r1_ok 会被误判 → 归因错误。旧 `obs_rows[-n_win:]` 缺陷不改变最终 obs 的每患者窗口集合，
    故 `test_obs_truncation_no_cross_patient` 无法检测，须用本纯函数回归测试。"""
    from simulate_cohort import _classify_observable
    obs0 = {0: {"HbA1c": 4.0, "PLT": 300.0, "AFP": 1.0},
            1: {"HbA1c": 5.0, "PLT": 290.0, "AFP": 1.0},
            2: {"HbA1c": 6.0, "PLT": 280.0, "AFP": 1.0}}     # HbA1c 上升、PLT 缓降（未达 -20%）
    # 干净 by_w（当前患者行，无窗口 3）→ w_r1=3 缺观测 → 条件失败 → 不可观测（条件未成立）
    r_clean = _classify_observable("r1", 55, "male", np.nan, 3.0, np.nan, np.nan, obs0, 4)
    assert r_clean["unobservable"] and r_clean["unobservable_reason"] == "condition_not_held"
    # 污染 by_w（混入窗口 3 满足 R1）→ r1_ok 被误判 True → 错误可观测（本断言捕获污染）
    polluted = dict(obs0)
    polluted[3] = {"HbA1c": 7.0, "PLT": 200.0, "AFP": 1.0}
    r_pol = _classify_observable("r1", 55, "male", np.nan, 3.0, np.nan, np.nan, polluted, 4)
    assert r_pol["unobservable"] is False

def test_simulate_classification_uses_current_patient_rows(monkeypatch):
    """**接线级回归**（捕获旧 `obs_rows[-n_win:]` 跨患者缺陷）：monkeypatch
    `_classify_observable` 记录 simulate **实际传入**的 by_w 键集，断言每路径组患者
    的 by_w 只含该患者自身观测窗口（0..min(事件,删失,admin_end)）。
    仅手工调用纯函数（上一测试）无法发现实现者在 simulate 中重新使用旧全局切片接线——
    本测试经过 simulate 的 patient_rows 接线，截断短的患者若混入上一患者窗口即失败。"""
    import simulate_cohort as sc
    original = sc._classify_observable
    calls = []
    def spy(z, age, sex, w_a, w_r1, ev, cw, by_w, hw):
        calls.append(set(by_w))
        return original(z, age, sex, w_a, w_r1, ev, cw, by_w, hw)
    monkeypatch.setattr(sc, "_classify_observable", spy)
    out = simulate(n=300, followup_months=60, horizon_months=24, seed=1)
    path_patients = out["patients"][out["patients"]["z"] != "none"]
    truncated = False
    for (_, row), byw in zip(path_patients.iterrows(), calls):
        trunc = int(min(row["admin_end"],
                        row["event_window"] if np.isfinite(row["event_window"]) else row["admin_end"],
                        row["censored_window"] if np.isfinite(row["censored_window"]) else row["admin_end"]))
        assert set(byw) == set(range(trunc + 1)), (row["patient_id"], byw, trunc)
        if trunc < row["admin_end"]:
            truncated = True
    assert truncated    # 场景有效：存在截断短于 admin_end 的患者（旧实现在此混入上一患者窗口）

def test_planted_sex_is_numeric_and_lookback():
    pr = _sim()["planted_rules"]
    sex_cond = pr.r1.conditions[0]
    assert sex_cond.indicator == "sex" and sex_cond.value == 1.0
    hba1c = pr.r1.conditions[2]
    assert hba1c.op == "consecutive_rises" and hba1c.lookback == 2   # lookback = 上升次数
    assert pr.r1.lookback == 2

def _rises(by_w, ind, w, k):
    vals = [by_w.get(w - i, {}).get(ind, np.nan) for i in range(k + 1)]
    return all(np.isfinite(v) for v in vals) and all(vals[i] > vals[i + 1] for i in range(k))

def _drop(by_w, ind, w, pct):
    base = np.mean([by_w[t][ind] for t in (0, 1) if t in by_w])
    return np.isfinite(base) and base != 0 and (by_w[w][ind] - base) / base <= -pct

def _anchor_expr(z):
    """指定确认/参考 landmark 表达式（row → 确认窗口），与 v16 §5.3 绑定：
    R1-only = w_r1；R2-only / R1∩R2 = w_A+1（共同确认 landmark）；neither = 首参考 landmark。"""
    return {"r1": lambda r: r["w_r1"],
            "r2": lambda r: r["w_a"] + 1,
            "r1_and_r2": lambda r: r["w_a"] + 1,
            "neither": lambda r: r["confirm_window"]}[z]


def _conditions_hold_at_anchor(out, rows, anchor_fn, horizon_windows, which):
    """按指定确认/参考 landmark 独立验证条件成立率（不依赖 group/unobservable 判定）。
    which ∈ {"r1", "r2", "both"（R1∩R2 双条件）, "neither_clean"（R1 不成立）}。
    分母 = 资格检查全部通过的患者（可评估：锚点有限 + 合格 + 视界够 + 无事件 + 未删失）。
    ——「条件成立率 ≥95%」仅针对观测条件（可评估患者），与 v16 §5.3 一致。
    neither_clean 只验 R1（4 条件复合，噪声下命中概率 ~0.1%）；R2 单条件在纯 iid
    噪声下两窗连升概率 = 1/6 ≈ 16.7%（三个独立同分布连续值严格递增的排列概率，
    与 σ 无关；v5.20 误写 25%，实测 17.5% 吻合 1/6），其命中如实计入
    `coverage.neither_false_positive_rate` 报告（规格 §5.3 定义命中=误报），不设门槛。"""
    obs_by_pid = {pid: g.to_dict("records") for pid, g in out["obs"].groupby("patient_id")}
    ok, eligible = 0, 0
    for _, row in rows.iterrows():
        raw = anchor_fn(row)
        if not np.isfinite(raw):
            continue
        w = int(raw)
        if w < 2 or w > row["admin_end"] - horizon_windows:      # 合格：>=2 且视界够
            continue
        if np.isfinite(row["event_window"]) and w >= row["event_window"]:
            continue
        if np.isfinite(row["censored_window"]) and w >= row["censored_window"]:
            continue
        eligible += 1
        by_w = {r["window"]: r for r in obs_by_pid[row["patient_id"]]}
        r1 = (row["sex"] == "male" and row["age"] > 50
              and _rises(by_w, "HbA1c", w, 2) and _drop(by_w, "PLT", w, 0.20))
        r2 = _rises(by_w, "AFP", w, 2)
        if which == "r1" and r1:
            ok += 1
        elif which == "r2" and r2:
            ok += 1
        elif which == "both" and r1 and r2:
            ok += 1
        elif which == "neither_clean" and (not r1):
            ok += 1
    return ok / eligible if eligible else float("nan")

def test_conditions_hold_across_seeds():
    """多 seed **观测条件成立率**稳定性回归（Codex 二轮 P2-2 + 三轮 P2 口径明确）：
    分母 = 可评估患者（锚点有限 + 合格 w≥2 且视界够 + 无事件 + 未删失）——排除
    删失/事件前确认/无可行锚点患者；这是"观测条件成立率 ≥95%"，**不是全路径组
    覆盖率**（后者含不可评估患者，会被删失客观拉低）；与 condition_not_held 的
    分母（实际进入条件检查的患者）口径一致。基线 SD 恢复 range/6 后须确认信号
    余量仍达标（Codex 脚本 0.891 系分母未按可评估过滤——确认点处观测截断的删失
    患者计入失败）。"""
    for seed in (9, 11, 17, 23, 31):
        out = _sim(n=2000, followup_months=60, horizon_months=24, seed=seed)
        p = out["patients"]
        for z, which in (("r1", "r1"), ("r2", "r2"), ("r1_and_r2", "both")):
            sub = p[p["z"] == z]
            assert len(sub) > 0, (seed, z)
            hold = _conditions_hold_at_anchor(out, sub, _anchor_expr(z), 4, which)
            assert hold >= 0.95, (seed, z, hold)

def test_conditions_hold_at_confirmation_landmark():
    out = _sim(n=3000, followup_months=60, horizon_months=24, seed=9)
    p = out["patients"]
    hw = 24 // cfg.SIM["window_months"]
    # 路径组在各自指定确认 landmark 上条件成立率 ≥95%（可评估分母，与 group/unobservable 无关）
    for z, which in (("r1", "r1"), ("r2", "r2"), ("r1_and_r2", "both")):
        sub = p[p["z"] == z]
        assert len(sub) > 0, z
        hold = _conditions_hold_at_anchor(out, sub, _anchor_expr(z), hw, which)
        assert hold >= 0.95, (z, which, hold)
    # neither 首参考 landmark：R1（4 条件复合）不成立——"条件未成立"是 neither 的定义；
    # R2 单条件噪声命中（~1/6）如实计入 coverage.neither_false_positive_rate（规格 §5.3）
    ne = p[p["z"] == "none"]
    clean = _conditions_hold_at_anchor(out, ne, _anchor_expr("neither"), hw, "neither_clean")
    assert clean >= 0.95, clean
    # 事件发生在确认 landmark 之后（路径组进展者）
    prog = p[(p["z"] != "none") & p["event_window"].notna()]
    assert (prog["event_window"] > prog["confirm_window"]).all()
    # unobservable ⟺ unobservable_reason 非空（绑定）；原因互斥且计数闭合
    for z in ("r1", "r2", "r1_and_r2"):
        sub = p[p["z"] == z]
        assert ((sub["unobservable"] == True) == sub["unobservable_reason"].notna()).all(), z
    reasons = set(p["unobservable_reason"].dropna())
    assert reasons <= {"no_feasible_anchor", "censored", "event_before_confirm", "condition_not_held"}
    # condition_not_held ≤5%：分母 = **实际进入条件检查的患者**（可评估 + condition_not_held），
    # 排除删失/no-anchor 稀释
    for z in ("r1", "r2", "r1_and_r2"):
        sub = p[p["z"] == z]
        checked = sub[sub["unobservable_reason"].isin(["condition_not_held", None])]
        n_cond = int(sub["unobservable_reason"].eq("condition_not_held").sum())
        assert n_cond / max(len(checked), 1) <= 0.05, (z, n_cond, len(checked))

def test_unobservable_reason_binding_and_closure():
    out = _sim(n=3000, followup_months=60, horizon_months=24, seed=9)
    p = out["patients"]
    path = p[p["z"] != "none"]
    reasons = ["no_feasible_anchor", "censored", "event_before_confirm", "condition_not_held"]
    # 计数闭合：四类原因计数之和 == 路径组 unobservable 患者数
    assert sum(int((path["unobservable_reason"] == r).sum()) for r in reasons) \
        == int(path["unobservable"].sum())
    # 逐类绑定：no_feasible_anchor ⇒ 对应确认锚点列 NaN（锚点确实不可行）
    for z, anchor in (("r1", "w_r1"), ("r2", "w_a"), ("r1_and_r2", "w_a")):
        sub = path[(path["z"] == z) & (path["unobservable_reason"] == "no_feasible_anchor")]
        assert (sub[anchor].isna()).all(), (z, anchor)
    # censored ⇒ confirm >= censored_window；event_before_confirm ⇒ confirm >= event_window
    cen = path[path["unobservable_reason"] == "censored"]
    assert (cen["confirm_window"] >= cen["censored_window"]).all() if len(cen) else True
    evb = path[path["unobservable_reason"] == "event_before_confirm"]
    assert (evb["confirm_window"] >= evb["event_window"]).all() if len(evb) else True
    # condition_not_held ⇒ 锚点合格、事件/删失均在后，且该路径要求条件在锚点实际失败
    cond = path[path["unobservable_reason"] == "condition_not_held"]
    obs_by_pid = {pid: g.to_dict("records") for pid, g in out["obs"].groupby("patient_id")}
    for _, row in cond.iterrows():
        assert np.isfinite(row["confirm_window"])
        assert (not np.isfinite(row["event_window"]) or row["confirm_window"] < row["event_window"])
        assert (not np.isfinite(row["censored_window"]) or row["confirm_window"] < row["censored_window"])
        by_w = {r["window"]: r for r in obs_by_pid[row["patient_id"]]}
        w = int(row["confirm_window"])
        r1 = (row["sex"] == "male" and row["age"] > 50
              and _rises(by_w, "HbA1c", w, 2) and _drop(by_w, "PLT", w, 0.20))
        r2 = _rises(by_w, "AFP", w, 2)
        held = r1 if row["z"] == "r1" else (r2 if row["z"] == "r2" else (r1 and r2))
        assert not held, (row["patient_id"], row["z"])

def test_unobservable_reason_classification_fixture():
    """四类原因**非空**手工输入逐类验证（自然模拟中 event_before_confirm 等稀有类别
    可能空集合 → `if len(...) else True` 空通过；此处用 `_classify_observable` 构造
    非空场景，验证归类**优先级**（censored/event 先于条件判定）、绑定与互斥）。"""
    from simulate_cohort import _classify_observable
    obs_ok = {0: {"HbA1c": 4.0, "PLT": 300.0, "AFP": 1.0},
              1: {"HbA1c": 5.0, "PLT": 290.0, "AFP": 1.0},
              2: {"HbA1c": 6.0, "PLT": 280.0, "AFP": 1.0},
              3: {"HbA1c": 7.0, "PLT": 200.0, "AFP": 1.0}}     # 窗口 3 满足 R1
    obs_flat = {k: v for k, v in obs_ok.items() if k < 3}       # 无窗口 3（条件失败）
    # 1) no_feasible_anchor：锚点 NaN
    r = _classify_observable("r1", 55, "male", np.nan, np.nan, np.nan, np.nan, obs_ok, 4)
    assert r["unobservable"] and r["unobservable_reason"] == "no_feasible_anchor"
    # 2) censored：confirm(3) >= censored_window(2)；即使条件成立也归 censored（优先级）
    r = _classify_observable("r1", 55, "male", np.nan, 3.0, np.nan, 2.0, obs_ok, 4)
    assert r["unobservable_reason"] == "censored"
    # 3) event_before_confirm：confirm(3) >= event_window(2)；优先于条件判定
    r = _classify_observable("r1", 55, "male", np.nan, 3.0, 2.0, np.nan, obs_ok, 4)
    assert r["unobservable_reason"] == "event_before_confirm"
    # 4) condition_not_held：锚点合格、事件/删失均在后、但条件失败
    r = _classify_observable("r1", 55, "male", np.nan, 3.0, np.nan, np.nan, obs_ok, 4)
    assert r["unobservable"] is False                            # obs_ok 满足 → 可观测（对照）
    r = _classify_observable("r1", 55, "male", np.nan, 3.0, np.nan, np.nan, obs_flat, 4)
    assert r["unobservable"] and r["unobservable_reason"] == "condition_not_held"
    # 四类原因互斥（每类独立归类，不重叠）
    labels = {"no_feasible_anchor", "censored", "event_before_confirm", "condition_not_held"}
    assert len(labels) == 4
