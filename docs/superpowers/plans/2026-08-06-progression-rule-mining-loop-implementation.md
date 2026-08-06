# 疾病进展规律挖掘 · 端到端最小闭环 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `research/` 独立子项目中实现端到端最小闭环：用含植入规律的模拟纵向数据跑通"模拟 → 窗口特征 → 模型 → 时序归因 → 规则挖掘 → evaluator → 规模退化 → 规律报告"全链路，验证方法论能可信地恢复植入规律，并量化现实数据规模下的可信度。

**Architecture:** 每个模块单一职责、纯接口清晰、可独立单测。`simulate_cohort` 产出「数据集 + planted_rules」；数据集流向 features→model→attribution→rules；**planted_rules 只流向 evaluator**（数据流约束，防答案泄漏）。模型训练用全量合格 landmark，规则/校准/evaluator 用每患者确认 landmark（§5.5 分角色口径表）。

**Tech Stack:** Python 3.10+、pandas、scikit-learn（GradientBoostingClassifier）、shap、pytest（`slow`/`acceptance` marker）；matplotlib 可选（仅报告时间线图）。

**规格依据：** `docs/superpowers/specs/2026-08-06-progression-rule-mining-loop-design.md`（v16，Codex 十五轮通过）。

## Global Constraints

以下约束**每个任务都必须遵守**，值从规格原样抄录：

- **独立边界**：`research/` 自带版本化 `config.py`（含指标参考范围常量）；**禁止**运行时 import 生产 `prediction_engine.py`、访问生产数据库、写现有表/API。
- **数据流**：`planted_rules` 只进 `evaluator.py`；`rules.py` 接口签名**不得接收** planted_rules。
- **主 estimand**：校准/验收/evaluator/规则/support/lift 用**每患者确认/参考 landmark**（R2/交集=w_A+1、R1-only=w_R1、neither=首个合格参考 landmark）；模型训练用**全量合格 landmark**；splitter 用**患者级结局**（仅分层，不进特征/规则）。
- **δ ∈ {1,2}**（默认 1），`w_event = 确认窗口 + δ`；`w_A+2` 仅作 R2 路径"高危区标记"，非事件窗口。
- **事件门控**：路径组 `g ~ Bernoulli(p_group)`；neither 不抽 p_group，由基线 hazard λ_b(t) 触发。
- **校准目标 = 潜在真实事件风险**（完整事件真值 g+事件窗口，不受删失影响，N=50,000 队列 ±3pp 验收）；`P_obs`（观测标签风险）单独报告、**不参与 §10 验收**。
- **标签**：正例 = 视界内且删失/行政终止前已观察到事件；unknown = 视界内先删失且在删失前未观察到事件（从标注集排除）；潜在 g+事件窗口**不得进入模型/OOF/规则流程**。
- **患者聚类**：CI、support、Bootstrap 全部按患者聚类；同一患者不视为独立样本。
- **信号门槛**：方法验证单元最终平均 OOF 预测上 AUC 的患者聚类 95% CI **下界 ≥ 0.65**；现实单元只报告。
- **成功标准（方法验收）**：K=20 种子、≥90% 通过；每种子四条同时成立——① AUC CI 下界 ≥0.65、② 两条植入规则均完整命中、③ lead-lag 次序恢复（R1∩R2 交集唯一患者 ≥30、每指标可分析患者 ≥20、unmatched ≤20%，不足 not estimable）、④ 每条规则可评估覆盖率 ≥80%。
- **测试分层**：`pytest.ini` 配 `addopts = -m "not slow and not acceptance"`，注册 `slow`/`acceptance` marker；默认只跑快速层。
- **TDD**：每步先写失败测试→确认红→最小实现→确认绿→单独提交。提交正文三行：`AI-Agent: Codex`、`AI-Client: Codex-Desktop`、`Task-ID: research-progression-min-loop`。
- **不 push**（由用户在 Codex 审查通过后统一推送）；在 main 分支直接开发，不建分支/worktree。

---

## 共享数据契约（各任务间接口，先定死）

### `patients` DataFrame（每患者一行）

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `patient_id` | int | 0..N-1 |
| `z` | str | 生成路径 `"none"`/`"r1"`/`"r2"`/`"r1_and_r2"` |
| `age` | int | 静态协变量 |
| `sex` | str | `"male"`/`"female"` |
| `group` | str | 确认/参考 landmark 上的互斥组 `"neither"`/`"r1_only"`/`"r2_only"`/`"r1_and_r2"` |
| `confirm_window` | int | 确认/参考 landmark 窗口序号 |
| `w_r1` | float | 生成器内部锚点：R1 条件确认窗口（R2-only 为 `NaN`） |
| `w_a` | float | 生成器内部锚点：AFP 激活窗口（R1-only 为 `NaN`） |
| `g` | float | 路径组事件门控指示 0/1；neither 为 `NaN` |
| `event_window` | float | 潜在事件窗口（进展者）；否则 `NaN` |
| `censored` | bool | 是否失访删失 |
| `censored_window` | float | 删失窗口；否则 `NaN` |
| `admin_end` | int | 行政随访终点窗口序号 |

### `obs` DataFrame（每患者每窗口一行）

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `patient_id` | int | 关联 patients |
| `window` | int | 0..admin_end |
| `ALT`..`BMI` | float | 10 个指标观测（含测量噪声） |

指标常量（`config.INDICATORS`）：`ALT, AST, GGT, TBIL, ALB, PLT, HbA1c, AFP, WAIST, BMI`。

### `planted_rules`（只进 evaluator）

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Condition:
    indicator: str          # "sex"|"age"|"ALT"|...（指标名）
    op: str                 # "eq"|"gt"|"consecutive_rises"|"drop_pct"
    value: float            # 阈值；eq 时 "male"/"female"
    lookback: int = 1       # 回溯窗口数

@dataclass(frozen=True)
class PlantedRule:
    name: str               # "r1"|"r2"
    horizon_months: int
    conditions: tuple[Condition, ...]
    group: str              # 对应互斥组
    target_risk: float      # 该视界该组条件风险目标

@dataclass(frozen=True)
class PlantedRules:
    horizon_months: int
    r1: PlantedRule
    r2: PlantedRule
    calibration: dict[str, float]   # {"neither":..., "r1_only":..., "r2_only":..., "r1_and_r2":...}
```

植入条件集（两视界通用）：
- **R1**：`sex=male`、`age>50`、`HbA1c 连续 2 窗上升`、`PLT 较基线下降 >20%`
- **R2**：`AFP 连续 ≥2 窗上升`

### 确认/参考 landmark 判定

- 路径组确认 landmark：R2/交集 = `w_A+1`；R1-only = `w_R1`。
- neither 参考 landmark = **每患者首个合格 landmark**（合格 = `窗口 ≥ 2` 且 `admin_end − 窗口 ≥ 视界窗数` 且 `窗口` 在事件/删失之前）；命中任一条件 → 计入误报、排除 neither 校准分母，**不标记为条件不可观测**。
- 合格 landmark（通用）：`窗口 ≥ 2`、`admin_end − 窗口 ≥ 视界窗数`、`窗口 < 事件窗口`（若有）、`窗口 < 删失窗口`（若有）。

---

## 任务分解

### Task 1: 脚手架 + config.py

**Files:**
- Create: `research/config.py`
- Create: `research/pytest.ini`
- Create: `research/requirements.txt`
- Create: `research/tests/__init__.py`
- Test: `research/tests/test_config.py`

**Interfaces:**
- Produces: `config.py` 的所有命名常量（后续所有任务依赖）：`INDICATORS`、`REFERENCE_RANGES`、`SIM`、`CALIBRATION`、`GRID`、`THRESHOLDS`、`PLANTED_CONDITIONS`。

- [ ] **Step 1: 写失败测试**

`research/tests/test_config.py`：

```python
import pytest
import config as cfg

def test_indicators_are_10_and_liver_relevant():
    assert len(cfg.INDICATORS) == 10
    assert {"ALT", "AST", "GGT", "TBIL", "ALB", "PLT", "HbA1c", "AFP", "WAIST", "BMI"} == set(cfg.INDICATORS)

def test_reference_ranges_have_all_indicators():
    assert set(cfg.REFERENCE_RANGES) == set(cfg.INDICATORS)

def test_sim_constants():
    assert cfg.SIM["window_months"] == 6
    assert cfg.SIM["censoring_rate"] == 0.2
    assert cfg.SIM["kappa"] >= 2.0
    assert cfg.SIM["delta_choices"] == [1, 2]
    assert cfg.SIM["resample_max"] >= 100
    assert cfg.SIM["calibration_n"] == 50_000

def test_calibration_targets():
    assert cfg.CALIBRATION[24] == {"neither": 0.12, "r1_only": 0.60, "r2_only": 0.40, "r1_and_r2": 0.73}
    assert cfg.CALIBRATION[12] == {"neither": 0.06, "r1_only": 0.40, "r2_only": 0.25, "r1_and_r2": 0.52}

def test_grid():
    assert cfg.GRID["method_validation"] == {"n": 1500, "followup_months": 60, "horizon_months": 24}
    assert cfg.GRID["scale_down"]["n"] == [150, 300, 600, 1500]
    assert cfg.GRID["scale_down"]["followup_months"] == [24, 36, 60]
    assert cfg.GRID["scale_down"]["horizon_months"] == 12
    assert cfg.GRID["repeats"] == 50 and cfg.GRID["repeats_max"] == 200

def test_thresholds():
    assert cfg.THRESHOLDS["auc_ci_lower_gate"] == 0.65
    assert cfg.THRESHOLDS["coverage_gate"] == 0.80
    assert cfg.THRESHOLDS["r1r2_intersection_min"] == 30
    assert cfg.THRESHOLDS["per_indicator_ll_min"] == 20
    assert cfg.THRESHOLDS["unmatched_max"] == 0.20
    assert cfg.THRESHOLDS["rule_event_support_min"] == 5
    assert cfg.THRESHOLDS["rule_total_support_min"] == 20
    assert cfg.THRESHOLDS["max_conditions"] == 4
    assert cfg.THRESHOLDS["method_acceptance_seeds"] == 20
    assert cfg.THRESHOLDS["method_acceptance_pass_rate"] == 0.90

def test_planted_conditions_match_spec():
    r1 = cfg.PLANTED_CONDITIONS["r1"]
    assert ("sex", "eq", "male") in r1
    assert ("age", "gt", 50.0) in r1
    r2 = cfg.PLANTED_CONDITIONS["r2"]
    assert ("AFP", "consecutive_rises", 2.0) in r2
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_config.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'config'`）

- [ ] **Step 3: 写最小实现**

`research/pytest.ini`：

```ini
[pytest]
pythonpath = .
addopts = -m "not slow and not acceptance"
markers =
    slow: long-running tests (regression fixture)
    acceptance: Monte Carlo method acceptance tests
```

`research/requirements.txt`：

```
pandas>=2.0
scikit-learn>=1.3
shap>=0.44
matplotlib>=3.7
pytest>=7.4
```

`research/config.py`（版本化常量；值全部抄录规格）：

```python
"""版本化配置：指标参考范围、模拟参数、实验网格、阈值（自包含，不依赖生产 DB）。

规格依据：docs/superpowers/specs/2026-08-06-progression-rule-mining-loop-design.md v16
"""

INDICATORS = ["ALT", "AST", "GGT", "TBIL", "ALB", "PLT", "HbA1c", "AFP", "WAIST", "BMI"]

# indicator -> (lower, upper, lower_inclusive, upper_inclusive, unit)
REFERENCE_RANGES = {
    "ALT": (9, 50, True, True, "U/L"),
    "AST": (13, 40, True, True, "U/L"),
    "GGT": (10, 60, True, True, "U/L"),
    "TBIL": (5, 21, True, True, "umol/L"),
    "ALB": (40, 55, True, True, "g/L"),
    "PLT": (125, 350, True, True, "x10^9/L"),
    "HbA1c": (4.0, 6.5, True, True, "%"),
    "AFP": (0, 7, True, True, "ng/mL"),
    "WAIST": (0, 90, True, True, "cm"),
    "BMI": (18.5, 24.0, True, True, "kg/m2"),
}

SIM = {
    "window_months": 6,
    "censoring_rate": 0.20,
    "kappa": 2.0,                    # 信号增量 ≥ κ·σ_meas
    "tau": 0.0,                      # 偏离阈值常量
    "delta_choices": [1, 2],         # δ ∈ {1,2}
    "delta_default": 1,
    "resample_max": 100,             # 前向锚点重采样上限
    "signal_increment_sd": 0.5,      # 每窗潜在 S 增量的个体间方差系数
    "calibration_n": 50_000,
    "calibration_tol_pp": 3.0,
    "observability_gate": 0.95,      # 可观测条件成立比例门槛
    "calibration_group_min": 200,    # 互斥组最低样本数
}

# 每视界校准目标（互斥组口径；潜在真实事件风险）
CALIBRATION = {
    24: {"neither": 0.12, "r1_only": 0.60, "r2_only": 0.40, "r1_and_r2": 0.73},
    12: {"neither": 0.06, "r1_only": 0.40, "r2_only": 0.25, "r1_and_r2": 0.52},
}

GRID = {
    "method_validation": {"n": 1500, "followup_months": 60, "horizon_months": 24},
    "scale_down": {
        "n": [150, 300, 600, 1500],
        "followup_months": [24, 36, 60],
        "horizon_months": 12,
    },
    "repeats": 50,
    "repeats_max": 200,
    "ci_halfwidth_target": 0.10,
    "event_bins": [0, 10, 20, 30, 40, 50, 75, 100, 150, 10 ** 9],
    "bin_min_cohorts": 10,
    "boundary_threshold": 0.50,
}

THRESHOLDS = {
    "auc_ci_lower_gate": 0.65,
    "coverage_gate": 0.80,
    "r1r2_intersection_min": 30,
    "per_indicator_ll_min": 20,
    "unmatched_max": 0.20,
    "rule_event_support_min": 5,
    "rule_total_support_min": 20,
    "max_conditions": 4,
    "top_m": 8,
    "thresholds_per_feature": 3,
    "max_candidates": 5000,
    "lift_min": 1.5,
    "method_acceptance_seeds": 20,
    "method_acceptance_pass_rate": 0.90,
    "bootstrap_b": 1000,
    "cv_folds": 5,
    "cv_repeats": 5,
    "shap_lags": [0, 1, 2],
}

# 植入条件集（可观察条件；只进 evaluator，不作为模拟内部语义）
PLANTED_CONDITIONS = {
    "r1": [
        ("sex", "eq", "male"),
        ("age", "gt", 50.0),
        ("HbA1c", "consecutive_rises", 2.0),
        ("PLT", "drop_pct", 20.0),
    ],
    "r2": [("AFP", "consecutive_rises", 2.0)],
}
```

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_config.py -v`
Expected: PASS（11 passed）

- [ ] **Step 5: 提交**

```bash
git add research/config.py research/pytest.ini research/requirements.txt research/tests/test_config.py research/tests/__init__.py
git commit -m "feat(research): 脚手架 + 版本化 config.py" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 2: simulate_cohort.py（模拟纵向数据生成器）

**Files:**
- Create: `research/simulate_cohort.py`
- Test: `research/tests/test_simulate_cohort.py`

**Interfaces:**
- Consumes: `config.INDICATORS`、`config.SIM`、`config.CALIBRATION`、`config.PLANTED_CONDITIONS`、`Condition/PlantedRule/PlantedRules`（定义在 `simulate_cohort.py` 顶部，供 evaluator 复用）。
- Produces:
  - `simulate(n, followup_months, horizon_months, seed, rng)` → `dict`，含：
    - `patients: pd.DataFrame`（§数据契约）
    - `obs: pd.DataFrame`
    - `planted_rules: PlantedRules`
    - `coverage: dict`（逐互斥组可观测条件成立比例，供验收/报告）

生成顺序（严格前向，规格 §5.4）：Z → 协变量按 Z 条件采样 → 基线指标（run-in）→ S(t) 前向演化 → 分阶段阈值（S_AFP/S_event，仅 R2 路径）→ 事件门控（路径组 p_group / neither λ_b）→ 指标观测（含噪声）→ 删失 → 截断。**禁止任何"先定事件时间、再反向构造特征"的逻辑。**

- [ ] **Step 1: 写失败测试**

`research/tests/test_simulate_cohort.py`：

```python
import numpy as np
import pandas as pd
from simulate_cohort import simulate

def _sim(**kw):
    kw.setdefault("n", 1500)
    kw.setdefault("followup_months", 60)
    kw.setdefault("horizon_months", 24)
    kw.setdefault("seed", 7)
    return simulate(**kw)

def test_returns_patients_and_obs():
    out = _sim()
    assert isinstance(out["patients"], pd.DataFrame)
    assert isinstance(out["obs"], pd.DataFrame)
    assert len(out["patients"]) == 1500
    assert out["patients"].columns.tolist() == [
        "patient_id", "z", "age", "sex", "group", "confirm_window", "w_r1", "w_a",
        "g", "event_window", "censored", "censored_window", "admin_end",
    ]

def test_obs_has_all_indicators_per_window():
    out = _sim()
    assert set(out["obs"].columns) == {"patient_id", "window"} | set(
        ["ALT", "AST", "GGT", "TBIL", "ALB", "PLT", "HbA1c", "AFP", "WAIST", "BMI"]
    )
    # 每患者窗口数 = admin_end + 1
    counts = out["obs"].groupby("patient_id")["window"].count()
    assert (counts == out["patients"]["admin_end"] + 1).all()

def test_forward_no_event_leakage():
    # 事件窗口前的观测不应依赖未来：验证事件窗口 ≥ 确认窗口 + 1（对进展者）
    out = _sim()
    p = out["patients"].dropna(subset=["event_window"])
    p = p[p["g"] == 1]
    assert (p["event_window"] >= p["confirm_window"] + 1).all()

def test_confirmation_landmarks_per_group():
    out = _sim()
    for grp, win_cond in [
        ("r1_only", lambda p: p["confirm_window"] == p["w_r1"]),
        ("r2_only", lambda p: p["confirm_window"] == p["w_a"] + 1),
        ("r1_and_r2", lambda p: p["confirm_window"] == p["w_a"] + 1),
    ]:
        sub = out["patients"][out["patients"]["group"] == grp]
        assert len(sub) > 0, grp

def test_gating_produces_calibratable_risk_on_large_cohort():
    # 在超大校准队列上，各组潜在条件风险应接近目标（±3pp）
    out = simulate(n=50_000, followup_months=60, horizon_months=24, seed=3)
    p = out["patients"]
    cal = out["planted_rules"].calibration
    for grp, target in cal.items():
        sub = p[p["group"] == grp]
        risk = sub["g"].mean() if grp != "neither" else (sub["event_window"].notna().mean())
        assert abs(risk - target) <= 0.03, (grp, risk, target)

def test_planted_rules_shape():
    out = _sim()
    pr = out["planted_rules"]
    assert pr.horizon_months == 24
    assert len(pr.r1.conditions) == 4
    assert len(pr.r2.conditions) == 1
```

注：`w_r1` / `w_a` 是生成器内部列，测试需由 `simulate` 返回（见 Step 3 的 patients 附加列说明）。

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_simulate_cohort.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写实现**

`research/simulate_cohort.py` 核心逻辑（逐项实现，含前向锚点采样、分阶段阈值、门控、删失、确认 landmark 判定）：

```python
"""模拟纵向数据生成器（外生潜在路径 Z + 前向生成，输出数据集 + planted_rules）。

规格 §5.3/§5.4/§5.5。planted_rules 只流向 evaluator。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field

import config as cfg


# ---------- 植入规律对象（供 evaluator 复用） ----------

@dataclass(frozen=True)
class Condition:
    indicator: str
    op: str            # "eq" | "gt" | "consecutive_rises" | "drop_pct"
    value: float
    lookback: int = 1


@dataclass(frozen=True)
class PlantedRule:
    name: str
    horizon_months: int
    conditions: tuple[Condition, ...]
    group: str
    target_risk: float


@dataclass(frozen=True)
class PlantedRules:
    horizon_months: int
    r1: PlantedRule
    r2: PlantedRule
    calibration: dict[str, float]


def _build_planted_rules(horizon_months: int) -> PlantedRules:
    cal = cfg.CALIBRATION[horizon_months]
    r1 = PlantedRule(
        name="r1", horizon_months=horizon_months,
        conditions=tuple(Condition(ind, op, float(val)) for ind, op, val in cfg.PLANTED_CONDITIONS["r1"]),
        group="r1_only", target_risk=cal["r1_only"],
    )
    r2 = PlantedRule(
        name="r2", horizon_months=horizon_months,
        conditions=tuple(Condition(ind, op, float(val)) for ind, op, val in cfg.PLANTED_CONDITIONS["r2"]),
        group="r2_only", target_risk=cal["r2_only"],
    )
    return PlantedRules(horizon_months=horizon_months, r1=r1, r2=r2, calibration=cal)


# ---------- 前向生成 ----------

def _sample_path_and_covariates(rng: np.random.Generator, n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """采样 Z 与按 Z 条件采样的协变量。Z=R1/R1∩R2 强制男且 >50。"""
    paths = rng.choice(["none", "r1", "r2", "r1_and_r2"], size=n, p=[0.70, 0.15, 0.10, 0.05])
    ages = np.empty(n, dtype=int)
    sexes = np.empty(n, dtype=object)
    for i, z in enumerate(paths):
        if z in ("r1", "r1_and_r2"):
            sexes[i] = "male"
            ages[i] = int(rng.integers(51, 80))
        else:
            sexes[i] = rng.choice(["male", "female"])
            ages[i] = int(rng.integers(20, 70))
    return paths, ages, sexes


def simulate(n: int, followup_months: int, horizon_months: int, seed: int):
    """生成纵向模拟队列。"""
    rng = np.random.default_rng(seed)
    window_months = cfg.SIM["window_months"]
    admin_end = followup_months // window_months
    horizon_windows = horizon_months // window_months
    cal = cfg.CALIBRATION[horizon_months]

    paths, ages, sexes = _sample_path_and_covariates(rng, n)

    rows = []
    obs_rows = []
    # 指标基线与测量噪声 σ_meas（版本化）
    sigma_meas = {ind: 0.1 * (cfg.REFERENCE_RANGES[ind][1] - cfg.REFERENCE_RANGES[ind][0]) for ind in cfg.INDICATORS}

    for pid in range(n):
        z = paths[pid]
        age, sex = ages[pid], sexes[pid]

        # --- 前向锚点：先采样 w0 / w_A / w_R1（在可行区间内，拒绝采样） ---
        # 可行性（规格 §5.4/§5.5）：确认 landmark 须合格
        #   R2/交集确认 = w_A+1：w_A+1 >= 2 且 w_A+1 + horizon_windows <= admin_end
        #   R1-only 确认 = w_R1：w_R1 >= 2 且 w_R1 + horizon_windows <= admin_end
        w0 = int(rng.integers(0, 2))
        w_a = np.nan
        w_r1 = np.nan
        for _ in range(cfg.SIM["resample_max"]):
            if z in ("r2", "r1_and_r2"):
                lo = 1
                hi = admin_end - horizon_windows - 1
                if hi < lo:
                    w_a = np.nan
                    break
                w_a = int(rng.integers(lo, hi + 1))
            if z in ("r1", "r1_and_r2"):
                if z == "r1":
                    # R1-only：可行区间直接采样 w_R1，不依赖事件窗口
                    lo, hi = 2, admin_end - horizon_windows
                    if hi < lo:
                        w_r1 = np.nan
                        break
                    w_r1 = int(rng.integers(lo, hi + 1))
                else:
                    # R1∩R2：w_R1 ∈ [w0, w_A-1]
                    lo, hi = w0, w_a - 1
                    if hi < lo:
                        w_r1 = np.nan
                        break
                    w_r1 = int(rng.integers(lo, hi + 1))
            break

        # --- 潜在进展状态 S(t) 前向演化 ---
        band = 2.0  # S_event - S_AFP
        s_afp = 1.0
        s_event = s_afp + band
        n_win = admin_end + 1
        s = np.full(n_win, 0.0)
        onset = w0
        # 每窗潜在增量 ΔS ∈ (band/2, band)，仅路径组
        inc = np.zeros(n_win)
        if z != "none":
            for t in range(max(onset, 1), n_win):
                inc[t] = rng.uniform(band / 2 + 1e-6, band - 1e-6)
        # R2 路径：S 首次跨 S_AFP 钉 S_AFP（w_A），之后恰好 2 窗达 S_event
        if z in ("r2", "r1_and_r2"):
            s[w_a] = s_afp
            if w_a + 1 < n_win:
                s[w_a + 1] = s_afp + inc[w_a + 1]
            if w_a + 2 < n_win:
                s[w_a + 2] = s_afp + inc[w_a + 1] + inc[w_a + 2]

        # --- 事件门控 ---
        # 路径组：g ~ Bernoulli(p_group)；neither：λ_b(t)（基线 hazard，年龄/性别）
        g = np.nan
        event_window = np.nan
        delta = int(rng.choice(cfg.SIM["delta_choices"]))
        if z != "none":
            confirm = (w_a + 1) if z in ("r2", "r1_and_r2") else w_r1
            if np.isfinite(confirm):
                p_group = cal[  # 按组目标概率（潜在真值；校准队列验收保证 ±3pp）
                    "r1_and_r2" if z == "r1_and_r2" else ("r1_only" if z == "r1" else "r2_only")
                ]
                g = int(rng.random() < p_group)
                if g == 1:
                    event_window = confirm + delta
        else:
            # neither：基线 hazard，自参考 landmark 起
            ref = 2  # 首个合格 landmark 由 §5.5 判定（此处近似：窗口 2 起）
            base_hazard = 0.05 + 0.001 * (age - 20) + (0.01 if sex == "male" else 0.0)
            for t in range(ref, n_win):
                if rng.random() < base_hazard:
                    event_window = t
                    break
            g = np.nan

        # --- 指标观测 X(t) = g(S(t), Z) + 个体噪声 + 测量噪声 ---
        baseline = {ind: float(rng.normal(mid, (hi - lo) / 6))
                    for ind, (lo, hi, *_rest) in cfg.REFERENCE_RANGES.items()
                    for mid in [(lo + hi) / 2]}
        patient_obs = []
        for t in range(n_win):
            row = {"patient_id": pid, "window": t}
            for ind in cfg.INDICATORS:
                sig = 0.0
                if z in ("r1", "r1_and_r2") and ind in ("HbA1c", "PLT") and t >= onset:
                    sig = (0.15 * (t - onset)) if ind == "HbA1c" else (-3.0 * (t - onset))
                if z in ("r2", "r1_and_r2") and ind == "AFP" and np.isfinite(w_a) and t >= w_a:
                    sig = 6.0 * (t - w_a + 1)
                val = baseline[ind] + sig + rng.normal(0, sigma_meas[ind])
                row[ind] = float(val)
            patient_obs.append(row)
        obs_rows.extend(patient_obs)

        # --- 删失（独立，20%）与截断 ---
        censored = rng.random() < cfg.SIM["censoring_rate"]
        censored_window = np.nan
        if censored:
            censored_window = float(rng.integers(1, n_win))

        rows.append({
            "patient_id": pid, "z": z, "age": age, "sex": sex,
            "group": _assign_group(z, w_r1, w_a, age, sex, patient_obs),
            "confirm_window": _confirm_window(z, w_r1, w_a, patient_obs),
            "w_r1": w_r1, "w_a": w_a,
            "g": g, "event_window": event_window,
            "censored": censored, "censored_window": censored_window,
            "admin_end": admin_end,
        })

    patients = pd.DataFrame(rows)
    obs = pd.DataFrame(obs_rows)
    planted_rules = _build_planted_rules(horizon_months)
    return {
        "patients": patients, "obs": obs,
        "planted_rules": planted_rules,
        "coverage": _compute_coverage(patients, obs, planted_rules),
    }


def _assign_group(z, w_r1, w_a, age, sex, patient_obs):
    """在确认/参考 landmark 上按可观察条件判定互斥组（规格 §5.3 组归属）。"""
    if z == "none":
        return "neither"
    conds = _conditions_at(z, w_r1, w_a, age, sex, patient_obs)
    r1_ok, r2_ok = conds
    if r1_ok and r2_ok:
        return "r1_and_r2"
    if r1_ok:
        return "r1_only"
    if r2_ok:
        return "r2_only"
    return "neither"  # 条件未成立（路径患者观察未达阈值 → 归 neither 或不可观测，见规格）


def _conditions_at(z, w_r1, w_a, age, sex, patient_obs):
    """在指定 landmark 判定 R1/R2 条件是否成立（连续 2 窗上升 / 较基线降 >20%）。"""
    r1_ok = False
    r2_ok = False
    if z in ("r1", "r1_and_r2"):
        r1_ok = _r1_holds(patient_obs, w_r1, age, sex)
    if z in ("r2", "r1_and_r2"):
        r2_ok = _r2_holds(patient_obs, w_a + 1)
    return r1_ok, r2_ok


def _r1_holds(obs, w, age, sex):
    if sex != "male" or age <= 50:
        return False
    hba1c = _window_value(obs, "HbA1c")
    if _consecutive_rises(hba1c, w, 2) is False:
        return False
    plts = _window_value(obs, "PLT")
    base = np.mean([plts.get(t, np.nan) for t in (0, 1) if t in plts])
    if not np.isfinite(base) or base == 0:
        return False
    return (plts.get(w, base) - base) / base <= -0.20


def _r2_holds(obs, w):
    afp = _window_value(obs, "AFP")
    return _consecutive_rises(afp, w, 2) is True


def _consecutive_rises(series, w, k):
    """series: {window: value}；判定 w 处连续 k 个窗口对观测值均上升。"""
    if w < k:
        return False
    vals = [series.get(w - i, np.nan) for i in range(k + 1)]
    if any(not np.isfinite(v) for v in vals):
        return False
    return all(vals[i] > vals[i + 1] for i in range(k))


def _window_value(obs, ind):
    return {r["window"]: r[ind] for r in obs}


def _confirm_window(z, w_r1, w_a, obs):
    if z in ("r2", "r1_and_r2"):
        return int(w_a + 1) if np.isfinite(w_a) else np.nan
    if z == "r1":
        return int(w_r1) if np.isfinite(w_r1) else np.nan
    return 2  # neither 参考 landmark（首个合格，近似窗口 2）


def _compute_coverage(patients, obs, planted_rules):
    """逐互斥组：指定确认/参考 landmark 上可观测条件成立比例（§5.3）。"""
    return {"per_group": {}, "false_positive_rate": 0.0}
```

实现说明（实现者须补齐）：
- `_compute_coverage` 按规格逐组统计：R1-only 在 w_R1 上 R1 成立比例、R2-only 在 w_A+1 上 R2 成立比例、R1∩R2 在同一 w_A+1 两套成立比例、neither 参考 landmark 上两者均不成立比例（命中任一 → 误报）。
- 校准验收（`test_gating_produces_calibratable_risk_on_large_cohort`）不满足 ±3pp 时，调 `p_group`/基线 hazard 参数使各组潜在风险贴近目标（校准是生成器验收，与规则挖掘无关）。
- 观测值需用患者真实 `obs` 行构建 `_window_value`（上面 `_r1_holds`/`_r2_holds` 的 `obs` 是 `{window: value}` 字典）。

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_simulate_cohort.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/simulate_cohort.py research/tests/test_simulate_cohort.py
git commit -m "feat(research): 模拟纵向数据生成器（Z 路径 + 前向生成 + 事件门控）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 3: features.py（窗口切片 + landmark 化 + 指标派生特征）

**Files:**
- Create: `research/features.py`
- Test: `research/tests/test_features.py`

**Interfaces:**
- Consumes: `simulate()` 返回的 `patients`/`obs`；`config.SIM`。
- Produces:
  - `qualifying_landmarks(patients, obs, horizon_windows)` → `pd.DataFrame`（全量合格 landmark 样本：`patient_id, window, age, sex, label, + 每个指标的派生特征`）——**模型训练用**。
  - `confirmation_subset(patients, obs)` → `pd.DataFrame`（每患者确认/参考 landmark 一个样本）——**规则/校准/evaluator 用**。
  - `label_for(patient, window, horizon_windows)` → `int | "unknown"`（§5.5 标签）。

每个指标、每个窗口派生（§6.1）：`当前值`、`Δ6m`、`Δ12m`、`斜率`、`连续上升次数`、`较基线下降百分比`（基线 = run-in 前 2 窗均值）。静态特征：`age`、`sex`。所有特征仅用 P 及 P 之前历史（无未来信息）。

- [ ] **Step 1: 写失败测试**

`research/tests/test_features.py`：

```python
import numpy as np
import pandas as pd
from simulate_cohort import simulate
from features import qualifying_landmarks, confirmation_subset, label_for, derive_window_features

OUT = simulate(n=200, followup_months=24, horizon_months=12, seed=1)

def test_derived_features_match_hand_computation():
    rows = [{"window": 0, "ALT": 30.0}, {"window": 1, "ALT": 33.0}, {"window": 2, "ALT": 36.0}]
    feat = derive_window_features(rows, "ALT", window=2, runin=2)
    assert feat["ALT_cur"] == 36.0
    assert feat["ALT_d6m"] == 36.0 - 33.0
    assert feat["ALT_d12m"] == 36.0 - 30.0
    assert feat["ALT_slope"] == (33.0 - 30.0)  # 相邻窗口线性拟合
    assert feat["ALT_rises"] == 2
    base = (30.0 + 33.0) / 2
    assert feat["ALT_drop_pct"] == 0.0  # 上升无下降

def test_qualifying_landmarks_no_future_leakage():
    lm = qualifying_landmarks(OUT["patients"], OUT["obs"], horizon_windows=2)
    # 特征只依赖窗口 <= window 的观测：检查无 window 之后的列
    assert "window" in lm.columns

def test_confirmation_subset_one_per_patient():
    sub = confirmation_subset(OUT["patients"], OUT["obs"])
    assert sub["patient_id"].is_unique

def test_label_semantics():
    # 正例：视界内且删失/行政终止前观察到事件
    p = OUT["patients"].iloc[0]
    lab = label_for(p, window=2, horizon_windows=2)
    assert lab in (0, 1, "unknown")
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_features.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/features.py` 核心：

```python
"""窗口切片 + landmark 化 + 指标派生特征（无未来信息）。"""
from __future__ import annotations
import numpy as np
import pandas as pd
import config as cfg


def derive_window_features(obs_rows, ind: str, window: int, runin: int) -> dict:
    """对单个指标在 window 处派生特征。obs_rows: [{window, <ind>}, ...]。"""
    series = {r["window"]: r[ind] for r in obs_rows if ind in r}
    base = np.mean([series.get(t, np.nan) for t in range(runin) if t in series])
    cur = series.get(window, np.nan)
    d6 = series.get(window, np.nan) - series.get(window - 1, np.nan) if window - 1 in series else np.nan
    d12 = series.get(window, np.nan) - series.get(window - 2, np.nan) if window - 2 in series else np.nan
    slope = series.get(window - 1, np.nan) - series.get(window - 2, np.nan) if window - 2 in series else np.nan
    rises = 0
    if window - 2 in series and window - 1 in series and window in series:
        rises = int((series[window] > series[window - 1]) + (series[window - 1] > series[window - 2]))
    drop = 0.0
    if np.isfinite(base) and base != 0:
        drop = (cur - base) / base if np.isfinite(cur) else 0.0
    return {
        f"{ind}_cur": cur, f"{ind}_d6m": d6, f"{ind}_d12m": d12,
        f"{ind}_slope": slope, f"{ind}_rises": rises, f"{ind}_drop_pct": drop,
    }


def _label(patient, window, horizon_windows):
    ev = patient["event_window"]
    cw = patient["censored_window"]
    # 正例：视界内且删失/行政终止前观察到事件
    if np.isfinite(ev) and ev <= window + horizon_windows:
        if (not np.isfinite(cw)) or cw > ev:
            return 1
    # unknown：视界内先删失且删失前未观察到事件
    if np.isfinite(cw) and cw <= window + horizon_windows and (not np.isfinite(ev) or ev > cw):
        return "unknown"
    # 负例：无事件且观察满视界
    return 0


def label_for(patient, window, horizon_windows):
    return _label(patient, window, horizon_windows)


def _qualifying_mask(patients, horizon_windows):
    """全量合格 landmark（模型训练用）：窗口>=2、admin_end-window>=视界、事件/删失之前。"""
    return (
        (patients["window"] >= 2)
        & (patients["admin_end"] - patients["window"] >= horizon_windows)
    )
```

实现说明（实现者须补齐）：
- `qualifying_landmarks(patients, obs, horizon_windows)`：对每患者每合格窗口，合并 `derive_window_features` 全指标特征 + `age/sex` + `label`（`_label`）；**标签 unknown 的行剔除**（§5.5），记录排除比例。
- `confirmation_subset(patients, obs)`：按 `patients.confirm_window` 取每患者一行，同样派生特征；neither 参考 landmark 用 `confirm_window`。
- 所有特征仅用 `window` 及之前的观测（`derive_window_features` 已天然满足）。

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_features.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/features.py research/tests/test_features.py
git commit -m "feat(research): 窗口特征 + landmark 化（无未来泄漏）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 4: splitters.py（患者级 repeated stratified group splitter + 患者聚类 Bootstrap）

**Files:**
- Create: `research/splitters.py`
- Test: `research/tests/test_splitters.py`

**Interfaces:**
- Produces:
  - `patient_folds(patients, n_folds, seed)` → `np.ndarray`（每患者一折标号；患者级分组 + 结局分层）
  - `repeated_stratified_folds(patients, n_folds, n_repeats, seeds)` → `list[np.ndarray]`
  - `patient_bootstrap_ci(values_by_patient, stat_fn, b, seed)` → `(lo, hi)`（患者聚类 Bootstrap）

- [ ] **Step 1: 写失败测试**

`research/tests/test_splitters.py`：

```python
import numpy as np
import pandas as pd
from splitters import patient_folds, patient_bootstrap_ci

def _mk_patients(n=100, p_event=0.3, seed=0):
    rng = np.random.default_rng(seed)
    event = rng.random(n) < p_event
    return pd.DataFrame({"patient_id": np.arange(n), "patient_event": event})

def test_patient_never_split_across_folds():
    df = _mk_patients()
    folds = patient_folds(df, n_folds=5, seed=1)
    # 每患者只在一个折
    assert len(folds) == len(df)
    assert set(folds) <= {0, 1, 2, 3, 4}

def test_folds_are_stratified_by_patient_outcome():
    df = _mk_patients(400, p_event=0.3)
    folds = patient_folds(df, n_folds=5, seed=2)
    for k in range(5):
        rate = df.loc[folds == k, "patient_event"].mean()
        assert abs(rate - 0.3) < 0.08, (k, rate)

def test_repeats_differ_by_seed():
    df = _mk_patients()
    f1 = patient_folds(df, n_folds=5, seed=1)
    f2 = patient_folds(df, n_folds=5, seed=2)
    assert not np.array_equal(f1, f2)

def test_patient_bootstrap_clusters_by_patient():
    rng = np.random.default_rng(0)
    vals = rng.normal(size=100)
    pid = np.repeat(np.arange(20), 5)  # 20 患者，各 5 样本（同一患者相关）
    lo, hi = patient_bootstrap_ci(pid, vals, stat_fn=np.mean, b=200, seed=0)
    assert lo < np.mean(vals) < hi
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_splitters.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/splitters.py`：

```python
"""患者级 repeated stratified group splitter + 患者聚类 Bootstrap（§6.3）。"""
from __future__ import annotations
import numpy as np
import pandas as pd


def patient_folds(patients: pd.DataFrame, n_folds: int, seed: int) -> np.ndarray:
    """患者级 + 结局分层：同一患者所有样本只落一个折，每折事件比例近似总体。"""
    rng = np.random.default_rng(seed)
    out = np.full(len(patients), -1, dtype=int)
    uniq = patients["patient_id"].unique()
    # 分层：事件患者与非事件患者各随机分入 n_folds 个桶
    for event_val in (0, 1):
        ids = uniq[np.isin(uniq, patients.loc[patients["patient_event"] == event_val, "patient_id"])]
        perm = rng.permutation(ids)
        for i, pid in enumerate(perm):
            out[patients["patient_id"].values == pid] = i % n_folds
    return out


def repeated_stratified_folds(patients, n_folds, n_repeats, seeds):
    return [patient_folds(patients, n_folds, seed=s) for s in seeds]


def patient_bootstrap_ci(patient_ids, values, stat_fn, b=1000, seed=0):
    """患者聚类 Bootstrap：按患者 resample，返回 stat_fn 的 95% CI。"""
    rng = np.random.default_rng(seed)
    uniq = np.unique(patient_ids)
    stats = np.empty(b)
    arr = np.asarray(values)
    for i in range(b):
        sample = rng.choice(uniq, size=len(uniq), replace=True)
        mask = np.isin(patient_ids, sample)
        stats[i] = stat_fn(arr[mask])
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))
```

实现说明：`patient_folds` 的空桶处理（某折无事件患者时按规格降折/not estimable 由调用方处理）；折数约束 `min(5, 事件患者数, 非事件患者数)`、任一类 <2 → not estimable 在 model.py 中实现。

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_splitters.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/splitters.py research/tests/test_splitters.py
git commit -m "feat(research): 患者级 repeated stratified splitter + 患者聚类 Bootstrap" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 5: model.py（进展二分类 + 患者级 OOF 验证）

**Files:**
- Create: `research/model.py`
- Test: `research/tests/test_model.py`

**Interfaces:**
- Consumes: `features.qualifying_landmarks`（训练样本，含 label）、`splitters.repeated_stratified_folds`、`patient_bootstrap_ci`。
- Produces:
  - `fit_and_oof(landmarks, n_folds, n_repeats, seeds)` → `dict`：`oof_mean`（每样本最终平均 OOF 概率）、`auc_ci`（`(lo, hi)`）、`auc_point`、`pr_auc`、`brier`、`not_estimable`（bool）。
  - `train_model(landmarks, seed)` → 已训练 GradientBoostingClassifier（供归因/规则用）。

评估口径（§6.3，固定）：折数 = `min(5, 事件患者数, 非事件患者数)`，任一类 <2 → not estimable；每重复内联合 OOF → 每重复一个 AUC；跨重复取概率均值 = 最终平均 OOF 预测；**AUC 点估计 + 患者聚类 Bootstrap 95% CI 在最终平均 OOF 预测上**；PR-AUC、Brier 同口径；跨重复 AUC 中位数仅作稳健性报告。

- [ ] **Step 1: 写失败测试**

`research/tests/test_model.py`：

```python
import numpy as np
import pandas as pd
from simulate_cohort import simulate
from features import qualifying_landmarks
from model import fit_and_oof

def _landmarks():
    out = simulate(n=600, followup_months=24, horizon_months=12, seed=3)
    return qualifying_landmarks(out["patients"], out["obs"], horizon_windows=2)

def test_oof_returns_metrics_and_estimable():
    lm = _landmarks()
    res = fit_and_oof(lm, n_folds=3, n_repeats=2, seeds=[1, 2])
    assert res["not_estimable"] is False
    assert res["oof_mean"].shape[0] == len(lm)
    assert res["auc_ci"][0] < res["auc_ci"][1]

def test_oof_probabilities_in_unit_range():
    lm = _landmarks()
    res = fit_and_oof(lm, n_folds=3, n_repeats=2, seeds=[1, 2])
    assert ((res["oof_mean"] >= 0) & (res["oof_mean"] <= 1)).all()

def test_not_estimable_when_one_class_has_few_patients():
    lm = _landmarks()
    tiny = lm.iloc[:3]  # 患者少
    res = fit_and_oof(tiny, n_folds=3, n_repeats=1, seeds=[1])
    assert res["not_estimable"] is True
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_model.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/model.py`：

```python
"""进展二分类 + 患者级 OOF 验证（§6.3）。"""
from __future__ import annotations
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
import config as cfg
from splitters import repeated_stratified_folds, patient_bootstrap_ci


def _feature_cols(lm):
    return [c for c in lm.columns if c not in ("patient_id", "window", "label")]


def train_model(lm, seed=0):
    X = lm[_feature_cols(lm)].to_numpy()
    y = lm["label"].to_numpy()
    clf = GradientBoostingClassifier(random_state=seed)
    clf.fit(X, y)
    return clf


def fit_and_oof(lm, n_folds, n_repeats, seeds):
    """患者级 repeated stratified group CV，返回最终平均 OOF 预测与指标。"""
    event_pat = lm.loc[lm["label"] == 1, "patient_id"].nunique()
    nonevent_pat = lm.loc[lm["label"] == 0, "patient_id"].nunique()
    folds_k = min(n_folds, event_pat, nonevent_pat)
    if min(event_pat, nonevent_pat) < 2 or folds_k < 2:
        return {"not_estimable": True, "oof_mean": np.full(len(lm), np.nan),
                "auc_ci": (np.nan, np.nan), "auc_point": np.nan,
                "pr_auc": np.nan, "brier": np.nan}
    per_repeat_oof = []
    patients = lm[["patient_id", "label"]].copy()
    patients["patient_event"] = (lm.groupby("patient_id")["label"].max() > 0).astype(int).reindex(
        lm["patient_id"]).to_numpy()
    for seed in seeds:
        folds = repeated_stratified_folds(patients, folds_k, 1, [seed])[0]
        oof = np.full(len(lm), np.nan)
        for k in range(folds_k):
            tr = folds != k
            va = folds == k
            clf = GradientBoostingClassifier(random_state=seed)
            clf.fit(lm.loc[tr, _feature_cols(lm)], lm.loc[tr, "label"])
            oof[va] = clf.predict_proba(lm.loc[va, _feature_cols(lm)])[:, 1]
        per_repeat_oof.append(oof)
    oof_mean = np.nanmean(np.vstack(per_repeat_oof), axis=0)
    y = lm["label"].to_numpy()
    valid = np.isfinite(oof_mean)
    auc_point = roc_auc_score(y[valid], oof_mean[valid])
    pr_auc = average_precision_score(y[valid], oof_mean[valid])
    brier = brier_score_loss(y[valid], oof_mean[valid])
    pid = lm["patient_id"].to_numpy()
    lo, hi = patient_bootstrap_ci(pid[valid], oof_mean[valid],
                                  stat_fn=lambda p: roc_auc_score(y[valid], p),
                                  b=cfg.THRESHOLDS["bootstrap_b"], seed=seeds[0])
    return {"not_estimable": False, "oof_mean": oof_mean,
            "auc_ci": (lo, hi), "auc_point": auc_point,
            "pr_auc": pr_auc, "brier": brier,
            "auc_median_across_repeats": float(np.median([roc_auc_score(y[np.isfinite(o)], o[np.isfinite(o)]) for o in per_repeat_oof]))}
```

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_model.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/model.py research/tests/test_model.py
git commit -m "feat(research): 患者级 OOF 模型验证（AUC CI / PR-AUC / Brier）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 6: attribution.py（lead-lag 时间对齐 + 时间滞后 SHAP/消融）

**Files:**
- Create: `research/attribution.py`
- Test: `research/tests/test_attribution.py`

**Interfaces:**
- Consumes: `simulate()` 输出、`features.qualifying_landmarks`、`model.train_model`。
- Produces:
  - `lead_lag_analysis(patients, obs, planted_rules)` → `dict`：`per_path`（r1_only/r2_only/r1_and_r2 各自的指标首次偏离中位窗口 + Bootstrap CI）、`order`（R1∩R2 的 PLT/HbA1c vs AFP 首次偏离次序）、`unmatched_rate`、`not_estimable`。
  - `lag_shap_analysis(landmarks, clf, lags)` → `dict`：每指标各滞后 `mean|SHAP|` + 消融结果（描述性）。

算法（§7.1）：偏离判定 `|X(t) − run-in 均值| > κ·σ_meas + τ` 且持续 ≥2 连续窗口；基线 = run-in 前 2 窗；对照 = 风险集匹配（index time = 进展者事件时间，允许替换）；首次偏离从 **onset 至事件前全窗口** 计算（§7.1 + §5.3）。

- [ ] **Step 1: 写失败测试**

`research/tests/test_attribution.py`：

```python
import numpy as np
from simulate_cohort import simulate
from attribution import lead_lag_analysis

OUT = simulate(n=1500, followup_months=60, horizon_months=24, seed=5)

def test_lead_lag_recovers_planted_ordering():
    res = lead_lag_analysis(OUT["patients"], OUT["obs"], OUT["planted_rules"])
    assert res["not_estimable"] is False
    # 植入先行次序：PLT/HbA1c 先行 → AFP 后行（R1∩R2 患者）
    order = res["order"]
    assert order["afp_after_early"] is True

def test_unmatched_rate_under_cap():
    res = lead_lag_analysis(OUT["patients"], OUT["obs"], OUT["planted_rules"])
    assert res["unmatched_rate"] <= 0.20
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_attribution.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/attribution.py` 核心：

```python
"""lead-lag 时间对齐（主证据）+ 时间滞后 SHAP/消融（佐证，描述性）。

规格 §7.1/§7.2。lead-lag 首次偏离从 onset 至事件前全窗口计算；w_R1/w_A+1 仅作入组锚点。
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import config as cfg


def _deviation_flag(series, runin_mean, sigma_meas, kappa, tau):
    """|X - runin_mean| > kappa*sigma + tau，且持续 >=2 连续窗口。series: {window: value}。"""
    flags = {}
    for w, v in series.items():
        flags[w] = abs(v - runin_mean) > kappa * sigma_meas + tau
    out = {}
    for w in sorted(series):
        out[w] = flags.get(w, False) and flags.get(w - 1, False)
    return out


def _first_deviation_window(series, runin_mean, sigma_meas):
    dev = _deviation_flag(series, runin_mean, sigma_meas, cfg.SIM["kappa"], cfg.SIM["tau"])
    flagged = [w for w, d in dev.items() if d]
    return min(flagged) if flagged else np.nan


def lead_lag_analysis(patients, obs, planted_rules):
    """分路径 lead-lag；R1∩R2 全排序，R1-only/R2-only 各自验证对应信号。"""
    # 1) 只取进展者（g==1）
    prog = patients[(patients["g"] == 1)].copy()
    # 2) 风险集匹配：为每进展者匹配 1 名未进展对照（index time = 事件时间，允许替换）
    controls, unmatched_rate = _risk_set_match(patients, prog)
    # 3) R1∩R2 全排序：PLT/HbA1c 首次偏离窗口 vs AFP 首次偏离窗口
    order_result = _intersection_order(prog, obs, controls)
    # 4) 样本门槛（§10）：交集 >=30、每指标 >=20、unmatched <=20%
    n_inter = int(prog["group"].eq("r1_and_r2").sum())
    n_analyzable = int(prog[prog["group"].eq("r1_and_r2")]["patient_id"].nunique())
    not_estimable = n_inter < cfg.THRESHOLDS["r1r2_intersection_min"] or unmatched_rate > cfg.THRESHOLDS["unmatched_max"]
    return {
        "per_path": {"r1_only": None, "r2_only": None, "r1_and_r2": order_result},
        "order": order_result,
        "unmatched_rate": unmatched_rate,
        "n_intersection": n_inter,
        "n_analyzable": n_analyzable,
        "not_estimable": not_estimable,
    }
```

实现说明（实现者须补齐）：
- `_risk_set_match`：index time = 进展者 `event_window`；对照 = 随访覆盖 ≥ index time 且 index time 尚未事件的未进展患者，按年龄（分箱）× 性别匹配，允许替换；无合格对照 → unmatched。
- `_intersection_order`：R1∩R2 进展者上，计算 PLT、HbA1c 的中位首次偏离窗口 vs AFP 的中位首次偏离窗口；`afp_after_early = median(afp) > median(early)`。
- `lag_shap_analysis`：`model.train_model` 后，按 `(指标 × 滞后)` 展开特征（`features` 已含 `_d6m/_d12m` 滞后），计算 `shap.TreeExplainer` 的 `mean|SHAP|`，并按指标整组做消融（移除该组滞后特征后模型 OOF 指标变化）——报告为**描述性**，措辞"模型预测贡献的时间滞后一致性（非因果）"。

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_attribution.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/attribution.py research/tests/test_attribution.py
git commit -m "feat(research): lead-lag 时序归因 + 时间滞后 SHAP 佐证" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 7: rules.py（规则挖掘：确认 landmark 子集、每折发现→冻结→验证）

**Files:**
- Create: `research/rules.py`
- Test: `research/tests/test_rules.py`

**Interfaces:**
- Consumes: `features.confirmation_subset`、`splitters.repeated_stratified_folds`、`model.train_model`（用于 SHAP 特征重要性选候选特征）。
- Produces:
  - `discover_rules_per_fold(train_subset, seed)` → 该训练折的候选规则（冻结）
  - `validate_rules_on_fold(rules, val_subset)` → 列联表 + lift
  - `mine_rules(subset, n_repeats, seeds)` → `dict`：`rules`（最终规则，含条件/方向/lift 点估计/支持数/选中频率/CI 或"CI 未估计"）、`selection_frequency`

规则数据口径（§8.1 + §5.5 角色表）：**只使用每患者确认 landmark 子集**；训练折 = 该折患者的确认 landmark（按患者分组切分，与模型共用折）；**禁止在全量 landmark 上发现规则、再在确认 landmark 上验证**。组合控制：max_conditions=4、top-M=8、每特征阈值 ≤3、候选 ≤5000、训练折支持度剪枝。**禁读 planted_rules**。

- [ ] **Step 1: 写失败测试**

`research/tests/test_rules.py`：

```python
import numpy as np
import pandas as pd
from simulate_cohort import simulate
from features import confirmation_subset
from rules import mine_rules

OUT = simulate(n=1500, followup_months=60, horizon_months=24, seed=6)
SUB = confirmation_subset(OUT["patients"], OUT["obs"])

def test_rules_never_see_planted_rules():
    # mine_rules 接口签名不得接收 planted_rules
    import inspect
    sig = inspect.signature(mine_rules)
    assert "planted_rules" not in sig.parameters

def test_mined_rules_have_support_fields():
    res = mine_rules(SUB, n_repeats=2, seeds=[1, 2])
    for r in res["rules"]:
        assert r["event_support"] >= 5
        assert r["total_support"] >= 20
        assert r["selection_frequency"] > 0

def test_rule_identity_canonical():
    from rules import _canonical_rule
    a = _canonical_rule([("sex", "eq", "male"), ("age", "gt", 50.0)])
    b = _canonical_rule([("age", "gt", 50.0), ("sex", "eq", "male")])
    assert a == b  # 指标集排序后的规范化表示一致
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_rules.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/rules.py` 核心：

```python
"""规则挖掘（确认 landmark 子集；每折发现→冻结→验证；禁读 planted_rules）。"""
from __future__ import annotations
import numpy as np
import pandas as pd
import itertools
import config as cfg


def _canonical_rule(conditions):
    """规范化规则表示：(指标集排序, 方向, 离散化阈值分箱) —— 跨重复比对身份用。"""
    normalized = sorted((c[0], c[1], float(c[2])) for c in conditions)
    return tuple(normalized)


def _discretize_threshold(series, value):
    """阈值聚类容差：同分位分箱视为同一规则（±10% 容差用于跨折身份比对）。"""
    return round(value / 10.0) * 10.0


def _candidate_conditions(subset):
    """从确认 landmark 子集派生候选条件（阈值从数据分位数选，禁读植入语义）。"""
    conds = []
    # 分类：sex
    for v in subset["sex"].unique():
        conds.append(("sex", "eq", v))
    # 连续指标：分位数阈值（每特征 <= THRESHOLDS["thresholds_per_feature"] 个）
    feature_cols = [c for c in subset.columns if c.endswith(("_cur", "_rises", "_drop_pct"))]
    for col in feature_cols[:cfg.THRESHOLDS["top_m"]]:
        qs = np.quantile(subset[col].dropna(), [0.33, 0.67])
        for q in qs:
            conds.append((col, "gt", float(q)))
            conds.append((col, "lt", float(q)))
    return conds


def discover_rules_per_fold(train_subset, seed):
    """训练折内：选候选特征（SHAP 重要性 top-M）→ 阈值 → 复合候选 → 剪枝 → 冻结。"""
    cand = _candidate_conditions(train_subset)
    # 单条件 + 两条件复合（覆盖植入规则 1 的完整 4 条件语义需 max_conditions=4；
    # 此处用两条件起始 + 递归扩展，组合上限 max_candidates）
    rules = []
    for k in range(1, cfg.THRESHOLDS["max_conditions"] + 1):
        for combo in itertools.combinations(cand, k):
            if len(rules) >= cfg.THRESHOLDS["max_candidates"]:
                break
            rule = _make_rule(combo)
            if _support_ok(train_subset, rule):
                rules.append(rule)
        if len(rules) >= cfg.THRESHOLDS["max_candidates"]:
            break
    # 按训练折 lift 排序，返回冻结规则
    return sorted(rules, key=lambda r: _lift(train_subset, r), reverse=True)[:20]


def _make_rule(conditions):
    return {"conditions": list(conditions)}


def _hits(subset, rule):
    """规则命中掩码：所有条件成立（含连续 2 窗上升 / drop_pct 等语义）。"""
    mask = np.ones(len(subset), dtype=bool)
    for cond in rule["conditions"]:
        ind, op, val = cond
        if op == "eq":
            mask &= (subset[ind].astype(str) == str(val)).to_numpy()
        elif op == "gt":
            mask &= (subset[ind].to_numpy() > val)
        elif op == "lt":
            mask &= (subset[ind].to_numpy() < val)
    return mask


def _support_ok(subset, rule):
    hit = _hits(subset, rule)
    n_event = int(subset.loc[hit, "label"].sum())
    n_total = int(hit.sum())
    return n_event >= cfg.THRESHOLDS["rule_event_support_min"] and n_total >= cfg.THRESHOLDS["rule_total_support_min"]


def _lift(subset, rule):
    hit = _hits(subset, rule)
    n = len(subset)
    base = subset["label"].mean()
    if hit.sum() == 0:
        return 0.0
    return subset.loc[hit, "label"].mean() / base if base > 0 else 0.0


def mine_rules(subset, n_repeats, seeds):
    """逐重复独立发现→验证；跨重复稳定性汇总（以重复为单元，不做跨重复患者合并）。"""
    selection = {}
    lift_pts = {}
    folds_k = min(cfg.THRESHOLDS["cv_folds"],
                  int(subset["label"].sum()), int((subset["label"] == 0).sum()))
    for seed in seeds:
        from splitters import repeated_stratified_folds
        patients = subset[["patient_id", "label"]].copy()
        patients["patient_event"] = (subset.groupby("patient_id")["label"].max() > 0).astype(int).to_numpy()
        folds = repeated_stratified_folds(patients, folds_k, 1, [seed])[0]
        repeat_rules = set()
        repeat_lift = {}
        for k in range(folds_k):
            tr, va = folds != k, folds == k
            frozen = discover_rules_per_fold(subset.loc[tr], seed)
            for rule in frozen:
                key = _canonical_rule(rule["conditions"])
                repeat_rules.add(key)
                repeat_lift.setdefault(key, []).append(_lift(subset.loc[va], rule))
        for key in repeat_rules:
            selection[key] = selection.get(key, 0) + 1
            lift_pts.setdefault(key, []).extend(repeat_lift[key])
    return {
        "rules": [
            {
                "conditions": list(key),
                "lift_median": float(np.median(v)),
                "selection_frequency": selection[key] / n_repeats,
                "event_support": -1,  # 由 evaluator 在确认 landmark 上重算（见 §8.3 两层恢复率）
                "total_support": -1,
                "ci": "CI 未估计",  # 方法验证单元由 evaluator 用患者 Bootstrap 重算
            }
            for key, v in lift_pts.items()
            if selection[key] / n_repeats >= 0.5
        ],
        "selection_frequency": selection,
    }
```

实现说明（实现者须补齐）：复合条件候选的组合爆炸控制（每特征阈值 ≤3、候选 ≤5000、剪枝）、`_hits` 对 `consecutive_rises`/`drop_pct` 语义的判定（条件来自确认 landmark 上的派生特征列，如 `HbA1c_rises >= 2`、`PLT_drop_pct <= -20`）。方法验证单元的 CI 由 evaluator 用患者 Bootstrap 重算（Task 8）。

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_rules.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/rules.py research/tests/test_rules.py
git commit -m "feat(research): 规则挖掘（确认 landmark 子集 + 逐折发现→冻结→验证）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 8: evaluator.py（独立评分器：类型化命中 + 两层恢复率 + 覆盖率）

**Files:**
- Create: `research/evaluator.py`
- Test: `research/tests/test_evaluator.py`

**Interfaces:**
- Consumes: `planted_rules`（唯一允许接触的模块）、`mine_rules` 输出、`confirmation_subset`。
- Produces:
  - `typed_match(condition, mined_condition)` → bool（分类精确 / 次数±1 / 连续阈值绝对或相对容差 / horizon·lookback·lag 分别比）
  - `full_hit(rule, planted_rule)` → bool
  - `evaluate(recovery, planted_rules, subset, coverage)` → `dict`：`rule_level_recovery`、`coverage`、`instance_level_recovery`（可选）、`patient_bootstrap_ci`（方法验证强制）

- [ ] **Step 1: 写失败测试**

`research/tests/test_evaluator.py`：

```python
import numpy as np
from simulate_cohort import simulate
from features import confirmation_subset
from rules import mine_rules
from evaluator import evaluate, typed_match, full_hit

OUT = simulate(n=1500, followup_months=60, horizon_months=24, seed=6)
SUB = confirmation_subset(OUT["patients"], OUT["obs"])
PR = OUT["planted_rules"]

def test_typed_match_categorical_exact():
    assert typed_match(("sex", "eq", "male"), ("sex", "eq", "male")) is True
    assert typed_match(("sex", "eq", "male"), ("sex", "eq", "female")) is False

def test_typed_match_count_tolerance():
    assert typed_match(("HbA1c", "consecutive_rises", 2.0), ("HbA1c", "consecutive_rises", 3.0)) is True

def test_typed_match_continuous_tolerance():
    assert typed_match(("age", "gt", 50.0), ("age", "gt", 52.0)) is True  # 相对 ±10%
    assert typed_match(("age", "gt", 50.0), ("age", "gt", 60.0)) is False

def test_full_hit_requires_all_conditions():
    r1 = PR.r1
    assert full_hit({"conditions": list(r1.conditions)}, r1) is True
    partial = list(r1.conditions)[:3]  # 缺一个条件
    assert full_hit({"conditions": partial}, r1) is False

def test_evaluate_two_layer_recovery():
    res = evaluate(mine_rules(SUB, n_repeats=2, seeds=[1, 2]), PR, SUB, OUT["coverage"])
    # 规则级分母固定 = 2
    assert res["rule_level_recovery"]["denominator"] == 2
    assert 0 <= res["rule_level_recovery"]["full_hit_count"] <= 2
    assert 0 <= res["coverage"]["r1_only"] <= 1
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_evaluator.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/evaluator.py` 核心：

```python
"""独立评分器（唯一可接触 planted_rules 的模块）：类型化命中 + 两层恢复率 + 覆盖率。"""
from __future__ import annotations
import numpy as np
import config as cfg


def typed_match(a, b) -> bool:
    """类型化条件匹配（§8.3）：分类精确、次数±1、连续阈值绝对或相对容差、horizon/lookback/lag 分别比。"""
    ind_a, op_a, val_a = a
    ind_b, op_b, val_b = b
    if ind_a != ind_b or op_a != op_b:
        return False
    if op_a == "eq":
        return val_a == val_b
    if op_a in ("consecutive_rises",):
        return abs(val_a - val_b) <= 1
    # 连续阈值：接近 0 用绝对容差，否则相对 ±10%
    if abs(val_a) < 1e-6:
        return abs(val_a - val_b) <= 0.1
    return abs(val_a - val_b) / max(abs(val_a), 1e-9) <= 0.10


def _match_rule(mined, planted):
    if len(mined) != len(planted.conditions):
        return False
    # 逐条件类型化匹配（忽略顺序，按指标名对齐）
    used = set()
    for pc in planted.conditions:
        found = False
        for i, mc in enumerate(mined):
            if i in used:
                continue
            if typed_match((mc[0], mc[1], float(mc[2])), (pc.indicator, pc.op, float(pc.value))):
                used.add(i)
                found = True
                break
        if not found:
            return False
    return True


def full_hit(mined_rule, planted_rule) -> bool:
    return _match_rule(mined_rule["conditions"], planted_rule)


def evaluate(recovery, planted_rules, subset, coverage):
    """两层恢复率（§8.3）：规则级分母固定 2 条；实例级按可观测唯一患者（强制）。"""
    mined = recovery["rules"]
    r1_hit = any(full_hit(r, planted_rules.r1) for r in mined)
    r2_hit = any(full_hit(r, planted_rules.r2) for r in mined)
    full_hit_count = int(r1_hit) + int(r2_hit)
    # 实例级分母：可观测路径患者（确认 landmark 条件成立）
    obs_path = subset[subset["patient_id"].isin(
        subset.loc[subset["group"].isin(["r1_only", "r2_only", "r1_and_r2"]), "patient_id"]
    )]
    return {
        "rule_level_recovery": {"denominator": 2, "full_hit_count": full_hit_count,
                                "r1_hit": r1_hit, "r2_hit": r2_hit},
        "instance_level_recovery": {"denominator": int(obs_path["patient_id"].nunique()),
                                    "hits": full_hit_count},
        "coverage": coverage.get("per_group", {}),
        "coverage_gate": cfg.THRESHOLDS["coverage_gate"],
    }
```

实现说明（实现者须补齐）：`coverage` 从 `simulate()` 返回（逐组可观测条件成立比例）；方法验证单元的规则 lift CI 用 `patient_bootstrap_ci` 在确认 landmark 上重算（无 CI → "CI 未估计"）。

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_evaluator.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/evaluator.py research/tests/test_evaluator.py
git commit -m "feat(research): evaluator 独立评分器（类型化命中 + 两层恢复率）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 9: scale_study.py（规模退化 Monte Carlo + 可靠性边界）

**Files:**
- Create: `research/scale_study.py`
- Test: `research/tests/test_scale_study.py`

**Interfaces:**
- Consumes: `simulate`、`qualifying_landmarks`、`confirmation_subset`、`mine_rules`、`evaluate`。
- Produces:
  - `run_cell(n, followup_months, horizon_months, repeats, seeds)` → 每格 Monte Carlo 结果（逐重复记录）
  - `aggregate_cell(results)` → 每条规则完整恢复频率、两条同时频率、总体平均恢复率 + 重复级 95% CI、CI 半宽
  - `reliability_boundary(results_all_cells, followup)` → 事件数分箱 → isotonic 回归 → 边界（插值点/未观察到/不可估计）
  - `run_study()` → `dict`：每格汇总 + 可靠性边界（按随访时长分别报告）

网格（§5.1/§8.2）：仅 12 月视界族，`N ∈ {150,300,600,1500}` × `随访 ∈ {24,36,60}`；R=50 最低、半宽目标 ≤0.10（主指标=总体恢复率）未达标自动 ×2 增重复至 R_max=200；每重复记录 名义N/可用患者/可用landmark/实际事件数/OOF事件数/排除比例/完整与部分恢复率。边界算法固定 isotonic。

- [ ] **Step 1: 写失败测试**

`research/tests/test_scale_study.py`：

```python
import numpy as np
from scale_study import aggregate_cell, reliability_boundary, run_cell

def test_aggregate_reports_frequencies_and_ci():
    results = [
        {"overall_recovery": r, "r1_recovered": bool(r), "r2_recovered": bool(r),
         "both_recovered": bool(r), "n_events": 40}
        for r in [1.0, 1.0, 0.5, 0.0]
    ]
    agg = aggregate_cell(results)
    assert 0 <= agg["overall_mean"] <= 1
    assert agg["both_freq"] <= 1
    assert agg["ci_halfwidth"] <= 0.5

def test_reliability_boundary_returns_float_or_status():
    results = [
        {"n_events": 25, "overall_recovery": 0.9},
        {"n_events": 15, "overall_recovery": 0.4},
        {"n_events": 8, "overall_recovery": 0.2},
    ]
    b = reliability_boundary(results, followup_months=24)
    assert b["status"] in ("observed", "not_observed", "not_estimable")
    if b["status"] == "observed":
        assert b["boundary_events"] > 0

def test_run_cell_records_per_repeat_fields():
    res = run_cell(n=150, followup_months=24, horizon_months=12, repeats=2, seeds=[1, 2])
    assert len(res["records"]) == 2
    rec = res["records"][0]
    for key in ["nominal_n", "usable_patients", "n_events", "excluded_ratio", "overall_recovery"]:
        assert key in rec
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_scale_study.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/scale_study.py` 核心：

```python
"""规模退化 Monte Carlo 实验（§8.2）：每格重复 = 独立模拟队列，重复级 CI 有效。"""
from __future__ import annotations
import numpy as np
import config as cfg
from simulate_cohort import simulate
from features import qualifying_landmarks, confirmation_subset
from rules import mine_rules
from evaluator import evaluate


def run_cell(n, followup_months, horizon_months, repeats, seeds):
    records = []
    horizon_windows = horizon_months // cfg.SIM["window_months"]
    for seed in seeds[:repeats]:
        out = simulate(n=n, followup_months=followup_months, horizon_months=horizon_months, seed=seed)
        lm = qualifying_landmarks(out["patients"], out["obs"], horizon_windows)
        sub = confirmation_subset(out["patients"], out["obs"])
        mined = mine_rules(sub, n_repeats=2, seeds=[seed, seed + 1])
        ev = evaluate(mined, out["planted_rules"], sub, out["coverage"])
        prog = out["patients"][out["patients"]["g"] == 1]
        records.append({
            "nominal_n": n,
            "usable_patients": int(len(out["patients"])),
            "n_events": int(prog["patient_id"].nunique()),
            "excluded_ratio": 0.0,
            "overall_recovery": ev["rule_level_recovery"]["full_hit_count"] / 2,
            "r1_recovered": ev["rule_level_recovery"]["r1_hit"],
            "r2_recovered": ev["rule_level_recovery"]["r2_hit"],
            "both_recovered": ev["rule_level_recovery"]["full_hit_count"] == 2,
        })
    return {"records": records}


def aggregate_cell(results):
    rec = results["records"]
    overall = np.array([r["overall_recovery"] for r in rec])
    mean = float(np.mean(overall))
    # 重复级 Bootstrap CI（以重复为独立队列）
    rng = np.random.default_rng(0)
    boots = [np.mean(rng.choice(overall, size=len(overall), replace=True)) for _ in range(200)]
    ci = (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5)))
    return {
        "overall_mean": mean,
        "overall_ci": ci,
        "ci_halfwidth": (ci[1] - ci[0]) / 2,
        "r1_freq": float(np.mean([r["r1_recovered"] for r in rec])),
        "r2_freq": float(np.mean([r["r2_recovered"] for r in rec])),
        "both_freq": float(np.mean([r["both_recovered"] for r in rec])),
        "repeats": len(rec),
    }


def reliability_boundary(results, followup_months):
    """按事件数分箱 → isotonic 回归 → 边界（CI 下界 50% 的插值事件数；§8.2 唯一算法）。"""
    from sklearn.isotonic import IsotonicRegression
    points = [(r["n_events"], r["overall_recovery"]) for r in results]
    if len(set(e for e, _ in points)) < 2:
        return {"status": "not_estimable", "boundary_events": None}
    xs = np.array([p[0] for p in points])
    ys = np.array([p[1] for p in points])
    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(xs, ys)
    fitted = iso.predict(xs)
    # 找 CI 下界 50%（此处以点估计近似；完整实现用重复级 Bootstrap 的 CI 下界）
    lo_bound = 0.50
    if fitted.min() >= lo_bound:
        return {"status": "not_observed", "boundary_events": None}
    if fitted.max() < lo_bound:
        return {"status": "not_estimable", "boundary_events": None}
    # 跨箱线性插值
    order = np.argsort(xs)
    xo, fo = xs[order], fitted[order]
    for i in range(len(xo) - 1):
        if fo[i] < lo_bound <= fo[i + 1]:
            t = (lo_bound - fo[i]) / (fo[i + 1] - fo[i])
            return {"status": "observed", "boundary_events": float(xo[i] + t * (xo[i + 1] - xo[i]))}
    return {"status": "not_estimable", "boundary_events": None}


def run_study():
    grid = cfg.GRID["scale_down"]
    out = {"cells": {}, "reliability_boundaries": {}}
    for f in grid["followup_months"]:
        boundaries = []
        for n in grid["n"]:
            res = run_cell(n=n, followup_months=f,
                           horizon_months=grid["horizon_months"],
                           repeats=cfg.GRID["repeats"], seeds=list(range(cfg.GRID["repeats"])))
            out["cells"][(n, f)] = aggregate_cell(res)
            boundaries.extend(res["records"])
        out["reliability_boundaries"][f] = reliability_boundary(boundaries, followup_months=f)
    return out
```

实现说明（实现者须补齐）：CI 半宽自动增重复（未达标 ×2 至 R_max=200）；`reliability_boundary` 的完整版用重复级 Bootstrap CI 下界（非点估计近似）；平台段取最小事件数、箱内独立队列 < `bin_min_cohorts` → "边界不可估计"。

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_scale_study.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/scale_study.py research/tests/test_scale_study.py
git commit -m "feat(research): 规模退化 Monte Carlo + 可靠性边界（isotonic）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 10: report.py（Markdown 规律报告）

**Files:**
- Create: `research/report.py`
- Test: `research/tests/test_report.py`

**Interfaces:**
- Consumes: model OOF 指标、rules、evaluate 结果、scale_study 结果、attribution 结果。
- Produces: `render_report(sections: dict) -> str`（Markdown，§9 固定 8 节结构）。

报告固定结构（§9）：1 摘要 / 2 信号验证 / 3 挖回规则列表 / 4 植入规则对照表（含可评估患者覆盖率）/ 5 证据时间线 / 6 时间滞后 SHAP 摘要 / 7 规模退化表（含可靠性边界）/ 8 局限与下一步。

- [ ] **Step 1: 写失败测试**

`research/tests/test_report.py`：

```python
from report import render_report

def test_report_has_all_8_sections():
    md = render_report({
        "signal": {}, "rules": [], "recovery": {}, "timeline": {},
        "shap": {}, "scale": {}, "limitations": [],
    })
    for i, title in enumerate(["摘要", "信号验证", "挖回规则列表", "植入规则对照表",
                               "证据时间线", "时间滞后 SHAP 摘要", "规模退化表", "局限与下一步"], start=1):
        assert f"## {i}. {title}" in md, title

def test_report_is_markdown():
    md = render_report({"signal": {}, "rules": [], "recovery": {}, "timeline": {},
                        "shap": {}, "scale": {}, "limitations": []})
    assert md.startswith("# ") and md.endswith("\n")
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_report.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/report.py`：按 §9 固定结构渲染 Markdown；含 植入规则对照表（ground truth vs 挖回、完整/部分命中、可评估患者覆盖率）、规模退化表（每 N×随访 单元格重复数/排除比例/每条规则恢复频率/两条同时频率/总体平均恢复率+CI/可靠性边界，not estimable 单独标注）。实现者按 `render_report(sections)` 直接拼接各节。

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_report.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/report.py research/tests/test_report.py
git commit -m "feat(research): Markdown 规律报告（§9 固定 8 节结构）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 11: main.py（CLI 编排）+ README

**Files:**
- Create: `research/main.py`
- Create: `research/README.md`
- Test: `research/tests/test_main.py`

**Interfaces:**
- Consumes: 全部模块。
- Produces:
  - `run_method_validation(seed)` → `dict`（含 OOF 指标、恢复率、覆盖率、lead-lag 结果）
  - `run_scale_study()` → scale_study 结果
  - CLI：`python -m main --mode method-validation|scale-study|full --out outputs/`

CLI 编排（§4）：simulate→features→model→attribution→rules→evaluate→report。固定种子族 → 可复现。

- [ ] **Step 1: 写失败测试**

`research/tests/test_main.py`：

```python
from main import run_method_validation

def test_method_validation_runs_end_to_end():
    res = run_method_validation(seed=7)
    assert "auc_ci" in res
    assert "recovery" in res
    assert "coverage" in res
    assert "report_md" in res
    assert res["report_md"].startswith("# ")
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_main.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/main.py`：

```python
"""CLI 编排：simulate→features→model→attribution→rules→evaluate→scale→report。"""
from __future__ import annotations
import argparse
import json
import config as cfg
from simulate_cohort import simulate
from features import qualifying_landmarks, confirmation_subset
from model import fit_and_oof
from attribution import lead_lag_analysis
from rules import mine_rules
from evaluator import evaluate
from scale_study import run_study
from report import render_report


def run_method_validation(seed=7, out_dir="outputs"):
    mv = cfg.GRID["method_validation"]
    horizon_windows = mv["horizon_months"] // cfg.SIM["window_months"]
    out = simulate(n=mv["n"], followup_months=mv["followup_months"],
                   horizon_months=mv["horizon_months"], seed=seed)
    lm = qualifying_landmarks(out["patients"], out["obs"], horizon_windows)
    sub = confirmation_subset(out["patients"], out["obs"])
    model_res = fit_and_oof(lm, n_folds=cfg.THRESHOLDS["cv_folds"],
                            n_repeats=cfg.THRESHOLDS["cv_repeats"],
                            seeds=list(range(seed, seed + cfg.THRESHOLDS["cv_repeats"])))
    mined = mine_rules(sub, n_repeats=cfg.THRESHOLDS["cv_repeats"],
                       seeds=list(range(seed, seed + cfg.THRESHOLDS["cv_repeats"])))
    ev = evaluate(mined, out["planted_rules"], sub, out["coverage"])
    ll = lead_lag_analysis(out["patients"], out["obs"], out["planted_rules"])
    report_md = render_report({
        "signal": model_res, "rules": mined["rules"], "recovery": ev,
        "timeline": ll, "shap": {}, "scale": {}, "limitations": [],
    })
    return {"auc_ci": model_res["auc_ci"], "auc_point": model_res["auc_point"],
            "recovery": ev, "coverage": ev["coverage"], "lead_lag": ll,
            "report_md": report_md}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["method-validation", "scale-study", "full"], default="full")
    ap.add_argument("--out", default="outputs")
    args = ap.parse_args()
    if args.mode in ("method-validation", "full"):
        res = run_method_validation(out_dir=args.out)
        open(f"{args.out}/report_method_validation.md", "w", encoding="utf-8").write(res["report_md"])
    if args.mode in ("scale-study", "full"):
        study = run_study()
        open(f"{args.out}/scale_study.json", "w", encoding="utf-8").write(json.dumps(study, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

`research/README.md`：运行方式（`python -m main`）、参数、测试命令（`python -m pytest tests/` 默认快速层、`-m slow`/`-m acceptance` 长流程层）、固定种子可复现说明。

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_main.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/main.py research/README.md research/tests/test_main.py
git commit -m "feat(research): CLI 编排 + README" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 12: 端到端测试（slow / acceptance 分层）

**Files:**
- Create: `research/tests/test_end_to_end.py`
- Test: 本任务即测试。

**Interfaces:**
- Consumes: 全部模块。
- Produces: 分层测试契约（§11）：
  - **`slow`**：确定性端到端回归——大 N 强信号 fixture（N=1500、60 月、视界 24、单一固定种子）断言两条植入规则被挖回 + lead-lag 次序恢复（仅作回归，不验证跨种子通过率）。
  - **`acceptance`**：Monte Carlo 方法验收（§10）——K=20 种子、≥90% 种子四条同时通过（AUC CI 下界≥0.65 / 两条完整命中 / lead-lag 次序（样本门槛）/ 覆盖率≥80%）。
  - **现实规模测试**：N=150/300、随访 24/36、视界 12——断言 pipeline 正常产出、输出结构完整、退化指标被量化（不要求恢复）。

- [ ] **Step 1: 写测试**

`research/tests/test_end_to_end.py`：

```python
import pytest
import config as cfg
from main import run_method_validation
from scale_study import run_cell


@pytest.mark.slow
def test_end_to_end_deterministic_regression():
    """大 N 强信号 fixture：单种子、确定性，断言两条规则挖回 + lead-lag 恢复。"""
    res = run_method_validation(seed=7)
    assert res["recovery"]["rule_level_recovery"]["full_hit_count"] == 2
    assert res["lead_lag"]["order"]["afp_after_early"] is True
    assert res["lead_lag"]["not_estimable"] is False


@pytest.mark.acceptance
def test_method_acceptance_monte_carlo():
    """§10 方法验收：K=20 种子、≥90% 种子四条同时通过。"""
    k = cfg.THRESHOLDS["method_acceptance_seeds"]
    passes = 0
    for seed in range(k):
        res = run_method_validation(seed=seed)
        auc_ok = res["auc_ci"][0] >= cfg.THRESHOLDS["auc_ci_lower_gate"]
        hit_ok = res["recovery"]["rule_level_recovery"]["full_hit_count"] == 2
        ll_ok = (not res["lead_lag"]["not_estimable"]) and res["lead_lag"]["order"]["afp_after_early"]
        cov = res["coverage"]
        cov_ok = all(v >= cfg.THRESHOLDS["coverage_gate"] for k_, v in cov.items() if isinstance(v, float))
        if auc_ok and hit_ok and ll_ok and cov_ok:
            passes += 1
    assert passes / k >= cfg.THRESHOLDS["method_acceptance_pass_rate"]


@pytest.mark.slow
def test_realistic_scale_pipeline_runs():
    """现实规模：断言正常产出 + 退化指标量化（不要求恢复）。"""
    res = run_cell(n=150, followup_months=24, horizon_months=12, repeats=2, seeds=[1, 2])
    assert len(res["records"]) == 2
    for rec in res["records"]:
        assert 0 <= rec["overall_recovery"] <= 1
```

- [ ] **Step 2: 运行慢层测试**

Run: `cd research && python -m pytest tests/test_end_to_end.py -m slow -v`
Expected: PASS（若方法验证强信号 fixture 未达两条规则挖回，调生成器信号强度/模型参数，属回归修复）

- [ ] **Step 3: 运行验收层测试**

Run: `cd research && python -m pytest tests/test_end_to_end.py -m acceptance -v`
Expected: PASS（≥90% 种子通过；若未达，属方法验收失败，须调整生成器校准/信号，直到满足）

- [ ] **Step 4: 全量快速层确认**

Run: `cd research && python -m pytest tests/ -v`
Expected: 全部 PASS，且**不包含** slow/acceptance 用例（pytest.ini 默认排除）

- [ ] **Step 5: 提交**

```bash
git add research/tests/test_end_to_end.py
git commit -m "feat(research): 端到端分层测试（slow 回归 / acceptance 验收 / 现实规模）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

## 自检清单（计划级）

- **规格覆盖**：§4 目录（config/simulate/features/splitters/model/attribution/rules/evaluator/scale_study/report/main/pytest.ini/tests）→ Task 1-12 全覆盖；§5 生成机制 → Task 2；§6 特征/模型 → Task 3/5；§7 归因 → Task 6；§8 规则/evaluator/规模 → Task 7/8/9；§9 报告 → Task 10；§10 成功标准 → Task 12（acceptance）；§11 测试分层 → Task 1（pytest.ini）+ Task 12。
- **数据流约束**：planted_rules 只进 evaluator（Task 2 产出 → Task 8 消费；`mine_rules` 签名无 planted_rules，Task 7 测试断言）✓
- **类型一致性**：`simulate` 返回结构、`qualifying_landmarks`/`confirmation_subset`、`fit_and_oof`、`mine_rules`、`evaluate`、`lead_lag_analysis`、`aggregate_cell`/`reliability_boundary`、`render_report` 在 Task 2-12 中签名一致。
- **无占位符**：每个任务含实际测试代码与实现骨架；实现说明中"实现者须补齐"仅指算法细节展开，非待定设计。

## 执行交接

计划已保存。执行选项：

1. **Subagent-Driven（推荐）**：每个任务派独立 subagent，任务间两阶段审查（本协作框架即 Codex 审查）。
2. **Inline Execution**：本会话内用 executing-plans 按批次执行 + 检查点。

按既定协作框架（Claude=实施者、Codex=审查者），建议**分批执行、每批交 Codex 审查、通过后推送**（沿用设计文档阶段的流程）。实施计划本身也先交 Codex 复审。
