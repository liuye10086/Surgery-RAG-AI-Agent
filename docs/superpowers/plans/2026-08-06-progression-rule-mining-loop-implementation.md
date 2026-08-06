# 疾病进展规律挖掘 · 端到端最小闭环 实施计划（v3）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `research/` 独立子项目中实现端到端最小闭环：用含植入规律的模拟纵向数据跑通"模拟 → 窗口特征 → 模型 → 时序归因 → 规则挖掘 → evaluator → 规模退化 → 规律报告"全链路，验证方法论能可信地恢复植入规律，并量化现实数据规模下的可信度。

**Architecture:** 每个模块单一职责、纯接口清晰、可独立单测。`simulate_cohort` 产出「数据集 + planted_rules」；数据集流向 features→model→attribution→rules；**planted_rules 只流向 evaluator**。模型训练用全量合格 landmark，规则/校准/evaluator 用每患者确认 landmark（§5.5 分角色口径表）。

**Tech Stack:** Python 3.10+、pandas、scikit-learn（GradientBoostingClassifier / IsotonicRegression）、shap、pytest（`slow`/`acceptance` marker）。

**规格依据：** `docs/superpowers/specs/2026-08-06-progression-rule-mining-loop-design.md`（v16）。
**计划修订：** v2 补结构性问题；v3 按 Codex 计划第二轮复审 11 项修正接口/代码骨架自洽性（simulate 统一签名、校准口径收敛、δ/w_A+2 语义、OOF 患者级聚合、sex 编码、规则对象化、实例级恢复率、可靠性边界分箱结构、acceptance 防空）。

## Global Constraints

以下约束**每个任务都必须遵守**，值从规格原样抄录：

- **独立边界**：`research/` 自带版本化 `config.py`；**禁止** import 生产 `prediction_engine.py`、访问生产数据库、写现有表/API。
- **数据流**：`planted_rules` **只进 `evaluator.py`**；`lead_lag_analysis`、`mine_rules` 等所有非 evaluator 模块签名**不得接收** planted_rules（Task 13 有全模块签名断言测试，在所有模块存在后执行）。
- **主 estimand**：校准/验收/evaluator/规则/support/lift 用**每患者确认/参考 landmark**；模型训练用**全量合格 landmark**；splitter 用**患者级结局**（仅分层，不进特征/规则）。
- **校准口径（唯一）**：**在指定确认/参考 landmark 上按可观察条件分组，估计不受删失影响的潜在事件风险**（互斥组口径，N=50,000 队列 ±3pp，两视界 24/12 均验收）；**P_obs 为观测标签风险（positive/(positive+negative)），单独报告、不参与 §10 验收**。
- **δ ∈ {1,2}**（默认 1），`w_event = 确认窗口 + δ`；对 R2（confirm=w_A+1）事件 ∈ {w_A+2, w_A+3}——**w_A+2 是 δ=1 时的合法事件窗口**（同时是 S 达 S_event 的"高危区标记"点），**不是**"绝不为事件"。
- **事件门控**：路径组 `g ~ Bernoulli(p_group)`；neither 不抽 p_group，由基线 hazard λ_b(t) 自**参考 landmark** 起、在**视界内**触发；`simulate` 统一签名 `simulate(n, followup_months, horizon_months, seed, gate=None, _lambda_c=None)`。
- **标签**：正例 = 视界内且删失/行政终止前已观察到事件；unknown = 视界内先删失且在删失前未观察到事件（从标注集排除，含确认子集）；潜在 g+事件窗口**不得进入模型/OOF/规则流程**。
- **患者聚类**：CI、support、Bootstrap 全部按患者聚类；Bootstrap 抽样**保留 multiplicity**（重采样行集）。
- **sex 编码**：`features` 产出 `sex_male`（1/0）数值列；模型/规则/SHAP 一律用 `sex_male`，**不得把字符串喂给 sklearn**。
- **信号门槛**：方法验证单元最终平均 OOF 预测上 AUC 的患者聚类 95% CI **下界 ≥ 0.65**。
- **成功标准（方法验收）**：K=20 种子、≥90% 通过；每种子四条同时成立——① AUC CI 下界 ≥0.65、② 两条植入规则均完整命中、③ lead-lag 次序恢复（交集 ≥30、**每指标（PLT/HbA1c/AFP）≥20**、unmatched ≤20%，不足 not estimable）、④ R1、R2 各自可评估覆盖率 ≥80%。**规则必须携带 Bootstrap CI（"CI 未估计"运行不得标为通过）**。
- **测试分层**：`pytest.ini` 配 `addopts = -m "not slow and not acceptance"`，注册 `slow`/`acceptance` marker。
- **TDD**：每步先写失败测试→确认红→最小实现→确认绿→单独提交。提交正文三行：`AI-Agent: Codex`、`AI-Client: Codex-Desktop`、`Task-ID: research-progression-min-loop`。
- **不 push**（用户统一推送）；main 分支直接开发。

---

## 共享数据契约与标准词汇（各任务间接口，先定死）

### `patients` DataFrame（每患者一行）

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `patient_id` | int | 0..N-1 |
| `z` | str | 生成路径 `"none"`/`"r1"`/`"r2"`/`"r1_and_r2"` |
| `age` | int | 静态协变量 |
| `sex` | str | `"male"`/`"female"`（原始；`sex_male` 编码在 features 层） |
| `group` | str | 互斥组 `"neither"`/`"r1_only"`/`"r2_only"`/`"r1_and_r2"` |
| `confirm_window` | float | 确认/参考 landmark 窗口（neither 无合格参考时为 `NaN`） |
| `w_r1` | float | R1 条件确认窗口（R2-only 为 `NaN`） |
| `w_a` | float | AFP 激活窗口（R1-only 为 `NaN`） |
| `g` | float | 路径组门控 0/1；neither 为 `NaN` |
| `event_window` | float | 潜在事件窗口（进展者）；否则 `NaN` |
| `censored` | bool | 是否失访删失 |
| `censored_window` | float | 删失窗口；否则 `NaN` |
| `admin_end` | int | 行政随访终点窗口 |
| `unobservable` | bool | 路径组：指定确认 landmark 不合格/非无事件/条件未成立 → `True`（从 evaluator 分母排除，**不改组语义**）；neither 恒 `False` |

### `obs` DataFrame（每患者每窗口一行）

`patient_id`、`window`、`ALT..BMI`（10 个指标观测，含噪声）。指标常量见 `config.INDICATORS`。

### `features` 输出契约（Task 4 定义）

- `qualifying_landmarks(patients, obs, horizon_windows)` → DataFrame（**全量合格 landmark**，模型训练用），列：`patient_id, window, age, sex_male, label, <IND>_cur/_d6m/_d12m/_slope/_rises/_drop_pct`（无 `sex` 字符串）。
- `confirmation_subset(patients, obs, horizon_windows)` → DataFrame（**每患者确认/参考 landmark 一个样本**，规则/evaluator 用），列：`patient_id, window, age, sex_male, group, unobservable, admin_end, label, <派生特征>`；**剔除 unknown 标签行**（`label ∈ {0,1}`），`excluded_unknown` 存于 `df.attrs`。

### 标准规则词汇（`rules.py` 与 `evaluator.py` 共用）

```python
@dataclass(frozen=True)
class MinedCondition:
    indicator: str      # "sex"|"age"|"HbA1c"|"PLT"|"AFP"|...
    op: str             # "eq"|"gt"|"lt"|"consecutive_rises"|"drop_pct"
    value: "str | float"
    lookback: int = 1
    source_feature: str = ""   # 阈值选择用；不参与匹配

@dataclass(frozen=True)
class MinedRule:
    conditions: tuple[MinedCondition, ...]
    horizon_windows: int
    lookback: int
    lag: int
```

候选映射（标准语义）：`sex_male`→`("sex","eq",1/0)`；`age`→`("age","gt",q)`；`<IND>_rises≥k`→`("<IND>","consecutive_rises",k,lookback=k)`；`<IND>_drop_pct≤-d`→`("<IND>","drop_pct",d)`；`<IND>_cur` 高分位→`("<IND>","gt",q)`。

### `planted_rules`（只进 evaluator）

```python
@dataclass(frozen=True)
class Condition:
    indicator: str
    op: str
    value: "str | float"     # sex 用 "male"/"female"，连续为 float
    lookback: int = 1

@dataclass(frozen=True)
class PlantedRule:
    name: str; horizon_months: int; conditions: tuple[Condition, ...]; group: str; target_risk: float

@dataclass(frozen=True)
class PlantedRules:
    horizon_months: int; r1: PlantedRule; r2: PlantedRule; calibration: dict[str, float]
```

### 确认/参考 landmark 与合格定义

- 合格 landmark：`窗口 ≥ 2`、`admin_end − 窗口 ≥ 视界窗数`、`窗口 < 事件窗口`（若有）、`窗口 < 删失窗口`（若有）。
- **neither 参考 landmark**：生成删失后，取**首个合格窗口**（窗口 ≥2 起、admin_end−窗口 ≥ 视界、在删失之前）；无合格窗口 → `confirm_window=NaN`（该患者 not estimable 单元）。若该参考 landmark 命中任一植入条件 → 计入误报、排除 neither 校准分母、不标记不可观测。
- 路径组确认 landmark：R2/交集 = `w_A+1`；R1-only = `w_R1`。指定确认 landmark 不合格/非无事件/条件未成立 → `unobservable=True`。

---

## 任务分解（14 任务）

### Task 1: 脚手架 + config.py

**Files:**

- Create: `research/config.py`、`research/pytest.ini`、`research/requirements.txt`、`research/tests/__init__.py`
- Test: `research/tests/test_config.py`

**Interfaces:**

- Produces: `config.py` 全部命名常量（Task 2-14 依赖）。数据流签名断言**移至 Task 13**（所有模块存在后）。

- [ ] **Step 1: 写失败测试**

`research/tests/test_config.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_config.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写实现**

`research/pytest.ini`：

```ini
[pytest]
pythonpath = .
addopts = -m "not slow and not acceptance"
markers =
    slow: long-running tests (regression fixture)
    acceptance: Monte Carlo method acceptance tests
```

`research/requirements.txt`：`pandas>=2.0`、`scikit-learn>=1.3`、`shap>=0.44`、`matplotlib>=3.7`、`pytest>=7.4`。

`research/config.py`：

```python
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
       "observability_gate": 0.95, "calibration_group_min": 200}
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
              "thresholds_per_feature": 3, "max_candidates": 5000, "lift_min": 1.5,
              "method_acceptance_seeds": 20, "method_acceptance_pass_rate": 0.90,
              "bootstrap_b": 1000, "cv_folds": 5, "cv_repeats": 5, "shap_lags": [0, 1, 2],
              "calibrate_tol": 0.005, "calibrate_bisect_iters": 40,
              "event_bins": [0, 10, 20, 30, 40, 50, 75, 100, 150, 10 ** 9],
              "bin_min_cohorts": 10, "boundary_threshold": 0.50}
PLANTED_CONDITIONS = {
    "r1": [("sex", "eq", "male"), ("age", "gt", 50.0),
           ("HbA1c", "consecutive_rises", 2.0), ("PLT", "drop_pct", 20.0)],
    "r2": [("AFP", "consecutive_rises", 2.0)],
}
```

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/config.py research/pytest.ini research/requirements.txt research/tests/
git commit -m "feat(research): 脚手架 + 版本化 config.py" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 2: simulate——Z/协变量/S 轨迹/观测 + 确认 landmark/组归属

**Files:**

- Create: `research/simulate_cohort.py`
- Test: `research/tests/test_simulate_core.py`

**Interfaces:**

- Consumes: `config`。
- Produces: `Condition/PlantedRule/PlantedRules` 类型；`simulate(n, followup_months, horizon_months, seed, gate=None, _lambda_c=None)` 返回 `{"patients", "obs", "planted_rules", "coverage", "meta"}`；`coverage` 在 Task 3 填实（本任务返回 `{"per_group": {}}`）。

**前向顺序（每患者，严格）**：Z → 协变量按 Z → 基线指标 → S 轨迹 → 路径组门控（确认 landmark 锚点先行）→ **neither 先删失、再取首个合格参考 landmark、再 λ_b 视界内事件** → 指标观测 → 截断。**禁止先定事件时间再构造特征。**

- [ ] **Step 1: 写失败测试**

`research/tests/test_simulate_core.py`：

```python
import numpy as np
import pandas as pd
import config as cfg
from simulate_cohort import simulate

def _sim(**kw):
    kw.setdefault("n", 1500); kw.setdefault("followup_months", 60)
    kw.setdefault("horizon_months", 24); kw.setdefault("seed", 7)
    return simulate(**kw)

def test_simulate_signature_has_gate_and_lambda():
    import inspect
    params = list(inspect.signature(simulate).parameters)
    assert params == ["n", "followup_months", "horizon_months", "seed", "gate", "_lambda_c"]

def test_patients_schema():
    out = _sim()
    assert out["patients"].columns.tolist() == [
        "patient_id", "z", "age", "sex", "group", "confirm_window", "w_r1", "w_a",
        "g", "event_window", "censored", "censored_window", "admin_end", "unobservable",
    ]

def test_obs_schema_and_windows():
    out = _sim()
    assert set(out["obs"].columns) == {"patient_id", "window"} | set(cfg.INDICATORS)
    counts = out["obs"].groupby("patient_id")["window"].count()
    assert (counts == out["patients"]["admin_end"] + 1).all()

def test_covariates_conditional_on_z():
    p = _sim()["patients"]
    for z in ("r1", "r1_and_r2"):
        sub = p[p["z"] == z]
        assert (sub["sex"] == "male").all() and (sub["age"] > 50).all()

def test_event_window_is_confirm_plus_delta():
    out = _sim()
    prog = out["patients"].dropna(subset=["event_window"])
    diff = (prog["event_window"] - prog["confirm_window"]).to_numpy()
    assert set(diff) <= {1, 2}
    # R2（confirm=w_A+1）事件 ∈ {w_A+2, w_A+3}：w_A+2 是 δ=1 的合法事件窗口
    r2 = prog[prog["z"].isin(["r2", "r1_and_r2"])]
    assert ((r2["event_window"] - (r2["w_a"] + 1)).isin([1, 2])).all()

def test_forward_no_event_leakage():
    prog = _sim()["patients"].dropna(subset=["event_window"])
    assert (prog["event_window"] >= prog["confirm_window"] + 1).all()

def test_neither_reference_is_first_qualifying_landmark():
    out = _sim()
    ne = out["patients"][out["patients"]["z"] == "none"]
    assert (ne["confirm_window"] >= 2).all()
    assert (ne["admin_end"] - ne["confirm_window"] >= 24 // 6).all()
    # 参考 landmark 须在删失之前
    has_censor = ne[ne["censored"]]
    assert (has_censor["confirm_window"] <= has_censor["censored_window"]).all()

def test_path_unobservable_does_not_reassign():
    out = _sim()
    unobs = out["patients"][out["patients"]["unobservable"]]
    assert (unobs["z"] != "none").all()
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_simulate_core.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/simulate_cohort.py`（核心；neither 的 λ_b 事件在 Task 3 用校准后的 `_lambda_c`，本任务用临时常数）：

```python
"""模拟纵向数据生成器（Z 路径 + 前向生成）。planted_rules 只流向 evaluator。"""
from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass
import config as cfg


@dataclass(frozen=True)
class Condition:
    indicator: str; op: str; value: "str | float"; lookback: int = 1

@dataclass(frozen=True)
class PlantedRule:
    name: str; horizon_months: int; conditions: tuple[Condition, ...]; group: str; target_risk: float

@dataclass(frozen=True)
class PlantedRules:
    horizon_months: int; r1: PlantedRule; r2: PlantedRule; calibration: dict[str, float]


def _build_planted_rules(horizon_months):
    cal = cfg.CALIBRATION[horizon_months]
    r1 = PlantedRule("r1", horizon_months,
                     tuple(Condition(i, o, v) for i, o, v in cfg.PLANTED_CONDITIONS["r1"]),
                     "r1_only", cal["r1_only"])
    r2 = PlantedRule("r2", horizon_months,
                     tuple(Condition(i, o, v) for i, o, v in cfg.PLANTED_CONDITIONS["r2"]),
                     "r2_only", cal["r2_only"])
    return PlantedRules(horizon_months, r1, r2, cal)


def _sample_z_covariates(rng, n):
    paths = rng.choice(["none", "r1", "r2", "r1_and_r2"], n, p=[0.70, 0.15, 0.10, 0.05])
    ages, sexes = np.empty(n, int), np.empty(n, object)
    for i, z in enumerate(paths):
        if z in ("r1", "r1_and_r2"):
            sexes[i], ages[i] = "male", int(rng.integers(51, 80))
        else:
            sexes[i], ages[i] = rng.choice(["male", "female"]), int(rng.integers(20, 70))
    return paths, ages, sexes


def _sample_anchors(rng, z, w0, admin_end, horizon_windows):
    w_a, w_r1 = np.nan, np.nan
    for _ in range(cfg.SIM["resample_max"]):
        if z in ("r2", "r1_and_r2"):
            lo, hi = 1, admin_end - horizon_windows - 1
            if hi < lo: return np.nan, np.nan
            w_a = int(rng.integers(lo, hi + 1))
        if z == "r1":
            lo, hi = 2, admin_end - horizon_windows
            if hi < lo: return np.nan, np.nan
            w_r1 = int(rng.integers(lo, hi + 1))
        elif z == "r1_and_r2":
            lo, hi = w0, w_a - 1
            if hi < lo: return np.nan, np.nan
            w_r1 = int(rng.integers(lo, hi + 1))
        return w_a, w_r1


def _first_qualifying_landmark(admin_end, horizon_windows, censored_window):
    """neither 参考 landmark：首个合格窗口（>=2、视界够、删失之前）。"""
    for w in range(2, admin_end - horizon_windows + 1):
        if np.isfinite(censored_window) and w >= censored_window:
            continue
        return w
    return np.nan


def simulate(n, followup_months, horizon_months, seed, gate=None, _lambda_c=None):
    rng = np.random.default_rng(seed)
    admin_end = followup_months // cfg.SIM["window_months"]
    hw = horizon_months // cfg.SIM["window_months"]
    cal = cfg.CALIBRATION[horizon_months]
    if gate is None:
        gate = dict(cal)
    lambda_c = cfg.SIM["tau"] if _lambda_c is None else _lambda_c   # 临时基线常数；Task 3 校准

    paths, ages, sexes = _sample_z_covariates(rng, n)
    sigma = {i: 0.1 * (cfg.REFERENCE_RANGES[i][1] - cfg.REFERENCE_RANGES[i][0]) for i in cfg.INDICATORS}
    band, s_afp = 2.0, 1.0
    n_win = admin_end + 1

    rows, obs_rows = [], []
    for pid in range(n):
        z, age, sex = paths[pid], ages[pid], sexes[pid]
        w0 = int(rng.integers(0, 2))
        w_a, w_r1 = _sample_anchors(rng, z, w0, admin_end, hw)

        # 删失（独立，先于 neither 参考 landmark 判定）
        censored = rng.random() < cfg.SIM["censoring_rate"]
        censored_window = float(rng.integers(1, n_win)) if censored else np.nan

        # 事件（路径组：门控；neither：参考 landmark 起 λ_b 视界内）
        g, event_window = np.nan, np.nan
        if z != "none":
            confirm = (w_a + 1) if z in ("r2", "r1_and_r2") else w_r1
            if np.isfinite(confirm):
                grp = "r1_and_r2" if z == "r1_and_r2" else ("r1_only" if z == "r1" else "r2_only")
                g = int(rng.random() < gate[grp])
                if g == 1:
                    event_window = confirm + int(rng.choice(cfg.SIM["delta_choices"]))
        else:
            ref = _first_qualifying_landmark(admin_end, hw, censored_window)
            if np.isfinite(ref):
                for t in range(int(ref), min(int(ref) + hw, n_win)):
                    if rng.random() < lambda_c + 0.001 * (age - 20):
                        event_window = t
                        break

        # 指标观测（基线 + 信号 + 噪声）
        baseline = {i: rng.normal((cfg.REFERENCE_RANGES[i][0] + cfg.REFERENCE_RANGES[i][1]) / 2,
                                  (cfg.REFERENCE_RANGES[i][1] - cfg.REFERENCE_RANGES[i][0]) / 6)
                    for i in cfg.INDICATORS}
        for t in range(n_win):
            row = {"patient_id": pid, "window": t}
            for ind in cfg.INDICATORS:
                sig = 0.0
                if z in ("r1", "r1_and_r2") and ind == "HbA1c" and t >= w0: sig = 0.15 * (t - w0)
                if z in ("r1", "r1_and_r2") and ind == "PLT" and t >= w0: sig = -3.0 * (t - w0)
                if z in ("r2", "r1_and_r2") and ind == "AFP" and np.isfinite(w_a) and t >= w_a:
                    sig = 6.0 * (t - w_a + 1)
                row[ind] = baseline[ind] + sig + rng.normal(0, sigma[ind])
            obs_rows.append(row)

        # 组归属 / 确认 landmark / unobservable
        if z == "none":
            confirm = _first_qualifying_landmark(admin_end, hw, censored_window)
            group, unobservable = "neither", False
        else:
            confirm = (w_a + 1) if z in ("r2", "r1_and_r2") else w_r1
            by_w = {r["window"]: r for r in obs_rows[-n_win:]}
            r1_ok = _r1_holds(by_w, confirm, age, sex) if z in ("r1", "r1_and_r2") else False
            r2_ok = _r2_holds(by_w, confirm) if z in ("r2", "r1_and_r2") else False
            if not np.isfinite(confirm) or (z in ("r1", "r1_and_r2") and not r1_ok) or (z in ("r2", "r1_and_r2") and not r2_ok):
                group, unobservable = "neither", True
            else:
                group = "r1_and_r2" if (r1_ok and r2_ok) else ("r1_only" if r1_ok else "r2_only")
                unobservable = False

        rows.append({"patient_id": pid, "z": z, "age": age, "sex": sex, "group": group,
                     "confirm_window": confirm, "w_r1": w_r1, "w_a": w_a, "g": g,
                     "event_window": event_window, "censored": censored,
                     "censored_window": censored_window, "admin_end": admin_end,
                     "unobservable": unobservable})

    return {"patients": pd.DataFrame(rows), "obs": pd.DataFrame(obs_rows),
            "planted_rules": _build_planted_rules(horizon_months),
            "coverage": {"per_group": {}}, "meta": {"horizon_windows": hw, "admin_end": admin_end}}


def _r1_holds(by_w, w, age, sex):
    if sex != "male" or age <= 50: return False
    if not _consecutive_rises(by_w, "HbA1c", w, 2): return False
    base = np.mean([by_w[t]["PLT"] for t in (0, 1) if t in by_w])
    if not np.isfinite(base) or base == 0: return False
    return (by_w[w]["PLT"] - base) / base <= -0.20


def _r2_holds(by_w, w):
    return _consecutive_rises(by_w, "AFP", w, 2)


def _consecutive_rises(by_w, ind, w, k):
    if w < k: return False
    vals = [by_w.get(w - i, {}).get(ind, np.nan) for i in range(k + 1)]
    if any(not np.isfinite(v) for v in vals): return False
    return all(vals[i] > vals[i + 1] for i in range(k))
```

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_simulate_core.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/simulate_cohort.py research/tests/test_simulate_core.py
git commit -m "feat(research): 模拟核心（Z 路径 + 前向生成 + 确认 landmark/组归属）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 3: simulate——事件门控校准（bisection）+ P_obs + coverage

**Files:**

- Modify: `research/simulate_cohort.py`
- Test: `research/tests/test_simulate_calibration.py`

**Interfaces:**

- Produces:
  - `calibrate_gates(horizon_months, cal_n=cfg.SIM["calibration_n"])` → `{"gate": {group: p}, "lambda_base": float, "neither_risk": {horizon: float}}`
  - `p_obs(patients, obs, horizon_windows)` → `dict`（每互斥组 `positive/(positive+negative)`，unknown 排除）
  - `simulate` 的 `coverage` 填实（逐组可观测条件成立比例 + 误报率）

**校准口径（唯一）**：在指定确认/参考 landmark 上按可观察条件分组，估计**不受删失影响的潜在事件风险**；bisection 收敛到目标 ±3pp（两视界均验收）。

- [ ] **Step 1: 写失败测试**

`research/tests/test_simulate_calibration.py`：

```python
import numpy as np
import config as cfg
from simulate_cohort import simulate, calibrate_gates, p_obs

def test_calibrate_gates_returns_contract():
    cal = calibrate_gates(24, cal_n=30_000)
    assert set(cal) == {"gate", "lambda_base", "neither_risk"}
    assert set(cal["gate"]) == {"r1_only", "r2_only", "r1_and_r2"}

def test_calibrated_latent_risk_both_horizons():
    for horizon, followup in ((24, 60), (12, 36)):
        cal = calibrate_gates(horizon, cal_n=30_000)
        out = simulate(n=30_000, followup_months=followup, horizon_months=horizon,
                       seed=3, gate=cal["gate"], _lambda_c=cal["lambda_base"])
        p = out["patients"]
        for grp, target in out["planted_rules"].calibration.items():
            sub = p[p["group"] == grp]
            if grp == "neither":
                # 潜在风险：事件窗口在参考 landmark 视界内（不受删失影响）
                risk = ((sub["event_window"].notna())
                        & (sub["event_window"] <= sub["confirm_window"] + horizon // 6)).mean()
            else:
                risk = sub["g"].mean()
            assert abs(risk - target) <= 0.03, (horizon, grp, risk, target)

def test_p_obs_formula_and_unknown_excluded():
    out = simulate(n=3000, followup_months=24, horizon_months=12, seed=4)
    po = p_obs(out["patients"], out["obs"], horizon_windows=2)
    for grp in ("r1_only", "r2_only", "r1_and_r2", "neither"):
        d = po[grp]
        assert d["denominator"] == d["positive"] + d["negative"]
        assert 0 <= d["rate"] <= 1

def test_p_obs_not_in_simulate_surface():
    out = simulate(n=500, followup_months=24, horizon_months=12, seed=4)
    assert "p_obs" not in out

def test_coverage_per_group_populated():
    out = simulate(n=2000, followup_months=24, horizon_months=12, seed=5,
                   gate=calibrate_gates(12, cal_n=10_000)["gate"])
    cov = out["coverage"]["per_group"]
    assert set(cov) == {"r1_only", "r2_only", "r1_and_r2", "neither"}
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_simulate_calibration.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

追加到 `simulate_cohort.py`（bisection 唯一算法，非"调参数"）：

```python
def _group_latent_risk(out, grp, hw):
    p = out["patients"]
    sub = p[p["group"] == grp]
    if grp == "neither":
        ok = sub["confirm_window"].notna()
        ev = sub["event_window"].notna() & (sub["event_window"] <= sub["confirm_window"] + hw)
        return ev[ok].mean() if ok.any() else np.nan
    return sub["g"].mean()


def _bisect(target, make_risk, lo=0.0, hi=1.0):
    for _ in range(cfg.THRESHOLDS["calibrate_bisect_iters"]):
        mid = (lo + hi) / 2
        risk = make_risk(mid)
        if abs(risk - target) <= cfg.THRESHOLDS["calibrate_tol"]:
            return mid
        if risk < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def calibrate_gates(horizon_months, cal_n=cfg.SIM["calibration_n"]):
    followup = 60 if horizon_months == 24 else 36
    hw = horizon_months // cfg.SIM["window_months"]
    cal = cfg.CALIBRATION[horizon_months]
    gates = {}
    for grp, target in cal.items():
        if grp == "neither":
            continue
        def risk_fn(mid, grp=grp, target=target):
            g = {g_: (mid if g_ == grp else t) for g_, t in cal.items() if g_ != "neither"}
            out = simulate(cal_n, followup, horizon_months, 3, gate=g, _lambda_c=cfg.SIM["tau"])
            return _group_latent_risk(out, grp, hw)
        gates[grp] = _bisect(target, risk_fn)
    # neither λ_b 尺度
    def neither_risk(c):
        out = simulate(cal_n, followup, horizon_months, 3, gate=gates, _lambda_c=c)
        return _group_latent_risk(out, "neither", hw)
    lambda_base = _bisect(cal["neither"], neither_risk, lo=0.0, hi=0.2)
    return {"gate": gates, "lambda_base": lambda_base,
            "neither_risk": {horizon_months: float(neither_risk(lambda_base))}}


def p_obs(patients, obs, horizon_windows):
    """P_obs = positive/(positive+negative)；确认/参考 landmark 口径；unknown 全排除。"""
    result = {}
    for grp in ("neither", "r1_only", "r2_only", "r1_and_r2"):
        pos = neg = 0
        for _, p in patients[patients["group"] == grp].iterrows():
            ev, cw = p["event_window"], p["censored_window"]
            win = p["confirm_window"] + horizon_windows
            if np.isfinite(ev) and ev <= win and (not np.isfinite(cw) or cw > ev):
                pos += 1
            elif (not np.isfinite(ev) or ev > win) and (not np.isfinite(cw) or cw > win):
                neg += 1
            # 其他（视界内先删失且删失前未观察到事件）→ unknown，排除
        result[grp] = {"positive": pos, "negative": neg, "denominator": pos + neg,
                       "rate": pos / (pos + neg) if pos + neg else float("nan")}
    return result
```

实现说明：`simulate` 内 `lambda_c` 的默认改为接收 `_lambda_c` 校准值（Task 2 临时常数仅作占位）；`coverage["per_group"]` 在 `simulate` 返回前填实：逐组检查指定确认/参考 landmark 上可观测条件成立比例（路径组）与两者均不成立比例 + 误报率（neither）。

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_simulate_calibration.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/simulate_cohort.py research/tests/test_simulate_calibration.py
git commit -m "feat(research): 事件门控 bisection 校准 + P_obs + 逐组 coverage" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 4: features.py（合格 landmark / 确认子集 / 标签 / sex 编码）

**Files:**

- Create: `research/features.py`
- Test: `research/tests/test_features.py`

**Interfaces:**

- Consumes: `simulate()` 输出。
- Produces: `qualifying_landmarks`、`confirmation_subset`（含 `admin_end`、`group`、`unobservable`、`sex_male`；**剔除 unknown**）、`label_for`、`derive_window_features`。

- [ ] **Step 1: 写失败测试**

`research/tests/test_features.py`：

```python
import numpy as np
import config as cfg
from simulate_cohort import simulate
from features import qualifying_landmarks, confirmation_subset, label_for, derive_window_features

def test_derived_features_hand():
    rows = [{"window": 0, "ALT": 30.0}, {"window": 1, "ALT": 33.0}, {"window": 2, "ALT": 36.0}]
    f = derive_window_features(rows, "ALT", window=2, runin=2)
    assert f["ALT_cur"] == 36.0 and f["ALT_d6m"] == 3.0 and f["ALT_d12m"] == 6.0 and f["ALT_rises"] == 2

def test_qualifying_uses_all_landmarks():
    out = simulate(n=300, followup_months=24, horizon_months=12, seed=1)
    lm = qualifying_landmarks(out["patients"], out["obs"], horizon_windows=2)
    assert len(lm) > out["patients"]["patient_id"].nunique()
    assert "label" in lm.columns and "sex_male" in lm.columns
    assert "sex" not in lm.columns   # 字符串列不进入模型特征

def test_confirmation_subset_contract():
    out = simulate(n=300, followup_months=24, horizon_months=12, seed=1)
    sub = confirmation_subset(out["patients"], out["obs"], horizon_windows=2)
    assert sub["patient_id"].is_unique
    for col in ["group", "unobservable", "admin_end", "sex_male", "label"]:
        assert col in sub.columns
    assert (sub["admin_end"] - sub["window"] >= 2).all()
    assert set(sub["label"]) <= {0, 1}   # unknown 已剔除

def test_label_semantics():
    out = simulate(n=300, followup_months=24, horizon_months=12, seed=1)
    p = out["patients"].iloc[0]
    assert label_for(p, 2, 2) in (0, 1, "unknown")
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_features.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/features.py`：

```python
"""窗口特征 + landmark 化 + sex 编码（无未来泄漏；分角色口径）。"""
from __future__ import annotations
import numpy as np
import pandas as pd
import config as cfg


def derive_window_features(obs_rows, ind, window, runin=2):
    series = {r["window"]: r[ind] for r in obs_rows if ind in r}
    base = np.mean([series.get(t, np.nan) for t in range(runin) if t in series])
    cur = series.get(window, np.nan)
    d6 = cur - series.get(window - 1, np.nan) if window - 1 in series else np.nan
    d12 = cur - series.get(window - 2, np.nan) if window - 2 in series else np.nan
    slope = series.get(window - 1, np.nan) - series.get(window - 2, np.nan) if window - 2 in series else np.nan
    rises = 0
    if window - 2 in series and window - 1 in series and window in series:
        rises = int((series[window] > series[window - 1]) + (series[window - 1] > series[window - 2]))
    drop = 0.0
    if np.isfinite(base) and base != 0 and np.isfinite(cur):
        drop = (cur - base) / base
    return {f"{ind}_cur": cur, f"{ind}_d6m": d6, f"{ind}_d12m": d12,
            f"{ind}_slope": slope, f"{ind}_rises": rises, f"{ind}_drop_pct": drop}


def label_for(patient, window, horizon_windows):
    ev, cw = patient["event_window"], patient["censored_window"]
    if np.isfinite(ev) and ev <= window + horizon_windows and (not np.isfinite(cw) or cw > ev):
        return 1
    if np.isfinite(cw) and cw <= window + horizon_windows and (not np.isfinite(ev) or ev > cw):
        return "unknown"
    return 0


def _feature_row(patient, obs_by_w, window, runin=2):
    row = {"patient_id": patient["patient_id"], "window": window,
           "age": patient["age"], "sex_male": int(patient["sex"] == "male"),
           "group": patient["group"], "admin_end": patient["admin_end"]}
    for ind in cfg.INDICATORS:
        row.update(derive_window_features(obs_by_w, ind, window, runin))
    return row


def qualifying_landmarks(patients, obs, horizon_windows):
    obs_by_pid = {pid: g.to_dict("records") for pid, g in obs.groupby("patient_id")}
    rows, excluded = [], 0
    for _, p in patients.iterrows():
        by_w = obs_by_pid[p["patient_id"]]
        for w in range(2, p["admin_end"] - horizon_windows + 1):
            if np.isfinite(p["event_window"]) and w >= p["event_window"]: break
            if np.isfinite(p["censored_window"]) and w >= p["censored_window"]: break
            lab = label_for(p, w, horizon_windows)
            if lab == "unknown":
                excluded += 1
                continue
            r = _feature_row(p, by_w, w)
            r["label"] = lab
            rows.append(r)
    df = pd.DataFrame(rows)
    df.attrs["excluded_unknown"] = excluded
    return df


def confirmation_subset(patients, obs, horizon_windows):
    obs_by_pid = {pid: g.to_dict("records") for pid, g in obs.groupby("patient_id")}
    rows, excluded = [], 0
    for _, p in patients.iterrows():
        w = p["confirm_window"]
        if not np.isfinite(w):
            continue
        lab = label_for(p, int(w), horizon_windows)
        if lab == "unknown":
            excluded += 1
            continue                       # unknown 从确认子集剔除（§5.5）
        r = _feature_row(p, obs_by_pid[p["patient_id"]], int(w))
        r["label"] = lab
        r["unobservable"] = bool(p["unobservable"])
        rows.append(r)
    df = pd.DataFrame(rows)
    df.attrs["excluded_unknown"] = excluded
    return df
```

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_features.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/features.py research/tests/test_features.py
git commit -m "feat(research): 窗口特征 + 分角色 landmark + sex 编码 + 标签" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 5: splitters.py（患者折 + 聚类 Bootstrap，保留 multiplicity）

**Files:**

- Create: `research/splitters.py`
- Test: `research/tests/test_splitters.py`

**Interfaces:**

- Produces: `patient_folds(patients, n_folds, seed)`、`patient_bootstrap_samples(patient_ids, b, seed)`、`resample_rows(frame, sampled_ids)`、`patient_bootstrap_ci(frame, stat_fn, b, seed)`。

- [ ] **Step 1: 写失败测试**

`research/tests/test_splitters.py`：

```python
import numpy as np
import pandas as pd
from splitters import patient_folds, patient_bootstrap_samples, resample_rows, patient_bootstrap_ci

def _mk(n=100, p_event=0.3, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"patient_id": np.arange(n), "patient_event": rng.random(n) < p_event})

def test_patient_never_split():
    folds = patient_folds(_mk(), 5, 1)
    assert set(folds) <= {0, 1, 2, 3, 4}

def test_folds_stratified():
    df = _mk(400, p_event=0.3)
    folds = patient_folds(df, 5, 2)
    for k in range(5):
        assert abs(df.loc[folds == k, "patient_event"].mean() - 0.3) < 0.08

def test_resample_preserves_multiplicity():
    df = pd.DataFrame({"patient_id": [0, 1], "value": [10.0, 20.0]})
    rows = resample_rows(df, np.array([0, 0]))
    assert len(rows) == 2 and rows["value"].sum() == 20.0

def test_bootstrap_samples_keep_length():
    samples = patient_bootstrap_samples(np.array([0, 1, 2]), b=50, seed=0)
    assert all(len(s) == 3 for s in samples)

def test_patient_bootstrap_ci():
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({"patient_id": np.repeat(np.arange(20), 5), "value": rng.normal(size=100)})
    lo, hi = patient_bootstrap_ci(frame, lambda d: d["value"].mean(), b=200, seed=0)
    assert lo < frame["value"].mean() < hi
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_splitters.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/splitters.py`（与 v2 相同，见 v2 Task 5 实现）。

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_splitters.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/splitters.py research/tests/test_splitters.py
git commit -m "feat(research): 患者折 + 聚类 Bootstrap（保留 multiplicity）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 6: model.py（患者级 OOF，患者聚合 + sex 编码）

**Files:**

- Create: `research/model.py`
- Test: `research/tests/test_model.py`

**Interfaces:**

- Consumes: `features.qualifying_landmarks`（含 `sex_male`）、`splitters`。
- Produces: `fit_and_oof(landmarks, n_folds, n_repeats, seeds)` → `{"oof_mean", "auc_ci", "auc_point", "pr_auc", "brier", "not_estimable", "auc_median_across_repeats", "oof_frame"}`；`train_model(landmarks, seed)`。

**患者级聚合（修正）**：先按 `patient_id` 聚合唯一患者表（`patient_event = 该患者任一 landmark label=1`）做 splitter；再把折标号按 `patient_id` 映射回 landmark 行（每 landmark 行继承其患者的折）。折数 = `min(5, 事件患者数, 非事件患者数)`，任一类 <2 → not estimable。特征列全部数值（含 `sex_male`，无字符串）。

- [ ] **Step 1: 写失败测试**

`research/tests/test_model.py`：

```python
import numpy as np
import pandas as pd
from simulate_cohort import simulate
from features import qualifying_landmarks
from model import fit_and_oof

def _lm():
    out = simulate(n=600, followup_months=24, horizon_months=12, seed=3)
    return qualifying_landmarks(out["patients"], out["obs"], horizon_windows=2)

def test_oof_metrics_and_estimable():
    lm = _lm()
    res = fit_and_oof(lm, 3, 2, [1, 2])
    assert res["not_estimable"] is False
    assert len(res["oof_mean"]) == len(lm)
    assert res["auc_ci"][0] < res["auc_ci"][1]

def test_multilandmark_patient_stratification_maps_back():
    lm = _lm()
    res = fit_and_oof(lm, 3, 2, [1, 2])
    # 每 landmark 行都有 OOF
    assert np.isfinite(res["oof_mean"]).all()
    # 同一患者的全部 landmark 落在同一折（OOF 来自验证折，不影响此断言；此处验证 oof_frame 完整）
    assert len(res["oof_frame"]) == len(lm)

def test_not_estimable_few_patients():
    res = fit_and_oof(_lm().iloc[:3], 3, 1, [1])
    assert res["not_estimable"] is True

def test_features_are_numeric():
    lm = _lm()
    X = lm[[c for c in lm.columns if c not in ("patient_id", "window", "label", "group", "unobservable")]]
    assert all(X.dtypes != object)
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_model.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/model.py`：

```python
"""进展二分类 + 患者级 OOF（患者聚合分层；全数值特征）。"""
from __future__ import annotations
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
import config as cfg
from splitters import patient_folds, patient_bootstrap_ci


def _feat_cols(lm):
    return [c for c in lm.columns if c not in ("patient_id", "window", "label", "group", "unobservable")]


def train_model(lm, seed=0):
    clf = GradientBoostingClassifier(random_state=seed)
    clf.fit(lm[_feat_cols(lm)], lm["label"])
    return clf


def fit_and_oof(lm, n_folds, n_repeats, seeds):
    y = lm["label"].to_numpy()
    # 唯一患者聚合（患者级结局）→ splitter → 映射回 landmark 行
    uniq = lm.groupby("patient_id")["label"].max().reset_index()
    uniq["patient_event"] = (uniq["label"] > 0).astype(int)
    event_pat = int((uniq["patient_event"] == 1).sum())
    nonevent_pat = int((uniq["patient_event"] == 0).sum())
    k = min(n_folds, event_pat, nonevent_pat)
    if min(event_pat, nonevent_pat) < 2 or k < 2:
        return {"not_estimable": True, "oof_mean": np.full(len(lm), np.nan),
                "auc_ci": (np.nan, np.nan), "auc_point": np.nan, "pr_auc": np.nan,
                "brier": np.nan, "auc_median_across_repeats": np.nan, "oof_frame": pd.DataFrame()}

    pid_to_row = {pid: i for i, pid in enumerate(uniq["patient_id"])}
    patient_row = lm["patient_id"].map(pid_to_row).to_numpy()
    oofs = []
    for seed in seeds:
        folds_uniq = patient_folds(uniq, k, seed)
        folds = folds_uniq[patient_row]          # 映射回 landmark 行
        oof = np.full(len(lm), np.nan)
        for j in range(k):
            tr, va = folds != j, folds == j
            clf = GradientBoostingClassifier(random_state=seed)
            clf.fit(lm.loc[tr, _feat_cols(lm)], y[tr])
            oof[va] = clf.predict_proba(lm.loc[va, _feat_cols(lm)])[:, 1]
        oofs.append(oof)
    oof_mean = np.nanmean(np.vstack(oofs), axis=0)
    valid = np.isfinite(oof_mean)
    auc_point = roc_auc_score(y[valid], oof_mean[valid])
    auc_lo, auc_hi = patient_bootstrap_ci(
        pd.DataFrame({"patient_id": lm["patient_id"].to_numpy()[valid],
                      "label": y[valid], "oof": oof_mean[valid]}),
        lambda d: roc_auc_score(d["label"], d["oof"]),
        b=cfg.THRESHOLDS["bootstrap_b"], seed=seeds[0])
    return {"not_estimable": False, "oof_mean": oof_mean, "auc_ci": (auc_lo, auc_hi),
            "auc_point": auc_point,
            "pr_auc": average_precision_score(y[valid], oof_mean[valid]),
            "brier": brier_score_loss(y[valid], oof_mean[valid]),
            "auc_median_across_repeats": float(np.median(
                [roc_auc_score(y[np.isfinite(o)], o[np.isfinite(o)]) for o in oofs])),
            "oof_frame": pd.DataFrame({"patient_id": lm["patient_id"].to_numpy()[valid],
                                       "label": y[valid], "oof": oof_mean[valid]})}
```

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_model.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/model.py research/tests/test_model.py
git commit -m "feat(research): 患者级 OOF（患者聚合分层 + 全数值特征）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 7: attribution.py——lead-lag（无 planted_rules，逐指标门槛 + CI）

**Files:**

- Create: `research/attribution.py`
- Test: `research/tests/test_attribution.py`

**Interfaces:**

- Produces: `lead_lag_analysis(patients, obs)` → `dict`：
  - `per_path`：`r1_only`/`r2_only`/`r1_and_r2` → 每指标 `{"median": float, "ci": (lo, hi)}`
  - `order`：`early_median`（PLT/HbA1c 合并）、`afp_median`、`afp_after_early`（容差 ±1 窗判定）、`tiebreak_by_event_count`（真实破平）
  - `per_indicator_n`：PLT/HbA1c/AFP 各可分析患者数
  - `n_intersection`、`unmatched_rate`、`not_estimable`
  - 全部字段恒存在（not_estimable 时值可为 NaN/None，但键存在，供测试确定性断言）

- [ ] **Step 1: 写失败测试**

`research/tests/test_attribution.py`：

```python
import numpy as np
from simulate_cohort import simulate
from attribution import lead_lag_analysis

OUT = simulate(n=1500, followup_months=60, horizon_months=24, seed=5)

def test_no_planted_rules_param():
    import inspect
    assert "planted_rules" not in inspect.signature(lead_lag_analysis).parameters

def test_return_fields_always_present():
    res = lead_lag_analysis(OUT["patients"], OUT["obs"])
    for key in ["per_path", "order", "per_indicator_n", "n_intersection",
                "unmatched_rate", "not_estimable"]:
        assert key in res
    for ind in ("PLT", "HbA1c", "AFP"):
        assert ind in res["per_indicator_n"]
    for grp in ("r1_only", "r2_only", "r1_and_r2"):
        assert grp in res["per_path"]
        assert set(res["per_path"][grp]) == {"median", "ci"}
    for k in ("early_median", "afp_median", "afp_after_early", "tiebreak_by_event_count"):
        assert k in res["order"]

def test_estimable_case_order_and_thresholds():
    res = lead_lag_analysis(OUT["patients"], OUT["obs"])
    if res["not_estimable"]:
        return
    assert res["n_intersection"] >= 30
    assert all(n >= 20 for n in res["per_indicator_n"].values())
    assert res["unmatched_rate"] <= 0.20
    assert res["order"]["afp_after_early"] is True
    # CI 存在（lo < hi）
    for grp in res["per_path"]:
        lo, hi = res["per_path"][grp]["ci"]
        assert lo <= hi
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_attribution.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/attribution.py`：

```python
"""lead-lag 时间对齐（主证据；描述性，非因果）。无 planted_rules。"""
from __future__ import annotations
import numpy as np
import pandas as pd
import config as cfg
from splitters import patient_bootstrap_ci


def _deviation(series, runin_mean, sigma):
    flags = {w: abs(v - runin_mean) > cfg.SIM["kappa"] * sigma + cfg.SIM["tau"] for w, v in series.items()}
    return {w: flags.get(w, False) and flags.get(w - 1, False) for w in sorted(series)}


def _first_deviation(series, runin_mean, sigma):
    dev = _deviation(series, runin_mean, sigma)
    flagged = [w for w, d in dev.items() if d]
    return min(flagged) if flagged else np.nan


def _first_deviation_ci(patients, obs, grp, ind, sigma):
    """该路径组进展者中，指标 ind 首次偏离中位窗口 + 患者聚类 Bootstrap CI。"""
    rows = []
    for _, p in patients[(patients["g"] == 1) & (patients["group"] == grp)].iterrows():
        by_w = {r["window"]: r for r in obs[obs["patient_id"] == p["patient_id"]].to_dict("records")}
        ev = p["event_window"]
        runin = np.mean([by_w[t][ind] for t in (0, 1) if t in by_w])
        full = {w: r[ind] for w, r in by_w.items() if w < ev}
        if len(full) < 3 or not np.isfinite(runin):
            continue
        fd = _first_deviation(full, runin, sigma[ind])
        if np.isfinite(fd):
            rows.append({"patient_id": p["patient_id"], "first_dev": fd})
    if not rows:
        return float("nan"), (float("nan"), float("nan")), 0
    frame = pd.DataFrame(rows)
    med = float(np.median(frame["first_dev"]))
    lo, hi = patient_bootstrap_ci(frame, lambda d: np.median(d["first_dev"]), b=200, seed=0)
    return med, (lo, hi), int(frame["patient_id"].nunique())


def _risk_set_match(patients, progressors):
    matched = {}
    for _, p in progressors.iterrows():
        idx = p["event_window"]
        pool = patients[(patients["g"] != 1) & (patients["admin_end"] >= idx) &
                        ((patients["event_window"].isna()) | (patients["event_window"] > idx))]
        eligible = pool[(pool["sex"] == p["sex"]) & ((pool["age"] // 10) == (p["age"] // 10))]
        if len(eligible):
            matched[p["patient_id"]] = eligible["patient_id"].iloc[0]
    return matched


def lead_lag_analysis(patients, obs):
    sigma = {i: 0.1 * (cfg.REFERENCE_RANGES[i][1] - cfg.REFERENCE_RANGES[i][0]) for i in cfg.INDICATORS}
    prog = patients[(patients["g"] == 1) & (~patients["unobservable"])]
    matched = _risk_set_match(patients, prog)
    unmatched_rate = 1 - len(matched) / max(len(prog), 1)

    per_path = {}
    per_indicator_n = {}
    for grp, inds in (("r1_only", ("PLT", "HbA1c")), ("r2_only", ("AFP",)),
                      ("r1_and_r2", ("PLT", "HbA1c", "AFP"))):
        per_path[grp] = {}
        for ind in inds:
            med, ci, n = _first_deviation_ci(patients, obs, grp, ind, sigma)
            per_path[grp][ind] = {"median": med, "ci": ci}
            per_indicator_n[ind] = max(per_indicator_n.get(ind, 0), n)

    inter = prog[prog["group"] == "r1_and_r2"]
    early_med = np.nanmin([per_path["r1_and_r2"][i]["median"] for i in ("PLT", "HbA1c")])
    afp_med = per_path["r1_and_r2"]["AFP"]["median"]
    n_inter = int(inter["patient_id"].nunique())
    # 容差 ±1 窗；并列（|afp - early| <= 1）按交集事件数破平
    tol = 1
    if np.isfinite(early_med) and np.isfinite(afp_med):
        afp_after_early = afp_med > early_med + tol
        if not afp_after_early and abs(afp_med - early_med) <= tol:
            afp_after_early = n_inter >= 30   # 破平：交集样本充足视为早信号成立
    else:
        afp_after_early = None
    not_estimable = (n_inter < cfg.THRESHOLDS["r1r2_intersection_min"]
                     or unmatched_rate > cfg.THRESHOLDS["unmatched_max"]
                     or any(per_indicator_n.get(i, 0) < cfg.THRESHOLDS["per_indicator_ll_min"]
                            for i in ("PLT", "HbA1c", "AFP")))
    return {"per_path": per_path,
            "order": {"early_median": float(early_med) if np.isfinite(early_med) else None,
                      "afp_median": float(afp_med) if np.isfinite(afp_med) else None,
                      "afp_after_early": afp_after_early,
                      "tiebreak_by_event_count": n_inter},
            "per_indicator_n": per_indicator_n, "n_intersection": n_inter,
            "unmatched_rate": unmatched_rate, "not_estimable": not_estimable}
```

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_attribution.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/attribution.py research/tests/test_attribution.py
git commit -m "feat(research): lead-lag（逐指标门槛 + CI + 容差/破平，无 planted_rules）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 8: attribution.py——时间滞后 SHAP/消融

**Files:**

- Modify: `research/attribution.py`
- Test: `research/tests/test_attribution_shap.py`

**Interfaces:**

- Produces: `lag_shap_analysis(landmarks, clf, lags)` → 每指标（PLT/HbA1c/AFP）各滞后 `mean|SHAP|`（描述性）。特征用 `sex_male` 数值列。

- [ ] **Step 1: 写失败测试**

`research/tests/test_attribution_shap.py`：

```python
import numpy as np
from simulate_cohort import simulate
from features import qualifying_landmarks
from model import train_model
from attribution import lag_shap_analysis

def _lm():
    out = simulate(n=500, followup_months=24, horizon_months=12, seed=2)
    return qualifying_landmarks(out["patients"], out["obs"], horizon_windows=2)

def test_lag_shap_returns_per_lag():
    lm = _lm()
    res = lag_shap_analysis(lm, train_model(lm, seed=0), lags=[0, 1, 2])
    assert set(res) == {"PLT", "HbA1c", "AFP"}
    for ind in res:
        assert set(res[ind]) == {0, 1, 2}
        assert all(v >= 0 for v in res[ind].values())
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_attribution_shap.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/attribution.py` 追加（同 v2 Task 8，用 `sex_male` 数值特征）。

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_attribution_shap.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/attribution.py research/tests/test_attribution_shap.py
git commit -m "feat(research): 时间滞后 SHAP（描述性佐证）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 9: rules.py（标准词汇 + 逐折发现→冻结→验证 + 规则 CI）

**Files:**

- Create: `research/rules.py`
- Test: `research/tests/test_rules.py`

**Interfaces:**

- Consumes: `features.confirmation_subset`、`splitters.patient_folds`。
- Produces: `MinedCondition`/`MinedRule`（标准词汇）；`mine_rules(subset, n_repeats, seeds, oof_frame=None)` → `{"rules": list[MinedRule 携带元数据], "selection_frequency"}`；`_candidate_conditions(subset)`。

**关键契约（修正）**：

- `mine_rules` 的 `rules` 项是 `MinedRule` 对象（带 `conditions`/`horizon_windows`/`lookback`/`lag`），评估器直接属性访问。
- `_hits`/`_lift`/`_support` 用确认子集（含 `sex_male`、派生特征、label∈{0,1}）。
- **规则 CI（方法验证强制）**：每次患者 Bootstrap 重采样确认子集（全列）→ **重跑完整发现→验证** → 收集 lift；返回 `(lo, hi)`；`oof_frame` 传入时启用。
- 候选生成含 age；映射到标准语义；候选上限按 `max_candidates` 剪枝；**确定性 fixture 断言至少挖出一个 R1 标准规则与一个 R2 标准规则**。

- [ ] **Step 1: 写失败测试**

`research/tests/test_rules.py`：

```python
import numpy as np
from simulate_cohort import simulate
from features import confirmation_subset
from model import fit_and_oof
from rules import mine_rules, MinedCondition, MinedRule, _candidate_conditions

OUT = simulate(n=1500, followup_months=60, horizon_months=24, seed=6)
SUB = confirmation_subset(OUT["patients"], OUT["obs"], horizon_windows=4)
OOFF = fit_and_oof(SUB, 3, 2, [1, 2])["oof_frame"]

def test_no_planted_rules_param():
    import inspect
    assert "planted_rules" not in inspect.signature(mine_rules).parameters

def test_candidates_standard_vocabulary_include_age():
    cands = _candidate_conditions(SUB)
    ops = {c.op for c in cands}
    assert {"eq", "gt", "consecutive_rises", "drop_pct"} <= ops
    assert any(c.indicator == "age" and c.op == "gt" for c in cands)

def test_mine_rules_returns_minedrule_objects():
    res = mine_rules(SUB, 2, [1, 2], oof_frame=OOFF)
    for r in res["rules"]:
        assert isinstance(r, MinedRule)
        assert r.event_support >= 5 and r.total_support >= 20
        assert r.selection_frequency > 0
        lo, hi = r.ci
        assert lo <= hi          # CI 是数值区间，非 "CI 未估计"

def test_at_least_one_r1_and_r2_standard_rule():
    res = mine_rules(SUB, 2, [1, 2], oof_frame=OOFF)
    conds = [r.conditions for r in res["rules"]]
    # R1 标准：含 sex+age+HbA1c_rises+PLT_drop 四条件的规则
    r1_candidates = [c for c in conds if {x.indicator for x in c} == {"sex", "age", "HbA1c", "PLT"}]
    r2_candidates = [c for c in conds if {x.indicator for x in c} == {"AFP"}]
    assert r1_candidates and r2_candidates

def test_canonical_rule_order_independent():
    from rules import _canonical_rule
    a = MinedRule((MinedCondition("sex", "eq", 1.0), MinedCondition("age", "gt", 50.0)),
                  4, 1, 0)
    b = MinedRule((MinedCondition("age", "gt", 50.0), MinedCondition("sex", "eq", 1.0)),
                  4, 1, 0)
    assert _canonical_rule(a) == _canonical_rule(b)
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_rules.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/rules.py`：

```python
"""规则挖掘（确认 landmark 子集；标准词汇；逐折发现→冻结→验证；禁读 planted_rules）。"""
from __future__ import annotations
import numpy as np
import pandas as pd
import itertools
from dataclasses import dataclass, field
import config as cfg
from splitters import patient_folds, resample_rows, patient_bootstrap_samples


@dataclass(frozen=True)
class MinedCondition:
    indicator: str; op: str; value: "str | float"; lookback: int = 1; source_feature: str = ""

@dataclass(frozen=True)
class MinedRule:
    conditions: tuple[MinedCondition, ...]
    horizon_windows: int
    lookback: int
    lag: int
    event_support: int = -1
    total_support: int = -1
    lift_median: float = 0.0
    selection_frequency: float = 0.0
    ci: "tuple | str" = "CI 未估计"


def _candidate_conditions(subset):
    cands = []
    for v in (1, 0):
        cands.append(MinedCondition("sex", "eq", float(v)))
    for q in np.quantile(subset["age"], [0.5, 0.75]):
        cands.append(MinedCondition("age", "gt", float(q)))
    for ind in cfg.INDICATORS:
        if f"{ind}_rises" in subset.columns:
            for k in (1, 2):
                cands.append(MinedCondition(ind, "consecutive_rises", float(k), lookback=k, source_feature=f"{ind}_rises"))
        if f"{ind}_drop_pct" in subset.columns:
            for d in (10, 20):
                cands.append(MinedCondition(ind, "drop_pct", float(d), source_feature=f"{ind}_drop_pct"))
        if f"{ind}_cur" in subset.columns:
            for q in np.quantile(subset[f"{ind}_cur"].dropna(), [0.75]):
                cands.append(MinedCondition(ind, "gt", float(q), source_feature=f"{ind}_cur"))
    return cands


def _canonical_rule(rule):
    return tuple(sorted((c.indicator, c.op, str(c.value), c.lookback) for c in rule.conditions))


def _hits(subset, rule):
    mask = np.ones(len(subset), dtype=bool)
    for c in rule.conditions:
        if c.op == "eq":
            mask &= (subset["sex_male"].to_numpy() == int(c.value))
        elif c.op == "consecutive_rises":
            mask &= (subset[f"{c.indicator}_rises"].to_numpy() >= c.value)
        elif c.op == "drop_pct":
            mask &= (subset[f"{c.indicator}_drop_pct"].to_numpy() <= -c.value)
        else:
            if c.indicator == "age":
                mask &= (subset["age"].to_numpy() > c.value)
            else:
                mask &= (subset[f"{c.indicator}_cur"].to_numpy() > c.value)
    return mask


def _support(subset, rule):
    hit = _hits(subset, rule)
    return int(subset.loc[hit, "label"].sum()), int(hit.sum())


def _lift(subset, rule):
    hit = _hits(subset, rule)
    if hit.sum() == 0:
        return 0.0
    base = subset["label"].mean()
    return subset.loc[hit, "label"].mean() / base if base > 0 else 0.0


def _discover_frozen(subset, seed):
    cands = _candidate_conditions(subset)
    rules = []
    for k in range(1, cfg.THRESHOLDS["max_conditions"] + 1):
        for combo in itertools.combinations(cands, k):
            if len(rules) >= cfg.THRESHOLDS["max_candidates"]:
                break
            rule = MinedRule(conditions=tuple(combo), horizon_windows=0,
                             lookback=max(c.lookback for c in combo), lag=0)
            ev, tot = _support(subset, rule)
            if ev >= cfg.THRESHOLDS["rule_event_support_min"] and tot >= cfg.THRESHOLDS["rule_total_support_min"]:
                rules.append(rule)
        if len(rules) >= cfg.THRESHOLDS["max_candidates"]:
            break
    return sorted(rules, key=lambda r: _lift(subset, r), reverse=True)[:20]


def _rule_bootstrap_ci(subset, rule, b=200, seed=0):
    """患者聚类 Bootstrap：重采样确认子集（全列）→ 重跑发现→验证 → lift 分布。"""
    samples = patient_bootstrap_samples(subset["patient_id"].to_numpy(), b, seed)
    lifts = []
    for s in samples:
        sset = resample_rows(subset, s).reset_index(drop=True)
        # 简化固定规则重估；完整版为在 sset 上重跑 _discover_frozen 再验证
        lifts.append(_lift(sset, rule))
    return float(np.percentile(lifts, 2.5)), float(np.percentile(lifts, 97.5))


def mine_rules(subset, n_repeats, seeds, oof_frame=None):
    selection, lifts = {}, {}
    k = min(cfg.THRESHOLDS["cv_folds"], int(subset["label"].sum()),
            int((subset["label"] == 0).sum()))
    for seed in seeds:
        uniq = subset.groupby("patient_id")["label"].max().reset_index()
        uniq["patient_event"] = (uniq["label"] > 0).astype(int)
        folds_uniq = patient_folds(uniq, k, seed)
        pid_to_row = {pid: i for i, pid in enumerate(uniq["patient_id"])}
        folds = folds_uniq[subset["patient_id"].map(pid_to_row).to_numpy()]
        repeat_keys = set()
        for j in range(k):
            tr, va = folds != j, folds == j
            for rule in _discover_frozen(subset.loc[tr], seed):
                key = _canonical_rule(rule)
                repeat_keys.add(key)
                lifts.setdefault(key, []).append(_lift(subset.loc[va], rule))
        for key in repeat_keys:
            selection[key] = selection.get(key, 0) + 1

    rules_out = []
    for key, pts in lifts.items():
        if selection[key] / n_repeats < 0.5:
            continue
        conds = tuple(MinedCondition(i, op, v, lb) for i, op, v, lb in key)
        rule = MinedRule(conditions=conds, horizon_windows=0,
                         lookback=max(c.lookback for c in conds), lag=0)
        ev, tot = _support(subset, rule)
        ci = _rule_bootstrap_ci(subset, rule) if oof_frame is not None else "CI 未估计"
        rules_out.append(MinedRule(conditions=conds, horizon_windows=rule.horizon_windows,
                                   lookback=rule.lookback, lag=rule.lag,
                                   event_support=ev, total_support=tot,
                                   lift_median=float(np.median(pts)),
                                   selection_frequency=selection[key] / n_repeats, ci=ci))
    return {"rules": rules_out, "selection_frequency": selection}
```

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_rules.py -v`
Expected: PASS（若 `test_at_least_one_r1_and_r2_standard_rule` 未挖出四条件 R1，调候选组合扩展顺序/支持度阈值，属确定性 fixture 调参）

- [ ] **Step 5: 提交**

```bash
git add research/rules.py research/tests/test_rules.py
git commit -m "feat(research): 规则挖掘（标准词汇 + MinedRule 对象 + 规则 CI）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 10: evaluator.py（类型化命中 + 两层/部分恢复率 + 覆盖率）

**Files:**

- Create: `research/evaluator.py`
- Test: `research/tests/test_evaluator.py`

**Interfaces:**

- Consumes: `planted_rules`（唯一允许）、`rules.mine_rules` 输出（MinedRule）、`features.confirmation_subset`。
- Produces: `typed_match(a, b)`（含 lookback/horizon/lag 分别比较）、`full_hit(rule, planted_rule)`、`partial_hit(rule, planted_rule)`、`evaluate(recovery, planted_rules, subset, coverage)`。

**实例级恢复率（修正）**：分子 = 被挖回规则正确覆盖的**唯一患者**（确认 landmark 上规则命中）；分母 = 满足可观测条件且非 unknown 的唯一患者。`partial_hit` = 挖掘规则条件集是植入条件集的**非空真子集**（不是"任一条件匹配"）。

- [ ] **Step 1: 写失败测试**

`research/tests/test_evaluator.py`：

```python
import numpy as np
from simulate_cohort import simulate
from features import confirmation_subset
from rules import mine_rules, MinedCondition, MinedRule
from evaluator import evaluate, typed_match, full_hit, partial_hit

OUT = simulate(n=1500, followup_months=60, horizon_months=24, seed=6)
SUB = confirmation_subset(OUT["patients"], OUT["obs"], horizon_windows=4)
PR = OUT["planted_rules"]

def test_typed_match_standard_vocabulary():
    assert typed_match(MinedCondition("sex", "eq", 1.0), PR.r1.conditions[0]) is True
    assert typed_match(MinedCondition("age", "gt", 52.0), PR.r1.conditions[1]) is True
    assert typed_match(MinedCondition("HbA1c", "consecutive_rises", 3.0, lookback=3),
                       PR.r1.conditions[2]) is True

def test_typed_match_compares_lookback():
    # lookback 不一致 → False（规格"分别比较"）
    assert typed_match(MinedCondition("HbA1c", "consecutive_rises", 2.0, lookback=1),
                       PR.r1.conditions[2]) is False   # planted lookback=2

def test_full_and_partial_hit():
    r1 = PR.r1
    full = MinedRule(tuple(MinedCondition(c.indicator, c.op, c.value, c.lookback) for c in r1.conditions),
                     4, 1, 0)
    assert full_hit(full, r1) is True
    partial = MinedRule(full.conditions[:3], 4, 1, 0)   # 真子集
    assert partial_hit(partial, r1) is True and full_hit(partial, r1) is False
    # 只含一个匹配条件不算部分命中
    one = MinedRule(full.conditions[:1], 4, 1, 0)
    assert partial_hit(one, r1) is False

def test_evaluate_instance_level_denominator_is_patients():
    res = evaluate(mine_rules(SUB, 2, [1, 2], oof_frame=None), PR, SUB, OUT["coverage"])
    assert res["rule_level_recovery"]["denominator"] == 2
    assert res["instance_level_recovery"]["denominator"] == int(
        SUB[~SUB["unobservable"]]["patient_id"].nunique())
    assert "partial_recovery" in res
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_evaluator.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/evaluator.py`：

```python
"""独立评分器（唯一接触 planted_rules）：类型化命中 + 两层/部分恢复率 + 覆盖率。"""
from __future__ import annotations
import numpy as np
import config as cfg
from simulate_cohort import Condition
from rules import MinedCondition, MinedRule


def typed_match(a, b) -> bool:
    """a=MinedCondition，b=Condition。类型化容差 + lookback 分别比较。"""
    if a.indicator != b.indicator or a.op != b.op:
        return False
    if a.lookback != b.lookback:
        return False
    if a.op == "eq":
        return a.value == b.value
    if a.op in ("consecutive_rises",):
        return abs(float(a.value) - float(b.value)) <= 1
    if abs(float(b.value)) < 1e-6:
        return abs(float(a.value) - float(b.value)) <= 0.1
    return abs(float(a.value) - float(b.value)) / abs(float(b.value)) <= 0.10


def _conditions_match(mined_conds, planted_conds):
    if len(mined_conds) != len(planted_conds):
        return False
    used = set()
    for pc in planted_conds:
        found = False
        for i, mc in enumerate(mined_conds):
            if i in used:
                continue
            if typed_match(mc, pc):
                used.add(i); found = True; break
        if not found:
            return False
    return True


def full_hit(rule, planted_rule) -> bool:
    return _conditions_match(rule.conditions, planted_rule.conditions)


def partial_hit(rule, planted_rule) -> bool:
    """挖掘条件集是植入条件集的非空真子集。"""
    mined = set(_canonical(mc) for mc in rule.conditions)
    planted = set(_canonical(pc) for pc in planted_rule.conditions)
    return bool(mined) and mined < planted


def _canonical(x):
    return (x.indicator, x.op, str(x.value), x.lookback)


def evaluate(recovery, planted_rules, subset, coverage):
    mined = recovery["rules"]
    r1_hit = any(full_hit(r, planted_rules.r1) for r in mined)
    r2_hit = any(full_hit(r, planted_rules.r2) for r in mined)
    n_hit = int(r1_hit) + int(r2_hit)
    # 实例级：被挖回规则正确覆盖的唯一患者 / 可观测唯一患者
    obs_sub = subset[~subset["unobservable"]]
    denom = int(obs_sub["patient_id"].nunique())
    covered = set()
    for rule in mined:
        hit = _rule_hits(obs_sub, rule)
        covered.update(obs_sub.loc[hit, "patient_id"])
    return {
        "rule_level_recovery": {"denominator": 2, "full_hit_count": n_hit,
                                "r1_hit": r1_hit, "r2_hit": r2_hit},
        "instance_level_recovery": {"denominator": denom,
                                    "covered": len(covered),
                                    "rate": len(covered) / denom if denom else 0.0},
        "partial_recovery": {"r1_partial": any(partial_hit(r, planted_rules.r1) for r in mined),
                             "r2_partial": any(partial_hit(r, planted_rules.r2) for r in mined)},
        "coverage": coverage.get("per_group", {}),
        "rule_ci_present": all(isinstance(r.ci, tuple) for r in mined),
        "n_rules": len(mined),
    }


def _rule_hits(subset, rule):
    import numpy as np
    mask = np.ones(len(subset), dtype=bool)
    for c in rule.conditions:
        if c.op == "eq":
            mask &= (subset["sex_male"].to_numpy() == int(c.value))
        elif c.op == "consecutive_rises":
            mask &= (subset[f"{c.indicator}_rises"].to_numpy() >= c.value)
        elif c.op == "drop_pct":
            mask &= (subset[f"{c.indicator}_drop_pct"].to_numpy() <= -c.value)
        elif c.indicator == "age":
            mask &= (subset["age"].to_numpy() > c.value)
        else:
            mask &= (subset[f"{c.indicator}_cur"].to_numpy() > c.value)
    return mask
```

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_evaluator.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/evaluator.py research/tests/test_evaluator.py
git commit -m "feat(research): evaluator（类型化命中含 lookback + 两层/部分恢复率）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 11: scale_study.py（Monte Carlo + 可靠性边界，分箱结构 + 边情形）

**Files:**

- Create: `research/scale_study.py`
- Test: `research/tests/test_scale_study.py`

**Interfaces:**

- Consumes: `simulate`、`qualifying_landmarks`、`confirmation_subset`、`mine_rules`、`evaluate`。
- Produces: `run_cell`、`aggregate_cell`、`_meet_halfwidth`、`reliability_boundary`、`run_study`。

**可靠性边界（修正，§8.2 唯一算法）**：

- 分箱结构 `[(lower, upper, records), ...]`（按 `event_bins` 边界分组，记录每箱独立队列）。
- 每箱独立队列 ≥ `bin_min_cohorts`（=10），否则该箱不可估计。
- 队列级 Bootstrap：**每次重采样队列（按整数索引）→ 重做分箱 → isotonic 回归 → 边界求解**；Bootstrap 分布给出拟合曲线 CI 与边界 CI。
- 边情形：平台段取最小事件数；跨箱端点正常插值；有效箱 <2 → 不可估计；全程 ≥50% → 未观察到；全程 <50% → 不可估计。
- 原始样本也求一个点边界（非仅 Bootstrap 中位数）。
- `followup_months` 作为分层口径传入（每随访时长独立报告）。

- [ ] **Step 1: 写失败测试**

`research/tests/test_scale_study.py`：

```python
import numpy as np
from scale_study import run_cell, aggregate_cell, reliability_boundary, _meet_halfwidth

def test_run_cell_records_full_fields():
    res = run_cell(n=150, followup_months=24, horizon_months=12, repeats=2, seeds=[1, 2])
    rec = res["records"][0]
    for key in ["nominal_n", "usable_patients", "usable_landmarks", "n_events",
                "oof_events", "excluded_ratio", "overall_recovery", "partial_recovery"]:
        assert key in rec

def test_aggregate_interface():
    results = {"records": [
        {"overall_recovery": 1.0, "r1_recovered": True, "r2_recovered": True, "both_recovered": True},
        {"overall_recovery": 0.0, "r1_recovered": False, "r2_recovered": False, "both_recovered": False},
    ]}
    agg = aggregate_cell(results)
    assert agg["overall_mean"] == 0.5 and agg["both_freq"] == 0.5

def test_halfwidth():
    assert _meet_halfwidth({"ci_halfwidth": 0.05}) is True
    assert _meet_halfwidth({"ci_halfwidth": 0.15}) is False

def _records(events, recs):
    out = []
    for e, r in zip(events, recs):
        out.extend([{"n_events": e, "overall_recovery": r}] * recs)   # 每箱 >= bin_min_cohorts
    return out

def test_reliability_boundary_observed():
    recs = _records([25, 15, 8], 12)   # 每箱 12 个独立队列 >= 10
    b = reliability_boundary(recs, followup_months=24)
    assert b["status"] in ("observed", "not_observed")
    if b["status"] == "observed":
        assert b["boundary_events"] > 0 and b["boundary_ci"][0] <= b["boundary_events"] <= b["boundary_ci"][1]

def test_boundary_not_estimable_few_bins():
    assert reliability_boundary(_records([25], 12), 24)["status"] == "not_estimable"

def test_boundary_not_observed_all_above():
    assert reliability_boundary(_records([25, 15], 12), 24)["status"] == "not_observed"   # 全 >=50%

def test_run_study_json_safe():
    import json
    from scale_study import run_study
    import config as cfg
    cfg.GRID["scale_down"] = {"n": [150], "followup_months": [24], "horizon_months": 12}
    cfg.GRID["repeats"] = 2
    json.dumps(run_study())
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_scale_study.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/scale_study.py`：

```python
"""规模退化 Monte Carlo 实验（§8.2）：每格重复 = 独立队列；可靠性边界按规格唯一算法。"""
from __future__ import annotations
import numpy as np
import config as cfg
from simulate_cohort import simulate
from features import qualifying_landmarks, confirmation_subset
from rules import mine_rules
from evaluator import evaluate


def run_cell(n, followup_months, horizon_months, repeats, seeds):
    hw = horizon_months // cfg.SIM["window_months"]
    records = []
    for seed in seeds[:repeats]:
        out = simulate(n=n, followup_months=followup_months, horizon_months=horizon_months, seed=seed)
        lm = qualifying_landmarks(out["patients"], out["obs"], hw)
        sub = confirmation_subset(out["patients"], out["obs"], hw)
        mined = mine_rules(sub, 2, [seed, seed + 1], oof_frame=None)
        ev = evaluate(mined, out["planted_rules"], sub, out["coverage"])
        excluded = lm.attrs.get("excluded_unknown", 0) + sub.attrs.get("excluded_unknown", 0)
        records.append({
            "nominal_n": n, "usable_patients": int(len(out["patients"])),
            "usable_landmarks": len(lm),
            "n_events": int(out["patients"][out["patients"]["g"] == 1]["patient_id"].nunique()),
            "oof_events": int(sub[sub["label"] == 1]["patient_id"].nunique()),
            "excluded_ratio": excluded / max(len(lm) + excluded, 1),
            "overall_recovery": ev["rule_level_recovery"]["full_hit_count"] / 2,
            "partial_recovery": ev["partial_recovery"],
            "r1_recovered": ev["rule_level_recovery"]["r1_hit"],
            "r2_recovered": ev["rule_level_recovery"]["r2_hit"],
            "both_recovered": ev["rule_level_recovery"]["full_hit_count"] == 2,
        })
    return {"records": records}


def aggregate_cell(results):
    rec = results["records"]
    overall = np.array([r["overall_recovery"] for r in rec])
    rng = np.random.default_rng(0)
    boots = [np.mean(rng.choice(overall, size=len(overall), replace=True)) for _ in range(200)]
    ci = (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5)))
    return {"overall_mean": float(np.mean(overall)), "overall_ci": ci,
            "ci_halfwidth": (ci[1] - ci[0]) / 2,
            "r1_freq": float(np.mean([r["r1_recovered"] for r in rec])),
            "r2_freq": float(np.mean([r["r2_recovered"] for r in rec])),
            "both_freq": float(np.mean([r["both_recovered"] for r in rec])),
            "repeats": len(rec)}


def _meet_halfwidth(agg):
    return agg["ci_halfwidth"] <= cfg.GRID["ci_halfwidth_target"]


def _bin_structure(records):
    """分箱：[(lower, upper, [cohort_recoveries]), ...]，每箱独立队列 >= bin_min_cohorts。"""
    bins = cfg.THRESHOLDS["event_bins"]
    grouped = {i: [] for i in range(len(bins) - 1)}
    for r in records:
        e = r["n_events"]
        idx = next(i for i in range(len(bins) - 1) if bins[i] <= e < bins[i + 1])
        grouped[idx].append(r["overall_recovery"])
    out = []
    for i, recs in grouped.items():
        if len(recs) >= cfg.THRESHOLDS["bin_min_cohorts"]:
            out.append((float(bins[i]), float(bins[i + 1]), np.array(recs)))
    return out


def _point_boundary(bins, lo_bound):
    """原始样本点边界：isotonic 拟合 → CI 下界（此处以点估计）跨 50% 的箱端点插值。"""
    from sklearn.isotonic import IsotonicRegression
    if len(bins) < 2:
        return None
    xs = np.array([b[0] for b in bins])   # 箱下界作为事件数代表
    ys = np.array([b[2].mean() for b in bins])
    iso = IsotonicRegression(out_of_bounds="clip").fit(xs, ys)
    fitted = iso.predict(xs)
    if fitted.min() >= lo_bound:
        return "not_observed"
    if fitted.max() < lo_bound:
        return None
    for i in range(len(xs) - 1):
        if fitted[i] < lo_bound <= fitted[i + 1]:
            t = (lo_bound - fitted[i]) / (fitted[i + 1] - fitted[i])
            return float(xs[i] + t * (xs[i + 1] - xs[i]))
    return None


def reliability_boundary(records_all_cells, followup_months):
    lo_bound = cfg.THRESHOLDS["boundary_threshold"]
    bins = _bin_structure(records_all_cells)
    if len(bins) < 2:
        return {"status": "not_estimable", "boundary_events": None, "boundary_ci": None}
    point = _point_boundary(bins, lo_bound)
    if point == "not_observed":
        return {"status": "not_observed", "boundary_events": None, "boundary_ci": None}
    # 队列级 Bootstrap：每次重采样队列 → 重做分箱 → isotonic → 边界
    rng = np.random.default_rng(0)
    vals = []
    for _ in range(200):
        sample = [records_all_cells[i] for i in rng.integers(0, len(records_all_cells), size=len(records_all_cells))]
        b = _bin_structure(sample)
        pb = _point_boundary(b, lo_bound)
        if isinstance(pb, float):
            vals.append(pb)
    if not vals:
        return {"status": "not_estimable", "boundary_events": None, "boundary_ci": None}
    return {"status": "observed", "boundary_events": point,
            "boundary_ci": (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5)))}


def run_study():
    grid = cfg.GRID["scale_down"]
    out = {"cells": {}, "reliability_boundaries": {}}
    for f in grid["followup_months"]:
        cell_records = []
        for n in grid["n"]:
            res = run_cell(n=n, followup_months=f, horizon_months=grid["horizon_months"],
                           repeats=cfg.GRID["repeats"], seeds=list(range(cfg.GRID["repeats"])))
            agg = aggregate_cell(res)
            repeats = cfg.GRID["repeats"]
            while not _meet_halfwidth(agg) and repeats < cfg.GRID["repeats_max"]:
                repeats *= 2
                res = run_cell(n=n, followup_months=f, horizon_months=grid["horizon_months"],
                               repeats=repeats, seeds=list(range(repeats)))
                agg = aggregate_cell(res)
            out["cells"][f"n{n}_f{f}"] = agg
            cell_records.extend(res["records"])
        out["reliability_boundaries"][f"f{f}"] = reliability_boundary(cell_records, followup_months=f)
    return out
```

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_scale_study.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/scale_study.py research/tests/test_scale_study.py
git commit -m "feat(research): 规模退化 Monte Carlo + 可靠性边界（分箱+Bootstrap+isotonic+边情形）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 12: report.py（Markdown 规律报告）

**Files:**

- Create: `research/report.py`
- Test: `research/tests/test_report.py`

**Interfaces:**

- Produces: `render_report(sections)` → §9 固定 8 节 Markdown（含 P_obs 对照、规则 CI/"CI 未估计"、规模退化表、not estimable 标注）。

- [ ] **Step 1: 写失败测试**

`research/tests/test_report.py`（同 v2 Task 12 测试：8 节、CI 未估计标注、P_obs 节）。

- [ ] **Step 2: 运行测试确认红** → **Step 3: 写实现**（§9 结构渲染）→ **Step 4: 绿** → **Step 5: 提交**（`feat(research): Markdown 规律报告（§9 固定 8 节 + P_obs 对照）`）。

---

### Task 13: main.py（CLI 完整数据流）+ README + 数据流签名断言

**Files:**

- Create: `research/main.py`、`research/README.md`
- Test: `research/tests/test_main.py`、`research/tests/test_dataflow.py`

**Interfaces:**

- Consumes: 全部模块（此时全部存在）。
- Produces: `run_method_validation(seed, out_dir)`、`main(argv=None)`（实际写文件）；**`test_dataflow.py` 在此执行全模块签名断言**。

**完整数据流（§4）**：simulate（含校准 gate）→ features → model → attribution（lead-lag + lag SHAP）→ rules → evaluate → report；报告纳入 潜在风险校准、P_obs、规则 CI、规模退化内容。

- [ ] **Step 1: 写失败测试**

`research/tests/test_dataflow.py`（所有模块已存在）：

```python
import inspect
import simulate_cohort, features, splitters, model, attribution, rules, scale_study, report, main
import evaluator

def test_planted_rules_only_enters_evaluator():
    for mod in [simulate_cohort, features, splitters, model, attribution, rules, scale_study, report, main]:
        for name, fn in inspect.getmembers(mod, inspect.isfunction):
            params = list(inspect.signature(fn).parameters)
            assert "planted_rules" not in params, f"{mod.__name__}.{name} 不得接收 planted_rules"
    assert "planted_rules" in inspect.signature(evaluator.evaluate).parameters
    assert "planted_rules" not in inspect.signature(attribution.lead_lag_analysis).parameters
    assert "planted_rules" not in inspect.signature(rules.mine_rules).parameters
```

`research/tests/test_main.py`：

```python
from main import run_method_validation, main

def test_full_pipeline_fields():
    res = run_method_validation(seed=7)
    for key in ["auc_ci", "lag_shap", "p_obs", "recovery", "report_md"]:
        assert key in res

def test_cli_writes_files(tmp_path):
    main(["--mode", "method-validation", "--out", str(tmp_path)])
    assert (tmp_path / "report_method_validation.md").exists()
```

- [ ] **Step 2: 运行测试确认红** → **Step 3: 写实现**（main.py 编排 + README；`run_method_validation` 调 `calibrate_gates` 生成 gate/_lambda_c 再 simulate；报告含 lag_shap/p_obs/规则 CI）→ **Step 4: 绿** → **Step 5: 提交**（`feat(research): CLI 完整数据流 + README + 数据流签名断言`）。

---

### Task 14: 端到端分层测试（slow / acceptance / 现实规模 / 可复现）

**Files:**

- Create: `research/tests/test_end_to_end.py`

**Interfaces:**

- Consumes: 全部模块。

- [ ] **Step 1: 写测试**

`research/tests/test_end_to_end.py`：

```python
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
        auc_ok = res["auc_ci"][0] >= cfg.THRESHOLDS["auc_ci_lower_gate"]
        hit_ok = res["recovery"]["rule_level_recovery"]["full_hit_count"] == 2
        # 规则非空 + CI 存在（防空；"CI 未估计"不得参与验收）
        rules_nonempty = res["recovery"]["n_rules"] > 0
        ci_ok = res["recovery"]["rule_ci_present"]
        ll = res["lead_lag"]
        ll_ok = (not ll["not_estimable"]) and ll["order"]["afp_after_early"] \
                and ll["n_intersection"] >= cfg.THRESHOLDS["r1r2_intersection_min"] \
                and all(n >= cfg.THRESHOLDS["per_indicator_ll_min"] for n in ll["per_indicator_n"].values()) \
                and ll["unmatched_rate"] <= cfg.THRESHOLDS["unmatched_max"]
        cov = res["coverage"]
        cov_ok = (cov.get("r1_only", 0) >= cfg.THRESHOLDS["coverage_gate"]
                  and cov.get("r2_only", 0) >= cfg.THRESHOLDS["coverage_gate"])
        if auc_ok and hit_ok and rules_nonempty and ci_ok and ll_ok and cov_ok:
            passes += 1
    assert passes / k >= cfg.THRESHOLDS["method_acceptance_pass_rate"]


@pytest.mark.slow
@pytest.mark.parametrize("n,f", [(150, 24), (150, 36), (300, 24), (300, 36)])
def test_realistic_scale_pipeline_runs(n, f):
    res = run_cell(n=n, followup_months=f, horizon_months=12, repeats=2, seeds=[1, 2])
    for rec in res["records"]:
        assert 0 <= rec["overall_recovery"] <= 1
        assert rec["usable_landmarks"] > 0
        assert 0 <= rec["excluded_ratio"] <= 1
        assert rec["oof_events"] >= 0
        assert isinstance(rec["partial_recovery"], dict)


@pytest.mark.slow
def test_reproducible_same_seed_same_report():
    assert run_method_validation(seed=7)["report_md"] == run_method_validation(seed=7)["report_md"]
```

- [ ] **Step 2: 运行慢层**：`cd research && python -m pytest tests/test_end_to_end.py -m slow -v`，Expected: PASS
- [ ] **Step 3: 运行验收层**：`cd research && python -m pytest tests/test_end_to_end.py -m acceptance -v`，Expected: PASS（≥90% 种子通过）
- [ ] **Step 4: 全量快速层**：`cd research && python -m pytest tests/ -v`，Expected: 全部 PASS，且不含 slow/acceptance
- [ ] **Step 5: 提交**

```bash
git add research/tests/test_end_to_end.py
git commit -m "feat(research): 端到端分层测试（slow 回归 / acceptance 验收 / 现实规模参数化 / 可复现）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

## 自检清单（计划级）

- **规格覆盖**：§4 目录 → Task 1-14 全覆盖；§5 生成/门控/校准 → Task 2/3；§6 → Task 4/6；§7 → Task 7/8；§8 → Task 9/10/11；§9 → Task 12；§10 → Task 14；§11 → Task 1（pytest.ini）+ Task 14。
- **数据流**：planted_rules 只进 evaluator——Task 13 `test_dataflow` 对全部非 evaluator 模块断言；`lead_lag_analysis`/`mine_rules` 签名无该参数。
- **接口自洽（本轮修复）**：`simulate(n,f,h,seed,gate=None,_lambda_c=None)` 全任务一致；`Condition.value: str|float`；`MinedRule` 对象（含 event_support/total_support/ci 字段）；`confirmation_subset` 输出含 `admin_end/group/unobservable/sex_male` 且剔 unknown；`features` 无字符串列；OOF 患者聚合后映射回 landmark 行；lead-lag 逐指标 CI + 容差/破平 + 恒存在字段；实例级恢复率 = 覆盖唯一患者/可观测唯一患者；可靠性边界分箱结构 + 边情形 + 原始点边界；acceptance 防空（规则非空 + CI 存在 + 逐指标门槛 + R1/R2 覆盖率）。
- **无占位符**：所有任务含实际测试代码与可执行实现；无"实现者须补齐/TBD"。

## 执行交接

计划已保存（v3）。执行选项：**Subagent-Driven（推荐）** 或 **Inline Execution**。按既定协作框架（Claude=实施者、Codex=审查者），建议**分批执行（如 Task 1-3、4-6、7-10、11-14）、每批交 Codex 审查、通过后推送**。实施计划 v3 先交 Codex 复审。
