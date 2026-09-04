# AI 操作者第 5 项：疾病标准与参考病例证据层设计

## 1. 文档状态

- 日期：2026-09-04
- 范围：AI 操作者电脑端，仅覆盖脂肪肝和阿尔茨海默病（AD）
- 目标流程：`AI操作者流程核查.md` 第 5 项“结合对应疾病标准和参考病例”
- 设计状态：用户已逐节批准
- 当前实现基线：`main` 分支，审计时最新提交 `4ac611f`
- 实施状态：本文仅定义设计，不表示代码、数据库迁移或生产部署已经完成

## 2. 已确认的产品决策

1. `backend/tests/fixtures/standards/fatty_liver_standard.docx` 是本项目认可的正式脂肪肝标准来源。
2. `backend/tests/fixtures/standards/ad_standard.docx` 是本项目认可的正式 AD 标准来源。
3. 两份 `standard_manifests/*.v1.json` 是上述文档的已审核、程序可读取规则清单；不在本项中寻找或替换其他医学标准。
4. 正式报告中的参考病例只允许使用非合成、来源可追溯、具有合法匿名编号且结局来源可靠的病例。
5. P151–P300、规则重组病例、生成结局病例和仅通过标题、量表或其他规则推断结局的病例不得进入正式参考病例池。
6. 标准缺失、标准完整性失败或标准查询失败必须阻止报告生成。
7. 标准适用条件不足时允许生成报告，但相关规则只能显示为证据、缺少条件或不适用，不能强行计算。
8. 没有合格或可比较的参考病例不阻止报告；参考病例技术故障也不阻止模型和标准部分，但必须显式标记为部分证据。
9. 采用严格类型化的独立证据层，不采用仅给现有 `sources` 数组补字段的方案。
10. 本期使用确定性相似度算法，不使用向量或机器学习相似病例检索；未来可以增加召回器，但必须继续经过相同的准入和确定性复排。

## 3. 目标与非目标

### 3.1 目标

- 将观察事实、标准解释、参考病例历史结果和模型预测严格分离。
- 让已保存的年龄、性别、基线阶段及访视检测上下文真正参与标准适用性判断。
- 为标准建立完整的文档、版本、规则、原文定位和哈希追溯链。
- 建立可解释、可重复、可版本化且不使用未来结局的相似病例算法。
- 在任何页面、接口、日志和 PDF 中只暴露匿名参考编号。
- 将证据固化为不可变快照，使历史报告不随当前标准或病例库变化。
- 对标准故障、无合格病例、可比性不足和参考病例服务故障给出不同的稳定状态。
- 为后续第 6～9 项提供可直接复用的证据契约和展示组件。

### 3.2 非目标

- 不改变第 4 项已经确定的模型注册、release set、模型任务路由和模型分数语义。
- 不把标准规则或参考病例结局加入模型特征。
- 不让 LLM 选择标准、计算相似度、补充阈值或生成新的医学结论。
- 不把 AD 的 evidence-only 规则提升为可计算规则。
- 不清洗、覆盖或重新计算旧报告。
- 不在本项中连接或迁移生产数据库；生产迁移必须进入单独部署窗口。
- 不在本项中实现向量召回、病例全文展示或自由文本相似度。

## 4. 当前实现审计

审计覆盖标准清单、标准解析器、纵向证据服务、报告 API、输入快照、报告生成器、前端报告页、PDF 和相关测试。审计时聚焦测试结果为 `50 passed, 1 warning`。

### 4.1 已完成并直接复用

| 能力 | 当前实现 |
| --- | --- |
| 病种隔离 | 脂肪肝和 AD 使用不同标准、数据适配器和模型任务 |
| 标准生命周期 | 标准版本具有 draft/review/approved/retired 状态和 current 指针 |
| 标准完整性基础 | 文档和版本保存 SHA-256，规则保存版本及来源片段关系 |
| 规则安全级别 | 支持 `calculable`、`evidence-only` 和 `blocked` |
| AD 安全边界 | 当前 AD 八条规则全部是 `evidence-only` |
| 访视上下文 | 已保存来源、机构、设备、方法、样本、量表版本、语言、教育年限、影像类型等字段 |
| 输入快照 | 年龄、性别、基线阶段、规范化访视和 `visit_context` 已进入报告输入快照 |
| 匿名编号 | 操作者病例和新导入参考病例已有 `CASE-XXXX-XXXX` 匿名编号基础设施 |
| 活动数据版本 | 参考病例查询可以限定当前活动数据 release |
| 历史稳定性 | 报告保存输入、预测、正文和完整性信息，旧报告只读兼容 |

### 4.2 部分完成，必须补齐

| 能力 | 当前问题 | 本设计处理 |
| --- | --- | --- |
| 标准上下文 | 报告 API 主要只传性别，访视上下文没有传给 resolver | 按指标最近一次观察构建类型化上下文 |
| 匿名保护 | 旧参考记录的 `patient_label` 仍可能进入 `sources` JSON | 证据层禁止读取后输出标签；无匿名编号直接排除 |
| 合成标记 | 依赖标签和数据集名称启发式判断 | 只信任已验证的结构化 provenance 和活动 release |
| 标准来源 | 已保存版本、规则和片段，但报告只展示 ID 或简单范围 | 输出文档、版本、定位、短原文和日期状态 |
| 故障处理 | 标准和病例查询共用一个 `try/except`，失败后统一变空 | 独立状态、独立超时和分级失败策略 |
| 类型契约 | `sources: list[dict]` 可放任意字段 | 新增 `EvidenceBundle v1` 严格契约 |

### 4.3 尚未实现

- 参考病例生产准入服务。
- 防结局泄漏的病例比较窗口。
- 人口学、阶段、数值、趋势、跨度和检测条件的确定性相似度。
- 相似度覆盖率、分项原因、算法版本和配置哈希。
- 证据快照及独立 SHA-256。
- 标准和参考病例结构化前端组件。
- 新证据链路的 PostgreSQL 集成、E2E、PDF 视觉和性能验收。

## 5. 总体架构

### 5.1 组件边界

新增或收敛为以下职责单一的组件：

1. `StandardEvidenceService`
   - 验证当前批准标准的文档、版本、归属和哈希。
   - 按指标最近一次有效观察解析上下文。
   - 解析规则适用性并返回来源完整的标准证据。
   - 不查询参考病例，不调用模型，不生成自然语言医学结论。
2. `ReferenceCaseEligibilityService`
   - 根据活动数据版本、合成标记、匿名编号、来源追溯和结局可靠性决定病例窗口能否进入正式参考池。
   - 为每个排除结果返回稳定原因码。
3. `ReferenceCaseSimilarityService`
   - 只对通过准入的病例窗口计算相似度。
   - 不访问身份标签，不读取未来结局作为特征，不生成临床结论。
4. `EvidenceBundleService`
   - 固定标准版本和活动数据版本。
   - 编排标准证据和参考病例服务。
   - 生成、验证并哈希 `EvidenceBundle v1`。
5. `LongitudinalSignalInterpreter`
   - 在原始模型输出完成后，结合观察事实和标准证据产生结构化信号解释。
   - 不修改模型分数、风险等级或模型状态。
6. 报告渲染器
   - 只消费输入快照、原始结构化模型输出、信号解释和证据快照。
   - 页面、历史报告和 PDF 均从同一快照派生。

### 5.2 运行数据流

```text
锁定并复核操作者病例
→ 创建生成批次与输入快照
→ 标准完整性预检并固定批准版本
→ 固定活动参考数据版本
→ 运行原始模型推理（不输入标准规则或参考病例结局）
→ 构建标准证据
→ 筛选并排序参考病例窗口
→ 构建 EvidenceBundle v1
→ 结构化信号解释
→ 渲染正文、页面和 PDF
→ 原子保存预测、证据、正文和完整性指纹
```

标准预检发生在模型前，因此核心标准不可用时不会浪费模型调用。标准规则只参与模型后的确定性解释，不进入模型特征。参考病例完全不进入模型或标准判断。

## 6. 标准适用性设计

### 6.1 指标级上下文

每个指标使用其最近一次有效观察所在访视的上下文，不能把多个访视的上下文合并为全局值。上下文由以下字段组成：

- 病例级：`age`、`sex`、`baseline_stage`、`disease_code`。
- 访视级：`source_type`、`facility_name`、`device_name`、`assay_platform`、`method`、`specimen`、`scale_version`、`assessment_language`、`education_years`、`education_adjusted`、`imaging_type`。
- 派生字段：指标 canonical code、canonical unit、观察日期及检测上下文是否跨访视变化。

`assay_platform` 是新增的独立字段。`device_name` 只能映射到设备，不能默认等同于检测平台。

自由文本 `notes`、`treatment_change` 和 `diagnosis_change` 不进入标准适用性或相似度。若需要表达变化，只派生 `has_treatment_change` 和 `has_diagnosis_change` 布尔值，不传播原文。

### 6.2 类型化适用条件

内部条件模型支持以下操作符：

- `present`：字段存在且非空。
- `equals`：规范化后精确相等。
- `in`：属于明确集合。
- `range`：数值处于明确闭区间或开区间。
- `all`：全部子条件成立。
- `any`：至少一个子条件成立。
- `not`：子条件不成立。

当前 `standard_manifest.v1` 由只读适配器转换为该内部模型：

- 值为 `"required"` 时转换为 `present`，不再与字面字符串比较。
- 普通标量转换为 `equals`。
- 列表转换为 `in`。
- 审计元数据键继续排除在临床适用性判断之外。

未来标准使用 `standard_manifest.v2` 的显式条件结构；现有两份 v1 文件和原文哈希保持不变。

### 6.3 规则解析状态

每条被请求指标的规则只能得到以下状态之一：

| 状态 | 含义 | 是否数值计算 |
| --- | --- | --- |
| `calculable` | 条件完整、单位兼容且规则经批准可计算 | 是 |
| `evidence_only` | 规则经批准但只能提供证据解释 | 否 |
| `missing_context` | 缺少必须的病例或检测条件 | 否 |
| `not_applicable` | 已有条件明确不匹配 | 否 |
| `conflict` | 同一互斥组内多条规则同时命中 | 否 |

脂肪肝只有 `calculable` 规则可以产生 `within_range`、`above_range` 或 `below_range`。AD 当前所有规则无论上下文是否完整都不得产生数值异常、诊断或必然进展结论。

跨访视单位、平台、方法、样本或量表版本发生变化时，标准只解释最新观察；纵向变化增加 `measurement_context_changed` 限制，禁止把不可比较的历史值包装成标准异常趋势。

## 7. 标准来源追溯

每条标准证据固化以下信息：

- 标准 ID、标准名称和疾病代码。
- 文档 ID、标题、文件名和原始内容 SHA-256。
- 发布机构、原文发布日期、外部标识和来源地址；缺失时保存 `null` 并显示“文档未注明”。
- 版本 ID、版本标签、内容 SHA-256、批准时间、生效时间和解析器版本。
- 规则 ID、规则类型、机器可操作性、适用条件及条件哈希。
- 来源片段 ID、章节、段落号、表格号、行号、列号、可用页码和短原文片段。

DOCX 页码会随渲染器、字体和页面设置变化，因此定位优先级为：

```text
PDF 稳定页码
→ DOCX 章节 + 表格号 + 行号 + 列号
→ DOCX 段落号
```

不允许用上传时间或系统批准时间冒充原文发布日期。

## 8. 参考病例窗口与生产准入

### 8.1 为什么使用比较窗口

一个参考患者可以产生多个历史截止点。每个 `reference_case_window` 仅包含 `as_of` 当日及以前的信息，并关联 `(as_of, as_of + 365 天]` 内已审核的后续结局。这样可以同时做到：

- 使用与当前病例相同的历史视角进行比较。
- 不把未来信息放入相似度特征。
- 保留可复核的后续观察结果。

### 8.2 强制准入规则

病例窗口必须同时满足：

1. 与当前病例疾病一致。
2. 属于当前活动数据 release，且 release ID 和数据内容哈希可验证。
3. `is_synthetic` 明确为 `false`。
4. 具有符合 `CASE-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}` 的匿名编号。
5. 截止 `as_of` 至少有 3 次有效、日期唯一且顺序规范的访视。
6. 来源追溯至少包含具体原始文档，或已批准数据 release、内容哈希和逐例审计记录。
7. 结局来源属于病种白名单并达到 `high` 可靠等级。
8. 当前任务与参考窗口任务兼容，终末阶段或任务不适用窗口被排除。
9. 时间线、指标和单位通过与操作者病例相同的规范化服务。

初始结局来源白名单：

- 脂肪肝：`explicit_cirrhosis`、`explicit_hcc` 或等价的人工审核明确事件日期。
- AD：`explicit_cdr`、`documented_ad_unspecified` 或等价的人工审核明确诊断记录。

明确排除：

- `generated_stage_assignment`。
- 仅由 MMSE、MoCA、功能描述或标题推断的结局。
- P151–P300 规则重组数据。
- 合成演示 release 中没有逐例真实来源审计的窗口。
- 匿名编号缺失或格式无效的旧记录。

白名单属于版本化准入配置。改变白名单会产生新的配置哈希和算法版本，不会改变旧报告。

## 9. 确定性相似度 `reference_similarity.v1`

### 9.1 维度与权重

| 维度 | 权重 |
| --- | ---: |
| 基线阶段及预测任务一致性 | 20 |
| 年龄接近程度 | 10 |
| 性别 | 5 |
| 当前病例指标覆盖率 | 15 |
| 最近指标值模式 | 20 |
| 指标方向与时间斜率 | 20 |
| 观察跨度与访视频率 | 5 |
| 检测条件兼容性 | 5 |
| 合计 | 100 |

每个分项分数 `s_i` 位于 `[0, 1]`。不可比较的维度不参与条件相似度，但会降低覆盖率：

```text
available_weight = Σ 可比较维度权重
conditional_similarity = 100 × Σ(weight_i × s_i) / available_weight
coverage = available_weight / 100
ranking_score = conditional_similarity × coverage
```

返回条件：

- `coverage >= 0.60`。
- `ranking_score >= 50`。
- 至少有 1 个当前病种核心指标可以比较。
- 最多返回 5 个参考窗口。

### 9.2 分项计算

- 基线阶段：相同阶段为 `1`。仅 AD 的同一预测任务按 `normal → mci → pre_dementia` 定义有序相邻阶段，相邻为 `0.5`，跨一级为 `0`。脂肪肝当前两个可预测阶段分别路由到不同任务，不定义跨阶段相似；任务不兼容在准入阶段排除。该顺序进入配置哈希，不能从展示文案推断。
- 年龄：`max(0, 1 - |age_current - age_reference| / 20)`。
- 性别：相同为 `1`，不同为 `0`；任一缺失则该维度不可比较。
- 指标覆盖率：当前病例可比较核心指标中，与参考窗口共同存在的比例。
- 最近值：
  - 仅比较相同 canonical code、canonical unit 且检测条件兼容的值。
  - 有固定量表范围时，使用 `1 - |a-b| / (scale_max-scale_min)` 并截断到 `[0,1]`。
  - 有适用可计算双侧参考区间时，以 `upper-lower` 归一化绝对差并截断到 `[0,1]`。
  - 只有单侧阈值时，以 `max(|boundary|, 0.1×max(|a|,|b|), epsilon)` 为尺度归一化绝对差并截断到 `[0,1]`。
  - 其他数值使用对称相对接近度 `1 - |a-b| / max(|a|, |b|, epsilon)` 并截断到 `[0,1]`。
  - 多指标结果取等权平均，不能用缺失指标补零。
- 趋势：方向一致为 `1`，稳定与非稳定组合为 `0.5`，方向相反为 `0`；方向一致时再与归一化时间斜率接近度等权平均。
- 观察跨度与频率：跨度比和访视次数比各占一半，均使用 `min(a,b)/max(a,b)`。
- 检测条件：在实际比较的指标中，样本、平台、方法、量表版本、语言和教育条件兼容的指标比例。

`epsilon` 固定为 `1e-9` 并属于配置哈希。AD 生物标志物缺少或不匹配样本、平台、方法时，该指标不可比较；AD 量表缺少或不匹配版本、语言、教育信息时，该指标不可比较。

### 9.3 稳定排序与解释

排序顺序固定为：

1. `ranking_score` 降序。
2. `coverage` 降序。
3. 结局可靠等级降序。
4. 匿名编号升序。
5. `as_of` 日期降序。

每个结果必须保存总分、覆盖率、八个分项、共同指标、被排除指标和排除原因。参考病例的后续结局不参与准入后的相似度评分，只在完成排序后作为历史观察展示。

## 10. `EvidenceBundle v1` 契约

### 10.1 顶层结构

```text
EvidenceBundle
├─ schema_version = longitudinal_evidence_bundle.v1
├─ evidence_bundle_id: UUID
├─ generation_batch_id: UUID
├─ disease_code: fatty_liver | ad
├─ created_at: UTC timestamp
├─ standard
│  ├─ status
│  ├─ document
│  ├─ version
│  ├─ rules[]
│  └─ warnings[]
├─ reference_cases
│  ├─ status
│  ├─ data_release
│  ├─ algorithm_version
│  ├─ configuration_hash
│  ├─ pool_statistics
│  └─ cases[]
├─ warnings[]
└─ integrity
   ├─ canonicalization_version = v1
   ├─ hash_algorithm = sha256
   └─ evidence_snapshot_sha256
```

所有 Pydantic 模型使用 `extra="forbid"`。日期统一为 ISO 8601，浮点分数在快照中保留 6 位小数，哈希前使用对象键递归排序、数组保持业务顺序的 UTF-8 紧凑 JSON。计算快照哈希时先将 `integrity.evidence_snapshot_sha256` 置为 `null`，对其余完整结构规范化并计算 SHA-256，再把结果写回该字段；数据库列必须保存同一结果，避免自引用哈希。

### 10.2 标准状态

- `available`：至少有一条可计算或 evidence-only 规则，且标准完整。
- `context_incomplete`：标准完整，但所有相关规则均因条件不足而不能计算。
- `not_applicable`：标准完整，但当前观察没有适用规则。
- `conflict`：存在规则冲突；无冲突规则仍可使用，冲突规则禁止计算。

标准缺失、完整性失败和技术查询失败不会产生成功报告，而是进入第 12 节的失败状态。

### 10.3 参考病例状态

- `available`：返回 1～5 个合格结果。
- `no_eligible_cases`：查询成功但正式参考池为空。
- `insufficient_comparability`：有合格窗口，但均未达到覆盖率或评分门槛。
- `reference_query_failed`：技术查询失败，报告以 `partial` 证据继续。
- `reference_index_stale`：索引版本与活动数据版本不一致，不使用旧窗口。

## 11. 数据模型和迁移

### 11.1 `reference_case_windows`

新增病例比较窗口表，主要字段为：

- 身份与版本：`id`、`disease_id`、`anonymous_case_code`、`logical_dataset`、`dataset_release_id`、`data_content_sha256`。
- 窗口：`as_of`、`horizon_days`、`baseline_stage`、`age`、`sex`、`visit_count`、`observation_span_days`。
- 特征：`feature_summary JSONB`、`measurement_context_summary JSONB`。
- 结局：`outcome_status`、`outcome_value`、`outcome_source`、`outcome_reliability`。
- 来源：`source_trace JSONB`、`is_synthetic`。
- 准入：`eligibility_status`、`exclusion_reasons JSONB`。
- 完整性：`timeline_sha256`、`profile_schema_version`、`eligibility_config_hash`、`generated_at`。

唯一约束：

```text
(dataset_release_id, anonymous_case_code, as_of, horizon_days, profile_schema_version)
```

必要索引：

- `(disease_id, dataset_release_id, eligibility_status, baseline_stage)`。
- `(dataset_release_id, anonymous_case_code)`。
- GIN：`feature_summary`。

数据库 CHECK 保护年龄、访视数量、观察跨度、预测周期、哈希格式、匿名编号格式、布尔合成标记和枚举状态。临床准入语义继续由版本化应用服务保护。

### 11.2 `ai_reports`

新增：

- `evidence_snapshot JSONB`，旧报告允许 `NULL`。
- `evidence_snapshot_sha256 CHAR(64)`，旧报告允许 `NULL`。
- `evidence_status VARCHAR(20)`：`complete` 或 `partial`。
- `standard_evidence_status VARCHAR(40)`。
- `reference_case_status VARCHAR(40)`。

新报告完成时必须同时具有有效证据快照、证据哈希和状态。报告生成指纹覆盖输入快照、预测结果、证据快照和正文。

### 11.3 标准引用元数据

`standard_documents` 增加可空的 `issuer`、`publication_date`、`external_identifier` 和 `source_url`。`standard_segments` 增加可空且大于零的 `page_number`。现有文档无信息时保持空值并明确展示“文档未注明”，不自动推断。

### 11.4 访视上下文

在 `VisitContext` 中增加可空 `assay_platform`，继续保存在现有 `operator_case_visits.visit_context JSONB`，无需为该字段增加独立数据库列。请求模型继续禁止额外字段并限制字符串长度。

### 11.5 构建与兼容

- 参考窗口构建器先 dry-run，输出总数、合格数和各排除原因数量。
- 正式构建按唯一键幂等 upsert；同一 release 和配置重复运行结果必须一致。
- release 或配置变化时创建新窗口版本，不覆盖旧报告引用的窗口语义。
- 旧报告不回填证据、不重新计算正文。
- 原 `sources` 字段保留；新报告只写入从证据快照派生的完全脱敏兼容投影，供旧客户端读取。

## 12. 运行一致性和错误处理

### 12.1 版本固定

标准 current 指针和活动数据 release 在证据读取前后各校验一次：

- 身份与哈希未变化：继续。
- 中途切换：重新读取并完整重试一次证据构建。
- 再次变化：以 `evidence_version_changed` 失败。

证据快照保存后不再跟随 current 指针变化。模型调用期间不保持长事务或数据库行锁。

### 12.2 标准失败

| 错误码 | 条件 | 处理 |
| --- | --- | --- |
| `standard_missing` | 没有已批准当前版本 | 报告失败，不调用模型 |
| `standard_integrity_failed` | 文档、版本、归属或哈希异常 | 报告失败，不调用模型 |
| `standard_query_failed` | 标准数据库查询故障或超时 | 报告失败，不调用模型 |
| `evidence_version_changed` | 连续两次读到不同证据版本 | 报告失败 |

失败报告保留输入快照、生成批次、稳定错误码和 `error_stage=standard_evidence`，不保存底层异常正文。

### 12.3 参考病例降级

参考病例查询使用独立超时。查询失败或索引过期时：

- 标准和模型部分继续生成。
- `evidence_status=partial`。
- `reference_case_status` 保存对应稳定状态。
- 正文、前端和 PDF 显示明确警告。
- 不回退到旧的指标重叠筛选，不使用上一 release 的索引，不放宽准入规则。

### 12.4 模型与持久化失败

继续复用第 4 项既有的模型加载、推理、超时、取消和原子终态收敛。持久化成功必须一次写入预测结果、证据快照、正文和完整性指纹；部分写入回滚并落为 `error_stage=persistence`。

## 13. 隐私、安全与审计

- 证据 schema 中不存在 `patient_label` 字段。
- 无合法匿名编号的参考记录直接排除，不使用标签回退。
- 相似度服务不接收姓名、住院号、证件号、联系方式或自由文本病历。
- 日志只记录 `case_id`、`report_id`、`evidence_bundle_id`、版本、数量、耗时和稳定原因码。
- 标准错误和参考病例错误不回显数据库异常、文件绝对路径、SQL、连接信息或完整请求。
- 审计只保存候选池数量、排除原因计数、最终数量、算法版本和配置哈希，不保存指标值或原始上下文文本。
- API、SSE、历史详情和 PDF 均从脱敏证据快照生成。
- 页面展示参考病例结局时必须附带：“参考病例结果不代表当前病例将发生相同结局。”

## 14. 页面与 PDF 设计

所有 UI 变更严格遵循 `docs/DESIGN_SPEC.md`。

### 14.1 组件

新增可复用的 `LongitudinalEvidenceSection`，接受严格类型的 `EvidenceBundle v1`，由两个区域组成：

1. 正式标准
   - 指标中文名和代码。
   - 可计算、仅供证据、缺少条件、不适用或冲突状态。
   - 最新观察、适用范围或证据解释。
   - 已满足、缺失和不匹配的适用条件。
   - 文档、版本、日期和原文定位。
   - 默认折叠的短原文片段。
2. 参考病例
   - 匿名编号、总分和覆盖率。
   - 主要相似原因及分项评分。
   - 年龄段、性别、基线阶段、访视次数和观察跨度。
   - 可比较指标与检测条件。
   - 后续结局、来源、可靠等级和数据版本。
   - 固定非因果、非预测提示。

### 14.2 状态文案

必须分别显示：

- “当前没有通过生产准入的参考病例。”
- “存在合格病例，但与当前病例可比信息不足。”
- “参考病例查询暂时不可用，本报告仅使用正式标准和模型结果。”
- “当前规则缺少量表版本、检测平台或其他必要条件，因此没有进行数值判断。”

技术故障使用带图标的警告卡片，不能伪装成普通空状态。

### 14.3 样式与可访问性

- 主内容保持最大宽度 `880px`。
- 卡片使用设计变量、`12px` 圆角、浅边框和 `--shadow-sm`。
- 状态使用文字、图标和颜色三重表达。
- 展开控件点击区域至少 `44×44px`，支持键盘和清晰焦点环。
- 遵循 `prefers-reduced-motion`。
- 不增加大面积主色色块，不改变暖杏蓝整体风格。

### 14.4 新旧报告与 PDF

- 新报告按 `evidence_snapshot.schema_version` 使用结构化证据组件。
- 旧报告继续渲染原有 Markdown 和 `sources`，不回写。
- 后端正文和前端组件使用同一证据快照及同一文案映射，不允许互相矛盾。
- PDF 显示与页面相同的标准状态、来源、参考病例限制和匿名编号。
- PDF 技术附录增加证据快照哈希、标准版本、数据版本、相似度算法版本和配置哈希。

## 15. 性能设计

- 数据库先执行病种、活动 release、准入状态、任务和核心指标硬筛选。
- 最多把 500 个候选窗口交给 Python 完整评分。
- 避免逐病例查询；窗口、来源和特征使用有限次数批量查询。
- 标准版本、活动 release 和相似度配置组成缓存身份；任一身份变化即失效。
- 标准查询与参考病例查询设置独立超时。
- 10,000 个参考窗口基准下，证据构建 P95 目标不超过 1 秒，不包含模型推理。
- 性能测试记录候选数、查询次数、数据库耗时、评分耗时和总耗时，不记录临床值。

## 16. 测试策略

### 16.1 后端单元测试

- 证据 schema 严格字段、枚举、日期和哈希。
- 两份已批准标准文档和 manifest 的 SHA-256 对齐。
- v1 条件适配和 `required` 正确语义。
- 脂肪肝规则边界、性别、单位和上下界开闭。
- AD 八条规则始终 evidence-only。
- 指标最近观察上下文、跨访视上下文变化和单位冲突。
- 全部准入与排除原因及结局来源白名单。
- 禁止合成、生成结局、推断结局、无匿名编号和不可追溯窗口。
- 八个相似度分项、覆盖率、阈值、稳定排序和配置哈希。
- 修改参考结局不会改变相似度，证明无结局泄漏。
- 标准失败阻断、参考失败降级和版本切换重试。
- 证据规范化、SHA-256、兼容来源投影和报告完整性指纹。

### 16.2 PostgreSQL 集成测试

- Alembic 升级/降级契约、ORM 和 `schema.sql` 对齐。
- 唯一键、外键、CHECK、普通索引和 GIN 索引。
- 窗口 dry-run、幂等构建和 release 切换隔离。
- 报告输入、模型、证据、正文和生成批次一致。
- 操作者权限隔离、旧报告只读和失败事务回滚。

### 16.3 前端、PDF 与 E2E

- 所有标准状态、参考病例状态和空状态。
- AD 页面和 PDF 不出现自动异常、确诊或必然进展结论。
- 匿名编号及敏感标签防泄漏。
- 键盘、焦点、ARIA、颜色非唯一表达和 reduced motion。
- 新旧报告渲染分支。
- 页面与 PDF 的证据内容、版本和哈希一致。
- 脂肪肝可计算标准、AD evidence-only、无合格病例、参考服务故障和标准硬失败的浏览器 E2E。

### 16.4 性能与故障注入

- 10,000 窗口基准和 500 候选上限。
- SQL 查询次数上限，检测 N+1。
- 标准查询超时、参考查询超时、活动指针连续切换、索引过期、持久化失败和客户端取消。

## 17. 部署与回滚

部署顺序固定为：

```text
1. 备份并执行生产数据库只读预检
2. 部署新增表、字段、约束和索引
3. dry-run 构建参考窗口并导出准入统计
4. 人工核对各排除原因和合格窗口数量
5. 正式幂等构建 reference_case_windows
6. 启用 EvidenceBundle v1 影子校验
7. 对比旧来源与新证据结果，不向用户展示影子结果
8. 启用新后端证据链路
9. 启用前端结构化证据区和 PDF
10. 执行双病种、历史报告和故障降级冒烟
```

迁移全部为向后兼容的新增结构。应用配置开关允许暂时恢复旧读取路径；新报告仍保存脱敏兼容 `sources` 投影，因此回滚旧应用版本后报告仍可读取。回滚不得删除已经生成的证据快照或窗口数据。

## 18. 验收标准

只有以下条件全部满足，才可以在仓库侧把第 5 项标记为完成：

1. 两份认可的 DOCX 与 manifest、数据库当前标准版本通过文档、归属、版本和哈希完整性检查。
2. 脂肪肝只在规则、单位和指标级上下文完整匹配时计算参考范围。
3. AD 始终只作证据解释，不进行通用数值异常、确诊或必然进展判断。
4. 正式参考池不包含合成、生成结局、推断结局、不可追溯、无匿名编号或任务不兼容窗口。
5. 相似病例具有确定性总分、覆盖率、分项原因、算法版本和配置哈希。
6. 后续结局不参与相似度或模型输入。
7. 标准失败阻止报告；参考病例失败明确降级；无数据与技术故障严格区分。
8. 页面、历史详情、兼容来源投影和 PDF 全部来自同一不可变证据快照。
9. 证据快照进入 SHA-256 和报告生成完整性指纹。
10. 所有后端、脚本、前端、构建、E2E、PDF 视觉和性能测试通过。
11. `docs/AI操作者流程核查.md` 根据实际实现更新已完成、剩余部署门禁和测试结果。
12. 真实 PostgreSQL 迁移、迁移后只读核对、生产浏览器冒烟和线上监控在部署窗口完成前，文档不得表述为生产已上线。

## 19. 预期文件边界

实施按以下文件职责落地；若现有模块需要拆分，只允许在实施计划评审时显式修订本节，不在编码过程中临时改变边界：

- `backend/app/schemas/longitudinal_evidence.py`：`EvidenceBundle v1` 及所有子结构。
- `backend/app/services/standard_evidence.py`：标准完整性、上下文和来源证据。
- `backend/app/services/reference_case_eligibility.py`：准入和结局来源白名单。
- `backend/app/services/reference_case_windows.py`：窗口构建与持久化。
- `backend/app/services/reference_case_similarity.py`：确定性评分。
- `backend/app/services/evidence_bundle.py`：版本固定、编排、快照和哈希。
- `backend/app/services/longitudinal_signal_interpreter.py`：保持模型输出与标准解释分离。
- `backend/app/services/longitudinal_report_generator.py`：消费新证据契约和生成兼容投影。
- `backend/app/schemas/operator_visit_context.py`：增加 `assay_platform`。
- `backend/app/db/models.py`、Alembic 和 `database/schema.sql`：新增表与字段。
- `scripts/build_reference_case_windows.py`：dry-run、正式幂等构建和统计输出。
- `scripts/check_database_readonly.py`：迁移后只读核对。
- `frontend/src/api/operator.ts`：严格 TypeScript 证据类型。
- `frontend/src/components/LongitudinalEvidenceSection.vue`：标准与参考病例结构化展示。
- `frontend/src/components/LongitudinalReportView.vue`：新旧报告路由与组件集成。
- `backend/app/templates/report_pdf.html`：证据卡片和技术追溯信息。
- `docs/AI操作者流程核查.md`：实施完成后的核查结论。
