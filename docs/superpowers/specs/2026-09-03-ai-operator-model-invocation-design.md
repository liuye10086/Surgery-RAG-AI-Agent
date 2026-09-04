# AI 操作者第 4 项：调用当前疾病模型——设计说明

## 背景与目标

AI 操作者流程的第 1–3 项和附录 12 项已经完成仓库侧实现。本设计覆盖第 4 项“调用当前疾病模型”，范围仅限脂肪肝和阿尔茨海默病（AD）的电脑端 AI 操作者报告链路。

目标是让当前 active release set 按稳定的生产运行方式参与报告生成，同时保持模型审计信息真实可追溯。当前模型使用合成演示数据训练，未校准且没有临床有效性声明；这些事实不得阻止工程链路运行，也不得在报告中被表述为已经完成临床验证。

## 已有能力与本次缺口

### 已有能力

- 疾病代码可路由到 `fatty_liver` 或 `ad`，两病种使用独立的 active 指针和 release set。
- release set、模型 artifact、metadata、evaluation 和数据清单已有哈希链校验。
- 结局、阶段和趋势模型已有独立执行路径；结局任务按基线阶段选择。
- 单个趋势模型失败可隔离，阶段模型失败不会猜测阶段。
- 报告保存 release set ID、数据版本和输入快照；历史报告不重新调用模型。
- 模型加载异常、超时和取消已有报告状态收敛逻辑。

### 本次补齐

1. 阶段/趋势模型与结局模型统一执行 metadata 的 `required_features` 和 `allowed_missing_features` 契约。
2. active release set 加载前校验病种、必需任务集合、生命周期和完整 bundle，禁止不完整模型组进入运行态。
3. 增加按 release-set 身份和哈希失效的进程内模型缓存，避免每次报告重复反序列化。
4. 明确“运行可用”和“临床有效性声明”是两个独立状态：active 指针授权运行，`audit` 字段控制报告中的警告和限制说明。
5. 增加输入契约、release set 完整性、缓存失效、并发首次加载和失败收敛测试，并同步核查文档。

## 架构与数据流

```text
病例疾病
  → 疾病能力注册表
  → active 指针
  → release set 完整性/哈希校验
  → 版本化模型组缓存
  → 每个模型的统一输入契约校验
  → 结局/阶段/趋势推理
  → 结构化 prediction_result
  → 报告渲染与持久化
```

### 模型运行授权

- active 指针是当前运行授权来源。只要指针、release set、模型文件和哈希链完整，当前模型可以参与报告。
- 当前 artifact 的 `production_enabled=false` 不作为运行阻断条件；该字段和 `audit.synthetic_in_formal_metrics`、`audit.clinical_validity_claim`、校准状态一起作为审计信息进入报告。
- 报告必须继续说明合成数据、未校准分数和无临床有效性声明，不得把模型分数写成诊断或临床概率。

### Release set 完整性

加载器必须确认：

- release set 的 dataset 与请求病种一致；
- release set 状态处于允许运行的生命周期；
- bundle 集合与该病种的 `REQUIRED_TASKS` 完全一致；
- 每个 bundle 的 artifact type、task、indicator 与 metadata 一致；
- 模型、metadata、evaluation、manifest、数据文件和 split 文件哈希全部通过；
- release set 记录哈希与 active 指针哈希一致。

任何一项失败都返回稳定的模型不可用状态，不加载部分模型组。

### 输入特征契约

阶段和趋势模型必须与结局模型一样，通过统一的 metadata 顺序构造 `pandas.DataFrame`：

- 特征列严格按 `feature_names` 排列；
- `required_features` 缺失返回 `required_feature_missing`；
- 只允许 `allowed_missing_features` 为空值；
- 数值特征必须是有限数字；
- 病例年龄、性别、基线阶段和访视时间线使用前序统一校验结果；
- 不修改原始病例或访视数据来“补齐”模型输入。

## 缓存设计

缓存位于模型注册/加载服务内部；不同 registry root 使用独立命名空间，每个命名空间内的键为：

```text
(dataset, release_set_id, release_set_sha256)
```

规则：

- 同一进程内同一键只加载一次模型文件；
- 不同 registry root 即使模型身份相同也不得共享缓存对象；
- active 指针的 release set ID 或 SHA-256 变化时，旧缓存不可命中；
- 首次读取的 active 指针与加载完成的 suite 身份不一致时返回 `active_pointer_changed`，不得把 suite 写入旧键；
- 首次加载使用线程安全的单飞（single-flight）保护，避免并发请求重复反序列化；
- 缓存只保存已完成完整性校验和 `joblib.load` 成功的不可变模型组；失败结果不缓存为可用模型；
- 缓存不改变报告的版本追溯，prediction 仍保存实际使用的 release set ID、记录哈希和数据版本。

## 错误处理与安全降级

### 调用前阻断

以下情况不调用模型：疾病不支持或停用、active 指针或 release set 无效、必需 bundle 缺失、输入契约不满足、访视不足或基线阶段没有适用结局任务。API 返回稳定错误码和中文消息，例如 `model_unavailable`、`required_feature_missing`、`insufficient_visits`、`prediction_not_applicable`。

### 单模型失败

- 结局模型失败：不输出风险分数；
- 阶段模型失败：不输出下一阶段猜测；
- 单个趋势模型失败：其他趋势结果继续保留；
- 所有状态写入 `model_status`，并将失败原因限制为稳定 reason code。

### 整体失败

- 模型加载、推理超时或报告持久化异常：`generating → failed`；
- 用户取消：`generating → cancelled`；
- 已完成或已失败报告不得被重复覆盖；
- SSE 只返回安全错误码和安全文案，内部异常仅记录 `case_id`、`report_id`、阶段和稳定错误码。

## 代码边界

- `backend/app/services/longitudinal_model_registry.py`：release set 完整性、版本缓存、缓存失效和模型组加载。
- `backend/app/services/longitudinal_features.py`：统一模型输入契约入口。
- `backend/app/services/longitudinal_prediction.py`：阶段/趋势使用统一特征构造，并区分契约错误与执行错误。
- `backend/app/services/operator_case_readiness.py`：提前反映活动模型组和输入契约是否可用。
- `backend/tests/`：新增契约、release set、缓存、并发和失败收敛测试，保留现有回归。
- `docs/AI操作者流程核查.md`：同步第 4 项的真实完成状态和生产部署门禁。

本设计不新增数据库字段或迁移；报告版本和输入快照继续使用现有字段。

## 测试与验收

必须通过以下验收：

1. 脂肪肝和 AD 只能加载自己的完整 release set，缺 bundle、错病种或哈希错误会整体拒绝。
2. 阶段/趋势模型缺必填特征时不执行模型，并返回 `required_feature_missing`。
3. active 指针版本不变时模型文件只加载一次；指针 ID 或哈希变化后下一次请求加载新模型。
4. 并发首次请求不会重复加载同一 release set。
5. 合成模型仍能生成结构化结果，但报告包含合成数据、未校准和无临床有效性声明。
6. 单趋势/阶段失败不会产生假预测；整条异常不会留下 `generating` 报告。
7. 第 4 项专项测试、后端完整回归和生产构建通过。
8. 核查文档、代码行为和测试结果一致，并明确真实 PostgreSQL 迁移、浏览器 E2E 和部署冒烟仍需在部署窗口执行。

## 非目标与后续边界

- 本次不重新训练模型、不声称模型具备临床有效性、不修改标准或参考病例检索逻辑。
- 本次不改变历史报告内容，不对旧报告重新推理。
- 真实临床数据接入、模型校准、外部验证和模型审计属于后续模型发布流程。
