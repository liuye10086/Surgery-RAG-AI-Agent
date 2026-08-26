# P0-05 纵向模型 Registry、状态与推理契约设计

> 日期：2026-08-26  
> 状态：设计已获项目所有者明确通过  
> 路线图任务：P0-05 统一模型 registry、状态和推理契约

## 1. 设计结论

P0-05 建立一个唯一、任务级、严格校验的纵向模型 registry。正式纵向结局任务固定为：

```text
fatty_liver.pre_cirrhosis_to_progression
fatty_liver.cirrhosis_to_hcc
ad.pre_dementia_to_dementia
```

registry 统一负责任务路由、artifact 发现、静态验证、运行时加载和状态解释。正式推理、readiness 检查、`scripts/check_model_artifacts.py` 以及临时 review/enable 流程必须复用同一验证器，不能继续各自维护不同规则。

旧 `/progression-predictions` 和 `progression_engine.py` 保持既有语义，继续只使用旧 `*_progression_model.*`。新 registry 明确忽略这些旧 artifact，不将其重命名或冒充新的 365 天纵向 outcome 模型。

P0-05 不训练 stage/trend 模型，不修改数据库 schema，不删除旧脚本、旧模型或旧接口。除已批准补充现有 `baseline_stage` 选择框外，不扩大前端范围。

## 2. 已核查基线与实际差距

### 2.1 仓库和产物状态

- 核查基线为 `main`、提交 `6bf7fdf`，与 `origin/main` 一致。
- 工作区已有用户改动 `outputs/report_method_validation.md`，P0-05 不覆盖该改动。
- `backend/app/ml_models/` 当前只有旧的脂肪肝和 AD `*_progression_model.*`，没有 P0-04 的 365 天 candidate。
- P0-04 candidate 位于 `.tmp`，状态均为 `candidate`、`production_enabled=false`。
- 当前相关回归实测为 `42 passed, 1 warning`，说明旧链路目前可运行，但不代表满足 P0-05。

### 2.2 当前实现差距

1. `longitudinal_model_registry.py` 仍按 disease 查找一个笼统 outcome 文件，不能路由脂肪肝两个任务。
2. registry 只检查文件存在，缺少严格 metadata、hash、生命周期和环境兼容校验。
3. readiness、registry 和 artifact checker 使用不同文件名和字段集合，没有唯一事实来源。
4. `longitudinal_prediction.py` 不读取 `baseline_stage`，无法证明任务适用性。
5. 当前线上特征构建使用 `summarize_observation()`，与 P0-04 fixed-window 特征语义不同。
6. outcome、stage、trend 没有独立结构化状态，失败原因主要依赖笼统 warning。
7. 当前无 trend 模型时会把观察斜率放入“未来趋势预测”，模型预测和观察事实没有清楚区分。
8. 报告生成失败时直接持久化和返回 `str(exc)`，存在暴露内部信息的风险。
9. P0-04 当前 candidate metadata 缺少 P0-05 正式加载所需的完整任务、窗口、包版本、artifact hash、模型标识和完整性闭环，不能直接启用。

## 3. 总体架构

正式加载顺序固定为：

```text
验证基线阶段并选择任务
  → 从任务级 registry 发现发布记录
  → 验证生命周期和启用状态
  → 静态验证 metadata、文件名、任务、特征、hash 和环境
  → 仅在全部静态检查通过后反序列化模型
  → 验证已加载对象的静态接口
  → 构建并校验本次病例特征
  → 调用模型
```

每一步返回结构化结果。正常的缺失、禁用或不兼容不使用空字典或笼统异常表达。

### 3.1 组件职责

- **任务路由器**：只根据疾病和经过验证的 `baseline_stage` 选择 outcome 任务。
- **artifact 验证器**：执行唯一的静态契约检查，不调用 `predict` 或 `predict_proba`。
- **registry 加载器**：只加载验证通过且已启用的 artifact，并返回结构化状态。
- **发布管理器**：在独立显式命令中执行 review/enable，生成可审计记录。
- **推理输入构建器**：使用 P0-04 fixed-window 特征语义和 metadata 中的特征契约构建一行输入。
- **纵向预测服务**：分别处理 outcome、stage、trend，不让单个模型失败阻断整份报告。
- **报告渲染器**：根据结构化状态准确说明哪些模型实际参与本次报告。

## 4. 生命周期与运行时状态

必须严格区分两组语义：

```text
artifact 生命周期：candidate | reviewed | enabled
运行时加载状态：available | missing | incompatible | disabled
```

映射规则：

- `candidate` 和 `reviewed` 在生产加载模式下均返回 `disabled`。
- `enabled` 且 `production_enabled=true` 只是继续验证的必要条件。
- enabled artifact 出现任务、hash、特征或环境问题时返回 `incompatible`。
- 只有完整验证通过并成功加载时才返回 `available`。
- artifact 文件或发布记录不存在时返回 `missing`。

`not_estimable` 只描述“本次病例是否能估计”，不加入 artifact 的四种运行时状态。例如基线阶段不确定时，artifact 本身可能存在，但本次 outcome 路由为 `not_estimable`，outcome 运行状态对本次报告表现为 `disabled`。

## 5. 任务路由与基线阶段

### 5.1 核心规则

系统只使用病例的疾病和 `baseline_stage` 选择任务，不根据指标值、观察趋势、notes、LLM 输出或旧模型结果猜测当前阶段。

脂肪肝：

- 未肝硬化：选择 `fatty_liver.pre_cirrhosis_to_progression`。
- 已肝硬化：选择 `fatty_liver.cirrhosis_to_hcc`。
- 已 HCC：终末阶段，本任务不适用。
- 疑似肝硬化：明确识别为阶段不确定，不在两个模型之间猜测。

AD：

- normal、MCI 或其他明确的痴呆前阶段：选择 `ad.pre_dementia_to_dementia`。
- 已 dementia：终末阶段，本任务不适用。
- 不建立或推断新的多阶段 CDR 任务。

### 5.2 规范值与兼容别名

新前端保存规范值；后端保留有限别名用于兼容既有自由文本：

| 疾病 | 规范值 | 含义 |
|---|---|---|
| 脂肪肝 | `pre_cirrhosis` | 未肝硬化 |
| 脂肪肝 | `cirrhosis` | 已肝硬化 |
| 脂肪肝 | `suspected_cirrhosis` | 疑似肝硬化，阶段不确定 |
| 脂肪肝 | `hcc` | 已肝癌/肝细胞癌 |
| AD | `normal` | 认知正常但尚未痴呆 |
| AD | `mci` | 轻度认知障碍但尚未痴呆 |
| AD | `pre_dementia` | 其他明确痴呆前状态 |
| AD | `dementia` | 已痴呆 |

允许有限、明确登记的中英文别名，例如“未肝硬化”“肝硬化”“疑似肝硬化”“认知正常”“轻度认知障碍”“痴呆”。不做模糊包含匹配，不把 `S1`、CDR 数值或任意说明文字自动转换成阶段。

### 5.3 路由结果和稳定原因

路由器返回 `selected` 或 `not_estimable`，并至少使用以下稳定 reason code：

- `task_selected`
- `baseline_stage_missing`
- `baseline_stage_unknown`
- `baseline_stage_uncertain`
- `baseline_stage_conflict`
- `baseline_stage_disease_conflict`
- `task_not_applicable_terminal_stage`

路由未成功时不发现、不加载和不调用 outcome 模型，`risk_score` 与 `risk_band` 必须为空。观察事实、参考标准、证据以及可用的其他章节继续生成。

### 5.4 前端补充

当前数据库和后端已存在 `baseline_stage`，但 `LongitudinalCaseEditor.vue` 没有输入控件，保存病例时也没有发送该字段。P0-05 增加疾病感知的 `el-select`，只保存上述规范值，不增加数据库字段。

控件复用现有病例编辑区、Element Plus 和 `docs/DESIGN_SPEC.md` 中的 CSS 变量、间距、圆角和无障碍规范。疾病切换导致当前阶段选项不再适用时，前端清空该值并要求重新选择，不能静默映射。

## 6. Artifact 和发布记录契约

### 6.1 文件命名与任务对应

任务级模型使用固定 stem：

```text
fatty_liver_pre_cirrhosis_to_progression_365d
fatty_liver_cirrhosis_to_hcc_365d
ad_pre_dementia_to_dementia_365d
```

模型文件为 `<stem>.joblib`，metadata 为 `<stem>.meta.json`。文件名必须与 metadata.task 唯一映射。`*_progression_model.*` 和笼统的 `<dataset>_longitudinal_outcome_365d.*` 不属于新任务级 outcome registry。

### 6.2 Metadata 最低要求

重新导出的 P0-05 合格 candidate metadata 至少包含：

- metadata schema/version；
- artifact type；
- task、dataset、disease、current state、target、horizon 365 天；
- feature schema/version；
- feature names、顺序、数量和 feature order hash；
- 必需输入、允许缺失特征、填补规则和输入容器类型；
- dataset schema、manifest hash、data content hash、训练文件 hash；
- model artifact SHA-256；
- model ID/name、model version、算法类型；
- Python、sklearn、joblib、NumPy、pandas 等构建兼容信息；
- score semantics、阳性类别语义、阈值；
- calibration status 和 calibration method；
- 训练审计、泄漏审查和临床有效性声明状态；
- candidate 创建时间和代码版本；
- `status=candidate`、`production_enabled=false`。

### 6.3 可验证的完整性闭环

模型文件保持不可变。candidate metadata 记录模型 SHA-256；独立的 review/enable 发布记录同时记录模型 SHA-256 和 metadata SHA-256。registry 只有在三者闭环一致时才允许加载：

```text
发布记录 → metadata SHA-256
发布记录 → model SHA-256
metadata  → model SHA-256
```

这样无需在 metadata 内保存无法稳定计算的“自身 hash”，同时可以发现模型、metadata 或发布记录被单独替换。

### 6.4 当前 P0-04 candidate 的处理

当前 P0-04 模型文件保留不动。由于其 metadata 不满足 P0-05 的完整验证要求，不能直接启用。

P0-05 在新的 `.tmp` 目录中，使用已经批准的 P0-03 数据和 P0-04 训练流程重新导出契约完整的 candidate，用于 review、enable、load 和真实推理 smoke test。这不是重命名旧 artifact，也不把旧文件补写后冒充新 artifact。未经项目所有者批准，不把任何 candidate 写入 `backend/app/ml_models/` 或生产 registry。

## 7. 严格验证与 reason code

验证顺序必须保证在 hash、环境和生命周期通过前不反序列化模型：

1. 发布记录、模型文件和 metadata 是否存在且唯一；
2. JSON/schema 是否可读取；
3. 生命周期和 `production_enabled` 是否允许当前加载模式；
4. 文件名、artifact type 和 task 是否一致；
5. dataset/disease/current state/target/horizon 是否匹配任务规范；
6. feature schema/version、名称、顺序、数量和 order hash 是否一致；
7. dataset/manifest/data/training file hash 是否格式有效并符合发布契约；
8. model hash、metadata hash 和发布记录是否形成完整闭环；
9. score、阳性类别、threshold 和 calibration 语义是否完整；
10. 当前 Python/package 版本是否满足 metadata 的兼容约束；
11. 静态检查全部通过后执行 `joblib.load`；
12. 只检查已加载对象的 pipeline 类型、预处理器、`predict_proba` 和 `classes_` 等静态接口，不执行患者预测。

至少定义以下稳定 reason code：

- `artifact_missing`
- `metadata_missing`
- `release_record_missing`
- `metadata_invalid`
- `metadata_schema_mismatch`
- `artifact_type_mismatch`
- `filename_task_mismatch`
- `task_mismatch`
- `dataset_mismatch`
- `disease_mismatch`
- `target_mismatch`
- `horizon_mismatch`
- `feature_schema_mismatch`
- `feature_names_invalid`
- `feature_order_mismatch`
- `dataset_hash_mismatch`
- `artifact_hash_mismatch`
- `metadata_hash_mismatch`
- `integrity_chain_broken`
- `package_incompatible`
- `score_semantics_invalid`
- `calibration_contract_invalid`
- `lifecycle_not_enabled`
- `production_disabled`
- `multiple_enabled_artifacts`
- `artifact_load_failed`
- `model_interface_incompatible`
- `legacy_progression_artifact_ignored`

同一任务存在多个 enabled 发布记录时，整个任务返回 `incompatible/multiple_enabled_artifacts`，不按时间、文件名或目录顺序自动选择。

## 8. Review 和 Enable 边界

训练 CLI 只能生成 `candidate`，不得审核、启用、更新生产 registry 或写入生产模型目录。

P0-05 增加独立、显式的管理入口，逻辑上分为：

```text
review candidate → create reviewed audit record
enable reviewed  → create enabled release record
```

review 必须验证 candidate 契约并记录：审核人、审核时间、审核说明、model hash、metadata hash 和审核结果。

enable 必须重新验证全部契约、审核记录和 hash，并确认同任务不存在另一个 enabled 发布记录。若已存在 enabled 模型，操作失败，不静默覆盖。

review/enable 使用文件式 registry，不新增数据库表：

- 每个 candidate bundle 位于独立目录，模型和 metadata 保持不可变；
- review 创建新的、不可变的审核记录文件；
- enable 创建新的、不可变的发布记录文件；
- 文件先写入同目录临时文件，再原子改名为最终名称；最终名称已存在时拒绝操作；
- 发布记录只使用 registry 根目录内的相对路径，拒绝目录穿越和指向 registry 外部的文件；
- 生产加载器以发布记录为入口，不通过扫描任意 joblib 文件自动启用模型。

管理 CLI 必须显式提供 candidate bundle 和 registry 根目录，不设置自动指向 `backend/app/ml_models/` 的危险默认发布行为。它不修改 joblib 模型内容。

P0-05 只在 `.tmp` 中完成完整管理流程 smoke test。未经项目所有者明确批准具体候选模型，不执行生产发布。

## 9. 实际推理输入契约

### 9.1 当前线上真实输入

AI 操作者纵向病例当前能够提供：

- 病例所属疾病；
- `sex`，允许为空；
- 新增前端选择后的 `baseline_stage`；
- 2 至 10 次访视日期；
- 每次访视的指标名称、有限数值和单位；
- 可选 notes，但 notes 不参与任务路由或模型特征。

当前 `operator_cases`、后端 schema、前端编辑器和 input snapshot 均没有 age。age 只存在于参考/训练病例的 `metadata.patient_age` 中。

### 9.2 Age 和缺失值处理

P0-05 不新增 age 数据库字段，也不从患者标签、notes、疾病名称、指标或参考病例猜年龄。线上推理的 age 明确为缺失。

只有当 artifact 同时满足以下条件时，age 缺失才允许进入模型：

- metadata 明确将 age 列入允许缺失的特征；
- metadata 记录训练时的填补方法；
- 已加载 pipeline 的预处理器与该填补契约一致；
- 输入构建器以规范缺失值交给该 pipeline，而不是伪造年龄。

sex 缺失以及个别指标缺失遵循相同原则。metadata 声明为必需且不可填补的特征缺失时，拒绝本次模型调用。

### 9.3 特征构建

推理必须使用与 P0-04 相同的 fixed-window 特征语义：

- `visit_count`；
- `observation_span_days`；
- `days_since_previous_visit`；
- 各指标的 first、last、minimum、maximum、mean、delta、time slope、recent delta、rise/fall count、observation count 和 missing ratio；
- sex；
- age 缺失值。

输入以 metadata.feature_names 的精确顺序构建，并使用模型训练时的容器类型，例如带列名的单行 pandas DataFrame。不得继续用当前只支持旧 `indicator.stat` 子集的 `build_feature_vector()` 作为 P0-04 outcome 输入。

outcome 模型要求至少 3 次访视。访视不足、任务不适用、特征契约不匹配、必需特征缺失或非法非有限输入时，不调用模型、不输出分数，但报告其他章节继续生成。

## 10. 结构化预测状态和最终报告

AI 操作者最终报告生成前，系统会先保存机器可读的 `prediction_result`。P0-05 将其升级为 `longitudinal_prediction.v2`，并增加 outcome、stage、trend 各自的模型状态。

outcome 状态至少记录：

- task；
- runtime status；
- reason code；
- lifecycle status；
- model ID/name 和 model version；
- model artifact SHA-256；
- target 和 horizon；
- feature version；
- score semantics；
- calibration status。

规则：

- outcome 不可用时，`risk_score` 和 `risk_band` 必须为空。
- stage 不可用时，不输出下一阶段猜测。
- trend 模型不可用时，不生成未来趋势预测；已经观察到的升降趋势仍保留在 observation 章节，明确称为“已观察趋势”。
- outcome、stage、trend 互不阻断，一个模型失败不影响观察、参考标准、证据和其他可用章节。
- `warnings` 只保存适合用户阅读的说明；稳定判断依赖结构化 reason code。

最终中文报告据此准确显示，例如：

```text
365 天结局模型：未启用，因此未计算风险分数。
阶段模型：尚未配置，因此未预测下一阶段。
趋势模型：尚未配置，仅展示已观察到的 ALT 上升趋势。
```

历史 `longitudinal_prediction.v1` JSON 不迁移、不重写。报告详情和渲染器继续容忍旧结构；新生成结果使用 v2。本阶段不修改数据库 schema。

## 11. 分数语义和异常安全

- 未校准输出只能称为“模型分数”，不能称为“临床概率”“患病概率”或“365 天发生概率”。
- 只有 metadata 明确满足校准契约时，才允许使用经过批准的概率表述。
- 分数必须有限且处于 artifact 声明的合法范围，阳性类别必须与 metadata 一致。
- 预测异常对外只返回稳定 reason code 和安全说明。
- SSE、API 响应、报告 `error_message` 和 CLI 输出不得包含文件绝对路径、患者标签、数据库 URL、密码或 traceback。
- 内部日志可以保留受控诊断信息，但不得把原始自由文本病例身份作为日志字段。

## 12. Stage 和 Trend 的部分可用行为

P0-05 不训练 stage 或 trend 模型。registry 仍为它们保留与 outcome 相同的四种运行时状态：`available`、`missing`、`incompatible`、`disabled`。

没有合格 stage/trend artifact 时，准确报告 `missing` 或 `disabled`，不构造占位模型、不模拟概率、不用观察斜率伪装模型预测。

观察章节继续根据真实访视计算已发生的变化。未来若增加 stage/trend 模型，它们必须使用独立 artifact type、metadata 契约和推理输入契约，不能复用 outcome 模型。

## 13. 旧链路兼容

旧链路继续保持：

```text
POST /operator/progression-predictions
  → progression_engine.py
  → <dataset>_progression_model.joblib
```

新纵向报告链路为：

```text
POST /operator/longitudinal-cases/{case_id}/reports
  → task router
  → P0-05 task registry
  → longitudinal_prediction.py
```

P0-05 不改变旧请求/响应 schema、错误语义、risk band、disclaimer 或模型 metadata 输出。只有在新模型正式审核启用、接口能力等价、前端和 API 消费者完成迁移，并且另有批准的退役方案与回归验证后，才考虑退役旧接口。

## 14. TDD 与测试范围

实现严格遵循 RED → GREEN → regression。至少覆盖：

- artifact、metadata 或发布记录缺失；
- metadata JSON 损坏或 schema 错误；
- model、metadata、dataset、manifest 或 data hash 不匹配；
- 错误 artifact type、文件名、disease、dataset、task、target 或 horizon；
- feature schema/version、名称或顺序不匹配；
- candidate/reviewed 被生产加载拒绝；
- 显式 disabled；
- enabled artifact 正常加载；
- 同一任务多个 enabled artifact 被拒绝；
- package 不兼容；
- artifact 检查不调用 `predict`/`predict_proba`；
- outcome 可用但 stage/trend 缺失；
- outcome 不可用时观察、标准和证据仍生成；
- 脂肪肝未肝硬化和已肝硬化正确路由；
- 疑似肝硬化返回 `baseline_stage_uncertain`；
- AD normal/MCI/pre-dementia 路由到唯一 AD 任务；
- 已 HCC 或 dementia 不适用；
- 基线阶段缺失、未知、冲突或疾病冲突；
- age 线上缺失但 artifact 明确允许填补时可推理；
- 不允许填补的必需特征缺失时拒绝推理；
- 非法非有限输入和预测异常安全降级；
- 旧 progression artifact 被新 registry 忽略；
- 旧 progression API 和 engine 回归；
- 双疾病 `.tmp` 真实 artifact review/enable/load/inference smoke test；
- 错误输出不泄漏路径、患者身份、数据库 URL、密码或 traceback；
- 前端基线阶段选项、疾病切换清理和保存字段测试。

## 15. 验证与完成门槛

PowerShell 验证统一设置：

```powershell
$env:PYTHONPATH='backend;.'
```

先运行 P0-05 专项测试，再运行纵向预测、报告、readiness、P0-03、P0-04、旧训练脚本和旧 progression 接口回归，最后运行：

```powershell
python -m pytest -q
```

在新 `.tmp` 目录完成脂肪肝两个任务和 AD 任务的真实 candidate → reviewed → enabled → load → inference 流程。smoke test 前后记录 `backend/app/ml_models/` 文件清单和 SHA-256，确认未经批准未发生变化。

若完整测试遇到既有 `test_cleanup_contracts` 对 `.superpowers/sdd` 的失败，保留目录并记录准确证据，不通过删除目录掩盖问题。

只有实现、专项测试、回归、完整测试、双疾病 smoke test、敏感信息检查和生产目录不变检查全部达到门槛后，才更新路线图 P0-05 状态与实际验证记录。

## 16. 预计文件边界

设计允许在实施计划中细化文件拆分，预计涉及：

- `backend/app/services/longitudinal_model_registry.py`
- `backend/app/services/longitudinal_prediction.py`
- `backend/app/services/longitudinal_readiness.py`
- `backend/app/services/longitudinal_report_generator.py`
- `backend/app/schemas/longitudinal_report.py`
- 新的 registry/release 严格 schema 模块
- `backend/app/api/operator.py`
- `scripts/check_model_artifacts.py`
- 独立 review/enable 管理 CLI
- `frontend/src/components/LongitudinalCaseEditor.vue`
- `frontend/src/views/OperatorView.vue`
- `frontend/src/api/operator.ts`
- `frontend/src/stores/operator.ts`
- P0-05 专项测试和必要回归测试

明确不修改：

- `backend/alembic/`
- 数据库表和 ORM schema
- 旧 progression artifact
- 旧训练脚本
- P0-03 标签语义
- P0-04 的三个任务定义
- AD 多阶段 CDR 模型范围
- outputs、旧模型或旧脚本的删除策略

## 17. 非目标

P0-05 不负责：

- 训练新的 outcome、stage 或 trend 算法；
- 启用任何未经项目所有者批准的具体候选模型；
- 增加 age 数据库或前端字段；
- 从 notes、LLM 或指标推断人口学信息或基线阶段；
- 建立 AD 多阶段 CDR 模型；
- 迁移、删除或退役旧 progression API；
- 修改数据库 schema；
- 声称模型具有临床有效性。
