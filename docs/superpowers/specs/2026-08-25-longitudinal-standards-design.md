# 双疾病参考标准可用化设计

> 日期：2026-08-25  
> Task-ID：`longitudinal-standards-001`  
> 路线图任务：P0-02  
> 状态：项目所有者已批准
> 协作方式：单 Agent

## 1. 背景与当前状态

P0-01 已建立 `longitudinal_readiness.v1` 只读契约。当前两种疾病均具有足够的参考患者、纵向访视和未来 365 天标签，但参考标准尚不可用。

本任务开始时的标准状态如下：

- 脂肪肝标准集合 `id=1` 存在。测试期间误退役的空版本 `id=2` 已经在项目所有者明确授权后删除；其 57 个片段和 57 个候选已级联删除，标准集合与 `脂肪肝标准.docx` 文档记录和磁盘文件均保留。当前 `current_version_id` 为空，文档已解除锁定并恢复可用。
- 阿尔茨海默病尚无标准集合、标准版本或正式标准文档记录。现有 `AD标准.docx` 源文件存在于项目验收文件与测试 fixture 中，但尚未登记到正式标准文档库。
- 两份源文件以内容哈希作为身份：脂肪肝 DOCX SHA-256 为 `f0e1b1dd3b3da14e214711438060a0a7f42a3461a446db63963b35cc99d94fba`，AD DOCX SHA-256 为 `96222b951522cdbb7ef211b226d95659e9dc624e684cb88240d36267d816f9df`。实施不得仅按文件名或临时路径选择源文件。
- `standard_indicators`、`standard_rules`、`standard_rule_conditions` 和版本化 `reference_ranges` 投影当前均为空。
- 两份 DOCX 的内容保持原样。本任务不修改医学源文档，而是从现有原文建立新 draft、审核清单和正式规则。

现有链路已经具备标准文档、版本、片段、候选、规则、验证、resolver 和发布投影的基础结构，但存在以下 P0-02 必须解决的缺口：

- current version 只有普通外键，数据库不能阻止其指向非 approved 或其他标准的版本。
- 独立退役当前版本不会清空 current 指针或关闭当前投影。
- 空规则版本或不满足疾病级 actionability 门槛的版本目前可能通过发布验证。
- 解析器可能把“约”“常见为”和说明文字误识别为精确阈值或单位。
- 候选 materialize 与候选状态更新跨越多个事务，存在部分成功状态。
- 管理页面虽有候选 API，但当前工作台不能可靠承载本任务所需的完整医学逐条审核；本任务不新增 UI。

## 2. 协作与实施约束

- 全程使用单 Agent，不使用子 Agent、双 Agent或交叉 Agent 评审。
- 不把 `AI_COLLABORATION.md` 作为前置条件。
- 不创建 worktree；如实施阶段确有需要，必须先获得项目所有者授权。
- 当前阶段只设计和编写实施计划。设计及计划获批前不修改生产代码和正式标准数据。
- 实现必须采用 TDD：先编写并运行失败测试，再写最小生产代码。
- 未经审核的 manifest、测试数据、解析候选和测试规则不得写入正式数据库。
- 本任务没有 UI 修改，不读取或修改 `docs/DESIGN_SPEC.md` 相关前端实现。
- P0-02 不训练模型，不修改模型 registry、纵向预测 schema、报告模板或模型 artifact。

## 3. 目标

1. 为脂肪肝和 AD 分别建立至少一个 current approved 标准版本。
2. 为双疾病核心指标建立经过人工审核的 canonical indicators 和正式规则。
3. 明确区分 calculable、evidence-only 和 blocked 内容。
4. 保留单位、边界包含性、异常方向、性别、平台、方法、样本、年龄、教育、队列和框架等适用信息。
5. 防止模糊医学文本、研究范围或缺少适用条件的内容被错误转换为通用机器阈值。
6. 保证 current version 只能指向同一标准的 approved 版本。
7. 保证发布、退役、投影和 current 指针更新具有原子性，失败时不留下部分状态。
8. 使 resolver 和报告证据能够保留标准版本 ID、规则 ID、边界、单位、适用条件和适用性哈希。

## 4. 非目标

- 不修改两份标准 DOCX 原文。
- 不把全部解析候选直接或批量发布为正式规则。
- 不要求每个核心指标都有 calculable 规则；源文档无法提供安全机器规则时允许明确记录为 evidence-only 或无可用规则。
- 不扩展管理员审核 UI。
- 不修改纵向模型特征、训练目标、artifact 或 registry。
- 不负责 P0-04 的 365 天 outcome artifact。
- 不重构 P0-07 报告模板。
- 不建设完整 EHR 上下文或新增操作者病例字段；相关扩展属于 P2-04。

## 5. 方案选择

采用“审核清单 + 机器可读规则 manifest 驱动发布”方案。

### 5.1 采用方案

```text
现有 DOCX 原文
  -> 创建全新 draft 版本
  -> 解析片段和候选仅作辅助
  -> 建立版本化机器可读规则 manifest
  -> 从同一 manifest 确定性生成 Markdown 审核清单
  -> 项目所有者逐条审核
  -> 导入 canonical indicators 和正式规则
  -> 严格发布前校验
  -> 单事务批准、生成投影并更新 current_version_id
```

机器可读 manifest 是待审核的结构化内容来源；Markdown 审核清单由 manifest 生成，防止两份内容漂移。只有项目所有者明确批准的条目才允许进入正式规则。

### 5.2 不采用的方案

- 强化后直接批量 materialize 现有候选：当前候选可能丢失性别、多阈值、适用条件或污染单位，不能作为默认正式来源。
- 将全部规则硬编码进一次性 Python 发布脚本：医学内容与生产逻辑耦合，难以逐条审核、比较和后续修订。
- 恢复或修改已删除的脂肪肝误操作版本：该版本已经按项目所有者授权删除；新标准从现有源文档创建全新 draft。

## 6. 核心产物

建议新增以下受版本控制的专项产物：

- `standard_manifests/fatty_liver.v1.json`
- `standard_manifests/ad.v1.json`
- `docs/superpowers/reviews/2026-08-25-fatty-liver-standard-rules-review.md`
- `docs/superpowers/reviews/2026-08-25-ad-standard-rules-review.md`

manifest 顶层至少包含：

- `schema_version`
- `dataset`
- `disease_name`
- `source_document_sha256`
- `target_version_label`
- `review_state`
- `reviewed_at`
- `entries`

`review_state` 初始为 `pending`。只有项目所有者在 Markdown 清单中逐条确认且明确批准整份清单后，才更新为 `approved`。导入命令必须同时验证：

- manifest 的 `review_state == approved`；
- 源 DOCX 哈希与 manifest 一致；
- 所有拟导入条目均具有明确审核结论；
- Markdown 审核清单由当前 manifest 重新生成时无差异。

## 7. 审核条目契约

每条审核项至少包含：

- 稳定 entry ID；
- 疾病与目标版本；
- 源文档哈希；
- 源片段定位，包括段落或表格/行号及原文；
- canonical indicator、英文名、中文名、别名；
- domain、specimen/modality、data type、scale/method、default unit、clinical dimension；
- rule type、比较符、上下界、边界包含性和单位；
- target state type/value；
- abnormal direction；
- sex、age、education、platform、assay method、sample、cohort、framework 等 applicability；
- evidence type、interpretation、priority 和 conflict group；
- 建议 `machine_actionability` 及原因；
- 审核状态 `pending / approved / rejected`；
- 审核备注。

同一指标的正常范围、异常阈值、分级阈值、研究阈值和方向性证据必须作为不同条目保存。多个研究或队列阈值不得合并、平均或互相覆盖。

## 8. Actionability 规则

### 8.1 Calculable

只有同时满足以下条件的条目可以标记为 calculable：

- indicator 身份明确且允许数值比较；
- 数值边界和比较方向完整；
- 开闭区间与原文一致；
- 单位明确且未混入解释文字；
- 原文不是“约”“常见为”“常作正常参考”等近似表达；唯一例外是脂肪肝 ALT、AST、GGT 的明确上下界范围，经项目所有者逐条审核并显式标记 `approximate_boundary_policy=owner_reviewed_strict` 后，可将原文数值按严格边界执行；
- 所有影响安全计算的适用条件均已结构化；
- 规则的疾病专属异常方向明确；
- 已获得项目所有者逐条批准。

### 8.2 Evidence-only

以下内容默认只能作为 evidence-only：

- “约”“常见为”“常作正常参考”“按实验室参考范围”；其中只有满足 8.1 节人工审核覆盖条件的脂肪肝 ALT、AST、GGT 明确范围可以例外升级；
- 单纯升高、降低、影像表现或研究发现；
- 平台、方法、样本、队列、年龄、教育、语言、量表版本或框架信息不足；
- 多研究范围、冲突阈值或不能安全择一的内容；
- 不允许数值比较的定性或分类指标；
- 不能单独用于诊断或分级的解释性内容。

Evidence-only 规则可以发布为标准证据，但不得生成 `reference_ranges` 投影或参与通用数值判断。

### 8.2.1 近似范围人工审核覆盖

近似文本不能因解析器识别出数字而自动成为 calculable。人工审核覆盖必须同时满足：

- 数据集为 `fatty_liver`；
- canonical indicator 仅限 `alt`、`ast`、`ggt`；
- 原文给出完整上下界和明确单位；
- 性别分列已拆成独立规则；
- manifest 和条目均为 approved；
- `applicability.source_language=approximate`；
- `applicability.approximate_boundary_policy=owner_reviewed_strict`；
- 导入时保存 manifest 条目 ID、源哈希和审核时间，生命周期校验可以证明该覆盖来自已批准 manifest。

满足以上条件时，原文中的数值按闭区间严格执行：ALT 男性 `[9, 50] U/L`、ALT 女性 `[7, 40] U/L`、AST `[15, 40] U/L`、GGT 男性 `[10, 60] U/L`、GGT 女性 `[7, 45] U/L`。`约`仍保留在原文、适用性和审核记录中，不得从正式规则中抹除。

该覆盖不得扩展到 BMI 的“常作正常参考”、PLT 的“按实验室参考范围”、AD 认知量表或平台/队列特异生物标志物阈值。未来扩展必须重新进行设计和医学审核。

### 8.3 Blocked

以下条目必须标记为 blocked，并在修正或拒绝前阻止版本发布：

- 解析结构疑似错误；
- 指标身份无法确定；
- 单位、边界或比较方向互相矛盾；
- 原文冲突尚未拆分或解释；
- 条件树不完整或存在循环；
- 规则被建议为 calculable 但缺少必要适用条件。

## 9. 双疾病核心指标与语义

### 9.1 脂肪肝

优先覆盖：

- ALT
- AST
- GGT
- TBIL
- ALB
- PLT
- AFP
- HbA1c
- BMI
- 腰围

要求：

- 每个核心指标均建立明确 canonical indicator，保留中文名和常见别名。
- ALT、AST、GGT 原文中的近似参考范围不能自动转成 calculable；经项目所有者逐条批准并带有 `owner_reviewed_strict` 显式覆盖后，按原文闭区间转成 calculable。
- 性别分列必须拆成独立适用规则；不能只保留第一组数值。
- PLT 等“按实验室参考范围”内容只作为 evidence-only，不补造通用范围。
- 源文档未提供 AFP 等安全规则时，允许记录“无可用规则”，不得从常识或测试数据补造。
- HbA1c、BMI 和腰围的代谢异常规则必须与肝损伤、脂肪变性、纤维化风险等 clinical dimension 分开。
- 脂肪变性规则不得与纤维化风险规则互相替代。

### 9.2 阿尔茨海默病

优先覆盖：

- MMSE
- MoCA
- CDR
- NfL
- p-tau217
- Aβ42/Aβ40

异常方向必须显式区分：

- MMSE、MoCA：分数降低为关注方向；
- CDR：分数升高为关注方向；
- NfL、p-tau217：通常升高为证据方向；
- Aβ42/Aβ40：通常降低为证据方向。

要求：

- 认知量表与生化指标不得共享单一异常方向配置。
- MMSE/MoCA 缺少教育、语言或量表版本条件时，不作为通用诊断阈值。
- CDR 是有序分期量表，不按普通实验室参考范围处理。
- NfL、p-tau217 和 Aβ42/Aβ40 缺少样本类型、平台或方法时，不能作为通用 calculable 规则。
- 队列、平台或研究特异阈值必须拆成独立规则并保留 conflict group。
- 不同队列阈值不得自动择一、合并或平均。

## 10. 组件职责

### 10.1 `standard_parser.py`

- 继续负责 DOCX 原文结构和位置解析。
- 输出候选建议，不创建正式规则。
- 对模糊措辞、性别分列、多阈值和单位列采用保守解析。
- 单元格说明文字不得进入单位字段。
- 无法安全解析时保留原文并标记候选风险，不猜测阈值。

### 10.2 `standard_validation.py`

- 校验 indicator、单位、数值边界、开闭区间和 actionability。
- 校验疾病专属异常方向和 clinical dimension。
- 校验性别、平台、方法、样本、年龄、教育、队列和框架等必要适用条件。
- 校验条件树结构、引用和循环。
- 版本发布要求不存在 blocked 规则或 error。脂肪肝至少存在一条经审核的 calculable 正式规则；AD 允许发布纯 evidence-only 版本，但至少存在一条经审核的 evidence-only 正式规则。
- evidence-only 规则不得计入投影数量。

### 10.3 Manifest 服务与命令

- 定义严格、拒绝额外字段的 manifest schema。
- 从 manifest 确定性生成 Markdown 审核清单。
- 提供默认只读的 lint 和 dry-run 命令。
- 校验源文件哈希、片段定位、核心指标覆盖和审核状态。
- 不提供“接受/导入全部候选”选项。

### 10.4 `standard_lifecycle.py`

- 成为版本发布、退役、候选 materialize 和审计更新的唯一写入口。
- API 和脚本不得直接修改版本状态或 current 指针。
- 候选 materialize、候选状态改为 materialized、正式规则和变更日志必须在同一事务内完成。
- 发布和退役失败时整体回滚。

### 10.5 `standard_resolver.py`

- 只读取 current approved 版本。
- 按 canonical indicator 和 applicability 解析规则。
- 缺少必要上下文时将规则降级为 evidence-only，并返回明确 warning。
- 不自动打破多阈值冲突。
- 返回版本 ID、规则 ID、适用性哈希和实际使用边界。

### 10.6 `longitudinal_evidence.py`

- 将 resolver 的 calculable、evidence-only、unmatched 和 warning 转换为报告证据来源。
- 不将 evidence-only 规则伪装成普通参考范围。
- 保留规则版本、规则 ID、适用性和警告快照。

## 11. 生命周期与数据库三层保护

### 11.1 服务层

生命周期服务必须验证：

- current version 属于同一 standard；
- current version 状态为 approved；
- 只有 review 版本可以发布；
- 空规则、blocked 或存在 error 的版本不得发布；脂肪肝零 calculable 不得发布，AD 零 calculable 时必须至少有一条经审核的 evidence-only 正式规则；
- 单独退役只能处理 approved 版本，并同步清空 current 指针和关闭投影。

### 11.2 数据库层

新增 Alembic revision 和 PostgreSQL 约束触发器，阻止：

- `reference_standards.current_version_id` 指向非 approved 版本；
- current version 指向其他 standard 的版本；
- 将 current version 的状态直接更新为 draft、review 或 retired 而不先更新 current 指针。

触发器应为可延迟约束触发器，允许发布事务在一次提交中完成多表状态切换，并在事务结束前验证终态一致性。迁移不得改写现有医学规则；升级前若发现非法 current 指针，应中止并要求人工处理，而不是自动猜测目标版本。

### 11.3 读取层

resolver 继续检查 current version 的状态和归属。数据库或服务层即使被旁路，读取端也不得使用非法版本。

## 12. 原子发布事务

发布操作必须在单个事务中完成：

1. 锁定标准集合。
2. 锁定目标 review 版本并重新读取规则。
3. 重新执行完整版本校验。
4. 验证疾病级 actionability 门槛：脂肪肝至少一条经审核 calculable 正式规则；AD 可为纯 evidence-only，但至少一条经审核 evidence-only 正式规则；同时不存在 blocked、error 或未解决拟发布条目。
5. 锁定旧 current approved 版本。
6. 将旧版本设为 retired，填写 `retired_at`，并关闭其当前投影。
7. 将目标版本设为 approved，写入批准人、批准时间和生效时间。
8. 只为安全 calculable 规则生成带 provenance 的 `reference_ranges` 投影。
9. 更新标准集合的 `current_version_id`。
10. 写入发布审计记录，包括版本、规则和投影摘要。
11. 单次 commit。

任一步发生异常时 rollback；旧版本、目标版本、投影、current 指针和审计记录均保持事务前状态。

## 13. 退役事务

单独退役当前 approved 版本时必须在单个事务中：

1. 锁定标准集合和当前版本。
2. 验证目标确为该标准的 current approved 版本。
3. 将版本设为 retired 并填写 `retired_at`。
4. 关闭该版本的所有当前投影。
5. 将 `current_version_id` 清空。
6. 写入退役审计记录。
7. 单次 commit。

不允许通过 API 直接将非 current approved 版本退役；非 current approved 版本只能通过发布新版本时自动退役，或由另行设计的数据修复流程处理。

## 14. 数据库写入检查点

### 14.1 检查点一：创建和解析 draft

只有在本设计和实施计划获批后执行：

- 复用当前已解锁的脂肪肝标准文档记录创建全新 draft；
- 将现有 AD DOCX 登记为标准文档，创建 AD 标准集合和全新 draft；
- 解析并保存源片段和辅助候选；
- 不接受候选、不创建正式规则、不提交 review、不发布。

### 14.2 检查点二：导入并发布规则

只有在项目所有者逐条批准两份审核清单后执行：

- 创建或复用审核通过的 canonical indicators；
- 导入审核通过的正式规则和条件；
- 写入审核和变更日志；
- 提交 review；
- 执行原子发布事务并生成投影。

导入命令默认 dry-run。正式执行必须显式指定疾病、manifest、目标版本和执行开关，并再次校验源文件哈希、manifest 审核状态和版本状态。

## 15. 代码修复、医学审核和数据库写入边界

### 15.1 代码修复

- 安全解析模糊文本、性别分列、多阈值和单位。
- 完善 manifest schema、lint、审核清单生成和受控导入。
- 强化规则与版本校验。
- 收口生命周期写入口和事务。
- 增加 current 指针数据库保护。
- 完善 resolver 的适用性和冲突行为。

### 15.2 医学人工审核

项目所有者必须逐条确认：

- canonical indicator 身份、别名和数据类型；
- 数值、单位、比较方向和边界包含性；
- 正常、异常、分级、阶段或证据状态的语义；
- calculable 或 evidence-only 分类；
- 性别、平台、方法、样本、年龄、教育、语言、量表、队列和框架等适用条件；
- 多阈值冲突的拆分和保留方式；
- 源文档未给出安全规则时的明确“无可用规则”结论。

程序不得替代以上医学审核。

### 15.3 正式数据库写入

- 登记 AD 标准文档；
- 创建 AD 标准集合；
- 创建双疾病 draft 和解析片段；
- 创建 canonical indicators；
- 写入审核通过的正式规则、条件和审计记录；
- 发布 approved 版本并生成投影。

## 16. 错误处理

出现以下任一情况必须停止，且不得部分发布：

- 源 DOCX 哈希与 manifest 不一致；
- manifest 或审核清单不是 approved；
- Markdown 重新生成后与审核版本不一致；
- 源片段定位失败或原文不匹配；
- 核心指标缺少明确审核结论；
- 规则校验存在 error 或 blocked 条目；
- calculable 规则数量为零；
- 版本不处于预期 draft/review 状态；
- current 指针、旧投影或版本归属异常；
- 数据库约束、事务或投影写入失败。

工具错误应输出不含数据库连接串、凭据和完整敏感路径的摘要。医学内容不应被工具自动修改以绕过校验。

## 17. TDD 测试策略

### 17.1 解析安全

- “约”“常见为”“常作正常参考”不得自动成为 calculable。
- 已批准的脂肪肝 ALT、AST、GGT 明确近似范围只有携带 `owner_reviewed_strict` 覆盖和 manifest 审核溯源时才成为 calculable；缺少标记、审核时间、条目 ID 或源哈希时仍应拒绝。
- BMI、MMSE、MoCA 和 AD 队列特异阈值即使含数值，也不得通过该覆盖升级。
- “按实验室参考范围”不得生成伪数值边界。
- 表格说明列不得污染单位。
- 性别分列生成独立适用信息。
- 多研究阈值保持独立，不合并或平均。
- `<`、`>`、`≤`、`≥` 和区间开闭性保持原义。

### 17.2 疾病语义

- MMSE/MoCA 下降与 CDR 上升分别解释。
- NfL、p-tau217 和 Aβ42/Aβ40 不复用认知量表方向。
- 缺少教育、语言、平台、方法、样本或年龄信息时按规则降级。
- 脂肪变性、纤维化风险、肝损伤、代谢和功能维度不混用。

### 17.3 Manifest 与审核

- schema 拒绝未知字段和非法状态。
- 源文件哈希变化时 lint 和导入失败。
- 片段定位或原文不匹配时失败。
- 未批准 manifest 或存在 pending 条目时失败。
- Markdown 生成确定且可重复。
- 每个核心指标必须具有 approved、rejected 或明确无可用规则结论。
- 不存在批量导入全部候选的入口。

### 17.4 生命周期与事务

- 空规则、blocked 规则和 validation error 均阻止发布；脂肪肝零 calculable 阻止发布，AD 纯 evidence-only 不阻止发布。
- current 指针不能指向非 approved 或其他标准的版本。
- 退役当前版本必须清空指针、填写 `retired_at` 并关闭投影。
- 发布新版本自动退役旧版本并切换 current。
- 候选 materialize、候选状态和审计日志同事务提交。
- 在旧版本退役、投影插入、current 更新或审计写入各阶段注入失败，验证全部回滚。
- 并发发布同一标准时只有一个版本能够成为 current。

### 17.5 Resolver 与证据

- 缺少必要适用上下文时不进入 calculable 结果。
- 上下文不匹配时进入 unmatched。
- 多个匹配且冲突的阈值不自动择一。
- 结果保留版本 ID、规则 ID、适用性哈希、边界、单位和 warning。
- Evidence-only 不被渲染为普通参考范围。

## 18. 真实环境验收

1. 写入前运行 `python scripts/check_longitudinal_readiness.py`，保存非敏感只读摘要。
2. 对两份 manifest 执行 lint 和 Markdown 重生成检查。
3. dry-run 输出拟新增标准文档、集合、版本、指标、规则、条件和投影数量。
4. 在项目所有者批准相应检查点后执行正式数据库事务。
5. 验证两种疾病的 current version 均属于同一标准且状态为 approved。
6. 验证脂肪肝至少有一条经过审核的 calculable 正式规则；验证 AD 至少有一条经过审核的 evidence-only 正式规则，允许 calculable 和投影数量均为 0。
7. 验证 evidence-only 规则不进入 `reference_ranges` 投影。
8. 验证 resolver 对核心指标返回 calculable、evidence-only 或明确 unmatched/warning。
9. 重新运行 `python scripts/check_longitudinal_readiness.py`。
10. 验证 P0-02 的 `approved_standard_missing` 和 `calculable_standard_rules_missing` 阻塞消失。
11. 验证 P0-04 outcome artifact 缺失仍保持 blocked，避免把标准完成误报为整条纵向链路 ready。
12. 保存非敏感发布摘要，包括文档哈希、标准 ID、版本 ID、规则数量、投影数量和验证命令。

## 19. 完成标准

- 脂肪肝和 AD 均有 current approved 标准版本。
- current version 不可能指向 draft、review、retired 或其他标准的版本。
- 双疾病核心指标均有 canonical indicator 和明确审核结论。
- 脂肪肝至少存在经过审核的 calculable 正式规则；AD 可仅包含经过审核的 evidence-only 正式规则。
- AD 认知量表、生化指标和 CDR 的异常方向彼此独立。
- 平台、方法、年龄、教育等上下文不足时不会执行通用阈值计算。
- 所有正式规则可追溯到源文档哈希和原文片段。
- 发布与退役失败不会留下部分版本、投影、current 指针或审计状态。
- `reference_ranges` 只包含当前 approved 版本的安全 calculable 投影。
- P0-01 readiness 中标准相关阻塞消失，其他路线图任务缺口保持真实可见。

## 19.1 AD 纯 evidence-only 发布例外

- 本例外只适用于当前 `ad` 数据集，不全局取消 calculable 发布门槛，也不新增可配置疾病策略框架。
- AD approved manifest 在核心指标均有明确审核结论、无 pending/blocked/error 且至少有一条 approved evidence-only 正式规则时，可以发布为 approved。
- AD 纯 evidence-only 版本的 `calculable_rule_count` 和 `reference_ranges` 投影数量均允许为 0。
- resolver 和报告只能使用这些规则提供方向、分期、来源、适用性与局限性，不得据此生成数值参考范围或自动正常/异常结论。
- readiness 将该标准记为 `degraded` 并报告 `evidence_only_standard`，但不再报告 P0-02 的 `calculable_standard_rules_missing` blocker；脂肪肝相同行为仍为 blocked。

## 20. 后续流程

1. 项目所有者审核本专项设计文档。
2. 设计文档获批后编写详细实施计划，不立即实现。
3. 实施计划获批后按 TDD 执行代码修复和检查点一。
4. 生成并提交两份规则审核清单。
5. 项目所有者逐条审核规则。
6. 审核清单获批后执行检查点二和真实环境验收。
