# 预测模型重构阶段五：本机隔离工程演示发布与持续评价设计

日期：2026-09-20；执行更新：2026-09-21。版本：0.6。状态：**书面规格已获用户批准；[实施计划](../plans/2026-09-20-prediction-model-refactor-phase-5-local-demo-release.md)的 S1–S5 已全部完成，实施5／5。**隔离数据库集成在本机准备的空库上实跑通过，实际演示会话已验证 `running → stopped` 与完整回退；事实与限制见[阶段五验收记录](../notes/2026-09-20-prediction-model-refactor-phase-5-local-demo-release-result.md)。本阶段仍只发布本机合成工程演示，未授权生产或临床使用。

S4 落地时对第 9 节「持续评价范围」的三点说明：

1. **「非所有者 404／错误角色 403／幂等重放」三类结果由演示会话自己发起的固定检查记录**（同源请求 + 三个种子身份），记录缺失时评价报告为 0 而不是推定通过。
2. **「疾病权限拒绝」在首版固定为 0**——冻结来源的两个病种均处于 `operator_enabled`，要产生真实拒绝必须在演示进行中临时停用某个病种，这会改写本次演示的业务行并让操作者在该窗口内无法为该病种生成报告。首版不这样做，该计数如实保留为 0 并在发布记录中可复核。
3. **`admission` 块只描述会话自己发起的固定检查**（固定为 2 次请求：1 次受理 + 1 次幂等重放），操作者在页面里生成的报告不进入该块，而由 `jobs` 块按数据库事实统计。两块的读数因此天然不同，阅读发布记录时以 `jobs` 为准判断本次实际完成了多少报告。

S4 另确定一条第 10 节未覆盖的错误语义：**评价发现的完整性矛盾不得以 `stopped` 掩盖**。归档原件字节与记录摘要不符、已保存上下文／输入／证据／文档摘要无法复算、在途任务未收敛或六类身份任一不匹配时，最终状态写 `failed` 并给出对应闭合码（`demo_archive_integrity_failed`／`demo_history_integrity_failed`／`demo_jobs_unsettled`／`demo_identity_drift`），评价块同时保留在记录中供复核。ready 归档的 `renderer_sha256` 必须等于冻结 renderer 身份，否则 `demo_renderer_identity_mismatch`。

依据：[预测模型重构总领文档](2026-09-09-prediction-model-refactor-master-design.md)、[阶段四设计](2026-09-16-prediction-model-refactor-phase-4-history-integration-design.md)、[阶段四实施计划](../plans/2026-09-16-prediction-model-refactor-phase-4-history-integration.md)、[阶段四总验收记录](../notes/2026-09-16-numeric-history-integration-result.md)及[报告发布与恢复运维文档](../../OPERATOR_REPORT_OPERATIONS.md)。阶段四合成工程已完成 S1–S6；当前工作区尚未把 C 包写入持久活动配置，真实临床有效性仍未验证。

## 1. 决策、目标与发布边界

阶段五首版采用**本机隔离工程演示发布**。目标是把阶段四已验收的 C 包以可重复、可审计、可停止的本机演示会话运行起来，证明发布前检查、活动配置注入、实际使用、停止回退和工程评价能够闭环。

本阶段不是生产部署，也不是临床发布：

- 只在本机运行，只监听 loopback 地址，只连接明确命名的隔离测试库 `surgery_rag_phase4_test`。
- 只使用冻结合成来源和明确标记为 `source_kind=synthetic` 的病例，只向本机会话中的 AI 操作者开放。
- 固定 `clinical_validity_claim=false`、`clinical_status=not_assessable`、`production_enabled=false`；页面、PDF、发布记录和评价摘要不得改写这些状态。
- 不修改业务 `.env`、系统服务、业务数据库、默认配置值或持久活动指针；活动配置只存在于监督进程及其子进程环境中。
- 不下载数据或模型，不重新训练，不重新索引，不修改阈值，不把合成结果转成临床准入结论。
- 真实资料到位后仍须独立完成审核、同契约适配、重新训练与评价、版本绑定及正式发布审批；本阶段不预写真实临床通过状态。

阶段五首版不新增用户模型选择、病种、时距、报告字段、页面样式或外部访问入口。既有受理、权限、幂等、取消、超时、租约、RAG、DeepSeek、历史读取及 PDF 原件语义保持不变。

## 2. 方案比较与选择

| 方案 | 优点 | 限制 | 决定 |
| --- | --- | --- | --- |
| 每次直接运行阶段四验收 runner | 无新增发布代码 | 验收完成即退出，自动生成固定五份报告；不能表达可交互的演示会话、停止和会话评价 | 不采用为发布入口，继续保留为验收入口 |
| 专用本机监督式演示入口 | 复用现有链路；活动配置仅对子进程有效；默认只读预检；可形成发布、停止和评价记录 | 需要新增小型运维 CLI 与测试 | **采用** |
| 修改持久配置或按生产方式部署 | 更接近正式上线 | 需要目标主机容量、备份恢复、访问边界、真实资料和临床准入；超出当前授权 | 不采用 |

专用入口不得复制预测、报告或归档业务逻辑。它只负责身份验证、隔离边界、进程环境、生命周期和评价汇总；实际业务继续调用现有 FastAPI、前端、报告 worker、PDF worker 和既有服务模块。

## 3. 冻结输入与权威身份

首版演示只接受下列输入：

| 身份 | 固定值 |
| --- | --- |
| 合成来源目录 | `outputs/synthetic-prediction-cases/2026-09-15-switch-v2` |
| 来源 manifest 原字节 SHA-256 | `3b333b090186e6c09fe938106bf2a176328e1d591b1bf6d56cf5ecbd7cd38296` |
| 旧 B 包 | `outputs/numeric-acceptance/2026-09-15/model-v2/bundle.json` |
| B canonical SHA-256 | `32b8069f92dab3e104f3668c3639cdc6e5461f5bedf61a4f7590ce2cef478215` |
| 活动 C 包 | `outputs/numeric-history-integration/2026-09-16-v1/bundle.json` |
| C canonical SHA-256 | `a6816ed1a30d9a65ae089f67746e98473f0514732883d98a2843d3bc90db2464` |
| renderer manifest | `outputs/numeric-history-renderers/2026-09-20-v1/38f18749e2ceed29eb12273c66f2a056e701f01db01b3ada7a5582e433357558/manifest.json` |
| renderer manifest 原字节 SHA-256 | `38f18749e2ceed29eb12273c66f2a056e701f01db01b3ada7a5582e433357558` |
| 当前权威端到端验收 | `outputs/numeric-history-acceptance/2026-09-20-v2/result.json` |
| 验收结果原字节 SHA-256 | `3dd8473c6df25aeb84c7e5c2782caef6e420e60227578062108a9edf30332c37` |
| 数据库 | 本机 PostgreSQL `surgery_rag_phase4_test`，Alembic `0031` |

发布前须用既有 canonical 规则重新加载 B／C 包并执行 runtime 核验，不能用文件字节哈希代替模型语义摘要。权威验收必须为 `status=passed`，绑定同一来源、B／C 包和 renderer，且记录 `planned_reports=5`、`worker_invocations=5`、`completed_reports=5`、`audited_invocations=5`、`page_errors=[]`。身份不一致时失败关闭，不搜索“最近目录”或自动选择另一制品。

`outputs/` 仍被 Git 忽略。用户已明确接受本机制品丢失后无法复现既有验收的风险；本阶段不新增外部备份策略。缺少任何冻结输入时，演示发布不可用，不能通过重建近似制品或修改登记哈希放行。

## 4. 组件与文件边界

阶段五新增以下运维边界；准确文件清单和测试步骤在实施计划中展开：

1. **发布记录 schema。** 严格描述 `numeric_history_demo_release.v1`，字段闭合，保存发布身份、状态、时间、工程计数和限制，不接受密钥、连接串、自由异常正文或病例内容。
2. **纯预检与评价模块。** 复用阶段四 runner 的冻结身份验证和安全 URL 规则，增加权威验收绑定、Git 提交身份、会话状态及工程评价汇总。纯函数不连接数据库、不启动进程、不写文件。
3. **监督式 CLI。** 新入口 `scripts/run_numeric_history_demo_release.py`；默认只执行静态预检，`--apply --allow-external-llm` 才允许连接隔离库、建立演示数据和启动子进程。
4. **本机浏览器会话。** 使用受控 Chromium 打开本机 AI 操作者页面，认证令牌只保存在进程／浏览器上下文内，不写入发布记录。浏览器保持可交互，直到操作者结束会话或监督进程收到终止信号。
5. **测试。** CLI／纯模块测试位于 `scripts/tests/`；需要数据库、worker、浏览器和归档的行为使用明确的隔离验收，不以 mock 代替最终链路。

不修改前端业务组件、API 数据契约、数据库 schema 或模型包。若实施时发现必须修改这些边界，先修订本设计并重新审核，不能把范围扩张藏在发布脚本中。

## 5. 命令与默认安全语义

入口采用一个监督式命令，参数必须显式给出冻结目录和全新输出目录：

```powershell
.\backend\.venv\Scripts\python.exe scripts/run_numeric_history_demo_release.py `
  --source-dir outputs/synthetic-prediction-cases/2026-09-15-switch-v2 `
  --legacy-bundle outputs/numeric-acceptance/2026-09-15/model-v2/bundle.json `
  --history-bundle outputs/numeric-history-integration/2026-09-16-v1/bundle.json `
  --renderer outputs/numeric-history-renderers/2026-09-20-v1/38f18749e2ceed29eb12273c66f2a056e701f01db01b3ada7a5582e433357558/manifest.json `
  --acceptance-result outputs/numeric-history-acceptance/2026-09-20-v2/result.json `
  --output outputs/numeric-history-demo-release/2026-09-20-v1
```

默认模式必须满足：

- 不连接数据库，不启动 API／前端／worker／浏览器，不创建目录，不写 Python bytecode。
- 只验证参数、路径、文件身份、运行时、Git 状态、端口和输出目录不存在，输出不含绝对私有路径或环境变量值。
- `TEST_DATABASE_URL` 必填但只解析，不回退 `DATABASE_URL`。拒绝 URL query／fragment、非 loopback 主机、非 `surgery_rag_phase4_test` 数据库，以及非空 `PGHOSTADDR`、`PGSERVICE`、`PGSERVICEFILE`、`PGOPTIONS`。
- 有 `--apply` 而无 `--allow-external-llm` 时失败；单独提供 `--allow-external-llm` 不产生副作用。

实际启动必须同时追加：

```powershell
--apply --allow-external-llm
```

`--apply` 不授权操作业务数据库、修改 `.env`、启动系统服务、执行部署、清理旧输出或推送代码。

## 6. 发布门禁与启动顺序

### 6.1 静态预检

静态预检依次完成：

1. 参数无重复、无缩写、无未知项；所有输入为普通文件／目录，不接受 symlink 绕过。
2. 来源逐文件长度和摘要、B／C canonical 摘要及 runtime、renderer 的源码／模板／字体／Chromium身份全部匹配第 3 节。
3. 权威验收结果原字节摘要及关键结论匹配当前冻结身份。
4. 当前 Git HEAD 可解析且工作区无代码改动。允许本设计、阶段五计划及阶段五发布记录文档存在明确列出的文档改动；应用、脚本或测试改动未提交时拒绝实际发布。
5. API、前端和 worker 使用的固定本机端口均空闲；输出目录不存在。

### 6.2 实际启动前重检

创建任何输出或连接数据库前重新执行静态预检，防止预检后输入变化。之后：

1. 连接 `TEST_DATABASE_URL`，立即核对实际主机／数据库身份；事务只读检查 Alembic head 为 `0031`。
2. 要求 `users`、`operator_cases`、`ai_reports` 为空；首版不提供复用、恢复或清理非空数据库的快捷路径。
3. 新建唯一输出目录，先原子写入 `release.json`，状态为 `starting`，记录冻结身份、代码提交及运行时，不记录连接信息。
4. 仅在该隔离库中创建本地演示操作者、疾病和冻结合成病例。全部种子写入须在事务中完成，失败整体回滚。
5. 使用子进程专属环境启动服务。核心值固定为：
   - `DATABASE_URL`、`VECTOR_STORE_CONNECTION_STRING` 指向已核验的隔离库；
   - `NUMERIC_MODEL_BUNDLE` 直接指向 C 包；
   - `NUMERIC_REPORTS_ENABLED=true`；
   - `REPORT_JOBS_ENABLED=true`、`REPORT_JOBS_ACCEPTING=true`；
   - `REPORT_PDF_ENABLED=true`、`REPORT_PDF_ACCEPTING=true`；
   - `REPORT_PDF_RENDERER_MANIFEST` 指向固定 renderer；
   - `REPORT_ARCHIVE_ROOT` 位于本次输出目录；
   - Hugging Face／Transformers／ModelScope 保持离线，DeepSeek 只使用调用者已提供的环境配置。
6. API、前端、报告 worker 和 PDF worker 全部通过就绪检查后，打开已认证的本机浏览器页面，将发布状态原子更新为 `running`。任一进程未就绪时不展示可用状态。

本入口不执行 Alembic upgrade、不创建或删除数据库、不 TRUNCATE 表。隔离库须由操作者按现有开发流程预先创建并迁移；非空或版本错误时报告明确门禁失败。

## 7. 会话、停止与回退

演示会话由监督进程持有；首版不把它安装为后台服务。正常停止为 Ctrl+C 或等价终止信号：

1. 先停止接受新报告请求。
2. 等待已领取任务在既有取消、阶段超时、总时限和租约语义内收敛；不强行改写任务终态。
3. 关闭浏览器、前端、API、报告 worker 和 PDF worker；子进程 teardown 错误不能覆盖原始失败，但要以错误类型和阶段写入记录。
4. 释放端口并恢复父进程原环境；不得把演示环境写回 `.env`。
5. 只读汇总数据库审计与输出原件，将 `release.json` 原子更新为 `stopped` 或 `failed`。

停止监督进程即完成活动配置回退：新进程不再接受 C 包报告。回退不删除演示病例、报告、审计、PDF 或失败诊断；再次运行必须使用新的空隔离库状态和新的输出目录。B 包不是自动备用模型，不能在 C 包失败时静默切到 B。历史报告继续按保存的上下文、模型身份和归档原件读取，不调用当前模型补算。

若监督进程被强制终止而来不及完成最终记录，已有 `starting`／`running` 记录不得被解释为成功。后续只读检查可标记为“未确认停止”，但不能伪造 `stopped`；首版不实现自动接管或后台恢复。

## 8. 发布记录与数据最小化

每次运行目录只保存演示所需及验收证据：

- `release.json`：schema、状态、run_id、开始／停止时间、Git提交、冻结身份、运行时、限制及工程汇总。
- `archive/`：本会话发布的 PDF 原件，继续按现有原件语义管理。
- 安全日志和失败诊断：阶段、错误类型、代码位置、页面错误类型、截图及截断页面文字；URL 必须脱敏。

禁止写入：

- 数据库 URL、密钥、令牌、密码、请求头或完整环境变量。
- 原始患者资料；本阶段只有冻结合成主体，记录仍只使用匿名主体身份。
- SQL／HTTP／LLM 原始异常正文，因为其中可能包含连接信息或服务响应。
- LLM 完整请求／响应正文；既有数据库审计按原规则保存调用事实。

输出目录必须是全新目录；失败产物原样保留，重试使用新 run_id，不覆盖或原地改写失败记录。

## 9. 持续评价范围

会话结束时生成的工程评价至少包含：

| 类别 | 指标 |
| --- | --- |
| 接单 | 请求数、幂等重放数、拒绝数及闭合原因码 |
| 任务 | queued／running／completed／failed／cancelled 数量，未收敛任务数量 |
| 时限 | load／prediction／evidence／render／persist 阶段耗时，`phase_timeout` 次数与阶段 |
| LLM审计 | `invocation_started`、`task_finished` 数量及逐报告是否闭合，不保存正文 |
| 权限 | 非所有者、错误角色及疾病权限拒绝结果 |
| 历史 | 保存上下文、来源、模型和文档身份可读；不加载当前模型重算 |
| PDF | published 原件数、下载次数、原件与下载字节 SHA-256 一致性、损坏／缺失状态 |
| 身份 | 实际来源、B／C包、renderer、代码提交与运行时 |

工程评价不得包含“临床通过”“模型优于基线”“真实患者泛化”或相似结论。没有真实结局时不计算临床准确率、MAE准入、校准、获益或患者亚组表现。收集到后续真实结局也只形成待审核输入，不自动触发训练、阈值变化、模型替换或发布。

阶段五完成记录须把三类结论分开：发布控制是否正确、演示链路是否可运行、临床有效性是否可评价。前两项可在本阶段通过；第三项固定为 `not_assessable`。

## 10. 错误语义

| 失败位置 | 行为 | 允许的外部结果 |
| --- | --- | --- |
| 参数、冻结身份、Git、端口、输出目录 | 预检退出，不创建目录、不连接数据库 | 闭合错误码 |
| 数据库目标、迁移或非空检查 | 连接后立即退出，不写数据库 | `isolated_test_database_required`、`phase4_migration_required`或`clean_test_database_required` |
| 种子事务 | 整体回滚，不启动服务 | 阶段与错误类型 |
| 服务就绪 | 关闭已启动子进程，保留失败记录 | `failed`，不显示为运行中 |
| 会话内报告失败 | 沿用既有持久任务状态和诊断；其他任务不自动重试 | 实际失败／取消／超时代码 |
| teardown／汇总 | 尽力关闭所有拥有的进程；记录 cleanup_errors | 不覆盖更早的主失败 |
| 发布记录写入失败 | 立即停止会话，不继续开放入口 | 固定安全错误码 |

未知异常对控制台和记录只投影类型、阶段及代码位置。任何“为了让演示成功”而放宽数据库、身份、权限、输入、任务时限、报告完整性或 PDF 校验的修改均不允许。

## 11. 验收策略

### 11.1 纯单元与 CLI 契约

至少验证：

- 默认预检不连接数据库、不创建目录、不启动进程、不调用外部 LLM。
- 必填参数、重复参数、参数缩写、symlink、输出已存在、端口占用全部失败关闭。
- 数据库名、主机和 libpq 重定向边界与阶段四一致。
- 来源、B／C 包、renderer、权威验收、Git提交任一漂移均拒绝。
- `--apply` 缺少外部 LLM 授权、单独授权、未知参数均有确定结果。
- 发布记录拒绝密钥／URL／病例正文，状态转换只允许 `starting -> running -> stopped|failed` 或 `starting -> failed`。
- teardown 错误不顶替主失败，环境在成功和异常路径均恢复。
- 工程评价按真实记录统计，不把报告 completed 推导成每项预测 available。

### 11.2 隔离集成

使用明确的本机 `_test` 数据库验证：

- 空库、0031、事务种子及失败回滚。
- C 包从接单时固定到任务上下文，运行中改变父进程环境不影响已受理任务。
- 关闭受理后在途任务按取消／超时／租约规则收敛。
- 非所有者 404、错误角色 403、幂等重放、保存历史和 PDF 原件字节保持。
- 监督进程退出后端口释放，父环境和默认配置未改变。

### 11.3 实际演示验收

在全新输出目录执行一次获准的 `--apply --allow-external-llm` 会话：

1. 发布状态进入 `running`，本地浏览器可查看三个冻结合成场景。
2. 至少实际完成 C 包两病种及历史不足场景，覆盖取消、权限、幂等和 PDF 下载；B 包兼容继续由冻结的阶段四验收结果守护，不在 C 包演示会话中临时切换活动包。
3. 停止后状态为 `stopped`，服务和端口关闭，历史事实及 PDF 可按保存身份核对。
4. 工程评价分母与数据库／文件事实一致，临床状态仍为不可评价。

实际验收不能复用阶段四 `2026-09-20-v2` 冒充阶段五运行；后者只作为发布前身份门禁。

### 11.4 回归与阶段出口

- 后端相关单元测试及 CLI 测试。
- 适用的隔离数据库、worker、归档和权限集成测试。
- 前端行为未改时复用现有测试记录；实际演示仍检查加载、空、失败、取消、历史和 PDF 页面。
- 从 `backend` 运行整仓非 integration／e2e 回归并要求 0 failed。
- 运行 `git diff --check`；文档链接、命令、冻结身份与实际产物一致。

## 12. 完成条件与后续真实资料交接

阶段五本机演示范围仅在以下条件同时满足时完成：

1. 默认 dry-run、实际启动、会话运行、正常停止、失败清理和回退均有可复核记录。
2. 当前 C 包、renderer、合成来源和代码提交身份一致，没有持久配置漂移。
3. 实际 API／worker／RAG／DeepSeek／浏览器／PDF 链路通过，权限、幂等、取消、历史和归档语义保持。
4. 工程评价可复算，失败和跳过如实保留；整仓非集成回归全绿。
5. 文档明确发布仅限本机合成演示，未授权生产或临床使用。

阶段五完成不关闭真实资料路线。真实资料到位后的工作至少包括：确认主体与时间线、冻结任务和标签、建立正式样本与独立分区、重新训练和比较、专业复核临床阈值、生成新的模型／来源／评价版本、重做阶段四接入验收，并为目标部署环境单独审批发布、容量、备份和回退。旧合成 C 包及其历史报告保持原身份，不升级为真实模型。

## 13. 实施顺序建议

实施计划应按以下可独立复审的交付拆分：

1. 严格发布记录、冻结身份和默认只读预检。
2. 隔离数据库重检、事务种子和监督式进程生命周期。
3. 本机已认证浏览器会话、停止受理与回退。
4. 工程评价、失败诊断和发布记录闭合。
5. 隔离集成、实际演示总验收、运维文档与阶段完成记录。

每步完成后记录实际改动、测试、失败／跳过、限制、剩余步骤和下一步。写实施计划不授权执行 `--apply`、调用外部 LLM、操作隔离数据库、启用演示会话、提交或推送；这些动作在对应实施步骤开始时按用户授权范围执行。
