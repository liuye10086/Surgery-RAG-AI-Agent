# 数据来源与生成说明

## 生成信息

- 生成日期：2026-08-18
- 固定随机种子：`20260818`
- 生成器版本：`1.3.1`
- 生成器：`scripts/generate_fatty_liver_longitudinal.py`
- 患者数：150
- 随访记录数：692

## 输入文档

| 文档 | SHA-256 |
|---|---|
| `脂肪肝相关病例（1-78例）.docx` | `8e5cd1158512b9806d84ca83517cc444186bf5aacd17e0c0ab70b767d32b2955` |
| `脂肪肝病例-2026.8.7.docx` | `3542d340059af7fddbc6ce867ef2bc970a1bb917f4cf263b133b791fed45a372` |

## 病例筛选

原始共解析 155 个病例段，固定排除 `A27-1`、`A30-1`、`A32-1`、`A34-1`、`A35-1`，保留 150 例。

## 字段来源

- 年龄、性别、明确日期、明确诊断及能够识别的检验值优先来自病例文本。
- 缺失人口学字段使用稳定规则补齐。
- 原病例没有提供的纵向日期与指标值由固定种子生成器补齐。
- `patients.csv` 与 `visits.csv` 保持采集规范的固定列，不增加来源或分类理由字段。
- `fatty_liver_progression` 允许糖尿病、肥胖、高血压、血脂异常等常见代谢共病；明确竞争性肝病病因、无脂肪肝证据或无脂肪肝前期的晚期首诊病例保留为 `mixed`。
- 每例分类理由记录在 `quality_report.json` 和 `extracted_cases.json`，用于逐例审计。
- 原文明确 HCC 或肝硬化时锁定对应结局；其余结局为达到方法验证所需事件量而生成分配。逐例来源见 `quality_report.json` 的 `outcome_assignment_audit` 和 `generated_outcome_ids`。
- `fatty_liver_date` 优先采用与脂肪肝证据相邻的明确日期；只有“X 年前发现/诊断脂肪肝”时，以病例中最早明确日期（若无则以生成首访）反推年份；仍无法定位时使用生成基线。三类患者清单见质量报告。
- `lost_to_followup=yes` 为固定规则生成的少量流程测试状态，不代表病例原文记载；患者清单见 `generated_lost_to_followup_ids`。
- 生成值不得表述为从已遗失的原始检验报告中补采得到，不得作为真实世界临床证据、诊疗依据或未经说明的临床研究原始数据。

## 使用边界

- 允许用途：数据导入管线测试、规律挖掘流程机制验证、界面与统计功能演示。
- 禁止用途：宣称发现真实临床规律、形成真实世界临床证据、支持诊疗决策或作为未经说明的临床研究原始数据。
- R1、R2、R1+R2 信号是生成器有意植入的流程验证路径；从本数据重新挖出这些信号属于机制回归测试，不是独立临床发现。

## 汇总

- 队列：{"fatty_liver_progression": 118, "mixed": 32}
- 结局：{"hcc": 25, "cirrhosis": 50, "fatty_liver": 75}
- 路径：{"r1_r2": 9, "r1": 9, "r2": 15, "non_rule_progression": 42, "stable": 75}
- actual_rule_signal_counts：{"r1": 18, "r2": 53, "r1_r2": 11, "neither": 90}
- 队列 × 结局：{"fatty_liver_progression|cirrhosis": 46, "fatty_liver_progression|fatty_liver": 48, "fatty_liver_progression|hcc": 24, "mixed|cirrhosis": 4, "mixed|fatty_liver": 27, "mixed|hcc": 1}
- 各指标缺失率：{"alt": 0.0723, "ast": 0.0882, "ggt": 0.1214, "tbil": 0.1012, "alb": 0.1012, "plt": 0.0, "hba1c": 0.0, "afp": 0.0, "waist": 0.1806, "bmi": 0.1344}
- 原文锚点冲突数：13
- 随访次数分布：{"3": 26, "4": 47, "5": 36, "6": 41}

## 患者来源映射

| patient_id | 源病例段 | 原文年龄 | 原文性别 | 队列分组 | 提取检验锚点数 |
|---|---|---:|---|---|---:|
| P001 | A1-1 | 38 | male | fatty_liver_progression | 8 |
| P002 | A2-1 | 未明确 | 未明确 | fatty_liver_progression | 9 |
| P003 | A3-1 | 38 | male | fatty_liver_progression | 1 |
| P004 | A4-1 | 72 | 未明确 | fatty_liver_progression | 0 |
| P005 | A5-1 | 63 | 未明确 | fatty_liver_progression | 0 |
| P006 | A6-1 | 72 | female | mixed | 0 |
| P007 | A7-1 | 35 | male | fatty_liver_progression | 3 |
| P008 | A8-1 | 69 | male | mixed | 1 |
| P009 | A9-1 | 52 | male | fatty_liver_progression | 6 |
| P010 | A10-1 | 59 | 未明确 | fatty_liver_progression | 0 |
| P011 | A11-1 | 47 | male | fatty_liver_progression | 1 |
| P012 | A12-1 | 51 | female | fatty_liver_progression | 7 |
| P013 | A13-1 | 58 | female | fatty_liver_progression | 3 |
| P014 | A14-1 | 45 | male | fatty_liver_progression | 2 |
| P015 | A15-1 | 51 | female | mixed | 0 |
| P016 | A16-1 | 60 | female | fatty_liver_progression | 1 |
| P017 | A17-1 | 29 | male | fatty_liver_progression | 1 |
| P018 | A17-2 | 29 | female | mixed | 5 |
| P019 | A18-1 | 46 | male | fatty_liver_progression | 5 |
| P020 | A19-1 | 28 | female | fatty_liver_progression | 12 |
| P021 | A20-1 | 28 | female | fatty_liver_progression | 12 |
| P022 | A21-1 | 54 | female | fatty_liver_progression | 3 |
| P023 | A22-1 | 17 | male | fatty_liver_progression | 1 |
| P024 | A23-1 | 42 | male | fatty_liver_progression | 1 |
| P025 | A24-1 | 29 | female | mixed | 7 |
| P026 | A25-1 | 31 | male | fatty_liver_progression | 5 |
| P027 | A26-1 | 37 | female | mixed | 6 |
| P028 | A26-2 | 37 | male | fatty_liver_progression | 14 |
| P029 | A28-1 | 39 | female | fatty_liver_progression | 5 |
| P030 | A29-1 | 22 | female | fatty_liver_progression | 4 |
| P031 | A31-1 | 未明确 | male | mixed | 1 |
| P032 | A33-1 | 30 | male | fatty_liver_progression | 15 |
| P033 | A36-1 | 33 | male | mixed | 5 |
| P034 | A37-1 | 66 | male | fatty_liver_progression | 1 |
| P035 | A38-1 | 30 | female | fatty_liver_progression | 10 |
| P036 | A38-2 | 31 | male | fatty_liver_progression | 3 |
| P037 | A39-1 | 33 | male | fatty_liver_progression | 7 |
| P038 | A40-1 | 28 | female | fatty_liver_progression | 7 |
| P039 | A41-1 | 28 | male | fatty_liver_progression | 4 |
| P040 | A42-1 | 23 | male | fatty_liver_progression | 5 |
| P041 | A43-1 | 57 | male | mixed | 0 |
| P042 | A44-1 | 37 | male | fatty_liver_progression | 14 |
| P043 | A45-1 | 22 | male | fatty_liver_progression | 5 |
| P044 | A46-1 | 69 | male | mixed | 8 |
| P045 | A47-1 | 38 | male | fatty_liver_progression | 8 |
| P046 | A48-1 | 38 | male | fatty_liver_progression | 8 |
| P047 | A49-1 | 34 | male | fatty_liver_progression | 5 |
| P048 | A50-1 | 未明确 | 未明确 | mixed | 2 |
| P049 | A51-1 | 未明确 | 未明确 | mixed | 4 |
| P050 | A52-1 | 47 | male | fatty_liver_progression | 4 |
| P051 | A53-1 | 38 | male | fatty_liver_progression | 8 |
| P052 | A54-1 | 24 | male | fatty_liver_progression | 0 |
| P053 | A55-1 | 53 | male | mixed | 4 |
| P054 | A56-1 | 44 | female | fatty_liver_progression | 3 |
| P055 | A57-1 | 51 | female | fatty_liver_progression | 0 |
| P056 | A58-1 | 31 | male | mixed | 3 |
| P057 | A59-1 | 29 | male | fatty_liver_progression | 1 |
| P058 | A60-1 | 32 | female | fatty_liver_progression | 1 |
| P059 | A61-1 | 52 | male | fatty_liver_progression | 6 |
| P060 | A62-1 | 47 | female | fatty_liver_progression | 0 |
| P061 | A63-1 | 25 | female | fatty_liver_progression | 29 |
| P062 | A64-1 | 25 | male | fatty_liver_progression | 10 |
| P063 | A65-1 | 63 | 未明确 | fatty_liver_progression | 6 |
| P064 | A66-1 | 40 | 未明确 | fatty_liver_progression | 6 |
| P065 | A67-1 | 32 | male | fatty_liver_progression | 4 |
| P066 | A68-1 | 21 | female | fatty_liver_progression | 2 |
| P067 | A69-1 | 43 | female | fatty_liver_progression | 3 |
| P068 | A70-1 | 10 | 未明确 | fatty_liver_progression | 0 |
| P069 | A71-1 | 38 | male | fatty_liver_progression | 9 |
| P070 | A72-1 | 40 | male | fatty_liver_progression | 5 |
| P071 | A73-1 | 64 | male | mixed | 3 |
| P072 | A74-1 | 45 | female | fatty_liver_progression | 4 |
| P073 | A75-1 | 63 | female | fatty_liver_progression | 2 |
| P074 | A76-1 | 38 | female | fatty_liver_progression | 6 |
| P075 | A77-1 | 64 | male | mixed | 3 |
| P076 | A78-1 | 37 | male | fatty_liver_progression | 15 |
| P077 | A78-2 | 55 | female | fatty_liver_progression | 2 |
| P078 | B1-1 | 38 | male | fatty_liver_progression | 0 |
| P079 | B2-1 | 23 | male | mixed | 2 |
| P080 | B3-1 | 28 | male | fatty_liver_progression | 3 |
| P081 | B4-1 | 54 | female | fatty_liver_progression | 2 |
| P082 | B5-1 | 65 | male | fatty_liver_progression | 2 |
| P083 | B6-1 | 69 | male | fatty_liver_progression | 2 |
| P084 | B7-1 | 27 | female | fatty_liver_progression | 5 |
| P085 | B8-1 | 34 | male | fatty_liver_progression | 3 |
| P086 | B9-1 | 66 | female | mixed | 8 |
| P087 | B10-1 | 72 | female | fatty_liver_progression | 3 |
| P088 | B11-1 | 28 | female | fatty_liver_progression | 2 |
| P089 | B12-1 | 37 | male | fatty_liver_progression | 3 |
| P090 | B13-1 | 未明确 | 未明确 | mixed | 33 |
| P091 | B14-1 | 64 | male | fatty_liver_progression | 4 |
| P092 | B15-1 | 63 | male | fatty_liver_progression | 7 |
| P093 | B16-1 | 68 | female | fatty_liver_progression | 2 |
| P094 | B17-1 | 68 | female | fatty_liver_progression | 2 |
| P095 | B18-1 | 53 | male | fatty_liver_progression | 13 |
| P096 | B19-1 | 57 | male | fatty_liver_progression | 1 |
| P097 | B20-1 | 16 | female | mixed | 2 |
| P098 | B21-1 | 43 | male | fatty_liver_progression | 0 |
| P099 | B22-1 | 43 | male | fatty_liver_progression | 13 |
| P100 | B23-1 | 24 | female | fatty_liver_progression | 3 |
| P101 | B24-1 | 24 | female | fatty_liver_progression | 4 |
| P102 | B25-1 | 39 | male | fatty_liver_progression | 3 |
| P103 | B26-1 | 25 | male | fatty_liver_progression | 11 |
| P104 | B27-1 | 54 | male | fatty_liver_progression | 2 |
| P105 | B28-1 | 36 | female | fatty_liver_progression | 7 |
| P106 | B29-1 | 36 | female | fatty_liver_progression | 6 |
| P107 | B30-1 | 23 | male | mixed | 2 |
| P108 | B31-1 | 23 | male | fatty_liver_progression | 5 |
| P109 | B32-1 | 56 | female | fatty_liver_progression | 3 |
| P110 | B33-1 | 78 | female | fatty_liver_progression | 1 |
| P111 | B34-1 | 46 | female | mixed | 8 |
| P112 | B35-1 | 45 | male | fatty_liver_progression | 2 |
| P113 | B36-1 | 45 | male | fatty_liver_progression | 25 |
| P114 | B37-1 | 37 | female | fatty_liver_progression | 1 |
| P115 | B38-1 | 40 | male | fatty_liver_progression | 3 |
| P116 | B39-1 | 66 | male | fatty_liver_progression | 1 |
| P117 | B40-1 | 42 | female | fatty_liver_progression | 4 |
| P118 | B41-1 | 19 | female | mixed | 1 |
| P119 | B42-1 | 54 | male | mixed | 2 |
| P120 | B43-1 | 40 | female | fatty_liver_progression | 1 |
| P121 | B44-1 | 28 | male | fatty_liver_progression | 3 |
| P122 | B45-1 | 56 | female | fatty_liver_progression | 3 |
| P123 | B46-1 | 35 | female | mixed | 4 |
| P124 | B47-1 | 65 | male | fatty_liver_progression | 4 |
| P125 | B48-1 | 41 | male | fatty_liver_progression | 2 |
| P126 | B49-1 | 54 | female | fatty_liver_progression | 3 |
| P127 | B50-1 | 48 | male | fatty_liver_progression | 4 |
| P128 | B51-1 | 55 | female | fatty_liver_progression | 2 |
| P129 | B52-1 | 53 | male | fatty_liver_progression | 2 |
| P130 | B53-1 | 39 | male | mixed | 2 |
| P131 | B54-1 | 33 | male | fatty_liver_progression | 1 |
| P132 | B55-1 | 19 | male | mixed | 5 |
| P133 | B56-1 | 31 | male | fatty_liver_progression | 5 |
| P134 | B57-1 | 37 | male | fatty_liver_progression | 5 |
| P135 | B58-1 | 30 | female | fatty_liver_progression | 2 |
| P136 | B59-1 | 67 | female | fatty_liver_progression | 3 |
| P137 | B60-1 | 40 | female | mixed | 1 |
| P138 | B61-1 | 62 | female | fatty_liver_progression | 2 |
| P139 | B62-1 | 71 | male | fatty_liver_progression | 3 |
| P140 | B63-1 | 74 | male | mixed | 4 |
| P141 | B64-1 | 74 | female | fatty_liver_progression | 0 |
| P142 | B65-1 | 39 | female | fatty_liver_progression | 3 |
| P143 | B66-1 | 66 | female | mixed | 12 |
| P144 | B67-1 | 71 | female | fatty_liver_progression | 0 |
| P145 | B68-1 | 46 | male | mixed | 8 |
| P146 | B69-1 | 29 | male | fatty_liver_progression | 2 |
| P147 | B70-1 | 58 | male | fatty_liver_progression | 2 |
| P148 | B71-1 | 58 | male | fatty_liver_progression | 2 |
| P149 | B72-1 | 69 | male | mixed | 6 |
| P150 | B73-1 | 74 | female | fatty_liver_progression | 4 |
