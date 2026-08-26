# 疾病进展规律挖掘 · 端到端最小闭环 报告

## 1. 摘要

- 方法：模拟纵向队列，含植入规律。
- 信号：AUC 点估计 0.776，95% CI [0.750, 0.801]。

## 2. 信号验证

- 最终平均 OOF 预测 AUC：0.776（患者聚类 95% CI [0.750, 0.801]）
- 跨重复 AUC 中位数：0.773
- PR-AUC：0.523；Brier：0.117
- 信号门槛：AUC 患者聚类 95% CI 下界 ≥ 0.65 → **通过**

**潜在风险校准（独立 N=50,000 队列，内部真值，不受删失影响；**校准达标**（四组 |误差| ≤ ±3pp））：**
| 组 | 目标 | 实际 | 误差 |
| --- | --- | --- | --- |
| neither | 0.120 | 0.120 | -0.000 |
| r1_only | 0.600 | 0.596 | -0.004 |
| r2_only | 0.400 | 0.395 | -0.005 |
| r1_and_r2 | 0.730 | 0.734 | 0.004 |

## 3. 挖回规则列表

| 条件 | horizon | lookback | lag | lift 中位 | 支持事件 | 总支持 | 选中频率 | CI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AFP consecutive_rises 2.0; HbA1c consecutive_rises 2.0; PLT drop_pct 0.2; age gt 40.0 | 4 | 2 | 0 | 2.89 | 99 | 130 | 1.00 | [2.640, 3.169] |
| AFP consecutive_rises 2.0; HbA1c consecutive_rises 2.0; PLT drop_pct 0.2; age gt 50.0 | 4 | 2 | 0 | 2.88 | 98 | 129 | 1.00 | [2.633, 3.168] |
| AFP consecutive_rises 2.0; PLT drop_pct 0.2; age gt 40.0; sex eq 1.0 | 4 | 2 | 0 | 2.88 | 98 | 129 | 1.00 | [2.631, 3.170] |
| AFP consecutive_rises 2.0; PLT drop_pct 0.2; age gt 50.0; sex eq 1.0 | 4 | 2 | 0 | 2.88 | 97 | 128 | 1.00 | [2.626, 3.160] |
| AFP consecutive_rises 2.0; PLT drop_pct 0.2; age gt 40.0 | 4 | 2 | 0 | 2.87 | 102 | 135 | 1.00 | [2.621, 3.149] |
| AFP consecutive_rises 2.0; HbA1c consecutive_rises 2.0; PLT drop_pct 0.2 | 4 | 2 | 0 | 2.87 | 99 | 131 | 1.00 | [2.616, 3.156] |
| AFP consecutive_rises 2.0; HbA1c consecutive_rises 2.0; PLT drop_pct 0.2; sex eq 1.0 | 4 | 2 | 0 | 2.85 | 97 | 129 | 1.00 | [2.600, 3.145] |
| AFP consecutive_rises 2.0; PLT drop_pct 0.2; age gt 40.0; age gt 50.0 | 4 | 2 | 0 | 2.85 | 99 | 132 | 1.00 | [2.601, 3.129] |
| AFP consecutive_rises 2.0; PLT drop_pct 0.2; age gt 50.0 | 4 | 2 | 0 | 2.85 | 99 | 132 | 1.00 | [2.601, 3.129] |
| AFP consecutive_rises 2.0; PLT drop_pct 0.2; sex eq 1.0 | 4 | 2 | 0 | 2.82 | 98 | 132 | 1.00 | [2.565, 3.098] |
| AFP consecutive_rises 2.0; PLT drop_pct 0.2 | 4 | 2 | 0 | 2.79 | 102 | 139 | 1.00 | [2.542, 3.063] |
| AFP consecutive_rises 2.0; HbA1c consecutive_rises 2.0; age gt 40.0; sex eq 1.0 | 4 | 2 | 0 | 2.77 | 97 | 133 | 1.00 | [2.520, 3.032] |
| AFP consecutive_rises 2.0; HbA1c consecutive_rises 2.0; age gt 50.0; sex eq 1.0 | 4 | 2 | 0 | 2.77 | 97 | 133 | 1.00 | [2.520, 3.032] |
| AFP consecutive_rises 2.0; HbA1c consecutive_rises 2.0; age gt 40.0; age gt 50.0 | 4 | 2 | 0 | 2.71 | 100 | 140 | 1.00 | [2.463, 2.976] |
| AFP consecutive_rises 2.0; HbA1c consecutive_rises 2.0; age gt 50.0 | 4 | 2 | 0 | 2.71 | 100 | 140 | 1.00 | [2.463, 2.976] |
| AFP consecutive_rises 2.0; HbA1c consecutive_rises 2.0; age gt 40.0 | 4 | 2 | 0 | 2.63 | 104 | 150 | 1.00 | [2.409, 2.887] |
| AFP consecutive_rises 2.0; HbA1c consecutive_rises 2.0; sex eq 1.0 | 4 | 2 | 0 | 2.60 | 102 | 149 | 1.00 | [2.372, 2.871] |
| AFP consecutive_rises 2.0; age gt 40.0; age gt 50.0; sex eq 1.0 | 4 | 2 | 0 | 2.49 | 109 | 166 | 1.00 | [2.266, 2.741] |
| AFP consecutive_rises 2.0; age gt 50.0; sex eq 1.0 | 4 | 2 | 0 | 2.49 | 109 | 166 | 1.00 | [2.266, 2.741] |
| HbA1c consecutive_rises 2.0; PLT drop_pct 0.2; age gt 40.0 | 4 | 2 | 0 | 2.44 | 179 | 278 | 1.00 | [2.284, 2.642] |

- 另有 69 条规则未列出（lift 中位范围 [0.57, 2.89]）。

## 4. 植入规则对照表

- 规则级恢复率：完整命中 2/2（R1=True、R2=True）
- 实例级恢复率：覆盖 542/1317（rate 0.412）
- 部分恢复：R1=True、R2=False
- 可评估覆盖率：R1=0.887、R2=0.900
- 规则 CI 齐全：False
- P_obs（观测标签风险 = positive/(positive+negative)，排除 unknown，不参与 §10 验收）：
  - neither: 113/917 = 0.123
  - r1_only: 94/170 = 0.553
  - r2_only: 57/126 = 0.452
  - r1_and_r2: 83/104 = 0.798

## 5. 证据时间线

- early_median：4.0；afp_median：2.0
- afp_after_early：True；tiebreak：0
- 交集患者：83；unmatched：0.000
- 路径级 unmatched（空组 NA）：r1_only=0.000, r2_only=0.000, r1_and_r2=0.000
- 进展组 vs 匹配对照首次偏离差（负=进展者更早）：PLT=-2.000（CI [-2.500, -1.000]）; HbA1c=-3.000（CI [-3.000, -2.000]）; AFP=-1.000（CI [-2.000, -1.000]）

## 6. 时间滞后 SHAP/消融摘要

- PLT: lag0=0.009, lag1=0.111, lag2=0.026
- HbA1c: lag0=0.278, lag1=0.215, lag2=0.032
- AFP: lag0=0.078, lag1=0.212, lag2=0.058

**整组滞后消融（移除该指标滞后观测组 → 重训 OOF AUC；描述性，非因果）：**
| 指标 | 基线 AUC | 移除组后 AUC | AUC 下降 |
| --- | --- | --- | --- |
| PLT | 0.773 ([0.747, 0.798]) | 0.772 ([0.746, 0.798]) | 0.001 |
| HbA1c | 0.773 ([0.747, 0.798]) | 0.770 ([0.744, 0.796]) | 0.002 |
| AFP | 0.773 ([0.747, 0.798]) | 0.762 ([0.734, 0.789]) | 0.011 |

## 7. 规模退化表

- 未运行规模退化实验

## 8. 局限与下一步

- 模拟数据非临床结论；现实事件数约束；后续子系统见规格 §12。
