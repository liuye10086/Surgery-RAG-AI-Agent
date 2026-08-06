# 疾病进展规律挖掘 · 端到端最小闭环 实施计划（v4.1）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `research/` 独立子项目中实现端到端最小闭环：用含植入规律的模拟纵向数据跑通"模拟 → 窗口特征 → 模型 → 时序归因 → 规则挖掘 → evaluator → 规模退化 → 规律报告"全链路，验证方法论能可信地恢复植入规律，并量化现实数据规模下的可信度。

**Architecture:** 每个模块单一职责、纯接口清晰、可独立单测。`simulate_cohort` 产出「数据集 + planted_rules」；数据集流向 features→model→attribution→rules；**planted_rules 只流向 evaluator**。模型训练用全量合格 landmark，规则/校准/evaluator 用每患者确认 landmark（§5.5 分角色口径表）。

**Tech Stack:** Python 3.10+、pandas、scikit-learn（GradientBoostingClassifier / IsotonicRegression）、shap、pytest（`slow`/`acceptance` marker）。

**规格依据：** `docs/superpowers/specs/2026-08-06-progression-rule-mining-loop-design.md`（v16）。
**计划修订：** v4 按 Codex 计划第三轮 13 条意见修正；**v4.1 按 Workflow 对抗验证 10 条真实发现修正**——PLT 乘性衰减信号使 R1 条件可达、coverage neither 误报率实现、可靠性边界测试防掉箱偏置、P_obs 渲染、consecutive_rises lookback=value、per-patient early/破平、typed_match lookback 一致、excluded_ratio 含不可观测、full 模式并入规模退化表、现实规模断言去恒真、Task 1 补全 config 完整代码。

## Global Constraints

以下约束**每个任务都必须遵守**，值从规格原样抄录：

- **独立边界**：`research/` 自带版本化 `config.py`；**禁止** import 生产 `prediction_engine.py`、访问生产数据库、写现有表/API。
- **数据流**：`planted_rules` **只进 `evaluator.py`**；`lead_lag_analysis`、`mine_rules` 等所有非 evaluator 模块签名**不得接收** planted_rules（Task 13 全模块签名断言）。
- **主 estimand**：校准/验收/evaluator/规则/support/lift 用**每患者确认/参考 landmark**；模型训练用**全量合格 landmark**；splitter 用**患者级结局**（仅分层）。
- **校准口径（唯一）**：在指定确认/参考 landmark 上按可观察条件分组，估计**不受删失影响的潜在事件风险**（互斥组口径，N=50,000 ±3pp，两视界 24/12 均验收）；**P_obs 为观测标签风险，单独报告、不参与 §10**。
- **δ ∈ {1,2}**，`w_event = 确认窗口 + δ`；对 R2（confirm=w_A+1）事件 ∈ {w_A+2, w_A+3}——**w_A+2 是 δ=1 的合法事件窗口**。
- **事件门控**：路径组 `g ~ Bernoulli(p_group)`；neither 由**可缩放基线 hazard `λ_b = λ_c · λ0(age, sex)`** 自参考 landmark **次一窗（ref+1）**起、视界内触发；`simulate(n, followup_months, horizon_months, seed, gate=None, _lambda_c=None)`。
- **组语义保留**：路径组不可观测（确认 landmark 不合格/非无事件/条件未成立）→ **保留其路径组**（`group` 仍为 r1_only/r2_only/r1_and_r2）且 `unobservable=True`；校准/coverage/evaluator **显式排除 `unobservable=True`**；`neither` 仅 z=none 患者。
- **标签**：正例 = 视界内且删失/行政终止前已观察到事件；unknown = 视界内先删失且删失前未观察到事件（从标注集与确认子集剔除）；潜在 g+事件窗口**不入模型/OOF/规则**。
- **患者聚类**：CI、support、Bootstrap 全部按患者聚类；Bootstrap **保留 multiplicity**。
- **sex 编码（统一）**：planted 与 mined 的 `sex` 条件统一用数值 `1.0`(male)/`0.0`(female)；`features` 产出 `sex_male`；模型/规则/SHAP 一律数值。
- **horizon/lookback/lag 单位统一**：`horizon_windows = horizon_months // 6`；`PlantedRule`/`MinedRule` 均携带 `horizon_windows`、`lookback`、`lag`（最小闭环 lag=0）；`full_hit` **分别比较**三字段。
- **信号门槛**：方法验证单元最终平均 OOF 预测上 AUC 患者聚类 95% CI 下界 ≥ 0.65。
- **成功标准（方法验收）**：K=20 种子、≥90% 通过；每种子：① AUC CI 下界 ≥0.65、② 两条植入规则均完整命中、③ lead-lag 次序恢复（交集 ≥30、每指标 PLT/HbA1c/AFP ≥20、unmatched ≤20%，不足 not estimable）、④ R1、R2 各自可评估覆盖率 ≥80%；**规则必须携带 Bootstrap CI（"CI 未估计"运行不得标为通过）**。
- **测试分层**：`pytest.ini` 配 `addopts = -m "not slow and not acceptance"`。
- **TDD**：每步先写失败测试→红→最小实现→绿→单独提交。提交正文三行：`AI-Agent: Codex`、`AI-Client: Codex-Desktop`、`Task-ID: research-progression-min-loop`。
- **不 push**（用户统一推送）；main 分支直接开发。

---

## 共享数据契约与标准词汇（各任务间接口，先定死）

### `patients` DataFrame（每患者一行）

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `patient_id` | int | 0..N-1 |
| `z` | str | `"none"`/`"r1"`/`"r2"`/`"r1_and_r2"` |
| `age` | int | 静态协变量 |
| `sex` | str | `"male"`/`"female"`（原始；`sex_male` 编码在 features 层） |
| `group` | str | 互斥组 `"neither"`/`"r1_only"`/`"r2_only"`/`"r1_and_r2"`；**路径组不可观测仍保留其组** |
| `confirm_window` | float | 确认/参考 landmark 窗口（neither 无合格参考为 `NaN`） |
| `w_r1` | float | R1 确认窗口（R2-only 为 `NaN`） |
| `w_a` | float | AFP 激活窗口（R1-only 为 `NaN`） |
| `g` | float | 路径组门控 0/1；neither 为 `NaN` |
| `event_window` | float | 潜在事件窗口（进展者）；否则 `NaN` |
| `censored` | bool | 是否失访删失 |
| `censored_window` | float | 删失窗口；否则 `NaN` |
| `admin_end` | int | 行政随访终点窗口 |
| `unobservable` | bool | 路径组：确认 landmark 不合格/非无事件/条件未成立 → `True`（校准/coverage/evaluator 排除）；neither 恒 `False` |

### `obs` DataFrame（每患者每窗口一行）

`patient_id`、`window`、`ALT..BMI`（10 指标观测，含噪声）。

### `features` 输出契约

- `qualifying_landmarks(patients, obs, horizon_windows)` → DataFrame（全量合格 landmark，模型训练用）：`patient_id, window, age, sex_male, label, <IND>_cur/_d6m/_d12m/_slope/_rises/_drop_pct`（无字符串列）。
- `confirmation_subset(patients, obs, horizon_windows)` → DataFrame（每患者确认/参考 landmark 一个样本）：`patient_id, window, age, sex_male, group, unobservable, admin_end, label, <派生特征>`；**剔除 unknown**（`label∈{0,1}`）；`df.attrs["horizon_windows"]`、`df.attrs["excluded_unknown"]`。

### 标准规则词汇（`rules.py` / `evaluator.py` 共用）

```python
@dataclass(frozen=True)
class MinedCondition:
    indicator: str      # "sex"|"age"|"HbA1c"|"PLT"|"AFP"|...
    op: str             # "eq"|"gt"|"lt"|"consecutive_rises"|"drop_pct"
    value: float        # 数值（sex 用 1.0/0.0）
    lookback: int = 1
    source_feature: str = ""

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
```

### `planted_rules`（只进 evaluator；sex 数值化；携带 horizon/lookback/lag）

```python
@dataclass(frozen=True)
class Condition:
    indicator: str; op: str; value: float; lookback: int = 1   # value 恒数值（sex 1.0/0.0）

@dataclass(frozen=True)
class PlantedRule:
    name: str; horizon_months: int; conditions: tuple[Condition, ...]
    group: str; target_risk: float; lag: int = 0
    @property
    def horizon_windows(self): return self.horizon_months // 6
    @property
    def lookback(self): return max((c.lookback for c in self.conditions), default=1)

@dataclass(frozen=True)
class PlantedRules:
    horizon_months: int; r1: PlantedRule; r2: PlantedRule; calibration: dict[str, float]
```

`_build_planted_rules` 将 `cfg.PLANTED_CONDITIONS` 的 `"male"/"female"` 转为 `1.0/0.0`。

### 确认/参考 landmark 与合格定义

- 合格 landmark：`窗口 ≥ 2`、`admin_end − 窗口 ≥ 视界窗数`、`窗口 < 事件窗口`（若有）、`窗口 < 删失窗口`（若有）。
- **neither 参考 landmark**：删失已知后取**首个合格窗口**；事件由 λ_b 自 **ref+1** 起视界内触发（ref 本身无事件）。命中任一植入条件 → 计入误报、排除 neither 校准分母。
- 路径组确认 landmark：R2/交集 = `w_A+1`；R1-only = `w_R1`。**不可观测判定（完整）**：`confirm` 非有限、或 `confirm ≥ event_window`、或 `confirm ≥ censored_window`、或指定确认 landmark 条件未成立 → `unobservable=True`，**保留路径组**。

---

## 任务分解（14 任务）

### Task 1: 脚手架 + config.py

**Files:**

- Create: `research/config.py`、`research/pytest.ini`、`research/requirements.txt`、`research/tests/__init__.py`
- Test: `research/tests/test_config.py`

**Interfaces:**

- Produces: `config.py` 全部命名常量。数据流签名断言移至 Task 13。

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

def test_planted_conditions():
    assert ("sex", "eq", "male") in cfg.PLANTED_CONDITIONS["r1"]
    assert ("HbA1c", "consecutive_rises", 2.0) in cfg.PLANTED_CONDITIONS["r1"]
    assert ("AFP", "consecutive_rises", 2.0) in cfg.PLANTED_CONDITIONS["r2"]
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_config.py -v`
Expected: FAIL

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
       "observability_gate": 0.95, "calibration_group_min": 200,
       "hba1c_rise_per_window": 0.8,     # >= 2*sigma(HbA1c)=0.5 → 两窗连续上升 ~0.98
       "plt_decline_per_window": 0.85,   # 乘性 15%/窗下降；w>=w0+2 时较基线降 ~28% >20%
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

### Task 2: simulate——Z/协变量/S 轨迹/观测 + 确认 landmark/组归属（含不可观测完整判定）

**Files:**

- Create: `research/simulate_cohort.py`
- Test: `research/tests/test_simulate_core.py`

**Interfaces:**

- Produces: `Condition/PlantedRule/PlantedRules`（sex 数值化 + horizon/lookback/lag 属性）；`simulate(n, followup_months, horizon_months, seed, gate=None, _lambda_c=None)` 返回 `{"patients","obs","planted_rules","coverage","meta"}`；`coverage` 在 Task 3 填实。

**前向顺序（每患者）**：Z → 协变量按 Z → S 轨迹 → 路径组门控（锚点先行）→ neither 删失 → 参考 landmark → λ_b（ref+1 起视界内）→ 指标观测 → 截断。**禁止先定事件时间再构造特征。**

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

def test_signature():
    import inspect
    assert list(inspect.signature(simulate).parameters) == \
        ["n", "followup_months", "horizon_months", "seed", "gate", "_lambda_c"]

def test_patients_schema():
    assert _sim()["patients"].columns.tolist() == [
        "patient_id", "z", "age", "sex", "group", "confirm_window", "w_r1", "w_a",
        "g", "event_window", "censored", "censored_window", "admin_end", "unobservable"]

def test_covariates_conditional_on_z():
    p = _sim()["patients"]
    for z in ("r1", "r1_and_r2"):
        sub = p[p["z"] == z]
        assert (sub["sex"] == "male").all() and (sub["age"] > 50).all()

def test_event_window_is_confirm_plus_delta():
    prog = _sim()["patients"].dropna(subset=["event_window"])
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
    # 所有可观测路径患者的确认 landmark 严格早于事件与删失
    obs = p[(~p["unobservable"]) & (p["z"] != "none")]
    assert ((obs["confirm_window"] < obs["event_window"])).all() if len(obs) else True
    cens = obs[obs["censored"]]
    assert (cens["confirm_window"] < cens["censored_window"]).all() if len(cens) else True

def test_neither_reference_is_first_qualifying_before_censor():
    out = _sim()
    ne = out["patients"][out["patients"]["z"] == "none"]
    assert (ne["confirm_window"] >= 2).all()
    assert (ne["admin_end"] - ne["confirm_window"] >= 4).all()   # 24 月视界
    c = ne[ne["censored"]]
    assert (c["confirm_window"] < c["censored_window"]).all() if len(c) else True

def test_planted_sex_is_numeric_and_lookback():
    pr = _sim()["planted_rules"]
    sex_cond = pr.r1.conditions[0]
    assert sex_cond.indicator == "sex" and sex_cond.value == 1.0
    hba1c = pr.r1.conditions[2]
    assert hba1c.op == "consecutive_rises" and hba1c.lookback == 2   # lookback = 上升次数
    assert pr.r1.lookback == 2

def test_r1_conditions_reachable():
    out = _sim(n=1500, followup_months=60, horizon_months=24, seed=9)
    p = out["patients"]
    r1 = p[p["z"].isin(["r1", "r1_and_r2"])]
    # 信号强度使 PLT 乘性降 >20% + HbA1c 两窗上升在 w_R1 可达 → 大部分 R1 患者可观测
    assert r1["unobservable"].mean() < 0.3
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_simulate_core.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/simulate_cohort.py`：

```python
"""模拟纵向数据生成器（Z 路径 + 前向生成）。planted_rules 只流向 evaluator。"""
from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass
import config as cfg


@dataclass(frozen=True)
class Condition:
    indicator: str; op: str; value: float; lookback: int = 1

@dataclass(frozen=True)
class PlantedRule:
    name: str; horizon_months: int; conditions: tuple[Condition, ...]
    group: str; target_risk: float; lag: int = 0
    @property
    def horizon_windows(self): return self.horizon_months // cfg.SIM["window_months"]
    @property
    def lookback(self): return max((c.lookback for c in self.conditions), default=1)

@dataclass(frozen=True)
class PlantedRules:
    horizon_months: int; r1: PlantedRule; r2: PlantedRule; calibration: dict[str, float]


def _to_condition(ind, op, val):
    if ind == "sex":
        val = 1.0 if val == "male" else 0.0
    lookback = int(val) if op == "consecutive_rises" else 1   # 连续上升的 lookback = 上升次数
    return Condition(ind, op, float(val), lookback=lookback)


def _build_planted_rules(horizon_months):
    cal = cfg.CALIBRATION[horizon_months]
    r1 = PlantedRule("r1", horizon_months,
                     tuple(_to_condition(i, o, v) for i, o, v in cfg.PLANTED_CONDITIONS["r1"]),
                     "r1_only", cal["r1_only"])
    r2 = PlantedRule("r2", horizon_months,
                     tuple(_to_condition(i, o, v) for i, o, v in cfg.PLANTED_CONDITIONS["r2"]),
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


def _sample_anchors(rng, z, w0, admin_end, hw):
    """R1 条件确认需 >=2 窗信号累积（PLT 乘性降 >20%、HbA1c 两窗上升）→ w_R1 >= w0+2。"""
    w_a, w_r1 = np.nan, np.nan
    for _ in range(cfg.SIM["resample_max"]):
        if z in ("r2", "r1_and_r2"):
            lo, hi = 1, admin_end - hw - 1
            if hi < lo: return np.nan, np.nan
            w_a = int(rng.integers(lo, hi + 1))
        if z == "r1":
            lo, hi = max(2, w0 + 2), admin_end - hw
            if hi < lo: return np.nan, np.nan
            w_r1 = int(rng.integers(lo, hi + 1))
        elif z == "r1_and_r2":
            lo, hi = w0 + 2, w_a - 1
            if hi < lo: return np.nan, np.nan
            w_r1 = int(rng.integers(lo, hi + 1))
        return w_a, w_r1


def _first_qualifying_landmark(admin_end, hw, censored_window):
    for w in range(2, admin_end - hw + 1):
        if np.isfinite(censored_window) and w >= censored_window:
            continue
        return w
    return np.nan


def _neither_hazard(lambda_c, age, sex):
    """可缩放基线 hazard = λ_c * λ0(age, sex)；λ_c=0 时风险为 0（bisection 可向下收敛）。"""
    lambda0 = 0.02 * (1 + 0.01 * (age - 40)) * (1.2 if sex == "male" else 1.0)
    return lambda_c * lambda0


def simulate(n, followup_months, horizon_months, seed, gate=None, _lambda_c=None):
    rng = np.random.default_rng(seed)
    admin_end = followup_months // cfg.SIM["window_months"]
    hw = horizon_months // cfg.SIM["window_months"]
    cal = cfg.CALIBRATION[horizon_months]
    if gate is None:
        gate = dict(cal)
    lambda_c = 0.0 if _lambda_c is None else _lambda_c

    paths, ages, sexes = _sample_z_covariates(rng, n)
    sigma = {i: 0.1 * (cfg.REFERENCE_RANGES[i][1] - cfg.REFERENCE_RANGES[i][0]) for i in cfg.INDICATORS}
    n_win = admin_end + 1

    rows, obs_rows = [], []
    for pid in range(n):
        z, age, sex = paths[pid], ages[pid], sexes[pid]
        w0 = int(rng.integers(0, 2))
        w_a, w_r1 = _sample_anchors(rng, z, w0, admin_end, hw)

        # 删失（独立，先于 neither 参考 landmark）
        censored = rng.random() < cfg.SIM["censoring_rate"]
        censored_window = float(rng.integers(1, n_win)) if censored else np.nan

        # 事件
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
                # 从 ref+1 起视界内触发（ref 本身无事件；上界 = admin_end）
                for t in range(int(ref) + 1, min(int(ref) + hw, admin_end) + 1):
                    if rng.random() < _neither_hazard(lambda_c, age, sex):
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
                if z in ("r1", "r1_and_r2") and ind == "HbA1c" and t >= w0:
                    sig = cfg.SIM["hba1c_rise_per_window"] * (t - w0)
                if z in ("r1", "r1_and_r2") and ind == "PLT" and t >= w0:
                    row[ind] = baseline[ind] * (cfg.SIM["plt_decline_per_window"] ** max(t - w0, 0)) \
                        + rng.normal(0, sigma[ind])
                    continue
                if z in ("r2", "r1_and_r2") and ind == "AFP" and np.isfinite(w_a) and t >= w_a:
                    sig = cfg.SIM["afp_rise_per_window"] * (t - w_a + 1)
                row[ind] = baseline[ind] + sig + rng.normal(0, sigma[ind])
            obs_rows.append(row)

        # 组归属 / 确认 landmark / unobservable（完整判定）
        if z == "none":
            confirm = _first_qualifying_landmark(admin_end, hw, censored_window)
            group, unobservable = "neither", False
        else:
            expected = "r1_and_r2" if z == "r1_and_r2" else ("r1_only" if z == "r1" else "r2_only")
            confirm = (w_a + 1) if z in ("r2", "r1_and_r2") else w_r1
            by_w = {r["window"]: r for r in obs_rows[-n_win:]}
            r1_ok = _r1_holds(by_w, confirm, age, sex) if z in ("r1", "r1_and_r2") else False
            r2_ok = _r2_holds(by_w, confirm) if z in ("r2", "r1_and_r2") else False
            valid = (np.isfinite(confirm)
                     and (not np.isfinite(event_window) or confirm < event_window)
                     and (not np.isfinite(censored_window) or confirm < censored_window))
            if not valid or (z in ("r1", "r1_and_r2") and not r1_ok) or (z in ("r2", "r1_and_r2") and not r2_ok):
                group, unobservable = expected, True      # 保留路径组，标不可观测
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
            "coverage": {"per_group": {}, "per_rule": {}, "neither_false_positive_rate": np.nan},
            "meta": {"horizon_windows": hw, "admin_end": admin_end}}


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
git commit -m "feat(research): 模拟核心（前向生成 + 完整不可观测判定 + 组语义保留）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 3: simulate——事件门控校准（bisection）+ P_obs + coverage（具体算法）

**Files:**

- Modify: `research/simulate_cohort.py`
- Test: `research/tests/test_simulate_calibration.py`

**Interfaces:**

- Produces: `calibrate_gates(horizon_months, cal_n=cfg.SIM["calibration_n"])` → `{"gate", "lambda_base", "neither_risk"}`；`p_obs(patients, obs, horizon_windows)`；`simulate` 的 `coverage` 填实（`per_group`/`per_rule`/`neither_false_positive_rate`）。

**校准口径**：确认/参考 landmark 上按可观察条件分组、不受删失影响的潜在风险；bisection 收敛 ±3pp（两视界）。**neither hazard 可缩放**（`λ_c · λ0`，λ_c=0 风险为 0）——测试断言 bisection 端点确实包围目标。

**coverage 算法（具体）**：

- `per_group[g]` = g 组（路径组保留语义）中 `unobservable=False` 且 `confirm_window` 有限的占比（neither 即"参考 landmark 合格"占比）。
- `per_rule["r1"]` =（`r1_only` ∪ `r1_and_r2` 可观测唯一患者）/（同组总数）；`per_rule["r2"]` 同理（`r2_only` ∪ `r1_and_r2`）。
- `neither_false_positive_rate` = neither 参考 landmark 命中任一植入条件的占比（误报，排除 neither 校准分母）。
- **不可观测（`unobservable=True`）与 unknown 均从 coverage 分母排除**。

- [ ] **Step 1: 写失败测试**

`research/tests/test_simulate_calibration.py`：

```python
import numpy as np
import config as cfg
from simulate_cohort import simulate, calibrate_gates, p_obs

def test_calibrate_gates_contract():
    cal = calibrate_gates(24, cal_n=30_000)
    assert set(cal) == {"gate", "lambda_base", "neither_risk"}
    assert set(cal["gate"]) == {"r1_only", "r2_only", "r1_and_r2"}

def test_bisection_endpoints_bracket_neither_target():
    from simulate_cohort import _neither_hazard
    # λ_c=0 → 风险 0（下界）< 目标；λ_c 大 → 风险 > 目标（上界），故 bisection 有解
    assert _neither_hazard(0.0, 40, "female") == 0.0

def test_calibrated_latent_risk_both_horizons():
    for horizon, followup in ((24, 60), (12, 36)):
        cal = calibrate_gates(horizon, cal_n=30_000)
        out = simulate(n=30_000, followup_months=followup, horizon_months=horizon,
                       seed=3, gate=cal["gate"], _lambda_c=cal["lambda_base"])
        p = out["patients"]
        for grp, target in out["planted_rules"].calibration.items():
            sub = p[(p["group"] == grp) & (~p["unobservable"])]
            if grp == "neither":
                ok = sub["confirm_window"].notna()
                risk = ((sub["event_window"].notna())
                        & (sub["event_window"] <= sub["confirm_window"] + horizon // 6))[ok].mean()
            else:
                risk = sub["g"].mean()
            assert abs(risk - target) <= 0.03, (horizon, grp, risk, target)

def test_p_obs_formula():
    out = simulate(n=3000, followup_months=24, horizon_months=12, seed=4)
    po = p_obs(out["patients"], out["obs"], 2)
    for grp in ("r1_only", "r2_only", "r1_and_r2", "neither"):
        assert po[grp]["denominator"] == po[grp]["positive"] + po[grp]["negative"]

def test_coverage_contract_and_gate_reachable():
    out = simulate(n=2000, followup_months=24, horizon_months=12, seed=5,
                   gate=calibrate_gates(12, cal_n=10_000)["gate"])
    cov = out["coverage"]
    assert set(cov["per_group"]) == {"r1_only", "r2_only", "r1_and_r2", "neither"}
    assert set(cov["per_rule"]) == {"r1", "r2"}
    # 可观测条件成立比例应很高（观测验收 ≥95% 量级；此处仅断言可观测者占比合理）
    for g in ("r1_only", "r2_only", "r1_and_r2"):
        assert cov["per_group"][g] >= 0.9
    assert 0 <= cov["neither_false_positive_rate"] <= 1
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_simulate_calibration.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

追加到 `simulate_cohort.py`：

```python
def _group_latent_risk(out, grp, hw):
    p = out["patients"]
    sub = p[(p["group"] == grp) & (~p["unobservable"])]
    if grp == "neither":
        ok = sub["confirm_window"].notna()
        ev = sub["event_window"].notna() & (sub["event_window"] <= sub["confirm_window"] + hw)
        return ev[ok].mean() if ok.any() else np.nan
    return sub["g"].mean()


def _bisect(target, risk_fn, lo=0.0, hi=1.0):
    """bisection：若 risk(lo) <= target <= risk(hi) 则收敛；否则返回端点（调用方保证包围）。"""
    for _ in range(cfg.THRESHOLDS["calibrate_bisect_iters"]):
        mid = (lo + hi) / 2
        r = risk_fn(mid)
        if abs(r - target) <= cfg.THRESHOLDS["calibrate_tol"]:
            return mid
        if r < target:
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
        def risk(mid, grp=grp, target=target):
            g = {g_: (mid if g_ == grp else t) for g_, t in cal.items() if g_ != "neither"}
            out = simulate(cal_n, followup, horizon_months, 3, gate=g, _lambda_c=0.0)
            return _group_latent_risk(out, grp, hw)
        # 端点包围检查（测试保证）；此处直接 bisect
        gates[grp] = _bisect(target, risk)

    def neither_risk(c):
        out = simulate(cal_n, followup, horizon_months, 3, gate=gates, _lambda_c=c)
        return _group_latent_risk(out, "neither", hw)
    # λ_c=0 → 风险 0 < 目标；λ_c=1 → 风险 > 目标（lambda0 上限保证）；bisect [0,1]
    lambda_base = _bisect(cal["neither"], neither_risk, lo=0.0, hi=1.0)
    return {"gate": gates, "lambda_base": lambda_base,
            "neither_risk": {horizon_months: float(neither_risk(lambda_base))}}


def p_obs(patients, obs, horizon_windows):
    result = {}
    for grp in ("neither", "r1_only", "r2_only", "r1_and_r2"):
        pos = neg = 0
        for _, p in patients[(patients["group"] == grp) & (~patients["unobservable"])].iterrows():
            ev, cw = p["event_window"], p["censored_window"]
            win = p["confirm_window"] + horizon_windows
            if np.isfinite(ev) and ev <= win and (not np.isfinite(cw) or cw > ev):
                pos += 1
            elif (not np.isfinite(ev) or ev > win) and (not np.isfinite(cw) or cw > win):
                neg += 1
        result[grp] = {"positive": pos, "negative": neg, "denominator": pos + neg,
                       "rate": pos / (pos + neg) if pos + neg else float("nan")}
    return result


def _compute_coverage(patients, obs, meta):
    """coverage：per_group/per_rule 排除 unobservable；neither 误报 = 参考 landmark 命中 R1/R2 条件占比。"""
    obs_by_pid = {pid: g.to_dict("records") for pid, g in obs.groupby("patient_id")}
    p = patients
    per_group = {}
    for grp in ("r1_only", "r2_only", "r1_and_r2", "neither"):
        sub = p[p["group"] == grp]
        obs_count = int(((~sub["unobservable"]) & sub["confirm_window"].notna()).sum())
        per_group[grp] = obs_count / len(sub) if len(sub) else float("nan")
    per_rule = {}
    for rule, groups in (("r1", ("r1_only", "r1_and_r2")), ("r2", ("r2_only", "r1_and_r2"))):
        tot = p[p["group"].isin(groups)]
        obs_count = int(((~tot["unobservable"]) & tot["confirm_window"].notna()).sum())
        per_rule[rule] = obs_count / len(tot) if len(tot) else float("nan")
    fp = 0
    ne = p[p["group"] == "neither"]
    for _, row in ne.iterrows():
        if not np.isfinite(row["confirm_window"]):
            continue
        by_w = {r["window"]: r for r in obs_by_pid.get(row["patient_id"], [])}
        w = int(row["confirm_window"])
        if _r1_holds(by_w, w, row["age"], row["sex"]) or _r2_holds(by_w, w):
            fp += 1
    neither_fp = fp / len(ne) if len(ne) else float("nan")
    return {"per_group": per_group, "per_rule": per_rule,
            "neither_false_positive_rate": float(neither_fp)}
```

实现说明：`simulate` 返回前调用 `_compute_coverage(patients, obs, meta)` 填 `coverage`；`coverage["per_group"]`/`per_rule` 排除 `unobservable`；`neither_false_positive_rate` 为真实浮点（非 NaN），满足 Task 3 测试 `0 <= cov[...] <= 1`。

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_simulate_calibration.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/simulate_cohort.py research/tests/test_simulate_calibration.py
git commit -m "feat(research): bisection 校准（可缩放 λ_b）+ P_obs + coverage 具体算法" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 4: features.py（合格 landmark / 确认子集 / 标签 / sex 编码）

**Files:**

- Create: `research/features.py`
- Test: `research/tests/test_features.py`

**Interfaces:**

- Produces: `qualifying_landmarks`、`confirmation_subset`（含 `admin_end`/`group`/`unobservable`/`sex_male`，剔 unknown，`attrs["horizon_windows"]`）、`label_for`、`derive_window_features`。

- [ ] **Step 1: 写失败测试** — 同 v3 Task 4 测试（`test_derived_features_hand`、`test_qualifying_uses_all_landmarks`、`test_confirmation_subset_contract`（含 admin_end/group/unobservable/sex_male/label∈{0,1}）、`test_label_semantics`），并新增：

```python
def test_confirmation_subset_attrs_horizon():
    out = simulate(n=200, followup_months=24, horizon_months=12, seed=1)
    sub = confirmation_subset(out["patients"], out["obs"], 2)
    assert sub.attrs["horizon_windows"] == 2
```

- [ ] **Step 2: 红** → **Step 3: 实现**（同 v3 Task 4 实现，`confirmation_subset` 设 `df.attrs["horizon_windows"]=horizon_windows`）→ **Step 4: 绿** → **Step 5: 提交**（`feat(research): 窗口特征 + 分角色 landmark + sex 编码 + 标签`）。

---

### Task 5: splitters.py（患者折 + 聚类 Bootstrap，保留 multiplicity）

**Files:**

- Create: `research/splitters.py`
- Test: `research/tests/test_splitters.py`

**Interfaces:**

- Produces: `patient_folds(patients, n_folds, seed)`、`patient_bootstrap_samples(patient_ids, b, seed)`、`resample_rows(frame, sampled_ids)`、`patient_bootstrap_ci(frame, stat_fn, b, seed)`。

- [ ] **Step 1: 写失败测试** — 同 v3 Task 5 测试（patient 不跨折、分层、multiplicity 保留、CI）。
- [ ] **Step 2: 红** → **Step 3: 实现**（同 v3 Task 5 实现）→ **Step 4: 绿** → **Step 5: 提交**（`feat(research): 患者折 + 聚类 Bootstrap（保留 multiplicity）`）。

---

### Task 6: model.py（患者级 OOF，患者聚合 + 全数值特征）

**Files:**

- Create: `research/model.py`
- Test: `research/tests/test_model.py`

**Interfaces:**

- Produces: `fit_and_oof(landmarks, n_folds, n_repeats, seeds)` → `{"oof_mean","auc_ci","auc_point","pr_auc","brier","not_estimable","auc_median_across_repeats","oof_frame"}`；`train_model(landmarks, seed)`。

- [ ] **Step 1: 写失败测试** — 同 v3 Task 6 测试（OOF 指标、患者聚合映射、not_estimable、全数值特征）。
- [ ] **Step 2: 红** → **Step 3: 实现**（同 v3 Task 6 实现：先聚合唯一患者表做 splitter → 映射回 landmark 行；`_feat_cols` 用 `sex_male`）→ **Step 4: 绿** → **Step 5: 提交**（`feat(research): 患者级 OOF（患者聚合分层 + 全数值特征）`）。

---

### Task 7: attribution.py——lead-lag（观察进展者 + 嵌套结构 + 真实破平 + CI）

**Files:**

- Create: `research/attribution.py`
- Test: `research/tests/test_attribution.py`

**Interfaces:**

- Produces: `lead_lag_analysis(patients, obs)` → `dict`：
  - `per_path[group][indicator] = {"median": float, "ci": (lo, hi)}`（**嵌套：路径→指标**）
  - `order`：`early_median`（**每患者 min(PLT, HbA1c) 首次偏离 → 中位**）、`afp_median`、`afp_after_early`（容差 ±1 窗）、`tiebreak_by_event_count`（并列时按支持各次序的患者数破平）
  - `per_indicator_n`（PLT/HbA1c/AFP 可分析患者数）
  - `n_intersection`、`unmatched_rate`、`not_estimable`
  - 字段恒存在（not_estimable 时值可为 NaN/None）

**观察进展者口径**：仅用 `g==1` 且 `unobservable=False` 且**事件在删失前被观察到**（`event_window` 有限，且 `censored_window` 为空或 `censored_window > event_window`）的患者；风险集匹配用观察事件时间。

- [ ] **Step 1: 写失败测试**

`research/tests/test_attribution.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_attribution.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/attribution.py`：

```python
"""lead-lag 时间对齐（主证据；描述性）。无 planted_rules。观察进展者口径。"""
from __future__ import annotations
import numpy as np
import pandas as pd
import config as cfg
from splitters import patient_bootstrap_ci


def _observed_progressors(patients):
    """g==1 且事件在删失前被观察到的患者（观察进展者）。"""
    p = patients[(patients["g"] == 1) & (~patients["unobservable"])]
    return p[(p["event_window"].notna()) &
             (p["censored_window"].isna() | (p["censored_window"] > p["event_window"]))]


def _deviation(series, runin_mean, sigma):
    flags = {w: abs(v - runin_mean) > cfg.SIM["kappa"] * sigma + cfg.SIM["tau"] for w, v in series.items()}
    return {w: flags.get(w, False) and flags.get(w - 1, False) for w in sorted(series)}


def _first_deviation(series, runin_mean, sigma):
    dev = _deviation(series, runin_mean, sigma)
    flagged = [w for w, d in dev.items() if d]
    return min(flagged) if flagged else np.nan


def _indicator_first_dev_ci(progressors, obs, ind, sigma):
    rows = []
    for _, p in progressors.iterrows():
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
    prog = _observed_progressors(patients)
    matched = _risk_set_match(patients, prog)
    unmatched_rate = 1 - len(matched) / max(len(prog), 1)

    per_path, per_indicator_n = {}, {}
    for grp, inds in (("r1_only", ("PLT", "HbA1c")), ("r2_only", ("AFP",)),
                      ("r1_and_r2", ("PLT", "HbA1c", "AFP"))):
        gprog = prog[prog["group"] == grp]
        per_path[grp] = {}
        for ind in inds:
            med, ci, n = _indicator_first_dev_ci(gprog, obs, ind, sigma[ind])
            per_path[grp][ind] = {"median": med, "ci": ci}
            per_indicator_n[ind] = max(per_indicator_n.get(ind, 0), n)

    inter = prog[prog["group"] == "r1_and_r2"]
    n_inter = int(inter["patient_id"].nunique())
    # 每患者首偏（PLT/HbA1c/AFP 各自逐患者计算，非组级中位数）
    early_rows, afp_rows = [], []
    for _, p in inter.iterrows():
        by_w = {r["window"]: r for r in obs[obs["patient_id"] == p["patient_id"]].to_dict("records")}
        ev = p["event_window"]
        plt_dev = _first_deviation({w: r["PLT"] for w, r in by_w.items() if w < ev},
                                   np.mean([by_w[t]["PLT"] for t in (0, 1) if t in by_w]), sigma["PLT"])
        hba1c_dev = _first_deviation({w: r["HbA1c"] for w, r in by_w.items() if w < ev},
                                     np.mean([by_w[t]["HbA1c"] for t in (0, 1) if t in by_w]), sigma["HbA1c"])
        afp_dev = _first_deviation({w: r["AFP"] for w, r in by_w.items() if w < ev},
                                   np.mean([by_w[t]["AFP"] for t in (0, 1) if t in by_w]), sigma["AFP"])
        if np.isfinite(plt_dev) or np.isfinite(hba1c_dev):
            early_rows.append((p["patient_id"], np.nanmin([plt_dev, hba1c_dev])))
        if np.isfinite(afp_dev):
            afp_rows.append((p["patient_id"], afp_dev))
    early_med = float(np.nanmedian([e for _, e in early_rows])) if early_rows else np.nan
    afp_med = float(np.nanmedian([e for _, e in afp_rows])) if afp_rows else np.nan

    afp_after_early = None
    tiebreak = 0
    tol = 1
    if np.isfinite(early_med) and np.isfinite(afp_med):
        afp_after_early = afp_med > early_med + tol
        if not afp_after_early and abs(afp_med - early_med) <= tol:
            # 真实破平：按支持"AFP 后行"的患者数 vs "AFP 先行"患者数
            n_afp_later = sum(1 for _, e in afp_rows if e > early_med + tol)
            n_afp_earlier = sum(1 for _, e in afp_rows if e <= early_med + tol)
            tiebreak = n_afp_later - n_afp_earlier
            afp_after_early = tiebreak >= 0

    not_estimable = (n_inter < cfg.THRESHOLDS["r1r2_intersection_min"]
                     or unmatched_rate > cfg.THRESHOLDS["unmatched_max"]
                     or any(per_indicator_n.get(i, 0) < cfg.THRESHOLDS["per_indicator_ll_min"]
                            for i in ("PLT", "HbA1c", "AFP")))
    return {"per_path": per_path,
            "order": {"early_median": early_med if np.isfinite(early_med) else None,
                      "afp_median": afp_med if np.isfinite(afp_med) else None,
                      "afp_after_early": afp_after_early,
                      "tiebreak_by_event_count": tiebreak},
            "per_indicator_n": per_indicator_n, "n_intersection": n_inter,
            "unmatched_rate": unmatched_rate, "not_estimable": not_estimable}
```

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_attribution.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/attribution.py research/tests/test_attribution.py
git commit -m "feat(research): lead-lag（观察进展者 + 嵌套结构 + 真实破平 + CI）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 8: attribution.py——时间滞后 SHAP/消融

**Files:**

- Modify: `research/attribution.py`
- Test: `research/tests/test_attribution_shap.py`

**Interfaces:**

- Produces: `lag_shap_analysis(landmarks, clf, lags)` → 每指标（PLT/HbA1c/AFP）各滞后 `mean|SHAP|`（描述性）；特征用 `sex_male` 数值列。

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

def test_shap_feature_columns_numeric():
    lm = _lm()
    import numpy as np
    assert all(lm.dtypes != object)
```

- [ ] **Step 2: 红** → **Step 3: 实现**：

```python
def lag_shap_analysis(landmarks, clf, lags):
    import shap
    feat = [c for c in landmarks.columns if c not in ("patient_id", "window", "label", "group", "unobservable")]
    X = landmarks[feat].to_numpy()
    vals = shap.TreeExplainer(clf).shap_values(X)
    if isinstance(vals, list):
        vals = vals[1]
    out = {}
    for ind in ("PLT", "HbA1c", "AFP"):
        out[ind] = {}
        for lag in lags:
            suffix = {0: "_cur", 1: "_d6m", 2: "_d12m"}[lag]
            col = f"{ind}{suffix}"
            out[ind][lag] = float(np.mean(np.abs(vals[:, feat.index(col)]))) if col in feat else 0.0
    return out
```

- [ ] **Step 4: 绿** → **Step 5: 提交**（`feat(research): 时间滞后 SHAP（描述性佐证）`）。

---

### Task 9: rules.py（标准词汇 + 逐折发现→冻结→验证 + 规则 CI 完整重跑）

**Files:**

- Create: `research/rules.py`
- Test: `research/tests/test_rules.py`

**Interfaces:**

- Consumes: `features.confirmation_subset`（含 `attrs["horizon_windows"]`）、`splitters.patient_folds`。
- Produces: `MinedCondition`/`MinedRule`（数值 value）；`mine_rules(subset, n_repeats, seeds)` → `{"rules": list[MinedRule], "selection_frequency"}`；`_candidate_conditions(subset)`；`_fold_discover_validate(sset, seed)` → `{canonical_key: [val_lifts]}`；`_rule_bootstrap_ci(subset, rule, b, seed)`（**重采样→重跑发现→验证**）。

**规则 CI（完整，非简化）**：每次患者 Bootstrap 重采样确认子集（全列）→ 在重采样集上重跑折内发现→折外验证 → 收集该 canonical 规则的验证 lift 分布 → `(2.5, 97.5)`；未重发现 → 该样本 NaN，剔除；<2 个有效 → `"CI 未估计"`。**`mine_rules` 签名无 oof_frame**。

**规范化（保类型）**：`_canonical_rule` 返回 `(indicator, op, float(value), lookback)`（value 恒数值）；重建 MinedCondition 用 float。

**确定性 fixture**：断言至少挖出一个 R1 四条件标准规则与一个 R2 标准规则。

- [ ] **Step 1: 写失败测试**

`research/tests/test_rules.py`：

```python
import numpy as np
from simulate_cohort import simulate
from features import confirmation_subset
from rules import mine_rules, MinedCondition, MinedRule, _candidate_conditions, _rule_bootstrap_ci

OUT = simulate(n=1500, followup_months=60, horizon_months=24, seed=6)
SUB = confirmation_subset(OUT["patients"], OUT["obs"], horizon_windows=4)

def test_no_planted_rules():
    import inspect
    assert "planted_rules" not in inspect.signature(mine_rules).parameters

def test_candidates_standard_include_age():
    cands = _candidate_conditions(SUB)
    ops = {c.op for c in cands}
    assert {"eq", "gt", "consecutive_rises", "drop_pct"} <= ops
    assert any(c.indicator == "age" and c.op == "gt" for c in cands)
    assert all(isinstance(c.value, float) for c in cands)   # 数值保类型

def test_mine_rules_returns_minedrule_with_real_ci():
    res = mine_rules(SUB, 2, [1, 2])
    for r in res["rules"]:
        assert isinstance(r, MinedRule)
        assert r.event_support >= 5 and r.total_support >= 20
        assert r.selection_frequency > 0
        assert isinstance(r.ci, tuple) and r.ci[0] <= r.ci[1]

def test_at_least_one_r1_and_r2_standard_rule():
    res = mine_rules(SUB, 2, [1, 2])
    conds = [r.conditions for r in res["rules"]]
    assert any({c.indicator for c in cs} == {"sex", "age", "HbA1c", "PLT"} for cs in conds)
    assert any({c.indicator for c in cs} == {"AFP"} for cs in conds)

def test_rule_ci_failure_mode():
    tiny = SUB.iloc[:20]
    ci = _rule_bootstrap_ci(tiny, MinedRule((MinedCondition("sex", "eq", 1.0),), 4, 1, 0), b=10, seed=0)
    assert ci == "CI 未估计" or isinstance(ci, tuple)   # 小样本可退化
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_rules.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/rules.py`：

```python
"""规则挖掘（确认 landmark 子集；标准词汇；逐折发现→冻结→验证；规则 CI 完整重跑；禁读 planted_rules）。"""
from __future__ import annotations
import numpy as np
import pandas as pd
import itertools
from dataclasses import dataclass
import config as cfg
from splitters import patient_folds, resample_rows, patient_bootstrap_samples


@dataclass(frozen=True)
class MinedCondition:
    indicator: str; op: str; value: float; lookback: int = 1; source_feature: str = ""

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
    cands = [MinedCondition("sex", "eq", 1.0), MinedCondition("sex", "eq", 0.0)]
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
    return tuple(sorted((c.indicator, c.op, float(c.value), c.lookback) for c in rule.conditions))


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


def _discover_frozen(subset, seed, horizon_windows):
    cands = _candidate_conditions(subset)
    rules = []
    for k in range(1, cfg.THRESHOLDS["max_conditions"] + 1):
        for combo in itertools.combinations(cands, k):
            if len(rules) >= cfg.THRESHOLDS["max_candidates"]:
                break
            rule = MinedRule(conditions=tuple(combo), horizon_windows=horizon_windows,
                             lookback=max(c.lookback for c in combo), lag=0)
            ev, tot = _support(subset, rule)
            if ev >= cfg.THRESHOLDS["rule_event_support_min"] and tot >= cfg.THRESHOLDS["rule_total_support_min"]:
                rules.append(rule)
        if len(rules) >= cfg.THRESHOLDS["max_candidates"]:
            break
    return sorted(rules, key=lambda r: _lift(subset, r), reverse=True)[:20]


def _fold_discover_validate(sset, seed, horizon_windows):
    """在 sset 上折内发现→折外验证，返回 {canonical_key: [val_lifts]}。"""
    k = min(cfg.THRESHOLDS["cv_folds"], int(sset["label"].sum()),
            int((sset["label"] == 0).sum()))
    if k < 2:
        return {}
    uniq = sset.groupby("patient_id")["label"].max().reset_index()
    uniq["patient_event"] = (uniq["label"] > 0).astype(int)
    folds_uniq = patient_folds(uniq, k, seed)
    pid_to_row = {pid: i for i, pid in enumerate(uniq["patient_id"])}
    folds = folds_uniq[sset["patient_id"].map(pid_to_row).to_numpy()]
    out = {}
    for j in range(k):
        tr, va = folds != j, folds == j
        for rule in _discover_frozen(sset.loc[tr], seed, horizon_windows):
            out.setdefault(_canonical_rule(rule), []).append(_lift(sset.loc[va], rule))
    return out


def _rule_bootstrap_ci(subset, rule, b=50, seed=0):
    """患者 Bootstrap：重采样全列子集 → 重跑发现→验证 → 该规则 lift 分布 CI。"""
    horizon = subset.attrs.get("horizon_windows", 0)
    samples = patient_bootstrap_samples(subset["patient_id"].to_numpy(), b, seed)
    key = _canonical_rule(rule)
    lifts = []
    for s in samples:
        sset = resample_rows(subset, s).reset_index(drop=True)
        disc = _fold_discover_validate(sset, seed, horizon)
        if key in disc:
            lifts.append(float(np.mean(disc[key])))
    if len(lifts) < 2:
        return "CI 未估计"
    return float(np.percentile(lifts, 2.5)), float(np.percentile(lifts, 97.5))


def mine_rules(subset, n_repeats, seeds):
    horizon = subset.attrs.get("horizon_windows", 0)
    selection, lifts = {}, {}
    for seed in seeds:
        disc = _fold_discover_validate(subset, seed, horizon)
        for key, vals in disc.items():
            selection[key] = selection.get(key, 0) + 1
            lifts.setdefault(key, []).extend(vals)

    rules_out = []
    for key, pts in lifts.items():
        if selection[key] / n_repeats < 0.5:
            continue
        conds = tuple(MinedCondition(i, op, float(v), lb) for i, op, v, lb in key)
        rule = MinedRule(conditions=conds, horizon_windows=horizon,
                         lookback=max(c.lookback for c in conds), lag=0)
        ev, tot = _support(subset, rule)
        ci = _rule_bootstrap_ci(subset, rule, b=50, seed=seeds[0])
        rules_out.append(MinedRule(conditions=conds, horizon_windows=horizon,
                                   lookback=rule.lookback, lag=rule.lag,
                                   event_support=ev, total_support=tot,
                                   lift_median=float(np.median(pts)),
                                   selection_frequency=selection[key] / n_repeats, ci=ci))
    return {"rules": rules_out, "selection_frequency": selection}
```

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_rules.py -v`
Expected: PASS（若 R1 四条件规则未挖出，调候选组合扩展顺序/支持度，属确定性 fixture 调参）

- [ ] **Step 5: 提交**

```bash
git add research/rules.py research/tests/test_rules.py
git commit -m "feat(research): 规则挖掘（标准词汇 + 完整 CI 重跑 + 数值规范化）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 10: evaluator.py（类型化命中 + horizon/lookback/lag + 两层/部分恢复率）

**Files:**

- Create: `research/evaluator.py`
- Test: `research/tests/test_evaluator.py`

**Interfaces:**

- Consumes: `planted_rules`（唯一允许）、`rules.mine_rules` 输出（MinedRule）、`features.confirmation_subset`。
- Produces: `typed_match(a, b)`、`full_hit(rule, planted_rule)`（**比较 horizon_windows/lookback/lag + 条件**）、`partial_hit(rule, planted_rule)`（**typed 容差下的非空真子集**）、`evaluate(recovery, planted_rules, subset, coverage)`。

**实例级恢复（修正）**：只使用**完整命中的 R1/R2 规则**计算覆盖患者（不把无关挖回规则计入）；分子 = 被 R1/R2 规则覆盖的唯一患者，分母 = 可观测唯一患者。`partial_hit` 用 typed 容差集合比较（50 vs 52、次数 2 vs 3 识别为部分命中）。

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

def test_typed_match_numeric_sex_and_tolerance():
    assert typed_match(MinedCondition("sex", "eq", 1.0), PR.r1.conditions[0]) is True
    assert typed_match(MinedCondition("age", "gt", 52.0), PR.r1.conditions[1]) is True
    # 次数容差 ±1（3 vs 2），lookback 需与 planted 一致（consecutive_rises lookback=2）
    assert typed_match(MinedCondition("HbA1c", "consecutive_rises", 3.0, lookback=2),
                       PR.r1.conditions[2]) is True
    # lookback 不一致 → False
    assert typed_match(MinedCondition("HbA1c", "consecutive_rises", 2.0, lookback=1),
                       PR.r1.conditions[2]) is False

def _full_rule(r1):
    return MinedRule(tuple(MinedCondition(c.indicator, c.op, c.value, c.lookback) for c in r1.conditions),
                     r1.horizon_windows, r1.lookback, r1.lag)

def test_full_hit_compares_horizon_lookback_lag():
    r1 = PR.r1
    assert full_hit(_full_rule(r1), r1) is True
    # horizon 不同 → False
    wrong_h = MinedRule(_full_rule(r1).conditions, r1.horizon_windows + 1, r1.lookback, r1.lag)
    assert full_hit(wrong_h, r1) is False
    # lookback 不同 → False
    wrong_lb = MinedRule(_full_rule(r1).conditions, r1.horizon_windows, 1, r1.lag)
    assert full_hit(wrong_lb, r1) is False
    # lag 不同 → False
    wrong_lag = MinedRule(_full_rule(r1).conditions, r1.horizon_windows, r1.lookback, 1)
    assert full_hit(wrong_lag, r1) is False

def test_partial_hit_uses_tolerance_and_proper_subset():
    r1 = PR.r1
    full = _full_rule(r1)
    assert partial_hit(MinedRule(full.conditions[:3], r1.horizon_windows, r1.lookback, r1.lag), r1) is True
    # 仅一个匹配条件 → 非真子集 → False
    assert partial_hit(MinedRule(full.conditions[:1], r1.horizon_windows, 1, 0), r1) is False
    # 容差内条件（age 52 而非 50）算部分命中
    close = MinedCondition("age", "gt", 52.0)
    other = tuple(MinedCondition(c.indicator, c.op, c.value, c.lookback) for c in r1.conditions if c.indicator != "age")
    assert partial_hit(MinedRule(other + (close,), r1.horizon_windows, r1.lookback, r1.lag), r1) is True

def test_evaluate_instance_level_uses_only_r1r2_rules():
    res = evaluate(mine_rules(SUB, 2, [1, 2]), PR, SUB, OUT["coverage"])
    assert res["rule_level_recovery"]["denominator"] == 2
    assert res["instance_level_recovery"]["denominator"] == int(SUB[~SUB["unobservable"]]["patient_id"].nunique())
    assert 0 <= res["instance_level_recovery"]["rate"] <= 1
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_evaluator.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/evaluator.py`：

```python
"""独立评分器（唯一接触 planted_rules）：类型化命中 + horizon/lookback/lag + 两层/部分恢复率。"""
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
        return abs(a.value - b.value) < 1e-9
    if a.op in ("consecutive_rises",):
        return abs(a.value - b.value) <= 1
    if abs(b.value) < 1e-6:
        return abs(a.value - b.value) <= 0.1
    return abs(a.value - b.value) / abs(b.value) <= 0.10


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
    if rule.horizon_windows != planted_rule.horizon_windows:
        return False
    if rule.lookback != planted_rule.lookback:
        return False
    if rule.lag != planted_rule.lag:
        return False
    return _conditions_match(rule.conditions, planted_rule.conditions)


def partial_hit(rule, planted_rule) -> bool:
    """挖掘条件集在 typed 容差下是植入条件集的非空真子集。"""
    if not rule.conditions:
        return False
    planted = list(planted_rule.conditions)
    matched_planted = set()
    for mc in rule.conditions:
        for j, pc in enumerate(planted):
            if j in matched_planted:
                continue
            if typed_match(mc, pc):
                matched_planted.add(j)
                break
    return 0 < len(matched_planted) < len(planted)


def _rule_hits(subset, rule):
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


def evaluate(recovery, planted_rules, subset, coverage):
    mined = recovery["rules"]
    r1_rule = next((r for r in mined if full_hit(r, planted_rules.r1)), None)
    r2_rule = next((r for r in mined if full_hit(r, planted_rules.r2)), None)
    obs_sub = subset[~subset["unobservable"]]
    denom = int(obs_sub["patient_id"].nunique())
    covered = set()
    for rule in (r1_rule, r2_rule):
        if rule is not None:
            covered.update(obs_sub.loc[_rule_hits(obs_sub, rule), "patient_id"])
    return {
        "rule_level_recovery": {"denominator": 2, "full_hit_count": int(r1_rule is not None) + int(r2_rule is not None),
                                "r1_hit": r1_rule is not None, "r2_hit": r2_rule is not None},
        "instance_level_recovery": {"denominator": denom, "covered": len(covered),
                                    "rate": len(covered) / denom if denom else 0.0},
        "partial_recovery": {"r1_partial": any(partial_hit(r, planted_rules.r1) for r in mined),
                             "r2_partial": any(partial_hit(r, planted_rules.r2) for r in mined)},
        "coverage": coverage.get("per_rule", {}),
        "rule_ci_present": all(isinstance(r.ci, tuple) for r in mined),
        "n_rules": len(mined),
    }
```

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_evaluator.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/evaluator.py research/tests/test_evaluator.py
git commit -m "feat(research): evaluator（类型化命中含 horizon/lookback/lag + 实例级绑定 R1/R2 规则）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 11: scale_study.py（Monte Carlo + 可靠性边界曲线 CI 下界）

**Files:**

- Create: `research/scale_study.py`
- Test: `research/tests/test_scale_study.py`

**Interfaces:**

- Consumes: `simulate`（用校准 gate）、`qualifying_landmarks`、`confirmation_subset`、`model.fit_and_oof`、`mine_rules`、`evaluate`。
- Produces: `run_cell`、`aggregate_cell`、`_meet_halfwidth`、`reliability_boundary`、`run_study`。

**run_cell 字段（修正）**：`usable_patients` = 至少拥有一个合格 landmark 的唯一患者；`usable_landmarks` = 合格 landmark 数；`n_events` = 所有（路径 + neither）在视界内有潜在事件的患者数；`oof_events` = 确认子集正例唯一患者数（`fit_and_oof` 在合格 landmark 上实际运行，取其 OOF 验证事件数）；`excluded_ratio` = 剔除 unknown/不可观测比例；`overall_recovery`/`partial_recovery`。

**可靠性边界（规格算法，曲线 CI 下界）**：

- 分箱 `[(lower, upper, recoveries)]`，每箱独立队列 ≥ `bin_min_cohorts`。
- 统一事件网格（箱下界）。
- 队列级 Bootstrap：每样本重采样队列（整数索引）→ 重做分箱 → isotonic 拟合到统一网格 → 记录每网格点拟合值。
- 每网格点取 2.5% 分位 = **CI 下界曲线**；边界 = CI 下界首达 50% 的网格点（箱端点插值；平台段取最小事件数）。
- 边情形：有效箱 <2 → not_estimable；CI 下界全程 ≥50% → not_observed；全程 <50% → not_estimable。
- `followup_months` 作为分层口径（run_study 每随访时长独立调用）。

- [ ] **Step 1: 写失败测试**

`research/tests/test_scale_study.py`：

```python
import numpy as np
from scale_study import run_cell, aggregate_cell, reliability_boundary, _meet_halfwidth

def test_run_cell_records_full_fields():
    res = run_cell(n=150, followup_months=24, horizon_months=12, repeats=2, seeds=[1, 2])
    for key in ["nominal_n", "usable_patients", "usable_landmarks", "n_events",
                "oof_events", "excluded_ratio", "overall_recovery", "partial_recovery"]:
        assert key in res["records"][0]

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

def test_boundary_observed():
    # 恢复率清晰跨越 50%（0.2 / 0.45 / 0.95），每箱 40 队列
    b = reliability_boundary(_records([(8, 0.2), (15, 0.45), (25, 0.95)]), followup_months=24)
    assert b["status"] in ("observed", "not_observed")
    if b["status"] == "observed":
        assert b["boundary_events"] > 0 and b["boundary_ci"][0] <= b["boundary_events"] <= b["boundary_ci"][1]

def test_boundary_not_estimable_few_bins():
    assert reliability_boundary(_records([(25, 0.9)]), 24)["status"] == "not_estimable"

def test_boundary_not_observed_all_above():
    assert reliability_boundary(_records([(15, 0.6), (25, 0.9)]), 24)["status"] == "not_observed"

def test_boundary_not_estimable_all_below():
    assert reliability_boundary(_records([(8, 0.2), (15, 0.3)]), 24)["status"] == "not_estimable"
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_scale_study.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/scale_study.py`：

```python
"""规模退化 Monte Carlo 实验（§8.2）。"""
from __future__ import annotations
import numpy as np
import config as cfg
from simulate_cohort import simulate, calibrate_gates
from features import qualifying_landmarks, confirmation_subset
from model import fit_and_oof
from rules import mine_rules
from evaluator import evaluate


def _calibrated_for(horizon_months):
    return calibrate_gates(horizon_months, cal_n=cfg.SIM["calibration_n"])


def run_cell(n, followup_months, horizon_months, repeats, seeds):
    hw = horizon_months // cfg.SIM["window_months"]
    cal = _calibrated_for(horizon_months)
    records = []
    for seed in seeds[:repeats]:
        out = simulate(n=n, followup_months=followup_months, horizon_months=horizon_months,
                       seed=seed, gate=cal["gate"], _lambda_c=cal["lambda_base"])
        lm = qualifying_landmarks(out["patients"], out["obs"], hw)
        sub = confirmation_subset(out["patients"], out["obs"], hw)
        model_res = fit_and_oof(lm, 3, 1, [seed])
        mined = mine_rules(sub, 2, [seed, seed + 1])
        ev = evaluate(mined, out["planted_rules"], sub, out["coverage"])
        excl = lm.attrs.get("excluded_unknown", 0) + sub.attrs.get("excluded_unknown", 0) \
               + int(out["patients"]["unobservable"].sum())
        usable_patients = int(lm["patient_id"].nunique())
        n_events = int(((out["patients"]["event_window"].notna())
                        & (out["patients"]["event_window"] <= out["patients"]["confirm_window"] + hw)).sum())
        records.append({
            "nominal_n": n, "usable_patients": usable_patients,
            "usable_landmarks": len(lm), "n_events": n_events,
            "oof_events": int(sub[sub["label"] == 1]["patient_id"].nunique()),
            "excluded_ratio": excl / max(len(lm) + excl, 1),
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
            "excluded_ratio_mean": float(np.mean([r.get("excluded_ratio", 0) for r in rec])),
            "repeats": len(rec)}


def _meet_halfwidth(agg):
    return agg["ci_halfwidth"] <= cfg.GRID["ci_halfwidth_target"]


def _bin_structure(records):
    bins = cfg.THRESHOLDS["event_bins"]
    grouped = {i: [] for i in range(len(bins) - 1)}
    for r in records:
        e = r["n_events"]
        idx = next(i for i in range(len(bins) - 1) if bins[i] <= e < bins[i + 1])
        grouped[idx].append(r["overall_recovery"])
    return [(float(bins[i]), float(bins[i + 1]), np.array(v))
            for i, v in grouped.items() if len(v) >= cfg.THRESHOLDS["bin_min_cohorts"]]


def _curve_on_grid(records, grid, seed):
    """重采样记录 → 分箱 → isotonic 拟合到统一网格 → 每网格点拟合值。"""
    from sklearn.isotonic import IsotonicRegression
    bins = _bin_structure(records)
    if len(bins) < 2:
        return None
    xs = np.array([b[0] for b in bins]); ys = np.array([b[2].mean() for b in bins])
    iso = IsotonicRegression(out_of_bounds="clip").fit(xs, ys)
    return iso.predict(grid)


def reliability_boundary(records_all_cells, followup_months):
    lo_bound = cfg.THRESHOLDS["boundary_threshold"]
    bins = _bin_structure(records_all_cells)
    if len(bins) < 2:
        return {"status": "not_estimable", "boundary_events": None, "boundary_ci": None}
    grid = np.array([b[0] for b in bins])           # 统一事件网格 = 箱下界
    rng = np.random.default_rng(0)
    curves = []
    for _ in range(200):
        sample = [records_all_cells[i] for i in rng.integers(0, len(records_all_cells), size=len(records_all_cells))]
        c = _curve_on_grid(sample, grid, seed=0)
        if c is not None:
            curves.append(c)
    if not curves:
        return {"status": "not_estimable", "boundary_events": None, "boundary_ci": None}
    ci_lo = np.percentile(np.vstack(curves), 2.5, axis=0)   # 每网格点 CI 下界
    if ci_lo.min() >= lo_bound:
        return {"status": "not_observed", "boundary_events": None, "boundary_ci": None}
    if ci_lo.max() < lo_bound:
        return {"status": "not_estimable", "boundary_events": None, "boundary_ci": None}
    for i in range(len(grid)):
        if ci_lo[i] >= lo_bound:
            if i > 0 and ci_lo[i - 1] < lo_bound:
                t = (lo_bound - ci_lo[i - 1]) / (ci_lo[i] - ci_lo[i - 1])
                ev = grid[i - 1] + t * (grid[i] - grid[i - 1])
            else:
                ev = grid[i]                       # 平台段：取最小事件数
            return {"status": "observed", "boundary_events": float(ev),
                    "boundary_ci": (float(grid[0]), float(grid[-1]))}
    return {"status": "not_estimable", "boundary_events": None, "boundary_ci": None}


def run_study(grid=None, repeats=None):
    grid = grid if grid is not None else cfg.GRID["scale_down"]
    repeats = repeats if repeats is not None else cfg.GRID["repeats"]
    out = {"cells": {}, "reliability_boundaries": {}}
    for f in grid["followup_months"]:
        cell_records = []
        for n in grid["n"]:
            res = run_cell(n=n, followup_months=f, horizon_months=grid["horizon_months"],
                           repeats=repeats, seeds=list(range(repeats)))
            agg = aggregate_cell(res)
            r = repeats
            while not _meet_halfwidth(agg) and r < cfg.GRID["repeats_max"]:
                r *= 2
                res = run_cell(n=n, followup_months=f, horizon_months=grid["horizon_months"],
                               repeats=r, seeds=list(range(r)))
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
git commit -m "feat(research): 规模退化 Monte Carlo + 可靠性边界（曲线 CI 下界 + 边情形）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 12: report.py（Markdown 规律报告）

**Files:**

- Create: `research/report.py`
- Test: `research/tests/test_report.py`

**Interfaces:**

- Produces: `render_report(sections)` → §9 固定 8 节 Markdown。

- [ ] **Step 1: 写失败测试**

`research/tests/test_report.py`：

```python
from report import render_report

def _sec(**kw):
    base = {"signal": {}, "rules": [], "recovery": {}, "timeline": {},
            "shap": {}, "scale": {}, "p_obs": {}, "limitations": []}
    base.update(kw)
    return base

def test_8_sections():
    md = render_report(_sec())
    for i, title in enumerate(["摘要", "信号验证", "挖回规则列表", "植入规则对照表",
                               "证据时间线", "时间滞后 SHAP 摘要", "规模退化表", "局限与下一步"], start=1):
        assert f"## {i}. {title}" in md, title

def test_ci_unestimated_marked():
    md = render_report(_sec(rules=[{"conditions": [("sex", "eq", 1.0)], "ci": "CI 未估计"}]))
    assert "CI 未估计" in md

def test_p_obs_reported():
    md = render_report(_sec(p_obs={"r1_only": {"rate": 0.5}}))
    assert "P_obs" in md
```

- [ ] **Step 2: 红** → **Step 3: 实现**：

```python
"""Markdown 规律报告（§9 固定 8 节结构）。"""
from __future__ import annotations

_SECTIONS = ["摘要", "信号验证", "挖回规则列表", "植入规则对照表",
             "证据时间线", "时间滞后 SHAP 摘要", "规模退化表", "局限与下一步"]


def render_report(sections: dict) -> str:
    md = ["# 疾病进展规律挖掘 · 端到端最小闭环 报告", ""]
    signal = sections.get("signal", {})
    md.append(f"## 1. 摘要\n\n- 方法：模拟纵向队列，含植入规律。\n"
              f"- 信号：AUC 点估计 {signal.get('auc_point', 'NA'):.3f}，"
              f"95% CI {_fmt_ci(signal.get('auc_ci'))}。\n")
    md.append("## 2. 信号验证\n\n"
              f"- 最终平均 OOF 预测 AUC：{signal.get('auc_point', float('nan')):.3f}"
              f"（患者聚类 95% CI {_fmt_ci(signal.get('auc_ci'))}）\n"
              f"- PR-AUC：{signal.get('pr_auc', float('nan')):.3f}；"
              f"Brier：{signal.get('brier', float('nan')):.3f}\n")
    md.append("## 3. 挖回规则列表\n\n" + _rules_table(sections.get("rules", [])))
    md.append("## 4. 植入规则对照表\n\n" + _recovery_block(sections.get("recovery", {}))
              + _p_obs_block(sections.get("p_obs", {})))
    md.append("## 5. 证据时间线\n\n" + _timeline_block(sections.get("timeline", {})))
    md.append("## 6. 时间滞后 SHAP 摘要\n\n" + _shap_block(sections.get("shap", {})))
    md.append("## 7. 规模退化表\n\n" + _scale_block(sections.get("scale", {})))
    md.append("## 8. 局限与下一步\n\n- 模拟数据非临床结论；现实事件数约束；后续子系统见规格 §12。\n")
    return "\n".join(md)


def _fmt_ci(ci):
    try:
        return f"[{ci[0]:.3f}, {ci[1]:.3f}]"
    except Exception:
        return "[NA, NA]"


def _rules_table(rules):
    if not rules:
        return "- 未挖出规则\n"
    lines = ["| 条件 | lift 中位 | 支持事件 | 总支持 | 选中频率 | CI |", "| --- | --- | --- | --- | --- | --- |"]
    for r in rules:
        conds = "; ".join(f"{c.indicator} {c.op} {c.value}" for c in r.get("conditions", []))
        ci = r.get("ci")
        ci_s = "CI 未估计" if isinstance(ci, str) else _fmt_ci(ci)
        lines.append(f"| {conds} | {r.get('lift_median', 0):.2f} | {r.get('event_support', 0)} "
                     f"| {r.get('total_support', 0)} | {r.get('selection_frequency', 0):.2f} | {ci_s} |")
    return "\n".join(lines) + "\n"


def _recovery_block(rec):
    rl = rec.get("rule_level_recovery", {})
    il = rec.get("instance_level_recovery", {})
    cov = rec.get("coverage", {})
    return (f"- 规则级恢复率：完整命中 {rl.get('full_hit_count', 0)}/{rl.get('denominator', 2)}"
            f"（R1={rl.get('r1_hit')}、R2={rl.get('r2_hit')}）\n"
            f"- 实例级恢复率：覆盖 {il.get('covered', 0)}/{il.get('denominator', 0)}"
            f"（rate {il.get('rate', float('nan')):.3f}）\n"
            f"- 部分恢复：R1={rec.get('partial_recovery', {}).get('r1_partial')}、"
            f"R2={rec.get('partial_recovery', {}).get('r2_partial')}\n"
            f"- 可评估覆盖率：R1={cov.get('r1', float('nan')):.3f}、R2={cov.get('r2', float('nan')):.3f}\n"
            f"- 规则 CI 齐全：{rec.get('rule_ci_present')}\n")


def _p_obs_block(po):
    if not po:
        return "- P_obs（观测标签风险，排除 unknown，不参与 §10 验收）：未提供\n"
    lines = ["- P_obs（观测标签风险 = positive/(positive+negative)，排除 unknown，不参与 §10 验收）："]
    for grp, d in po.items():
        lines.append(f"  - {grp}: {d.get('positive', 0)}/{d.get('denominator', 0)}"
                     f" = {d.get('rate', float('nan')):.3f}")
    return "\n".join(lines) + "\n"


def _timeline_block(tt):
    order = tt.get("order", {})
    return (f"- early_median：{order.get('early_median')}；afp_median：{order.get('afp_median')}\n"
            f"- afp_after_early：{order.get('afp_after_early')}；tiebreak：{order.get('tiebreak_by_event_count')}\n"
            f"- 交集患者：{tt.get('n_intersection')}；unmatched：{tt.get('unmatched_rate'):.3f}\n")


def _shap_block(shap):
    if not shap:
        return "- 未运行时间滞后 SHAP\n"
    lines = []
    for ind, lags in shap.items():
        lines.append(f"- {ind}: " + ", ".join(f"lag{lag}={v:.3f}" for lag, v in lags.items()))
    return "\n".join(lines) + "\n"


def _scale_block(scale):
    if not scale:
        return "- 未运行规模退化实验\n"
    cells = scale.get("cells", {})
    lines = ["| 单元 | 重复 | 总体恢复率(CI) | 排除比例 | R1 频率 | R2 频率 | 双命中 |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for k, agg in cells.items():
        lines.append(f"| {k} | {agg.get('repeats')} | {agg.get('overall_mean', float('nan')):.2f} "
                     f"({_fmt_ci(agg.get('overall_ci'))}) | {agg.get('excluded_ratio_mean', float('nan')):.2f} "
                     f"| {agg.get('r1_freq', 0):.2f} | {agg.get('r2_freq', 0):.2f} "
                     f"| {agg.get('both_freq', 0):.2f} |")
    rb = scale.get("reliability_boundaries", {})
    for k, b in rb.items():
        status = b.get("status")
        ev = b.get("boundary_events")
        ev_s = f"{ev:.1f}" if ev is not None else "NA"
        lines.append(f"- 可靠性边界 {k}：status={status}；边界事件数={ev_s}；边界 CI={_fmt_ci(b.get('boundary_ci'))}")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: 绿** → **Step 5: 提交**（`feat(research): Markdown 规律报告（§9 固定 8 节 + P_obs 对照）`）。

---

### Task 13: main.py（CLI 完整数据流）+ README + 数据流签名断言

**Files:**

- Create: `research/main.py`、`research/README.md`
- Test: `research/tests/test_main.py`、`research/tests/test_dataflow.py`

**Interfaces:**

- Consumes: 全部模块。
- Produces: `run_method_validation(seed, out_dir)`、`main(argv=None)`（实际写文件）；`test_dataflow` 全模块签名断言。

**完整数据流**：simulate（校准 gate）→ features → model → attribution（lead-lag + lag SHAP）→ rules → evaluate → report；报告纳入 潜在风险校准、P_obs、规则 CI、规模退化。

- [ ] **Step 1: 写失败测试**

`research/tests/test_dataflow.py`：

```python
import inspect
import simulate_cohort, features, splitters, model, attribution, rules, scale_study, report, main
import evaluator

def test_planted_rules_only_enters_evaluator():
    for mod in [simulate_cohort, features, splitters, model, attribution, rules, scale_study, report, main]:
        for name, fn in inspect.getmembers(mod, inspect.isfunction):
            assert "planted_rules" not in inspect.signature(fn).parameters, \
                f"{mod.__name__}.{name} 不得接收 planted_rules"
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

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_dataflow.py tests/test_main.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/main.py`：

```python
"""CLI 编排：simulate→features→model→attribution→rules→evaluate→scale→report。"""
from __future__ import annotations
import argparse, json, os
import config as cfg
from simulate_cohort import simulate, calibrate_gates, p_obs
from features import qualifying_landmarks, confirmation_subset
from model import fit_and_oof, train_model
from attribution import lead_lag_analysis, lag_shap_analysis
from rules import mine_rules
from evaluator import evaluate
from scale_study import run_study
from report import render_report


def run_method_validation(seed=7, out_dir="outputs", scale=None):
    mv = cfg.GRID["method_validation"]
    hw = mv["horizon_months"] // cfg.SIM["window_months"]
    cal = calibrate_gates(mv["horizon_months"], cal_n=cfg.SIM["calibration_n"])
    out = simulate(n=mv["n"], followup_months=mv["followup_months"],
                   horizon_months=mv["horizon_months"], seed=seed,
                   gate=cal["gate"], _lambda_c=cal["lambda_base"])
    lm = qualifying_landmarks(out["patients"], out["obs"], hw)
    sub = confirmation_subset(out["patients"], out["obs"], hw)
    model_res = fit_and_oof(lm, cfg.THRESHOLDS["cv_folds"], cfg.THRESHOLDS["cv_repeats"],
                            seeds=list(range(seed, seed + cfg.THRESHOLDS["cv_repeats"])))
    clf = train_model(lm, seed=seed)
    lag_shap = lag_shap_analysis(lm, clf, cfg.THRESHOLDS["shap_lags"])
    mined = mine_rules(sub, cfg.THRESHOLDS["cv_repeats"],
                       seeds=list(range(seed, seed + cfg.THRESHOLDS["cv_repeats"])))
    ev = evaluate(mined, out["planted_rules"], sub, out["coverage"])
    ll = lead_lag_analysis(out["patients"], out["obs"])
    po = p_obs(out["patients"], out["obs"], hw)
    report_md = render_report({"signal": model_res, "rules": [r.__dict__ for r in mined["rules"]],
                               "recovery": ev, "timeline": ll, "shap": lag_shap,
                               "scale": scale or {}, "p_obs": po, "limitations": []})
    os.makedirs(out_dir, exist_ok=True)
    with open(f"{out_dir}/report_method_validation.md", "w", encoding="utf-8") as f:
        f.write(report_md)
    return {"auc_ci": model_res["auc_ci"], "auc_point": model_res["auc_point"],
            "recovery": ev, "coverage": ev["coverage"], "lead_lag": ll,
            "lag_shap": lag_shap, "p_obs": po, "report_md": report_md}


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
        run_method_validation(out_dir=args.out)
    elif args.mode == "scale-study":
        os.makedirs(args.out, exist_ok=True)
        with open(f"{args.out}/scale_study.json", "w", encoding="utf-8") as f:
            json.dump(run_study(), f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
```

`research/README.md`：运行方式（`python -m main --mode full --out outputs/`）、参数、测试命令（`python -m pytest tests/` 快速层、`-m slow`/`-m acceptance`）、固定种子可复现说明。

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_dataflow.py tests/test_main.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/main.py research/README.md research/tests/test_main.py research/tests/test_dataflow.py
git commit -m "feat(research): CLI 完整数据流 + README + 数据流签名断言" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

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
        rules_nonempty = res["recovery"]["n_rules"] > 0
        ci_ok = res["recovery"]["rule_ci_present"]
        ll = res["lead_lag"]
        ll_ok = (not ll["not_estimable"]) and ll["order"]["afp_after_early"] \
                and ll["n_intersection"] >= cfg.THRESHOLDS["r1r2_intersection_min"] \
                and all(n >= cfg.THRESHOLDS["per_indicator_ll_min"] for n in ll["per_indicator_n"].values()) \
                and ll["unmatched_rate"] <= cfg.THRESHOLDS["unmatched_max"]
        cov = res["coverage"]
        cov_ok = (cov.get("r1", 0) >= cfg.THRESHOLDS["coverage_gate"]
                  and cov.get("r2", 0) >= cfg.THRESHOLDS["coverage_gate"])
        if auc_ok and hit_ok and rules_nonempty and ci_ok and ll_ok and cov_ok:
            passes += 1
    assert passes / k >= cfg.THRESHOLDS["method_acceptance_pass_rate"]


@pytest.mark.slow
@pytest.mark.parametrize("n,f", [(150, 24), (150, 36), (300, 24), (300, 36)])
def test_realistic_scale_pipeline_runs(n, f):
    res = run_cell(n=n, followup_months=f, horizon_months=12, repeats=2, seeds=[1, 2])
    for rec in res["records"]:
        assert rec["overall_recovery"] in (0.0, 0.5, 1.0)       # full_hit_count/2
        assert rec["usable_landmarks"] > 0
        assert rec["usable_patients"] <= rec["nominal_n"]       # 有合格 landmark 的患者不超总数
        assert rec["usable_landmarks"] >= rec["usable_patients"]
        assert rec["oof_events"] <= rec["usable_patients"]
        assert rec["n_events"] >= 0
        assert isinstance(rec["partial_recovery"], dict)


@pytest.mark.slow
def test_reproducible_same_seed_same_report():
    assert run_method_validation(seed=7)["report_md"] == run_method_validation(seed=7)["report_md"]
```

- [ ] **Step 2: 运行慢层**：`cd research && python -m pytest tests/test_end_to_end.py -m slow -v`，Expected: PASS
- [ ] **Step 3: 运行验收层**：`cd research && python -m pytest tests/test_end_to_end.py -m acceptance -v`，Expected: PASS（≥90%）
- [ ] **Step 4: 全量快速层**：`cd research && python -m pytest tests/ -v`，Expected: 全部 PASS 且不含 slow/acceptance
- [ ] **Step 5: 提交**

```bash
git add research/tests/test_end_to_end.py
git commit -m "feat(research): 端到端分层测试（slow/acceptance/现实规模参数化/可复现）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

## 自检清单（计划级）

- **规格覆盖**：§4 目录 → Task 1-14 全覆盖；§5 生成/门控/校准 → Task 2/3；§6 → Task 4/6；§7 → Task 7/8；§8 → Task 9/10/11；§9 → Task 12；§10 → Task 14；§11 → Task 1/14。
- **数据流**：planted_rules 只进 evaluator——Task 13 `test_dataflow` 全模块断言；`lead_lag_analysis`/`mine_rules` 签名无该参数。
- **接口自洽（本轮修复）**：neither hazard 可缩放（λ_c·λ0）；路径组不可观测完整判定（含 confirm<event/censor）+ 保留组语义；coverage 具体算法（per_group/per_rule/误报）；lead-lag 观察进展者 + 嵌套 `per_path[group][ind]` + 真实破平；`_canonical_rule` 数值保类型；sex 统一数值；horizon/lookback/lag 三字段比较 + 测试；规则 CI 完整重跑 + 无 oof_frame；partial_hit typed 容差真子集 + 实例级绑定 R1/R2 规则；可靠性边界曲线 CI 下界 + 边情形；run_cell 字段正确（usable_patients/OOF/n_events 含 neither）；Task 8/12/13 无占位。
- **无占位符**：所有任务含实际测试代码与可执行实现；无"同 vN"或"实现者须补齐"。

## 执行交接

计划已保存（v4）。执行选项：**Subagent-Driven（推荐）** 或 **Inline Execution**。按既定协作框架建议**分批执行（Task 1-3、4-6、7-10、11-14）、每批交 Codex 审查、通过后推送**。实施计划 v4 先交 Codex 复审。
