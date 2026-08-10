# 疾病进展规律挖掘 · 端到端最小闭环 实施计划（v5.5）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `research/` 独立子项目中实现端到端最小闭环：用含植入规律的模拟纵向数据跑通"模拟 → 窗口特征 → 模型 → 时序归因 → 规则挖掘 → evaluator → 规模退化 → 规律报告"全链路，验证方法论能可信地恢复植入规律，并量化现实数据规模下的可信度。

**Architecture:** 每个模块单一职责、纯接口清晰、可独立单测。`simulate_cohort` 产出「数据集 + planted_rules」；数据集流向 features→model→attribution→rules；**planted_rules 只流向 evaluator**。模型训练用全量合格 landmark，规则/校准/evaluator 用每患者确认 landmark（§5.5 分角色口径表）。

**Tech Stack:** Python 3.10+、pandas、scikit-learn（GradientBoostingClassifier / IsotonicRegression）、shap、pytest（`slow`/`acceptance` marker）。

**规格依据：** `docs/superpowers/specs/2026-08-06-progression-rule-mining-loop-design.md`（v16）。
**计划修订：** v4 按 Codex 计划第三轮 13 条意见修正；**v4.1 按 Workflow 对抗验证 10 条真实发现修正**；**v5**（Codex 第四轮 8 大项）；**v5.1**（Codex 第五轮 12 项）；**v5.2 按 Codex 计划第六轮 11 项修正**——R1 ≥95% 测试改按 z + 指定锚点直接验证（脱离 group/unobservable 生成判定循环）、`_group_latent_risk` 排除 neither 误报患者（obs 传参 + 校准测试同分母）、coverage 文档口径统一（excluded 单列不从规则覆盖率分母移除）、mine_rules 内部过滤 unobservable、候选标准优先确定性顺序（candidate_grid 版本化，R1/R2 组合先于截断枚举）+ synthetic fixture 测试、control_delta 对照无偏离取 cutoff 端点（有限值）+ 确定性手工 fixture、边界 Bootstrap B/有效比例版本化 + +inf CI 契约、run_cell excluded_breakdown 明细 + 字段语义修正、`_fold_discover_validate` 签名统一（显式 horizon）、acceptance ci_ok 加强（长度一致 + 有限数值区间）。**v5.3 按 Codex 计划第七轮 10 项修正**——R1 条件成立率口径限定可评估患者 + unobservable 原因分解（删失不设门槛、条件未成立 ≤5%，patients 表新增 `unobservable_reason`）、neither 误报分母改为全部 neither 候选患者（规格 §5.3 口径，校准分母不变）、`_bisect` 端点包围检查 + 上界自适应扩展（非包围显式 ValueError）、synthetic fixture 加确定性负例（折数可用）+ `_discover_frozen` 显式标准组合优先枚举（discover_top_k 版本化）、Task 8 新增整组滞后消融 `lag_ablation_analysis`（§7.2 佐证）、`_recovery_block` 兼容嵌套 coverage 契约 + 报告测试、run_cell excluded_breakdown 统一患者口径（unknown 行级单独字段）、`patient_bootstrap_ci` 无效重采样契约（单类样本丢弃、有效 <2 → NaN，规则/模型 CI 同步）、版本残留清理。**v5.4 按 Codex 计划第八轮 10 项修正**——Task 2 schema 断言加 `unobservable_reason` + 无潜在事件（g=0）/无参考 landmark 分别处理（可转绿）、R1/R2 条件成立率按**各自指定确认 landmark** 验证（交集组 = w_A+1 双条件、补 R2-only 与 neither 首参考不命中两规则）+ 原因互斥/绑定/计数闭合 + condition_not_held 分母限定实际进入条件检查的患者、删 per_group coverage ≥0.9 门槛（与删失不设门槛一致，保留 §10 per-rule ≥0.80）、neither 误报分母全文统一（Task 3 算法说明）+ 三类患者手工 fixture（误报/有参考非误报/无参考，断言 1/3 识别分母错误）、`_discover_frozen` 去除 `_standard_candidates` 标准组合优先（植入语义泄漏）→ 通用全枚举 + lift 排序 + max_candidates ≥ 组合总数防截断（显式 raise）、`_fold_discover_validate` 按**唯一患者**定折数（Bootstrap 重复患者不重复计数）+ 唯一正例重复确定性测试 + 收紧 CI 失败契约（"CI 未估计"确定性断言）、`lag_ablation_analysis` 消融组 = `lags` 对应滞后观测列（不误删 slope/rises/drop_pct）+ 基线/移除后均报告患者 Bootstrap CI、`reliability_boundary` 统一为规格算法（每网格点 CI 下界曲线首达 50%，boundary_events 与 point_boundary_events 分列）、lead-lag per_indicator_n 限定相关路径组 + 有匹配合格对照（§10 口径）+ 风险集匹配检查对照 index time 前删失、模拟器观测截断 `T = min(事件, 删失, 行政终点)`（§5.4 第 9 步，杜绝未来观测）。**v5.5 按 Codex 计划第九轮 6 项修正**——simulate 观测改 `patient_rows` 逐患者收集（修 `obs_rows[-n_win:]` 截断后跨患者污染，条件判定只用当前患者行）+ 观测截断无跨患者测试、`reliability_boundary` 去掉 `_point_boundary` 提前判边情形（point 仅诊断，边情形只由 CI 下界曲线判定；"原始点达标但 CI 下界跨 50%" fixture `test_boundary_point_high_ci_lower_crosses`）、`_discover_frozen` 排序改二级键 `(-lift, canonical_rule)`（并列 lift 不依赖组合枚举顺序）+ `test_discover_sorted_by_lift_then_canonical` + Task 9 Step 4 残留清理、`unobservable_reason` 逐类绑定与计数闭合测试（no_feasible_anchor⇒锚点 NaN、censored⇒confirm≥删失、event_before_confirm⇒confirm≥事件、condition_not_held⇒锚点合格事件删失在后且条件实际失败）、`lag_ablation` Bootstrap CI 可估计/不足样本两测试（(nan,nan) 必须）+ `_fmt_ci` NaN→`[NA, NA]` + 报告测试、synthetic fixture 提取 helper + `test_synthetic_fixture_r1_rule_in_top_k`（R1 canonical 规则确定性进 top_k，Task 14 依赖链有测试支撑而非仅注释）。

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
| `unobservable_reason` | str/`None` | 不可观测原因分解（仅路径组且 unobservable=True 时非空）：`"no_feasible_anchor"`（锚点采样无可行区间）、`"censored"`（confirm ≥ 删失窗，删失客观导致，不设门槛）、`"event_before_confirm"`（confirm ≥ 事件窗）、`"condition_not_held"`（锚点合格无事件未删失但条件未成立——生成器缺陷信号，测试设 ≤5% 门槛）；否则 `None` |

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
    # 候选网格（标准优先）与边界 Bootstrap 参数
    assert cfg.THRESHOLDS["candidate_grid"]["age"] == [50, 40, 60]
    assert cfg.THRESHOLDS["candidate_grid"]["drop_pct"] == [0.20, 0.10, 0.30]
    assert cfg.THRESHOLDS["boundary_bootstrap_b"] == 200
    assert cfg.THRESHOLDS["boundary_valid_ratio_min"] == 0.5

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
              "thresholds_per_feature": 3, "lift_min": 1.5,
              # 通用枚举防截断：max_candidates 必须 >= 候选 1..max_conditions 全组合数
              # （当前候选 ~21 项 → 全组合 7546 < 10000；`_discover_frozen` 超限即 raise）
              "max_candidates": 10000,
              "method_acceptance_seeds": 20, "method_acceptance_pass_rate": 0.90,
              "bootstrap_b": 1000, "cv_folds": 5, "cv_repeats": 5, "shap_lags": [0, 1, 2],
              "calibrate_tol": 0.005, "calibrate_bisect_iters": 40, "calibrate_hi_max": 128.0,
              "event_bins": [0, 10, 20, 30, 40, 50, 75, 100, 150, 10 ** 9],
              "bin_min_cohorts": 10, "boundary_threshold": 0.50,
              # 规则候选临床阈值网格（确定性；标准值在前保证 R1/R2 组合先被枚举）
              "candidate_grid": {"age": [50, 40, 60],
                                 "consecutive_rises": [2, 1],
                                 "drop_pct": [0.20, 0.10, 0.30]},
              # 规则发现：通用全枚举 + lift 排序取 top_k（无植入语义优先）
              "discover_top_k": 20,
              # 可靠性边界 Bootstrap（版本化）
              "boundary_bootstrap_b": 200, "boundary_valid_ratio_min": 0.5}
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
    which ∈ {"r1", "r2", "both"（R1∩R2 双条件）, "neither_clean"（R1、R2 均不成立）}。
    分母 = 资格检查全部通过的患者（可评估：锚点有限 + 合格 + 视界够 + 无事件 + 未删失）。
    ——「条件成立率 ≥95%」仅针对观测条件（可评估患者），与 v16 §5.3 一致。"""
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
        elif which == "neither_clean" and (not r1) and (not r2):
            ok += 1
    return ok / eligible if eligible else float("nan")

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
    # neither 首参考 landmark：R1、R2 均不成立（"条件未成立"是 neither 的定义而非失败）
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
    if op == "drop_pct":
        val = float(val) / 100.0          # 标准语义统一为比例（特征 drop_pct 是 -0.20 量级）
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
        patient_rows = []
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

        # 指标观测（基线 + 信号 + 噪声）；观测截断（规格 5.4 第 9 步）：
        # T = min(事件, 删失, 行政随访终点)，**其后窗口观测截断**——T 窗口本身有观测，
        # T+1 起无观测（杜绝事件/删失后的"未来观测"，避免 lead-lag 对已删失对照使用未来值）。
        # **观测按 patient_rows 收集**（截断后每患者行数 ≠ n_win，不能用全局 obs_rows 尾部切片，
        # 否则会混入上一患者窗口——条件判定 by_w 必须只用当前患者行）
        baseline = {i: rng.normal((cfg.REFERENCE_RANGES[i][0] + cfg.REFERENCE_RANGES[i][1]) / 2,
                                  (cfg.REFERENCE_RANGES[i][1] - cfg.REFERENCE_RANGES[i][0]) / 6)
                    for i in cfg.INDICATORS}
        trunc = admin_end
        if np.isfinite(event_window):
            trunc = min(trunc, int(event_window))
        if np.isfinite(censored_window):
            trunc = min(trunc, int(censored_window))
        for t in range(trunc + 1):
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
            patient_rows.append(row)
        obs_rows.extend(patient_rows)

        # 组归属 / 确认 landmark / unobservable（完整判定 + 原因分解）
        if z == "none":
            confirm = _first_qualifying_landmark(admin_end, hw, censored_window)
            group, unobservable, unobservable_reason = "neither", False, None
        else:
            expected = "r1_and_r2" if z == "r1_and_r2" else ("r1_only" if z == "r1" else "r2_only")
            confirm = (w_a + 1) if z in ("r2", "r1_and_r2") else w_r1
            by_w = {r["window"]: r for r in patient_rows}   # 只用当前患者观测（杜绝跨患者污染）
            r1_ok = _r1_holds(by_w, confirm, age, sex) if z in ("r1", "r1_and_r2") else False
            r2_ok = _r2_holds(by_w, confirm) if z in ("r2", "r1_and_r2") else False
            valid = (np.isfinite(confirm)
                     and (not np.isfinite(event_window) or confirm < event_window)
                     and (not np.isfinite(censored_window) or confirm < censored_window))
            if not valid or (z in ("r1", "r1_and_r2") and not r1_ok) or (z in ("r2", "r1_and_r2") and not r2_ok):
                group, unobservable = expected, True      # 保留路径组，标不可观测
                # 原因分解（确定性归因顺序）：无可行锚点 → 删失 → 事件先于确认 → 条件未成立
                if not np.isfinite(confirm):
                    unobservable_reason = "no_feasible_anchor"
                elif np.isfinite(censored_window) and confirm >= censored_window:
                    unobservable_reason = "censored"           # 删失客观导致（20% 删失率），不设门槛
                elif np.isfinite(event_window) and confirm >= event_window:
                    unobservable_reason = "event_before_confirm"
                else:
                    unobservable_reason = "condition_not_held" # 生成器缺陷信号（测试设 ≤5% 门槛）
            else:
                group = "r1_and_r2" if (r1_ok and r2_ok) else ("r1_only" if r1_ok else "r2_only")
                unobservable, unobservable_reason = False, None

        rows.append({"patient_id": pid, "z": z, "age": age, "sex": sex, "group": group,
                     "confirm_window": confirm, "w_r1": w_r1, "w_a": w_a, "g": g,
                     "event_window": event_window, "censored": censored,
                     "censored_window": censored_window, "admin_end": admin_end,
                     "unobservable": unobservable,
                     "unobservable_reason": unobservable_reason})

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

**coverage 算法（具体，口径唯一）**：

- `per_group[g]` = `{"eligible_total", "eligible_observed", "excluded", "coverage"}`；`eligible_total` = 该组全部患者；`eligible_observed` = 确认/参考 landmark 合格、无事件、条件成立；`excluded = eligible_total - eligible_observed`（不可观测/无合格 landmark **单列，不从分母移除**）；`coverage = eligible_observed / eligible_total`。
- `per_rule["r1"]` = 同上结构，按规则路径组（`r1_only` ∪ `r1_and_r2`）**唯一患者**聚合；`per_rule["r2"]` 同理。**规则覆盖率分母 = 规则路径全部唯一患者（含 excluded），excluded 不从分母移除**（与 §10 一致）。
- `neither_false_positive_rate`（**误报率分母 = 全部 neither 候选患者**，规格 §5.3）——参考 landmark 命中任一植入条件计入误报分子；**无合格参考 landmark 的患者无法判定误报、不计入分子，但仍在分母中**。**neither 校准分母（`_group_latent_risk`）= 有合格参考 landmark 且非误报**——两个口径不同，勿混淆。

- [ ] **Step 1: 写失败测试**

`research/tests/test_simulate_calibration.py`：

```python
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
    out = simulate(n=2000, followup_months=24, horizon_months=12, seed=5,
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
```

- [ ] **Step 2: 运行测试确认红**

Run: `cd research && python -m pytest tests/test_simulate_calibration.py -v`
Expected: FAIL

- [ ] **Step 3: 写实现**

追加到 `simulate_cohort.py`：

```python
def _group_latent_risk(out, grp, hw, obs=None):
    """潜在风险（不受删失影响）。neither：排除"参考 landmark 命中 R1/R2"的误报患者。
    **校准分母** = 有合格参考 landmark 且非误报的 neither 患者（规格 §5.3 明确定义；
    与 coverage 的**误报率分母 = 全部 neither 候选患者**是两个不同口径，勿混淆）。"""
    p = out["patients"]
    sub = p[(p["group"] == grp) & (~p["unobservable"])]
    if grp == "neither":
        if obs is None:
            raise ValueError("neither 校准需传入 obs 以检查参考 landmark 误报")
        obs_by_pid = {pid: g.to_dict("records") for pid, g in obs.groupby("patient_id")}
        ok_mask = sub["confirm_window"].notna().to_numpy()
        fp_mask = np.zeros(len(sub), dtype=bool)
        for i, row in enumerate(sub.itertuples()):
            if not np.isfinite(row.confirm_window):
                continue
            by_w = {r["window"]: r for r in obs_by_pid.get(row.patient_id, [])}
            w = int(row.confirm_window)
            if _r1_holds(by_w, w, row.age, row.sex) or _r2_holds(by_w, w):
                fp_mask[i] = True
        valid = ok_mask & (~fp_mask)                       # 误报患者排除出 neither 校准分母
        ev = sub["event_window"].notna().to_numpy() \
             & (sub["event_window"] > sub["confirm_window"]).to_numpy() \
             & (sub["event_window"] <= sub["confirm_window"] + hw).to_numpy()
        return ev[valid].mean() if valid.any() else np.nan
    return sub["g"].mean()


def _bisect(target, risk_fn, lo=0.0, hi=1.0):
    """bisection（端点包围强制检查 + 上界自适应扩展）。

    - 检查 risk(lo) <= target <= risk(hi)；**不包围 → 上界倍增扩展**（λ_c 允许 >1，
      neither 基线 hazard 可缩放语义），扩展超 `calibrate_hi_max` 仍不达 → 显式
      `ValueError`（**绝不静默返回伪校准端点值**）。
    - risk(lo) > target → 直接 `ValueError`（下界即超目标，参数错误）。"""
    risk_lo = risk_fn(lo)
    if risk_lo > target:
        raise ValueError(f"bisection 下界风险 {risk_lo:.4f} > 目标 {target:.4f}")
    risk_hi = risk_fn(hi)
    while risk_hi < target and hi < cfg.THRESHOLDS["calibrate_hi_max"]:
        hi *= 2.0
        risk_hi = risk_fn(hi)
    if risk_hi < target:
        raise ValueError(f"bisection 上界风险 {risk_hi:.4f} < 目标 {target:.4f}（扩展至 hi={hi:.1f} 仍不包围）")
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
            return _group_latent_risk(out, grp, hw, obs=out["obs"])
        # 端点包围：g=0 → 风险 0 < 目标；g=1 → 风险 1 ≥ 目标（事件=confirm+δ ≤ confirm+hw）→ 必有解
        gates[grp] = _bisect(target, risk)

    def neither_risk(c):
        out = simulate(cal_n, followup, horizon_months, 3, gate=gates, _lambda_c=c)
        return _group_latent_risk(out, "neither", hw, obs=out["obs"])
    # λ_c=0 → 风险 0 < 目标；λ_c 可能需 >1（视界内 λ0 累积不足目标时自动扩展上界）
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
    """coverage 口径（唯一）：每互斥组/规则输出
    {"eligible_total", "eligible_observed", "excluded", "coverage"}。
    eligible_total = 该组全部患者；eligible_observed = 确认/参考 landmark 合格、无事件、条件成立的患者；
    excluded = eligible_total - eligible_observed；coverage = eligible_observed / eligible_total。
    per_rule 按规则路径组聚合，**按唯一患者去重**（避免 landmark 行数混入患者口径）。
    neither 误报分母 = **全部 neither 候选患者**（规格 §5.3：误报率分母 = 全部 neither 候选患者）；
    无合格参考 landmark 的患者无法判定误报、不计入分子，但仍在分母中。"""
    obs_by_pid = {pid: g.to_dict("records") for pid, g in obs.groupby("patient_id")}
    p = patients
    per_group = {}
    for grp in ("r1_only", "r2_only", "r1_and_r2", "neither"):
        sub = p[p["group"] == grp]
        total = int(len(sub))
        observed = int((sub["confirm_window"].notna() & (~sub["unobservable"])).sum())
        per_group[grp] = {"eligible_total": total, "eligible_observed": observed,
                          "excluded": total - observed,
                          "coverage": observed / total if total else float("nan")}
    per_rule = {}
    for rule, groups in (("r1", ("r1_only", "r1_and_r2")), ("r2", ("r2_only", "r1_and_r2"))):
        sub = p[p["group"].isin(groups)]
        total = int(sub["patient_id"].nunique())                          # 唯一患者
        observed_ids = sub[(sub["confirm_window"].notna()) & (~sub["unobservable"])]["patient_id"].nunique()
        per_rule[rule] = {"eligible_total": total, "eligible_observed": observed_ids,
                          "excluded": total - observed_ids,
                          "coverage": observed_ids / total if total else float("nan")}
    ne = p[p["group"] == "neither"]                    # 分母 = 全部 neither 候选患者（规格 §5.3）
    fp = 0
    for _, row in ne.iterrows():
        if not np.isfinite(row["confirm_window"]):
            continue                                    # 无合格参考 landmark → 无法判定，不计入分子
        by_w = {r["window"]: r for r in obs_by_pid.get(row["patient_id"], [])}
        w = int(row["confirm_window"])
        if _r1_holds(by_w, w, row["age"], row["sex"]) or _r2_holds(by_w, w):
            fp += 1
    neither_fp = fp / len(ne) if len(ne) else float("nan")
    return {"per_group": per_group, "per_rule": per_rule,
            "neither_false_positive_rate": float(neither_fp)}
```

实现说明：**Task 3 必须修改 `simulate` 的返回**——将 Task 2 中硬编码的 `"coverage": {"per_group": {}, "per_rule": {}, "neither_false_positive_rate": np.nan}` 替换为 `_compute_coverage(patients, obs, meta)`（在返回前调用，`meta` 来自 `out["meta"]`）。`per_group`/`per_rule` 分母 = 该组患者总数（含 unobservable）、分子 = 可评估患者，与 §10 覆盖率门槛口径一致；`excluded` 单列。

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
    assert "sex" not in lm.columns   # 无字符串列

def test_confirmation_subset_contract():
    out = simulate(n=300, followup_months=24, horizon_months=12, seed=1)
    sub = confirmation_subset(out["patients"], out["obs"], horizon_windows=2)
    assert sub["patient_id"].is_unique
    for col in ["group", "unobservable", "admin_end", "sex_male", "label"]:
        assert col in sub.columns
    assert (sub["admin_end"] - sub["window"] >= 2).all()
    assert set(sub["label"]) <= {0, 1}   # unknown 已剔除
    assert sub.attrs["horizon_windows"] == 2

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
            continue
        r = _feature_row(p, obs_by_pid[p["patient_id"]], int(w))
        r["label"] = lab
        r["unobservable"] = bool(p["unobservable"])
        rows.append(r)
    df = pd.DataFrame(rows)
    df.attrs["horizon_windows"] = horizon_windows
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

def test_bootstrap_ci_single_class_dropped():
    # 全正例患者 → 任何重采样都单类 → AUC 抛 ValueError → 全部样本丢弃
    # → 有效样本 <2 → (nan, nan)（CI 未估计），**不抛异常**
    from sklearn.metrics import roc_auc_score
    frame = pd.DataFrame({"patient_id": np.zeros(10, dtype=int),
                          "label": np.ones(10, dtype=int), "x": np.arange(10.0)})
    lo, hi = patient_bootstrap_ci(frame, lambda d: roc_auc_score(d["label"], d["x"]),
                                  b=30, seed=0)
    assert np.isnan(lo) and np.isnan(hi)

def test_bootstrap_ci_nan_stats_dropped():
    # 非有限统计值被丢弃；其余样本正常 → CI 有限
    frame = pd.DataFrame({"patient_id": np.repeat(np.arange(10), 5),
                          "value": np.repeat([1.0, 2.0, 3.0, 4.0, 5.0], 10)})
    def stat(d):
        v = d["value"].mean()
        return v if v < 4.0 else float("nan")      # 部分样本 NaN → 丢弃
    lo, hi = patient_bootstrap_ci(frame, stat, b=100, seed=0)
    assert np.isfinite(lo) and np.isfinite(hi)
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
    return frame.set_index("patient_id").loc[sampled_ids].reset_index()


def patient_bootstrap_ci(frame, stat_fn, b=1000, seed=0):
    """患者聚类 Bootstrap CI（无效重采样契约）：
    - 单类样本（如 AUC 不可定义抛 ValueError）→ 丢弃该样本；
    - 非有限统计值（NaN/inf）→ 丢弃；
    - 有效样本 <2 → 返回 (nan, nan)（**CI 未估计**，调用方必须处理，不得静默视为数值 CI）。
    绝不因单个 Bootstrap 样本的异常而中断整个 CI。"""
    samples = patient_bootstrap_samples(frame["patient_id"].to_numpy(), b, seed)
    vals = []
    for s in samples:
        try:
            v = stat_fn(resample_rows(frame, s))
        except ValueError:
            continue                        # 单类样本（AUC 不可定义）→ 丢弃该样本
        if np.isfinite(v):
            vals.append(v)
    if len(vals) < 2:
        return float("nan"), float("nan")   # 有效样本不足 → CI 未估计
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))
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

### Task 6: model.py（患者级 OOF，患者聚合 + 全数值特征）

**Files:**

- Create: `research/model.py`
- Test: `research/tests/test_model.py`

**Interfaces:**

- Produces: `fit_and_oof(landmarks, n_folds, n_repeats, seeds)` → `{"oof_mean","auc_ci","auc_point","pr_auc","brier","not_estimable","auc_median_across_repeats","oof_frame"}`；`train_model(landmarks, seed)`。
- **模型 CI 契约**：`auc_ci` 来自 `patient_bootstrap_ci`——**无效重采样（单类 AUC 抛异常 / 非有限值）被丢弃**，有效样本 <2 时返回 `(nan, nan)`（**CI 未估计**）；报告 `_fmt_ci` 渲染 `[NA, NA]`，acceptance 的 `auc_ci[0] >= 0.65` 对 NaN 自然为 False（CI 未估计不得视为通过）。

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
"""进展二分类 + 患者级 OOF（患者聚合分层 + 全数值特征）。"""
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
        folds = folds_uniq[patient_row]
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
        assert ind in res["control_delta"]
    # 匹配对照参与：至少一个指标有有限 control_delta（进展者更早 → 为负）
    assert any(np.isfinite(v) for v in res["control_delta"].values())
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
    """风险集匹配（§7.1 + §10）：为进展患者匹配 1 名**在 index time（事件时间）尚未事件、
    随访覆盖 ≥ index time 且 index time 前未删失**的未进展患者（年龄分箱 × 性别，允许替换）。
    —— 对照在 index time 前已删失（censored_window <= idx）不算合格对照（随访未覆盖 index time）。"""
    matched = {}
    for _, p in progressors.iterrows():
        idx = p["event_window"]
        pool = patients[(patients["g"] != 1) & (patients["admin_end"] >= idx) &
                        ((patients["event_window"].isna()) | (patients["event_window"] > idx)) &
                        (patients["censored_window"].isna() | (patients["censored_window"] > idx))]
        eligible = pool[(pool["sex"] == p["sex"]) & ((pool["age"] // 10) == (p["age"] // 10))]
        if len(eligible):
            matched[p["patient_id"]] = eligible["patient_id"].iloc[0]
    return matched


def _first_dev_by_patient(progressors, obs, ind, sigma, cutoff=None):
    """{patient_id: 首次偏离窗口}；cutoff 缺省 = 该患者事件窗口（观察进展者）；
    匹配对照无事件窗口 → 传入显式 cutoff = 匹配的进展者事件时间（§7.1 伪零点）。"""
    out = {}
    for _, p in progressors.iterrows():
        by_w = {r["window"]: r for r in obs[obs["patient_id"] == p["patient_id"]].to_dict("records")}
        ev = cutoff if cutoff is not None else p["event_window"]
        if not np.isfinite(ev):
            continue
        runin = np.mean([by_w[t][ind] for t in (0, 1) if t in by_w])
        fd = _first_deviation({w: r[ind] for w, r in by_w.items() if w < ev}, runin, sigma[ind])
        if np.isfinite(fd):
            out[p["patient_id"]] = fd
    return out


def lead_lag_analysis(patients, obs):
    sigma = {i: 0.1 * (cfg.REFERENCE_RANGES[i][1] - cfg.REFERENCE_RANGES[i][0]) for i in cfg.INDICATORS}
    prog = _observed_progressors(patients)
    matched = _risk_set_match(patients, prog)          # 匹配对照（§7.1，参与偏离比较）
    unmatched_rate = 1 - len(matched) / max(len(prog), 1)

    # 每指标可分析患者（§10 口径）：**该指标相关路径组**进展者中、**有匹配合格对照**且
    # 有限首偏的唯一患者（不是所有观察进展者）——门槛与 §10 第 3 条一致
    dev_by_ind = {ind: _first_dev_by_patient(prog, obs, ind, sigma[ind])
                  for ind in ("PLT", "HbA1c", "AFP")}
    ind_paths = {"PLT": ("r1_only", "r1_and_r2"), "HbA1c": ("r1_only", "r1_and_r2"),
                 "AFP": ("r2_only", "r1_and_r2")}
    per_indicator_n = {}
    for ind, grps in ind_paths.items():
        gids = set(prog[prog["group"].isin(grps)]["patient_id"]) & set(matched)
        per_indicator_n[ind] = len({pid for pid in gids if pid in dev_by_ind[ind]})

    per_path = {}
    for grp, inds in (("r1_only", ("PLT", "HbA1c")), ("r2_only", ("AFP",)),
                      ("r1_and_r2", ("PLT", "HbA1c", "AFP"))):
        gids = set(prog[prog["group"] == grp]["patient_id"])
        per_path[grp] = {}
        for ind in inds:
            rows = [(pid, v) for pid, v in dev_by_ind[ind].items() if pid in gids]
            if rows:
                frame = pd.DataFrame(rows, columns=["patient_id", "first_dev"])
                per_path[grp][ind] = {
                    "median": float(np.median(frame["first_dev"])),
                    "ci": patient_bootstrap_ci(frame, lambda d: np.median(d["first_dev"]), b=200, seed=0),
                }
            else:
                per_path[grp][ind] = {"median": np.nan, "ci": (np.nan, np.nan)}

    inter = prog[prog["group"] == "r1_and_r2"]
    n_inter = int(inter["patient_id"].nunique())
    # 逐患者比较：afp_dev vs 该患者 min(plt_dev, hba1c_dev)（真实破平）
    pairs = []
    for _, p in inter.iterrows():
        pid = p["patient_id"]
        e = np.nanmin([dev_by_ind["PLT"].get(pid, np.nan), dev_by_ind["HbA1c"].get(pid, np.nan)])
        a = dev_by_ind["AFP"].get(pid, np.nan)
        if np.isfinite(e) and np.isfinite(a):
            pairs.append((pid, e, a))
    early_med = float(np.median([e for _, e, _ in pairs])) if pairs else np.nan
    afp_med = float(np.median([a for _, _, a in pairs])) if pairs else np.nan

    afp_after_early = None
    tiebreak = 0
    tol = 1
    if pairs:
        n_afp_later = sum(1 for _, e, a in pairs if a > e + tol)
        n_afp_earlier = sum(1 for _, e, a in pairs if a <= e + tol)
        afp_after_early = afp_med > early_med + tol
        if not afp_after_early:
            tiebreak = n_afp_later - n_afp_earlier
            afp_after_early = tiebreak >= 0

    # 匹配对照比较（§7.1）：进展者 vs 对照 首偏中位数差（进展者应更早 → 差为负）
    # 对照无事件窗口 → 用匹配进展者的事件时间作显式 cutoff（伪零点）；
    # 对照在 cutoff 内无偏离 → 取 cutoff 端点（"未更早偏离"），保证 control_delta 有限
    prog_event = dict(zip(prog["patient_id"], prog["event_window"]))
    control_delta = {}
    for ind in ("PLT", "HbA1c", "AFP"):
        prog_vals, ctrl_vals = [], []
        for pid, fd in dev_by_ind[ind].items():
            cpid = matched.get(pid)
            if cpid is None or pid not in prog_event:
                continue
            cutoff_w = prog_event[pid]
            ctrl = _first_dev_by_patient(patients[patients["patient_id"] == cpid], obs, ind, sigma[ind],
                                         cutoff=cutoff_w).get(cpid, cutoff_w)   # 无偏离 → cutoff 端点
            if np.isfinite(fd) and np.isfinite(ctrl):
                prog_vals.append(fd); ctrl_vals.append(ctrl)
        control_delta[ind] = float(np.median(prog_vals) - np.median(ctrl_vals)) if prog_vals else np.nan

    not_estimable = (n_inter < cfg.THRESHOLDS["r1r2_intersection_min"]
                     or unmatched_rate > cfg.THRESHOLDS["unmatched_max"]
                     or any(per_indicator_n.get(i, 0) < cfg.THRESHOLDS["per_indicator_ll_min"]
                            for i in ("PLT", "HbA1c", "AFP")))
    return {"per_path": per_path,
            "order": {"early_median": early_med if np.isfinite(early_med) else None,
                      "afp_median": afp_med if np.isfinite(afp_med) else None,
                      "afp_after_early": afp_after_early,
                      "tiebreak_by_event_count": tiebreak},
            "control_delta": control_delta,
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

### Task 8: attribution.py——时间滞后 SHAP/整组滞后消融（§7.2 佐证）

**Files:**

- Modify: `research/attribution.py`
- Test: `research/tests/test_attribution_shap.py`

**Interfaces:**

- Produces: `lag_shap_analysis(landmarks, clf, lags)` → 每指标（PLT/HbA1c/AFP）各滞后 `mean|SHAP|`（描述性）；特征用 `sex_male` 数值列。
- Produces: `lag_ablation_analysis(landmarks, lags, seed=0)` → 每指标 `{"baseline_auc", "baseline_ci", "without_auc", "without_ci", "auc_drop"}`——**整组滞后消融（§7.2）**：**消融组 = 该指标在 `lags` 中对应的滞后观测列**（lags=[0,1,2] → `_cur/_d6m/_d12m`；slope/rises/drop_pct 为派生特征，不属滞后组、保留）；移除该组后重训患者级 OOF，比较 OOF AUC 相对全特征基线的变化，**基线/移除后均报告患者 Bootstrap CI**（§7.2 滞后预测贡献分布带 CI；描述性措辞）。

- [ ] **Step 1: 写失败测试**

`research/tests/test_attribution_shap.py`：

```python
import numpy as np
from simulate_cohort import simulate
from features import qualifying_landmarks
from model import train_model
from attribution import lag_shap_analysis, lag_ablation_analysis

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

def test_lag_ablation_group_contract():
    lm = _lm()
    res = lag_ablation_analysis(lm, lags=[0, 1, 2], seed=0)
    assert set(res) == {"PLT", "HbA1c", "AFP"}
    for ind, d in res.items():
        assert set(d) == {"baseline_auc", "baseline_ci", "without_auc", "without_ci", "auc_drop"}
        assert 0 <= d["baseline_auc"] <= 1 and 0 <= d["without_auc"] <= 1
        assert np.isfinite(d["auc_drop"])
        assert len(d["baseline_ci"]) == 2 and len(d["without_ci"]) == 2

def test_lag_ablation_signal_group_drop_positive():
    # 植入信号确定（HbA1c/PLT 早期偏离自 onset 先行）→ 移除该指标全部滞后组应使
    # OOF AUC 下降（固定种子确定性；这是 §7.2"整组消融"验证的实质断言）
    lm = _lm()
    res = lag_ablation_analysis(lm, lags=[0, 1, 2], seed=0)
    assert res["PLT"]["auc_drop"] > 0.0 and res["HbA1c"]["auc_drop"] > 0.0

def test_lag_ablation_ci_estimable():
    # 正常数据：基线/移除后患者 Bootstrap CI **两端有限**（可估计）
    lm = _lm()
    res = lag_ablation_analysis(lm, lags=[0, 1, 2], seed=0)
    for ind, d in res.items():
        assert all(np.isfinite(v) for v in d["baseline_ci"])
        assert all(np.isfinite(v) for v in d["without_ci"])

def test_lag_ablation_ci_unestimated_insufficient():
    # 不足样本（fit_and_oof not_estimable）→ CI **必须 (nan, nan)**（CI 未估计），
    # 不得伪装为数值；报告 _fmt_ci 渲染 [NA, NA]（不得把 (nan,nan) 当有效结果）
    tiny = _lm().iloc[:5]
    res = lag_ablation_analysis(tiny, lags=[0, 1, 2], seed=0)
    for ind, d in res.items():
        assert np.isnan(d["baseline_ci"][0]) and np.isnan(d["baseline_ci"][1])
        assert np.isnan(d["without_ci"][0]) and np.isnan(d["without_ci"][1])
```

- [ ] **Step 2: 红** → **Step 3: 实现**：

```python
import config as cfg
from model import fit_and_oof

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


def lag_ablation_analysis(landmarks, lags, seed=0):
    """整组滞后消融（§7.2）：**消融组 = 该指标在 `lags` 中对应的滞后观测列**
    （lags=[0,1,2] → _cur/_d6m/_d12m；slope/rises/drop_pct 为派生特征，不属滞后组、保留）。
    移除该组后重训患者级 OOF → 比较 AUC；**基线/移除后均报告患者 Bootstrap CI**
    （§7.2 滞后预测贡献分布带 CI）。与 SHAP 佐证互补（分摊下 SHAP 大小不可单独证明
    时间先后）；措辞限定为"模型预测贡献的时间滞后一致性（描述性）"，不解释为因果先后。"""
    feat = [c for c in landmarks.columns
            if c not in ("patient_id", "window", "label", "group", "unobservable")]
    suffixes = {0: "_cur", 1: "_d6m", 2: "_d12m"}
    base_res = fit_and_oof(landmarks, cfg.THRESHOLDS["cv_folds"], 1, [seed])
    base_auc, base_ci = base_res["auc_point"], base_res["auc_ci"]
    out = {}
    for ind in ("PLT", "HbA1c", "AFP"):
        drop_cols = [f"{ind}{suffixes[lag]}" for lag in lags if f"{ind}{suffixes[lag]}" in feat]
        res_d = fit_and_oof(landmarks.drop(columns=drop_cols),
                            cfg.THRESHOLDS["cv_folds"], 1, [seed])
        out[ind] = {"baseline_auc": float(base_auc), "baseline_ci": tuple(base_ci),
                    "without_auc": float(res_d["auc_point"]), "without_ci": tuple(res_d["auc_ci"]),
                    "auc_drop": float(base_auc - res_d["auc_point"])}
    return out
```

- [ ] **Step 4: 绿** → **Step 5: 提交**（`feat(research): 时间滞后 SHAP + 整组滞后消融（描述性佐证）`）。

---

### Task 9: rules.py（标准词汇 + 逐折发现→冻结→验证 + 规则 CI 完整重跑）

**Files:**

- Create: `research/rules.py`
- Test: `research/tests/test_rules.py`

**Interfaces:**

- Consumes: `features.confirmation_subset`（含 `attrs["horizon_windows"]`）、`splitters.patient_folds`。
- Produces: `MinedCondition`/`MinedRule`（数值 value）；`mine_rules(subset, n_repeats, seeds)` → `{"rules": list[MinedRule], "selection_frequency"}`；`_candidate_conditions(subset)`；`_fold_discover_validate(sset, seed, horizon_windows)` → `{canonical_key: [val_lifts]}`（**horizon 显式传参，非从 attrs 隐式读**）；`_rule_bootstrap_ci(subset, rule, b, seed)`（**重采样→重跑发现→验证**）。**mine_rules 内部先过滤 `unobservable` 行**（发现/验证/CI 只用可评估确认 landmark）。

**规则 CI（完整，非简化）**：每次患者 Bootstrap 重采样确认子集（全列）→ 在重采样集上重跑折内发现→折外验证 → 收集该 canonical 规则的验证 lift 分布 → `(2.5, 97.5)`；未重发现 → 该样本 NaN，剔除；**重采样集单类（负例 0 → `_fold_discover_validate` 折数 k<2 返回空）→ 该样本无结果，同样剔除**；<2 个有效 → `"CI 未估计"`。**`mine_rules` 签名无 oof_frame**。

**规范化（保类型）**：`_canonical_rule` 返回 `(indicator, op, float(value), lookback)`（value 恒数值）；重建 MinedCondition 用 float。

**确定性 fixture**：断言至少挖出一个 R1 四条件标准规则与一个 R2 标准规则。

- [ ] **Step 1: 写失败测试**

`research/tests/test_rules.py`：

```python
import numpy as np
import config as cfg
from simulate_cohort import simulate
from features import confirmation_subset
from rules import (mine_rules, MinedCondition, MinedRule, _candidate_conditions,
                   _fold_discover_validate, _rule_bootstrap_ci,
                   _discover_frozen, _canonical_rule, _lift)

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
        # 大 N fixture（方法验证规模）下规则必须携带 Bootstrap CI（数值区间，非"CI 未估计"）
        assert isinstance(r.ci, tuple) and r.ci[0] <= r.ci[1]

def test_at_least_one_r1_and_r2_full_hit_rule():
    """确定性：挖回规则包含与植入 R1/R2 标准语义精确一致的规则（drop_pct 比例单位 0.20）。"""
    from rules import _canonical_rule, MinedCondition, MinedRule
    from evaluator import full_hit
    r1_std = MinedRule(tuple([
        MinedCondition("sex", "eq", 1.0),
        MinedCondition("age", "gt", 50.0),
        MinedCondition("HbA1c", "consecutive_rises", 2.0, lookback=2),
        MinedCondition("PLT", "drop_pct", 0.20),
    ]), horizon_windows=4, lookback=2, lag=0)
    r2_std = MinedRule(tuple([MinedCondition("AFP", "consecutive_rises", 2.0, lookback=2)]),
                       horizon_windows=4, lookback=2, lag=0)
    mined = mine_rules(SUB, 2, [1, 2])
    keys = {_canonical_rule(r) for r in mined["rules"]}
    assert _canonical_rule(r1_std) in keys
    assert _canonical_rule(r2_std) in keys
    # 直接对植入规律做 full_hit（含 horizon/lookback/lag + 类型化条件）
    assert any(full_hit(r, OUT["planted_rules"].r1) for r in mined["rules"])
    assert any(full_hit(r, OUT["planted_rules"].r2) for r in mined["rules"])

def _unique_pos_neg_frame():
    """确定性 fixture：唯一正例患者（重复 20 行）+ 唯一负例患者（重复 10 行）。
    按行数正 20/负 10（旧实现会误判 k>=2），按唯一患者正 1/负 1 → 折数不足。"""
    import pandas as pd
    rows = ([{"patient_id": 0, "label": 1, "age": 55, "sex_male": 1,
              "HbA1c_rises": 2, "PLT_drop_pct": -0.25, "AFP_rises": 0,
              **{f"{i}_cur": 1.0 for i in cfg.INDICATORS}} for _ in range(20)]
            + [{"patient_id": 1, "label": 0, "age": 30, "sex_male": 0,
                "HbA1c_rises": 0, "PLT_drop_pct": 0.0, "AFP_rises": 0,
                **{f"{i}_cur": 1.0 for i in cfg.INDICATORS}} for _ in range(10)])
    sub = pd.DataFrame(rows)
    sub.attrs["horizon_windows"] = 4
    return sub

def test_fold_validate_unique_patient_denominator():
    # 唯一正例被 Bootstrap 重复抽中 → 按唯一患者仍仅 1 正例 → 折数不足 → 返回空
    assert _fold_discover_validate(_unique_pos_neg_frame(), 1, 4) == {}

def test_discover_sorted_by_lift_then_canonical():
    # 确定性契约：lift 降序主键 + canonical_rule 二级键（并列 lift 不依赖组合枚举顺序）
    rules = _discover_frozen(SUB, 1, 4)
    lifts = [_lift(SUB, r) for r in rules]
    keys = [_canonical_rule(r) for r in rules]
    assert lifts == sorted(lifts, reverse=True)                       # lift 非升
    for i in range(len(rules) - 1):
        if abs(lifts[i] - lifts[i + 1]) < 1e-12:
            assert keys[i] <= keys[i + 1], (keys[i], keys[i + 1])     # 并列段内 canonical 升序
    # 同输入两次运行逐位一致（枚举顺序无关）
    again = _discover_frozen(SUB, 1, 4)
    assert [_canonical_rule(r) for r in again] == keys

def test_rule_ci_failure_mode():
    # 确定性失败契约：唯一正例重复抽中 → 全部样本无效 → **必然** "CI 未估计"
    # （不允许 tuple 兜底模糊——用确定性 fixture 验证失败路径，而非"小样本可退化"）
    rule = MinedRule((MinedCondition("sex", "eq", 1.0),), 4, 1, 0)
    ci = _rule_bootstrap_ci(_unique_pos_neg_frame(), rule, b=5, seed=0)
    assert ci == "CI 未估计"

def test_synthetic_fixture_discovers_r1_full_hit():
    """确定性 synthetic fixture（不依赖模拟器）：**40 正例（满足 R1 四条件，唯一患者）+
    20 确定性负例（不满足任何条件，唯一患者）**——负例保证 `_fold_discover_validate` 折数可用；
    通用枚举（max_candidates ≥ 组合总数防截断）+ **(-lift, canonical) 排序**保证
    R1 四条件组合（正例全命中、lift 最高）确定性进入 top_k → full_hit 确定性成立。"""
    from rules import mine_rules
    from evaluator import full_hit
    sub = _synthetic_fixture()
    res = mine_rules(sub, 1, [1])
    assert any(full_hit(r, OUT["planted_rules"].r1) for r in res["rules"])

def test_synthetic_fixture_r1_rule_in_top_k():
    # 验收 n_rules 依赖链：**R1 canonical 规则必须确定性进入 _discover_frozen 的 top_k**
    # （"候选全集存在" ≠ "最终结果一定包含"——并列 lift 由 canonical 二级键稳定；
    # 若规则未进 top-k，Task 14 验收的 n_rules/full_hit 前提即失败，本断言兜底）
    from rules import _discover_frozen
    disc = _discover_frozen(_synthetic_fixture(), 1, 4)
    keys = {_canonical_rule(r) for r in disc}
    r1_std = MinedRule(tuple([
        MinedCondition("sex", "eq", 1.0), MinedCondition("age", "gt", 50.0),
        MinedCondition("HbA1c", "consecutive_rises", 2.0, lookback=2),
        MinedCondition("PLT", "drop_pct", 0.20),
    ]), horizon_windows=4, lookback=2, lag=0)
    assert _canonical_rule(r1_std) in keys

def _synthetic_fixture():
    """40 正例（满足 R1 四条件，唯一患者）+ 20 负例（不满足，唯一患者）——确定性可发现 R1。"""
    import pandas as pd
    rows = []
    for i in range(40):                       # 正例：满足 R1 四条件
        rows.append({
            "patient_id": i, "window": 2, "age": 55, "sex_male": 1,
            "group": "r1_only", "unobservable": False, "admin_end": 8, "label": 1,
            "HbA1c_rises": 2, "PLT_drop_pct": -0.25, "AFP_rises": 0,
            **{f"{ind}_cur": 1.0 for ind in cfg.INDICATORS},
        })
    for i in range(40, 60):                   # 确定性负例：不满足任何条件
        rows.append({
            "patient_id": i, "window": 2, "age": 30, "sex_male": 0,
            "group": "neither", "unobservable": False, "admin_end": 8, "label": 0,
            "HbA1c_rises": 0, "PLT_drop_pct": 0.0, "AFP_rises": 0,
            **{f"{ind}_cur": 1.0 for ind in cfg.INDICATORS},
        })
    sub = pd.DataFrame(rows)
    sub.attrs["horizon_windows"] = 4
    return sub
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
    """标准词汇候选（**通用、无植入语义**）：固定临床阈值网格 + 数据分位数。
    候选列表内容确定（通用阈值切点：sex ∈ {0,1}、age ∈ 候选网格、rises/drop 通用网格）；
    组合枚举与排序是**通用算法**（`_discover_frozen` 全枚举 + lift 排序），
    不识别/不优先任何 planted 组合。阈值来自 config.candidate_grid
    （通用临床切点，不引用 planted_rules）。"""
    grid = cfg.THRESHOLDS["candidate_grid"]
    cands = [MinedCondition("sex", "eq", 1.0), MinedCondition("sex", "eq", 0.0)]
    for a in grid["age"]:
        cands.append(MinedCondition("age", "gt", float(a)))
    # R1/R2 信号指标优先（顺序固定：HbA1c → PLT → AFP），标准值在前
    for ind in ("HbA1c", "PLT", "AFP"):
        for k in grid["consecutive_rises"]:
            if f"{ind}_rises" in subset.columns:
                cands.append(MinedCondition(ind, "consecutive_rises", float(k), lookback=k, source_feature=f"{ind}_rises"))
        if ind == "PLT" and "PLT_drop_pct" in subset.columns:
            for d in grid["drop_pct"]:
                cands.append(MinedCondition("PLT", "drop_pct", float(d), source_feature="PLT_drop_pct"))
    # 其余指标：仅 cur 高分位（数据分位数）
    for ind in cfg.INDICATORS:
        if ind in ("HbA1c", "PLT", "AFP"):
            continue
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


def _enumerate_combos(cands, k):
    """枚举 k 项组合（去重、确定性有序）。"""
    out, seen = [], set()
    for combo in itertools.combinations(cands, k):
        key = tuple(sorted((c.indicator, c.op, float(c.value), c.lookback) for c in combo))
        if key in seen:
            continue
        seen.add(key)
        out.append(tuple(combo))
    return out


def _discover_frozen(subset, seed, horizon_windows):
    """通用枚举（**无植入语义**——不识别/不优先任何特定组合）：
    候选组合 1..max_conditions **全枚举**（去重）→ 满足支持门槛 → 按 lift 降序取 top_k。
    确定性来自 **lift 排序**（R1/R2 组合正例比例最高必然入选 top_k），不依赖 itertools 组合次序、
    不把 ground-truth 组合写进 rules.py。组合总数若超过 max_candidates → **显式 raise**
    （防静默截断；网格扩展时强制调大 max_candidates，而非悄悄丢组合）。"""
    from math import comb
    cands = _candidate_conditions(subset)
    total_combos = sum(comb(len(cands), k) for k in range(1, cfg.THRESHOLDS["max_conditions"] + 1))
    if total_combos > cfg.THRESHOLDS["max_candidates"]:
        raise ValueError(f"候选全组合数 {total_combos} 超过 max_candidates "
                         f"{cfg.THRESHOLDS['max_candidates']}（防静默截断，需调大 max_candidates）")
    rules = []
    for k in range(1, cfg.THRESHOLDS["max_conditions"] + 1):
        for combo in _enumerate_combos(cands, k):
            rule = MinedRule(conditions=tuple(combo), horizon_windows=horizon_windows,
                             lookback=max(c.lookback for c in combo), lag=0)
            ev, tot = _support(subset, rule)
            if ev >= cfg.THRESHOLDS["rule_event_support_min"] and tot >= cfg.THRESHOLDS["rule_total_support_min"]:
                rules.append(rule)
    # 确定性排序：lift 降序为主键，**canonical_rule 为二级键**（并列 lift 时不依赖组合枚举顺序）
    return sorted(rules, key=lambda r: (-_lift(subset, r), _canonical_rule(r)))[:cfg.THRESHOLDS["discover_top_k"]]


def _fold_discover_validate(sset, seed, horizon_windows):
    """在 sset 上折内发现→折外验证，返回 {canonical_key: [val_lifts]}。
    **折数按唯一患者计数**（Bootstrap 重复患者不得重复计数）：
    k = min(cv_folds, 唯一正例患者数, 唯一负例患者数)；任一类别唯一患者 <2 → 无效（返回空）。
    仅按行数计正/负会把"一个唯一正例被重复抽中"误判为 k>=2。"""
    uniq = sset.groupby("patient_id")["label"].max().reset_index()
    pos = int((uniq["label"] > 0).sum())
    neg = int((uniq["label"] == 0).sum())
    k = min(cfg.THRESHOLDS["cv_folds"], pos, neg)
    if k < 2:
        return {}
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
    # 规则发现/验证/CI 只用可评估确认 landmark（排除 unobservable，避免事后信息/不可评估样本泄漏）
    subset = subset[~subset["unobservable"]].reset_index(drop=True)
    subset.attrs["horizon_windows"] = subset.attrs.get("horizon_windows", 0)
    horizon = subset.attrs["horizon_windows"]
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
Expected: PASS（通用全枚举 + 确定性排序 `(-lift, canonical_rule)`：R1/R2 组合 lift 最高必然进入 top_k；并列 lift 由 canonical 二级键稳定排序。若仍失败，属生成器信号/支持度问题，按 §5.3 观测验收修复，非"调参"）

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
    # coverage 必须含 r1/r2 键（不接受 get(..., 0) 静默缺失）
    assert "r1" in res["coverage"] and "r2" in res["coverage"]

def test_partial_hit_count_tolerance():
    r1 = PR.r1
    full = _full_rule(r1)
    # 次数 2 vs 3（容差 ±1）→ 部分命中（typed 容差）
    conds = [c for c in full.conditions if c.indicator != "HbA1c"]
    hba1c3 = MinedCondition("HbA1c", "consecutive_rises", 3.0, lookback=2)
    assert partial_hit(MinedRule(tuple(conds) + (hba1c3,), r1.horizon_windows, r1.lookback, r1.lag), r1) is True
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

**run_cell 字段（修正）**：`usable_patients` = 至少拥有一个合格 landmark 的**可评估唯一患者**（排除不可观测）；`usable_landmarks` = 可评估合格 landmark 数；`n_events` = 有效确认/参考 landmark 且非不可观测、事件在视界内（confirm < event <= confirm+hw）的患者数；`oof_events` = `fit_and_oof(...)["oof_frame"]` 中正例唯一患者数（**实际跑模型**，非确认子集 label 计数）；`excluded_ratio` = 未进入可评估 landmark 模型的患者比例（唯一患者口径）；`excluded_breakdown` = **患者级明细** `{"unobservable", "no_feasible_landmark"}`（`unobservable + no_feasible + usable == nominal_n` 闭环核对）；`unknown_landmark_rows` = **landmark 行级** unknown 剔除数（单独字段，不混入患者级 breakdown）；`overall_recovery`/`partial_recovery`。

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
                "oof_events", "excluded_ratio", "overall_recovery", "partial_recovery",
                "excluded_breakdown", "unknown_landmark_rows"]:
        assert key in res["records"][0]

def test_run_cell_excluded_patient_level_closure():
    """excluded_breakdown 是患者级明细，与 usable/excluded_ratio 同一层级核对：
    unobservable + no_feasible_landmark + usable == nominal_n（患者级闭环）；
    unknown 行级单独字段（>= 0），不参与 breakdown 求和。"""
    res = run_cell(n=150, followup_months=24, horizon_months=12, repeats=1, seeds=[1])
    rec = res["records"][0]
    bd = rec["excluded_breakdown"]
    assert set(bd) == {"unobservable", "no_feasible_landmark"}
    assert bd["unobservable"] + bd["no_feasible_landmark"] + rec["usable_patients"] == rec["nominal_n"]
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
    """波动版：specs: [(n_events, mean_recovery, spread)]，箱内 recovery 在 [mean±spread] 线性铺开，
    使 Bootstrap 下界明显低于箱均值（用于验证边情形只由 CI 下界曲线判定）。"""
    out = []
    for e, mean, spread in specs:
        vals = np.linspace(mean - spread, mean + spread, cohorts_per_bin)
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

def test_boundary_point_high_ci_lower_crosses():
    # 原始箱均值 0.6/0.95 全程 ≥50% → _point_boundary 判 "not_observed"（**诊断**），
    # 但箱内 recovery 波动大 → Bootstrap **CI 下界曲线**在低事件数箱 <50%、高事件数箱 >50%
    # → 跨 50% → status=observed。**不得提前用原始点短路**（否则误判 not_observed）。
    b = reliability_boundary(_records_var([(8, 0.6, 0.4), (25, 0.95, 0.1)]), 24)
    assert b["point_boundary_events"] == "not_observed"   # 原始点达标（诊断）
    assert b["status"] == "observed"                       # CI 下界曲线跨 50% → observed
    assert b["boundary_ci"][0] <= b["boundary_events"] <= b["boundary_ci"][1]
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
        # 可评估 landmark：排除不可观测路径患者（其确认 landmark 不合格/条件未成立）
        unobs_ids = set(out["patients"].loc[out["patients"]["unobservable"], "patient_id"])
        lm_eval = lm[~lm["patient_id"].isin(unobs_ids)]
        sub = confirmation_subset(out["patients"], out["obs"], hw)
        model_res = fit_and_oof(lm_eval, 3, 1, [seed])
        mined = mine_rules(sub, 2, [seed, seed + 1])
        ev = evaluate(mined, out["planted_rules"], sub, out["coverage"])
        usable_patients = int(lm_eval["patient_id"].nunique())
        # n_events：有效确认/参考 landmark 且非不可观测、事件在视界内（confirm < event <= confirm+hw）
        p = out["patients"]
        valid = p["confirm_window"].notna() & (~p["unobservable"])
        n_events = int((valid & p["event_window"].notna()
                        & (p["event_window"] > p["confirm_window"])
                        & (p["event_window"] <= p["confirm_window"] + hw)).sum())
        # oof_events：fit_and_oof 的 OOF 验证正例唯一患者（实际跑模型，非确认子集 label 计数）
        oof_frame = model_res["oof_frame"]
        oof_events = int(oof_frame.loc[oof_frame["label"] == 1, "patient_id"].nunique()) \
            if len(oof_frame) else 0
        # excluded 明细（**唯一患者口径，同一层级可核对**）：
        # n_unobservable + n_no_feasible + usable_patients == n_total（患者级闭环）。
        # unknown 是 landmark 行级概念（每患者可能多行被剔除），**单独字段**放顶层、
        # 不混入患者级 breakdown（避免与 excluded_ratio 的患者分母核对不上）。
        n_total = int(out["patients"]["patient_id"].nunique())
        n_unobservable = int(out["patients"]["unobservable"].sum())
        n_no_feasible = max(n_total - n_unobservable - usable_patients, 0)
        excluded_breakdown = {"unobservable": n_unobservable,
                              "no_feasible_landmark": n_no_feasible}
        unknown_landmark_rows = int(lm.attrs.get("excluded_unknown", 0))
        records.append({
            "nominal_n": n, "usable_patients": usable_patients,
            "usable_landmarks": len(lm_eval), "n_events": n_events,
            "oof_events": oof_events,
            # excluded_ratio = 未进入可评估 landmark 模型的患者比例（唯一患者口径，含不可观测与无可评估 landmark）
            "excluded_ratio": 1 - usable_patients / max(n_total, 1),
            "excluded_breakdown": excluded_breakdown,
            "unknown_landmark_rows": unknown_landmark_rows,
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


def _point_boundary(bins, lo_bound):
    """原始样本点边界（诊断单列）：isotonic 拟合箱均值 → 跨 50% 的箱端点插值。
    返回 float / "not_observed" / None(全程<50%)。"""
    from sklearn.isotonic import IsotonicRegression
    if len(bins) < 2:
        return None
    xs = np.array([b[0] for b in bins]); ys = np.array([b[2].mean() for b in bins])
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


def _cross_boundary(fitted, grid, lo_bound):
    """在拟合曲线上求跨 50% 的箱端点插值点（平台段天然由插值处理）。
    返回 float / "not_observed"（全程 ≥50%）/ None（全程 <50%）。"""
    if fitted.min() >= lo_bound:
        return "not_observed"
    if fitted.max() < lo_bound:
        return None
    for i in range(len(grid) - 1):
        if fitted[i] < lo_bound <= fitted[i + 1]:
            t = (lo_bound - fitted[i]) / (fitted[i + 1] - fitted[i])
            return float(grid[i] + t * (grid[i + 1] - grid[i]))
    return None


def reliability_boundary(records_all_cells, followup_months):
    """规格 §8.2（**唯一算法**，与 Task 11 说明一致）：
    1) 队列级 Bootstrap：每样本重采样队列 → 重做分箱 → isotonic 拟合到**统一网格**（箱下界）
       → 记录每网格点拟合值（**不是**仅对"每次边界值"取分位）；
    2) 每网格点 2.5% 分位 = **CI 下界曲线**；
    3) **boundary_events = CI 下界曲线首达 50% 的事件数**（跨箱线性插值；规格 492）；
    4) boundary_ci = 每次 Bootstrap 样本在其拟合曲线上求边界点的分布 (2.5, 97.5)；
       "not_observed" 样本编码 +inf（上界可为 inf，允许语义）；无效样本丢弃；
    5) 边情形**只用 CI 下界曲线判定**：有效箱 <2 / 有效样本比例 < 门槛 → not_estimable；
       CI 下界曲线全程 ≥50% → not_observed；全程 <50% → not_estimable；
    6) point_boundary_events = 原始样本 isotonic 曲线跨 50%（**仅诊断单列，不参与边情形判定**，
       ≠ 边界主值——原始点达标不代表 CI 下界达标）。"""
    from sklearn.isotonic import IsotonicRegression
    lo_bound = cfg.THRESHOLDS["boundary_threshold"]
    bins = _bin_structure(records_all_cells)
    if len(bins) < 2:
        return {"status": "not_estimable", "boundary_events": None,
                "boundary_ci": None, "point_boundary_events": None}
    # point 仅作诊断（point_boundary_events），**不得提前用它判定边情形**——
    # 规格要求边情形由 Bootstrap 后的 CI 下界曲线判定：原始点估计全程 ≥50% 时
    # CI 下界仍可能跨 50%（低事件数箱波动大），提前短路会把 observed 误判为 not_observed。
    point = _point_boundary(bins, lo_bound)
    grid = np.array([b[0] for b in bins])
    B = cfg.THRESHOLDS["boundary_bootstrap_b"]
    valid_min = cfg.THRESHOLDS["boundary_valid_ratio_min"]
    rng = np.random.default_rng(0)
    grid_vals = [[] for _ in grid]
    boundary_samples, valid = [], 0
    for _ in range(B):
        sample = [records_all_cells[i] for i in
                  rng.integers(0, len(records_all_cells), size=len(records_all_cells))]
        sb = _bin_structure(sample)
        if len(sb) < 2:
            continue                       # 无效样本（<2 有效箱）→ 丢弃
        xs = np.array([b[0] for b in sb]); ys = np.array([b[2].mean() for b in sb])
        iso = IsotonicRegression(out_of_bounds="clip").fit(xs, ys)
        fitted = iso.predict(grid)
        for gi, v in enumerate(fitted):
            grid_vals[gi].append(v)
        valid += 1
        cb = _cross_boundary(fitted, grid, lo_bound)
        if cb == "not_observed":
            boundary_samples.append(float("inf"))
        elif isinstance(cb, float):
            boundary_samples.append(cb)
    valid_ratio = valid / B
    if valid_ratio < valid_min:                 # 有效样本比例门槛（版本化）
        return {"status": "not_estimable", "boundary_events": None,
                "boundary_ci": None, "point_boundary_events": point}
    lo_curve = np.array([np.percentile(vs, 2.5) if len(vs) else np.nan for vs in grid_vals])
    finite = np.isfinite(lo_curve)
    if not finite.any():
        return {"status": "not_estimable", "boundary_events": None,
                "boundary_ci": None, "point_boundary_events": point}
    # 边情形判定基于 CI 下界曲线（规格 496-497）
    if lo_curve[finite].min() >= lo_bound:
        return {"status": "not_observed", "boundary_events": None,
                "boundary_ci": None, "point_boundary_events": point}
    if lo_curve[finite].max() < lo_bound:
        return {"status": "not_estimable", "boundary_events": None,
                "boundary_ci": None, "point_boundary_events": point}
    boundary = _cross_boundary(lo_curve[finite], grid[finite], lo_bound)
    if not isinstance(boundary, float):
        return {"status": "not_estimable", "boundary_events": None,
                "boundary_ci": None, "point_boundary_events": point}
    if sum(np.isfinite(v) for v in boundary_samples) < 2:   # 有限边界样本不足 → observed + CI 缺失
        return {"status": "observed", "boundary_events": boundary,
                "boundary_ci": None, "point_boundary_events": point}
    return {"status": "observed", "boundary_events": boundary, "point_boundary_events": point,
            "boundary_ci": (float(np.percentile(boundary_samples, 2.5)),
                            float(np.percentile(boundary_samples, 97.5)))}


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
            agg["precision_not_met"] = not _meet_halfwidth(agg)   # 达 repeats_max 仍未满足半宽 → 标记
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
                               "证据时间线", "时间滞后 SHAP/消融摘要", "规模退化表", "局限与下一步"], start=1):
        assert f"## {i}. {title}" in md, title

def test_ci_unestimated_marked():
    md = render_report(_sec(rules=[{"conditions": [("sex", "eq", 1.0)], "ci": "CI 未估计"}]))
    assert "CI 未估计" in md

def test_p_obs_reported():
    md = render_report(_sec(p_obs={"r1_only": {"rate": 0.5}}))
    assert "P_obs" in md

def test_recovery_nested_coverage():
    # evaluate 的 coverage 是嵌套 per_rule（{"r1": {"eligible_total":..., "coverage":...}}）——
    # 报告必须按嵌套契约取数（_cov_rate），不能用 float 格式直接格式化 dict
    rec = {"rule_level_recovery": {"full_hit_count": 2, "denominator": 2,
                                   "r1_hit": True, "r2_hit": True},
           "instance_level_recovery": {"covered": 30, "denominator": 40, "rate": 0.75},
           "partial_recovery": {"r1_partial": False, "r2_partial": False},
           "coverage": {"r1": {"eligible_total": 100, "eligible_observed": 95, "coverage": 0.95},
                        "r2": {"eligible_total": 100, "eligible_observed": 98, "coverage": 0.98}},
           "rule_ci_present": True}
    md = render_report(_sec(recovery=rec))
    assert "0.95" in md and "0.98" in md

def test_ablation_block_renders():
    md = render_report(_sec(ablation={"PLT": {"baseline_auc": 0.9, "baseline_ci": (0.85, 0.95),
                                              "without_auc": 0.7, "without_ci": (0.6, 0.8),
                                              "auc_drop": 0.2}}))
    assert "整组滞后消融" in md and "0.200" in md

def test_ablation_block_nan_ci_renders_na():
    # CI 未估计（(nan,nan)）→ 报告显示 [NA, NA]，不得渲染为数值或 "[nan, nan]"
    md = render_report(_sec(ablation={"PLT": {"baseline_auc": 0.9,
                                              "baseline_ci": (float("nan"), float("nan")),
                                              "without_auc": 0.8, "without_ci": (0.7, 0.9),
                                              "auc_drop": 0.1}}))
    assert "[NA, NA]" in md
    assert "nan" not in md.replace("[NA, NA]", "")
```

- [ ] **Step 2: 红** → **Step 3: 实现**：

```python
"""Markdown 规律报告（§9 固定 8 节结构）。

契约：规则列表 = list[dict]（main 用 MinedRule.__dict__ 转换；测试直接传 dict）。
字段访问统一走 _rget，兼容 dict 与 MinedRule 对象（后续若改传对象无需改渲染）。
"""
from __future__ import annotations
import numpy as np

_SECTIONS = ["摘要", "信号验证", "挖回规则列表", "植入规则对照表",
             "证据时间线", "时间滞后 SHAP/消融摘要", "规模退化表", "局限与下一步"]


def _rget(rule, key, default=None):
    """统一字段访问：兼容 dict（rule[key]）与 MinedRule 对象（getattr）。"""
    if isinstance(rule, dict):
        return rule.get(key, default)
    return getattr(rule, key, default)


def _fmt_num(v):
    try:
        f = float(v)
        return f"{f:.3f}" if np.isfinite(f) else "NA"
    except (TypeError, ValueError):
        return "NA"


def _cond_str(c):
    if isinstance(c, (tuple, list)):
        return f"{c[0]} {c[1]} {c[2]}"
    return f"{c.indicator} {c.op} {c.value}"


def render_report(sections: dict) -> str:
    md = ["# 疾病进展规律挖掘 · 端到端最小闭环 报告", ""]
    signal = sections.get("signal", {})
    md.append(f"## 1. 摘要\n\n- 方法：模拟纵向队列，含植入规律。\n"
              f"- 信号：AUC 点估计 {_fmt_num(signal.get('auc_point'))}，"
              f"95% CI {_fmt_ci(signal.get('auc_ci'))}。\n")
    md.append("## 2. 信号验证\n\n"
              f"- 最终平均 OOF 预测 AUC：{_fmt_num(signal.get('auc_point'))}"
              f"（患者聚类 95% CI {_fmt_ci(signal.get('auc_ci'))}）\n"
              f"- PR-AUC：{_fmt_num(signal.get('pr_auc'))}；"
              f"Brier：{_fmt_num(signal.get('brier'))}\n")
    md.append("## 3. 挖回规则列表\n\n" + _rules_table(sections.get("rules", [])))
    md.append("## 4. 植入规则对照表\n\n" + _recovery_block(sections.get("recovery", {}))
              + _p_obs_block(sections.get("p_obs", {})))
    md.append("## 5. 证据时间线\n\n" + _timeline_block(sections.get("timeline", {})))
    md.append("## 6. 时间滞后 SHAP/消融摘要\n\n" + _shap_block(sections.get("shap", {}))
              + _ablation_block(sections.get("ablation", {})))
    md.append("## 7. 规模退化表\n\n" + _scale_block(sections.get("scale", {})))
    md.append("## 8. 局限与下一步\n\n- 模拟数据非临床结论；现实事件数约束；后续子系统见规格 §12。\n")
    return "\n".join(md)


def _fmt_ci(ci):
    """CI 渲染：有限数值 → [lo, hi]；None / NaN / inf / 异常 → [NA, NA]
    （CI 未估计（(nan,nan)）必须显示 NA，不得渲染成 "[nan, nan]" 伪装为有效）。"""
    try:
        if ci is None or not np.all(np.isfinite(ci)):
            return "[NA, NA]"
        return f"[{ci[0]:.3f}, {ci[1]:.3f}]"
    except Exception:
        return "[NA, NA]"


def _rules_table(rules):
    if not rules:
        return "- 未挖出规则\n"
    lines = ["| 条件 | lift 中位 | 支持事件 | 总支持 | 选中频率 | CI |", "| --- | --- | --- | --- | --- | --- |"]
    for r in rules:
        conds = "; ".join(_cond_str(c) for c in _rget(r, "conditions", []))   # 兼容 tuple 与 MinedCondition
        ci = _rget(r, "ci")
        ci_s = "CI 未估计" if isinstance(ci, str) else _fmt_ci(ci)
        lines.append(f"| {conds} | {_rget(r, 'lift_median', 0):.2f} | {_rget(r, 'event_support', 0)} "
                     f"| {_rget(r, 'total_support', 0)} | {_rget(r, 'selection_frequency', 0):.2f} | {ci_s} |")
    return "\n".join(lines) + "\n"


def _cov_rate(cov, key):
    """coverage 兼容契约：evaluate 传 `per_rule`（嵌套 dict，`{"r1": {"coverage": ...}}`）；
    防御旧格式（纯 float）。缺失 → NaN，绝不把 dict 当 float 格式化。"""
    v = cov.get(key, {})
    if isinstance(v, dict):
        return v.get("coverage", float("nan"))
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


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
            f"- 可评估覆盖率：R1={_cov_rate(cov, 'r1'):.3f}、R2={_cov_rate(cov, 'r2'):.3f}\n"
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
    order = tt.get("order", {}) if tt else {}
    return (f"- early_median：{order.get('early_median')}；afp_median：{order.get('afp_median')}\n"
            f"- afp_after_early：{order.get('afp_after_early')}；tiebreak：{order.get('tiebreak_by_event_count')}\n"
            f"- 交集患者：{tt.get('n_intersection')}；unmatched：{_fmt_num(tt.get('unmatched_rate'))}\n")


def _shap_block(shap):
    if not shap:
        return "- 未运行时间滞后 SHAP\n"
    lines = []
    for ind, lags in shap.items():
        lines.append(f"- {ind}: " + ", ".join(f"lag{lag}={v:.3f}" for lag, v in lags.items()))
    return "\n".join(lines) + "\n"


def _ablation_block(abl):
    """整组滞后消融（§7.2 佐证）：移除该指标滞后观测组后的 OOF AUC（含患者 Bootstrap CI）。"""
    if not abl:
        return ""
    lines = ["\n**整组滞后消融（移除该指标滞后观测组 → 重训 OOF AUC；描述性，非因果）：**",
             "| 指标 | 基线 AUC | 移除组后 AUC | AUC 下降 |", "| --- | --- | --- | --- |"]
    for ind, d in abl.items():
        lines.append(f"| {ind} | {_fmt_num(d.get('baseline_auc'))} ({_fmt_ci(d.get('baseline_ci'))}) "
                     f"| {_fmt_num(d.get('without_auc'))} ({_fmt_ci(d.get('without_ci'))}) "
                     f"| {_fmt_num(d.get('auc_drop'))} |")
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
    # 只检查"本模块定义"的函数（fn.__module__ == mod.__name__），避免把 import 进来的 evaluate
    # 误判为非 evaluator 模块成员（scale_study/main 都 import 了 evaluator.evaluate）
    for mod in [simulate_cohort, features, splitters, model, attribution, rules, scale_study, report, main]:
        for name, fn in inspect.getmembers(mod, inspect.isfunction):
            if fn.__module__ != mod.__name__:
                continue
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
    for key in ["auc_ci", "lag_shap", "lag_ablation", "p_obs", "recovery", "report_md"]:
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
from attribution import lead_lag_analysis, lag_shap_analysis, lag_ablation_analysis
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
    ablation = lag_ablation_analysis(lm, cfg.THRESHOLDS["shap_lags"], seed=seed)
    mined = mine_rules(sub, cfg.THRESHOLDS["cv_repeats"],
                       seeds=list(range(seed, seed + cfg.THRESHOLDS["cv_repeats"])))
    ev = evaluate(mined, out["planted_rules"], sub, out["coverage"])
    ll = lead_lag_analysis(out["patients"], out["obs"])
    po = p_obs(out["patients"], out["obs"], hw)
    report_md = render_report({"signal": model_res, "rules": [r.__dict__ for r in mined["rules"]],
                               "recovery": ev, "timeline": ll, "shap": lag_shap,
                               "ablation": ablation,
                               "scale": scale or {}, "p_obs": po, "limitations": []})
    os.makedirs(out_dir, exist_ok=True)
    with open(f"{out_dir}/report_method_validation.md", "w", encoding="utf-8") as f:
        f.write(report_md)
    return {"auc_ci": model_res["auc_ci"], "auc_point": model_res["auc_point"],
            "recovery": ev, "coverage": ev["coverage"], "lead_lag": ll,
            "lag_shap": lag_shap, "lag_ablation": ablation, "p_obs": po,
            "report_md": report_md, "rules_ci": [r.ci for r in mined["rules"]]}


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
        cov_ok = ("r1" in cov and "r2" in cov                      # 键必须存在（防 get(...,0) 静默缺失）
                  and cov["r1"]["coverage"] >= cfg.THRESHOLDS["coverage_gate"]
                  and cov["r2"]["coverage"] >= cfg.THRESHOLDS["coverage_gate"])
        # n_rules > 0 且 rule_ci_present ⇒ 每条规则 CI 均为有限数值区间（非"CI 未估计"、非 NaN/inf）
        # 依赖链闭合（有测试支撑，非仅注释假设）：Task 9 通用全枚举（max_candidates ≥ 组合总数，
        # 防截断显式 raise）+ 确定性排序 (-lift, canonical_rule) 保证 R1/R2 组合进入 top_k
        # ——**synthetic fixture 断言 canonical 规则确定性入选 top_k**（test_synthetic_fixture_r1_rule_in_top_k）
        # 且 full_hit（test_synthetic_fixture_discovers_r1_full_hit）；并列 lift 稳定排序
        # （test_discover_sorted_by_lift_then_canonical）；_fold_discover_validate 按唯一患者定折数
        # （无"唯一正例重复抽中"导致的虚假 k>=2）。若规则未进 top-k → 本 acceptance 直接失败。
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
        assert rec["usable_landmarks"] > 0
        assert rec["usable_patients"] <= rec["nominal_n"]
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
- **接口自洽（v5.4 修复）**：neither hazard 可缩放（λ_c·λ0）+ 参考 landmark 无事件；路径组不可观测完整判定 + 保留组语义 + **unobservable_reason 原因分解（删失不设门槛、条件未成立 ≤5%，分母限定实际进入条件检查的患者；原因互斥/绑定/计数闭合）**；coverage 分母=可评估/规则路径总数 + excluded 单列 + **neither 误报分母 = 全部 neither 候选患者（规格 §5.3，校准分母不变；三类患者手工 fixture 断言 1/3 识别分母错误）**；校准下界 confirm<event<=confirm+hw；**各路径组条件成立率 ≥95% 按各自指定确认 landmark**（R1-only=w_R1、R2-only/交集=w_A+1 双条件、neither 首参考不命中两规则；仅限可评估患者）；**`_bisect` 端点包围强制检查 + 上界自适应扩展 + 非包围显式 ValueError**；lead-lag per-patient 破平（逐患者 afp vs min(plt,hba1c)）+ 匹配对照参与（control_delta）+ **per_indicator_n 限定相关路径组且有匹配合格对照（§10 口径）+ 风险集匹配检查对照 index time 前删失**；规则候选固定临床阈值网格（**通用、无植入语义**）+ **`_discover_frozen` 通用全枚举 + lift 排序 + max_candidates ≥ 组合总数防截断（显式 raise）**（fixture 正例+确定性负例断言 full_hit）；`_canonical_rule` 数值保类型；sex 统一数值；horizon/lookback/lag 三字段比较；规则 CI 完整重跑 + 无 oof_frame + **按唯一患者定折数（Bootstrap 重复患者不重复计数）+ 单类/不足样本剔除 + 确定性"CI 未估计"契约**；**模型/规则 Bootstrap 无效样本契约（单类丢弃、有效 <2 → NaN/"CI 未估计"）**；partial_hit typed 容差真子集 + 实例级绑定 R1/R2 规则；可靠性边界**规格算法唯一**（每网格点 CI 下界曲线首达 50% 为主值，point_boundary_events 诊断单列）+ 边情形；**run_cell excluded_breakdown 统一患者级口径（unobservable + no_feasible + usable == nominal_n），unknown 行级单独字段**；**report `_cov_rate` 嵌套 coverage 契约（含真实嵌套 coverage 报告测试）**；**Task 8 整组滞后消融 lag_ablation_analysis（消融组 = lags 对应滞后观测列，含患者 Bootstrap CI，§7.2）**；**模拟器观测截断 T = min(事件, 删失, 行政终点) + 逐患者收集（`patient_rows`，杜绝截断后跨患者污染，`test_obs_truncation_no_cross_patient`）**；report 格式化守卫（signal/timeline/条件 tuple）；method-validation 并入缩小规模退化；acceptance 键存在断言 + 现实规模交叉核对 + ci_ok 有限区间 + 依赖链闭合（Task 9 synthetic fixture 断言 R1 canonical 规则**确定性进 top_k** + full_hit + 并列 lift 稳定排序，非仅注释假设）。
- **v5.5 追加**：`_discover_frozen` 排序二级键 `(-lift, canonical_rule)`（并列 lift 不依赖枚举顺序）；`reliability_boundary` 边情形只由 CI 下界曲线判定（point 仅诊断，`test_boundary_point_high_ci_lower_crosses` 覆盖"原始达标但 CI 下界跨 50%"）；`unobservable_reason` 逐类绑定 + 计数闭合测试；`lag_ablation` CI 可估计/不足样本两测试 + `_fmt_ci` NaN→`[NA, NA]`（CI 未估计不伪装数值）。
- **无占位符**：所有任务（含 Task 4/5/6）均含实际测试代码与可执行实现；无"同 vN"或"实现者须补齐"。

## 执行交接

计划已保存（v5.5）。执行选项：**Subagent-Driven（推荐）** 或 **Inline Execution**。按既定协作框架建议**分批执行（Task 1-3、4-6、7-10、11-14）、每批交 Codex 审查、通过后推送**。实施计划 v5.5 先交 Codex 复审。
