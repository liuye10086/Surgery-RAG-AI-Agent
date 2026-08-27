# AI 操作者端纵向预测报告优化总领路线图

> 日期：2026-08-25
> 文档类型：总领路线图 / 任务卡目录
> 协作方式：简化流程
> 覆盖疾病：脂肪肝、阿尔茨海默病
> 当前状态：待项目所有者审核
> 核心目标：以当前可运行链路为基础，分阶段解决数据库、标准、训练、推理、证据、报告和展示问题，最终稳定生成内容完整、来源可追溯、结论边界清晰的纵向进展预测报告。

## 1. 文档定位

本文档是 AI 操作者端纵向预测报告优化工作的总领入口，用于回答以下问题：

1. 当前系统已经具备什么，缺少什么；
2. 什么样的报告才算“内容完整”；
3. 哪些问题必须先解决，哪些问题可以后置；
4. 脂肪肝与阿尔茨海默病有哪些共用能力，哪些必须分别处理；
5. 每个问题涉及哪些数据库对象、代码模块、测试和验收条件；
6. 后续应按照什么顺序逐张任务卡实施。

本文档不直接替代单项任务的设计规格和实施计划。每张任务卡正式启动时，仍应根据 `AI_COLLABORATION.md` 选择协作流程；涉及数据库、RAG 核心链路、模型训练契约或跨模块调整时，应单独编写设计文档、登记范围并接受交叉评审。

## 2. 总体目标与非目标

### 2.1 总体目标

系统应支持 AI 操作者完成以下闭环：

```text
创建患者纵向病例
  → 录入和保存多次访视
  → 校验数据质量与可预测性
  → 固化本次预测输入快照
  → 计算纵向观察特征
  → 调用与疾病、时间窗口和特征版本匹配的模型
  → 解析参考标准与患者指标状态
  → 检索真正可比较的纵向参考病例
  → 生成结构化预测结果
  → 生成中文预测报告
  → 保存、追溯、查看和下载 PDF
```

最终报告必须让操作者能够清楚区分：

- 已经观察到的事实；
- 模型计算得到的分数；
- 基于参考标准得到的解释；
- 相似病例提供的支持性证据；
- 当前无法估计的内容；
- 数据和模型的局限性；
- 需要人工复核的事项。

### 2.2 本路线图的非目标

以下内容不作为“先看到完整报告”的前置条件：

- 自动给出诊断或治疗处方；
- 将未经校准的模型分数描述为临床发生概率；
- 在没有合格模型时猜测疾病下一阶段；
- 在没有数值预测模型时生成未来精确指标值；
- 用 LLM 覆盖或改写结构化模型事实；
- 一次性建设完整的临床决策支持系统；
- 将合成病例描述为真实世界临床证据。

## 3. 2026-08-25 当前基线

本节记录路线图制定时的实测状态。后续实施任务前应重新运行只读检查，不应把本节数值当作永久事实。

### 3.1 已具备的能力

- PostgreSQL 数据库结构可用，Alembic revision 与代码 head 均为 `0010`；
- 脂肪肝与阿尔茨海默病均已导入 300 名参考患者的纵向数据；
- AI 操作者可以创建自有纵向病例并保存最多 10 次访视；
- 访视日期会排序、去重，指标名称、数值和单位具有基础校验；
- 系统可以计算首次值、最近值、变化量、变化率、访视序号斜率、上升次数、观测数和缺失情况；
- 系统可以生成结构化纵向预测对象；
- 系统可以保存 `AIReport`、输入快照、预测结果、证据来源和报告正文；
- 前端支持流式接收结构化预测和 Markdown 报告；
- 完成状态的报告可以下载 PDF；
- 缺少模型时系统会显式返回“未估计”，不会伪造风险分数或阶段。

### 3.2 实测数据状态

| 项目 | 脂肪肝 | 阿尔茨海默病 |
|---|---:|---:|
| 参考患者数 | 300 | 300 |
| 纵向访视记录数 | 1354 | 1365 |
| 数据集标识 | `longitudinal_300` | `ad_longitudinal_300` |
| 当前旧版最终结局模型 | 已有 | 已有 |
| 完整报告要求的 365 天结局模型 | 未安装 | 未安装 |
| 阶段模型 | 未安装 | 未安装 |
| 指标趋势模型 artifact | 未安装 | 未安装 |

旧版模型文件为：

```text
backend/app/ml_models/fatty_liver_progression_model.joblib
backend/app/ml_models/ad_progression_model.joblib
```

完整报告模型 registry 当前寻找：

```text
backend/app/ml_models/fatty_liver_longitudinal_outcome_365d.joblib
backend/app/ml_models/ad_longitudinal_outcome_365d.joblib
backend/app/ml_models/{dataset}_trend_{indicator}.joblib
```

两者预测目标和 artifact 契约不同，不能通过简单重命名复用。

### 3.3 当前报告的主要缺口

当前脂肪肝测试报告已经能展示三次访视和七项指标的已观察变化，但存在以下断点：

1. 风险等级与模型分数均为“未估计”；
2. 阶段模型状态为 `not_estimated`；
3. “未来趋势预测”主要由既往观察斜率回退生成，并非已训练趋势模型；
4. 数据库当前标准版本不可用于解析，报告提示“没有已批准的标准版本”；
5. 关键进展信号只是统一的 `progression_signal` 技术枚举；
6. 相似病例按指标名称重叠筛选，不能证明轨迹真正相似；
7. 报告中暴露 `likely_rising`、`direction_only` 等英文内部状态；
8. 缺失情况只有笼统警告，没有数据质量评分和具体缺失说明；
9. 报告未展示模型版本、训练数据构成、预测窗口和 artifact 身份；
10. 标题、分页和章节内容仍偏技术调试输出，不是成熟业务报告。

### 3.4 当前标准数据库异常

路线图制定时，脂肪肝标准存在以下实测状态：

- `ReferenceStandard.current_version_id` 指向一个 `retired` 版本；
- 该版本正式 `StandardRule` 数量为 0；
- 存在 57 条解析候选，但尚未形成可发布规则；
- 因当前版本不是 `approved`，标准解析器会返回“当前疾病没有已批准的标准版本”。

阿尔茨海默病标准的完整性也必须在对应任务中单独审计，不能根据脂肪肝状态推断。

## 4. “内容完整预测报告”的统一定义

### 4.1 最低完整性标准

一份报告只有同时满足以下条件，才可以标记为“内容完整”：

1. **病例身份完整**：疾病、内部患者编号、性别、基线阶段、报告编号和生成时间可追溯；
2. **输入范围完整**：明确列出访视次数、起止日期、观察跨度和本次使用的数据快照；
3. **数据质量完整**：显示核心指标覆盖、缺失指标、单位冲突、异常值和可预测性判断；
4. **观察事实完整**：每项关键指标至少显示首次值、最近值、绝对变化、百分比变化、时间化趋势和参考状态；
5. **模型结果完整**：模型可用时显示预测窗口、风险等级、模型分数、校准状态和模型版本；
6. **不可估计说明完整**：模型不可用或数据不足时说明具体原因，不用空值或技术枚举代替解释；
7. **疾病阶段完整**：阶段模型可用时显示候选阶段；不可用时不输出阶段猜测；
8. **关键进展信号完整**：每条信号有方向、强度、依据、参考状态和关注级别；
9. **证据来源完整**：参考标准、相似病例、真实/合成来源和适用性警告可追溯；
10. **局限性完整**：明确样本量、合成数据、未校准分数、缺失数据和适用范围；
11. **人工复核建议完整**：建议必须来自结构化缺口和风险信号，不得自由生成治疗结论；
12. **交付完整**：报告能够保存、历史查看、权限隔离并下载排版正常的 PDF。

### 4.2 完整不等于所有模型都必须存在

阶段模型或数值趋势模型不是第一版完整报告的强制条件。完整性要求的是：

- 已有能力必须正确展示；
- 缺失能力必须给出明确原因；
- 报告不能把观察趋势伪装成未来模型预测；
- 报告不能因为某个可选模型缺失而让其他章节退化为空白。

因此，P0 里程碑可以暂不提供阶段预测，但必须提供可用的固定窗口结局风险、参考标准、关键变化解释和完整的不可估计说明。

## 5. 两种疾病的统一边界与差异

### 5.1 共用能力

以下能力应使用统一契约和共用模块：

- 操作者病例与访视存储；
- 输入快照；
- 日期、单位、有限数值和重复指标校验；
- 历史前缀构造；
- 患者级训练/验证分组；
- 模型 artifact 元数据；
- 模型 registry；
- 数据质量评分；
- 观察特征接口；
- 标准规则解析接口；
- 相似病例返回结构；
- 结构化预测 schema；
- 报告章节和 PDF 生成流程；
- 权限、审计和报告追溯。

### 5.2 脂肪肝专属内容

- 阶段顺序：`fatty_liver → cirrhosis → hcc`；
- 结局事件：肝硬化日期、肝癌日期；
- 核心指标：ALT、AST、GGT、TBIL、ALB、PLT、AFP，扩展指标包括 HbA1c、BMI、腰围；
- 关键轨迹示例：肝酶上升、白蛋白下降、血小板下降、AFP 上升、代谢指标恶化；
- 需要识别病毒性肝炎、酒精性肝病、药物性肝损伤等竞争病因或排除条件；
- 报告必须避免把单次肝酶异常直接解释为肝硬化或肝癌。

### 5.3 阿尔茨海默病专属内容

- 阶段顺序：`normal → mci → dementia`；
- 结局事件：痴呆日期或等价的明确进展日期；
- 核心指标：MMSE、MoCA、CDR、plasma NfL、plasma p-tau217，可扩展 Aβ42/Aβ40、GFAP、p-tau181 等；
- 认知量表下降方向与多数生化指标升高方向的语义不同，不能共用单一“数值升高即恶化”规则；
- CDR 参与结局标签时不得同时作为泄漏特征直接喂入对应结局模型；
- 标准适用性可能依赖检测平台、分析方法、年龄、教育水平和人群；
- 报告必须区分认知量表、血液生物标志物和疾病阶段证据。

## 6. 总体实施原则

### 6.1 先完整，再可信，后增强，最后美化

- **P0 报告完整**：打通标准、固定窗口结局模型、关键解释和报告主链路；
- **P1 结果可信**：提升数据质量、相似病例、时间特征、版本追溯和验证质量；
- **P2 能力增强**：阶段模型、趋势模型、校准和更丰富临床上下文；
- **P3 展示优化**：中文化、PDF 结构、图表和交互体验。

### 6.2 结构化结果优先

所有报告事实必须先进入结构化 schema，再由模板渲染。模板或 LLM 不得自行产生：

- 模型未输出的概率；
- 模型未输出的下一阶段；
- 不存在的未来指标数值；
- 未经过标准解析的正常/异常结论；
- 未查询到的相似病例结局；
- 治疗和用药建议。

### 6.3 Artifact 必须与契约匹配

每个模型必须同时校验：

- 数据集；
- 疾病；
- 预测目标；
- 预测窗口；
- 特征名称和顺序；
- 特征版本；
- sklearn 版本；
- 模型版本；
- 训练时间；
- 文件哈希；
- 校准状态。

不匹配时必须拒绝加载，不能静默回退到旧模型。

### 6.4 真实病例和合成病例始终分层

训练、验证、相似病例和报告证据都必须明确：

- 真实或原始来源病例；
- 规则构造病例；
- 重组合成病例；
- 各自在训练集和验证集中的数量；
- 仅真实病例评估结果；
- 全量病例评估结果。

## 7. 任务依赖与推荐顺序

```text
P0-01 基线审计与完整报告契约
 ├─→ P0-02 标准版本和规则可用化
 ├─→ P0-03 固定窗口结局训练数据集
 │     └─→ P0-04 结局模型训练、评估和 artifact
 │            └─→ P0-05 推理 registry 与模型状态
 ├─→ P0-06 关键进展信号解释器
 └─→ P0-07 完整报告模板和端到端验收

P1-01 数据质量评分
 ├─→ P1-02 真实时间特征
 ├─→ P1-03 患者级纵向相似病例
 └─→ P1-04 模型、规则和报告可追溯性
        └─→ P1-05 双疾病验证基线

P2-01 阶段模型
P2-02 下一次访视趋势方向模型
P2-03 模型校准
P2-04 操作者病例临床上下文扩展

P3-01 中文展示词典
P3-02 报告信息设计与 PDF 分页
P3-03 趋势图和证据可视化
P3-04 前端生成状态与故障解释
```

## 8. P0：先生成内容完整的预测报告

### P0-01：建立双疾病基线审计与完整报告契约

**状态**：`completed`

**Task-ID**：`longitudinal-readiness-001`

**设计文档**：`docs/superpowers/specs/2026-08-25-longitudinal-readiness-design.md`

**实施计划**：`docs/superpowers/plans/2026-08-25-longitudinal-readiness.md`

**验证记录**：`python scripts/check_longitudinal_readiness.py` 已成功输出双疾病只读 JSON。当前脂肪肝与 AD 的业务状态均为 `blocked`，命令退出码为 `1`；缺口明确映射到 P0-02、P0-04、P0-07 及可选增强任务。新增测试、相关纵向回归与数据库基线检查通过。

**现状**

系统已有多份设计和测试，但缺少一个可自动运行的双疾病报告就绪检查。模型、标准和数据缺失往往要等到生成报告后才暴露。

**目标**

建立只读就绪检查和完整报告契约，明确每种疾病当前是 `ready`、`degraded` 还是 `blocked`。

**范围**

- 数据库中的疾病、参考患者、访视、事件日期、标准版本、标准规则；
- 模型目录中的 outcome、stage、trend artifact；
- 模型元数据与 registry 契约；
- 报告 schema 必填字段；
- 双疾病最小测试病例。

**主要涉及文件/对象**

- `scripts/check_model_artifacts.py`
- 新增纵向报告就绪检查脚本或扩展现有基线脚本
- `backend/app/services/longitudinal_model_registry.py`
- `backend/app/schemas/longitudinal_report.py`
- `backend/tests/test_longitudinal_prediction_contract.py`
- `case_records`
- `reference_standards`
- `reference_standard_versions`
- `standard_rules`
- `ai_reports`

**实施要点**

1. 为脂肪肝和 AD 分别统计患者数、可用前缀数、阳性/阴性/未知标签数；
2. 检查每种疾病是否存在当前 approved 标准及可计算规则；
3. 检查模型文件、元数据、哈希和加载结果；
4. 输出结构化 JSON，不在检查脚本中修改数据库；
5. 定义完整报告 schema 的必填章节和状态语义；
6. 将模型缺失、标准缺失和输入不足区分为不同状态码。

**测试与验证**

- 单测覆盖模型缺失、元数据不匹配、无 approved 标准、无可估计标签；
- 使用当前本地数据库执行只读检查；
- 检查结果必须分别列出脂肪肝与 AD，不能合并成一个总状态。

**完成标准**

- 一条命令可以说明两种疾病距离完整报告还缺什么；
- 检查脚本不写入数据库；
- 失败原因可以直接映射到后续任务卡；
- 报告 schema 不再依赖阅读 Markdown 才能判断是否完整。

**前置依赖**：无。
**主要风险**：把运行环境缺失与业务数据缺失混为一谈。
**建议任务编号**：`longitudinal-readiness-001`。

### P0-02：修复并发布双疾病参考标准

**状态**：`completed`

**Task-ID**：`longitudinal-standards-001`

**设计文档**：`docs/superpowers/specs/2026-08-25-longitudinal-standards-design.md`

**实施计划**：`docs/superpowers/plans/2026-08-25-longitudinal-standards.md`
**验证记录**：数据库 revision/head 已升级为 `0012`。脂肪肝标准版本 `id=3` 已成为 current approved，包含 11 条正式规则（10 calculable、1 evidence-only）和 10 条当前投影；AD 标准版本 `id=4` 已成为 current approved，包含 8 条 evidence-only 正式规则、0 calculable 和 0 投影。canonical indicator 的疾病专属异常方向已持久化；两个版本的 135 条解析候选仍全部 pending，0 条 materialized。`python scripts/check_longitudinal_readiness.py` 已不再报告 `approved_standard_missing` 或 `calculable_standard_rules_missing`，AD 明确报告 `evidence_only_standard` 限制，P0-04/P0-07 缺口保持可见。专项与相关回归共 206 项通过。

**现状**

脂肪肝当前版本指向 retired 状态且没有正式规则；AD 标准需要独立审计。报告无法给出可靠的参考范围、异常状态和标准版本。

**目标**

为脂肪肝和 AD 分别建立至少一个可用的 approved 标准版本，并确保当前版本只指向 approved 版本。

**范围**

- 标准文档、版本、解析候选、规则审核、发布和投影；
- 指标 canonical key 和 aliases；
- 单位、边界包含性、性别和其他适用条件；
- calculable 与 evidence-only 规则区分；
- 当前版本生命周期约束。

**主要涉及文件/对象**

- `backend/app/services/standard_parser.py`
- `backend/app/services/standard_validation.py`
- `backend/app/services/standard_lifecycle.py`
- `backend/app/services/standard_resolver.py`
- `backend/app/services/longitudinal_evidence.py`
- `backend/app/api/admin_standards.py`
- `backend/app/api/admin_standard_documents.py`
- `reference_standards`
- `reference_standard_versions`
- `standard_indicators`
- `standard_rules`
- `standard_rule_conditions`
- `reference_ranges`

**疾病差异**

- 脂肪肝优先覆盖 ALT、AST、GGT、TBIL、ALB、PLT、AFP、HbA1c、BMI、腰围；
- AD 优先覆盖 MMSE、MoCA、CDR、NfL、p-tau217、Aβ42/Aβ40，并明确平台、方法、年龄或教育等适用性；
- AD 量表类规则与生化指标规则不得使用同一种异常方向解释。

**实施要点**

1. 对每种疾病列出报告必须覆盖的 canonical indicators；
2. 审核解析候选，将可用候选转成正式规则；
3. 对模糊或缺少适用条件的内容标记为 evidence-only；
4. 验证规则冲突、单位、边界和适用性；
5. 经 review 后发布 approved 版本；
6. 只在发布事务成功后更新 current version；
7. 防止 current version 指向 retired/draft/review；
8. 为每条报告引用保留版本 ID、规则 ID 和适用性哈希。

**测试与验证**

- 生命周期状态转换测试；
- current version 一致性测试；
- 双疾病核心指标解析测试；
- 性别、平台或条件缺失时降级为 evidence-only 的测试；
- 报告端能够输出标准版本和参考范围；
- 数据库发布事务回滚测试。

**完成标准**

- 脂肪肝和 AD 均有当前 approved 标准；
- 报告核心指标可以命中 canonical rule 或得到明确的未匹配说明；
- 不再出现 current version 指向 retired 版本；
- 报告可以展示规则来源和适用性，而不仅是一个数值范围。

**前置依赖**：P0-01。
**主要风险**：把文档中的证据性内容错误转换为机器可计算阈值。
**建议任务编号**：`longitudinal-standards-001`。

### P0-03：构建无未来泄漏的固定窗口训练数据集

**状态**：`completed`

**Task-ID**：`longitudinal-prefix-dataset-001`

**设计文档**：`docs/superpowers/specs/2026-08-26-fixed-window-longitudinal-dataset-design.md`

**实施计划**：`docs/superpowers/plans/2026-08-26-fixed-window-longitudinal-dataset.md`

**验证记录**：`python scripts/build_longitudinal_dataset.py` 已以只读方式连续两次生成完全一致的双疾病匿名审计摘要。脂肪肝真实患者 150 名、692 次访视、392 个候选前缀，其中 59 个阳性、141 个阴性、167 个观察不足、25 个不适用，正式可训练前缀 200 个，涉及 106 名患者；AD 真实患者 150 名、672 次访视、372 个候选前缀，其中 56 个阳性、109 个阴性、23 个观察不足、184 个不适用，正式可训练前缀 165 个，涉及 88 名患者。显式临时导出验证了稳定 JSONL、manifest、SHA-256、不覆盖、真实/合成隔离和禁止字段防护；正式训练文件中合成样本为 0，模型特征中禁止字段为 0。P0-03 聚焦测试、旧训练脚本回归、readiness 回归和相关纵向测试通过；未训练模型、未写数据库、未生成生产 artifact。

**现状**

旧模型使用患者完整轨迹和最终 `confirmed` 标签，不能回答“从当前时间点开始未来 365 天是否进展”。现有前缀训练辅助函数尚未形成完整数据库到训练集的 CLI 闭环。

**目标**

为脂肪肝和 AD 分别构建以历史前缀为输入、未来 365 天事件为标签的可审计训练数据集。

**范围**

- 从 `case_records` 按 `(source_dataset, patient_label)` 重建患者；
- 读取访视日期、最终阶段和事件日期；
- 生成每个患者的历史前缀；
- 只使用 `as_of` 当日及之前访视；
- 生成阳性、阴性和未知标签；
- 按患者保留 group ID；
- 输出真实/合成来源和训练统计。

**主要涉及文件/对象**

- `scripts/train_longitudinal_models.py`
- `scripts/train_progression_model.py`
- `backend/app/services/disease_progression.py`
- `backend/app/services/longitudinal_features.py`
- `scripts/tests/test_train_longitudinal_models.py`
- `case_records.metadata`

**疾病差异**

- 脂肪肝事件：`cirrhosis_date`、`hcc_date`；
- AD 事件：`dementia_date` 或经明确确认的等价事件字段；
- 脂肪肝稳定终点可作为阴性，但已进展且缺少事件日期的前缀不得伪装为阴性；
- AD 如果最终 CDR 达到进展阈值但缺少进展日期，同样应标为时间窗口未知；
- 任何用于生成标签的字段不得作为同期模型特征泄漏。

**实施要点**

1. 完成训练数据数据库加载函数；
2. 明确最少访视数和 365 天窗口；
3. 对每个前缀记录 `patient_id`、`as_of`、来源和标签理由；
4. 剔除对应目标下的未知标签，但保留统计；
5. 输出患者数、前缀数、阳性、阴性、未知、真实/合成比例；
6. 增加未来访视泄漏断言；
7. 对特征中可能直接编码结局的字段建立禁止列表。

**测试与验证**

- 同一前缀绝不包含 `as_of` 之后访视；
- 事件恰好落在窗口边界时的标签测试；
- 缺少事件日期时返回未知而非阴性；
- 同一患者所有前缀保留同一 group；
- AD 的 CDR 泄漏防护测试；
- 双疾病当前数据库统计可重复生成。

**完成标准**

- 一条 CLI 命令可以生成每种疾病的训练统计；
- 数据集标签含义是明确的未来 365 天结局；
- 未知标签数量可见；
- 训练数据可审计且没有未来访视泄漏。

**前置依赖**：P0-01。
**主要风险**：事件日期缺失导致可估计样本过少。
**建议任务编号**：`longitudinal-prefix-dataset-001`。

### P0-04：训练、评估并产出双疾病 365 天结局模型

**状态**：`completed`

**Task-ID**：`longitudinal-outcome-model-001`

**设计文档**：`docs/superpowers/specs/2026-08-26-longitudinal-outcome-model-design.md`

**实施计划**：`docs/superpowers/plans/2026-08-26-longitudinal-outcome-model.md`

**验证记录**：已实现 P0-03 JSONL/manifest 严格读取、三任务筛选、患者级划分、特征与泄漏审计、候选模型和安全 CLI。专项及相关回归共 148 项通过（仅 1 条既有 Pydantic 弃用警告）。真实 P0-03 数据审计统计为：脂肪肝未肝硬化 147 个可训练前缀/86 名患者/50 阳性/97 阴性，脂肪肝已肝硬化 53 个可训练前缀/53 名患者/9 阳性/44 阴性，AD 未痴呆 165 个可训练前缀/88 名患者/56 阳性/109 阴性。临时目录成功生成三个任务级 `candidate` artifact 及 metadata，并通过 SHA-256 清单检查；默认 CLI 只读、不训练、不更新 registry。生产 `backend/app/ml_models/` 未修改，旧脚本和旧 artifact 未清除。完整项目回归在正确 `PYTHONPATH=backend;.` 下发现 1 条既有 `test_cleanup_contracts.py` 关于 `.superpowers/sdd` 的失败，与 P0-04 变更无关；未删除该目录或修改无关清理范围。未生成生产模型、未写业务数据库、未自动启用 registry，未声称临床有效性。

**现状**

完整报告缺少 registry 所要求的 outcome artifact；已有旧模型的高 AUC 主要反映完整轨迹和构造数据可分性，不能直接沿用。

**目标**

基于 P0-03 数据集训练脂肪肝和 AD 的 365 天结局模型，保存与线上契约一致的模型和元数据。

**范围**

- `SimpleImputer` 和候选分类模型；
- 患者级交叉验证；
- 全量和真实病例子集评估；
- 类别分布和 fold 可估计性；
- artifact、metadata 和 hash；
- 人工启用检查点。

**主要涉及文件/对象**

- `scripts/train_longitudinal_models.py`
- `backend/app/ml_models/`
- `scripts/tests/test_train_longitudinal_models.py`
- `scripts/check_model_artifacts.py`
- `backend/requirements.txt`

**实施要点**

1. 以现有 Gradient Boosting 作为基线，不在首轮引入复杂深度模型；
2. 交叉验证必须按患者分组；
3. fold 缺少任一类别时不得虚报 AUC；
4. 分别报告全量病例和真实病例子集表现；
5. 保存特征顺序、患者数、前缀数、阳性数、合成比例、fold 指标；
6. 元数据明确 `calibration_status=not_calibrated`；
7. 写入模型版本、训练数据版本、sklearn 版本、训练时间和文件哈希；
8. 训练脚本不自动启用模型，必须先人工审阅指标和数据分布。

**测试与验证**

- patient GroupKFold 无交叉；
- artifact 命名与 registry 完全一致；
- 元数据缺字段时 artifact 检查失败；
- 使用临时目录训练和加载 smoke test；
- 报告全量与真实子集指标；
- 对可能异常接近满分的指标输出显著警告。

**完成标准**

- 两种疾病均生成 `*_longitudinal_outcome_365d.joblib` 和对应元数据；
- 模型可以通过 artifact 检查；
- 项目所有者已查看训练统计和交叉验证结果；
- 不以固定 AUC 阈值自动宣称临床可用；
- 模型限制能够进入报告。

**前置依赖**：P0-03。
**主要风险**：可估计前缀不足、合成规则造成虚高、真实子集表现不稳定。
**建议任务编号**：`longitudinal-outcome-model-001`。

### P0-05：统一模型 registry、状态和推理契约

**状态**：`completed`

**Task-ID**：`longitudinal-registry-001`

**设计文档**：`docs/superpowers/specs/2026-08-26-longitudinal-registry-design.md`

**实施计划**：`docs/superpowers/plans/2026-08-26-longitudinal-registry.md`

**验证记录**：已建立共享任务级 registry、严格 artifact metadata/hash 校验、candidate → reviewed → enabled 的不可变临时发布链、运行时 `available | missing | incompatible | disabled` 状态和 `longitudinal_prediction.v2` 推理契约。正式任务固定为 `fatty_liver.pre_cirrhosis_to_progression`、`fatty_liver.cirrhosis_to_hcc` 和 `ad.pre_dementia_to_dementia`；脂肪肝基线阶段按已确认阶段路由，`疑似肝硬化` 返回 `disabled / baseline_stage_uncertain`，不猜任务、不输出风险分数，同时保留 3 次访视观察事实。线上 age 保持缺失，不从标签、notes 或指标推断。

P0-05 专项测试通过：`79 passed`。纵向推理、报告、readiness、PDF、安全回归通过：`80 passed, 1 warning`。P0-03/P0-04 数据、训练、评估和审计回归通过：`135 passed, 1 warning`。旧训练/progression engine/API 回归通过：`22 passed, 1 warning`；旧前端 progression 契约：`3 passed`。前端全部 Node 契约：`19 passed`；`vue-tsc` 与 Vite build 成功（仅既有 Rollup 注释和大 chunk 警告）。

真实双疾病临时 smoke 目录为 `.tmp/p005-verification-20260826-155121`，证据包括 `dataset-build.json`、`training.json`、`candidate-checks.json`、`release-smoke.json`、`registry-check.json`、`inference-smoke.json`。三个任务均完成 candidate 检查、临时 review、临时 enable、registry load 和真实 fixed-window inference；每个可用结果均记录 task、model version、artifact SHA-256、365 天 target、feature version、`model_score` 语义和未校准状态。`backend/app/ml_models/` 前后 SHA-256 完全一致；限定到 checker/release/registry/inference 对外证据 JSON 的敏感信息扫描无匹配。静态 artifact 检查未调用 `predict`/`predict_proba`。

完整 `python -m pytest -q` 按要求执行；首个失败是既有 `backend/tests/test_cleanup_contracts.py::CleanupContractTests::test_removed_files_do_not_exist`，原因是项目要求清理但当前仍存在 `.superpowers/sdd`，未删除目录掩盖问题。为取得可复核的后续证据，使用 `--maxfail=1` 重跑时在 `research/tests/test_attribution_shap.py::test_lag_ablation_signal_group_drop_positive` 发现既有研究基线随机/数据敏感断言失败（本次 AFP `auc_drop=-0.006542...`）。`backend + scripts` 广泛回归另有既有外部 DOCX 缺失、跨测试 SQLAlchemy metadata 重复定义以及同一 cleanup 失败；P0-05 专项和产品相关分层回归均已通过。上述既有失败未修改、未删除相关目录或数据。

**现状**

快速预测与完整报告使用不同模型路径；完整报告 registry 只检查文件是否存在，没有完整校验数据集、目标、窗口、特征和版本。

**目标**

建立唯一、严格、可解释的纵向模型加载和状态契约，使报告能够准确说明模型是否加载、为什么没有加载，以及使用了哪个版本。

**范围**

- outcome/stage/trend registry；
- artifact metadata 验证；
- 模型加载错误分类；
- 结构化 model status；
- 旧快速预测接口的兼容或退役决策。

**主要涉及文件/对象**

- `backend/app/services/longitudinal_model_registry.py`
- `backend/app/services/longitudinal_prediction.py`
- `backend/app/services/progression_engine.py`
- `backend/app/schemas/longitudinal_report.py`
- `backend/app/api/operator.py`
- `backend/tests/test_longitudinal_model_registry.py`
- `backend/tests/test_longitudinal_prediction_contract.py`

**实施要点**

1. registry 校验 dataset、target、horizon、feature version 和 hash；
2. 定义 `available`、`missing`、`incompatible`、`disabled` 状态；
3. 在结构化结果中保存模型 ID、版本和加载状态；
4. outcome 模型不可用时保留观察、标准和证据章节；
5. 不再用一个笼统 warning 表示所有模型问题；
6. 评估旧 `/progression-predictions` 是否迁移到新 registry；
7. 迁移前保留兼容性，不通过重命名复用旧 artifact。

**测试与验证**

- 模型缺失、元数据缺失、特征顺序不匹配、错误疾病、错误窗口测试；
- outcome 可用但 stage 缺失时的部分可用测试；
- 双疾病各一次端到端加载；
- 旧接口回归测试。

**完成标准**

- 报告可以显示“365 天结局模型已加载，阶段模型未启用”等准确状态；
- 不兼容模型不能进入推理；
- 报告可追溯到确切模型版本；
- 缺少可选模型不会让整份报告失败。

**前置依赖**：P0-04。
**主要风险**：同时维护旧接口和新报告接口造成语义漂移。
**建议任务编号**：`longitudinal-registry-001`。

### P0-06：建立双疾病关键进展信号解释器

**状态**：`completed`

**Task-ID**：`longitudinal-signals-001`

**设计文档**：`docs/superpowers/specs/2026-08-27-longitudinal-signal-interpreter-design.md`

**实施计划**：`docs/superpowers/plans/2026-08-27-longitudinal-signal-interpreter.md`

**验证记录**：已新增确定性的双疾病信号解释器和严格 `longitudinal_signal_interpretation.v1` schema，并只挂载到 `longitudinal_prediction.v2`；历史 v1 和旧 progression API 保持不变。脂肪肝显式支持 ALT、AST、GGT、TBIL、ALB、HbA1c、腰围、PLT、AFP、BMI，AD 显式支持 MMSE、MoCA、CDR、NfL、p-tau217、Aβ42/Aβ40；p-tau181 不与 p-tau217 合并。所有指标统一要求至少 3 次有效数值观察，4 次以上使用全部有效观察，不截取最近三次，也不为凑数补足三条信号。CDR 只作为阶段相关观察；个体模型贡献始终为 `null`，解释器不调用模型预测。

正式范围判断只消费 approved resolver 快照。脂肪肝版本 3 的 ALT 男性规则 1（9–50 U/L）、ALT 女性规则 2（7–40 U/L）和 ALB 规则 7（≥35 g/L）可计算；AD 版本 4 的 MMSE 规则 28、MoCA 规则 29、CDR 规则 30、NfL 规则 31、p-tau217 规则 32 均按证据状态处理，不猜测数值阈值。缺单位、单位冲突、观察单位不受支持以及正式标准单位不匹配均安全降级，不输出 above/below；标准单位不匹配回归按 TDD 先得到预期失败，再修复为 `unsupported_unit`。

P0-06 解释器测试：`15 passed`。解释器、特征、证据、预测、报告、端到端和安全专项：`74 passed, 1 warning`。P0-02/P0-03/P0-04/P0-05、旧 progression engine/API 分层回归：`212 passed, 1 warning`；旧前端 progression 合约：`3 passed`。真实 smoke 位于 `.tmp/p006-20260827-084139/fatty-liver-signal-smoke.json` 和 `.tmp/p006-20260827-084139/ad-signal-smoke.json`：脂肪肝输出 4 次 ALT/ALB/PLT 观察，其中 ALT、ALB 结合正式范围为 priority，PLT 因无可用范围为 attention；AD 输出 3 次 MMSE/MoCA 方向信号，只有 1 次的 NfL/p-tau217 按 `insufficient_observations` 省略。两个文件的数据库 URL、密码、traceback、本机路径、患者编号和旧 `progression_signal` 精确字段扫描均无匹配。

`git diff --check` 退出码为 0（仅 Windows LF/CRLF 提示）；生产模型、数据库 schema/migration、前端均无 diff。生产 artifact SHA-256 保持为：脂肪肝模型 `baf711866e22f4a03cfcfc2a047d47a281f856100d269c84ed4dc13dfba63a47`、metadata `935ff03d81fa970a97b4de877cb51fb0b3a16567b5a39f33139d7980b95f6c30`；AD 模型 `a645d369631c0dcced6b402cfb61a4bb0afe7e7955fd73f6f88cc722a06cf803`、metadata `7c56d974ed1fa9e42a0953addee7c8c45118879fe779c4927aca7d3e5c04e3e8`。

完整 `python -m pytest -q --maxfail=1` 已执行，结果为 `1 failed, 74 passed, 2 subtests passed, 10 warnings`；首个失败仍是既有 `backend/tests/test_cleanup_contracts.py::CleanupContractTests::test_removed_files_do_not_exist`，原因是 `.superpowers/sdd` 存在，与 P0-06 改动无关。未删除该目录掩盖失败，未声称全仓测试全部通过。

**现状**

所有指标统一输出 `progression_signal`，没有方向、阈值、强度、原因和疾病差异。

**目标**

把观察特征、标准规则和模型输入转换为可审计的关键进展信号，同时明确区分事实、规则解释和模型重要性。

**范围**

- 指标名称标准化和中文名称；
- 观察变化；
- 参考范围状态；
- 疾病方向语义；
- 信号关注等级；
- 信号理由；
- 是否进入模型；
- 模型贡献缺失时的明确状态。

**主要涉及文件/对象**

- 建议新增 `backend/app/services/longitudinal_signal_interpreter.py`
- `backend/app/services/longitudinal_features.py`
- `backend/app/services/longitudinal_evidence.py`
- `backend/app/services/longitudinal_prediction.py`
- `backend/app/schemas/longitudinal_report.py`
- 新增对应单元测试

**疾病差异**

- 脂肪肝：ALT/AST/GGT/TBIL/AFP 上升与 ALB/PLT 下降可能是关注方向，但必须结合幅度和标准；
- AD：MMSE/MoCA 下降与 NfL/p-tau 等升高可能是关注方向；CDR 的角色取决于目标，可能只用于阶段事实而不能用于结局模型；
- “数值上升”不能作为跨疾病统一的恶化定义。

**建议输出结构**

```json
{
  "indicator": "alt",
  "display_name": "谷丙转氨酶",
  "unit": "U/L",
  "observed_direction": "rising",
  "absolute_change": 45.0,
  "relative_change": 1.4516,
  "reference_status": "above_range",
  "attention_level": "high",
  "reason_codes": ["persistent_rise", "latest_above_reference"],
  "used_by_outcome_model": true,
  "model_contribution": null
}
```

**实施要点**

1. 将信号解释和模型预测解耦；
2. 只基于可追溯数据生成 reason code；
3. 没有标准时只描述变化，不宣称异常；
4. 没有特征贡献方法时不编造模型贡献；
5. 给每种疾病维护显式方向配置；
6. 将技术枚举保留在结构化结果，报告使用中文映射。

**测试与验证**

- 脂肪肝 ALT 上升、ALB 下降、PLT 下降解释；
- AD MMSE 下降和 p-tau217 上升解释；
- 无参考标准时不输出 above/below；
- 缺失和单位冲突时降级；
- 同一输入重复计算结果一致。

**完成标准**

- 每个指标至少有 3 次有效观察才可形成信号；报告展示全部实际达标信号，不为凑数补足三条，没有信号时明确说明未达到关注条件；
- 不再直接展示 `progression_signal`；
- 每条信号能够追溯到观察数据和标准规则；
- 脂肪肝与 AD 的方向解释分别正确。

**前置依赖**：P0-02；可与 P0-03/P0-04 并行设计。
**主要风险**：把启发式规则误表述为模型结论。
**建议任务编号**：`longitudinal-signals-001`。

### P0-07：重构完整报告模板并完成双疾病端到端验收

**实际状态（2026-08-27）**：`completed`

- 已完成脂肪肝和 AD 三次访视的 11 节完整报告、独立桌面阅读页、历史只读打开和同正文 PDF。
- 页面、历史详情和 PDF 均读取生成时保存的 `AIReport.content`；匿名真实数据库验收确认病例后续修改不改变旧报告正文哈希。
- 观察事实、模型状态和标准解释已分开；P0-06 `progression_signals` 仍是唯一信号来源，模板层不重新判断信号。
- 专项后端回归：326 passed，5 个既有框架弃用警告；前端 Node 合约：23 passed；`npm run build` 通过。
- 脂肪肝和 AD PDF 均为 3 页，已用 Poppler 逐页渲染检查中文、图表、表格、分页、页眉页脚、页码、空白页、截断和重叠。
- 匿名验收证据：`output/evidence/p0-07/README.md`；最终 PDF：`output/pdf/p0-07-fatty-liver-longitudinal-report.pdf`、`output/pdf/p0-07-ad-longitudinal-report.pdf`。
- 全量 `pytest` 未完成：正确设置 `PYTHONPATH=backend` 后运行到约 64%，出现 2 个失败标记但尚未输出失败详情；因全量研究测试预计耗时超过两小时，按项目方要求中止。本项不声称全量通过。
- 项目方确认当前只做电脑端，移动端不属于 P0-07 验收和上线条件。
- 未修改或上线新的生产模型；阶段模型和趋势模型缺失时继续按普通中文降级说明。

**现状**

报告章节齐全但核心摘要为空、技术状态未翻译、观察趋势和预测混杂，且缺少数据质量、模型身份和可操作的人工复核提示。

**目标**

生成脂肪肝和 AD 各一份内容完整的报告样例，并确保页面、历史记录和 PDF 内容一致。

**范围**

- 结构化结果到 Markdown 的确定性渲染；
- 报告标题；
- 摘要卡片；
- 数据质量；
- 观察变化；
- 固定窗口风险；
- 阶段和趋势的可用性状态；
- 关键进展信号；
- 标准和相似病例；
- 局限性和人工复核；
- 保存、历史、PDF。

**主要涉及文件/对象**

- `backend/app/services/longitudinal_report_generator.py`
- `backend/app/templates/report_pdf.html`
- `backend/app/services/pdf_generator.py`
- `backend/app/schemas/longitudinal_report.py`
- `frontend/src/components/LongitudinalPredictionSummary.vue`
- `frontend/src/views/OperatorView.vue`
- `frontend/src/api/operator.ts`
- `frontend/src/stores/operator.ts`
- `backend/tests/test_longitudinal_report_generator.py`
- `backend/tests/test_longitudinal_pdf_contract.py`
- `backend/tests/test_longitudinal_end_to_end.py`

**推荐报告结构**

1. 报告摘要；
2. 病例与预测范围；
3. 数据质量与适用性；
4. 已观察到的纵向变化；
5. 未来 365 天进展风险；
6. 疾病阶段与下一次随访趋势；
7. 关键进展信号；
8. 参考标准和相似病例；
9. 不确定性与局限性；
10. 人工复核重点；
11. 模型和数据技术附录。

**实施要点**

1. 摘要优先回答数据是否可分析、模型是否可用、风险是什么；
2. 将观察事实与模型预测分成不同章节；
3. 模型缺失时写明缺失类型和受影响章节；
4. 标准缺失时不展示伪参考范围；
5. 所有内部技术状态转换为中文；
6. 标题避免重复拼接“纵向进展”；
7. 报告内容持久化后再生成 PDF；
8. PDF 与页面必须使用同一份持久化 Markdown；
9. 关键摘要和关键表格避免跨页断开。

**测试与验证**

- 脂肪肝三次访视完整报告；
- AD 三次访视完整报告；
- outcome 可用、stage 不可用的部分可用报告；
- 标准缺失时的降级报告；
- 生成中断、模型异常和 PDF 下载权限测试；
- PDF 逐页渲染检查中文、分页、表格和页脚；
- 历史报告重新打开后内容不随病例修改而变化。

**完成标准**

- 脂肪肝与 AD 各产生一份符合第 4 节定义的完整报告；
- 报告摘要不再出现无解释的“未估计”；
- 页面、数据库 content 和 PDF 内容一致；
- 所有重要结论都能追溯到输入、模型或标准；
- 存量纵向报告接口和权限测试通过。

**前置依赖**：P0-02、P0-05、P0-06。
**主要风险**：模板层承担过多业务判断，造成页面和 PDF 逻辑分叉。
**建议任务编号**：`longitudinal-complete-report-001`。

## 9. P1：提高结果可信度与可审计性

### P1-01：建立数据质量评分和可预测性判定

**现状**

系统只提示“部分指标存在缺失”，没有说明缺哪些、缺失比例、单位问题和数据是否足以支持某个模型。

**目标**

在模型调用前生成结构化质量报告，并按 outcome、stage、trend 分别判断是否可估计。

**主要内容**

- 核心指标覆盖率；
- 每项指标观测数和缺失率；
- 访视次数和跨度；
- 访视间隔；
- 单位一致性；
- 重复指标；
- 非有限值和极端值；
- 最近一次访视新鲜度；
- 各模型的 minimum requirements。

**主要涉及文件**

- 建议新增 `backend/app/services/longitudinal_data_quality.py`
- `backend/app/services/longitudinal_features.py`
- `backend/app/services/longitudinal_prediction.py`
- `backend/app/schemas/longitudinal_report.py`
- 前端摘要组件及对应测试

**数据库影响**

- 第一阶段不新增表，优先从 `operator_cases`、`operator_case_visits` 和输入快照计算；
- 如果后续需要持久化质量结果，应存入报告结构化结果，不覆盖原始访视；
- 不允许质量清洗过程自动修改操作者录入值。

**实施步骤摘要**

1. 定义质量问题、严重级别和模型可估计性 reason codes；
2. 分别配置脂肪肝与 AD 的核心指标要求；
3. 计算覆盖率、时间跨度、单位一致性和异常输入；
4. 在模型调用前生成质量对象；
5. 将质量结果写入结构化预测、前端摘要和 PDF。

**测试与验证**

- 完整数据、部分缺失、单位冲突、重复指标、跨度不足和访视不足测试；
- 同一输入重复计算必须得到相同质量结果；
- 数据不足时验证模型不会被错误调用；
- 验证质量计算不修改数据库原始值。

**完成标准**

- 报告显示具体缺失指标和覆盖率；
- outcome、stage、trend 分别有 `estimable/not_estimable` 及原因；
- 单位冲突不会被静默当作相同特征；
- 质量评分不替代医学有效性判断。

**前置依赖**：P0-01。
**主要风险**：用单一综合分数掩盖关键缺陷，或把数据完整度误解为临床可信度。
**建议任务编号**：`longitudinal-data-quality-001`。

### P1-02：将纵向趋势改为真实时间尺度

**现状**

当前 slope 使用访视序号作为横轴，不考虑两次访视之间实际相隔多少天。

**目标**

增加按真实日期计算的日变化率、月化或年化变化率，同时保留旧特征的兼容策略。

**数据库影响**

- 不修改原始访视日期和指标；
- 如需保存派生特征，只进入模型训练数据或报告结果，不回写 `operator_case_visits`；
- artifact 元数据必须记录新的 feature version。

**主要涉及文件**

- `backend/app/services/longitudinal_features.py`
- `backend/app/services/progression_engine.py`
- `scripts/train_longitudinal_models.py`
- 模型特征版本和对应测试

**实施要点**

- 新特征必须产生新的 feature version；
- 旧模型不能加载新特征向量；
- 报告显示有单位的年化趋势；
- 不规则访视间隔必须覆盖测试。

**测试与验证**

- 等间隔和不等间隔访视的时间化斜率测试；
- 同日重复访视继续拒绝；
- 单次有效观测返回不可估计；
- 新特征向量与旧 artifact 不兼容测试；
- 脂肪肝和 AD 各选择一个指标验证单位化展示。

**完成标准**

- 报告不再展示无时间单位的“趋势斜率 22.50”；
- 相同数值变化、不同观察跨度得到不同时间化趋势；
- 新旧模型契约不会混用。

**前置依赖**：P0-05、P1-01。
**主要风险**：特征口径变化后旧模型仍被加载，或年化外推放大短期波动。
**建议任务编号**：`longitudinal-time-features-001`。

### P1-03：建立患者级纵向相似病例检索

**现状**

相似病例按 `confirmed=true` 和指标名称交集选择，结果顺序接近数据库原始顺序，不代表数值轨迹相似。

**目标**

按患者聚合参考访视，基于可比较轨迹特征计算相似度，并优先展示真实病例。

**数据库影响**

- 第一阶段只读 `case_records`，不新增相似度结果表；
- 继续使用 `(source_dataset, patient_label)` 作为参考患者身份；
- 必须读取来源和合成标记，不能仅依据患者编号推断；
- 如未来引入向量索引，应另立数据库任务，不在本卡默认范围内。

**主要涉及文件/对象**

- `backend/app/services/longitudinal_evidence.py`
- 可拆分新增 `backend/app/services/longitudinal_similarity.py`
- `case_records`
- `backend/tests/test_longitudinal_evidence.py`

**相似度建议组成**

- 疾病一致；
- 基线阶段可比；
- 观察跨度接近；
- 指标覆盖交集；
- 首次值距离；
- 最近值距离；
- 相对变化距离；
- 时间化趋势距离；
- 关键方向一致；
- 缺失惩罚。

**实施步骤摘要**

1. 按患者聚合参考病例并构造可比较特征；
2. 定义归一化、缺失惩罚和疾病专属权重；
3. 计算相似度并提供逐项解释；
4. 优先真实病例，再补充合成病例；
5. 将算法版本和选择依据写入 evidence。

**测试与验证**

- 同一患者多次访视只返回一个候选；
- 数值轨迹更接近的患者排名更高；
- 只有指标名称相同但轨迹相反的患者不能排名靠前；
- 合成病例标记和真实病例优先级测试；
- 脂肪肝与 AD 分别验证恶化方向差异。

**完成标准**

- 同一参考患者只出现一次；
- 结果包含相似度和具体相似依据；
- 真实病例优先，合成病例显式标记；
- 报告显示最终结局、观察跨度和重叠轨迹，不只显示指标名称；
- 双疾病使用适合各自指标方向的距离。

**前置依赖**：P1-02。
**主要风险**：距离函数未做尺度归一化，导致大数值指标主导排序；参考病例结局泄漏进相似度输入。
**建议任务编号**：`longitudinal-similarity-001`。

### P1-04：完善模型、标准和报告版本追溯

**现状**

报告保存输入快照和部分预测结果，但模型身份、规则版本、训练数据版本和 artifact hash 不完整。

**目标**

任何历史报告都可以回答“用什么输入、什么规则、什么模型生成”。

**数据库影响**

- 优先利用 `AIReport.input_snapshot`、`prediction_result` 和 `sources` 的 JSONB 扩展字段；
- 如果现有字段无法建立稳定索引或审计约束，再单独评估 Alembic 迁移；
- 不修改历史报告已有正文，新增字段必须向后兼容。

**主要追溯字段**

- 输入 schema/version；
- model name/version/hash；
- target/horizon；
- feature version；
- training dataset version；
- real/synthetic counts；
- calibration status；
- standard ID/version ID/rule IDs；
- similarity algorithm version；
- report renderer version；
- 生成时间。

**主要涉及文件/对象**

- `backend/app/schemas/longitudinal_report.py`
- `backend/app/services/longitudinal_prediction.py`
- `backend/app/services/longitudinal_report_generator.py`
- `AIReport.prediction_result`
- `AIReport.input_snapshot`
- `AIReport.sources`

**实施步骤摘要**

1. 定义统一 provenance schema；
2. 将模型、标准、相似度和渲染器版本写入结构化结果；
3. 生成报告时固化 provenance，不在查看时重新解析；
4. 在技术附录展示必要字段；
5. 对旧报告缺失字段提供兼容读取。

**测试与验证**

- 模型更新后旧报告仍显示原模型版本；
- 标准更新后旧报告仍引用原规则 ID；
- 病例访视修改后旧输入快照不变化；
- JSON schema 向后兼容测试；
- PDF 技术附录与数据库 provenance 一致。

**完成标准**

- 修改病例或更新模型后，历史报告仍能还原原始生成依据；
- PDF 技术附录包含必要版本信息；
- 不需要读取服务器日志才能判断使用的 artifact。

**前置依赖**：P0-02、P0-05、P1-03。
**主要风险**：只保存显示文本而未保存稳定 ID，或查看历史报告时重新查询当前标准造成结果漂移。
**建议任务编号**：`longitudinal-traceability-001`。

### P1-05：建立双疾病验证基线与回归样例

**现状**

存在许多模块测试，但缺少一套稳定的双疾病“黄金输入 → 结构化结果 → 报告章节 → PDF”验证基线。

**目标**

为脂肪肝和 AD 各建立至少三类匿名化固定样例：稳定、明显恶化、数据不足。

**数据库影响**

- 固定样例默认使用测试 fixture 或临时数据库，不写入开发/生产参考病例；
- 如需本地端到端数据库验证，必须使用可清理的专用测试数据标识；
- 不将真实患者身份写入仓库。

**主要涉及文件**

- `backend/tests/fixtures/longitudinal/`
- `backend/tests/test_longitudinal_end_to_end.py`
- `backend/tests/test_longitudinal_pdf_contract.py`
- 前端合同测试
- `scripts/verify_baseline.ps1`

**实施步骤摘要**

1. 定义六个匿名化黄金输入；
2. 固化预期结构状态、章节和警告；
3. 建立 API、持久化、前端合同和 PDF 验证；
4. 将 artifact/标准版本纳入基线元数据；
5. 接入统一基线验证命令。

**测试与验证**

- 六个样例逐一执行结构化预测和报告生成；
- 验证报告状态、章节、证据类型和不可估计原因；
- 对 PDF 做文本提取和逐页渲染；
- 验证 fixture 不含可识别个人信息；
- 验证缺少外部 artifact 时给出明确 blocked 原因。

**完成标准**

- 六个样例能够稳定执行；
- 测试不硬编码未经保证的具体模型分数，但校验状态、范围和章节；
- artifact 或规则版本变化会触发显式基线更新；
- PDF 渲染检查无乱码、截断、重叠和缺页。

**前置依赖**：P0-07、P1-04。
**主要风险**：黄金样例过度绑定随机模型分数，导致正常重训练产生大量无意义基线变化。
**建议任务编号**：`longitudinal-validation-baseline-001`。

## 10. P2：增强预测能力

### P2-01：疾病阶段模型

**现状**

结构化 schema 支持阶段候选，但 registry 没有可用阶段 artifact，当前报告只能返回 `not_estimated`。

**目标**

在标签和样本支持时分别建立脂肪肝阶段模型和 AD 阶段模型，输出阶段候选而不是硬编码阶段。

**数据库影响**

- 训练读取 `case_records.metadata` 中的阶段和事件字段；
- 不将模型推断阶段回写为患者确诊阶段；
- 阶段结果只保存到报告预测结果，除非未来另行设计人工确认流程。

**主要涉及文件**

- `scripts/train_longitudinal_models.py` 或独立阶段训练脚本
- `backend/app/services/disease_progression.py`
- `backend/app/services/longitudinal_model_registry.py`
- `backend/app/services/longitudinal_prediction.py`
- 阶段模型训练和推理测试

**疾病差异**

- 脂肪肝：脂肪肝、肝硬化、肝癌；
- AD：正常、MCI、痴呆；
- AD 阶段可考虑有序关系；
- 阶段标签字段不得同时作为泄漏特征。

**测试与验证**

- 患者级交叉验证和类别覆盖；
- 标签泄漏禁止列表；
- 不兼容阶段 artifact 拒绝加载；
- outcome 可用但 stage 缺失的降级测试；
- 双疾病阶段顺序和候选输出测试。

**完成标准**

- `stage_projection.status=available` 只在真实模型加载后出现；
- 返回候选和分数语义；
- 没有合格模型时继续 `not_estimated`；
- 真实子集表现单独报告。

**前置依赖**：P0-03、P0-05、P1-05。
**主要风险**：阶段标签直接由输入量表定义导致近乎确定的泄漏；小类别样本过少导致不稳定。
**建议任务编号**：`longitudinal-stage-model-001`。

### P2-02：下一次访视趋势方向模型

**现状**

训练脚本目前只构造相邻访视标签，尚未完成训练、验证、保存和线上加载；报告回退使用既往斜率。

**目标**

完成关键指标的 rising/stable/falling 训练、评估、保存和加载，并将“观察趋势”与“模型预测方向”分开。

**数据库影响**

- 只读参考纵向访视；
- 不保存未来推测数值；
- 趋势预测结果保存在报告中，不覆盖原始指标。

**主要涉及文件**

- `scripts/train_longitudinal_trend_models.py`
- `backend/app/services/disease_progression.py`
- `backend/app/services/longitudinal_model_registry.py`
- `backend/app/services/longitudinal_prediction.py`
- 训练和推理测试

**实施要点**

- 使用患者级分组验证；
- 容差规则必须按指标配置；
- 特征不能只依赖当前值，应评估历史变化和时间间隔；
- 类别不平衡需显式报告；
- 只输出方向，不输出未来精确数值。

**测试与验证**

- rising/stable/falling 容差边界；
- 患者级分组无泄漏；
- 类别缺失时拒绝训练或明确降级；
- artifact 加载和观察斜率回退测试；
- `direction_only` 不携带 projected value 和 prediction interval。

**完成标准**

- 报告分别显示“既往观察方向”和“下一次随访模型方向”；
- artifact 缺失时明确显示“仅观察趋势”；
- 双疾病关键指标覆盖有清晰名单。

**前置依赖**：P1-02、P1-05。
**主要风险**：仅使用当前值产生伪预测能力；不同指标共用 5% 容差造成临床语义错误。
**建议任务编号**：`longitudinal-trend-model-001`。

### P2-03：模型分数校准

**现状**

所有风险结果都标记为未校准模型分数，无法解释为实际发生概率。

**目标**

评估 Platt scaling、isotonic regression 等校准方法，在独立验证条件满足时将分数升级为经过说明的风险估计。

**数据库影响**

- 不需要业务表迁移；
- 校准器作为模型 artifact 的组成部分或独立 artifact 保存；
- 报告元数据记录校准数据集、方法和版本。

**主要涉及文件**

- outcome 模型训练脚本
- `backend/app/services/longitudinal_model_registry.py`
- `backend/app/services/longitudinal_prediction.py`
- 模型元数据和校准测试

**测试与验证**

- 未校准 artifact 继续输出 `model_score`；
- 校准 artifact 输出明确的 score semantics；
- 校准集与拟合集患者隔离；
- Brier score、可靠性曲线和分层指标生成；
- 小样本条件下拒绝不稳定校准。

**完成标准**

- 报告 Brier score、校准曲线和分层表现；
- 校准数据不与训练拟合数据混用；
- 校准不足时继续使用“模型分数”；
- 不因校准而删除原始模型版本追溯。

**前置依赖**：P0-04、P1-05。
**主要风险**：在小样本或合成数据上过拟合校准曲线，并错误包装成临床概率。
**建议任务编号**：`longitudinal-calibration-001`。

### P2-04：扩展操作者病例临床上下文

**现状**

病例只有疾病、内部编号、性别、基线阶段和备注，无法稳定解析部分标准适用性或竞争病因。

**目标**

补充影响队列适用性和结果解释的结构化上下文，但不一次性建设完整电子病历。

**数据库影响**

- 可能修改 `operator_cases` 或新增受控 JSONB 上下文字段，属于 schema 任务；
- 必须新增 Alembic 迁移并保持历史记录可读；
- 敏感字段遵循最小化采集，不保存无关身份信息。

**主要涉及文件/对象**

- `backend/app/db/models.py`
- Alembic revision
- `backend/app/schemas/longitudinal_case.py`
- `backend/app/services/longitudinal_case_service.py`
- `frontend/src/views/OperatorView.vue` 或病例编辑组件
- 输入快照、标准解析和权限测试

**建议字段**

- 年龄或出生年份；
- 确诊日期；
- 关键并发症；
- 治疗和重要干预事件；
- 数据来源和审核状态；
- 脂肪肝：饮酒、病毒性肝炎、代谢共病；
- AD：教育水平、检测平台、认知评估条件和重要神经系统共病。

**测试与验证**

- Alembic upgrade/downgrade；
- 旧病例字段为空时兼容；
- 上下文进入输入快照；
- 标准适用性正确匹配或降级；
- 操作者所有权和敏感字段访问隔离；
- 前端输入校验与保存回显。

**完成标准**

- 字段有明确用途，不为“以后可能用”而无限扩表；
- 上下文进入输入快照和标准适用性解析；
- schema 迁移、前端录入和权限测试完整；
- 历史病例兼容。

**前置依赖**：P1-01、P0-02。
**主要风险**：范围扩张成完整 EHR；收集了没有明确用途的敏感信息。
**建议任务编号**：`longitudinal-case-context-001`。

## 11. P3：优化展示和使用体验

### P3-01：统一中文展示词典

**现状**

内部英文枚举直接进入前端和 PDF，后端模板与前端存在各自翻译的风险。

**目标**

为内部枚举建立集中式中文展示映射，避免后端 Markdown、前端和 PDF 各自翻译。

**数据库影响**

- 不修改数据库；
- 历史结构化结果继续保存稳定英文枚举；
- 查看时或报告生成时使用版本化展示词典。

**主要涉及文件**

- 建议新增后端展示映射模块
- 前端对应类型和映射模块
- `backend/app/services/longitudinal_report_generator.py`
- `frontend/src/components/LongitudinalPredictionSummary.vue`
- 文案合同测试

**至少覆盖**

- `likely_rising → 预计继续上升`
- `likely_falling → 预计继续下降`
- `likely_stable → 预计保持稳定`
- `direction_only → 仅预测方向`
- `not_estimated → 暂未估计`
- `not_estimable → 当前数据不足，无法估计`
- `progression_signal → 疾病进展相关信号`
- `reference → 参考病例`
- `synthetic → 合成或规则重组病例`

**测试与验证**

- API 枚举保持不变；
- 页面和 PDF 使用一致中文；
- 未知枚举有安全回退，不直接显示空白；
- 脂肪肝与 AD 疾病阶段名称分别翻译。

**完成标准**

- 用户界面和 PDF 不直接暴露内部英文枚举；
- API 仍保留稳定机器枚举；
- 中文映射具有合同测试。

**前置依赖**：P0-07。
**主要风险**：后端和前端词典版本漂移，或翻译改变原始状态语义。
**建议任务编号**：`longitudinal-copy-001`。

### P3-02：报告信息设计与 PDF 分页

**现状**

当前 PDF 能正常渲染中文，但标题可能重复，关键进展信号跨页，第二页留白较多，首页没有集中呈现风险与数据质量。

**目标**

把报告从技术清单改为适合人工审核的专业文档，并解决标题重复、章节断裂和大面积空白。

**数据库影响**

- 不修改数据库 schema；
- 使用已经持久化的报告正文和结构化结果；
- 不在下载时重新计算预测。

**主要涉及文件**

- `backend/app/templates/report_pdf.html`
- `backend/app/services/pdf_generator.py`
- `backend/app/services/longitudinal_report_generator.py`
- PDF 合同和视觉验证测试

**测试与验证**

- A4 中文渲染；
- 长标题去重；
- 关键摘要、表格和警告的分页测试；
- 脂肪肝与 AD 各渲染一份多页报告并逐页检查；
- 页面正文和 PDF 文本一致性检查。

**完成标准**

- 首页优先呈现摘要、数据质量、风险和关键进展信号；
- 关键结论块不跨页；
- 指标表和相似病例表具有清晰表头和单位；
- 标题避免重复拼接；
- 页眉、页脚、报告编号和生成时间一致；
- 脂肪肝与 AD 报告均完成逐页视觉检查。

**前置依赖**：P0-07、P3-01。
**主要风险**：只优化视觉却改变报告事实，或使用浏览器专属 CSS 导致部署环境分页不同。
**建议任务编号**：`longitudinal-pdf-layout-001`。

### P3-03：趋势图和证据可视化

**现状**

报告只有文字列表，操作者难以快速比较多次访视的变化速度和缺失点。

**目标**

在不改变结论的前提下，用小型趋势图辅助理解多次访视变化。

**数据库影响**

- 不新增业务表；
- 图表直接使用报告输入快照或预测结果中的真实观测值；
- PDF 静态图片如需缓存，应另行定义生命周期，不默认持久化。

**主要涉及文件**

- 前端纵向摘要或独立趋势图组件
- `backend/app/templates/report_pdf.html`
- PDF 图表生成辅助模块（如确有需要）
- 前端和 PDF 视觉测试

**边界**

- 图表只显示真实已录入数据；
- 不延伸虚构未来曲线；
- 缺失点和单位必须清楚；
- PDF 中使用可稳定打印的静态图；
- 不把不同单位指标画在同一纵轴。

**测试与验证**

- 2 次、3 次和 10 次访视图表；
- 缺失点和不规则日期；
- 不同单位分图；
- 页面与 PDF 数值一致；
- 图表生成失败时文字报告仍可用。

**完成标准**

- 3 次以上访视可显示关键指标小图；
- 图表与表格数值一致；
- 屏幕和 PDF 均清晰；
- 图表失败不阻塞文字报告。

**前置依赖**：P1-02、P3-02。
**主要风险**：图形暗示不存在的连续趋势，或把观察曲线误解为未来预测。
**建议任务编号**：`longitudinal-visualization-001`。

### P3-04：前端生成状态和故障解释

**现状**

后端主要发送 `feature_extraction`、`prediction`、`delta` 和 `done`，前端无法细分模型、标准和证据的处理状态。

**目标**

让操作者在报告生成过程中看到正在执行的阶段，并在失败时获得可行动的原因。

**数据库影响**

- 沿用 `AIReport.status` 和 `error_message`；
- 如果新增详细阶段持久化字段，需要单独评估迁移，首轮可仅通过 SSE 传输；
- 取消和失败必须保留已固化输入快照和允许保留的结构化结果。

**主要涉及文件**

- `backend/app/services/longitudinal_report_generator.py`
- `backend/app/api/operator.py`
- `frontend/src/api/operator.ts`
- `frontend/src/stores/operator.ts`
- `frontend/src/views/OperatorView.vue`
- SSE、取消、失败和重试测试

**建议状态**

```text
保存输入快照
→ 校验数据质量
→ 提取纵向特征
→ 加载结局模型
→ 解析参考标准
→ 检索相似病例
→ 生成结构化结果
→ 生成报告
→ 保存完成
```

**测试与验证**

- 正常阶段顺序；
- 模型缺失、标准缺失、证据查询失败和 PDF 失败提示；
- 用户取消和网络断开；
- 重试幂等和重复报告识别；
- 历史报告状态与页面展示一致。

**完成标准**

- 不再只显示笼统“生成中”；
- 模型缺失、标准缺失、数据不足和网络中断提示不同；
- 用户取消后数据库状态正确；
- 重试不会生成无法识别的重复报告。

**前置依赖**：P0-07。
**主要风险**：前端阶段与后端实际执行顺序漂移；把可降级警告错误显示为全流程失败。
**建议任务编号**：`longitudinal-generation-ux-001`。

## 12. 里程碑与阶段验收

### 里程碑 M0：基线可测

包含：P0-01。

验收：可以用一条只读命令分别说明脂肪肝和 AD 的数据、标准、模型和报告就绪状态。

### 里程碑 M1：内容完整报告

包含：P0-02 至 P0-07。

验收：脂肪肝和 AD 各生成一份内容完整报告；至少固定窗口 outcome 风险可用，标准、关键信号、局限性、历史和 PDF 均完整。阶段模型可以暂不可用，但必须解释清楚。

### 里程碑 M2：可信和可追溯

包含：P1-01 至 P1-05。

验收：报告具有数据质量、真实时间特征、患者级相似病例、完整版本追溯和双疾病固定验证样例。

### 里程碑 M3：增强预测

包含：P2-01 至 P2-04。

验收：根据数据质量决定是否启用阶段、趋势和校准能力；新增上下文字段有明确作用且历史兼容。

### 里程碑 M4：专业交付体验

包含：P3-01 至 P3-04。

验收：页面和 PDF 使用统一中文表达、专业信息结构、稳定分页、必要趋势图和清晰生成状态。

## 13. 每张任务卡启动时的统一检查清单

后续逐项处理时，每张任务卡必须重新确认：

1. 本任务选择简化流程还是完整任务流程；
2. 是否涉及数据库 schema、迁移或生产数据写入；
3. 是否涉及 RAG 核心链路、标准规则、模型目标或安全边界；
4. 修改文件、数据库对象和接口范围；
5. 脂肪肝和 AD 是共用实现还是分别实现；
6. 是否需要独立 worktree；
7. 是否需要另一个 Agent 交叉评审；
8. 失败回滚和兼容策略；
9. 单元测试、集成测试、真实数据库只读验证和 PDF 视觉验证；
10. 完成后是否更新本文档的任务状态和验证证据。

## 14. 建议的任务状态记录方式

本文档中的任务卡状态建议使用以下枚举：

- `not_started`：尚未设计；
- `designing`：正在编写专项设计；
- `approved`：设计已批准，待实施；
- `implementing`：正在实施；
- `reviewing`：测试完成，等待交叉评审；
- `completed`：验收完成；
- `blocked`：存在明确外部阻塞。

建议在每张任务卡标题下追加状态、Task-ID、设计文档、实施计划、分支、提交和验证记录，不在未开始时预填虚假信息。

## 15. 推荐的第一批执行任务

为了尽快达到“看到一份内容完整的预测报告”，推荐严格按以下顺序启动：

1. `P0-01` 双疾病基线审计与完整报告契约；
2. `P0-02` 双疾病参考标准可用化；
3. `P0-03` 固定窗口训练数据集；
4. `P0-04` 365 天结局模型；
5. `P0-05` registry 与推理状态；
6. `P0-06` 关键进展信号解释器；
7. `P0-07` 完整报告模板和端到端验收。

不建议在以上任务完成前优先投入阶段模型、未来精确数值预测、复杂图表或纯视觉美化，因为这些工作不会解决当前报告核心风险和标准为空的问题。

## 16. 总体验收结论

本路线图完成后，AI 操作者端不应只是“生成了一份有十个标题的 PDF”，而应真正形成以下闭环：

- 数据库知道患者输入、参考病例、标准版本和报告归属；
- 训练系统知道预测目标、时间窗口、可估计标签和真实/合成来源；
- registry 知道哪个模型可以安全加载；
- 推理系统区分观察事实、模型结果和不可估计项；
- 证据系统提供适用标准和真正可比较的患者级轨迹；
- 报告系统用中文、可追溯方式说明风险、依据和局限；
- 前端和 PDF 展示同一份持久化结果；
- 脂肪肝与 AD 共享稳定技术契约，同时保留各自疾病语义。

达到这一状态后，后续才能有序讨论阶段模型、趋势模型、校准、更多疾病和临床验证，而不会继续在不完整的基础链路上叠加功能。
