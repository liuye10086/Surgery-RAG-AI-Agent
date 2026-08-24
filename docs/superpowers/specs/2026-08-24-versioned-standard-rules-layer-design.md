# 版本化标准规则层设计规格

- 日期：2026-08-24
- 状态：设计已确认，待实施计划
- 协作方式：简化流程
- 首期范围：脂肪肝标准、AD 标准

## 1. 目标与边界

建立独立、可追溯、可审核、可版本化的医学标准规则层，替代把 `reference_ranges` 当作标准事实来源的做法。

本规格覆盖：

- 标准集合、不可变版本、规范化指标、结构化片段、规则、组合条件、候选结果和修改审计。
- DOCX 专用结构感知解析、确定性解析、LLM 候选归类、冲突和适用条件校验。
- 管理员标准管理工作台、逐条编辑、审核、批准和发布。
- 批准后立即生成并启用 `reference_ranges` 兼容投影。
- 纵向报告通过 resolver 获取当前批准标准依据，并保存版本和规则快照。

不在首期范围内：

- PDF、DOC、图片等非 DOCX 标准源文件。
- 新增独立标准审核角色。
- 多个版本并行生效或未来定时生效。
- 将标准命中、阶段阈值等加入纵向模型特征。
- 修改现有 `.joblib`、`meta.json` 或重新训练纵向模型。
- 单时点指标预测报告功能；当前 AI 操作者只保留纵向进展预测及预测报告生成、查看、下载和删除。

## 2. 已确认的产品决策

1. 管理员拥有标准版本的完整生命周期权限；AI 操作者只读取已批准版本。
2. 首期只迁移脂肪肝和 AD，但数据模型、解析器接口和规则类型可扩展到其他疾病。
3. 管理后台侧边栏新增独立“标准管理”入口，复用 `/admin` 路由和管理员权限。
4. 原始文件复用现有 `documents` 表，标准版本通过 `document_id` 关联 DOCX 文件。
5. 一个疾病对应一个逻辑标准集合；内容修订通过新版本表达。
6. 版本状态固定为 `draft -> review -> approved -> retired`。
7. 新版本批准后立即生效，旧版本自动退役；不支持并行有效版本。
8. `draft`/`review` 版本支持逐条编辑，所有修改记录审计轨迹；`approved`/`retired` 版本不可原地修改。
9. 无法安全计算的方向性、影像、研究发现和适用条件不足的内容可以随版本发布，但必须标记为 `evidence-only`。
10. LLM 只能生成候选结构化结果，不能直接发布规则或生成投影。
11. 批准事务立即生成并启用安全的 `reference_ranges` 兼容投影。
12. 标准 resolver 本次直接接入纵向报告证据链路；历史报告不因新版本发布而重算。

## 3. 实际标准文档约束

### 3.1 AD 标准

AD 文档同时包含核心生物标志物方向、影像表现、认知/功能量表、NIA-AA 六阶段、A/T/N 状态、平台/示踪剂/队列/年龄/量表限制、多研究阈值、冲突框架和诊断限制。因此：

- 同一指标的方向性结论、研究阈值和平台阈值必须作为不同规则保留。
- A/T/N 状态和 NIA-AA 阶段必须结构化，不能只存解释段落。
- `framework`、`biomarker_axis`、`biomarker_state`、`stage`、`clinical_function` 和诊断限制必须可追踪。
- 不同诊断框架或冲突阈值不可自动合并、平均或互相替代。

### 3.2 脂肪肝标准

脂肪肝文档同时包含正常范围、脂肪变性分级、病理金标准、MAFLD/ALD/NAFLD 组合或排除规则、设备限制和脂肪变性/纤维化维度区分。因此：

- `clinical_dimension` 至少区分 `steatosis`、`fibrosis_risk`、`liver_injury`、`metabolic`、`function` 和 `pathology`。
- LFC、CAP、MRI-PDFF 等脂肪变性指标不能与 LSM、FIB-4、NFS 等纤维化风险指标互相替代。
- MAFLD 支持“脂肪变性证据 + 至少一项代谢异常”；NAFLD 支持排除条件；ALD 支持按性别区分的饮酒阈值。
- 轻度、中度、重度和正常是独立目标状态；影像和病理文字不能被强制压成数值范围。

## 4. 数据模型

### 4.1 `reference_standards`

表示逻辑标准集合。

- `id`
- `disease_id`：唯一关联一个疾病
- `name`
- `description`
- `status`
- `current_version_id`
- `created_at` / `updated_at`

### 4.2 `reference_standard_versions`

表示不可变发布版本。

- `id`、`standard_id`、`document_id`
- `version_label`
- `content_hash`
- `parser_version`
- `status`：`draft` / `review` / `approved` / `retired`
- `supersedes_version_id`
- `effective_from` / `retired_at`
- `created_by`、`approved_by`、`approved_at`
- `created_at` / `updated_at`

创建版本时选择已有 DOCX 文档；文件不存在、类型不是 DOCX 或内容哈希变化时，不能继续解析或批准。同一标准、同一文件哈希不重复创建版本。

### 4.3 `standard_indicators`

保存规范化指标字典。

- canonical key、规范英文名、中文名
- 别名/历史名称
- `domain`
- `specimen_or_modality`
- `data_type`：`numeric` / `ordinal` / `categorical` / `qualitative`
- `scale_or_method`
- `default_unit`
- `clinical_dimension`
- `allows_numeric_comparison`

指标主键只使用规范标识；不同样本、模态、设备或量表上下文由规则适用条件表达。

### 4.4 `standard_segments`

保存 DOCX 的结构化解析中间层。

- `version_id`
- 章节、段落、表号、行号、列号和定位信息
- `raw_text`
- `segment_type`：`paragraph`、`table_row`、`stage_row`、`rule_text` 等
- `parse_status`
- `review_status`
- 结构化原文元数据

标准片段不复用病例 `Chunk`，不进入病例向量库。

### 4.5 `standard_parse_candidates`

保存确定性解析和 LLM 产生的候选结果。

- `segment_id`
- 候选结构化 JSON
- `source_type`：`deterministic` / `llm`
- `parser_version`
- 模型和提示词版本
- 原始输出
- 置信度
- 管理员采纳/拒绝状态
- 创建时间

候选永远不能绕过管理员直接发布。

### 4.6 `standard_rules`

统一保存可计算规则和证据规则。

- `version_id`、`indicator_id`、`source_segment_id`
- `rule_type`：`numeric_range`、`threshold`、`qualitative_direction`、`classification`、`exclusion`、`composite`
- 比较符号、上下界、开闭区间和单位
- 性别、类别和 `applicability` JSONB
- `target_state_type`：`control`、`disease`、`grade`、`stage`、`biomarker_state`、`evidence`
- `target_state_value`
- `clinical_dimension`
- `evidence_type`
- `machine_actionability`：`calculable` / `evidence-only` / `blocked`
- `interpretation`
- 优先级和冲突组标识
- `framework`、`biomarker_axis`、`biomarker_state`、`stage`、`clinical_function` 等可选结构化字段

同一指标的正常、疾病、分级、阶段和研究阈值必须分别保存。多个研究阈值并存，不平均、不合并、不按写入时间覆盖。

### 4.7 `standard_rule_conditions`

表达组合和排除条件树，至少支持：

- `all`
- `any`
- `not`
- `at_least_n`
- `at_most_n`
- 性别、年龄、设备、平台、示踪剂、量表版本和诊断框架条件
- 对规则结果、定性证据和数值比较的叶子条件

### 4.8 `standard_change_logs`

记录 `draft`/`review` 阶段每次编辑：实体、字段、修改前后 JSON、修改原因、管理员和时间。approved/retired 版本不可产生编辑日志，只能通过新版本修订。

### 4.9 `reference_ranges` 兼容投影字段

保留现有表作为只读派生投影，并增加：

- `standard_id`
- `standard_version_id`
- `standard_rule_id`
- `applicability_hash`
- `is_current_projection`：仅当前批准版本的投影为 `true`

数据库为 `standard_id`、规范指标、性别/类别和 `applicability_hash` 建立当前投影唯一约束；管理员不能直接编辑投影。

## 5. 解析与审核流程

```text
管理员选择疾病标准和已有 DOCX
    -> 创建 draft 版本并保存内容哈希
    -> 结构感知解析段落、表格、行列和定位
    -> 写入 standard_segments
    -> 确定性解析数值、方向、分级、阶段和组合规则
    -> 未完整解析片段生成 standard_parse_candidates
    -> LLM 只做候选归类/补充
    -> 冲突、单位、边界、维度和适用条件校验
    -> 管理员预览、逐条编辑、接受或拒绝候选
    -> 提交 review
    -> 管理员批准
    -> 退役旧版本、生成 reference_ranges 投影并立即启用
```

确定性解析规则：

- `<`、`>` 为开区间；`≤`、`≥` 为闭区间。
- `5%–10%` 两端默认闭合，除非原文另有说明。
- “约”“常见为”不能静默转换为精确临床阈值。
- 平台、示踪剂、年龄、队列、量表版本或研究条件不完整时，默认只作为证据或待审核候选。

发布前校验：

- 指标和单位完整且已归一化。
- 数值边界和比较符号完整。
- 研究阈值适用条件完整，多个阈值未被合并。
- 条件树引用存在且无循环。
- 脂肪变性与纤维化维度未混用。
- AD A/T/N 和阶段规则声明诊断框架。
- 方向性、影像和实验性发现未被误标为可计算。
- evidence-only 规则不会进入兼容投影。

校验级别为 `error`、`warning`、`info`。`error` 阻止提交或批准；`warning` 允许继续但要求管理员确认。

批准在一个数据库事务内完成：完整校验、批准新版本、自动退役旧版本、生成投影、更新当前版本和写发布审计。任一步失败则回滚。

## 6. Resolver 与报告

resolver 契约：

```python
resolve_standard_rules(
    db,
    disease_id: int,
    indicator_names: list[str],
    context: dict,
) -> ResolvedStandardRules
```

`context` 可包含性别、年龄、样本类型、平台、实验室、示踪剂、设备、量表版本、疾病阶段、诊断框架和队列。

返回：

- `calculable_rules`
- `evidence_rules`
- `unmatched_rules`
- `standard_version`
- `resolution_warnings`

resolver 只读取当前批准版本，不按 `created_at` 选择最新规则；上下文不匹配、规则冲突或条件不足时不自动选择。

纵向报告将 `build_reference_range_sources()` 改为调用 resolver：

- 可计算规则作为带版本和规则来源的参考依据。
- evidence-only 规则作为标准依据/解释限制展示，不进入模型输入。
- 未匹配规则转为适用条件提示。
- `AIReport.prediction_result` 和 `AIReport.sources` 保存实际使用版本、规则 ID、边界、单位和适用条件快照。

不修改纵向模型 artifact、特征顺序、访视特征提取和风险分数计算。未来若增加标准相关模型特征，必须另建 artifact 版本并重新训练。

## 7. API 与管理员前端

### 7.1 管理员 API

```text
GET    /admin/reference-standards
POST   /admin/reference-standards
GET    /admin/reference-standards/{standard_id}
POST   /admin/reference-standards/{standard_id}/versions
GET    /admin/reference-standard-versions/{version_id}
POST   /admin/reference-standard-versions/{version_id}/parse
POST   /admin/reference-standard-versions/{version_id}/submit-review
POST   /admin/reference-standard-versions/{version_id}/approve
POST   /admin/reference-standard-versions/{version_id}/retire
GET    /admin/reference-standard-versions/{version_id}/segments
GET    /admin/reference-standard-versions/{version_id}/rules
PATCH  /admin/reference-standard-rules/{rule_id}
GET    /admin/reference-standard-rules/{rule_id}/history
GET    /admin/reference-standard-versions/{version_id}/validation
GET    /admin/reference-standard-versions/{version_id}/candidates
```

只有 `draft`/`review` 版本允许编辑规则；`approved`/`retired` 写操作返回 `409`。创建版本只能选择现有 DOCX，且文件哈希必须稳定。

### 7.2 管理员“标准管理”区块

在 `AdminSidebar.vue` 增加“标准管理”，在 `AdminView.vue` 增加对应 section，复用 `/admin` 路由、管理员权限、折叠侧边栏和 DESIGN_SPEC 视觉规范。

工作区包含：

1. 标准集合：疾病、当前版本、状态和新建版本入口。
2. 版本列表：状态、DOCX、哈希、解析器版本和生命周期操作。
3. 审核工作台：原文定位、规则编辑、LLM 候选、校验问题和修改历史。
4. 发布摘要：可计算规则、evidence-only、冲突、缺失条件和投影数量。

### 7.3 AI 操作者

AI 操作者不可上传、解析、编辑或发布标准；不再触发 `/operator/reference-ranges/sync`。现有“解析为参考范围”操作从 `CaseManageView` 删除。纵向病例、进展预测、预测报告生成、查看、下载和删除继续保留。

若没有匹配的已批准标准依据，只显示适用性提示，不阻止纵向模型运行。

## 8. 数据迁移与首期初始化

新增 Alembic revision，建立所有标准层表、外键、唯一约束、状态校验和投影索引。

首期从 `AD标准.docx` 和 `脂肪肝标准.docx` 创建两个 `draft` 版本，不自动批准，不自动改变已有报告。现有 `reference_ranges` 保留，迁移后标记为 legacy/未绑定版本，不再作为新标准事实来源。

标准 DOCX 不要求通用文档分块或向量化；标准专用解析直接读取 DOCX 原始结构。

## 9. API、数据和 UI 验收标准

后端必须验证：

- 两份 DOCX 的段落、表格、行列和原文定位完整保留。
- 数值边界开闭语义保持原义。
- 多研究阈值并存，不平均、不覆盖。
- 平台、示踪剂、年龄、量表版本不匹配时不能计算。
- 方向性、影像、研究发现和框架冲突进入 evidence-only。
- `at_least_n`、排除和组合规则可保存、校验和解析。
- AD A/T/N、诊断框架和 NIA-AA 阶段可追溯。
- 脂肪变性与纤维化维度不能混用。
- draft/review 可编辑，approved/retired 不可编辑。
- 批准事务自动退役旧版本并生成当前投影。
- resolver 只读取当前批准版本，并在冲突或缺失上下文时发出警告。
- 历史报告来源快照不随新版本变化。
- 纵向模型 artifact 校验值和特征顺序不变。

前端必须验证：

- 管理员侧边栏显示并切换“标准管理”。
- 版本状态和操作按钮按生命周期正确显示。
- 审核工作台可逐条编辑并要求修改原因。
- AI 操作者不再显示标准同步操作。
- 报告依据展示标准版本和规则来源。

## 10. 风险与明确取舍

- 规则表和条件树比 JSONB-only 方案复杂，但能提供更强的医学语义约束、冲突检测和长期可迁移性。
- `applicability` 保留 JSONB 以容纳稀疏条件，但核心身份、边界、状态和条件关系使用明确字段。
- LLM 保留在候选层，牺牲自动化速度换取可审计和人工可控发布。
- 兼容投影保留旧消费者能力，但事实来源始终是批准的标准版本，投影不可直接编辑。
