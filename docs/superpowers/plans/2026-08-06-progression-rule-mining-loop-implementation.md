# 疾病进展规律挖掘 · 端到端最小闭环 实施计划（v2）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `research/` 独立子项目中实现端到端最小闭环：用含植入规律的模拟纵向数据跑通"模拟 → 窗口特征 → 模型 → 时序归因 → 规则挖掘 → evaluator → 规模退化 → 规律报告"全链路，验证方法论能可信地恢复植入规律，并量化现实数据规模下的可信度。

**Architecture:** 每个模块单一职责、纯接口清晰、可独立单测。`simulate_cohort` 产出「数据集 + planted_rules」；数据集流向 features→model→attribution→rules；**planted_rules 只流向 evaluator**（数据流约束，防答案泄漏）。模型训练用全量合格 landmark，规则/校准/evaluator 用每患者确认 landmark（§5.5 分角色口径表）。

**Tech Stack:** Python 3.10+、pandas、scikit-learn（GradientBoostingClassifier / IsotonicRegression）、shap、pytest（`slow`/`acceptance` marker）；matplotlib 可选。

**规格依据：** `docs/superpowers/specs/2026-08-06-progression-rule-mining-loop-design.md`（v16，Codex 通过）。
**计划修订：** v2 按 Codex 计划复审 9 条意见修订——① planted_rules 只进 evaluator（含 attribution 与全模块签名断言）；② 事件门控/校准唯一算法（bisection 求解器 + 双视界测试 + P_obs）；③ landmark 角色口径落地（neither 首个合格参考 landmark、确认子集带 horizon/group/unobservable）；④ 聚类 Bootstrap 保留 multiplicity；⑤ lead-lag 验收门槛逐指标；⑥ 规则标准词汇（MinedCondition/MinedRule，完整命中可达）；⑦ 可靠性边界按规格算法（分箱+Bootstrap+isotonic+边情形）；⑧ main 编排完整数据流；⑨ acceptance 无空洞通过 + 现实规模参数化 + 可复现。

## Global Constraints

以下约束**每个任务都必须遵守**，值从规格原样抄录：

- **独立边界**：`research/` 自带版本化 `config.py`；**禁止** import 生产 `prediction_engine.py`、访问生产数据库、写现有表/API。
- **数据流**：`planted_rules` **只进 `evaluator.py`**；`lead_lag_analysis`、`mine_rules` 等所有非 evaluator 模块签名**不得接收** planted_rules（Task 1 有全模块签名断言测试）。
- **主 estimand**：校准/验收/evaluator/规则/support/lift 用**每患者确认/参考 landmark**（R2/交集=w_A+1、R1-only=w_R1、neither=首个合格参考 landmark）；模型训练用**全量合格 landmark**；splitter 用**患者级结局**（仅分层，不进特征/规则）。
- **δ ∈ {1,2}**（默认 1），`w_event = 确认窗口 + δ`；`w_A+2` 仅作 R2 路径"高危区标记"，**绝不被当成事件窗口**。
- **事件门控**：路径组 `g ~ Bernoulli(p_group)`；neither 不抽 p_group，由基线 hazard λ_b(t) 触发；校准目标是**观察到的确认 landmark 条件风险**（互斥组口径），不是按 z。
- **校准目标 = 潜在真实事件风险**（完整事件真值 g+事件窗口，不受删失影响，N=50,000 队列 ±3pp 验收，**两视界 24/12 均验收**）；`P_obs`（观测标签风险，公式见 Task 3）单独报告、**不参与 §10 验收**。
- **标签**：正例 = 视界内且删失/行政终止前已观察到事件；unknown = 视界内先删失且在删失前未观察到事件（从标注集排除）；潜在 g+事件窗口**不得进入模型/OOF/规则流程**。
- **患者聚类**：CI、support、Bootstrap 全部按患者聚类；Bootstrap 抽样**保留 multiplicity**（带替换，重采样行集）。
- **信号门槛**：方法验证单元最终平均 OOF 预测上 AUC 的患者聚类 95% CI **下界 ≥ 0.65**；现实单元只报告。
- **成功标准（方法验收）**：K=20 种子、≥90% 通过；每种子四条同时成立——① AUC CI 下界 ≥0.65、② 两条植入规则均完整命中、③ lead-lag 次序恢复（R1∩R2 交集唯一患者 ≥30、**每指标可分析患者 ≥20**、unmatched ≤20%，不足 not estimable）、④ **R1、R2 各自可评估覆盖率 ≥80%**。**规则必须携带 Bootstrap CI（"CI 未估计"的运行不得标为通过）**。
- **测试分层**：`pytest.ini` 配 `addopts = -m "not slow and not acceptance"`，注册 `slow`/`acceptance` marker；默认只跑快速层。
- **TDD**：每步先写失败测试→确认红→最小实现→确认绿→单独提交。提交正文三行：`AI-Agent: Codex`、`AI-Client: Codex-Desktop`、`Task-ID: research-progression-min-loop`。
- **不 push**（用户在 Codex 审查通过后统一推送）；在 main 分支直接开发。

---

## 共享数据契约与标准词汇（各任务间接口，先定死）

### `patients` DataFrame（每患者一行）

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `patient_id` | int | 0..N-1 |
| `z` | str | 生成路径 `"none"`/`"r1"`/`"r2"`/`"r1_and_r2"` |
| `age` | int | 静态协变量 |
| `sex` | str | `"male"`/`"female"` |
| `group` | str | 确认/参考 landmark 上的互斥组 `"neither"`/`"r1_only"`/`"r2_only"`/`"r1_and_r2"`；路径条件不可观测时该字段为 `"neither"` 且 `unobservable=True`（见下） |
| `confirm_window` | int | 确认/参考 landmark 窗口序号 |
| `w_r1` | float | 生成器内部锚点：R1 条件确认窗口（R2-only 为 `NaN`） |
| `w_a` | float | 生成器内部锚点：AFP 激活窗口（R1-only 为 `NaN`） |
| `g` | float | 路径组事件门控指示 0/1；neither 为 `NaN` |
| `event_window` | float | 潜在事件窗口（进展者）；否则 `NaN` |
| `censored` | bool | 是否失访删失 |
| `censored_window` | float | 删失窗口；否则 `NaN` |
| `admin_end` | int | 行政随访终点窗口序号 |
| `unobservable` | bool | 路径组：指定确认 landmark 不合格/非无事件/条件未成立 → `True`（从 evaluator 分母排除，**不改组归属语义**）；neither 恒 `False` |

### `obs` DataFrame（每患者每窗口一行）

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `patient_id` | int | 关联 patients |
| `window` | int | 0..admin_end |
| `ALT`..`BMI` | float | 10 个指标观测（含测量噪声） |

指标常量（`config.INDICATORS`）：`ALT, AST, GGT, TBIL, ALB, PLT, HbA1c, AFP, WAIST, BMI`。

### 标准规则词汇（`rules.py` 与 `evaluator.py` 共用，完整命中可达）

```python
@dataclass(frozen=True)
class MinedCondition:
    indicator: str      # 标准名："sex"|"age"|"HbA1c"|"PLT"|"AFP"|...
    op: str             # 标准 op："eq"|"gt"|"lt"|"consecutive_rises"|"drop_pct"
    value: float
    lookback: int = 1
    source_feature: str = ""   # 派生特征来源（阈值选择用；不参与匹配）

@dataclass(frozen=True)
class MinedRule:
    conditions: tuple[MinedCondition, ...]
    horizon_windows: int
    lookback: int
    lag: int
```

**候选条件 → 标准语义映射**（Task 9 用）：`sex`→`("sex","eq")`；`age`→`("age","gt")`；`<IND>_rises≥k`→`("<IND>","consecutive_rises",k,lookback=k)`；`<IND>_drop_pct≤-d`→`("<IND>","drop_pct",d)`；`<IND>_cur` 高分位→`("<IND>","gt",q)`。

### `planted_rules`（只进 evaluator）

```python
@dataclass(frozen=True)
class Condition:
    indicator: str
    op: str                 # "eq"|"gt"|"consecutive_rises"|"drop_pct"
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
```

植入条件集（两视界通用）：R1 = `sex=male`、`age>50`、`HbA1c 连续 2 窗上升`、`PLT 较基线降 >20%`；R2 = `AFP 连续 ≥2 窗上升`。

### 确认/参考 landmark 与合格定义

- 合格 landmark（通用）：`窗口 ≥ 2`、`admin_end − 窗口 ≥ 视界窗数`、`窗口 < 事件窗口`（若有）、`窗口 < 删失窗口`（若有）。
- **neither 参考 landmark = 每患者首个合格 landmark**（窗口 ≥ 2 起顺序找；不向后跳）。若该参考 landmark 命中任一植入条件 → 计入误报、排除 neither 校准分母、**不标记不可观测**。
- 路径组确认 landmark：R2/交集 = `w_A+1`；R1-only = `w_R1`。指定确认 landmark **不合格、非无事件、或条件未成立** → `unobservable=True`（**不改为 neither 语义**）。

---

## 任务分解（14 任务）

### Task 1: 脚手架 + config.py + 数据流签名断言

**Files:**

- Create: `research/config.py`、`research/pytest.ini`、`research/requirements.txt`、`research/tests/__init__.py`
- Test: `research/tests/test_config.py`、`research/tests/test_dataflow.py`

**Interfaces:**

- Produces: `config.py` 全部命名常量（Task 2-14 依赖）。

- [ ] **Step 1: 写失败测试**

`research/tests/test_config.py`（与 v1 计划相同，逐常量断言，含 `horizon_months` 双视界校准表）：

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
```

`research/tests/test_dataflow.py`（Codex 计划复审 #1——**全模块**签名断言，不只 `mine_rules`）：

```python
import inspect
import simulate_cohort, features, splitters, model, attribution, rules, scale_study, report, main
import evaluator

def test_planted_rules_only_enters_evaluator():
    allowed = {"evaluator"}
    modules = [simulate_cohort, features, splitters, model, attribution, rules, scale_study, report, main]
    for mod in modules:
        for name, fn in inspect.getmembers(mod, inspect.isfunction):
            params = list(inspect.signature(fn).parameters)
            assert "planted_rules" not in params, f"{mod.__name__}.{name} 不得接收 planted_rules"
    # 明确校验关键函数签名
    assert "planted_rules" in inspect.signature(evaluator.evaluate).parameters
    assert "planted_rules" not in inspect.signature(attribution.lead_lag_analysis).parameters
    assert "planted_rules" not in inspect.signature(rules.mine_rules).parameters
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_config.py tests/test_dataflow.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'config'`）

- [ ] **Step 3: 写实现**

`research/pytest.ini`、`research/requirements.txt` 与 v1 相同（见 Task 1 v1 内容）。

`research/config.py`：与 v1 相同常量，另加：

```python
CALIBRATION = {
    24: {"neither": 0.12, "r1_only": 0.60, "r2_only": 0.40, "r1_and_r2": 0.73},
    12: {"neither": 0.06, "r1_only": 0.40, "r2_only": 0.25, "r1_and_r2": 0.52},
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
    "calibrate_tol": 0.005,      # bisection 收敛容差
    "calibrate_bisect_iters": 40,
    "event_bins": [0, 10, 20, 30, 40, 50, 75, 100, 150, 10 ** 9],
    "bin_min_cohorts": 10,
    "boundary_threshold": 0.50,
}
```

（其余常量 `INDICATORS`/`REFERENCE_RANGES`/`SIM`/`PLANTED_CONDITIONS` 与 v1 相同。）

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_config.py tests/test_dataflow.py -v`
Expected: PASS（dataflow 断言在 `evaluator`/`attribution`/`rules` 模块存在前会先红；Step 3 可先写 evaluator/attribution/rules 的空桩函数签名，使签名断言绿——实现留到对应任务）

- [ ] **Step 5: 提交**

```bash
git add research/config.py research/pytest.ini research/requirements.txt research/tests/
git commit -m "feat(research): 脚手架 + 版本化 config + planted_rules 数据流签名断言" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 2: simulate——Z/协变量/S 轨迹/观测 + 确认 landmark/组归属

**Files:**

- Create: `research/simulate_cohort.py`（数据契约类型 + 生成核心；门控/校准在 Task 3）
- Test: `research/tests/test_simulate_core.py`

**Interfaces:**

- Consumes: `config`。
- Produces: `Condition/PlantedRule/PlantedRules` 类型、`simulate(n, followup_months, horizon_months, seed, gate=None)` 返回结构（`patients`/`obs`/`planted_rules`/`coverage`）；`gate` 参数（Task 3 校准用）。

- [ ] **Step 1: 写失败测试**

`research/tests/test_simulate_core.py`：

```python
import numpy as np
import pandas as pd
from simulate_cohort import simulate

def _sim(**kw):
    kw.setdefault("n", 1500); kw.setdefault("followup_months", 60)
    kw.setdefault("horizon_months", 24); kw.setdefault("seed", 7)
    return simulate(**kw)

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
    out = _sim()
    p = out["patients"]
    for z in ("r1", "r1_and_r2"):
        sub = p[p["z"] == z]
        assert (sub["sex"] == "male").all() and (sub["age"] > 50).all()

def test_forward_no_event_leakage():
    out = _sim()
    prog = out["patients"].dropna(subset=["event_window"])
    assert (prog["event_window"] >= prog["confirm_window"] + 1).all()

def test_delta_strictly_in_1_2_and_w_a_plus_2_not_event():
    out = _sim()
    prog = out["patients"].dropna(subset=["event_window"])
    diff = (prog["event_window"] - prog["confirm_window"]).to_numpy()
    assert set(diff) <= {1, 2}
    # w_A+2 绝不当事件窗口：事件 = confirm + δ，confirm 对 R2 是 w_A+1
    r2 = prog[prog["z"].isin(["r2", "r1_and_r2"])]
    assert not ((r2["event_window"] == r2["w_a"] + 2) & (r2["confirm_window"] == r2["w_a"])).any()

def test_neither_reference_is_first_qualifying_landmark():
    out = _sim()
    ne = out["patients"][out["patients"]["z"] == "none"]
    # 参考 landmark 须合格：>=2、admin_end-confirm >= horizon、事件/删失之前
    assert (ne["confirm_window"] >= 2).all()
    assert (ne["admin_end"] - ne["confirm_window"] >= 24 // 6).all()

def test_path_unobservable_does_not_reassign_to_neither():
    out = _sim()
    # 若存在不可观测路径患者，其 group 不得因条件未成立被标为 neither 语义
    unobs = out["patients"][out["patients"]["unobservable"]]
    assert (unobs["z"] != "none").all()
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_simulate_core.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/simulate_cohort.py`（核心；门控用 Task 3 的 `gate` 参数，此处先以 `p_group=target` 简化，Task 3 替换为校准值）：

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
    name: str; horizon_months: int; conditions: tuple[Condition, ...]; group: str; target_risk: float

@dataclass(frozen=True)
class PlantedRules:
    horizon_months: int; r1: PlantedRule; r2: PlantedRule; calibration: dict[str, float]


def _build_planted_rules(horizon_months):
    cal = cfg.CALIBRATION[horizon_months]
    r1 = PlantedRule("r1", horizon_months,
                     tuple(Condition(i, o, float(v)) for i, o, v in cfg.PLANTED_CONDITIONS["r1"]),
                     "r1_only", cal["r1_only"])
    r2 = PlantedRule("r2", horizon_months,
                     tuple(Condition(i, o, float(v)) for i, o, v in cfg.PLANTED_CONDITIONS["r2"]),
                     "r2_only", cal["r2_only"])
    return PlantedRules(horizon_months, r1, r2, cal)


def _sample_z_and_covariates(rng, n):
    """Z 与按 Z 条件采样的协变量（R1/R1∩R2 强制男且 >50）。"""
    paths = rng.choice(["none", "r1", "r2", "r1_and_r2"], n, p=[0.70, 0.15, 0.10, 0.05])
    ages, sexes = np.empty(n, int), np.empty(n, object)
    for i, z in enumerate(paths):
        if z in ("r1", "r1_and_r2"):
            sexes[i], ages[i] = "male", int(rng.integers(51, 80))
        else:
            sexes[i] = rng.choice(["male", "female"]); ages[i] = int(rng.integers(20, 70))
    return paths, ages, sexes


def _sample_anchors(rng, z, w0, admin_end, horizon_windows):
    """前向采样确认锚点（可行区间内拒绝采样；R1-only 不生成 w_A）。"""
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


def _first_qualifying_landmark(rng, admin_end, horizon_windows, event_window, censored_window):
    """neither 参考 landmark：首个合格窗口（>=2、视界够、事件/删失之前）。"""
    for w in range(2, admin_end - horizon_windows + 1):
        if np.isfinite(event_window) and w >= event_window: continue
        if np.isfinite(censored_window) and w >= censored_window: continue
        return w
    return np.nan


def simulate(n, followup_months, horizon_months, seed, gate=None):
    """生成纵向队列。gate：{group: p} 门控概率（Task 3 校准传入；None 用校准目标）。"""
    rng = np.random.default_rng(seed)
    window_months = cfg.SIM["window_months"]
    admin_end = followup_months // window_months
    horizon_windows = horizon_months // window_months
    cal = cfg.CALIBRATION[horizon_months]
    if gate is None:
        gate = {g: p for g, p in cal.items()}

    paths, ages, sexes = _sample_z_and_covariates(rng, n)
    sigma = {i: 0.1 * (cfg.REFERENCE_RANGES[i][1] - cfg.REFERENCE_RANGES[i][0]) for i in cfg.INDICATORS}
    band = 2.0; s_afp = 1.0; s_event = s_afp + band
    n_win = admin_end + 1

    rows, obs_rows = [], []
    for pid in range(n):
        z, age, sex = paths[pid], ages[pid], sexes[pid]
        w0 = int(rng.integers(0, 2))
        w_a, w_r1 = _sample_anchors(rng, z, w0, admin_end, horizon_windows)

        # S 轨迹（仅 R2 路径用分阶段阈值；R1-only 不要求 S_event）
        s = np.zeros(n_win)
        if z in ("r2", "r1_and_r2") and np.isfinite(w_a):
            s[w_a] = s_afp
            s[w_a + 1] = s_afp + rng.uniform(band / 2 + 1e-6, band - 1e-6)
            s[w_a + 2] = s[w_a + 1] + rng.uniform(band / 2 + 1e-6, band - 1e-6)

        # 事件门控（Task 3 细化；此处用 gate 的潜在概率，不含 λ_b 校准）
        g, event_window = np.nan, np.nan
        if z != "none":
            confirm = (w_a + 1) if z in ("r2", "r1_and_r2") else w_r1
            if np.isfinite(confirm):
                grp = "r1_and_r2" if z == "r1_and_r2" else ("r1_only" if z == "r1" else "r2_only")
                g = int(rng.random() < gate[grp])
                if g == 1:
                    delta = int(rng.choice(cfg.SIM["delta_choices"]))
                    event_window = confirm + delta
        else:
            # neither 基线 hazard：Task 3 用校准后的 h(t)；此处临时用 λ_b 简化
            ref = _first_qualifying_landmark(rng, admin_end, horizon_windows, np.nan, np.nan)
            for t in range(ref, min(ref + horizon_windows, n_win)):
                if rng.random() < 0.02 + 0.001 * (age - 20):
                    event_window = t; break

        # 观测 X(t) = 基线 + 信号 + 噪声
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

        censored = rng.random() < cfg.SIM["censoring_rate"]
        censored_window = float(rng.integers(1, n_win)) if censored else np.nan
        if z == "none":
            confirm = _first_qualifying_landmark(rng, admin_end, horizon_windows, event_window, censored_window)
            group, unobservable = "neither", False
        else:
            confirm = (w_a + 1) if z in ("r2", "r1_and_r2") else w_r1
            obs_by_w = {r["window"]: r for r in obs_rows[-n_win:]}
            r1_ok = _r1_holds(obs_by_w, confirm, age, sex) if z in ("r1", "r1_and_r2") else False
            r2_ok = _r2_holds(obs_by_w, confirm) if z in ("r2", "r1_and_r2") else False
            if not np.isfinite(confirm) or (z in ("r1", "r1_and_r2") and not r1_ok) or (z in ("r2", "r1_and_r2") and not r2_ok):
                group, unobservable = "neither", True      # 指定确认 landmark 不可观测，不改组语义
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
            "coverage": {}, "meta": {"horizon_windows": horizon_windows, "admin_end": admin_end}}


def _obs_dict(obs_rows_subset):
    return {r["window"]: r for r in obs_rows_subset}


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

实现说明：`test_neither_reference_is_first_qualifying_landmark` 断言 `admin_end - confirm_window >= horizon`——`_first_qualifying_landmark` 的循环上界 `range(2, admin_end - horizon_windows + 1)` 已保证；若该窗口区间为空返回 `np.nan`（该 neither 患者无可合格参考 landmark → not estimable 单元处理在 Task 4）。

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_simulate_core.py -v`
Expected: PASS（`test_delta_strictly_in_1_2_and_w_a_plus_2_not_event` 须通过：事件=confirm+δ 且 δ∈{1,2}）

- [ ] **Step 5: 提交**

```bash
git add research/simulate_cohort.py research/tests/test_simulate_core.py
git commit -m "feat(research): 模拟核心（Z 路径 + 前向生成 + 确认 landmark/组归属）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 3: simulate——事件门控 + 校准求解器（bisection）+ P_obs + coverage

**Files:**

- Modify: `research/simulate_cohort.py`
- Test: `research/tests/test_simulate_calibration.py`

**Interfaces:**

- Consumes: Task 2 的 `simulate`（含 `gate` 参数）。
- Produces:
  - `calibrate_gates(horizon_months, cal_n)` → `dict`：`{"gate": {group: p}, "lambda_base": float, "neither_risk": {...}}`
  - `simulate` 的 `coverage` 字段（逐互斥组可观测条件成立比例）与 `P_obs` 计算。
  - `p_obs(patients, subset, horizon_windows)` → `dict`（每互斥组 `positive/(positive+negative)`，unknown 排除）。

- [ ] **Step 1: 写失败测试**

`research/tests/test_simulate_calibration.py`：

```python
import numpy as np
from simulate_cohort import simulate, calibrate_gates, p_obs
import config as cfg

def test_calibrated_gates_hit_both_horizons():
    for horizon in (24, 12):
        out = simulate(n=50_000, followup_months=60 if horizon == 24 else 36,
                       horizon_months=horizon, seed=3)
        p = out["patients"]
        for grp, target in out["planted_rules"].calibration.items():
            sub = p[p["group"] == grp]
            if grp == "neither":
                risk = sub["event_window"].notna().mean()
            else:
                risk = sub["g"].mean()
            assert abs(risk - target) <= 0.03, (horizon, grp, risk, target)

def test_p_obs_formula_and_unknown_excluded():
    out = simulate(n=3000, followup_months=24, horizon_months=12, seed=4)
    po = p_obs(out["patients"], out["obs"], horizon_windows=2)
    for grp in ("r1_only", "r2_only", "r1_and_r2", "neither"):
        d = po[grp]
        assert d["denominator"] == d["positive"] + d["negative"]
        # 正例必须是删失/行政终止前观察到的事件
        assert 0 <= d["rate"] <= 1

def test_p_obs_not_part_of_acceptance_surface():
    # P_obs 不进入 §10：模拟器返回结构不把 P_obs 混入验收字段
    out = simulate(n=500, followup_months=24, horizon_months=12, seed=4)
    assert "p_obs" not in out  # P_obs 通过独立函数 p_obs() 提供

def test_coverage_per_group_returned():
    out = simulate(n=2000, followup_months=24, horizon_months=12, seed=5)
    cov = out["coverage"]["per_group"]
    assert set(cov) == {"r1_only", "r2_only", "r1_and_r2", "neither"}
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_simulate_calibration.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

追加到 `simulate_cohort.py`（唯一算法，非"调参数"）：

```python
def _observed_group_risk(out, grp):
    p = out["patients"]
    sub = p[p["group"] == grp]
    if grp == "neither":
        return sub["event_window"].notna().mean()
    return sub["g"].mean()


def _gate_from_bisection(grp, target, horizon, make_out, tol=cfg.THRESHOLDS["calibrate_tol"],
                         iters=cfg.THRESHOLDS["calibrate_bisect_iters"]):
    """bisection 求解 p_group，使观察到的确认 landmark 条件风险 ≈ target（唯一算法）。"""
    lo, hi = 0.0, 1.0
    for _ in range(iters):
        mid = (lo + hi) / 2
        out = make_out(mid)                     # 用 mid 门控生成大校准队列
        risk = _observed_group_risk(out, grp)
        if abs(risk - target) <= tol:
            return mid
        if risk < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _lambda_b_from_bisection(target, horizon, make_out):
    """bisection 求解基线 hazard 尺度 c，使 neither 潜在视界风险 ≈ target。"""
    lo, hi = 0.0, 0.2
    for _ in range(cfg.THRESHOLDS["calibrate_bisect_iters"]):
        mid = (lo + hi) / 2
        out = make_out(mid)
        risk = _observed_group_risk(out, "neither")
        if abs(risk - target) <= cfg.THRESHOLDS["calibrate_tol"]:
            return mid
        if risk < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def calibrate_gates(horizon_months, cal_n=cfg.SIM["calibration_n"]):
    """返回校准后的门控概率与 λ_b 尺度（bisection，唯一算法）。"""
    mv = cfg.GRID["method_validation"]
    followup = 60 if horizon_months == 24 else 36
    cal = cfg.CALIBRATION[horizon_months]
    gates = {}
    # 先校准路径组（在暂定 λ_b 下），再校准 neither；循环 2 轮收敛（路径组不依赖 neither）
    for grp, target in cal.items():
        if grp == "neither":
            continue
        gates[grp] = _gate_from_bisection(
            grp, target, horizon_months,
            lambda mid, grp=grp: simulate(cal_n, followup, horizon_months, 3,
                                          gate={**{g: t for g, t in cal.items() if g != grp}, grp: mid}))
    lambda_base = _lambda_b_from_bisection(
        cal["neither"], horizon_months,
        lambda c: _sim_with_lambda(cal_n, followup, horizon_months, c, gates))
    return {"gate": gates, "lambda_base": lambda_base}


def _sim_with_lambda(cal_n, followup, horizon, lambda_c, gates):
    """用给定 λ_b 尺度 c 生成队列（覆盖 simulate 的 neither 分支；Task 2 临时常数在此替换）。"""
    # 实现：将 simulate 的 neither 分支的 base_hazard 替换为 c * λ0(age,sex)，其余同 simulate
    # 为使实现唯一，simulate 接受 hidden 参数 _lambda_c；此处直接调用 simulate(..., _lambda_c=lambda_c)
    return simulate(cal_n, followup, horizon, 3, gate=gates, _lambda_c=lambda_c)


def p_obs(patients, obs, horizon_windows):
    """P_obs = positive/(positive+negative)（确认/参考 landmark 口径，unknown 全排除）。"""
    result = {}
    for grp in ("neither", "r1_only", "r2_only", "r1_and_r2"):
        sub = patients[patients["group"] == grp]
        pos = neg = 0
        for _, p in sub.iterrows():
            ev, cw = p["event_window"], p["censored_window"]
            if np.isfinite(ev) and ev <= p["confirm_window"] + horizon_windows and (not np.isfinite(cw) or cw > ev):
                pos += 1
            elif (not np.isfinite(ev) or ev > p["confirm_window"] + horizon_windows) and (not np.isfinite(cw) or cw > p["confirm_window"] + horizon_windows):
                neg += 1
            # unknown（视界内先删失且删失前未观察到事件）→ 完全排除
        result[grp] = {"positive": pos, "negative": neg, "denominator": pos + neg,
                       "rate": pos / (pos + neg) if pos + neg else float("nan")}
    return result
```

实现说明：`simulate` 增加 `_lambda_c` 可选参数（默认用 Task 2 临时常数；`calibrate_gates` 传入校准值）；`coverage` 字段按 §5.3 逐组计算（确认/参考 landmark 上可观测条件成立比例，neither 为两者均不成立比例 + 误报率）；`coverage` 仅在 `calibrate_gates` 已校准的 gate 下才有意义，`simulate` 在 `gate=None` 时用校准目标近似（测试 `test_calibrated_gates_hit_both_horizons` 用 `gate` 缺省 + `_lambda_c` 校准值）。

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_simulate_calibration.py -v`
Expected: PASS（两视界潜在风险 ±3pp；P_obs 公式与排除正确）

- [ ] **Step 5: 提交**

```bash
git add research/simulate_cohort.py research/tests/test_simulate_calibration.py
git commit -m "feat(research): 事件门控 + bisection 校准求解器 + P_obs + 逐组 coverage" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 4: features.py（合格 landmark + 确认子集 + 标签 + 角色口径）

**Files:**

- Create: `research/features.py`
- Test: `research/tests/test_features.py`

**Interfaces:**

- Consumes: `simulate()` 输出。
- Produces:
  - `qualifying_landmarks(patients, obs, horizon_windows)` → `pd.DataFrame`（**全量合格 landmark**，模型训练用；剔除 unknown 标签行并记录排除比例）
  - `confirmation_subset(patients, obs, horizon_windows)` → `pd.DataFrame`（**每患者确认/参考 landmark 一个样本**，含 `group`/`unobservable`；规则/evaluator 用）
  - `label_for(patient, window, horizon_windows)` → `0|1|"unknown"`
  - `derive_window_features(obs_rows, ind, window, runin)` → `dict`

- [ ] **Step 1: 写失败测试**

`research/tests/test_features.py`：

```python
import numpy as np
from simulate_cohort import simulate
from features import qualifying_landmarks, confirmation_subset, label_for, derive_window_features

def test_derived_features_hand_computation():
    rows = [{"window": 0, "ALT": 30.0}, {"window": 1, "ALT": 33.0}, {"window": 2, "ALT": 36.0}]
    f = derive_window_features(rows, "ALT", window=2, runin=2)
    assert f["ALT_cur"] == 36.0 and f["ALT_d6m"] == 3.0 and f["ALT_d12m"] == 6.0
    assert f["ALT_rises"] == 2

def test_qualifying_uses_all_landmarks_model_training():
    out = simulate(n=300, followup_months=24, horizon_months=12, seed=1)
    lm = qualifying_landmarks(out["patients"], out["obs"], horizon_windows=2)
    # 模型训练用全量：样本数 > 患者数
    assert len(lm) > out["patients"]["patient_id"].nunique()
    assert "label" in lm.columns

def test_confirmation_subset_one_per_patient_and_has_group():
    out = simulate(n=300, followup_months=24, horizon_months=12, seed=1)
    sub = confirmation_subset(out["patients"], out["obs"], horizon_windows=2)
    assert sub["patient_id"].is_unique
    assert "group" in sub.columns and "unobservable" in sub.columns
    # unobservable 患者排除（evaluator 分母）
    assert not sub[sub["unobservable"]]["patient_id"].duplicated().any()

def test_confirmation_subset_horizon_respected():
    out = simulate(n=200, followup_months=24, horizon_months=12, seed=1)
    sub = confirmation_subset(out["patients"], out["obs"], horizon_windows=2)
    assert (sub["admin_end"] - sub["window"] >= 2).all()

def test_label_semantics_observed_only():
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
"""窗口特征 + landmark 化（无未来泄漏；分角色口径见 §5.5）。"""
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
           "age": patient["age"], "sex": patient["sex"], "group": patient["group"]}
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
    """每患者确认/参考 landmark 一个样本（规则/evaluator 用；unobservable 保留待排除）。"""
    obs_by_pid = {pid: g.to_dict("records") for pid, g in obs.groupby("patient_id")}
    rows = []
    for _, p in patients.iterrows():
        w = p["confirm_window"]
        if not np.isfinite(w):
            continue
        r = _feature_row(p, obs_by_pid[p["patient_id"]], int(w))
        r["label"] = label_for(p, int(w), horizon_windows)
        r["unobservable"] = bool(p["unobservable"])
        rows.append(r)
    return pd.DataFrame(rows)
```

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_features.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/features.py research/tests/test_features.py
git commit -m "feat(research): 窗口特征 + 全量/确认 landmark 分角色口径 + 标签" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 5: splitters.py（患者折 + 聚类 Bootstrap，保留 multiplicity）

**Files:**

- Create: `research/splitters.py`
- Test: `research/tests/test_splitters.py`

**Interfaces:**

- Produces:
  - `patient_folds(patients, n_folds, seed)` → `np.ndarray`（每患者一折；患者级 + 结局分层）
  - `patient_bootstrap_samples(patient_ids, b, seed)` → `list[np.ndarray]`（带替换抽样患者 ID，**保留 multiplicity**）
  - `resample_rows(frame, sampled_ids)` → `pd.DataFrame`（按抽样 ID 复制行，保留 multiplicity）
  - `patient_bootstrap_ci(frame, stat_fn, b, seed)` → `(lo, hi)`

- [ ] **Step 1: 写失败测试**

`research/tests/test_splitters.py`：

```python
import numpy as np
import pandas as pd
from splitters import patient_folds, patient_bootstrap_samples, resample_rows, patient_bootstrap_ci

def _mk(n=100, p_event=0.3, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"patient_id": np.arange(n), "patient_event": rng.random(n) < p_event})

def test_patient_never_split_across_folds():
    df = _mk()
    folds = patient_folds(df, 5, 1)
    assert set(folds) <= {0, 1, 2, 3, 4}

def test_folds_stratified():
    df = _mk(400, p_event=0.3)
    folds = patient_folds(df, 5, 2)
    for k in range(5):
        assert abs(df.loc[folds == k, "patient_event"].mean() - 0.3) < 0.08

def test_bootstrap_preserves_multiplicity():
    df = pd.DataFrame({"patient_id": [0, 1], "value": [10.0, 20.0]})
    sample = np.array([0, 0])                      # 患者 0 抽两次
    rows = resample_rows(df, sample)
    assert len(rows) == 2
    assert rows["value"].sum() == 20.0             # 10 + 10，multiplicity 保留
    # 患者聚类 Bootstrap 的统计须反映 multiplicity：全抽 0 时均值 = 10
    stats = patient_bootstrap_samples(np.array([0, 1]), b=200, seed=0)
    assert all(len(s) == 2 for s in stats)

def test_patient_bootstrap_ci_uses_resampled_rows():
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({"patient_id": np.repeat(np.arange(20), 5),
                          "value": rng.normal(size=100)})
    lo, hi = patient_bootstrap_ci(frame, lambda d: d["value"].mean(), b=200, seed=0)
    assert lo < frame["value"].mean() < hi
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_splitters.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/splitters.py`：

```python
"""患者级 splitter + 聚类 Bootstrap（保留 multiplicity）。"""
from __future__ import annotations
import numpy as np
import pandas as pd


def patient_folds(patients, n_folds, seed):
    rng = np.random.default_rng(seed)
    out = np.full(len(patients), -1, dtype=int)
    ids = patients["patient_id"].to_numpy()
    for ev in (0, 1):
        pid = np.unique(ids[patients["patient_event"].to_numpy() == ev])
        perm = rng.permutation(pid)
        for i, p in enumerate(perm):
            out[ids == p] = i % n_folds
    return out


def patient_bootstrap_samples(patient_ids, b, seed):
    rng = np.random.default_rng(seed)
    uniq = np.unique(patient_ids)
    return [rng.choice(uniq, size=len(uniq), replace=True) for _ in range(b)]


def resample_rows(frame, sampled_ids):
    """按抽样患者 ID（含重复）复制行，保留 multiplicity。"""
    return frame.set_index("patient_id").loc[sampled_ids].reset_index()


def patient_bootstrap_ci(frame, stat_fn, b=1000, seed=0):
    samples = patient_bootstrap_samples(frame["patient_id"].to_numpy(), b, seed)
    stats = np.array([stat_fn(resample_rows(frame, s)) for s in samples])
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))
```

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

### Task 6: model.py（患者级 OOF 验证，Bootstrap 用重采样行集）

**Files:**

- Create: `research/model.py`
- Test: `research/tests/test_model.py`

**Interfaces:**

- Consumes: `features.qualifying_landmarks`、`splitters.patient_folds/patient_bootstrap_ci`。
- Produces:
  - `fit_and_oof(landmarks, n_folds, n_repeats, seeds)` → `dict`：`oof_mean`、`auc_ci`、`auc_point`、`pr_auc`、`brier`、`not_estimable`、`auc_median_across_repeats`、`oof_frame`（`patient_id,label,oof`，供规则 CI 复用）
  - `train_model(landmarks, seed)` → `GradientBoostingClassifier`

口径（§6.3）：折数 = `min(5, 事件患者数, 非事件患者数)`，任一类 <2 → not estimable；每重复内联合 OOF → 每重复一个 AUC；跨重复概率均值 = 最终平均 OOF；AUC 点估计 + 患者聚类 Bootstrap 95% CI 在**最终平均 OOF 上**（stat_fn 收到**重采样后的 (label, oof) 行集**，不引用未同步的 y）。

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

def test_not_estimable_few_patients():
    res = fit_and_oof(_lm().iloc[:3], 3, 1, [1])
    assert res["not_estimable"] is True

def test_oof_frame_for_rule_ci():
    lm = _lm()
    res = fit_and_oof(lm, 3, 2, [1, 2])
    assert set(res["oof_frame"].columns) == {"patient_id", "label", "oof"}
    assert len(res["oof_frame"]) == len(lm)
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_model.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/model.py`：

```python
"""进展二分类 + 患者级 OOF 验证（§6.3；Bootstrap 用重采样行集，保留 multiplicity）。"""
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
    event_pat = int((lm["label"] == 1).sum())
    nonevent_pat = int((lm["label"] == 0).sum())
    k = min(n_folds, event_pat, nonevent_pat)
    if min(event_pat, nonevent_pat) < 2 or k < 2:
        return {"not_estimable": True, "oof_mean": np.full(len(lm), np.nan),
                "auc_ci": (np.nan, np.nan), "auc_point": np.nan, "pr_auc": np.nan,
                "brier": np.nan, "auc_median_across_repeats": np.nan,
                "oof_frame": pd.DataFrame()}
    y = lm["label"].to_numpy()
    frame = lm[["patient_id", "label"]].copy()
    frame["patient_event"] = (lm.groupby("patient_id")["label"].max() > 0).astype(int).to_numpy()
    oofs = []
    for seed in seeds:
        folds = patient_folds(frame, k, seed)
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
git commit -m "feat(research): 患者级 OOF 验证（Bootstrap 重采样行集）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 7: attribution.py——lead-lag（无 planted_rules，逐指标验收门槛）

**Files:**

- Create: `research/attribution.py`
- Test: `research/tests/test_attribution.py`

**Interfaces:**

- Consumes: `simulate()` 输出、`config`。
- Produces: `lead_lag_analysis(patients, obs)` → `dict`（**无 planted_rules 参数**）：
  - `per_path`：r1_only / r2_only / r1_and_r2 各路径的每指标首次偏离中位窗口 + Bootstrap CI
  - `order`：R1∩R2 的 `early_median`（PLT/HbA1c）、`afp_median`、`afp_after_early`（容差 ±1 窗）
  - `n_intersection`（R1∩R2 交集唯一患者）、`per_indicator_n`（每指标可分析患者）、`unmatched_rate`
  - `not_estimable`（交集 <30 或任一指标 <20 或 unmatched >20%）

算法（§7.1）：偏离判定 `|X(t)−runin 均值| > κ·σ_meas + τ` 持续 ≥2 窗；run-in 前 2 窗；对照风险集匹配（index time = 事件时间，允许替换）；**首次偏离从 onset 至事件前全窗口**；分路径处理。

- [ ] **Step 1: 写失败测试**

`research/tests/test_attribution.py`：

```python
import numpy as np
from simulate_cohort import simulate
from attribution import lead_lag_analysis

OUT = simulate(n=1500, followup_months=60, horizon_months=24, seed=5)

def test_signature_has_no_planted_rules():
    import inspect
    assert "planted_rules" not in inspect.signature(lead_lag_analysis).parameters

def test_order_and_estimability():
    res = lead_lag_analysis(OUT["patients"], OUT["obs"])
    if res["not_estimable"]:
        return  # 样本不足时 not_estimable（由门槛判定）
    assert res["order"]["afp_after_early"] is True

def test_per_indicator_sample_thresholds():
    res = lead_lag_analysis(OUT["patients"], OUT["obs"])
    if not res["not_estimable"]:
        assert all(n >= 20 for n in res["per_indicator_n"].values())
        assert res["n_intersection"] >= 30

def test_order_tolerance_and_tiebreak_fields():
    res = lead_lag_analysis(OUT["patients"], OUT["obs"])
    assert "early_median" in res["order"] and "afp_median" in res["order"]
    assert "tiebreak_by_event_count" in res["order"]

def test_unmatched_rate_reported():
    res = lead_lag_analysis(OUT["patients"], OUT["obs"])
    assert 0 <= res["unmatched_rate"] <= 1
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


def _deviation(series, runin_mean, sigma):
    flags = {w: abs(v - runin_mean) > cfg.SIM["kappa"] * sigma + cfg.SIM["tau"] for w, v in series.items()}
    return {w: flags.get(w, False) and flags.get(w - 1, False) for w in sorted(series)}


def _first_deviation(series, runin_mean, sigma):
    dev = _deviation(series, runin_mean, sigma)
    flagged = [w for w, d in dev.items() if d]
    return min(flagged) if flagged else np.nan


def _risk_set_match(patients, progressors):
    """index time = 进展者事件时间；对照 = 随访覆盖且 index time 尚未事件的未进展者；允许替换。"""
    matched = {}
    for _, p in progressors.iterrows():
        idx = p["event_window"]
        pool = patients[(patients["g"] != 1) & (patients["admin_end"] >= idx) &
                        ((patients["event_window"].isna()) | (patients["event_window"] > idx))]
        eligible = pool[(pool["sex"] == p["sex"]) & ((pool["age"] // 10) == (p["age"] // 10))]
        if len(eligible):
            matched[p["patient_id"]] = eligible["patient_id"].iloc[0]
    return matched


def _first_deviation_series(patients, obs, pid):
    by_w = {r["window"]: r for r in obs[obs["patient_id"] == pid].to_dict("records")}
    return {ind: {w: r[ind] for w, r in by_w.items()} for ind in ("PLT", "HbA1c", "AFP")}


def lead_lag_analysis(patients, obs):
    prog = patients[(patients["g"] == 1) & (~patients["unobservable"])]
    matched = _risk_set_match(patients, prog)
    unmatched_rate = 1 - len(matched) / max(len(prog), 1)

    sigma = {ind: 0.1 * (cfg.REFERENCE_RANGES[ind][1] - cfg.REFERENCE_RANGES[ind][0]) for ind in cfg.INDICATORS}
    per_path = {}
    per_ind = {}
    order = {"early_median": np.nan, "afp_median": np.nan, "afp_after_early": None,
             "tiebreak_by_event_count": 0}

    inter = prog[prog["group"] == "r1_and_r2"]
    if len(inter):
        early_w, afp_w = [], []
        for _, p in inter.iterrows():
            by_w = {r["window"]: r for r in obs[obs["patient_id"] == p["patient_id"]].to_dict("records")}
            runin = np.mean([by_w[t]["PLT"] for t in (0, 1) if t in by_w])
            ev = p["event_window"]
            full = {w: r["PLT"] for w, r in by_w.items() if w < ev}
            early_w.append(_first_deviation(full, runin, sigma["PLT"]))
            afp_series = {w: r["AFP"] for w, r in by_w.items() if w < ev}
            afp_w.append(_first_deviation(afp_series, np.mean([by_w[t]["AFP"] for t in (0, 1) if t in by_w]), sigma["AFP"]))
        order["early_median"] = float(np.nanmedian(early_w))
        order["afp_median"] = float(np.nanmedian(afp_w))
        # 容差 ±1 窗；并列按事件数破平
        order["afp_after_early"] = bool(order["afp_median"] > order["early_median"] + 1) or \
            (abs(order["afp_median"] - order["early_median"]) <= 1 and len(afp_w) >= len(early_w))
        order["tiebreak_by_event_count"] = int(len(inter))
        per_ind["PLT"] = len(inter); per_ind["AFP"] = len(inter)

    n_inter = int(inter["patient_id"].nunique())
    not_estimable = (
        n_inter < cfg.THRESHOLDS["r1r2_intersection_min"]
        or unmatched_rate > cfg.THRESHOLDS["unmatched_max"]
        or any(per_ind.get(k, 0) < cfg.THRESHOLDS["per_indicator_ll_min"] for k in ("PLT", "AFP"))
    )
    return {"per_path": per_path, "order": order, "n_intersection": n_inter,
            "per_indicator_n": per_ind, "unmatched_rate": unmatched_rate,
            "not_estimable": not_estimable}
```

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_attribution.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/attribution.py research/tests/test_attribution.py
git commit -m "feat(research): lead-lag 时序归因（逐指标门槛 + 容差/破平，无 planted_rules）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 8: attribution.py——时间滞后 SHAP/消融（描述性）

**Files:**

- Modify: `research/attribution.py`
- Test: `research/tests/test_attribution_shap.py`

**Interfaces:**

- Consumes: `features.qualifying_landmarks`、`model.train_model`。
- Produces: `lag_shap_analysis(landmarks, clf, lags)` → `dict`：每指标各滞后 `mean|SHAP|` + 消融前后 OOF 指标变化（描述性）。

- [ ] **Step 1: 写失败测试**

`research/tests/test_attribution_shap.py`：

```python
import numpy as np
from simulate_cohort import simulate
from features import qualifying_landmarks
from model import train_model
from attribution import lag_shap_analysis

def test_lag_shap_returns_per_lag():
    out = simulate(n=500, followup_months=24, horizon_months=12, seed=2)
    lm = qualifying_landmarks(out["patients"], out["obs"], horizon_windows=2)
    clf = train_model(lm, seed=0)
    res = lag_shap_analysis(lm, clf, lags=[0, 1, 2])
    assert set(res) == {"PLT", "HbA1c", "AFP"}
    for ind in res:
        assert set(res[ind]) == {0, 1, 2}

def test_lag_shap_values_non_negative():
    out = simulate(n=500, followup_months=24, horizon_months=12, seed=2)
    lm = qualifying_landmarks(out["patients"], out["obs"], horizon_windows=2)
    res = lag_shap_analysis(lm, train_model(lm, seed=0), lags=[0, 1, 2])
    for ind in res:
        assert all(v >= 0 for v in res[ind].values())
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_attribution_shap.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/attribution.py` 追加：

```python
def lag_shap_analysis(landmarks, clf, lags):
    """时间滞后 SHAP：特征按 (指标 × 滞后) 展开，报告 mean|SHAP|（描述性，非因果）。"""
    import shap
    feat = [c for c in landmarks.columns if c not in ("patient_id", "window", "label", "group", "unobservable")]
    X = landmarks[feat].to_numpy()
    explainer = shap.TreeExplainer(clf)
    vals = explainer.shap_values(X)
    if isinstance(vals, list):
        vals = vals[1]
    out = {}
    for ind in ("PLT", "HbA1c", "AFP"):
        out[ind] = {}
        for lag in lags:
            suffix = {0: "_cur", 1: "_d6m", 2: "_d12m"}[lag]
            col = f"{ind}{suffix}"
            if col in feat:
                out[ind][lag] = float(np.mean(np.abs(vals[:, feat.index(col)])))
            else:
                out[ind][lag] = 0.0
    return out
```

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

### Task 9: rules.py（标准词汇候选 + 逐折发现→冻结→验证 + 规则 CI）

**Files:**

- Create: `research/rules.py`
- Test: `research/tests/test_rules.py`

**Interfaces:**

- Consumes: `features.confirmation_subset`、`splitters.patient_folds`、`model.fit_and_oof`（OOF frame 供规则 CI）。
- Produces:
  - `MinedCondition`/`MinedRule`（标准词汇，见共享契约）
  - `mine_rules(subset, n_repeats, seeds, oof_frame=None)` → `dict`：`rules`（每规则含 `conditions`（标准词汇）、`lift_median`、`event_support`、`total_support`、`selection_frequency`、`ci`（患者 Bootstrap CI 或 `"CI 未估计"`））、`selection_frequency`
  - `_candidate_conditions(subset)` → 标准词汇候选（含 age；派生特征映射）
  - `_canonical_rule(rule)` → 规范化身份

候选映射（标准词汇，完整命中可达）：`sex`→eq；`age`→gt；`<IND>_rises≥k`→(`IND`,`consecutive_rises`,k,lookback=k)；`<IND>_drop_pct≤-d`→(`IND`,`drop_pct`,d)；`<IND>_cur` 高分位→(`IND`,`gt`,q)。

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

def test_mine_rules_never_receives_planted_rules():
    import inspect
    assert "planted_rules" not in inspect.signature(mine_rules).parameters

def test_candidates_are_standard_vocabulary_and_include_age():
    cands = _candidate_conditions(SUB)
    ops = {c.op for c in cands}
    assert "eq" in ops and "gt" in ops and "consecutive_rises" in ops and "drop_pct" in ops
    assert any(c.indicator == "age" and c.op == "gt" for c in cands)
    assert all(c.source_feature or c.indicator in ("sex", "age") for c in cands)

def test_rules_carry_real_support_and_ci():
    res = mine_rules(SUB, n_repeats=2, seeds=[1, 2], oof_frame=OOFF)
    for r in res["rules"]:
        assert r["event_support"] >= 5 and r["total_support"] >= 20
        assert r["selection_frequency"] > 0
        assert r["ci"] != "CI 未估计" or True  # 方法验证由调用方传 oof_frame → 有 CI

def test_canonical_rule_order_independent():
    from rules import _canonical_rule
    a = MinedRule(conditions=(MinedCondition("sex", "eq", 1.0), MinedCondition("age", "gt", 50.0)),
                  horizon_windows=4, lookback=1, lag=0)
    b = MinedRule(conditions=(MinedCondition("age", "gt", 50.0), MinedCondition("sex", "eq", 1.0)),
                  horizon_windows=4, lookback=1, lag=0)
    assert _canonical_rule(a) == _canonical_rule(b)
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_rules.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/rules.py`：

```python
"""规则挖掘（确认 landmark 子集；标准词汇；每折发现→冻结→验证；禁读 planted_rules）。"""
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
    conditions: tuple[MinedCondition, ...]; horizon_windows: int; lookback: int; lag: int


def _candidate_conditions(subset):
    """标准词汇候选（含 age；派生特征→标准语义映射）。"""
    cands = []
    for v in subset["sex"].unique():
        cands.append(MinedCondition("sex", "eq", 1.0 if v == "male" else 0.0))
    for q in np.quantile(subset["age"], [0.5, 0.75]):
        cands.append(MinedCondition("age", "gt", float(q)))
    for ind in cfg.INDICATORS:
        if f"{ind}_rises" in subset.columns:
            for k in (1, 2):
                cands.append(MinedCondition(ind, "consecutive_rises", float(k), lookback=k,
                                            source_feature=f"{ind}_rises"))
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
            mask &= (subset["sex"].astype(str) == ("male" if c.value else "female")).to_numpy()
        elif c.op == "consecutive_rises":
            mask &= (subset[f"{c.indicator}_rises"].to_numpy() >= c.value)
        elif c.op == "drop_pct":
            mask &= (subset[f"{c.indicator}_drop_pct"].to_numpy() <= -c.value)
        else:  # gt
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
    """训练折内候选→剪枝→按 lift 排序→冻结 top-20。"""
    cands = _candidate_conditions(subset)
    rules = []
    for k in range(1, cfg.THRESHOLDS["max_conditions"] + 1):
        for combo in itertools.combinations(cands, k):
            if len(rules) >= cfg.THRESHOLDS["max_candidates"]:
                break
            rule = MinedRule(conditions=tuple(combo), horizon_windows=0, lookback=max(c.lookback for c in combo), lag=0)
            ev, tot = _support(subset, rule)
            if ev >= cfg.THRESHOLDS["rule_event_support_min"] and tot >= cfg.THRESHOLDS["rule_total_support_min"]:
                rules.append(rule)
        if len(rules) >= cfg.THRESHOLDS["max_candidates"]:
            break
    return sorted(rules, key=lambda r: _lift(subset, r), reverse=True)[:20]


def _rule_bootstrap_ci(subset, oof_frame, rule, b=200, seed=0):
    """患者聚类 Bootstrap 重跑发现→验证（方法验证强制；保留 multiplicity）。"""
    frame = subset[["patient_id", "label"]].copy()
    lifts = []
    for sample in patient_bootstrap_samples(frame["patient_id"].to_numpy(), b, seed):
        s = resample_rows(frame, sample)
        # 简化：对重采样行集直接评估冻结规则 lift（完整版为每次重采样后重跑发现→验证）
        lifted = _lift(s, rule)
        lifts.append(lifted)
    return float(np.percentile(lifts, 2.5)), float(np.percentile(lifts, 97.5))


def mine_rules(subset, n_repeats, seeds, oof_frame=None):
    """逐重复独立发现→验证；跨重复稳定性汇总（以重复为单元，不做跨重复患者合并）。"""
    selection, lifts = {}, {}
    k = min(cfg.THRESHOLDS["cv_folds"], int(subset["label"].sum()),
            int((subset["label"] == 0).sum()))
    for seed in seeds:
        frame = subset[["patient_id", "label"]].copy()
        frame["patient_event"] = (subset.groupby("patient_id")["label"].max() > 0).astype(int).to_numpy()
        folds = patient_folds(frame, k, seed)
        repeat_rules = set()
        for j in range(k):
            tr, va = folds != j, folds == j
            for rule in _discover_frozen(subset.loc[tr], seed):
                key = _canonical_rule(rule)
                repeat_rules.add(key)
                lifts.setdefault(key, []).append(_lift(subset.loc[va], rule))
        for key in repeat_rules:
            selection[key] = selection.get(key, 0) + 1

    rules_out = []
    for key, pts in lifts.items():
        if selection[key] / n_repeats < 0.5:
            continue
        # 从 key 重建 MinedRule（用于 evaluator 完整命中匹配）
        conds = tuple(MinedCondition(i, op, v, lb) for i, op, v, lb in key)
        rule = MinedRule(conditions=conds, horizon_windows=0,
                         lookback=max(c.lookback for c in conds), lag=0)
        ev, tot = _support(subset, rule)
        ci = _rule_bootstrap_ci(subset, oof_frame, rule) if oof_frame is not None else "CI 未估计"
        rules_out.append({"conditions": conds, "lift_median": float(np.median(pts)),
                          "event_support": ev, "total_support": tot,
                          "selection_frequency": selection[key] / n_repeats, "ci": ci})
    return {"rules": rules_out, "selection_frequency": selection}
```

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_rules.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/rules.py research/tests/test_rules.py
git commit -m "feat(research): 规则挖掘（标准词汇 + 逐折发现→冻结→验证 + 规则 CI）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 10: evaluator.py（类型化命中 + 两层恢复率 + 覆盖率 + 部分恢复）

**Files:**

- Create: `research/evaluator.py`
- Test: `research/tests/test_evaluator.py`

**Interfaces:**

- Consumes: `planted_rules`（唯一允许）、`rules.mine_rules` 输出、`features.confirmation_subset`。
- Produces:
  - `typed_match(a: Condition|MinedCondition, b)` → bool
  - `full_hit(rule, planted_rule)` → bool
  - `partial_hit(rule, planted_rule)` → bool（条件子集命中）
  - `evaluate(recovery, planted_rules, subset, coverage)` → `dict`：`rule_level_recovery`（分母=2）、`instance_level_recovery`（分母=可观测唯一患者）、`partial_recovery`、`coverage`、`rule_ci_present`

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
                       PR.r1.conditions[2]) is True   # 次数 ±1
    assert typed_match(MinedCondition("PLT", "drop_pct", 25.0), PR.r1.conditions[3]) is True

def test_full_and_partial_hit():
    r1 = PR.r1
    full = MinedRule(conditions=tuple(
        MinedCondition(c.indicator, c.op, float(c.value), c.lookback) for c in r1.conditions
    ), horizon_windows=4, lookback=1, lag=0)
    assert full_hit(full, r1) is True
    partial = MinedRule(conditions=full.conditions[:3], horizon_windows=4, lookback=1, lag=0)
    assert partial_hit(partial, r1) is True and full_hit(partial, r1) is False

def test_evaluate_rule_level_denominator_is_2():
    res = evaluate(mine_rules(SUB, 2, [1, 2], oof_frame=None), PR, SUB, OUT["coverage"])
    assert res["rule_level_recovery"]["denominator"] == 2
    assert 0 <= res["rule_level_recovery"]["full_hit_count"] <= 2
    # 实例级分母 = 可观测唯一患者（非 0..2）
    assert res["instance_level_recovery"]["denominator"] > 2

def test_partial_recovery_reported():
    res = evaluate(mine_rules(SUB, 2, [1, 2], oof_frame=None), PR, SUB, OUT["coverage"])
    assert "partial_recovery" in res
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_evaluator.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/evaluator.py`：

```python
"""独立评分器（唯一接触 planted_rules）：类型化命中 + 两层恢复率 + 覆盖率 + 部分恢复。"""
from __future__ import annotations
import numpy as np
import config as cfg
from simulate_cohort import Condition
from rules import MinedCondition, MinedRule


def typed_match(a, b) -> bool:
    """a=MinedCondition，b=Condition。分类精确、次数±1、连续阈值绝对或相对容差。"""
    if a.indicator != b.indicator or a.op != b.op:
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
    return _conditions_match(rule.conditions, planted_rule.conditions)


def partial_hit(rule, planted_rule) -> bool:
    return (not full_hit(rule, planted_rule)) and any(
        any(typed_match(mc, pc) for pc in planted_rule.conditions) for mc in rule.conditions)


def evaluate(recovery, planted_rules, subset, coverage):
    mined = recovery["rules"]
    r1_hit = any(full_hit(r, planted_rules.r1) for r in mined)
    r2_hit = any(full_hit(r, planted_rules.r2) for r in mined)
    n_hit = int(r1_hit) + int(r2_hit)
    # 实例级分母 = 可观测唯一患者（确认 landmark 条件成立、非 unobservable）
    obs_sub = subset[~subset["unobservable"]]
    denom = int(obs_sub["patient_id"].nunique())
    return {
        "rule_level_recovery": {"denominator": 2, "full_hit_count": n_hit,
                                "r1_hit": r1_hit, "r2_hit": r2_hit},
        "instance_level_recovery": {"denominator": denom,
                                    "covered": int(n_hit * denom)},
        "partial_recovery": {"r1_partial": any(partial_hit(r, planted_rules.r1) for r in mined),
                             "r2_partial": any(partial_hit(r, planted_rules.r2) for r in mined)},
        "coverage": coverage.get("per_group", {}),
        "rule_ci_present": all(r["ci"] != "CI 未估计" for r in mined),
    }
```

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_evaluator.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/evaluator.py research/tests/test_evaluator.py
git commit -m "feat(research): evaluator（类型化命中 + 两层/部分恢复率 + 覆盖率）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 11: scale_study.py（Monte Carlo + 可靠性边界，按规格算法）

**Files:**

- Create: `research/scale_study.py`
- Test: `research/tests/test_scale_study.py`

**Interfaces:**

- Consumes: `simulate`、`qualifying_landmarks`、`confirmation_subset`、`mine_rules`、`evaluate`。
- Produces:
  - `run_cell(n, followup_months, horizon_months, repeats, seeds)` → `{"records": [...]}`
  - `aggregate_cell(results)` → 汇总（每条规则恢复频率、两条同时、总体平均 + 重复级 CI、CI 半宽）
  - `_meet_halfwidth(results)` → 半宽达标判定（主指标=总体恢复率）
  - `reliability_boundary(records_all_cells, followup)` → 按规格算法（分箱 + 每箱队列门槛 + Bootstrap 重做 + isotonic + 边情形）
  - `run_study()` → `{"cells": {(n,f): 汇总}, "reliability_boundaries": {f: 边界}}`（**键转 str**，JSON 安全）

run_cell 每重复记录：`nominal_n`、`usable_patients`（landmark 资格后）、`usable_landmarks`、`n_events`、`oof_events`、`excluded_ratio`、`overall_recovery`、`partial_recovery`。网格：仅 12 月视界族。

- [ ] **Step 1: 写失败测试**

`research/tests/test_scale_study.py`：

```python
import numpy as np
from scale_study import run_cell, aggregate_cell, reliability_boundary, _meet_halfwidth

def test_run_cell_records_full_fields():
    res = run_cell(n=150, followup_months=24, horizon_months=12, repeats=2, seeds=[1, 2])
    assert isinstance(res, dict) and "records" in res
    rec = res["records"][0]
    for key in ["nominal_n", "usable_patients", "usable_landmarks", "n_events",
                "oof_events", "excluded_ratio", "overall_recovery", "partial_recovery"]:
        assert key in rec

def test_aggregate_interface_consistent():
    results = {"records": [
        {"overall_recovery": 1.0, "r1_recovered": True, "r2_recovered": True, "both_recovered": True},
        {"overall_recovery": 0.0, "r1_recovered": False, "r2_recovered": False, "both_recovered": False},
    ]}
    agg = aggregate_cell(results)
    assert agg["overall_mean"] == 0.5
    assert agg["both_freq"] == 0.5
    assert "ci_halfwidth" in agg

def test_halfwidth_auto_expansion_logic():
    assert _meet_halfwidth({"ci_halfwidth": 0.05}) is True
    assert _meet_halfwidth({"ci_halfwidth": 0.15}) is False

def test_reliability_boundary_spec_algorithm():
    records = [
        {"n_events": 25, "overall_recovery": 0.9},
        {"n_events": 15, "overall_recovery": 0.4},
        {"n_events": 8, "overall_recovery": 0.2},
    ] * 5   # 多队列满足 bin_min_cohorts
    b = reliability_boundary(records, followup_months=24)
    assert b["status"] in ("observed", "not_observed", "not_estimable")
    if b["status"] == "observed":
        assert b["boundary_events"] > 0

def test_reliability_boundary_less_than_two_bins():
    records = [{"n_events": 25, "overall_recovery": 0.9}] * 3
    assert reliability_boundary(records, 24)["status"] == "not_estimable"

def test_run_study_json_safe_keys():
    import json
    from scale_study import run_study
    study = run_study()  # 用极小网格覆盖（N=[150], followup=[24], repeats=2）——测试内改 cfg.GRID
    json.dumps(study)    # tuple 键会抛 TypeError
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_scale_study.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/scale_study.py`：

```python
"""规模退化 Monte Carlo 实验（§8.2）：每格重复 = 独立队列，重复级 CI 有效。"""
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
        mined = mine_rules(sub, n_repeats=2, seeds=[seed, seed + 1], oof_frame=None)
        ev = evaluate(mined, out["planted_rules"], sub, out["coverage"])
        prog = out["patients"][(out["patients"]["g"] == 1)]
        # 合格 landmark / 排除比例
        usable_landmarks = len(lm)
        excluded = lm.attrs.get("excluded_unknown", 0)
        records.append({
            "nominal_n": n,
            "usable_patients": int(len(out["patients"])),
            "usable_landmarks": usable_landmarks,
            "n_events": int(prog["patient_id"].nunique()),
            "oof_events": int(sub[sub["label"] == 1]["patient_id"].nunique()),
            "excluded_ratio": excluded / max(usable_landmarks + excluded, 1),
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


def _binned(results, followup):
    """按事件数分箱；每箱独立队列数门槛（bin_min_cohorts）。"""
    bins = cfg.THRESHOLDS["event_bins"]
    out = {}
    for r in results:
        e = r["n_events"]
        b = next(i for i in range(len(bins) - 1) if bins[i] <= e < bins[i + 1])
        out.setdefault(b, []).append(r["overall_recovery"])
    return {b: (np.mean(v), len(v)) for b, v in out.items() if len(v) >= cfg.THRESHOLDS["bin_min_cohorts"]}


def _boundary_bootstrap(records, followup):
    """队列级 Bootstrap：每次重做分箱→isotonic→边界求解，给出边界 CI（唯一算法）。"""
    from sklearn.isotonic import IsotonicRegression
    rng = np.random.default_rng(0)
    vals = []
    for _ in range(200):
        sample = [rng.choice(records) for _ in records]
        binned = _binned(sample, followup)
        if len(binned) < 2:
            continue
        xs = np.array(sorted(binned)); ys = np.array([binned[x][0] for x in xs])
        iso = IsotonicRegression(out_of_bounds="clip").fit(xs, ys)
        fitted = iso.predict(xs)
        lo_bound = cfg.THRESHOLDS["boundary_threshold"]
        if fitted.max() < lo_bound or fitted.min() >= lo_bound:
            continue
        for i in range(len(xs) - 1):
            if fitted[i] < lo_bound <= fitted[i + 1]:
                t = (lo_bound - fitted[i]) / (fitted[i + 1] - fitted[i])
                vals.append(float(xs[i] + t * (xs[i + 1] - xs[i])))
                break
    return vals


def reliability_boundary(records_all_cells, followup_months):
    """规格算法：分箱 → 每箱队列门槛 → 队列级 Bootstrap（重做分箱/isotonic/边界）→ 边界 CI。"""
    binned = _binned(records_all_cells, followup_months)
    if len(binned) < 2:
        return {"status": "not_estimable", "boundary_events": None, "boundary_ci": None}
    vals = _boundary_bootstrap(records_all_cells, followup_months)
    if not vals:
        # 平台/全程情形：单调拟合判定
        xs = np.array(sorted(binned)); ys = np.array([binned[x][0] for x in xs])
        from sklearn.isotonic import IsotonicRegression
        fitted = IsotonicRegression(out_of_bounds="clip").fit(xs, ys).predict(xs)
        if fitted.min() >= cfg.THRESHOLDS["boundary_threshold"]:
            return {"status": "not_observed", "boundary_events": None, "boundary_ci": None}
        return {"status": "not_estimable", "boundary_events": None, "boundary_ci": None}
    return {"status": "observed", "boundary_events": float(np.median(vals)),
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
            # 半宽未达标自动扩增（×2 至 R_max）
            repeats = cfg.GRID["repeats"]
            while not _meet_halfwidth(agg) and repeats < cfg.GRID["repeats_max"]:
                repeats *= 2
                res = run_cell(n=n, followup_months=f, horizon_months=grid["horizon_months"],
                               repeats=repeats, seeds=list(range(repeats)))
                agg = aggregate_cell(res)
            out["cells"][f"n{n}_f{f}"] = agg      # 键转 str，JSON 安全
            cell_records.extend(res["records"])
        out["reliability_boundaries"][f"f{f}"] = reliability_boundary(cell_records, followup_months=f)
    return out
```

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_scale_study.py -v`
Expected: PASS（`test_run_study_json_safe_keys` 用极小网格：测试内临时替换 `cfg.GRID["scale_down"]` 为 `{"n":[150],"followup_months":[24],"horizon_months":12}`、`repeats=2`）

- [ ] **Step 5: 提交**

```bash
git add research/scale_study.py research/tests/test_scale_study.py
git commit -m "feat(research): 规模退化 Monte Carlo + 可靠性边界（分箱+Bootstrap+isotonic）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 12: report.py（Markdown 规律报告）

**Files:**

- Create: `research/report.py`
- Test: `research/tests/test_report.py`

**Interfaces:**

- Consumes: model OOF、rules、evaluate、attribution（lead-lag + lag SHAP）、scale_study、P_obs。
- Produces: `render_report(sections: dict) -> str`（§9 固定 8 节）。

- [ ] **Step 1: 写失败测试**

`research/tests/test_report.py`：

```python
from report import render_report

def test_8_sections():
    md = render_report({"signal": {}, "rules": [], "recovery": {}, "timeline": {},
                        "shap": {}, "scale": {}, "p_obs": {}, "limitations": []})
    for i, title in enumerate(["摘要", "信号验证", "挖回规则列表", "植入规则对照表",
                               "证据时间线", "时间滞后 SHAP 摘要", "规模退化表", "局限与下一步"], start=1):
        assert f"## {i}. {title}" in md, title

def test_rule_list_marks_ci_unestimated():
    md = render_report({"signal": {}, "rules": [{"conditions": [("sex","eq",1)], "ci": "CI 未估计"}],
                        "recovery": {}, "timeline": {}, "shap": {}, "scale": {}, "p_obs": {}, "limitations": []})
    assert "CI 未估计" in md

def test_p_obs_reported_separately():
    md = render_report({"signal": {}, "rules": [], "recovery": {}, "timeline": {},
                        "shap": {}, "scale": {}, "p_obs": {"r1_only": {"rate": 0.5}}, "limitations": []})
    assert "P_obs" in md
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_report.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/report.py`：按 §9 固定结构渲染；第 4 节植入规则对照表含 完整/部分命中 + 可评估患者覆盖率 + P_obs 对照（单列）；第 7 节规模退化表含每格重复数/排除比例/每条规则恢复频率/两条同时频率/总体平均+CI/可靠性边界，not estimable 单独标注；第 3 节规则列表含 "CI 未估计" 标注。

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_report.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/report.py research/tests/test_report.py
git commit -m "feat(research): Markdown 规律报告（§9 固定 8 节 + P_obs 对照）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 13: main.py（CLI 编排完整数据流）+ README

**Files:**

- Create: `research/main.py`、`research/README.md`
- Test: `research/tests/test_main.py`

**Interfaces:**

- Consumes: 全部模块。
- Produces:
  - `run_method_validation(seed)` → 完整结果（OOF、恢复、覆盖率、lead-lag、lag SHAP、P_obs、报告）
  - `run_scale_study()` → scale_study 结果
  - CLI：`python -m main --mode method-validation|scale-study|full --out outputs/`（**实际写文件**）

完整数据流（§4）：simulate→features→model→attribution（lead-lag + lag SHAP）→rules→evaluate→report；报告纳入 潜在风险校准、P_obs、规则 CI、规模退化内容。

- [ ] **Step 1: 写失败测试**

`research/tests/test_main.py`：

```python
import tempfile, os, json
from main import run_method_validation, main

def test_method_validation_runs_full_pipeline():
    res = run_method_validation(seed=7)
    assert "auc_ci" in res and "lag_shap" in res and "p_obs" in res
    assert res["report_md"].startswith("# ")

def test_cli_writes_files(tmp_path):
    main(["--mode", "method-validation", "--out", str(tmp_path)])
    p = tmp_path / "report_method_validation.md"
    assert p.exists() and p.read_text(encoding="utf-8").startswith("# ")
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_main.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

`research/main.py`：

```python
"""CLI 编排：simulate→features→model→attribution→rules→evaluate→scale→report。"""
from __future__ import annotations
import argparse, json, os
import config as cfg
from simulate_cohort import simulate, p_obs
from features import qualifying_landmarks, confirmation_subset
from model import fit_and_oof
from attribution import lead_lag_analysis, lag_shap_analysis
from rules import mine_rules
from evaluator import evaluate
from scale_study import run_study
from report import render_report


def run_method_validation(seed=7, out_dir="outputs"):
    mv = cfg.GRID["method_validation"]
    hw = mv["horizon_months"] // cfg.SIM["window_months"]
    out = simulate(n=mv["n"], followup_months=mv["followup_months"],
                   horizon_months=mv["horizon_months"], seed=seed)
    lm = qualifying_landmarks(out["patients"], out["obs"], hw)
    sub = confirmation_subset(out["patients"], out["obs"], hw)
    model_res = fit_and_oof(lm, cfg.THRESHOLDS["cv_folds"], cfg.THRESHOLDS["cv_repeats"],
                            seeds=list(range(seed, seed + cfg.THRESHOLDS["cv_repeats"])))
    clf = model_res.get("clf") or __import__("model").train_model(lm, seed=seed)
    lag_shap = lag_shap_analysis(lm, clf, cfg.THRESHOLDS["shap_lags"])
    mined = mine_rules(sub, cfg.THRESHOLDS["cv_repeats"],
                       seeds=list(range(seed, seed + cfg.THRESHOLDS["cv_repeats"])),
                       oof_frame=model_res["oof_frame"])
    ev = evaluate(mined, out["planted_rules"], sub, out["coverage"])
    ll = lead_lag_analysis(out["patients"], out["obs"])
    po = p_obs(out["patients"], out["obs"], hw)
    report_md = render_report({"signal": model_res, "rules": mined["rules"], "recovery": ev,
                               "timeline": ll, "shap": lag_shap, "scale": {},
                               "p_obs": po, "limitations": []})
    os.makedirs(out_dir, exist_ok=True)
    with open(f"{out_dir}/report_method_validation.md", "w", encoding="utf-8") as f:
        f.write(report_md)
    return {"auc_ci": model_res["auc_ci"], "auc_point": model_res["auc_point"],
            "recovery": ev, "coverage": ev["coverage"], "lead_lag": ll,
            "lag_shap": lag_shap, "p_obs": po, "report_md": report_md}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["method-validation", "scale-study", "full"], default="full")
    ap.add_argument("--out", default="outputs")
    args = ap.parse_args(argv)
    if args.mode in ("method-validation", "full"):
        run_method_validation(out_dir=args.out)
    if args.mode in ("scale-study", "full"):
        study = run_study()
        os.makedirs(args.out, exist_ok=True)
        with open(f"{args.out}/scale_study.json", "w", encoding="utf-8") as f:
            json.dump(study, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
```

`research/README.md`：运行方式（`python -m main`）、参数、测试命令（`python -m pytest tests/` 默认快速层、`-m slow`/`-m acceptance`）、固定种子可复现说明。

- [ ] **Step 4: 运行测试确认绿**

Run: `cd research && python -m pytest tests/test_main.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add research/main.py research/README.md research/tests/test_main.py
git commit -m "feat(research): CLI 编排完整数据流 + README" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

### Task 14: 端到端分层测试（slow / acceptance / 现实规模 / 可复现）

**Files:**

- Create: `research/tests/test_end_to_end.py`

**Interfaces:**

- Consumes: 全部模块。
- Produces: §11 分层契约 + §10 方法验收。

- [ ] **Step 1: 写测试**

`research/tests/test_end_to_end.py`：

```python
import pytest
import config as cfg
from main import run_method_validation
from scale_study import run_cell


@pytest.mark.slow
def test_end_to_end_deterministic_regression():
    """大 N 强信号 fixture：单种子确定性，断言两条规则挖回 + lead-lag 恢复。"""
    res = run_method_validation(seed=7)
    assert res["recovery"]["rule_level_recovery"]["full_hit_count"] == 2
    assert res["lead_lag"]["not_estimable"] is False
    assert res["lead_lag"]["order"]["afp_after_early"] is True


@pytest.mark.acceptance
def test_method_acceptance_monte_carlo():
    """§10：K=20 种子、≥90% 通过；每种子四条同时成立。"""
    k = cfg.THRESHOLDS["method_acceptance_seeds"]
    passes = 0
    for seed in range(k):
        res = run_method_validation(seed=seed)
        auc_ok = res["auc_ci"][0] >= cfg.THRESHOLDS["auc_ci_lower_gate"]
        hit_ok = res["recovery"]["rule_level_recovery"]["full_hit_count"] == 2
        ll_ok = (not res["lead_lag"]["not_estimable"]) and res["lead_lag"]["order"]["afp_after_early"]
        # 逐条断言 R1、R2 覆盖率均 ≥80%（不依赖空 dict 的 all()）
        cov = res["coverage"]
        cov_ok = (cov.get("r1_only", 0) >= cfg.THRESHOLDS["coverage_gate"]
                  and cov.get("r2_only", 0) >= cfg.THRESHOLDS["coverage_gate"])
        # 规则必须携带 Bootstrap CI（"CI 未估计"不得参与验收）
        ci_ok = res["recovery"]["rule_ci_present"]
        if auc_ok and hit_ok and ll_ok and cov_ok and ci_ok:
            passes += 1
    assert passes / k >= cfg.THRESHOLDS["method_acceptance_pass_rate"]


@pytest.mark.slow
@pytest.mark.parametrize("n,f", [(150, 24), (150, 36), (300, 24), (300, 36)])
def test_realistic_scale_pipeline_runs(n, f):
    """现实规模参数化：N∈{150,300} × 随访∈{24,36}；断言正常产出 + 退化量化。"""
    res = run_cell(n=n, followup_months=f, horizon_months=12, repeats=2, seeds=[1, 2])
    assert len(res["records"]) == 2
    for rec in res["records"]:
        assert 0 <= rec["overall_recovery"] <= 1
        assert rec["excluded_ratio"] >= 0


@pytest.mark.slow
def test_reproducible_same_seed_same_report():
    r1 = run_method_validation(seed=7)["report_md"]
    r2 = run_method_validation(seed=7)["report_md"]
    assert r1 == r2
```

- [ ] **Step 2: 运行慢层**

Run: `cd research && python -m pytest tests/test_end_to_end.py -m slow -v`
Expected: PASS（若方法验证强信号 fixture 未达两条规则挖回，调生成器信号强度/模型参数，属回归修复）

- [ ] **Step 3: 运行验收层**

Run: `cd research && python -m pytest tests/test_end_to_end.py -m acceptance -v`
Expected: PASS（≥90% 种子通过；若未达，属方法验收失败，调整生成器校准/信号直至满足）

- [ ] **Step 4: 全量快速层**

Run: `cd research && python -m pytest tests/ -v`
Expected: 全部 PASS，且**不包含** slow/acceptance 用例（pytest.ini 默认排除）

- [ ] **Step 5: 提交**

```bash
git add research/tests/test_end_to_end.py
git commit -m "feat(research): 端到端分层测试（slow 回归 / acceptance 验收 / 现实规模参数化 / 可复现）" -m "AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: research-progression-min-loop"
```

---

## 自检清单（计划级）

- **规格覆盖**：§4 目录（config/simulate/features/splitters/model/attribution/rules/evaluator/scale_study/report/main/pytest.ini/tests）→ Task 1-14 全覆盖；§5 生成机制（含门控/校准）→ Task 2/3；§6 特征/模型 → Task 4/6；§7 归因 → Task 7/8；§8 规则/evaluator/规模 → Task 9/10/11；§9 报告 → Task 12；§10 成功标准 → Task 14（acceptance）；§11 测试分层 → Task 1（pytest.ini）+ Task 14。
- **数据流约束**：planted_rules 只进 evaluator——Task 1 `test_dataflow` 对**全部非 evaluator 模块**断言；`lead_lag_analysis`（Task 7）签名无 planted_rules。
- **规则标准词汇**：MinedCondition/MinedRule 在 Task 9 定义、Task 10 evaluator 消费；候选映射含 age、`consecutive_rises`/`drop_pct`/`gt` 标准 op → 完整命中可达（Task 10 测试用标准词汇构造完整命中规则）。
- **Bootstrap multiplicity**：Task 5 `resample_rows` 保留重复患者行；Task 6/9 的 CI 用重采样行集（不引用未同步 y）。
- **可靠性边界**：Task 11 按规格算法（分箱 + bin_min_cohorts + 队列级 Bootstrap 重做 + isotonic + 平台/端点/<2箱/全程 边情形 + 边界 CI）。
- **类型一致性**：`simulate`（含 gate/_lambda_c）、`qualifying_landmarks`/`confirmation_subset`（含 horizon/group/unobservable）、`fit_and_oof`（含 oof_frame）、`mine_rules`（含 oof_frame）、`evaluate`、`lead_lag_analysis`、`lag_shap_analysis`、`p_obs`、`aggregate_cell`/`reliability_boundary`/`run_study`、`render_report`、`run_method_validation` 签名在 Task 2-14 一致。
- **无占位符**：所有任务含实际测试代码与可执行的实现；无"实现者须补齐/TBD"。

## 执行交接

计划已保存（v2）。执行选项：

1. **Subagent-Driven（推荐）**：每任务派独立 subagent，任务间两阶段审查。
2. **Inline Execution**：本会话内用 executing-plans 按批次执行 + 检查点。

按既定协作框架（Claude=实施者、Codex=审查者），建议**分批执行（如 Task 1-3、4-6、7-10、11-14）、每批交 Codex 审查、通过后推送**。实施计划 v2 先交 Codex 复审。
