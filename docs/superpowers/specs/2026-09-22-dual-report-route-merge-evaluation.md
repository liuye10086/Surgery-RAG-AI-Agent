# 预测报告双线路合并评估

创建日期：2026-09-22。更新日期：2026-09-23。版本：**v0.16**。状态：**评估文档定稿（方案未决）**——本文只做事实梳理与方案评估，合并方案尚未批准、排期或实施；本次文档修订不构成应用实施授权。逐轮修订见第 14 节。

依据：见第 13 节。代码基准为 `d5b5dd9`；代码、行数及报告 48／49 的数据库事实已经本地复核。配置与数据库数量是复核时的快照，不保证之后保持不变；历史验收结果不代表当前环境重新验收通过。本文区分代码事实、实测记录与待验证的方案判断。

## 0. 范围声明

`report_kind` 是**三值**枚举：`longitudinal_predictive`、`synthetic_numeric`、`numeric_prediction`（`api/operator_report_jobs.py:31`），后端按保存的 `context.schema_version` 分派：`workers/report_execution.py` 有**四个**显式分支（`:32` v3、`:36` v2、`:40` v1、`:44` synthetic）＋`:48` 旧线路默认。

- 本评估讨论的"两条线路"**只指两条预测报告线路**：`longitudinal_predictive`（旧临床）与 `numeric_prediction`（数值）。
- **第三条线路 `synthetic_numeric`（合成工程报告，指纹 `v3`、文档 `synthetic_numeric_report_document.v1`）不在本文的合并范围内**，但它：
  - 仍实现完整（**后端** `synthetic_*.py` —— `schemas/`／`services/`／`workers/` 下 13 个文件 —— 合计 **2,216 行**，含独立 admission／worker／publication；**前端另有**渲染与提交分支，不计入此数）；
  - 其发布约束正是本文第 6 节引用的 `ck_ai_reports_synthetic_publication`；
  - 已核实的跨线路耦合包括：`schemas/numeric_prediction.py:7` 从 `synthetic_numeric_prediction` 导入基类；`numeric_model_bundle.py:146` 的 `_implementation_files()` 把 `schemas/synthetic_numeric_prediction.py`、`services|schemas/synthetic_prediction_cases.py` 计入数值模型包的 `implementation_sha256`；`RENDERER_FILES` 同时含 `templates/synthetic_numeric_report_pdf.html` 与 `services/synthetic_report_publication.py`；反向也有——`services/synthetic_numeric_prediction.py:9`、`:13` 直接 import 数值侧的 `prediction_calculation`，而该模块计在第 4 节数值侧一行的 611 行内。因此数值侧清单包含第三条线路也在使用的依赖。
  - **来源校验与旧输入转换也跨线路复用**：`services/prediction_case_source.py:10`、`:13`–`:16` 导入 `SyntheticNumericInput` 及 `synthetic_case_source` 的校验／文件辅助函数；当病例没有 `prediction_source` 而有 `engineering_source` 时，`:83`–`:89` 调用 `validate_engineering_case` 后经 `convert_legacy_input` 转换。`:36`–`:46` 仅在内存中转换已验证事实并保留来源版本信息，不覆盖已存原版本；`schemas/prediction_case_source.py:8`–`:9` 还复用合成输入基础类型和 `PackageFile`。
- 设计须明确第三条线路的保留与兼容边界（问题 20），并验证共用依赖的改动对它的影响。本评估不默认将它并入或退役，也不认为它的全部发布约束必然需要修改。上述为已核实的依赖，不声称穷举所有间接导入。

## 1. 结论

**本文能支持的判断**：两条预测线路共用大量基础设施，但业务契约和模型资产仍有实质差异。合并涉及输入生命周期、模型发布、证据、报告与任务契约。已检查代码中未发现证明“无法合并”的结构性限制；这不等于真实来源、临床适用性或容量已经满足上线条件。

**本文尚不能支持的判断**：是否现在实施合并，以及采用 A、B、中立还是混合骨架。第 10.0 节加入保留双线路的对照基线；第 10.2 节十一层的方案工作量、长期维护收益和运行成本仍未测量。方向 A 保持为**待验证候选**，不能依据文件行数或既有偏好认定其最优。

已识别的未知项包括输入 provenance、模型子系统、证据契约、LLM 边界、任务与结果语义、预算与容量。第 8 节其余层同样需要评估；此清单不构成风险排序。第 10.1 节区分三类事项：

- **合并硬约束**：分别来自第 7 节沿用的评估目标（原始确认来源待补）、AGENTS.md 的保存与审计要求，以及方向修订文档的来源／业务分离要求。
- **实现选择**：物理任务拓扑与快照承载形式，见第 12 节问题 10、11。
- **适用条件**：输入已具备合法来源绑定、所选模型兼容且获准用于目标场景、依赖满足；不满足时的拒绝或 partial 规则尚待问题 7–9 定义。

**决策次序**：先确认各方案能否满足同一目标与使用范围，再比较收益、增量成本和风险。分别计量：①新建／修改代码；②模型评价与端到端验收；③数据迁移；④切换与回滚；⑤运行及持续维护成本；⑥隐私与安全风险。复用资产及其可继承证据是收益，不能与重写行数相加作为待最小化的成本。六项不能直接按不同单位相加；比较应注明观察周期、工作量估算区间、必须满足的门槛和取舍理由，存在互有优劣时交由决策者选择。

三点必须先说清，否则决策会被误导：

1. **共用面比表面大**（两条预测线路看似各有一套，实际大量基础设施已经共用，且与第三条线路 `synthetic_numeric` 共享 `report_execution.py` 的分派框架）：worker 入口与分派、读取层、任务框架、归档、渲染引擎、前端容器已经共用（第 5 节）。真正各有一套的是**输入与病例生命周期、模型执行与文档构建、证据契约、模型发布语义、发布完整性投影**。
2. **"统一输入契约"不足以让真实资料接入**：数值 v3 在 context 校验、结果 schema、推理、受理**四处**都**显式拒绝非 synthetic 来源**（第 7.2 节），模型包也固定 `production_enabled=false`。
3. 这是跨输入、模型、持久化与展示的多模块变更；本文尚未估算工期，不排除第 8 节任一层构成实施阻断项。

## 2. 前因：为什么会变成两条

1. **原始产品**是一条线路：`longitudinal_predictive`，产出 `report_document.v1` 的 **11 节临床预测报告**，输入是操作者录入的普通病例，模型来自 `backend/app/ml_models` 注册表／发布集。
2. **2026-09-14 统一方向**（[统一预测流程与报告展示：方向修订](2026-09-14-unified-prediction-report-direction.md)）要求先用合成数据跑通完整目标流程，并把**来源与预测业务契约分离**。其中“仍会保留目前后端两种业务路径”以“统一仅发生在展示层”为前提，随后指出这样不能满足真实来源接入目标；这是对仅统一展示的局限说明，**不是要求长期保留双线路的决定**。
3. **阶段一至五**完成并验收新数值路线；当前代码仍保留旧预测执行链与 `report_document.v1`。新能力作为独立版本分支接入，共用框架也发生过改动，不能将此概括为整个旧线路相关代码从未变化。
4. 于是今天两条线路并存。

### 2.1 一个具体的后果（本次暴露）

2026-09-21 真机调试时，普通病例的「生成报告」按钮永远灰、提示「数值预测报告暂停受理新任务」。根因是**前端在两处把线路写死成数值线路**（就绪检查与提交），而数值线路在业务配置下是关闭的。

- 已修复并提交：`1ef6ef5 修复普通病例无法生成报告与提交的线路选择`。
- `git log -S` 确认：该行为由 `2650d27 预测线路修改或重构第二阶段` 引入，且当时**有测试专门断言**（`requests numeric readiness for an ordinary saved case`）。
- **措辞的准确界限**：测试能证明该行为被**实现并固化**，不能单独证明它经过产品决策。本次修复**反转了该行为**。
- 同一条业务动作有两个出口，任一处选错都会让另一条线路不可用——这是并存成本的具体证据。

## 3. 已有运行证据与当前配置

两侧均有完成报告的记录，但来自不同运行环境与配置。2026-09-23 只读加载本机设置仍为 `NUMERIC_REPORTS_ENABLED=false`、`NUMERIC_MODEL_BUNDLE` 为空；数值线路当前不受理新任务，不能把阶段五验收等同于业务环境当前已启用。关闭新受理不取消已受理任务，也不影响历史与 PDF 原件读取（见运维文档）。

| 项 | 旧线路 | 数值线路 |
| --- | --- | --- |
| 一次完整实测（**48 不是"最近一次"**） | **报告 48**（`surgery_rag` 库、`longitudinal_predictive`、`v2` 指纹、`report_document.v1`、11 节、9 次模型运行、3 张图）。**精确耗时：worker 3.06 秒；排队 304.21 秒；端到端 307.27 秒**。同库另有更晚的**报告 49**（同为 `longitudinal_predictive`／`v2`／`report_document.v1`／11 节／`completed`／`error_code IS NULL`，排队 **晚 23 分钟**：16:52:29 vs 16:29:07），为 **7 次模型运行、1 张图**。该库 `report_generation_jobs` 共 **2 行**，即这两次 | 阶段五 `2026-09-21-v5`：`release.json` 记录 `status=stopped`、jobs `completed 3`+`cancelled 1`、历史核验 3/0、3 次 LLM `invocation_started`；「三份均 `v6`」来自验收记录中的独立数据库复核，不是 `release.json` 自身字段 |

旧线路 11 节（实测取自报告 48 的 `report_document`）：

```text
1. 报告摘要                              7. 关键进展信号
2. 病例与预测范围                        8. 参考标准和相似病例
3. 数据质量与适用性                      9. 不确定性与局限性
4. 已观察到的纵向变化                   10. 人工复核重点
5. 未来 365 天进展风险                  11. 模型和数据技术附录
6. 阶段模型和下一次随访趋势的可用状态
```

## 4. 两条线路的差异面（按职责）

| # | 差异面 | 旧线路 `longitudinal_predictive` | 数值线路 `numeric_prediction` |
| --- | --- | --- | --- |
| 1 | **病例编辑与准入** | 输入是**可编辑的普通录入病例**；任务准入时冻结输入快照。带 `prediction_source`／`engineering_source` 的病例会被旧线路**拒绝**（`report_generation_service.py:102` 预检、`:144` 锁内复核；三元表达式在 `:103`／`:145` —— 有 `prediction_source` 抛 `numeric_report_kind_required`，否则抛 `synthetic_report_kind_required`） | 只接受**已绑定版本化预测输入**的病例 |
| 2 | **来源绑定与冻结生命周期** | 无来源包概念；快照在准入时从病例构造 | 输入由冻结来源包导入并绑定；**绑定后病例只读**（`longitudinal_case_service.py:57`、`OperatorCaseWorkspace.vue:56`、`:59`） |
| 3 | **模型执行与文档构建** | `build_report_document`（`report_document_builder.py:64`）**只服务旧线路**，唯一调用点 `report_execution.py:86` | 三个独立 builder：`numeric_report_publication.py:88`、`numeric_report_v2.py:58`、`numeric_report_v3.py:90`；发布时 repository 显式分支重建（`report_job_repository.py:293`） |
| 4 | **证据契约与检索语义** | 批准标准规则 + 结构化相似病例窗口（`report_generation_context.py:131`、`schemas/longitudinal_evidence.py:203`） | v1 不执行检索；v2／v3 使用冻结参考片段目录上的向量/全文/RRF（`numeric_report_evidence.py:72`、`:105`）；**「不是指南」的强制表述出自叙述 prompt**（`numeric_report_narrative_v2.py:11`、`:102`），不在证据模块 |
| 5 | **报告文档与发布完整性投影** | `report_document.v1`：11 节 | `numeric_report_document.v1/v2/v3` |
| 6 | **任务语义** | 按疾病／阶段选择 outcome、stage 与多个 trend 模型；报告 48 实测 **9 次模型运行**（报告 49 为 **7 次**），各任务有独立可用状态 | 各版本均按当前病例病种处理 6／12 月任务；v1 为 `last_value` 基线，v2 为训练后的 Ridge 与比较基线，v3 才引入逐任务提供者、候选三态与独立基线状态。「2 病种 × 2 时距」是全系统任务集合，不是单病例运行四项 |
| 7 | **是否调用 LLM** | **不调用**（`longitudinal_prediction.py` 文档字符串 "no LLM-generated facts"；执行链无 LLM 引用） | **v1 不调用**（`numeric_report_execution.py`："without clinical model, evidence, or LLM calls"）；**v2／v3 各一次有界 DeepSeek**（worker 调用点 `workers/numeric_report_v2.py:45`、`workers/numeric_report_v3.py:45`；LLM `.invoke` 在 `numeric_report_narrative.py:109`、`numeric_report_narrative_v2.py:137`）。阶段五跑的是 v3 |
| 8 | **模型发布语义** | `ml_models` 注册表／发布集／活动指针，含训练、评价、发布、回滚 | v1 固定基线算法身份，不加载 bundle；v2／v3 通过 `NUMERIC_MODEL_BUNDLE` 选择模型包，v3 另有逐任务提供者分配（`schemas/numeric_history_bundle.py:111` 的 `provider`、`:548` 的 `task_assignments`、`:555` 的强校验） |

LLM 断言的核对范围为受理上下文、模型加载／推理、证据构建、信号解释、文档与发布。旧链由 `report_generation_service.py` 捕获 `report_generation_context.py` 的身份；`workers/report_execution.py:50`、`:55`、`:66`、`:77`、`:86`、`:95` 依次加载固定模型、审计推理、构建固定证据、解释信号、构建文档和发布。对应的 `longitudinal_prediction`／模型运行、`evidence_bundle`／`standard_evidence`／`reference_case_*`、信号与报告辅助模块执行的是模型、规则、查询和确定性构建，没有报告生成 LLM 调用。这里不把上游资料录入或其他问答功能的 LLM 调用算入报告生成链。

数值 v2／v3 的“一次有界调用”指单次 worker 执行到叙述阶段时的一次 `.invoke`，其前置阶段失败时为零次；客户端配置 `max_retries=0`、超时与输出 token 上限（`numeric_report_narrative.py:43` 起、`numeric_report_narrative_v2.py:45` 起）。它不表示用户另发一个任务也不会再次调用。

**模块归属（按引用关系分类，不是按文件名前缀）**

| 类别 | 组成 | 行数 |
| --- | --- | --- |
| **数值侧模块（相对旧预测线路）** | `services/numeric_*.py` 2,382 ＋ `prediction_calculation*` 611 ＋ `prediction_candidate_*` 648 ＋ `prediction_history*` 809 ＋ `prediction_stability*` 131 ＋ `prediction_case_source.py` 205 | **4,786** |
| **旧侧模块（相对数值线路）** | `services/longitudinal_*.py` 扣除 `longitudinal_case_service.py` 后 8,984 ＋ `evidence_bundle.py` 565 ＋ `standard_evidence.py` 802 ＋ `report_document_builder.py` 620 ＋ `report_generation_context.py` 144 ＋ `reference_case_*` 1,164 ＋ **`report_publication.py` 145** | **12,424** |
| **共用／跨路线** | `report_read_service.py` 319 ＋ `report_job_repository.py` 391 ＋ `report_archive_storage.py` 308 ＋ `report_generation_service.py` 345 ＋ `workers/report_execution.py` 108 ＋ `longitudinal_case_service.py` 523 | **1,994** |
| **跨路线、未计入上表** | `pdf_generator.py` 568、`report_integrity.py` 240、`api/operator.py` 529、`api/operator_report_jobs.py` 257、`workers/report_worker.py` 179、`workers/report_pdf_worker.py` 163、`report_history_query.py` 173、`report_saved_identity.py` 23、`report_document_renderer.py` 26 —— **即左列九项之和** | **2,158**（可逐项复算；本行**不穷举**，真实跨路线共用面只会更大） |

口径为逐文件 `wc -l`，**表内不带目录的 glob 一律指 `services/`**。三处未计入，**均不改变上表合计**：

- **`app/` 下全部 `numeric_*.py` 实为 4,245 行**（27 文件）＝ `services/` 2,382（15 文件）＋ `schemas/` 1,708（9 文件）＋ `workers/` **155**（3 文件：`numeric_report_execution.py` **45**、`v2.py` 55、`v3.py` 55）。数值侧的 workers 部分本表未计。
- **两侧 schema**：`schemas/numeric_*.py` 1,708 行（9 文件）、`schemas/longitudinal_*.py` 1,821 行（8 文件）。
- **框架进程控制类另计 699 行**（`workers/report_process_control.py` 357、`report_pdf_process_control.py` 202、`report_pdf_execution.py` 70、`report_pdf_publication.py` 49、`report_database.py` 21）——跨路线，第 8 节第 11 层的预算与租约分析实际落在这些文件里。

另：前端、脚本与测试不在本口径内。**本表未计入 `synthetic_*.py` 的 2,216 行，但"数值侧"一行中包含第三线路复用的依赖**——`prediction_calculation` 被 `services/synthetic_numeric_prediction.py:9`、`:13` 直接 import（第 0 节）。因此 4,786 是**相对旧预测线路**的数值侧模块量，**不是系统范围内的"专属"**。

**归属依据**：

- `longitudinal_case_service.py`（523 行）的 `build_input_snapshot` 被数值准入直接调用（`numeric_report_admission.py:9`、`:33`），归入共用。
- `report_publication.py`（145 行）依赖 `ReportDocument`、`EvidenceBundle`、`evidence_bundle` 与 365 天旧线路语义（`report_publication.py:8`、`:45`），归入旧侧。
- `reference_case_*`（1,164 行）使用 `longitudinal_evidence` schema，由旧线路的 `app/services/evidence_bundle.py:23` 调用；数值 RAG 使用 Chunk／Document 中冻结的 `numeric_reference.v1` 片段，不引用这些模块。数值侧非 `numeric_` 前缀模块合计 2,404 行。

**三点结论**：

1. **不能按文件名前缀作对称比较**。旧侧非 `longitudinal_` 前缀模块也有 3,440 行。按职责分类才反映真实归属。
2. **行数不是工作量**。数值侧的 4,786 行里，哪部分保留、适配、重建或不受影响，必须逐模块判定（见第 8 节第 2 层）。
3. 本表未将 `synthetic_*.py` 的 2,216 行加入合计，但包含其复用的数值侧依赖；也未穷举跨路线模块（见第 0 节与 5.1 节）。

## 5. 已共用与未共用（实测）

### 5.1 已经共用

| 层 | 精确范围 | 证据 |
| --- | --- | --- |
| worker 入口与分派 | **分派框架**共用；各分支实现独立 | `report_execution.py:32` 按保存的 `context.schema_version` 分派到数值 v1／v2／v3、synthetic 与旧线路 |
| 读取层 | **解析分支框架**共用 | `report_read_service.py:135` 按 `schema_version` 解析五种 context |
| 任务表、幂等、取消、超时、租约、阶段审计 | 框架共用 | — |
| 归档存储与原件交付 | 共用 | — |
| PDF 引擎 | **引擎共用，验证与渲染分支各自实现** | `pdf_generator.py:428`–`:434` 共用 Markdown 转换与 HTML 净化，`:515`–`:562` 共用 Playwright／Chromium PDF 输出；`:423`–`:427` 按文档类型选择扩展。`:213` 的 `calendar_positions` 复用仅在旧报告构建／旧 PDF 图表之间，不能作为两条预测线路共用的证据 |
| 前端页面容器 | 容器共用；`LongitudinalReportView.vue:88` 内部承载独立数值组件 | — |
| 身份、病例归属检查与审计存储设施 | **设施共用；路线准入条件、审计事件与任务投影语义各自实现** | 数值线路另有 numeric actor、来源绑定、疾病/模型版本等准入（`numeric_report_admission.py:15`、`report_generation_service.py:85`） |

### 5.2 尚未共用（合并的真正对象）

输入与病例生命周期、来源绑定、模型执行与文档构建、证据契约与检索语义、模型发布语义、报告文档与发布完整性投影、渲染与验证分支、展示表现。

## 6. 合并在采用新契约版本时应触碰的约束

`ai_reports` 当前共有 **13 条 CHECK**（业务库只读查询确认）。其中**与版本及发布映射直接相关的是下列 7 条**；其余 6 条（`ck_ai_reports_document_object`、`ck_ai_reports_document_sha256`、`ck_ai_reports_evidence_snapshot_sha256`、`ck_ai_reports_evidence_status`、`ck_ai_reports_standard_evidence_status`、`ck_ai_reports_reference_case_status`）是字段类型与取值约束，**不声称它们必然随合并修改**。

**v3–v6 共用的发布完整性条件**（实测自业务库约束定义）：均要求 `analysis_type`、`status='completed'`、`report_document` 及其摘要、`generation_fingerprint`、`input_snapshot` 及其摘要、`evidence_snapshot` 及其摘要全部非空。**这是设计新发布约束时的最低参考基线，不是要求照抄**——合并后的证据状态语义可能不同。`analysis_type` 的具体取值同样属于版本映射的一部分（见下表）。

各版本在此骨架之上的差异：

| 约束 | 指纹 → 附加条件 |
| --- | --- |
| `ck_ai_reports_fingerprint_version` | 允许 **`NULL`**；**非空值**只允许 **`v1`–`v6`**（`models.py:1165`–`:1167`）。新增非空指纹版本时**必须**修改它 |
| `ck_ai_reports_v2_publication` | **v2 →** 要求 `completed` 且三个发布字段存在。**不受**上面那套骨架约束（它是更早的版本） |
| `ck_ai_reports_synthetic_publication` | **v3 →** `analysis_type='synthetic_numeric'`；文档 `synthetic_numeric_report_document.v1`；`evidence_status`／`standard_evidence_status`／`reference_case_status` **三者均为 `not_requested`** |
| `ck_ai_reports_numeric_publication` | **v4 →** `analysis_type='numeric_prediction'`；文档 `numeric_report_document.v1`；**三种证据状态均为 `not_requested`** |
| `ck_ai_reports_numeric_full_publication` | **v5 →** `analysis_type='numeric_prediction'`；文档 `numeric_report_document.v2`；`evidence_status IN ('complete','partial')`；`standard_evidence_status='not_requested'`；`reference_case_status IN ('available','no_eligible_cases','reference_query_failed')` |
| `ck_ai_reports_numeric_history_publication` | **v6 → 且对文档 schema 排他**：`analysis_type='numeric_prediction'`；文档 `numeric_report_document.v3`；`evidence_status IN ('complete','partial')`；`standard_evidence_status='not_requested'`；`reference_case_status` 取值同 v5；并额外规定「非 v6 时 `report_document->>'schema_version'` 不得为 `numeric_report_document.v3`」 |
| `ck_ai_reports_engineering_evidence` | 证据状态豁免规则：`(三种状态都不是 not_requested) OR (指纹 ∈ v3–v6)` |

**方向性说明**：v2–v5 的数据库实现是**单向蕴含**（`fingerprint_version IS DISTINCT FROM 'vX' OR (...)`），即"若是 vX 则必须满足"，**反向不成立**；只有 v6 额外加入了排他条件。

**推论**：按现有**不可变版本纪律**，新的合并 schema 应使用新指纹版本。若采用 `v7`：

- **必须**扩展 `ck_ai_reports_fingerprint_version` 的枚举；
- **必须**为 v7 新增对应的发布约束（即上面那套骨架 + v7 自己的 analysis_type／schema／证据状态）；
- **不一定**需要调整 `ck_ai_reports_engineering_evidence`：其第一分支对任意指纹版本成立；只有当新契约允许三种证据状态中出现 `not_requested` 时，才必须把 `v7` 加入豁免集合；
- 需要编写 Alembic 迁移。

**关于旧版本与缺失版本**：在已有的**非空版本号**中，v3–v5 已绑定各自的旧文档 schema、v6 还有排他条件，v1／v2 的数据库约束较弱。数据库还允许版本为 `NULL`；v2–v5 的 `IS DISTINCT FROM` 前提不会据此触发对应发布条件，v6 仍禁止非 v6 使用 `numeric_report_document.v3`。只读表达式复算确认：版本为 `NULL`、文档 schema 为另一个非 v3 名称且三个证据状态均非 `not_requested` 的构造记录可以通过全部 13 条 CHECK；这不是插入或应用发布验收。应用历史完整性检查在存在文档而版本为 `NULL` 时会返回 `document_integrity_fields_missing`（`report_integrity.py:118`–`:139`）。因此数据库约束可通过不等于应用认可；缺失版本或复用弱约束旧版本都不能代替新契约的不可变版本纪律。

按项目既有边界，"编写迁移"与"在已有业务数据库执行迁移"是两件不同的事，后者需要单独授权。

## 7. 两项评估目标与其真实前提

本文沿用下列两项目标比较候选方案。原始产品确认对话未附于仓库，本次无法独立核实其确认来源；它们在本文中作为评估条件保留，不由本次修订新增产品或实施授权。方案选定前须补充确认来源或重新确认目标。

| 问题 | 沿用的评估目标 |
| --- | --- |
| 旧线路 11 节中的**临床内容**是否保留 | **保留**，作为独立区块 |
| **输入契约**统一成哪一种 | **录入也产生预测输入** |

### 7.1 确定性映射与来源证明

需要定义“从录入病例推导预测输入”的确定性规则。现有五个来源字段性质不同（`schemas/numeric_prediction.py:16`–`:18`、`:31`–`:32`）：

- `dataset_id`／`dataset_version`／`run_id` 是 manifest 声明的身份，不自行证明来源真实性。
- `manifest_sha256`／`input_file_sha256` 绑定实际文件字节，证明内容完整性。加载器明确说明 *“hashes detect corruption, not source authenticity”*（`prediction_case_source.py:109`）。
- 页面录入没有现成的来源包。不能把结构化字段摘要直接填入上述文件摘要字段，冒充已经存在的文件；若服务端确实生成相应不可变制品，则可按明确定义的字节序列计算摘要。

设计需同时确定两个独立维度：

1. **内容身份与保存形式**：是否生成并持久化不可变的 canonical input artifact；也可设计版本化数据库快照。无论使用何种形式，都须定义 canonical 序列化、摘要、保存位置与重新验证规则。没有文件时使用适合交互录入的字段语义，不冒用文件包契约。
2. **来源权威性与沿革（authority／lineage）**：无论是否保存 artifact，都要关联生成主体、生成权限、病例版本、生成时间、映射规则版本与审计记录。内容摘要是来源证明的一部分，不能单独代替这些关联。

还需确定 `known_on`、测量 `method`、单位、锚点与历史覆盖如何从已有访视得到，以及缺失时哪些字段必须拒绝、哪些可明确标为缺失。不得为通过校验而静默填充。

### 7.2 输入统一与真实来源使用范围

真实录入接入至少有三个独立前提：

1. 第 7.1 节的确定性映射、内容身份与来源证明。
2. **病例编辑、冻结、版本失效与审计生命周期**。现有已绑定输入病例只读；普通 HTTP 写入不能设置来源绑定。当前数值准入还明确要求 `prediction_source`／`engineering_source`（`numeric_report_admission.py:29`–`:35`），普通录入即使能构造 `NumericInput`，也不能直接提交数值报告。
3. **与目标使用范围相符的模型适用证据及授权**。真实来源的工程验证与临床／生产使用不能混为一谈。当前 v3 在 context 校验（`schemas/numeric_report_v3.py:54`）、结果 schema（`schemas/numeric_history_prediction.py:122`）、推理（`services/numeric_history_bundle.py:195`）、受理（`services/numeric_report_v3_admission.py:17`）四处拒绝非 synthetic；现有模型包固定 `clinical_validity_claim=false`、`production_enabled=false`（`schemas/numeric_model_bundle.py:87`–`:88`）。接入真实来源要建立适用的训练／评价、版本绑定与发布流程；既有参数能否复用、是否重训，须由适用性证据决定，不能只删除 synthetic 校验或修改标志。

v1 基线的输入 schema 和计算函数未限制为 synthetic，但这只证明一个底层能力；普通录入的准入映射与绑定尚未实现，真实临床性能和生产使用也未获证明。第 12 节问题 8 先决定本次允许的来源与使用范围，问题 9 再决定该范围内是否允许 v1 工程基线以及拒绝／partial 的分支。“真实数据只换来源”不是当前能力；操作者流程不因来源重做仍是需要设计和验收的目标。

## 8. 影响面（十一层）

| 层 | 需要评估／改动的内容 |
| --- | --- |
| 1 输入与病例生命周期 | 手工录入的来源身份与 canonical provenance（第 7.1 节）；`known_on`／`method`／单位／锚点／历史覆盖的确定规则与禁止静默填充；编辑后重新派生／冻结、版本替换、旧绑定保留与审计；同时检查第 0 节 `engineering_source` 校验、旧输入转换和共用来源类型对第三条线路的兼容影响 |
| 2 模型子系统（离线→在线全链） | 需逐项判定**保留／适配／重建／不受影响**：任务与特征定义（`numeric_history_features.py`）、基线与候选及历史模型训练（`prediction_calculation*`、`prediction_candidate_training.py`、`prediction_history*`）、配对评价与稳定性（`prediction_candidate_evaluation.py`、`prediction_stability.py`）、bundle 构建与协议绑定（`numeric_history_bundle_build.py`）、JSON 导出、**runtime 一致性校验（两层，合计 17 个实现文件）**——`services/numeric_history_bundle.py:80` 的 `verify_numeric_history_runtime` 比对 `:20`–`:26` 的 **5 个文件**（错误码 `numeric_history_implementation_changed`），内部再调 `numeric_model_bundle.py:159` 比对 `:146` 的 **12 个文件**（错误码 `numeric_model_implementation_changed`）；**被计入的 5 个含 `numeric_history_features.py` 与 `prediction_history_features.py`，即本层的"任务与特征定义"**；在线 loader 与分派（`numeric_model_dispatch.py:41` 起为**各 bundle 版本的分支**；"排队任务固定"由保存的 context 携带 `model_bundle` 并在执行时校验体现——`workers/numeric_report_v3.py:22`–`:31`）；旧侧对应 `ml_models` 注册表／发布集／活动指针 |
| 3 证据 | 两套证据契约与检索状态的统一；批准标准是否进入 LLM 输入；访问范围、固定身份、失败／partial 状态 |
| 4 执行与发布 | 文档构建（1 个旧 builder、3 个数值 builder 与 repository 分支重建）、发布完整性投影、LLM 叙述范围及安全边界。现有叙述 prompt 禁止方法词、数字和日期，并声明缺少指南证据（`numeric_report_narrative_v2.py:9`–`:14`）；它可用于定性补充，但不能直接承担含具体数值、日期、术语的整个临床区块。`filter_input` 检查请求、`filter_output` 检查生成内容（`:134`、`:144`），不等同于患者数据去标识。LLM 载荷含病种、锚点、逐条观测、预测结果和检索文本（`:52` 起），需明确允许外发的字段与服务边界；仅凭调用代码不能认定数据发生跨境传输。见问题 12、13 |
| 5 报告文档与指纹 | 新 schema；新指纹版本与第 6 节约束；Alembic 迁移 |
| 6 历史读取 | 多 schema 解析与完整性重建（`report_read_service.py:135`）、生成的前端类型（`scripts/generate_report_document_types.py`） |
| 7 展示与 PDF | 报告视图与模板、renderer 重建（`scripts/build_report_pdf_renderer_manifest.py`）、监测指标 |
| 8 任务与结果语义 | **权威任务集合**（365 天风险／下一阶段／next-visit trends／6–12 月数值如何各自表达状态）、**结果组合与跨引擎冲突裁决**、**部分任务失败或 LLM 失败时的发布资格**。冲突裁决影响任务组合、发布资格、报告构建、LLM 输入边界与展示，**不属于检索证据契约** |
| 9 切换与回滚 | 活动配置切换、模型包与发布集的活动版本回滚、迁移与回退演练 |
| 10 **API／线路路由与客户端选择** | 涉及 API schema、就绪、提交、幂等请求摘要、保存身份、历史筛选、前端 API／store／页面选路与待恢复请求。代表位置为 `api/operator_report_jobs.py:31`、`report_generation_service.py:82`、`report_generation_idempotency.py:12`、`report_saved_identity.py:21`、`report_history_query.py:69`、`frontend/src/stores/operator.ts:136`、`frontend/src/stores/report-generation.ts:112`。源码字面统计为后端 32 行／34 次、前端 14 行／17 次；使用 `rg -n`／`rg -o` 搜索 `report_kind`，后端限定 `backend/app/` 与 `-g '*.py'`，前端限定 `frontend/src/` 并用 `-g '!**/__tests__/**'` 排除测试。合并需决定旧 kind、别名及 sessionStorage pending request 的兼容；2026-09-21 故障发生在该层 |
| 11 **任务预算与成本** | 按禁用／v1／v2／v3 区分当前行为与目标成本；测量准入、推理、检索、LLM、发布、PDF 与队列占用。全局总预算、阶段预算、租约、并发度及受理上限见第 8.1 节。关闭路线不构成满足同一交付目标的低成本方案 |

### 8.1 执行模式、预算与容量证据

| 数值侧模式 | 当前代码行为与预算口径 |
| --- | --- |
| 新受理关闭 | `NUMERIC_REPORTS_ENABLED=false` 在 `numeric_report_admission.py:23`–`:24` 拒绝新的数值快照。被拒请求不执行数值 worker，但仍有受理检查成本；已经受理的任务不因此取消。此状态不产出新的数值报告，不能用“零成本”与完整交付方案比较 |
| v1 基线 | 数值准入通过且 `NUMERIC_MODEL_BUNDLE` 为空时选择 v1（`numeric_model_dispatch.py:55`–`:59`）。执行固定算法身份校验、确定性基线计算、文档与发布；不执行检索、LLM 或 bundle 校验 |
| v2 训练模型 | 配置 `numeric_model_bundle.v1`，经 context.v2 分支执行；包含 12 文件的 bundle/runtime 校验、模型计算、检索、一次有界 LLM、文档与发布 |
| v3 历史混合模型 | 配置 `numeric_model_bundle.v2`，经 context.v3 分支执行；runtime 校验增加 5 文件，合计 17 文件，然后推理、检索、一次有界 LLM、文档与发布（`workers/numeric_report_v3.py:24`、`:31`、`:39`、`:45`、`:47`–`:50`） |

这些是数值分支的现有行为。复合任务还要计入旧侧模型与证据获取、组合校验，以及所选叙述范围带来的增量；报告 48／49 分别记录 9／7 次旧侧模型运行，不能直接当作所有病例的固定调用量。准入也有来源／模型／参考身份捕获与事务内复核（`report_generation_service.py:125`–`:156`）；PDF 使用独立任务与预算，不能把报告完成耗时当作“报告＋PDF”交付耗时。

当前报告任务的全局限制（`core/config.py:29`–`:40`）为：

- 总执行 300 秒、租约 45 秒；阶段预算为 LOAD 60／PREDICTION 120／EVIDENCE 30／RENDER 30／PERSIST 5 秒。总预算计算 `run_deadline`（`report_job_repository.py:131`），租约更新不越过它（`:164`）；阶段预算由 `workers/report_worker.py:94`–`:100` 传给监督器。
- `REPORT_JOB_CONCURRENCY=1`，修改会触发 `report_job_concurrency_requires_capacity_review`（`core/config.py:66`–`:67`）。领任务使用 `pg_advisory_xact_lock(73607)` 与全局 running 计数（`report_job_repository.py:91`–`:96`）。
- 排队期限 `REPORT_JOB_QUEUE_SECONDS=600`（`report_generation_service.py:226`）、全局 queued 上限 `REPORT_JOB_QUEUED_LIMIT=20`（`:197`）、每用户 active 上限 `REPORT_JOB_USER_ACTIVE_LIMIT=2`（`:195`）。已受理任务适用这些规则；关闭新受理的请求不会因此获得一个执行预算。

如果父子执行各占 job 行，需同时处理 `report_id` 主键与 running 计数，不能假定新增子执行自然获得并发容量（问题 10）。复合任务延长占用对队列的影响需要测量。报告 48 的排队 304.21 秒为 600 秒的 50.7%，但等待原因未记录，不能据此认定队列饱和。模型推理、准入开销、LLM 时延、PDF、峰值内存及并发下排队时延均应分别记录；引入外部 LLM 后的失败／超时语义见问题 7、12、13。

## 9. 风险

1. **历史兼容**：既有各版本报告与归档 PDF（包括已实测的 v2／v5／v6）必须继续按保存身份读取，**不重算、不替换原件**。
2. **本节只列已识别的风险，不给优先级**：第 10.2 节没有任何一层完成测量，因此**不排除任何层**构成阻断项（第 1 节同）。
3. **验收边界（三类，不得互相替代）**：

   - **(1) 复用现有 bundle／renderer manifest 的运行时条件**。"点名的源文件一字节未变"只属于这一类：数值模型包的加载门禁比对 `_implementation_files()` 点名的 12 个文件哈希（`numeric_model_bundle.py:146`），不符即抛 `numeric_model_implementation_changed`（`:167`–`:168`）。**但在配置为 v3 history bundle 时，该门禁还叠加了第二层清单（不是当前配置——当前 `NUMERIC_MODEL_BUNDLE` 为空，见第 3 节）**：`services/numeric_history_bundle.py:20`–`:26` 的 **5 个文件**（`schemas/numeric_history_bundle.py`、`schemas/numeric_history_prediction.py`、`services/numeric_history_features.py`、`services/numeric_history_bundle.py`、`services/prediction_history_features.py`）与那 12 个共同构成 `history_implementation_sha256`（`:74`–`:77`），不符抛**第二个实现哈希错误码** `numeric_history_implementation_changed`（`:104`–`:108`、`:136`–`:137`）。**因此 v3 线路实际冻结的实现文件是 17 个、两个实现哈希错误码**（该函数另有 `numeric_history_loaded_code_mismatch`：`:97`–`:100`、`:134`–`:135` 检查导入对象／别名身份，`:115`–`:132` 将磁盘源码编译后的代码对象与已加载函数的 `__code__` 比较；`numeric_history_loaded_module_missing`（`:112`–`:114`）检查模块是否存在于 `sys.modules`。这些不是实现哈希比对，**不计入上面两个实现哈希错误码**）；这 5 个中有 `numeric_history_features.py` 与 `prediction_history_features.py`——正是第 8 节第 2 层要求逐项判定"保留／适配／重建"的**任务与特征定义**模块，是否修改这些模块取决于所选任务／输入契约，需列入影响评估。renderer manifest 则在加载时校验 `platform`／`playwright`／`fonttools` 版本、`print_options` 与全部 `RENDERER_FILES` 哈希（`report_pdf_renderer_manifest.py:92`–`:109`）。**二者性质不同**：前者是模型的运行时准入门禁（该函数文档字符串明示 *"Admission/worker gate only; historical validation must not call this disk check."*，`numeric_model_bundle.py:160`），后者是**当前渲染环境**的 fail-closed 门禁（`report_pdf_renderer_manifest.py:92`）——而历史报告又禁止即时重渲染，因此**两者不能对称类比**。
   - **(2) 组件证据是否可继承的条件**。这**不等于**字节未变。数值 bundle 同时冻结训练样本／被试／依赖组身份与训练数据摘要、`parameters_sha256`（`schemas/numeric_model_bundle.py:45`–`:50`），以及挑战集身份、来源、评价与评价摘要（同文件 `:75`–`:88`）——源码哈希只是其中一项：**注释或等价重构造成字节变化，不必然使既有科学证据全部失效；反过来，源码未变也不足以证明训练数据、参数与评价仍适用于新的输入来源**。设计阶段必须对每个组件明确"契约等价"或"重新验证"的判定条件——其验证成本尚待评估，第 11 节的测量须计入成本。
   - **(3) 端到端验收必须重做的条件**：阶段四／五覆盖 API、worker、RAG、LLM、报告、历史、PDF 的集成与发布验收，在**新的 context／document／fingerprint** 下必须重做。

   三类不得混用：旧证据不能**单独**证明合并后的端到端线路，(1) 成立也不能单独推出 (2)。
4. **资产取舍**：旧侧保留风险／阶段／趋势任务、注册表、发布集与信号解释；数值侧保留基线／Ridge／历史候选、离线评价、bundle 与 RAG／叙述。两侧均有可复用资产，不能仅按新旧或代码体积决定淘汰哪一侧。
5. **真实资料路线耦合**：第 7.2 节的三个前提与合并高度重叠。

## 10. 方案比较

### 10.0 先比较是否实施，再比较合并骨架

保留双线路也必须进入比较，但须写明它交付了什么：

| 对照或候选 | 定义与当前证据 | 不能假定的结论 |
| --- | --- | --- |
| O：暂不合并 | 保留当前两套业务契约、已修复的选路及共用基础设施；只处理独立获准的维护工作。旧侧有报告 48／49，数值侧有隔离验收，当前业务配置禁用数值新受理 | O 没有实现“录入也产生预测输入”和合并后的独立临床／数值区块；只能作为成本与延期收益的基线，不能冒充满足目标的最终交付 |
| O+：保留两套执行实现，单独建设统一录入 | 是需要另行估算的对照变体，需建设第 7 节的来源绑定、编辑与冻结生命周期。当前绑定病例会被旧路线拒绝，故连旧侧准入也要评估 | 不能假定只改前端或没有迁移。如果为了交付一份复合报告再增加统一编排、快照与发布，它已属于下述中立／H，不能重复计为“无需合并” |
| A／B／中立／H | 在第 10.1 节约束下交付复合报告，并按第 10.2 节评估具体实现 | 未完成工作量及运行测量，不能宣称某骨架成本最低或已经满足真实来源上线条件 |

第 2.1 节故障证明存在选路一致性的维护负担；修复已完成，不能把同一故障再次计作未来必然发生的损失。合并减少哪些重复改动、回归分支或操作步骤，仍是待验证收益。保留双线路也有未来维护成本，不能按“零新增代码”视作零成本。

比较记录须采用相同目标使用范围、负载和观察周期，分别记录第 1 节的六项维度：新建／修改代码、模型评价与端到端验收、数据迁移、切换与回滚、运行及持续维护成本、隐私与安全风险，并另列未交付目标的影响。第 7 节的评估目标及来源限制继续适用；若本次必须立即交付全部目标，O／不满足目标的 O+ 不具备候选资格。若比较“现在实施还是延期”，则须明确延期时缺失的能力和后续交付安排。问题 12 的外发边界用于判断资格；满足边界后，各方案的剩余隐私与安全风险仍须单独比较，不能由“具备资格”推定为零风险。本文没有完成这些测量，不代替用户决定实施时机。

### 10.1 合并约束、实现选择与候选骨架

| # | 合并方案应满足的要求 | 来源 |
| --- | --- | --- |
| 1 | 在输入和模型满足目标使用范围、且任务满足发布条件时，交付一份含临床与数值独立区块的复合报告；拒绝或 partial 的例外必须显式定义 | 第 7 节沿用的评估目标（原始确认来源待补），不表示已批准合并实施 |
| 2 | 保存完整输入、来源、证据、模型、叙述与版本身份，历史读取保存事实，PDF 交付归档原件；不能依赖当前模型重算历史 | AGENTS.md 的版本、审计、历史与归档要求 |
| 3 | `source_kind` 不直接选择用户可见的报告业务路线，但可以约束来源验证、映射及兼容、获准使用的模型版本 | 方向修订文档第 18、23 行的来源／业务分离与版本接入要求 |

这里的“可用”须拆开判断：输入及来源可受理、模型可加载且兼容、在目标场景获准使用、执行依赖满足。这些都不保证每项预测一定有结果；v3 的 `abstain`／`error` 与整条引擎无法受理也不是同一状态。执行后允许发布什么，由问题 1、2、7–9 决定。

以下是实现选择：

| 选择 | 当前事实与可评估的替代 | 决定于 |
| --- | --- | --- |
| 物理任务拓扑 | 当前 `report_generation_jobs.report_id` 为主键（`models.py:1096`）；一个任务串行执行，或父任务＋子执行后原子发布，都须满足取消、租约、预算与审计。后者不能直接套入当前 job 主键和并发计数 | 问题 10 |
| 快照承载形式 | 当前 `ai_reports.input_snapshot` 是 JSONB（`models.py:1252`），同一列已经承载多版本 schema；单列不要求所有版本形状相同。新的统一 schema、复合 envelope、父子快照均需评估完整性与历史兼容 | 问题 11 |

两引擎是否执行属于来源与使用范围的条件，不能由任务拓扑解决。真实 v3 当前被拒绝；v1 的底层来源支持也不能代替普通录入的绑定建设或临床／生产授权（第 7.2、12.0 节）。

**应保存的身份依据**：下表列出两个代表性 context 的现有字段；具体数值版本选择不同，应补充对应 context。新契约可以组合或重新表达这些事实，但不得丢失其审计与完整性含义。

| context | 字段 |
| --- | --- |
| 旧线路 `ReportGenerationContext`（`schemas/report_document.py:46`–`:62`） | `schema_version`、`disease_code`、`release_set_id`／`release_set_sha256`、`data_release_id`、`dataset_manifest_sha256`、`split_sha256`、`indicator_catalog_sha256`、`indicator_labels`、`minimum_visits`、`minimum_signal_observations`、`standard_rules_sha256`、`evidence_token`、`template_version` |
| 数值 v3 `NumericGenerationContextV3`（`schemas/numeric_report_v3.py:33`–`:47`） | `schema_version`、`disease_code`、`numeric_input` 及 `numeric_input_sha256`、`source_binding_sha256`、`model_bundle`、`algorithm`、`task_algorithms`、`references`、`llm_model`、`prompt_text`、`prompt_sha256`、`prompt_version`、`retrieval_settings`、`template_version` |

此外还须保存输入快照、证据快照和最终报告／指纹的关联。当前输入快照为 `longitudinal_input.v1` 与 `numeric_report_input.v1`（`longitudinal_case_service.py:506`、`numeric_report_admission.py:37`）；新身份元组由问题 15 定义。

候选骨架的区别在于复合契约、编排和发布以谁为基础，并不预先要求迁移全部模型内部实现：

- **A（数值侧骨架）**：扩展数值报告的输入／context／文档与发布契约，接入保留的临床区块和旧模型能力。
- **B（旧侧骨架）**：扩展旧报告契约与构建／发布路径，接入数值模型、RAG 和叙述能力。B 不等于放弃训练、评价、数值推理或版本纪律。
- **中立（新建复合层）**：新增明确的复合契约和编排，两侧作为内部组件复用；新增层及跨层适配本身也有成本。
- **混合（H）**：按职责选择以上基础，不要求所有层归同一侧。需要明确每个契约和模块的维护责任。

四种方案都可能保留现有 `ml_models` 注册表和数值 bundle 作为内部子系统；是否迁移模型格式、训练／评价或发布机制，需要逐项证明必要性。共用设施继续按共用设施评估，不因 A／B 命名而迁移全局配置、任务表或归档系统。

逐模块可记录“原样复用／扩展／包裹／迁移／新建”等处置：原样复用不修改组件；扩展修改已有组件；包裹新增适配层；迁移改变责任或存放位置；新建实现新增契约。同一模块可能需要多步处置，不能将这些标签作为互斥成本项反复加总。每项改动都须落到文件、契约、验证要求和不确定性。

| 影响层 | 数值侧候选基础 | 旧侧候选基础或共用设施 |
| --- | --- | --- |
| 1 输入与病例生命周期 | `numeric_report_admission.py`、`prediction_case_source.py`；后者依赖的合成来源校验与旧输入转换见第 0 节 | 共用的 `longitudinal_case_service.py`，需处理编辑与冻结；来源基础类型与辅助函数的兼容影响须同时覆盖第三条线路 |
| 2 模型子系统 | `numeric_history_*`、`prediction_calculation*`、`prediction_candidate_training.py`、`numeric_model_dispatch.py` | `ml_models` 注册表／发布集／活动指针 |
| 3 证据契约 | `numeric_report_evidence.py` | `evidence_bundle.py`、`standard_evidence.py`、`reference_case_*` |
| 4 执行与发布 | `numeric_report_publication.py`、`numeric_report_v2.py`、`numeric_report_v3.py` | `report_document_builder.py`、`report_publication.py` |
| 5 报告文档与指纹 | `numeric_report_document.v1/v2/v3` | `report_document.v1`；共同受数据库发布约束约束 |
| 6 历史读取 | `report_read_service.py` 的数值分支 | 同文件的旧分支 |
| 7 展示与 PDF | 数值组件及渲染分支 | `LongitudinalReportView.vue`、`report_pdf.html` 等共用容器及旧分支 |
| 8 任务与结果语义 | 6／12 月任务与基线状态 | 365 天风险／阶段／next-visit trends |
| 9 切换与回滚 | `NUMERIC_MODEL_BUNDLE` 的新受理配置 | 发布集活动版本；需定义两侧配置的兼容组合 |
| 10 API／线路路由 | 数值 kind 与前端分支 | 旧 kind、共用 API／store 与待恢复请求 |
| 11 预算与成本 | 共用 `core/config.py`、worker 及队列限制 | 同一组共用设施，按实际新增执行和测量调整 |

### 10.2 逐层差异矩阵

下表是测量清单，全部方案均未完成工作量测量。O／O+ 的目标差距按第 10.0 节记录；中立与 H 同样能复用两侧资产。下列六项是贯穿十一层的记录维度，不是新增影响层；O／O+ 与 A／B／中立／H 均按相同口径记录。每项注明证据、观察周期、估算区间或待测状态，同一改动跨层引用时不重复累计。

| 维度 | 比较记录的最低内容 |
| --- | --- |
| ① 新建／修改代码 | 逐模块处置、契约变化和工作量估算；复用资产单列为收益，不与重写量相加 |
| ② 模型评价与端到端验收 | 可继承证据、需重新评价／验收的范围及成本；区分第 9 节三类边界 |
| ③ 数据迁移 | 受影响的保存数据与版本、迁移验证范围及成本；编写与执行分开 |
| ④ 切换与回滚 | 兼容版本组合、切换／回退验证及成本，记录不能撤销的既有发布事实 |
| ⑤ 运行及持续维护成本 | 同负载下的时延、资源、队列占用及维护工作量，注明周期、单位和估算区间 |
| ⑥ 隐私与安全风险 | 允许处理／外发的字段、接收方与部署／日志留存边界、访问控制与审计证据，以及满足资格门槛后的剩余风险和接受条件；无证据时标待核实，不记为零风险。成本若已计入其他维度，仅引用，不重复相加 |

六项均未完成方案比较；不把不同单位强行汇总为分数。跨层风险需注明涉及的层与责任边界，问题 12 不能替代第⑥项的比较记录。

| 层 | A | B | 中立 | H | 已确认的评估边界 |
| --- | --- | --- | --- | --- | --- |
| 1 输入与病例生命周期 | 待测 | 待测 | 待测 | 待测 | 均需建设手工录入映射、来源证明与生命周期；可复用来源绑定和病例快照；须评估第 0 节合成来源校验／旧输入转换依赖，不能推定整层全新实现 |
| 2 模型子系统 | 待测 | 待测 | 待测 | 待测 | 按第 8 节逐模块判定保留／适配／重建／不受影响；单列 runtime 制品重建、证据继承和重新评价 |
| 3 证据契约 | 待测 | 待测 | 待测 | 待测 | 均可复用 numeric RAG、批准标准和结构化相似病例；组合状态、身份与 LLM 输入边界待定 |
| 4 执行与发布 | 待测 | 待测 | 待测 | 待测 | 当前 1 个旧 builder＋3 个数值 builder；需组合完整性校验、叙述、失败与发布规则 |
| 5 文档与指纹 | 待测 | 待测 | 待测 | 待测 | 新契约按第 6 节建立新版本与迁移；不能把约束弱的旧版本当作捷径 |
| 6 历史读取 | 待测 | 待测 | 待测 | 待测 | 保留旧 schema 与保存事实的读取，增加新版本验证 |
| 7 展示与 PDF | 待测 | 待测 | 待测 | 待测 | 复合区块布局、渲染与校验分支、renderer 制品、历史原件 |
| 8 任务与结果语义 | 待测 | 待测 | 待测 | 待测 | 权威任务集合、冲突裁决、逐任务缺失及 partial；物理任务拓扑另定 |
| 9 切换与回滚 | 待测 | 待测 | 待测 | 待测 | 定义新请求使用的兼容版本组合，保持已受理身份；评估活动配置、应用与迁移回退，不默认能够撤销已有发布事实 |
| 10 API／线路路由 | 待测 | 待测 | 待测 | 待测 | kind、别名、幂等请求、历史筛选与 pending request 兼容 |
| 11 预算与成本 | 待测 | 待测 | 待测 | 待测 | 按相同交付模式与负载测量第 8.1 节各项，禁用状态不作为完整交付的性能替代 |

目前没有选择某一合并骨架的成本证据；也没有证明立即合并优于保留双线路一段时间。两种判断都需要补齐目标范围与上述测量。

## 11. 建议的推进方式

1. 先回答第 12 节影响方案资格的合同问题：目标使用范围、输入来源证明与生命周期、权威任务与冲突裁决、失败／partial、叙述及允许外发的字段。它们是成本估算的前提，不能靠选定 schema 后补答。
2. 对 O／O+ 与 A／B／中立／H 使用相同目标、负载和观察周期。对全部十一层按第 10.2 节六项维度分别记录：①逐模块处置及代码／契约改动；②组件证据继承、模型评价与端到端验收；③迁移；④切换与回滚；⑤运行及持续维护；⑥隐私与安全风险（包括满足资格门槛后的剩余风险）。成本未知项给出有依据的区间或标待测，并说明核实办法；风险注明证据与接受条件，不以行数直接换算工期或以资格通过替代风险比较。
3. 根据目标符合度、测量结果和明确取舍决定是否现在实施及骨架。真实来源的准备与合并可共同设计，但是否同一阶段交付由问题 8、18 决定。
4. 获得方案确认后再编写设计文档（`docs/superpowers/specs/`）和分步实施计划（`docs/superpowers/plans/`），分别安排回归、隔离集成与端到端验收。
5. 在设计与计划里区分编写迁移和执行业务库迁移，并列明活动配置切换、外部 LLM／真实资料使用及生产／临床发布等需独立授权的动作。

## 12. 未决问题（合同问题在前）

### 12.0 来源、执行与发布场景

“数值引擎可用”不能作为未解释的单一条件。至少分别记录：

- **输入可受理**：病例／疾病／权限满足，且有合法预测输入与来源绑定。未来普通录入的确定性派生尚待建设。
- **实现可执行**：指定算法或 bundle 可加载、身份一致并兼容该输入；空配置选择 v1，与配置损坏导致失败是不同状态。
- **目标场景获准**：该来源、模型与数据处理方式是否获准用于本次工程验证或临床／生产场景。当前 `clinical_validity_claim=false`／`production_enabled=false` 不能因为设置了真实来源就变为 true，也不能靠添加免责声明替代授权。
- **依赖满足与执行结果**：检索／LLM 等依赖、预算及运行状态；单任务 `abstain`／`error`、整条任务失败和获准的 partial 发布要分别表达。

**代码现状与拒绝时点**：

| 条件 | 就绪检查 | 新提交／执行 | 证据与边界 |
| --- | --- | --- | --- |
| 数值新受理关闭，或缺少来源绑定 | 返回对应 blocker | `build_numeric_snapshot` 拒绝，分别为 `numeric_reports_unavailable`／`prediction_source_required` | `numeric_report_admission.py:22`–`:35`；提交在 `report_generation_service.py:100` 与 `:146` 构造／复核快照。关闭新受理不取消已受理任务 |
| 已通过数值准入，bundle 配置为空 | 按 v1 捕获 context | 选择 v1 基线，不执行检索或 LLM | `numeric_model_dispatch.py:55`–`:59`、`report_execution.py:40`–`:43`。非空但损坏／未知 bundle 失败，不自动回退 v1 |
| 非 v1 的 LLM 密钥为空 | 内部抛 `numeric_narrative_configuration_missing`，对外转换为 `model_unavailable` blocker | 提交直接捕获 context，没有调用该就绪检查；仅此缺项不保证提交时被拒。若其他条件通过且执行到叙述调用，调用异常映射为 `numeric_narrative_llm_failed` | `numeric_model_dispatch.py:71`–`:83`、`report_generation_service.py:125`–`:156`、`numeric_report_v2_admission.py:14`–`:24`、`numeric_report_v3_admission.py:13`–`:31`、`numeric_report_narrative.py:108`–`:111`、`numeric_report_narrative_v2.py:136`–`:139`。这是代码路径核对，未为本评估实际提交失败任务 |
| 真实输入选择当前 v3 | context 捕获被拒 | 新提交被拒，schema／推理也保留 synthetic 限制 | 第 7.2 节四处校验。这不同于 v1 底层接受 real，也不同于模型获准临床／生产使用 |

最后两行意味着**页面就绪不是服务端准入的完整等价物**。合并设计须确定检查在哪些入口实施、事务内复核哪些条件，以及受理后依赖变化如何失败。本文只记录现状，不在此次文档修订中修改服务端。

**用于设计的场景矩阵**（不是当前已实现能力清单，发布策略均待定）：

| 场景 | 必须定义的规则 | 决定于 |
| --- | --- | --- |
| 普通录入，尚无合法预测输入／绑定 | 完成确定性映射、来源证明、冻结与绑定；不能因为 `NumericInput` 可构造就视作数值准入通过 | 问题 3、4、5 |
| synthetic 输入已绑定，指定模型／依赖满足工程范围 | 冻结两侧身份、执行权威任务、构建独立区块；如实保留逐任务状态及工程证据边界 | 问题 1、2、5、6、7、8、13、15、16 |
| 真实输入已完成映射／绑定，有兼容且获准的数值模型 | 两侧准入与保存身份；不以合成验收代替真实适用性证据 | 问题 3、4、5、8 |
| 真实输入已完成映射／绑定，没有适用于目标范围的训练模型 | 按下述同一决策树选择获准的 v1 工程基线、临床区块 partial 或拒绝／延期 | 问题 8、9 |
| 任一来源，路线开关关闭、bundle 损坏、依赖缺失或运行失败 | 分别定义拒绝时点、是否允许既定降级／partial，以及可恢复状态；不能统一写成“引擎不可用” | 问题 5、7、9 |
| 两引擎执行拓扑 | 串行单任务、父子执行或并行执行后原子发布；阶段与预算、取消和租约 | 问题 10、第 8.1 节 |
| 叙述失败、越界或不符合外发条件 | 是否拒绝整份报告或允许无叙述的确定性区块；不得伪称 LLM 成功 | 问题 7、12、13 |
| 最终发布 | 发布资格、身份元组、文档与指纹、历史兼容 | 问题 7、14、15、16、19 |

真实来源的 v1 支持应准确表述为：`schemas/numeric_prediction.py:14` 允许 real，`services/numeric_prediction.py:94` 的计算没有 synthetic 限制；但报告提交仍要求开关、权限、有效绑定等条件，普通录入当前缺少后者。v1 证据固定 `clinical_validity_claim=false`／`production_enabled=false`（`schemas/numeric_report.py:65`–`:66`），仅提供基线且没有 RAG／LLM，不能计作完成训练模型全流程。

**问题 8 与 9 是前后相依的决策，不是两个互斥场景**：

1. 先由问题 8 确定允许的来源与使用范围。范围外的请求不受理；范围内仍须完成映射、来源证明与其他准入条件。
2. 再检查有没有兼容且获准用于该范围的训练模型。有则按指定版本执行；模型没有提供可用结果时按逐任务规则处理。
3. 没有适用训练模型时，由问题 9 决定是否允许 v1 作为明确的工程基线替代。允许也不取得临床／生产授权，且必须如实表示训练模型／检索／LLM 未执行，记录与完整目标的差距。
4. 不允许该替代时，明确选择仅临床区块的 partial，或拒绝／延期；partial 本身也必须满足该临床区块的来源适用性、证据与发布条件。没有答案时不默认降级。

### 12.1 必须先回答的合同问题

1. 每病种的**权威任务集合**是什么？365 天风险、下一阶段状态、next-visit trends、6／12 月数值任务如何各自表达执行、弃权、错误和缺失？
2. **跨引擎结果重叠、冲突与权威性如何裁决**？决定结果权威来源，是否并列展示冲突，LLM 是否可解释冲突，以及冲突对发布资格的影响。
3. **手工录入的 canonical provenance 如何建立**？分别决定第 7.1 节的内容保存／摘要与生成主体、权限、病例版本、映射版本、审计之间的不可变关联。
4. 手工病例**何时冻结**？编辑后生成新版本、重新绑定还是整例只读？如何保留旧绑定、在途任务与报告的关系？
5. **来源兼容、模型证据状态、bundle／发布集选择及活动版本回滚**由什么统一合同控制？就绪、提交与事务内复核各负责什么，如何避免只能由页面阻止的请求？
6. **正式标准、结构化相似病例与数值 RAG 片段**如何组合？明确访问范围、固定身份、缺失／partial 状态，以及哪些内容可以进入 LLM。
7. **逐任务不可用、单侧失败或 LLM 失败时**，整份报告是否允许发布？区分正常弃权、错误、取消、超时与业务认可的 partial；既有幂等和租约语义如何保持？
8. **本次交付的来源与使用范围**是什么：仅 synthetic／demo，是否包含真实来源的受控工程验证，还是另有临床／生产目标？分别需要哪些证据与授权？现有合成模型与报告记录不能证明真实来源临床／生产目标已满足。
9. **问题 8 允许的范围内，没有适用训练模型时如何处置**？是否允许在合法映射与绑定完成后使用 v1 工程基线；若不允许，是仅临床区块 partial，还是拒绝／延期？这是第 12.0 节同一决策树的后续分支。标注无临床证据不能替代所需授权，也不能把 v1 算作已执行 RAG／LLM 的完整目标流程。
10. **执行拓扑**：一个物理任务，还是父任务＋子执行后原子发布？子执行是否占 job 行、计入全局 running 数？`REPORT_JOB_CONCURRENCY=1` 的校验和领任务锁（`core/config.py:66`–`:67`、`report_job_repository.py:91`–`:96`）与 `report_id` 主键都需评估；同时定义总／阶段预算、取消与租约收敛。
11. **输入快照的承载**：单一新 schema、复合 envelope，还是父子快照？同列 JSONB 可承载多版本，决定因素是完整性、审计、读取和生命周期，不能从列数推出唯一方案。
12. **真实病例进入 LLM 的外发边界**：允许发送哪些病种、日期、观测、预测和检索字段？去标识、供应商／部署位置、日志留存与审计如何约束？不满足条件时是否禁用叙述或拒绝发布？代码仅证明调用配置的兼容接口，不能单据此认定跨境传输。
13. **LLM 叙述范围、内容过滤与来源展示**：只解释数值区块，还是也生成临床区块的文字？定性解释可保留现有禁数字规则；若生成内容需包含具体数值、日期或模型术语，就须调整 prompt、schema 校验与事实边界（`numeric_report_narrative_v2.py:9`–`:14`）。`filter_input` 无条件调用，`filter_output` 经 `apply_medical_filter=True`（`numeric_report_narrative.py:106`／`:116`、`numeric_report_narrative_v2.py:134`／`:144`）。现有叙述还禁用 synthetic／合成／模拟／测试数据标签（`numeric_report_narrative_v2.py:83`–`:84`）；方向修订文档明确来源保留在后端审计／版本／快照，主界面去除专用标签，因此这与 AGENTS.md 的来源可追溯要求**并不自动冲突**。若改变来源展示位置或文字范围，再评估校验与展示契约；保持医疗过滤、内容净化和审计。
14. **报告顶层结构**：数值与临床区块如何组织，同时满足第 7 节沿用的临床内容保留及独立区块目标（确认来源限制同该节）？
15. **持久业务身份元组**是什么？至少决定 `analysis_type`、`report_kind`、输入／context／证据／document schema、指纹及 LLM 模型／prompt 身份之间的关联；检查数据库约束、历史筛选、展示和类型生成，不丢弃现有保存事实。
16. **新指纹版本号**如何分配，并如何与 schema、发布约束和历史兼容绑定？遵守第 6 节不可变版本纪律，不在原版本号下重新解释已发布报告。
17. 旧线路**历史报告**如何呈现？是否需要标注生成时的契约版本，同时继续读取原内容和 PDF 原件？
18. **是否分阶段交付**，每阶段完成哪些契约、区块和来源范围？若完整产品目标延期，怎样明确该阶段未完成的能力？
19. **API 兼容**：旧 kind 是否保留、别名兼容多久、幂等请求摘要及 sessionStorage pending request 如何恢复？恢复观察不能自动变为重新生成。
20. **第三条线路 `synthetic_numeric`** 保留、并入还是退役？即使不并入，也需确定共享依赖与历史兼容边界，包括第 0 节的来源校验、旧输入转换及共用来源类型；不得通过移除共用模块破坏它。

## 13. 依据

- [预测模型重构总领文档](2026-09-09-prediction-model-refactor-master-design.md)
- [统一预测流程与报告展示：方向修订](2026-09-14-unified-prediction-report-direction.md)（来源与业务契约分离；“仍会保留两种业务路径”是对仅统一展示层的条件性说明）
- [阶段三计划](../plans/2026-09-15-prediction-model-refactor-phase-3-offline-comparison.md)（"本阶段不改UI、API、worker或数据库"）
- [阶段四设计](2026-09-16-prediction-model-refactor-phase-4-history-integration-design.md)
- [阶段五设计](2026-09-20-prediction-model-refactor-phase-5-local-demo-release-design.md)与[阶段五验收记录](../notes/2026-09-20-prediction-model-refactor-phase-5-local-demo-release-result.md)
- [报告发布与恢复运维文档](../../OPERATOR_REPORT_OPERATIONS.md)（新代码须重建 manifest，同时**保留**旧 manifest 与旧归档原件）
- 代码：`app/db/models.py`、`app/core/config.py`、`app/schemas/report_document.py`、`app/schemas/numeric_report.py`、`app/schemas/numeric_report_v3.py`、`app/schemas/numeric_prediction.py`、`app/schemas/numeric_history_prediction.py`、`app/schemas/numeric_model_bundle.py`、`app/schemas/numeric_history_bundle.py`、`app/schemas/longitudinal_evidence.py`、`app/workers/report_execution.py`、`app/workers/numeric_report_execution.py`、`app/workers/numeric_report_v2.py`、`app/workers/numeric_report_v3.py`、`app/services/numeric_model_bundle.py`、`app/services/report_pdf_renderer_manifest.py`、`app/services/report_document_builder.py`、`app/services/numeric_report_publication.py`、`app/services/report_job_repository.py`、`app/services/report_read_service.py`、`app/services/report_generation_service.py`、`app/services/pdf_generator.py`、`app/services/numeric_report_admission.py`、`app/services/numeric_report_v3_admission.py`、`app/services/numeric_report_evidence.py`、`app/services/report_generation_context.py`、`app/services/longitudinal_case_service.py`、`app/services/prediction_case_source.py`、`app/services/numeric_model_dispatch.py`、`frontend/src/components/operator-case/OperatorCaseWorkspace.vue`、`frontend/src/components/LongitudinalReportView.vue`
- 提交：`2650d27`（引入写死线路的测试）、`1ef6ef5`（反转该行为）

### 13.1 证据边界

本次复核区分当前代码／业务库事实与历史验收记录。下列缺口明确保留，不据此补造结论，也不将其作为已经完成的测量：

| 事项 | 本文可支持的范围与缺失证据 |
| --- | --- |
| 第 7 节两项目标 | 作为既有评估条件沿用；缺原始产品确认记录，方案选定前须补充来源或重新确认 |
| 第 14 节 v0.14 → v0.15 的“上一轮 4 Important／2 Minor” | 该表所列 I1–I4／M1–M2 的自身计数可确认；缺对应原始审查全文，不能把它认定为第十三轮 1 Critical／7 Important／2 Minor 的原始总数 |
| 阶段五历史验收 | 可读取验收记录和归档 `outputs/numeric-history-demo-release/2026-09-21-v5/release.json`；未重新查询原隔离测试库或执行全链验收，不能称为当前环境重新通过 |
| 历史测试、模型与 PDF | 第 14 节历轮测试结果保留为当时记录；本次未运行测试、模型或 LLM，未生成报告／PDF，也未逐份校验归档 PDF 内容 |
| 方案比较与上线资格 | 第 10 节六项维度及十一层估算、真实来源的模型适用证据和资格合同问题仍未完成；本文定稿不表示已经选型或满足上线条件 |

## 14. 复审与修订记录

**每一行是"该轮修订当时"的记录**：其中的问题编号、数字与措辞保持当轮原样，不随后续版本回改；跨轮变化在同轮行的"修订"列或下一轮的首行说明。

### v0.1 → v0.2（第一轮复审：3 Critical／8 Important／3 Minor，逐条核实后全部成立）

| 复审发现 | 修订 |
| --- | --- |
| C1「只有四处差异／重复的已共用」是事实错误：两条线路**并不共同调用**该构建器 | 改为按职责的差异矩阵与共用／未共用两层清单；补证据契约差异 |
| C2「统一输入后真实数据只换来源、体验不变」不成立 | 新增 7.2 节，拆成三个独立前提 |
| C3 方案 B 代价被夸大 | 第 10 节改写 B 的真实代价 |
| I1 任务语义两边都过度简化 | 第 4 节改写 |
| I2 行数口径不对称 | 补口径说明，明确不得据此判断移植工作量 |
| I3 LLM 说法需限定版本 | 第 4 节改写（v1 不调用，v2／v3 各一次） |
| I4 漏 `ck_ai_reports_fingerprint_version` | 第 6 节重写为 7 条 |
| I5 影响面低估 | 第 8 节扩为八层（v0.4 再补第 9 层） |
| I6「阶段三／四／五全部重做」高估 | 见 v0.3 的进一步修正 |
| I7 未决问题没问到合同层 | 第 12 节改为合同问题在前 |
| I8「产品决定被推翻」措辞超出证据 | 第 2.1 节改写 |
| Minor：时间与来源口径、renderer「失效」措辞 | 第 3、9、13 节修正 |

### v0.2 → v0.3（第二轮复审：1 Critical／5 Important／3 Minor）

| 复审发现 | 核实结果 | 修订 |
| --- | --- | --- |
| C1 没有证据支撑"本次采纳方向 A"，且与文档自身决策标准矛盾；未评估"中立组合层" | **成立**：第 10 节确实要求按改动量选择，而结论直接采纳 A | 第 1 节降级为**待验证候选**；第 10 节新增**中立方案**与按层比较矩阵；第 11 节改为"先补测量，再定骨架" |
| I1「已绑定输入病例只读」被错列为旧线路输入契约 | **成立**：旧线路会**拒绝**带 `prediction_source` 的病例（`report_generation_service.py:102`） | 第 4 节拆为两行：病例编辑与准入／来源绑定与冻结生命周期 |
| I2 手工录入的来源身份表述不够严格 | **成立**：`manifest_sha256` 等证明的是文件字节，页面录入无此文件 | 第 7.1 节新增 (a)／(b) 二选一，明确**不得伪造包身份** |
| I3 约束被写成双向等价、标题与推论冲突 | **成立**：数据库实现是单向蕴含，仅 v6 排他 | 第 6 节改为「vX → 条件」，标题改为"在采用新契约版本时应触碰" |
| I4 阶段三证据表述自相矛盾 | **成立** | 第 9 节改为「组件级证据可继承，线路级验收必须重做」 |
| I5「权限与审计共用」过宽 | **成立**：数值线路另有准入条件，审计与任务投影语义不同 | 第 5.1 节按"设施共用／语义各自实现"改写 |
| Minor：worker 用时、来源口径、对上一轮意见的概括失真 | **成立**。实测 `worker_seconds=3.059546`；来源含 Git 与归档记录；上一轮原话是"只服务旧线路"，我此前的转述写成了"两条线路都不用" | 第 3 节改为精确耗时；第 1 节补口径；本表按原话更正 |

### v0.3 → v0.4（第三轮复审：1 Critical／**7** Important／1 组 Minor；表格实为 I1–I7 共 7 条）

| 复审发现 | 核实结果 | 修订 |
| --- | --- | --- |
| C1「真正区分 A／B／中立的只有第 2、4 两层」无证据，会错误缩小测量范围 | **成立**，且逻辑上不成立：输入层、证据层、展示层同样有各不相同的可复用资产（A 可复用数值来源绑定与 numeric RAG；B 可复用病例快照、批准标准与结构化相似病例 bundle；两侧各有报告组件与 PDF 验证分支） | 第 10.2 节**删除该断言**并说明理由；第 11 节改为"测量必须覆盖全部九层" |
| I1 行数分组不完整：漏 `prediction_calculation*`／`prediction_history*`／`prediction_stability*` | **成立**：实测 611＋809＋131＝**1,551 行**，六组合计 **3,568 行** | 第 4 节改为按职责六组列出并给出合计；点明 `prediction_history_*` 是 v3 历史模型的核心 |
| I2「相关 CHECK 共 7 条」是事实错误 | **成立**：业务库实测 `ai_reports` 共 **13 条 CHECK**，漏的正是复审列出的 6 条字段类约束 | 第 6 节改为"共 13 条，其中 7 条与版本及发布映射直接相关"，并声明其余 6 条不必然修改 |
| I3 采用 v7 并不无条件要求调整 `ck_ai_reports_engineering_evidence` | **成立**：实测该约束第一分支「三种证据状态都不是 `not_requested`」对任意指纹版本成立 | 第 6 节推论改为"不一定需要调整"，并写明触发条件 |
| I4 影响面缺 API／准入路由／客户端线路选择层 | **成立**，且**本次实际故障正出在这一层** | 第 8 节新增第 9 层，列出 `report_kind` 的六个存在位置与兼容问题；第 12 节补 API 兼容问题 |
| I5 (a)／(b) 只解决内容身份与完整性，未建立完整 provenance | **成立**：`prediction_case_source.py:108` 文档字符串原文即 *"hashes detect corruption, not source authenticity"* | 第 7.1 节拆为「canonical content identity／integrity」与「source authority 与 lineage」两件事 |
| I6「用户已表达倾向方向 A」在可核对材料中无依据 | **成立**：该表述来自对话，仓库内无记录，且可能造成锚定偏差 | 第 1 节改为"对话中的非正式偏好、仓库内无记录、不构成本文依据" |
| I7 缺"跨引擎结果重叠、冲突与权威性"的合同问题 | **成立** | 第 12 节新增问题 2（权威结果、是否并列声明冲突、LLM 能否解释冲突、冲突是否影响发布资格） |
| Minor：`prediction_case_source.py:470` 不存在、`:140` 应为 `:144`、narrative 调用点、粗体引号未闭合 | **全部成立**：该文件仅 205 行；`:144` 是锁内复核分支；v2 调用点在 `numeric_report_narrative.py:99` | 逐条修正引用与排版 |

### v0.4 → v0.5（第四轮复审：1 Critical／**6** Important／2 Minor；表格实为 I1–I6 共 6 条）

| 复审发现 | 核实结果 | 修订 |
| --- | --- | --- |
| C1 比较框架仍不可执行，且内部矛盾 | **成立**：①第 8 节已十层而第 10.2 节只有八行；②"三方案相同"是未测量的断言；③A 与中立定义不互斥（扩展 numeric context ＋新增协调器可同时满足） | 第 10 节重写：先按**七个所有权的归属**把三方案定义为**互斥**选项；矩阵补齐为十行并将**所有未测量格子标为"待测"**，删除全部"三方案相同"表述 |
| I1 `reference_case_*`（1,164 行）归入数值线路是错的 | **成立**：它由**旧线路**的 `evidence_bundle.py:23` 调用，使用 `longitudinal_evidence` schema；数值 RAG 用冻结的 `numeric_reference.v1` 片段，不引用这些模块 | 第 4 节改为**三类模块清单**（数值专属 4,786／旧线路专属 12,802／共用 1,616）；更正数值非前缀小计为 **2,404**；明确不再按前缀作对称比较 |
| I2 第 6 节称"精确语义"但漏 v3–v6 的共用完整性条件 | **成立**：实测还要求 `analysis_type`、`status='completed'`、`report_document` 及摘要、`generation_fingerprint`、`input_snapshot` 及摘要、`evidence_snapshot` 及摘要 | 第 6 节先列**共用骨架**，再列各版本附加条件 |
| I3 第 6 节结论句写反 | **成立**：原文语义像是在认可复用旧版本号；且只有约束较弱的 v1／v2 存在物理绕过空间 | 改为"复用 v1／v2 物理上可能通过但违反不可变版本纪律；**新增指纹才是架构上正确的做法**" |
| I4 模型子系统被压缩成发布与回滚 | **成立**：数值侧离线→在线全链含任务与特征定义、训练、配对评价与稳定性、bundle 构建与协议绑定、JSON 导出、runtime 校验、在线 loader／dispatch／排队固定 | 第 8 节第 2 层展开为逐项四类处置（保留／适配／重建／不受影响） |
| I5 冲突裁决未进影响层，且被错归为"证据层成本" | **成立** | 第 8 节新增**第 8 层「任务与结果语义」**；第 11 节改为"决定第 4、5、7、8 层成本，不是检索证据契约本身" |
| I6 五个来源字段被统称为"证明实际文件字节" | **成立**：`dataset_id`／`run_id` 是 manifest **声明身份字段**；`manifest_sha256`／`input_file_sha256` 才是**内容完整性摘要** | 第 7.1 节按两类分别表述 |
| Minor：第 1 节"重复面比表面大"语义相反；第 14 节标题计数与表格不符 | **均成立** | 分别改为"共用面比表面大"、计数改为 7 并加注 |

### v0.5 → v0.6（第五轮复审：1 Critical／3 Important／3 Minor）

| 复审发现 | 核实结果 | 修订 |
| --- | --- | --- |
| C1 三方案的所有权定义不符业务语义 | **成立，且是架构级错误**：①`source_kind` 取值只有 `synthetic`／`real`（`schemas/numeric_prediction.py:14`），**与线路无关**；线路由 `report_kind` 决定（`report_generation_service.py:83`）。按 `source_kind` 二选一等于对同一病例只跑一个引擎，而合并报告必须**同时组合两个引擎**。②A／B 的活动配置只写一侧身份，但复合报告必须**同时固定**旧 release set 与 numeric bundle。③"混用即定义不清"不成立，混合所有权可以是明确合理的架构 | 第 10.1 节重写：先定义**五项共同不变量**（单一复合任务、同时固定两套身份、同时执行两引擎、`source_kind` 只选来源规则、统一身份），再只比较"复合契约由谁拥有"；七个所有权改为**可独立选择的决策维度**，A／B／中立降为**角点**，并明确**混合所有权合法** |
| I1 模块归属仍有两处错误 | **成立**：`longitudinal_case_service.py`（523 行）的 `build_input_snapshot` **被数值准入调用**（`numeric_report_admission.py:9`、`:33`）→ 应归共用；`report_publication.py`（145 行）严格依赖 `ReportDocument`／`EvidenceBundle`／旧线路语义（`:8`、`:45`）→ 应归旧线路专属 | 第 4 节更正：旧线路专属 **12,424**、共用 **1,994**、数值侧 4,786 不变 |
| I2 各版本附加条件仍不完整 | **成立**：v4 还要求 `analysis_type='numeric_prediction'` 且三种证据状态全 `not_requested`；v5／v6 还要求该 `analysis_type`、`standard_evidence_status='not_requested'`、`reference_case_status` 属三个允许值 | 第 6 节补全每个版本的 `analysis_type`、文档 schema 与三种证据状态；"照抄骨架"改为"最低参考基线" |
| I3 新合并报告的持久业务身份 `analysis_type` 未列为合同问题 | **成立**：数据库、读取层与前端历史筛选都依赖它 | 第 12 节新增问题 9（统一身份元组：`analysis_type`／`report_kind`／context schema／document schema／指纹版本），原 9–12 顺延为 10–13 |
| Minor：字段名应为 `dataset_version`；第 1 节"完全没有评估第三种选项"已过时；第 14 节计数 | **均成立** | 第 7.1 节改为五个字段全名；第 1 节改为"三种方案均未完成改动量测量"；计数改为 6 并加注 |

### v0.6 → v0.7（第六轮复审：3 Critical／7 Important／11 Minor；复审判定**不通过**，必改项 C1、C2、C3、I1、I3）

| 复审发现 | 核实结果 | 修订 |
| --- | --- | --- |
| **C1 现状不是两条线路，是三条** | **成立**：`report_kind` 是三值枚举（`api/operator_report_jobs.py:31`），`workers/report_execution.py:44` 有第三路分派，`synthetic_*.py` 实测 **2,216 行**，且与数值线路存在跨线路耦合（`schemas/numeric_prediction.py:7` 导入其基类、`_implementation_files()` 计入其文件、`RENDERER_FILES` 含其模板） | 新增**第 0 节范围声明**：本文只讨论两条预测线路，第三条的处置是必须显式回答的合同问题（第 12 节问题 14）；第 1／3／4 节补相应限定 |
| **C2 七个决策维度覆盖不了十层** | **成立**：第 1／2／3／7 层不在七个维度内，但矩阵却给它们写了分化内容——上一轮的「框架不可执行」只从「不互斥」换成了「不闭合」 | 第 10.1 节改为**按影响层逐层给出所有者候选**，A／B／中立在每一层都有定义 |
| **C3 不变量漏两套已被冻结的身份** | **成立**：v3 context 冻结 `llm_model`／`prompt_text`／`prompt_sha256`／`prompt_version`／`retrieval_settings`；输入快照 schema 两侧不同（`longitudinal_input.v1` vs `numeric_report_input.v1`） | 不变量 2 由「两套身份」改为**逐项清单**（旧 context 全字段／数值 context 全字段／统一输入快照与证据快照 schema）；不变量 5 补「输入快照 schema 必须唯一」 |
| I1「旧线路非前缀专属 3,295 行」是过期数字 | **成立**：565＋802＋620＋144＋1,164＋145＝**3,440** | 第 4 节已改 |
| I2 共用面 1,994 行低估 | **成立**：另有点名外的跨路线模块 ≥2,534 行（`pdf_generator.py` 568、`api/operator*.py` 786、`report_integrity.py` 240 等） | 第 4 节新增「跨路线但未点名」一行 |
| **I3 组件级证据的真实边界是「源文件一字节未变」** | **成立**：`verify_numeric_bundle_runtime` 比对 12 个实现文件哈希，不符即抛 `numeric_model_implementation_changed`（`numeric_model_bundle.py:146`、`:167`）；`RENDERER_FILES` 同理 | 第 9 节第 3 条收窄边界，并指明这两组文件恰是合并最可能改动处 |
| I4 缺「任务预算与成本」层 | **成立**：`REPORT_JOB_LEASE_SECONDS=45`／`REPORT_JOB_RUN_SECONDS=300` 是与线路无关的全局常量 | 第 8 节新增第 11 层；第 10.2 节补对应行 |
| I5 合同问题仍缺四项 | **成立** | 第 12 节问题 9 扩为完整身份元组（含输入快照／证据快照 schema、LLM 身份），新增问题 14（第三条线路） |
| I6 `report_kind`「六个位置」不符 | **成立**：实测 ≥13 处 | 第 8 节第 10 层与第 10.2 节改为实测值与完整清单 |
| I7「明确不是指南」引证位置错误 | **成立**：该强制表述出自叙述 prompt（`numeric_report_narrative_v2.py:11`、`:102`），不在证据模块 | 第 4 节第 4 项拆为两处引用 |
| M1–M11 引用／行号／口径 | **全部成立** | 逐条修正（`source_kind` → :14、`prediction_case_source.py` → :109、`numeric_model_bundle.py` → :159、`report_generation_service.py` → :102、narrative 调用点、`OperatorCaseWorkspace.vue` → :56/:59、`ReportHistoryWorkspace.vue` 路径等）；第 4 节补统计口径（仅 `app/services/`，两侧 schemas 各约 1.8k 行未计） |
| 复审指出的**残留倾向性结论** | **成立**：第 1 节「技术上可行且值得进入设计阶段」与自家「没有任何一层完成测量」冲突 | 第 1 节改为「未发现阻断性合并障碍；关键变量集中在第 2、3 层，须由测量确认」，并注明五项不变量是**由产品决定推出的约束**而非独立结论 |

### v0.7 → v0.8（第七轮复审：2 Critical／6 Important／3 Minor；判定**不通过**，必改项 C1、C2、I1–I6）

| 复审发现 | 核实结果 | 修订 |
| --- | --- | --- |
| **C1 把"源文件一字节未变"写成组件证据可继承的真实边界** | **成立**：`verify_numeric_bundle_runtime` 文档字符串明示 *"Admission/worker gate only; historical validation must not call this disk check"*（`numeric_model_bundle.py:159`），`:167` 是运行时准入门禁；bundle 另冻结训练样本／被试／依赖组身份、`parameters_sha256`、评价与来源（`schemas/numeric_model_bundle.py:75`–`:88`）；renderer manifest 是**当前渲染环境**的 fail-closed 门禁（`report_pdf_renderer_manifest.py:92`），而历史报告禁止即时重渲染，**两者不能对称类比** | 第 9 节第 3 条重构为**三类边界**：①复用现有 bundle／renderer manifest 的运行时条件；②组件证据是否可继承（契约等价或重新验证）；③端到端验收必须重做。明确"字节未变"**只属第①类**，不能称为证据继承的边界 |
| **C2 五项"不变量"并非都由两个产品决定推出，提前锁死任务拓扑与输入表示** | **成立**：`models.py:1096` 以 `report_id` 为主键只是**实现现状**（父任务＋两子执行、并行后原子发布同样成立）；"同时执行两引擎"缺适用条件——v3 拒绝非 synthetic 输入（`numeric_report_v3.py:53`）、bundle 固定 `production_enabled=false`（`schemas/numeric_model_bundle.py:88`）；"快照 schema 唯一"只在**单列存储**下成立 | 第 10.1 节不变量**由五项收缩为三条**（单一复合交付物／全部冻结身份可复现／`source_kind` 不选引擎），另三项下沉为第 12 节**问题 8、9、10**；第 10.2 节三处依据同步改写，不再引用已降级的不变量 |
| I1 "关键变量集中在第 2、3 层"与 §10.2"没有任何一层完成测量"冲突 | **成立** | 第 1 节改为列出**五层高风险候选**（1、2、3、8、11）、优先级待测；第 9 节第 2 条同步改写 |
| I2 自称"完整清单"的冻结身份各漏三项 | **成立**：旧 context 漏 `schema_version`（`report_document.py:47`）、`disease_code`（`:50`）；数值 v3 漏 `schema_version`（`:33`）、`disease_code`（`:34`）、`template_version`（`:47`） | 改为按两个 Pydantic context **列全身份字段**，删除"完整清单／漏一项即不可复现"的措辞 |
| I3 第 11 层漏掉数值模型推理本身 | **成立**：`workers/numeric_report_v3.py:31` 先跑 `predict_numeric_history_bundle`，`:24` 还要校验 bundle runtime，之后才检索（`:39`）与调用 LLM（`:45`）；另有分阶段预算 `LOAD 60／PREDICTION 120／EVIDENCE 30／RENDER 30／PERSIST 5`（`core/config.py:33`–`:37`） | 第 8 节第 11 层改为**六项成本逐项列全**，并补总预算＋阶段预算 |
| I4 A／B／中立仍无可执行定义 | **成立** | 第 10.1 节新增**五类处置**（复用／扩展／包裹／迁移／新建）、三个角点与**混合（H）**的确切定义，并补**逐层候选目标模块表** |
| I5 合同问题缺"真实来源 numeric bundle 不存在时如何处置" | **成立**：第 7.2 节已述现状，但未列为待决问题 | 第 12 节新增**问题 8**（拒绝准入／partial 发布／仅限 synthetic），并新增**12.0 合同矩阵**；第 7.2 节补指向 |
| I6 "跨路线未点名 ≥2,534 行"无法复算 | **成立**：左列九项之和实为 **2,158**（568+240+529+257+179+163+173+23+26） | 第 4 节改为与左列逐项相符的 **2,158**，并补口径（仅 `backend/app/` 点名文件；两侧 schema 另计 1,708／1,821 行） |
| Minor：§11"全部十层"应为十一层；§7.1 `version` 应为 `dataset_version`；§0"2,216 行含前端分支"易误读 | **均成立**：2,216 经实测为 `schemas/`／`services/`／`workers/` 下 **13 个** Python 文件之和（63+213+147+14+290+153+193+261+202+391+62+182+45） | 逐条修正 |
| 复审建议补充"来源适用性 × 执行拓扑 × 失败语义"合同表 | **采纳** | 新增第 12.0 节：八种场景逐格列出必须定义的规则与对应问题号 |
| 问题编号变化 | — | 合同问题新增 8、9、10，原 8–14 **顺延为 11–17**；第 0 节与第 10.2 节的交叉引用已同步 |

### v0.8 → v0.9（第八轮复审：**无 Critical**／4 Important／13 Minor；判定**不通过**——首轮未出现 Critical，复审认为四条必改项"可局部修补、不需重写"）

| 复审发现 | 核实结果 | 修订 |
| --- | --- | --- |
| **I1 被删除的定向断言在两处存活** | **成立**：§1 第 3 点仍写"主要风险在模型与证据层，不在报告文档本身"——**正是第 1 段刚删掉的断言**；§9 第 2 条仍写"未测量面最大……风险不在报告文档本身"，且同句自称"已删除此前的定向断言"，自相矛盾 | 两处均改为"只列风险、不给优先级、不排除任何层"；§1 高风险候选补第 4 层（LLM 叙述与内容过滤） |
| **I2「产品不变量」的类定义与成员不符** | **成立**：逐一验证两条产品决定——第 1 条可推出、第 3 条由第 1 条推出、**只有第 2 条推不出**（由 AGENTS.md 支撑） | 类名改为**合并硬约束**并加"来源"列（两条产品决定＋一条 AGENTS.md 既有要求）；第 0 节同步 |
| **I3 §10.1 三处内部矛盾** | **成立**：①第 223 行用"必须同时组合两引擎"否定 v0.5 中立方案，同一节 13 行后又把同一命题列为"缺适用条件"；②下沉表表头判据是"架构上有等价方案"，该行理由却是"适用性未定"——**不同范畴混表**；③硬约束 1 写"含两类独立区块"，问题 8 选项 (b) 却允许"仅临床区块 partial" | ①加"在数值引擎可用时"限定；②该项**移出表**，单列为**条件性要求**；③硬约束 1 补**适用条件**并声明 (b) 为**显式例外** |
| **I4 覆盖缺口：内容过滤与叙述 validator** | **成立**：`content_filter.filter_input`／`filter_output` 经 `apply_medical_filter=True` 在叙述入口生效（`numeric_report_narrative.py:116`、`numeric_report_narrative_v2.py:144`）；叙述 prompt 规则**按数值文本面裁剪**（`:9` 禁方法词、`:12`–`:13` 禁任何阿拉伯数字、`:11` 强制"缺少指南证据"），**不能原样套用于必然含数值与日期的临床区块**；AGENTS.md 明确要求保留内容净化与医疗内容过滤，而全文此前**零命中** | 第 8 节第 4 层补该机制；第 12 节新增**问题 11**；§11.1 增列该项为分化前提 |
| M1 `numeric_model_dispatch.py:55` 与"逐任务提供者分配"无关 | **成立**：`:55` 是 `capture_configured_numeric_context` 的函数体；真正的分配在 `schemas/numeric_history_bundle.py:111`／`:548`／`:555` | 改正引用 |
| M2 拒绝语句行号与位置数 | **成立**：`numeric_history_bundle.py:191` 是函数定义行、拒绝在 `:195`；错误码实测**四处**而非三处 | 改正行号并补第 4 处 |
| M3 `numeric_*.py` 口径与 glob 不符 | **成立**：2,382 实为 `services/numeric_*.py`；`app/` 下全部 `numeric_*.py` 为 **4,245** | 表内 glob 一律标注 `services/`，并补 4,245／workers 110／框架 699 三处未计入项 |
| M4「三路执行」与第 5.1 节「五种出口」不一致 | **成立**：实为四个显式 `schema_version` 分支（`:32`／`:36`／`:40`／`:44`）＋`:48` 旧线路默认 | 第 0 节改为四个分支＋默认 |
| M5 `report_job_repository.py:131`／`:164` 与阶段预算的关系 | **成立**：`:131` 只用**总预算**算 `run_deadline`，`:164` 只用**租约**；阶段预算实际用在 `workers/report_worker.py:94`–`:100` | 区分使用点并补引用 |
| M6 §10.1 并无"处置"列 | **成立** | 删除该措辞 |
| M7 §10.1 声明混合（H）而 §10.2 只有三列 | **成立** | 补限定：矩阵不覆盖 H，H 由第 11 节逐层测量得出 |
| M8 §1 引用"第 10 节自己的决策标准"，但该判据全文未写出 | **成立** | 判据（复用＋重写总量最小者）写入第 1 节，并注明为全文唯一出处 |
| M9 旧线路拒绝错误码漏 `synthetic_report_kind_required` | **成立**：`report_generation_service.py:103`／`:145` 是三元表达式 | 补充 |
| M10「未发现阻断性合并障碍」偏强 | **成立** | 改为"在已检查范围内" |
| M11"数值引擎不可用"谓词未定义 | **成立**：实测**四种**原因（`NUMERIC_REPORTS_ENABLED` 关闭／`NUMERIC_MODEL_BUNDLE` 为空／`DEEPSEEK_API_KEY` 为空／真实来源 bundle 不存在），**前三种配置可修、第四种不可** | §12.0 新增该四项说明 |
| M12 §14 中 2,216 的 13 项分解顺序 | **不成立**：该顺序与 `find` 输出及文件名字典序一致（…153＋**193**＋261＋202＋391…），合计数亦无误 | **不改**；复审自身亦建议该历史行不必回溯 |
| M13 框架进程控制类 699 行未计 | **成立**：`report_process_control.py` 357＋`report_pdf_process_control.py` 202＋`report_pdf_execution.py` 70＋`report_pdf_publication.py` 49＋`report_database.py` 21 | 在口径段补记，并说明第 11 层的预算／租约分析实际落在这些文件 |
| 问题编号变化 | — | 新增问题 11，原 11–17 **顺延为 12–18**；第 0、10.1、10.2 节交叉引用已同步 |

### v0.9 → v0.10（第九轮复审：**无 Critical**／5 Important／9 Minor；判定**不通过**——复审认为"局部可修补，不需重写"）

| 复审发现 | 核实结果 | 修订 |
| --- | --- | --- |
| **I1 §3"最近一次真实运行＝报告 48"是事实错误** | **成立，且可被一次 SQL 推翻**：只读查询 `surgery_rag` 确认报告 **49** 存在——同为 `longitudinal_predictive`／`v2`／`report_document.v1`／11 节／`completed`／`error_code IS NULL`，排队 **16:52:29**，比 48 的 16:29:07 **晚 23 分钟**；`model_runs` **7**、`charts` **1**（48 为 9／3）。`report_generation_jobs` 共 **2 行**（即 48、49），无"48 是唯一真实运行"的解释空间 | §3 改为"一次完整实测（**不是'最近一次'**）"并写明 49 的存在与差异；§4 第 6 行、§8 第 11 层补"报告 49 为 7 次" |
| **I2 §1 的约束分类口径与 §10.1 冲突** | **成立**：§1 仍写"分成两类"，把"适用性未定"并入"实现选择"、把问题 8–10 一起归给该类——**恰好抵消 v0.9 单列该项的理由**，属第八轮 I1 同类（改动只落一处，摘要节未同步） | §1 改为**三类**（硬约束／实现选择→问题 9、10／条件性要求→问题 8） |
| **I3 §12.0"四种原因"第 2 种不成立** | **成立**：`NUMERIC_MODEL_BUNDLE` 为空时 `capture_configured_numeric_context` **回落到 v1**（`numeric_model_dispatch.py:56`–`:58`），走 `report_execution.py:40`–`:43` 的 v1 分支；该路径的 `numeric_algorithm_identity()` 只校验实现源码哈希（`services/numeric_prediction.py:78`–`:89`）、**不需要 bundle**——线路**并未不可用**，而是退化为不调 LLM 的基线报告 | 改为"训练后的数值模型（v2／v3）不可用，退化为 v1 基线"；并加一句要求问题 8 与硬约束 1 **写明"数值引擎可用"指哪个谓词** |
| **I4 §4 的 4,245 分解不能复算** | **成立**：27 文件实测 ＝ `services/` 2,382（15 文件）＋`schemas/` 1,708（9 文件）＋`workers/` **155**（3 文件：`numeric_report_execution.py` **45**、`v2.py` 55、`v3.py` 55）；v0.9 把 workers 写成 110、漏了 45，2,382＋1,708＋110＝**4,200**≠4,245 | 补 `numeric_report_execution.py` 45 并注明差额来源 |
| **I5 第 11 层与问题 9 漏 `REPORT_JOB_CONCURRENCY`** | **成立**：`core/config.py:38` 的常量 ＋ `:66`–`:67` 校验器 `report_job_concurrency_requires_capacity_review`；`report_job_repository.py:91`–`:96` 用 `pg_advisory_xact_lock(73607)` 按 `count(status='running')` 在**进程间拒领**。与第 10.1 节"父任务＋两子执行架构上成立"直接相关，且会与 `report_id` 主键构成**两道硬门** | 第 11 层补该常量与两道门；问题 9 补"子执行是否计入 `running` 计数" |
| M1 §1"唯一出处"自我指代 | **成立**：第 29 行同节自称"本节"又称"第 1 节引用"；第 22 行仍写"第 10 节**自己的**决策标准" | 第 22 行改"第 10 节的判据"；第 29 行改"唯一出处是第 10 节" |
| M2 §1 风险候选无筛选标准，且与第 10 层矛盾 | **成立**：列了 6 层却无入列依据，而 §8 第 10 层自称"实际故障正出在这一层"却不在候选内 | 补入列依据（有**具体已识别未知项**），并说明第 10 层属**已实现成本**而非待测风险 |
| M3 §9 3(1) 行号 | **成立**：`:167` 是 `if`，`raise` 在 `:168` | 改 `:167`–`:168` |
| M4 问题 11 把 `filter_input` 也说成受 flag 控制 | **成立**：`filter_input` 是**无条件**调用（`numeric_report_narrative.py:106`、`…_v2.py:134`），只有 `filter_output` 经 `apply_medical_filter`（判定在 `…_v2.py:85`） | 拆成两句并注明判定位置 |
| M5 §14 第六轮标题"1 Critical" | **成立**：表内为 C1／C2／C3 | 改为 3 Critical |
| M6 §0 漏第三线路**反向** import 数值侧 | **成立**：`services/synthetic_numeric_prediction.py:9`、`:13` 直接 import `prediction_calculation`，而该模块计在"数值线路专属"611 行内 | §0 补该项并注明**两侧模块清单在此处重叠** |
| M7 §10.2"已识别差异"从不给中立列 | **成立**：中立按定义两侧均包裹，同样可复用 | §10.1 中立定义补"两侧资产同样可复用" |
| M8 引用与执行序 | **成立**：①`numeric_model_dispatch.py:41` 只是 **v1 分支**，"排队固定"由保存 context 的 `model_bundle` 体现（`workers/numeric_report_v3.py:22`–`:31`）；②第 11 层 ①②③④⑤⑥ **非执行序**（③ `:24` 先于 ② `:31`） | 分别改写并注明"编号非执行序" |
| M9 漏叙述的**来源标识禁令** | **成立**：`numeric_report_narrative_v2.py:83`–`:84`、`numeric_report_narrative.py:76`–`:77` 对 `synthetic\|合成\|模拟\|测试数据` 抛 `numeric_narrative_source_label_forbidden`（prompt 亦在 `numeric_report_narrative.py:27`／`numeric_report_narrative_v2.py:14` 明写），与 AGENTS.md「**保持真实、合成、演示和测试数据的来源标识**」**可能直接冲突** | 并入问题 11 的规则清单 |

### v0.10 → v0.11（第十轮复审：**无 Critical**／**1 Important**／6 Minor；判定**不通过**——复审认为"修复面很小、只需复核局部改动"）

| 复审发现 | 核实结果 | 修订 |
| --- | --- | --- |
| **I1 §9.3(1) 的 bundle 运行时门禁只列了 12 个文件，实为 12＋5 个、两个错误码** | **成立**：`services/numeric_history_bundle.py:20`–`:26` 另有 `SOURCE_FILES` **5 个**（`schemas/numeric_history_bundle.py`、`schemas/numeric_history_prediction.py`、`services/numeric_history_features.py`、`services/numeric_history_bundle.py`、`services/prediction_history_features.py`）；`:74`–`:77` 的 `history_implementation_sha256` 把 **5＋12** 一起计入；`:104`–`:107`／`:136`–`:137` 抛**第二个错误码** `numeric_history_implementation_changed`。被漏掉的 5 个里有 `numeric_history_features.py` 与 `prediction_history_features.py`——正是 §8 第 2 层要求逐项处置的**特征定义**模块 | §9.3(1) 补第二层清单、**17 个文件与两个错误码**，并点明漏掉的正是最可能改动处；§8 第 2 层与第 11 层 ③ 同步引用 |
| M1 §12.0 原因 2 的行号区间少一行 | **成立**：回落本体 `return capture_numeric_context(snapshot)` 在 `:59` | 改 `:56`–`:59` |
| M2 §12.0 原因 3 的行号 | **成立**：`:78` 是条件行，`raise` 在 `:79` | 改 `:78`–`:79` |
| M3 问题 11 与 §14 M9 的 `:27` 指代不明 | **成立**：该句在 `numeric_report_narrative.py:27`，而 **v2 的对应句在 `:14`**；上下文列的是 v2 行号，易误读 | 两处均写明两个文件与行号 |
| M4 §9.3(2) 的引用区间不含所断言字段 | **成立**：`parameters_sha256` 在 `schemas/numeric_model_bundle.py:50`，训练样本／被试／依赖组身份在 `:45`–`:49`；`:75`–`:88` 只覆盖挑战集／来源／评价 | 拆为 `:45`–`:50` 与 `:75`–`:88` |
| M5 §1"入列依据"判据覆盖不到被排除的成员 | **成立**：第 10 层同样有未定项（问题 17），排除理由却换成了另一条——与第八轮 I2"类定义与成员不符"**同型** | 判据加限定"**且成本尚未发生**" |
| M6 §8 第 11 层常量清单不全 | **成立**：另有 `REPORT_JOB_QUEUE_SECONDS=600`（`core/config.py:31`，用于 `report_job_repository.py:102`／`:121`／`:352`，在 `report_generation_service.py:226` 施加）与 `REPORT_JOB_QUEUED_LIMIT=20`／`REPORT_JOB_USER_ACTIVE_LIMIT=2`（`:39`／`:40`，在 `:195`／`:197` 施加）；**§3 实测排队 304.21 秒已接近 600 秒预算的一半** | 第 11 层补队列与受理上限，并写明挤压效应 |
| 复审附注：§8 第 10 层清单含**选路行** | **成立**（该行字面不含 `report_kind`，同组文件 `:136`／`:112` 才是字面出现；"≥13 处"仍成立） | 补口径说明（**注：本行当时写入的"字面共 18 处"经第十一轮实测无法复算，见下行 M-2**） |

### v0.11 → v0.12（第十一轮复审：**判定通过**——无 Critical、无 Important；4 条非阻断 Minor，复审认为"一句话可改，不必再审全文"）

**这是十一轮中第一次"通过"。** 复审逐条核到代码行后确认：§14 第十轮那 7 行对应的正文改动**实质全部成立**；§9.3(1) 的补全（5 个文件、17 个、并点明特征定义模块）在代码层面完全站得住；§8 第 2 层与 §11 ③ 的同步引用无一处错。

| 复审 Minor | 核实结果 | 修订 |
| --- | --- | --- |
| M-1 §9.3(1) 第二层句两处口径 | **成立**：`raise ValueError('numeric_history_implementation_changed')` 在 **`:108`／`:137`**（v0.11 写 `:104`–`:107` **不含**该 raise）；且该函数另抛 `numeric_history_loaded_code_mismatch`（`:98`／`:100`／`:132`／`:135`）与 `numeric_history_loaded_module_missing`（`:114`），故"两个错误码"作为**绝对计数**不完整 | 区间改 `:104`–`:108`；"两个错误码"限定为"两个**实现哈希**错误码"并列出另两个码与区间 |
| M-2 §8 第 10 层"字面出现为 18 处"**无法复算** | **成立**：实测后端 `app/` **32 行／34 次**、前端 `src/` 非测试 **14 行／17 次**；上列 15 处中**恰 13 处**含字面量——"18"**不属任何自然口径**。该数是我从第十轮复审的括注中**未经核实即写入**的 | 改为可复算表述（13／后端 32 行／前端 14 行），并注明"18"已删 |
| M-3 §1"入列依据"加限定后**仍过宽** | **成立**：第 5／6／7／9 层的未定项（问题 5／12／13／14／15）成本同样"尚未发生"，会被判为候选，而正文只解释了第 10 层一处排除——与第八轮 I2 同型 | 括注收窄为**该层专属**未知项并逐层列出；补"未入列的层各有理由"（第 5／6／7／9 层属**待选择**而非**待发现**） |
| M-4 §8 第 11 层常量↔使用点**配对反向**，且"接近一半"低估 | **成立**：`core/config.py:39` 的 `QUEUED_LIMIT=20` 用于 `report_generation_service.py:197`、`:40` 的 `USER_ACTIVE_LIMIT=2` 用于 `:195`；实测 304.212／600 ＝ **50.7%，已过半** | 改为配对写法；"接近一半"→"达 50.7%（已过半）" |

### v0.12 → v0.13（第十二轮：只点检上表 4 处改动，判定**通过**；另 3 条措辞精度提示）

**这是第一次只做局部点检的一轮。** 复审确认 4 处新写入的字句**所有数字全部复算一致**（`:104`–`:108` 与 `:136`–`:137`、`loaded_code_mismatch` 四处、13／15、32／34、14／17、50.7%），未发现新的实质不准确；并明确"两个**实现哈希**错误码"的限定精确（全链基于哈希比对的错误码确实只有 `numeric_history_implementation_changed` 与 `numeric_model_implementation_changed`）。

| 点检提示 | 核实结果 | 修订 |
| --- | --- | --- |
| (a) "可复算口径"未写明 grep 限定 | **成立**：不加 `--include=*.py` 时后端为 **49 行／51 次**（差额来自 **17 个 `__pycache__/*.pyc`**）；前端不排除 `__tests__` 为 **30 行** | 补两条限定，使 32／34 与 14／17 严格可复算 |
| (b) "此外全仓…"被读成"上列之外另有 32／14" | **成立**：32／34 与 14／17 是**含**上列 13 处的全仓总数 | 改为"另有全仓口径（**含**上列 13 处，不是'上列之外'）" |
| (c) 判据仍不足以**唯一**挑出这 6 层 | **成立**：第 5／6／7／9 层同样"有专属未知项且成本未发生"，靠紧随其后的独立理由排除 | 判据补第三项"**且本文尚未为该层给出候选**"，使判据本身即可排除第 5／6／7／9 层 |

### v0.13 → v0.14（第十三轮：**用户指派的审查**——1 Critical／7 Important／2 Minor；判定**暂不建议标记为最终通过**）

**这一轮由用户指派，是十三轮里第一次出现"决策规则本身不闭合"类的发现**（此前集中在事实与引用精度）。另：用户侧只读复核确认了报告 48/49、阶段五、13 条 CHECK、17 文件双层门禁、全部行数与 `report_kind` 计数。

| 审查发现 | 核实结果 | 修订 |
| --- | --- | --- |
| **C1 决策判据不可执行，且方向相反** | **成立**："复用"是**收益而非成本**，与"重写"相加再取最小会得出反向结论（复用 1,000 行＋重写 100 行＝1,100，会输给复用 100＋重写 200＝300）；五类处置彼此也不互斥（"复用并做兼容适配"与"扩展"重叠，"包裹"本身含复用）。第 11 层 A／B 的候选目标甚至是同一个全局配置模块 | 判据改为"**最大化已验证资产的复用、最小化增量代码与契约改动**"，并列出须**分别计量**的六项：①新建／修改代码；②模型评价与端到端验收；③数据迁移；④切换与回滚；⑤运行成本；⑥隐私与安全风险 |
| **I1 §1 的筛选规则挑不出所列六层，且错误排除第 10 层** | **成立**：第 10.1 节已为**全部十一层**列出候选目标，故"尚未给出候选"对**入列层同样为假**；第 10 层 2026-09-21 的故障虽已由 `1ef6ef5` 修复，但问题 19 的 `report_kind` 兼容、别名与 pending request **尚未实现**，其合并成本同样未发生 | **删除该筛选规则**，改称"已识别的未知项"，**不构成风险排序、不排除任何一层** |
| **I2 把 v3 全链成本当作当前成本；"当前 bundle 指向 history bundle"不成立** | **成立**：实测当前 `NUMERIC_REPORTS_ENABLED=False`、`NUMERIC_MODEL_BUNDLE=''`；bundle 为空时回落 v1（`services/numeric_model_dispatch.py:56`–`:59` → `report_execution.py:40`–`:43`），v1 **不检索、不调 LLM、不做 bundle 校验** | §9.3(1) 改为"**配置为 v3 history bundle 时**"；§8 第 11 层**按执行模式重构**（禁用／v1 baseline／v2／v3 分别列预算） |
| **I3 §12.0 漏"真实来源＋v1 baseline"一格** | **成立**：v1 路径**无** synthetic 限制（`schemas/numeric_prediction.py:14` 允许 `'real'`；`predict_numeric` 不校验来源，`services/numeric_prediction.py:94`），但 v1 证据固定 `clinical_validity_claim=false`／`production_enabled=false`（`schemas/numeric_report.py:63`–`:64`） | §12.0 补该行；新增**问题 9**；"没有一格被漏掉"改为"力求覆盖，但不声称穷举" |
| **I4 硬约束 3 过于绝对** | **成立**：方向修订文档原文是"**不能靠来源自动选择一种报告**"（该文档 `:18`），且 `:23` 明确真实数据接入"采用新数据版本及所需的新模型版本" | 改为"**不选择用户可见的报告业务路线**；**但可以约束来源验证、映射规则与适用的模型／bundle 版本**" |
| **I5 canonical artifact 与来源证明契约不是二选一** | **成立**：artifact 本身即可作为"真实录入来源证明契约"的组成部分；§7.1 后文另要求 authority 与 lineage，两者维度不排斥 | 改为**两项可组合的设计选择** |
| **I6 §4 类别名与第 0 节已承认的重叠矛盾** | **成立**：`prediction_calculation` 被 `services/synthetic_numeric_prediction.py:9`、`:13` 直接 import，却计入"数值线路专属"611 行 | 表内类别改为"**数值侧模块（相对旧预测线路）**"／"旧侧模块"；口径段补"未计入 2,216 行，但**包含第三线路复用的依赖**，不是系统范围内的'专属'" |
| **I7 缺真实病例进入外部 LLM 的数据出境边界** | **成立**：叙述载荷含**病种、锚点日期、逐条观测（指标／测量日／已知日／数值／单位）、预测结果与检索文本**（`services/numeric_report_narrative_v2.py:62` 起），经**外部兼容接口**（`:45`）；而 `content_filter` 处理的是提示注入与医疗表述，**不是患者数据去标识或出境控制** | §8 第 4 层补该项；新增**问题 12**（允许发送的字段集、去标识规则、供应商与日志留存边界、审计、不满足时是否禁用叙述或只生成确定性区块） |
| M1 "50.7%"不能作为并发容量不足的证据 | **成立**：库中仅 48、49 两个 job，49 晚 23 分钟入队，等待原因未记录 | 保留等待时长事实，补"**原因未记录，不能据此推断队列饱和**；容量风险须由压测或持续运行记录验证" |
| M2 正文混入逐版本纠错说明；首页"未新增断言"不实 | **均成立**（v0.13 确实新增了判据条件） | 正文的"vX 曾…／vX 更正…"**全部移入本节**；首页改为"未新增**代码事实**" |
| 问题编号变化 | — | 新增问题 9、12，全表重排为 **1–20**；交叉引用已逐条重新核对 |

### v0.14 → v0.15（2026-09-23：用户授权修订与自审，待独立复审）

本轮处理上一轮 4 Important／2 Minor，并复核相邻推论。此前修订记录保持原样；本轮是文档编写后的自审，不构成其他审查者对最终版本的通过结论，也没有选定合并方案。

| 问题 | 本轮处理与边界 |
| --- | --- |
| I1 缺少“不合并”的对照 | 新增第 10.0 节 O／O+，区分当前双线路、单独建设统一录入、实际形成复合契约。明确未满足产品目标的基线不能冒充等价交付；收益、成本与延期影响仍待测量 |
| I2 真实录入＋v1 只验证到底层能力，问题 8／9 重叠 | 第 7.2、12.0 节补足来源绑定与提交前提。问题 8 确定来源和使用范围，问题 9 在其范围内决定 v1／partial／拒绝或延期，改为同一决策树 |
| I3 密钥缺失的拒绝时点写得过于笼统 | 第 12.0 节分别记录就绪 blocker、直接提交的 context 捕获与 worker 叙述失败；明确结论来自读代码，未实际提交失败任务。没有修改 API 行为 |
| I4 artifact 与来源证明的维度混淆 | 第 7.1 节拆为内容身份／保存形式与 authority／lineage，两项均需设计；artifact 摘要不代替生成主体、权限和沿革 |
| M1 执行拓扑交叉引用错误 | 场景矩阵指向问题 10；问题 8／9 的其他引用按新含义统一 |
| M2 正文残留逐版纠错 | 正文只保留现行事实与判断；历史修订留在本节，不继续使用“数值专属”等与归属口径冲突的简称 |
| 自审：方向修订文档的条件句被误作保留双线路的决定 | 按原文完整上下文修正第 2、13 节：“仍会保留”描述仅统一展示层的局限，不是长期保留双线路的要求 |
| 自审：来源标签与 AGENTS.md 被写成直接冲突 | 方向文档明确来源保留后端审计／版本／快照；第 12 节不再推导必须由 LLM 输出来源标签。改变展示位置仍需设计 |
| 自审：成本、所有权与快照推论过强 | 第 8.1 节区分禁用、v1、v2、v3，不把拒绝请求算作完整交付的零成本模式；第 10 节允许继续复用共用设施及两套模型子系统，不从 JSONB 列数推出唯一 schema，也不从历史可读推出所有版本必须统一切换 |
| 自审：真实模型与临床文字的条件范围 | 明确训练参数是否复用／重训取决于适用性证据；v1 工程基线不等于完整目标流程。LLM 仅做定性补充时可能沿用禁数值规则，生成具体临床事实时才需相应调整 |

本轮验证：后端 `python -B -m pytest tests/test_cleanup_contracts.py -q -p no:cacheprovider` 为 **7 passed**；8 处相对链接均存在，正文表格列数一致，合同问题编号连续为 1–20，无尾随空白。`report_kind` 源码计数复算为后端 32 行／34 次、前端 14 行／17 次；服务模块行数按换行字节重新统计，与第 4 节口径一致。只读加载设置确认数值新受理仍关闭、bundle 配置为空。

本轮仅修改本评估文档；已有测试允许清单改动保持不变。未重新运行模型、LLM、业务库迁移或端到端报告生成；报告 48／49 与阶段五事实沿用此前只读复核及归档证据。各方案的工作量、真实来源适用证据与运行成本仍未补齐，不能据本次文档修订宣称架构方案或上线条件已通过。

### v0.15 → v0.16（2026-09-23：按本次独立复审的 3 Important／3 Minor 修订）

本次逐条处理六项发现，另核对相邻表述。以下是修改后的核验记录，不冒称另一名独立审查者已对 v0.16 给出通过结论。此前第 14 节记录原文保留，历史事实错误在此追加勘误。

| 发现 | 修订与核验范围 |
| --- | --- |
| I1 第 6 节遗漏 NULL 指纹 | 补足数据库允许 NULL、非空版本只限 v1–v6；区分 CHECK 可通过与应用完整性认可，保留不可变版本纪律 |
| I2 六项维度未承接隐私与安全风险 | 第 10.0、10.2、11 节共同使用六项维度；明确问题 12 是资格门槛，剩余风险仍须比较，待核实不等于零风险 |
| I3 第三条线路的来源依赖漏列 | 第 0 节补来源校验、内存转换与共用类型；第 8、10.1、10.2 节第 1 层及问题 20 承接兼容影响 |
| M1 PDF 共用证据引用不成立 | 第 5.1 节改引共用 Markdown／净化和 Playwright 输出；旧图表辅助函数不再用作跨线路证据 |
| M2 运行时错误码描述与文档字符串行号 | 第 9 节分开模块存在性、导入对象／别名身份、代码对象比对，保留“两个实现哈希错误码”；文档字符串定位至第 160 行 |
| M3 第十三轮“首次”断言错误 | 第四轮 C1 已记比较框架不成立，第六轮 C2 已记不闭合；因此第十三轮开头的“第一次出现”不成立，以本条勘误为准 |

相邻事项说明：

- “上一轮 4 Important／2 Minor”的原始审查出处无法核实，不将其与第十三轮计数等同。第十三轮十条在当前正文的对应位置为：C1 → 第 1、10、11 节（本次补齐第六维度）；I1 → 第 1、9 节；I2 → 第 3、8.1、9 节；I3 → 第 7.2、12.0 节及问题 8／9；I4 → 第 10.1 节要求 3；I5 → 第 7.1 节；I6 → 第 4 节口径；I7 → 第 8 节第 4 层及问题 12；M1 → 第 8.1 节；M2 → 正文与历史记录分离。这只说明当前承接位置，不把“有对应文字”替代事实核验。
- 第十二轮曾记未限定后端文件类型得到 49 行／51 次，本次 `rg` 未复现该结果；在当前目录与工具默认规则下，后端不加 `-g '*.py'` 仍为 32 行／34 次。前端不排除测试为 30 行／33 次。正文继续显式限定源码和测试范围以固定口径，但不声称去掉任何一个限定都必然改变结果。
- 第 7 节原始确认来源缺失，改为明确沿用的评估目标，并同步第 1、10、12 节；不撤销既有目标，也不把文档作者的表述作为确认来源。第 8.1 节将排队期限和两类上限逐一绑定配置名及生效行号。

本轮实际核验（代码基准仍为 `d5b5dd9`）：

- 逐项读取该提交的来源校验／转换、PDF、运行时门禁、完整性检查及配置使用点；修改涉及的代码引用已核对。
- 业务库仅执行 SELECT，`SELECT current_database(), current_setting('transaction_read_only')` 返回 `surgery_rag / on`；从 `pg_constraint` 读取 `ai_reports` 的 13 条 CHECK，以 `jsonb_populate_record` 构造不落库记录，并逐条计算 `(<CHECK 表达式>) IS NOT FALSE`。记录使用 NULL 指纹、`review_probe.v1` 文档、占位摘要及 `complete / available / available` 三种证据状态，结果为 **13／13 通过**。版本列的 `information_schema.columns.is_nullable` 为 `YES`。此结果仅说明 CHECK 行为，不代表插入成功或应用认可。
- `rg -n report_kind backend/app -g '*.py'`／`rg -o report_kind backend/app -g '*.py'`：**32 行／34 次**；省略 glob 的对应命令仍为 **32／34**。`rg -n report_kind frontend/src -g '!**/__tests__/**'`／对应 `rg -o`：**14／17**；省略测试排除条件为 **30／33**。
- 用项目 Python 的只读脚本检查：**8 个相对链接均存在、33 张表列数一致、问题连续为 1–20，第 8／10.1／10.2 节各 11 层、比较维度 6 项、无尾随空白**。已核对正文问题交叉引用；问题 8 → 9 的决策树仍明确禁止无答案时默认降级。
- 原第 14 节 **44,974 字节**逐字节保留，SHA-256 为 `785a961e2a8ecec267d4ffdbee8e7634b80677331954704d877ec7af3441c389`；无关测试文件 SHA-256 前后均为 `d6b244b03a916368502133da487bdc64033b62db4ce8573e0969e57d5f61436f`。

**本次修订判定：可作为评估文档定稿，六项发现均已处理，未发现仍须修改的已知问题。** 第 13.1 节的证据缺口和第 12 节未决合同问题继续保留；待测量不被改写为已测量。本次只修改本评估文档，未运行测试、外部 LLM、模型或报告／PDF 生成，未写数据库、执行迁移、提交或推送。定稿不选定合并骨架，也不批准、排期或实施合并。
