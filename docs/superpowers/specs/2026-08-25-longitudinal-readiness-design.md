# 双疾病纵向报告就绪检查与完整性契约设计

## 1. 背景

AI 操作者端已经具备纵向病例、访视、观察特征、结构化预测、报告持久化和 PDF 下载等基础能力，但目前缺少一条能够在生成报告前说明系统是否就绪的统一检查链路。

现有能力存在以下边界：

- `scripts/check_database_readonly.py` 检查 PostgreSQL、扩展、Alembic 和基础列，不了解纵向报告业务条件。
- `scripts/check_model_artifacts.py` 生成模型文件 SHA-256 清单，不判断 artifact 是否符合纵向模型契约。
- `backend/app/services/longitudinal_model_registry.py` 主要按文件存在性加载 artifact，严格 registry 校验属于后续 P0-05。
- `LongitudinalPredictionResult` 描述单次患者预测结果，不适合承载整个系统的报告就绪状态。
- 脂肪肝和阿尔茨海默病的数据、标准、模型缺口不同，不能合并成一个模糊总状态。

本设计对应路线图任务 `P0-01 / longitudinal-readiness-001`，建立独立、只读、可自动测试的双疾病系统体检报告。

## 2. 协作与实施约束

- 本任务由单 Agent 完成，不使用双 Agent 开发、子 Agent 实施或交叉 Agent 评审。
- 本任务采用设计批准、实施计划、测试驱动实现和最终验证的顺序。
- 不把 `AI_COLLABORATION.md` 的双 Agent 流程作为本任务的启动或验收条件。
- 不修改 UI，因此本任务不涉及 `docs/DESIGN_SPEC.md`。

## 3. 目标

1. 提供一条只读命令，分别说明脂肪肝和 AD 的数据、标准、模型及完整报告能力。
2. 为每种疾病输出 `ready`、`degraded` 或 `blocked`，并列出具体原因。
3. 统计参考患者、访视、历史前缀、阳性、阴性、未知和可估计标签数量。
4. 检查当前标准是否存在、是否为 `approved`，以及是否存在正式可计算规则。
5. 独立检查 outcome、stage 和 trend artifact，不修改线上 registry。
6. 定义独立的完整报告能力契约，使程序无需读取 Markdown 正文即可判断报告所需能力是否齐备。
7. 使用稳定 reason code 将缺口映射到后续路线图任务卡。
8. 输出可供人工阅读和 CI 解析的统一 JSON，并使用明确退出码。

## 4. 非目标

- 不修改 `LongitudinalPredictionResult.v1` 或现有线上预测 API。
- 不重构 `longitudinal_model_registry.py`，不把检查结果接入生产推理。
- 不发布或修复参考标准。
- 不训练、启用、重命名或迁移任何模型 artifact。
- 不执行患者级真实预测，不生成报告或 PDF。
- 不修改数据库 schema，不新增 Alembic revision，不写入任何业务数据。
- 不修改前端。
- 不提前实现 P0-02 至 P0-07 的业务能力。

## 5. 方案选择

采用“独立领域服务 + 薄 CLI”方案：

- schema 模块定义稳定输出契约和状态枚举；
- service 模块执行数据、标准、artifact 与报告能力检查并汇总状态；
- CLI 只负责建立只读数据库事务、调用服务、打印 JSON 和返回退出码。

不采用以下方案：

- 单脚本实现：数据库查询、状态聚合、artifact 校验和命令行逻辑会耦合，难以单测和复用。
- 扩展两个现有检查脚本后再拼装：无法自然形成“一条命令、一份契约”，错误语义也会分散。
- 直接扩展线上预测 schema：会提前侵入 P0-05/P0-07 的生产契约并增加兼容风险。

## 6. 文件结构与职责

### 6.1 新增文件

`backend/app/schemas/longitudinal_readiness.py`

- 定义 `longitudinal_readiness.v1` 输出模型。
- 定义疾病状态、检查项状态、原因严重级别和 artifact 状态枚举。
- 校验顶层状态与疾病状态的一致性。
- 保证每种疾病均有独立结果。

`backend/app/services/longitudinal_readiness.py`

- 查询并聚合参考纵向病例。
- 复用 adapter 和现有前缀标签逻辑统计 365 天标签。
- 查询当前标准版本与规则数量。
- 校验 outcome、stage 和 trend artifact。
- 评估完整报告能力并生成 reason code。
- 汇总疾病状态和顶层状态。

`scripts/check_longitudinal_readiness.py`

- 加载项目运行环境。
- 建立显式数据库只读事务。
- 调用 readiness service。
- 将完整 JSON 输出到 stdout。
- 按检查结果返回 `0`、`1` 或 `2`。
- 捕获工具级异常并输出不含敏感信息的最小错误 JSON。

### 6.2 测试文件

`backend/tests/test_longitudinal_readiness_schema.py`

- 验证 schema、状态聚合和报告能力契约。

`backend/tests/test_longitudinal_readiness_service.py`

- 使用可注入查询结果和临时 artifact 目录测试各业务检查。

`scripts/tests/test_check_longitudinal_readiness.py`

- 验证 CLI JSON、敏感信息过滤和退出码。

### 6.3 现有文件

- `scripts/check_model_artifacts.py` 保留现有清单用途；新服务可复用其 SHA-256 函数，不改变既有 CLI 行为。
- `backend/app/services/disease_progression.py` 的 adapter 和 `outcome_label` 规则作为疾病标签语义来源。
- `scripts/train_longitudinal_models.py` 的前缀构造能力可以复用，但 readiness 统计必须同时保留未知标签数量，而不能只看过滤后的训练行。
- `backend/app/schemas/longitudinal_report.py`、`backend/app/services/longitudinal_model_registry.py` 和生产预测链路保持不变。

## 7. 输出契约

顶层 schema 版本固定为：

```text
longitudinal_readiness.v1
```

JSON 顶层结构：

```json
{
  "schema_version": "longitudinal_readiness.v1",
  "generated_at": "2026-08-25T00:00:00Z",
  "overall_status": "blocked",
  "environment": {
    "database_check": "available",
    "alembic_revision": "0010",
    "code_heads": ["0010"]
  },
  "diseases": {
    "fatty_liver": {},
    "ad": {}
  }
}
```

每种疾病至少包含：

- `dataset`：稳定数据集键，固定为 `fatty_liver` 或 `ad`。
- `disease_name`：中文疾病名称。
- `status`：`ready`、`degraded` 或 `blocked`。
- `data`：患者、访视和标签统计。
- `standard`：标准及当前版本状态。
- `models`：outcome、stage、trend 分项诊断。
- `report_contract`：完整报告所需能力检查。
- `available_capabilities`：面向人工阅读的已具备能力。
- `reasons`：稳定编码、中文说明、严重级别和后续任务。
- `next_tasks`：从 reasons 去重并保持路线图顺序的任务列表。

输出始终保留稳定英文机器编码，同时提供中文 `message`。不得只输出中文自由文本，也不得要求使用者阅读服务器日志才能理解结果。

## 8. 状态语义

状态严重度顺序为：

```text
ready < degraded < blocked
```

### 8.1 `ready`

完整报告必需能力和已配置的可选能力均可用，没有降级或阻塞原因。

### 8.2 `degraded`

完整报告必需能力可用，但缺少 stage、trend 等可选增强能力，或存在不会阻止内容完整报告的明确限制。

### 8.3 `blocked`

以下任一条件成立即判为阻塞：

- 疾病或核心参考数据不存在。
- 没有可估计的 365 天结局标签，或可估计标签只有一个类别。
- 没有当前 `approved` 标准。
- 当前 approved 标准没有正式 calculable 规则。
- 缺少兼容的 365 天 outcome artifact。
- 完整报告必需能力契约无效或缺项。

顶层 `overall_status` 取两种疾病中的最高严重度，但疾病明细始终完整保留。

## 9. 数据与标签统计

参考患者身份继续使用：

```text
(source_dataset, patient_label)
```

每种疾病统计：

- `patient_count`
- `visit_count`
- `all_prefix_count`
- `estimable_prefix_count`
- `positive_count`
- `negative_count`
- `unknown_count`
- `source_datasets`
- `real_patient_count`
- `synthetic_patient_count`

历史前缀和 365 天标签必须复用现有疾病 adapter 的最少访视、事件字段与 `outcome_label` 语义。readiness 统计不得另建一套标签规则。

未知标签必须进入统计，不能因训练函数过滤未知标签而消失。阳性、阴性与未知之和必须等于全部前缀数。

来源真实性优先读取显式 `is_synthetic` 元数据。缺少该字段时标记来源状态未知，不根据患者编号猜测真实或合成身份。

## 10. 参考标准检查

每种疾病检查：

- 是否存在 `ReferenceStandard`。
- `current_version_id` 是否存在。
- 当前版本状态是否为 `approved`。
- 当前版本正式 `StandardRule` 数量。
- 当前版本 `machine_actionability = calculable` 的规则数量。
- 当前版本 ID、版本标签和内容哈希。

以下情况均不得视为可用标准：

- 标准不存在。
- current version 为空。
- current version 指向 draft、review 或 retired。
- 当前版本没有正式规则。
- 仅存在解析候选但没有正式规则。
- 正式规则全部为 evidence-only，没有 calculable 规则。

P0-01 只报告问题，不创建规则、不更改生命周期状态、不更新 current version。

## 11. Artifact 检查

### 11.1 检查范围

分别检查：

- 未来 365 天 outcome artifact。
- stage artifact。
- 各关键指标 trend artifact。

outcome 命名使用现有约定：

```text
{dataset}_longitudinal_outcome_365d.joblib
{dataset}_longitudinal_outcome_365d.meta.json
```

stage 和 trend 的精确命名由现有或后续 registry 契约提供；P0-01 不发明可被生产加载的新命名。若当前没有已定义命名，结果明确显示为 `missing` 或 `not_configured`，不得猜测加载路径。

### 11.2 Artifact 状态

- `available`：所有必填校验通过。
- `missing`：模型文件或配套 metadata 不存在。
- `incompatible`：文件存在但不符合契约。
- `disabled`：存在明确禁用配置。
- `not_configured`：系统尚未定义该可选 artifact 的生产契约。

### 11.3 Outcome metadata 必填项

兼容的 365 天 outcome metadata 至少包含：

- `dataset`
- `disease`
- `target`
- `horizon_days`
- `feature_names`
- `feature_version`
- `model_name`
- `model_version`
- `training_dataset_version`
- `sklearn_version`
- `trained_at`
- `artifact_sha256`
- `calibration_status`

校验内容：

- dataset 与当前疾病一致。
- target 为固定窗口 outcome 目标。
- `horizon_days == 365`。
- `feature_names` 为非空且顺序稳定的列表。
- feature version 存在。
- metadata 中哈希与实际 joblib SHA-256 一致。
- joblib 能够在隔离检查中加载。
- 加载对象具备 outcome 推理所需的 `predict_proba` 接口。
- sklearn 版本信息存在；兼容策略本步只报告，不改线上依赖。

检查脚本不调用模型对患者进行预测，也不将加载结果注册到生产 registry。

## 12. 完整报告能力契约

P0-01 定义独立的能力检查，不修改患者预测 schema。能力项分为必需和可选。

### 12.1 必需能力

- `case_identity`
- `input_scope`
- `data_quality_explanation`
- `observed_longitudinal_changes`
- `outcome_365d`
- `reference_standard_interpretation`
- `key_progression_signals`
- `evidence_sources`
- `limitations`
- `manual_review_items`
- `persistence_and_history`
- `pdf_delivery`

P0-01 检查当前代码契约是否具有承载这些章节的结构位置，以及依赖数据、标准或模型是否可用。它不要求 P0-01 自己生成这些章节。

### 12.2 可选能力

- `stage_projection`
- `next_followup_trend_model`
- `calibrated_probability`

可选能力缺失不会单独阻塞完整报告，但必须产生降级说明，且不得被伪装为已有能力。

### 12.3 能力状态

- `available`
- `degraded`
- `blocked`
- `not_applicable`

每个能力项包含中文说明和依赖 reason code，便于后续 P0-02 至 P0-07 逐项消除缺口。

## 13. Reason code 与任务映射

首批阻塞 reason code：

| Code | 中文含义 | 后续任务 |
| --- | --- | --- |
| `disease_not_found` | 数据库中缺少疾病 | `P0-01` |
| `reference_data_missing` | 缺少参考患者或纵向访视 | `P0-01` |
| `estimable_labels_missing` | 没有可估计的 365 天标签 | `P0-03` |
| `label_class_missing` | 可估计标签只有一个类别 | `P0-03` |
| `approved_standard_missing` | 没有当前 approved 标准 | `P0-02` |
| `calculable_standard_rules_missing` | 当前标准没有可计算正式规则 | `P0-02` |
| `outcome_model_missing` | 缺少 365 天结局模型 | `P0-04` |
| `outcome_model_incompatible` | 结局 artifact 与契约不匹配 | `P0-04` 或 `P0-05` |
| `report_contract_invalid` | 完整报告必需能力契约缺失 | `P0-07` |

首批降级 reason code：

| Code | 中文含义 | 后续任务 |
| --- | --- | --- |
| `stage_model_missing` | 阶段模型未配置或缺失 | `P2-01` |
| `trend_models_missing` | 下一次随访趋势模型缺失 | `P2-02` |
| `model_not_calibrated` | 模型分数尚未校准 | `P2-03` |
| `traceability_incomplete` | 模型或规则追溯字段不完整 | `P1-04` |

工具级错误使用：

- `database_unavailable`
- `runtime_error`

工具级错误不伪装成某种疾病的普通业务缺口。

## 14. 数据流

```text
CLI 启动
  -> 加载数据库配置和模型目录
  -> 建立事务并执行 SET TRANSACTION READ ONLY
  -> 读取疾病、参考病例、标准和报告存储能力
  -> 按患者聚合访视
  -> 复用 adapter 构造历史前缀和 365 天标签
  -> 独立校验模型文件与 metadata
  -> 评估完整报告必需/可选能力
  -> 为脂肪肝和 AD 分别聚合状态与原因
  -> 聚合 overall_status
  -> 回滚只读事务
  -> 输出 JSON
  -> 返回退出码
```

数据库读取和文件系统 artifact 检查相互独立。某一个 artifact 失败只影响对应模型项；一种疾病存在业务阻塞时，另一种疾病仍输出完整结果。

## 15. 错误处理与信息安全

### 15.1 正常业务缺口

数据、标准或模型缺失属于成功完成检查后的业务结果：

- 输出完整 JSON。
- 对应疾病判为 `blocked` 或 `degraded`。
- 不输出 Python traceback。
- 退出码为 `1`，仅当任一疾病为 `blocked`。

### 15.2 工具运行失败

数据库无法连接、无法建立只读事务、配置无效或未处理异常属于工具级失败：

```json
{
  "schema_version": "longitudinal_readiness.v1",
  "overall_status": "error",
  "error": {
    "code": "database_unavailable",
    "message": "无法完成纵向报告就绪检查"
  }
}
```

工具级错误：

- 退出码为 `2`。
- 不包含数据库 URL、密码、用户名、患者编号、完整文件系统敏感路径或 traceback。
- 详细异常仅用于本地调试日志；默认 CLI JSON 不输出异常正文。

### 15.3 只读保证

- CLI 在业务查询前执行 `SET TRANSACTION READ ONLY`。
- 查询结束无论成功或失败都回滚事务。
- service 不调用 ORM `add`、`delete`、`flush` 或 `commit`。
- artifact 检查只读取文件。
- 测试验证只读事务初始化和无写入调用。

## 16. CLI 与退出码

命令：

```powershell
python scripts/check_longitudinal_readiness.py
```

stdout 始终输出 JSON，不混入普通日志或进度文本。

退出码：

| 退出码 | 含义 |
| ---: | --- |
| `0` | 检查完成，两种疾病均为 `ready` 或 `degraded` |
| `1` | 检查完成，至少一种疾病为 `blocked` |
| `2` | 检查工具未能完成运行 |

PowerShell 可以通过 `$LASTEXITCODE` 读取退出码，CI 也可直接据此判断。

## 17. 测试策略

### 17.1 Schema 测试

- schema version 固定为 `longitudinal_readiness.v1`。
- 脂肪肝和 AD 都必须存在独立结果。
- 顶层状态等于疾病状态中的最高严重度。
- `next_tasks` 与 reasons 一致并去重。
- 未知字段按明确策略拒绝，防止契约静默漂移。

### 17.2 数据与标签测试

- 患者按 `(source_dataset, patient_label)` 聚合。
- 同一患者多次访视只计为一个患者。
- 全部前缀等于阳性、阴性和未知之和。
- 未知标签不会被误记为阴性。
- 零个可估计标签产生 `estimable_labels_missing`。
- 只有阳性或只有阴性产生 `label_class_missing`。
- 脂肪肝与 AD 使用各自 adapter 的事件字段和阶段语义。
- 合成来源只依据显式元数据统计，不根据编号猜测。

### 17.3 标准测试

- 没有标准产生 `approved_standard_missing`。
- current version 为空产生阻塞。
- current version 为 retired、draft 或 review 不能通过。
- approved 但无正式规则不能通过。
- approved 且只有 evidence-only 规则产生 `calculable_standard_rules_missing`。
- approved 且具有 calculable 规则时标准项可用。

### 17.4 Artifact 测试

- 模型和 metadata 同时缺失判为 `missing`。
- 只存在其中一个文件判为 `incompatible`。
- metadata 缺必填字段判为 `incompatible`。
- dataset、target 或 horizon 错误判为 `incompatible`。
- feature names 为空或 feature version 缺失判为 `incompatible`。
- SHA-256 不匹配判为 `incompatible`。
- joblib 无法加载判为 `incompatible`。
- 缺少 `predict_proba` 判为 `incompatible`。
- stage/trend 缺失只产生降级原因。
- 检查过程不执行患者预测。

### 17.5 CLI 测试

- 两种疾病均 ready/degraded 时退出 `0`。
- 任一疾病 blocked 时退出 `1`。
- 数据库连接或工具异常时退出 `2`。
- stdout 是单一合法 JSON 文档。
- 输出不包含连接串、密码、患者编号或 traceback。
- 显式建立只读事务并最终回滚。

### 17.6 回归与真实环境验证

- 运行新增 schema、service 和 CLI 测试。
- 运行现有 longitudinal registry、prediction contract、训练辅助和数据库只读检查测试。
- 对当前本地 PostgreSQL 执行真实只读命令。
- 验证数据库 revision/head 均为 `0010`。
- 验证当前缺少 approved 标准和 365 天 outcome 模型时，两种疾病均明确为 `blocked`。
- 验证当前已有患者、访视和标签统计仍完整输出。

## 18. 当前基线的预期结果

根据 2026-08-25 的只读核验：

- 脂肪肝有 300 名参考患者、1354 次访视、1054 个历史前缀；当前标签逻辑得到 146 个阳性和 908 个阴性可估计前缀。
- AD 有 300 名参考患者、1365 次访视、1065 个历史前缀；当前标签逻辑得到 155 个阳性和 910 个阴性可估计前缀。
- 脂肪肝 current version 指向 retired 版本，正式规则和 calculable 规则均为 0。
- AD 当前没有参考标准。
- 模型目录仅存在旧版最终结局模型，不存在完整报告要求的 365 天 outcome、stage 和 trend artifact。

因此当前预期：

- `fatty_liver.status = blocked`
- `ad.status = blocked`
- `overall_status = blocked`
- 退出码为 `1`
- 主要后续任务至少包含 `P0-02` 和 `P0-04`

这些数值是设计时基线，不在测试中作为永久固定常量；真实检查每次重新读取当前环境。

## 19. 路线图记录与完成条件

完成 P0-01 后，在总领路线图的任务标题下记录：

- 状态 `completed`。
- Task-ID `longitudinal-readiness-001`。
- 本设计文档路径。
- 实施计划路径。
- 验证命令和结果摘要。

不得把两种疾病标记为 `ready`，除非实际检查满足严格状态语义。路线图更新记录任务已完成，不代表 P0 后续业务阻塞已经消除。

## 20. 验收标准

1. 一条命令输出脂肪肝和 AD 的独立系统体检结果。
2. JSON 包含数据、标签、标准、模型、报告能力、原因和后续任务。
3. 状态严格遵循 `ready / degraded / blocked` 语义。
4. 缺少 approved 标准或兼容的 365 天 outcome 模型时判为 `blocked`。
5. stage/trend 缺失只作为可选能力降级，不覆盖更严重的阻塞状态。
6. artifact 文件、metadata、哈希、加载能力和推理接口得到只读诊断。
7. 不修改线上 registry、患者预测 schema、数据库、标准、模型或前端。
8. CLI 退出码 `0/1/2` 与设计一致。
9. 工具级错误不泄露数据库配置、患者身份或 traceback。
10. 自动测试和当前 PostgreSQL 只读验证通过。
11. 当前环境能够明确输出两种疾病为何尚未具备完整报告条件。
12. 路线图记录 P0-01 的完成状态和实际验证证据。
