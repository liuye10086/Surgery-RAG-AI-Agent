# 阿尔茨海默病纵向数据集扩展至 300 例设计

> 日期：2026-08-19  
> 协作方式：简化流程，直接在当前 `main` 工作区实施  
> 状态：已实施、验证并通过独立只读评审  
> 基线：`data/generated/ad_longitudinal_150/` 经过病例校准、测试与交叉评审的五项产物  
> 输出：`data/generated/ad_longitudinal_300/` 下五项确定性产物

## 1. 背景与目标

当前 `data/generated/ad_longitudinal_150/` 已包含 150 例带 CDR 分级的病例约束纵向合成数据，其中 P001–P146 逐例锚定两份真实 AD 病例 Word 文档，P147–P150 为可审计的分层重组病例。

本任务在不修改原 150 例数据及其生成器的前提下，新增 P151–P300 共 150 例分层重组患者，形成独立的 300 例合并数据集，用于操作者端进展预测、规则挖掘、数据导入、统计、性能及算法回归验证。

最终数据必须满足：

- 患者编号连续为 P001–P300；
- P001–P150 的患者行、访视行及顺序与基线完全一致；
- P151–P300 不冒充新的真实病例，不伪造 DOCX 源病例编号；
- CDR、队列和五类路径均按 150 例基线等比例翻倍；
- 所有五项产物固定种子、字节级可复现；
- 质量报告和来源说明可区分基线、扩展与总体统计。

## 2. 变更边界

### 2.1 新增文件

- `docs/superpowers/specs/2026-08-19-ad-longitudinal-300-extension-design.md`
- `docs/superpowers/plans/2026-08-19-ad-longitudinal-300-extension.md`
- `scripts/extend_ad_longitudinal_to_300.py`
- `scripts/tests/test_extend_ad_longitudinal_to_300.py`
- `data/generated/ad_longitudinal_300/` 下五项产物

### 2.2 必须保持不变

- `scripts/generate_ad_longitudinal.py`
- `scripts/tests/test_generate_ad_longitudinal.py`
- `data/generated/ad_longitudinal_150/` 下全部五项产物
- `scripts/generate_fatty_liver_longitudinal.py`
- `scripts/extend_fatty_liver_longitudinal_to_300.py`
- `data/generated/longitudinal_150/`
- `data/generated/longitudinal_300/`
- `.claude/settings.local.json`
- 现有 AD CSV 字段、字段顺序、编码和缺失值约定
- R1、R2、组合路径、非规则进展和稳定路径的数值语义

## 3. 方案选择

采用独立扩展器，而不是修改原 150 例生成器。

扩展器只读加载：

- `patients.csv`
- `visits.csv`
- `quality_report.json`
- `extracted_cases.json`
- `DATA_PROVENANCE.md`

脚本复制基线数据后，只生成并追加 P151–P300。该架构具有以下优点：

- 能用哈希和逐行比较证明 P001–P150 未改变；
- 不会因扩大随机循环而改变原 150 例固定序列；
- 基线真实病例锚点与新增分层重组病例边界清晰；
- 扩展生成逻辑、审计、去重和复现验证相互独立；
- 与已运行的脂肪肝 150→300 扩展架构一致。

## 4. 数据规模与精确分布

### 4.1 CDR 分布

| CDR | 基线 P001–P150 | 新增 P151–P300 | 最终 P001–P300 |
|---|---:|---:|---:|
| 0 | 5 | 5 | 10 |
| 0.5 | 10 | 10 | 20 |
| 1 | 55 | 55 | 110 |
| 2 | 45 | 45 | 90 |
| 3 | 35 | 35 | 70 |

### 4.2 队列分布

| 队列 | 基线 | 新增 | 最终 |
|---|---:|---:|---:|
| `ad_progression` | 124 | 124 | 248 |
| `mixed` | 26 | 26 | 52 |

### 4.3 路径分布

| 路径 | 基线 | 新增 | 最终 |
|---|---:|---:|---:|
| `r1` | 25 | 25 | 50 |
| `r2` | 25 | 25 | 50 |
| `r1_r2` | 25 | 25 | 50 |
| `non_rule_progression` | 45 | 45 | 90 |
| `stable` | 30 | 30 | 60 |

队列、CDR 和路径标签分别使用固定种子打散，不能按患者编号形成机械连续分块。阶段与路径必须兼容：stable 表示随访期内 CDR 不上升，可包括 CDR 0/0.5 未进展者，也可包括基线即为 CDR 1 且全程保持 CDR 1 的既存痴呆稳定者；其余四类路径的最终 CDR 必须达到 1、2 或 3。新增 30 例 stable 固定由 CDR 0 的 5 例、CDR 0.5 的 10 例和基线至末次均为 CDR 1 的 15 例组成。

## 5. 分层特征池与新增患者蓝图

新增患者不与某一基线患者一一对应，也不复制任何基线患者的完整患者行和访视序列。扩展器从基线五项产物构建相互独立的特征池。

### 5.1 人口学池

- 按 `cohort_group` 分层抽取年龄和性别；
- 年龄以来源患者为中心应用有限、确定性扰动，并裁剪到 30–100 岁；
- 性别沿用对应人口学来源值；
- 人口学来源与静态标志物、分类理由、轨迹来源应尽量不同。

### 5.2 静态标志池

- APOE 从相同队列的已审核值中抽取，也允许按基线缺失模式保留为空；
- `gene_mutation` 从相同队列的直接阳性基因值或空值经验分布中抽取；
- 不将抗体、阴性检测、VUS、风险多态、蛋白机制或无归属汇总重新解释为阳性基因；
- 静态标志组合只表示合成分层组合，不声称来自同一真实患者。

### 5.3 队列理由池

- `ad_progression` 从已审核的 AD 临床、病理、影像或生物标志物支持理由中抽取；
- `mixed` 从明确竞争病因和模拟病理由中抽取；
- 不得把 mixed 的竞争理由组合进主队列；
- B37 一类边界病例的 C9ORF72 背景理由不得机械传播为所有新患者的主队列判定；只有组合同时保留 AD 表型/生物标志物优先语义时才可使用该理由模板。

### 5.4 来源组件

每名扩展患者至少记录：

- `demographics_patient_id`
- `static_marker_patient_id`
- `classification_reason_patient_id`
- `baseline_biomarker_patient_id`
- `trajectory_patient_id`

这些来源仅写入审计文件，不进入 CSV。若某一来源池只有单个可用值，允许来源重复，但不得复制该来源患者的整套记录。

## 6. 随访时间线与结局

- 每名新增患者生成 3–6 次随访；
- 首末随访跨度为 730–1830 天；
- 日期严格递增且不晚于数据截止日 `2026-08-19`；
- 基线日期和内部间隔使用固定种子生成，间隔不规则；
- 最后一次 CDR 必须等于 `final_stage`；
- `dementia_date` 等于首次 CDR ≥ 1 的访视日期，未达到痴呆者留空；
- `last_followup_date` 等于末次访视日期；
- 新增结局统一审计为 `generated_stage_assignment`；
- 少量确定性失访可保留，但不得直接复制基线患者的失访状态。

## 7. 指标与轨迹生成

### 7.1 CSV 契约

沿用原 AD 生成器：

- `patients.csv` 字段不变；
- `visits.csv` 字段不变；
- UTF-8 无 BOM；
- 缺失值为空字符串；
- CSV 不增加 synthetic、source、provenance 或 path 列。

### 7.2 单次字段

以下字段只在首访记录，后续置空：

- `abeta42`
- `abeta40`
- `abeta_ratio`
- `ptau181`
- `ttau`
- `plasma_ptau217`
- `plasma_nfl`
- `ykl40`
- `strem2`

基线值从相同队列或相近 CDR 层的经验分布/来源患者中抽取并施加有限扰动。Aβ42、Aβ40 和比值应保持数值一致性；所有值必须在原生成器 `SAFETY_BOUNDS` 内。

### 7.3 纵向字段

以下字段每患者至少有 3 个非空值：

- `cdr`
- `mmse`
- `moca`
- `gfap`
- `crp`
- `homocysteine`

认知轨迹由最终 CDR 和路径共同约束：进展患者的 MMSE/MoCA 总体下降、CDR 非递减；stable 患者允许小幅测量波动，但 CDR 必须保持不变。基线 CDR 0/0.5 的 stable 患者不能出现随访中新发痴呆事件；基线已为 CDR 1 的 stable 患者将 `dementia_date` 记为首访日期，但不能在随访期间继续升至 CDR 2/3。

### 7.4 五类路径

- R1：首访 `abeta42 < 540`、`ptau181 > 58`，末 3 次 GFAP 严格上升，且信号早于首次 CDR ≥ 1；
- R2：末 3 次 CRP 严格上升，末次同型半胱氨酸高于基线；
- `r1_r2`：同时满足 R1 和 R2；
- `non_rule_progression`：CDR 进展但明确破坏完整 R1 和 R2；
- `stable`：随访期内 CDR 不上升，并明确避免被数值检测为完整 R1/R2；允许基线即为 CDR 1 的既存痴呆稳定患者。

分配路径必须与原生成器的 `detect_rule_path()` 数值检测结果一致，`assigned_path_mismatches=[]`。

## 8. 多样性与去重

必须检查：

- 新增患者与基线患者之间不存在完整患者行 + 完整访视序列重复；
- 新增患者之间不存在完整重复；
- 人口学、队列、CDR、路径、APOE、基因和来源组件组合具有足够多样性；
- 队列、CDR 和路径的最长连续相同标签长度受测试限制；
- P151–P300 的来源组件不能全部指向同一名基线患者；
- 完整重复检查结果写入 `quality_report.json`。

近似值相似不视为错误；禁止的是完整患者身份和完整纵向序列的机械复制。

## 9. 输出与审计

输出目录 `data/generated/ad_longitudinal_300/` 包含：

- `patients.csv`
- `visits.csv`
- `quality_report.json`
- `extracted_cases.json`
- `DATA_PROVENANCE.md`

### 9.1 quality_report.json

至少包含：

- 基线目录名和基线五项 SHA-256；
- 基线生成器版本、扩展器版本和扩展种子；
- 基线、新增和总体的患者数、访视数、CDR、队列和路径统计；
- `baseline_patient_ids` 与 `generated_extension_patient_ids`；
- 全体路径分配与实际检测结果；
- 新增病例结局来源；
- 新增病例 `source_components`；
- 新增失访 ID；
- 缺失率、数值摘要、访视数与随访跨度摘要；
- 完整重复检查；
- `validation.errors`；
- `assigned_path_mismatches`；
- 允许用途和禁止用途。

### 9.2 extracted_cases.json

- 前 150 条直接继承基线审计记录；
- 后 150 条 `record_type` 为 `stratified_recombination_extension`；
- `source_case_id` 为 `null`；
- 记录队列、分类理由、静态标志、最终 CDR、路径、结局来源和 `source_components`；
- 不伪造病例原文、真实诊断日期或新的 Word 来源。

### 9.3 DATA_PROVENANCE.md

必须明确：

- P001–P150 来自已审核 150 例基线且未修改；
- P151–P300 是固定种子分层重组的合成患者；
- 纵向值和规则信号是为流程验证生成的；
- 不得作为真实世界临床证据、诊疗依据或未经说明的临床研究原始数据；
- 不得声称扩展患者来自新增病例文档；
- R1/R2 仅用于规则检测机制验证，不是独立临床发现。

## 10. 验证要求

### 10.1 基线保护

- 扩展前后 `ad_longitudinal_150/` 五项 SHA-256 完全一致；
- 合并产物 P001–P150 患者行逐字段、逐顺序等于基线；
- 合并产物中 P001–P150 访视行逐字段、逐顺序等于基线。

### 10.2 数据规模与契约

- 患者恰好 300 例，P001–P300 唯一连续；
- 新增恰好 150 例，P151–P300；
- 总体及新增 CDR、队列、路径精确匹配 §4；
- 每名患者 3–6 次访视；
- 每名新增患者跨度 730–1830 天；
- 日期、CDR、事件字段、缺失值和安全范围合法；
- 单次字段仅首访非空；
- 纵向核心字段每患者至少 3 个值；
- `validation.errors=[]`；
- `assigned_path_mismatches=[]`；
- 完整重复组为空。

### 10.3 可复现性

- 相同基线和种子在两个独立临时目录生成；
- 五项产物 SHA-256 逐文件一致；
- 正式目录五项哈希与临时生成一致；
- 相对基线路径与绝对基线路径不影响输出字节。

### 10.4 交叉评审

完成实现与验证后，由另一 Agent 只读检查：

- 基线未变；
- 分布、路径和日期契约；
- R1/R2 数值信号；
- mixed 分类理由和静态标志组合；
- 去重与多样性；
- 审计和 provenance 边界；
- 五项产物可复现性；
- 禁止路径未修改。

## 11. 实现与错误处理

- 扩展器使用标准库，动态只读加载 `generate_ad_longitudinal.py` 的字段、边界、规则检测和格式化函数；
- 若基线数量、字段或哈希契约不符合预期，立即失败；
- 若扩展配置的队列、CDR 或路径计数之和不等于 150，立即失败；
- 若验证错误、路径不一致或完整重复非空，不写正式产物；
- 输出采用临时同级目录生成，验证成功后逐文件替换，避免半成品目录；
- 所有随机操作使用局部 `random.Random`，不污染全局随机状态。

## 12. 完成条件

任务只有在以下条件全部满足后才能交付：

1. 本设计规格经项目所有者审核；
2. 书面实施计划完成并经项目所有者批准；
3. 所有新行为先有失败测试，再实现转绿；
4. 原 150 例生成器和五项基线保持不变；
5. 300 例五项正式产物生成完成；
6. 完整测试、语法检查、工作区检查和双次 SHA-256 验证通过；
7. 独立只读评审无 Critical/Important；
8. 不提交、不推送、不清理工作区，除非项目所有者另行明确授权。
