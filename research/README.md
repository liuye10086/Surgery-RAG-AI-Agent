# 疾病进展规律挖掘 · 端到端最小闭环（research/）

独立子项目：用含植入规律的模拟纵向数据，跑通"模拟 → 窗口特征 → 模型 → 时序归因 → 规则挖掘 → evaluator → 规模退化 → 规律报告"全链路，验证方法论能可信地恢复植入规律，并量化现实数据规模下的可信度。

## 运行

```bash
# 完整流程（方法验证 + 缩小规模退化）
python -m main --mode full --out outputs/

# 仅方法验证（含缩小规模退化，报告 §7 有内容）
python -m main --mode method-validation --out outputs/

# 仅规模退化（全局网格）
python -m main --mode scale-study --out outputs/
```

产物：`outputs/report_method_validation.md`（8 节 Markdown 报告）、`outputs/scale_study.json`（规模退化）。

## 测试

```bash
cd research

# 快速层（默认，排除 slow/acceptance）
python -m pytest tests/

# 慢层（端到端回归、完整 pipeline、现实规模参数化）
python -m pytest tests/ -m slow

# 验收层（Monte Carlo 方法验收，K=20 种子 ≥90% 通过）
python -m pytest tests/ -m acceptance
```

## 可复现性

- 随机种子族固定（`seed` → `simulate`/`fit_and_oof`/`mine_rules`/`patient_bootstrap_ci` 层层传递）。
- `simulate` 事件门控用**患者级 CRN**（`rng_gate` 每患者固定消耗 1 个 uniform + `rng_delta` δ 独立流 + 患者级派生 `rng_i`），患者构成与 gate 无关 → 校准 bisection 收敛可复现。
- 同种子两次运行报告逐字一致（`test_reproducible_same_seed_same_report`）。

## 模块

| 模块 | 职责 |
| --- | --- |
| `config.py` | 版本化常量（指标/参考范围/校准目标/阈值/网格） |
| `simulate_cohort.py` | 前向模拟（Z 路径 + 事件门控校准 + coverage） |
| `features.py` | 窗口特征 + 分角色 landmark（全量/确认子集） |
| `splitters.py` | 患者折 + 聚类 Bootstrap |
| `model.py` | 患者级 OOF（梯度提升） |
| `attribution.py` | lead-lag 时间对齐 + 时间滞后 SHAP/整组消融 |
| `rules.py` | 规则挖掘（折内候选 + Apriori + 规则 CI） |
| `evaluator.py` | 类型化命中 + 两层恢复率（唯一接触 planted_rules） |
| `scale_study.py` | Monte Carlo 规模退化 + 可靠性边界 |
| `report.py` | §9 固定 8 节 Markdown 报告 |
| `main.py` | CLI 编排 |

规格依据：`../docs/superpowers/specs/2026-08-06-progression-rule-mining-loop-design.md`（v18）。
