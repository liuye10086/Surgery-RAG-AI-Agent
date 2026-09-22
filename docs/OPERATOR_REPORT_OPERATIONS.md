# 完整预测报告发布与恢复

本项迁移为 0023（结构化报告）和 0024（持久任务），必须沿当前 Alembic 迁移链升级。HTTP 受理只保存快照和任务，独立 worker 使用固定版本生成；页面刷新、断线和返回病例不会取消任务。服务重启后查询数据库状态，失去租约的执行只收敛为失败，不自动重算。

## 配置与容量

### 统一数值预测主流程（0029，2026-09-14）

新请求使用 `report_kind=numeric_prediction`，readiness 查询使用同名参数，仅接受空 `model_options`。`NUMERIC_REPORTS_ENABLED=False` 默认关闭新接单；还需现有 `REPORT_JOBS_ENABLED`、`REPORT_JOBS_ACCEPTING` 开启。关闭新开关不取消已受理任务，不影响历史或已发布 PDF 下载。未配置 `NUMERIC_MODEL_BUNDLE` 时保留 `last_value` 基线；配置固定模型包后的完整流程见下一节。`clinical_validity_claim=False` 不表示临床效果通过。

迁移 0029 增加服务端 `OperatorCase.prediction_source` 和 v4 发布约束。新来源绑定不与 `engineering_source` 同时保存；有新绑定或 v4 报告时 downgrade 拒绝丢弃事实。普通 HTTP 病例写入不能设置来源，已绑定输入只读。旧绑定先按原合同验证，再在内存转换为新数值输入，不覆写旧记录。页面只接收服务端生成的 `prediction` 能力摘要，不接收来源绑定原文。

受控导入使用显式版本包目录和操作者 ID；来源真实性来自服务端管理的包与操作权限，SHA 只证明完整性。包内仅需 `manifest.json` 和 `records.jsonl`，不读取随访结果文件：

- manifest：`schema_version=prediction_case_package.v1`，`source` 包含 `source_kind`、严格布尔 `is_synthetic`、`dataset_id`、`dataset_version`、`run_id`、`generator_version`；真实来源的 generator 为 null，合成来源必须为非空版本。还需 `records={bytes,sha256}`、正整数 `record_count`、严格 `clinical_validity_claim=false`。
- records：每行包含 `age`、`sex`、`baseline_stage` 和 `numeric_input`。输入沿用双时距任务契约，但不填写顶层 source，由 loader 根据 manifest 注入来源和两文件摘要；各 packet 的 source 必须与 manifest 一致。未知来源、重复主体／sample、错误单位、未来观测和文件摘要不符均拒绝。

从仓库根目录执行以下默认 dry-run，不连接数据库；必须显式设置 `TEST_DATABASE_URL`，不加载 `.env`，不回退业务 `DATABASE_URL`。仅允许本机 PostgreSQL `_test` 数据库，拒绝 URL 查询参数及 `PGHOSTADDR`／`PGSERVICE` 重定向。确认隔离目标已迁移后，显式加 `--apply` 才建立病例、访视、绑定和审计；整个包处于一个事务，同一操作者的相同 dataset_id／dataset_version 重复导入拒绝，中途失败全部回滚。

```powershell
backend/.venv/Scripts/python.exe scripts/import_prediction_cases.py --package-dir <version-package-directory> --user-id <operator-id>
```

新快照、上下文和文档分别使用 `numeric_report_input.v1`、`numeric_generation_context.v1`、`numeric_report_document.v1`，算法固定 `numeric.last_value.v1`，发布指纹 v4。来源摘要、输入摘要和算法身份进入保存事实。旧临床 v1/v2、合成数值 v3 仍按保存版本读取，不调用当前算法重算。新数值报告复用 `report_pdf.html`；更新渲染源码后按下文重建独立 renderer 制品，已发布原件继续交付原字节，缺失或损坏只按原件恢复流程处理。

本阶段真实来源合同只用明确虚构 fixture 验证；实际真实病例导入和临床性能尚未验证。下方 B/C/D 内容为前序记录，其专用页面与模板方向由本节统一方向取代，冻结数据、源码与旧 PDF 仍保留。

### 训练模型、检索与说明生成（0030，2026-09-14）

新请求仍使用同一个 `numeric_prediction` 入口。将 `NUMERIC_MODEL_BUNDLE` 指向已验证、不可变的 `bundle.json` 文件后，接单固定四任务 Ridge 参数、实现摘要、参考候选、检索配置、提示词全文及摘要、说明模型名称。使用 `numeric_generation_context.v2`、`numeric_prediction.v2`、`numeric_report_document.v2` 和发布指纹 v5；输入仍为 `numeric_input.v1`。0030 升级仅增加兼容约束；已有 v5 报告或 v2 排队／终止上下文时拒绝降级。

API 与 worker 必须使用相同模型制品和兼容实现。模型包不能是 pickle；加载验证严格 JSON、四任务参数、单位、来源及训练／挑战分离。接单前和最终事务内重新捕获模型与参考身份；worker 使用已保存参数，不训练，也不加载当前指针替代已受理版本。提示词或检索配置在排队期间变化会失败，不静默换版本；已有幂等请求仍回到原报告。

参考检索复用本地 BGE-M3、PGVector、pg_trgm 与 RRF，只允许固定、当前、全局且 operator／both 范围内的参考片段，核对病种、锚点时已知信息及来源，排除同主体／依赖组。两分支均失败则任务失败；部分失败和空结果如实保存。当前参考语料是输入测量记录，不是临床指南或随访结局，报告明确未执行临床标准评价。

DeepSeek 只生成解释，数值表由固定计算结果产生；调用失败、非法引用、禁止的数字或不一致算法说明会拒绝发布，不用模板冒充 LLM 成功。保存请求模型名及服务实际响应模型名，两者可能因服务端别名映射不同。生成时执行内容过滤；历史只验证保存的输入、提示词身份、响应原文及引用，不调用当前模型、检索、LLM 或当前内容过滤配置。

前端与 PDF 继续共用原有入口和 `report_pdf.html`，显示模型结果、末次值基线、保存说明和引用；来源属性仅保存在后端。训练数值报告（numeric_report_document.v2）的页面及新版 PDF 将预测值与比较基线统一显示为两位小数，并注明展示值已四舍五入；后台保留完整浮点值，历史实测记录不改变展示精度。旧版未训练数值报告继续保留原有展示规则。准备 PDF 必须通过保存事实完整性验证；下载仍只交付归档原件。

2026-09-15 展示调整只在已验证的打印 HTML 与前端展示层应用，不修改用于完整性校验的 canonical 正文生成规则。数值报告的模型版本信息集中末尾，PDF 参考附录按记录块控制分页并保留全部引用。更新 pdf_generator.py 或 report_pdf.html 后必须构建新的 renderer manifest，API 与 PDF worker 使用一致的新资源；既有归档仍交付原 PDF 字节，不因新模板重渲染替换。

本机参考种子命令默认只读校验；`--apply` 仅接受显式 `TEST_DATABASE_URL` 指向本机 `_test` 库，不回退业务连接：

```powershell
backend/.venv/Scripts/python.exe scripts/seed_numeric_reference_corpus.py --source-dir outputs/synthetic-prediction-cases/2026-09-14-v1 --limit-per-disease 8
```

本轮训练过程、旧来源源码摘要的隔离复现、实际外部调用和检查结果见[完整能力验收记录](superpowers/notes/2026-09-14-numeric-full-capability-result.md)。本机验收不授权业务库迁移、部署或模型发布；默认开关和 `.env` 不变。训练模型未优于基线，不将本轮合成数据结果解释为真实临床效果。

### 统一隔离总验收与版本切换（2026-09-15）

`scripts/run_numeric_report_acceptance.py` 是持久验收入口。默认只读核对两份合成来源包、对应已训练模型、renderer、输出路径与端口；实际运行须同时显式指定 `--apply --allow-external-llm`。仅允许 `TEST_DATABASE_URL` 指向本机 `_test` 库，SQL 与向量连接均覆盖为该隔离目标；库需已迁移至当前 head，用户、病例和报告为空，允许已有受控参考索引。脚本不清空既有业务数据。

准备两个独立合成数据/计算/训练制品目录；复用 `build_synthetic_prediction_cases.py`、`evaluate_synthetic_prediction_cases.py`、`build_numeric_model_bundle.py`，生成后不可修改源包或模型。按上文索引合成开发池输入参考，构建匹配当前代码的 renderer。固定源码校验如不匹配须使用对应保存源码或新建版本，不能改旧manifest以绕过检查。

从项目根目录使用以下入口（尖括号参数替换为已验证的本地路径；输出目录必须尚不存在）：

```powershell
backend/.venv/Scripts/python.exe scripts/run_numeric_report_acceptance.py --source-a <source-a-dir> --source-b <source-b-dir> --model-a <model-a-bundle.json> --model-b <model-b-bundle.json> --renderer <renderer-manifest.json> --output <fresh-output-dir>
```

确认是获准的隔离环境后，在同一命令追加 `--apply --allow-external-llm`。验收包含两病种两模型版本的实际 API、worker CLI、RAG/DeepSeek、浏览器、历史及 PDF；B 数据通过当前版本包导入契约接入。切换 `NUMERIC_MODEL_BUNDLE` 只影响随后新接单，已排队任务保存原包；提示词、检索配置或实现不兼容仍按既有门控失败。幂等重放返回原报告，既有报告及 PDF 保存原版本和原字节。

结果、日志、页面与 PDF 写入本次新输出目录；异常退出非零并清理该次拥有的进程树，数据库由调用者单独停止。不得将合成版本切换验收解释为任意真实文件可以直接替换，亦不自动授权业务模型发布。真实资料须先完成同契约映射、事实审核、适用训练/评价，再配置通过验收的新版本。

### 历史候选接入（0031，2026-09-18）

将 `NUMERIC_MODEL_BUNDLE` 指向严格混合包 `numeric_model_bundle.v2` 后，受理使用 `numeric_generation_context.v3`、预测 `numeric_prediction.v3`、文档 `numeric_report_document.v3` 与发布指纹 **v6**；输入仍为 `numeric_input.v1`。混合包内嵌完整旧 `numeric_model_bundle.v1`（按旧 canonical 摘要核验），另有唯一 RF 模型与固定四项 `task_assignments`：`ad.mmse.12m` 使用 `random_forest:history_v1:value_history`，其余任务继承旧 Ridge。未配置模型包时保持 `numeric_generation_context.v1`；配置旧 v1 包时保持 v2 上下文。**非空但未知的版本一律失败，不按字段猜测算法。**

候选与末次值基线**独立记录状态**：某任务可以是 `available`／`abstain`／`error`，同时两条基线正常可用。历史不足不回填基线、有限越界不裁剪（raw 值仅留在审计中）、制品损坏整体验证失败。**报告完成不代表所有预测可用**；AD 无历史时 12 个月弃权、6 个月与两条基线仍可用，页面与 PDF 均显示原因并披露模型未执行。`source_kind=synthetic`、`clinical_validity_claim=false`、`clinical_status=not_assessable`；新包只接受合成输入。

迁移 0031 保留旧 v5 约束并扩展允许 v6，新增 v6／document.v3 完整发布约束（条件用 `IS TRUE` 避免 NULL 穿透）。downgrade 在任何 DDL 之前检查 v6 报告、v3 文档与任意状态的 v3 任务上下文，存在即拒绝。API 与 worker 必须使用同一混合包；worker 使用受理时保存的包与参数，当前选择包变化不影响已排队任务，保存参数／对应 prompt／runtime／检索配置漂移则失败。abstain／error 在审计中映射为既有 `unavailable` 并保留 reason。

`scripts/run_numeric_history_acceptance.py` 是阶段四验收专用入口（与 2026-09-15 的通用入口并列，互不改动对方约束）。默认只读预检；真实执行需同时 `--apply --allow-external-llm`，且输出目录必须尚不存在：

```powershell
.\backend\.venv\Scripts\python.exe scripts/run_numeric_history_acceptance.py --source-dir <source-dir> --legacy-bundle <v1-bundle.json> --history-bundle <v2-bundle.json> --renderer $env:REPORT_TEST_RENDERER_MANIFEST --output <fresh-output-dir> --apply --allow-external-llm
```

专用库必须精确为 `surgery_rag_test`，拒绝 URL 查询参数／fragment 与 `PGHOSTADDR`／`PGSERVICE`／`PGSERVICEFILE`／`PGOPTIONS` 重定向；`users`／`operator_cases`／`ai_reports` 必须为空，允许已有受控参考索引。失败时结果目录写入截图、页面 body、page error 类型与**已脱敏 URL**（不含连接串与密钥），并保留 `browser-failure.json`；新失败一律使用新输出目录，不覆盖、不原地修复既有报告。更新 `pdf_generator.py` 或 `report_pdf.html` 后必须重建 renderer manifest；既有归档继续交付原字节。

2026-09-18 实际验收：5 份报告（含 B 排队后切 C 完成 v5、C 两病种、C AD 部分结果、真实排队取消）退出 0，5 次真实说明生成，5 份归档原件与下载字节一致，非所有者 404／doctor 403／幂等重放均通过。详见[阶段四实施与总验收记录](superpowers/notes/2026-09-16-numeric-history-integration-result.md)。该结果只证明合成工程链路，不构成临床有效性。

### 合成路线产物与验收入口对照（2026-09-20）

本项目曾并行推进三条合成路线，产物目录**共用 `2026-09-15` 日期前缀**且各有独立验收入口。**当前活动配置不指向其中任何一个**（`NUMERIC_MODEL_BUNDLE` 为空、各报告开关默认关闭）。下表用于区分用途与权威性，避免按日期误判新旧或误用不可加载的制品：

| 路线 | 产物 | 协议 / 版本 | 验收入口 | 可加载制品 | 权威性 |
| --- | --- | --- | --- | --- | --- |
| 统合路线（阶段二合成工程） | 来源 `outputs/synthetic-prediction-cases/2026-09-15-switch-v2`；模型 A `outputs/numeric-fullflow/2026-09-14/model-v1`、B `outputs/numeric-acceptance/2026-09-15/model-v2` | `synthetic_prediction_candidates.v1`；报告 v1–v5 | `scripts/run_numeric_report_acceptance.py`（+ `numeric_report_acceptance_browser.py`） | **有**（A、B 两个 `bundle.json`） | B 为**旧包基线**，被阶段四冻结并引用 |
| 阶段三合成离线比较 | `outputs/synthetic-prediction-history/2026-09-15-v1` | `synthetic_prediction_history.v1` | `scripts/run_synthetic_prediction_history.py` | **无**——内存拟合，**禁止**当作可加载制品 | 仅离线比较证据，**不得用于接入** |
| 阶段四合成候选接入 | `outputs/numeric-history-integration/2026-09-16-v1` | `numeric_model_bundle.v2`；上下文 v3／预测 v3／文档 v3／指纹 v6 | `scripts/run_numeric_history_acceptance.py`（+ `numeric_history_acceptance_browser.py`） | **有**（混合包 C，内嵌 B） | **阶段四权威验收输入**；未启用 |

**两点易错处：**

- 阶段三包与阶段四包**不是同一制品**。阶段四的混合包 C 按 S2 的固定选择规则**重新拟合**产出，与阶段三的内存模型**无继承关系**；阶段三明确禁止把其 RF 结果包当作可加载制品。
- `2026-09-15` 同时出现在三条路线的目录名中（其中阶段三实际执行于 2026-09-16），**一律按目录全路径区分，不要按日期判断新旧**。

### 合成数值报告B包（2026-09-14）

迁移0027新增`OperatorCase.engineering_source`，保留旧病例为空；已有来源数据时downgrade拒绝删除该列。B包完成隔离来源导入与接单，`SYNTHETIC_REPORTS_ENABLED=False`为默认值。B包时的worker排除限制已由下述C包解除；来源导入及客户端只读边界不变。

种子使用`scripts/seed_synthetic_numeric_cases.py`，必须明确`TEST_DATABASE_URL`，不回退业务`DATABASE_URL`。目标仅允许PostgreSQL本机地址、`_test`库名、无URL查询参数，且不得存在非空`PGHOSTADDR`或`PGSERVICE`。固定包根为`outputs/synthetic-prediction-cases`；普通客户端不得赋值来源绑定。以下命令从仓库根目录运行，替换占位主体及操作者，默认仅校验文件，不连接数据库；明确隔离目标已迁移后才用`--apply`执行原子导入。

```powershell
backend/.venv/Scripts/python.exe scripts/seed_synthetic_numeric_cases.py --package-dir outputs/synthetic-prediction-cases/2026-09-14-v1 --user-id <operator-id> --subject-id <synthetic-subject-id>
```

接单显式传`report_kind=synthetic_numeric`，仅接受空`model_options`；对应readiness使用同名查询参数。无类型请求维持旧临床语义，工程病例走旧入口会拒绝。详细证据见[本轮B包验收](superpowers/notes/2026-09-14-synthetic-report-admission-result.md)。本节不授权在业务库执行迁移或启用新报告。

### 合成数值报告C包（2026-09-14）

迁移0028支持独立v3发布指纹及工程专用`not_requested`证据状态；旧临床报告不能使用该状态绕过证据要求。有已发布v3事实时拒绝downgrade。现有报告worker已能领取合成任务，使用接单固定输入与算法身份生成；不需要训练模型或调用LLM。算法身份变化时旧排队任务明确失败，不换用新代码重算。

任务仍受原租约、并发、取消、阶段预算和sweep约束。`SYNTHETIC_REPORTS_ENABLED`只控制新接单，关闭后已受理任务仍可执行；停止所有worker则沿用既有全局开关与服务管理。历史读取只校验保存事实，不加载当前算法或来源文件；损坏按错误处理，不重新生成补齐。C包曾临时拒绝v3 PDF，该限制已由下述D包专用模板支持解除。

本轮仅在私有测试库迁移和验证，详见[C包结果](superpowers/notes/2026-09-14-synthetic-report-execution-result.md)。这不改变业务库迁移和正式部署的授权边界。

### 合成数值报告D包（2026-09-14）

操作者页面根据服务端验证的`engineering`摘要显示只读工程病例及类型化生成入口；功能关闭或来源无效时不回退旧临床入口。数值历史与失败／取消输入按保存版本展示，未知文档禁止导出。

完整性通过的v3报告可以沿用现有PDF准备与归档流程。新增`synthetic_numeric_report_pdf.html`及相关渲染源码已纳入manifest，部署兼容实现时须构建独立新renderer，不能修改旧manifest哈希来放行漂移。旧ready归档仍交付已发布原件；损坏时使用已有原件备份恢复，不重新渲染替代。新模板不代表正式部署获准。

两病种真实PDF worker、权限／字节校验／原件恢复与实际浏览器结果见[D包记录](superpowers/notes/2026-09-14-synthetic-report-ui-pdf-result.md)。本机专项验收通过，完整新旧隔离启动器扩展及总验收留给E包；生产容量和发布门禁不变。

### 既有报告配置

默认 `REPORT_JOBS_ENABLED=False`、`REPORT_JOBS_ACCEPTING=False`。启用 worker 需前者为 True；开放新受理还需后者为 True。关闭受理不影响历史读取、状态查询、取消和下载。

默认全局并发 1、队列上限 20、每用户活动任务 2、每病例活动任务 1；排队 600 秒、执行 300 秒、租约 45 秒、心跳 10 秒。各阶段预算见 `backend/.env.example`，阶段超时不能通过重复消息延长。新增部署不得提升并发绕过 4 GiB 主机资源基线。

systemd 模板位于 `deploy/systemd/`，沿用 `DEPLOY.md` 的 `surgery` 账户和 `/opt/surgery-rag/backend/venv`。安装前核对实际 User/Group、虚拟环境、目录和环境文件最小读取权限。模板中 worker 的 MemoryHigh 1536 MiB、MemoryMax 2048 MiB 是初始隔离预算，必须结合 PostgreSQL、Web、BGE 等其他服务的总 RSS 复核；本机 Windows 测试不能代替 Linux 4 GiB 主机容量验收。

worker 使用 `KillMode=control-group`，Windows CLI 使用 Job Object 的 KILL_ON_JOB_CLOSE。独立 sweep timer 每 15 秒执行一次，即使 worker 不可用也会收敛过期任务。监控必须单独检查 worker 服务状态，不能以无任务时没有心跳判断死亡。

执行期限按领取时数据库 run_deadline 的剩余预算计算；独立 watchdog 在数据库心跳回调阻塞时仍终止执行进程。worker 专用连接设置连接/语句 5 秒、锁等待 3 秒、池等待 5 秒及 TCP 存活检查；数据库不可达时不伪造终态，恢复后由独立 sweep 根据租约收敛。前端遵守 Retry-After，重连、窗口焦点恢复不能绕过限流等待。

## 发布顺序

1. 备份数据库和当前应用制品，关闭新报告入口，运行只读 preflight。旧版 generating 非零时门禁失败，先按下文处置。
2. 排空旧 SSE 请求并停止旧执行进程。维护人员明确旧报告 ID 范围后，条件更新无 job 的 generating 为 failed，error_stage/error_message 记为 worker_interrupted；记录 ID、数量和处置时间。不得自动重新生成。
3. 用部署环境的 Alembic 升级 head（0024），不允许 stamp 跳过迁移。运行既有正式标准来源、manifest 和参考窗口门禁。
4. 发布新后端/前端，保持 ACCEPTING=False，设置 ENABLED=True。启动 worker 和独立 sweep timer。
5. 在隔离环境完成真实数据库、双病种浏览器、PDF、强杀进程、超时、取消竞争验收；生产只执行获准的发布检查。
6. 确认 `systemctl is-active surgery-report-worker`，再运行 `python scripts/check_operator_report_generation_readonly.py --phase postflight --worker-ready`。该参数是监督检查的明确断言，不是自动推断。脚本显式 READ ONLY，输出计数和错误代码，不修改任务或打印数据库地址、原始输入。
7. postflight PASS 后开启 ACCEPTING=True 并重启读取配置的 HTTP 服务。旧 SSE 兼容开关初期保持开启；确认旧入口调用量为 0、前端更新完成后，关闭 `REPORT_LEGACY_SSE_ENABLED`，旧入口返回 410。

preflight 允许结构尚未迁移但仍输出 schema_ready=False；任何遗留任务、完整性错误均应先处置。postflight 要求完整结构、标准和参考版本可用、无过期任务或终态不一致、worker ready，且受理尚未开放。

## 故障处理与监测

- 监测 queued/running/expired、最长队龄、阶段耗时、失败原因、worker readiness 和整个服务组 RSS；日志只记 report_id、batch_id、阶段、安全原因代码与耗时。
- 断线只恢复观察；取消必须调用明确 cancel 接口。取消与完成竞争由数据库事务决定唯一终态。
- worker 失联后等待租约与独立 sweep 收敛；重启 worker 继续领取 queued，已失效的 running 不重算。
- 发布提交响应不确定时读取数据库事实，不覆盖 completed、不自动重试推理；幂等请求重试仍指向同一报告。
- 正在生成的报告禁止删除；终态删除保留幂等墓碑。重复原 key 返回资源已删除，需新 key 才能创建新报告。
- 哈希校验失败时屏蔽正文、图表与下载，不能用当前模型重新生成历史内容掩盖损坏。

Nginx 为 `/api/v1/operator/reports/<id>/events` 单独关闭代理 buffering，设置略高于 SSE 连接周期的 read timeout（例如 300s）；普通接口保持有界超时。不要给全部 HTTP 请求无限时限。

## 回滚

先关闭 ACCEPTING，取消或排空任务，再停 worker。保留新列、任务、报告和幂等记录。应用只能回滚到理解 v2 指纹与 report_document 的兼容版本；更早版本必须阻断新报告读取/下载并显示升级提示。禁止删除新列或批量把 completed 改成其他状态。0024 downgrade 遇到报告幂等记录会拒绝执行，防止静默丢失历史；生产应用回滚不执行破坏性 schema downgrade。

## 本机隔离验收

`scripts/run_operator_case_e2e.ps1` 接受显式的本机 `_test` 数据库；未传入时使用独立 Docker 测试库。流程为迁移、测试种子、启动真实 operator API/worker/Vite、两用户浏览器验收，并在 finally 停止本次启动的进程、恢复环境。测试 HTTP host 位于 tests/e2e，只省略无关聊天向量预热，不替换报告 API、推理、标准或持久化实现。

测试种子只使用已批准的两份标准 fixture 与 manifest，全部病例为软件验收虚构数据。不得指向生产数据库。


### 本机隔离工程演示发布（阶段五）

`scripts/run_numeric_history_demo_release.py` 是把阶段四已验收的 C 包放进一次**本机、合成、可停止**演示会话的入口。它不是部署入口，也不授权临床或生产使用。

**前置条件。** 需要一个本机可丢弃且为空的 `surgery_rag_test`，Alembic 必须为 `0031`，且 `users`／`operator_cases`／`ai_reports` 三张业务表为空；全新空库需先由管理员安装 `vector`／`uuid-ossp`／`pg_trgm` 扩展，再执行 `alembic upgrade head`。本脚本**不创建、不迁移、不清空**数据库，非空或版本不符时直接失败关闭。`TEST_DATABASE_URL` 必须显式给出，只接受 loopback 与该库名，拒绝 URL 查询参数／fragment 与非空的 `PGHOSTADDR`／`PGSERVICE`／`PGSERVICEFILE`／`PGOPTIONS`，不回退 `DATABASE_URL`。

**默认只读预检（dry-run）。** 不连库、不建目录、不启动进程／浏览器、不调用外部 LLM：

```powershell
.\backend\.venv\Scripts\python.exe scripts/run_numeric_history_demo_release.py `
  --source-dir outputs/synthetic-prediction-cases/2026-09-15-switch-v2 `
  --legacy-bundle outputs/numeric-acceptance/2026-09-15/model-v2/bundle.json `
  --history-bundle outputs/numeric-history-integration/2026-09-16-v1/bundle.json `
  --renderer outputs/numeric-history-renderers/2026-09-20-v1/38f18749e2ceed29eb12273c66f2a056e701f01db01b3ada7a5582e433357558/manifest.json `
  --acceptance-result outputs/numeric-history-acceptance/2026-09-20-v2/result.json `
  --output outputs/numeric-history-demo-release/2026-09-20-v1
```

dry-run 退出 0 时打印 `status=dry_run`、`database_connected=false`、`services_started=false`。工作区存在未提交的应用／脚本／测试改动时返回 `uncommitted_release_code` —— 这是设计行为：**发布必须能追溯到一个明确的代码提交**，只有本设计、阶段五计划与本文件等已登记文档允许处于未提交状态。

**实际启动。** 需同时追加 `--apply --allow-external-llm`；只给 `--allow-external-llm` 不会产生任何副作用。启动前会重新执行静态预检并核对身份未变，随后连接隔离库、原子写 `starting`、事务内种子、按 API → 前端 → report worker → PDF worker 顺序启动，全部就绪后才转为 `running` 并打开已认证浏览器。C 包是唯一活动包，不会在失败时静默切回 B 包。

**停止与回退。** 正常停止为 `Ctrl+C` 或关闭浏览器。顺序固定为：停止 API（立即关闭新受理）→ 关闭浏览器 → 停止前端 → 只读等待在途任务收敛 → 停止 report worker → 停止 PDF worker → 重试清理 → 汇总评价 → dispose engine → 恢复父环境 → 核验端口释放。**停止监督进程即完成活动配置回退**；不删除演示病例、报告、审计、PDF 或失败诊断。再次运行必须使用新的空库状态与新的输出目录。

**读取结果。** 输出目录只包含 `release.json`、`archive/`、`process-events.jsonl`、`session-checks.json` 与浏览器安全诊断／截图。`release.json` 的 `status` 为 `stopped` 仅当本次清理、评价与端口核验都无错误，且评价未发现完整性矛盾；归档原件与记录摘要不符、已保存摘要无法复算、在途任务未收敛或身份漂移时一律为 `failed`，并给出对应闭合错误码。遗留的 `starting`／`running` 记录（监督进程被强杀）**不得当作成功**，只读检查如下，它不连库、不写文件：

```powershell
.\backend\.venv\Scripts\python.exe scripts/run_numeric_history_demo_release.py `
  --inspect-release outputs/numeric-history-demo-release/2026-09-20-v1/release.json
```

输出 `unconfirmed_stop=true` 表示本次运行未确认停止；首版不实现自动接管或后台恢复。

**禁止事项。** 不得用于生产或临床；不修改 `.env`、系统服务或持久活动指针；不把 B 包设为自动备用；不重训、调参、重新索引或替换冻结制品；不为让演示通过而放宽数据库、身份、权限、任务时限、报告完整性或 PDF 校验；不在 C 包失败后清理失败输出或数据库事实。

### 本次参考窗口修正

真实数据库验收发现旧窗口缺少单位，无法通过逐指标可比性检查。参考比较专用投影已保留 unit / unit_state，模型输入特征计算保持原契约。配置身份新增 reference_history.units.v1，因此发布时必须用既有 `build_reference_case_windows.py --dataset ... --apply` 重建两病种参考窗口；保留旧窗口和旧报告，不覆写旧配置身份。测试种子的参考病例模拟登记来源契约，is_synthetic=False 只用于测试分支覆盖；所有内容仍是虚构的软件验收数据，不能导入业务库。

生成上下文还固定正式标准规则及来源绑定的完整哈希，worker 在同一只读可重复读事务中验证后读取，避免批准版本下的规则值或原文绑定被改动而未被发现。


## 第 7～9 项：保存历史与永久 PDF 原件（0025 / 0026）

历史入口为 `GET /api/v1/operator/report-history`，使用独立、至少 32 字节的 `REPORT_HISTORY_CURSOR_SECRET`。更换密钥会使旧分页游标失效，页面重新读取第一页即可。列表只读取保存记录的标量摘要，不连接当前病例；详情验证已保存快照、生成上下文及报告指纹。失败/取消只展示已确认输入与阶段审计，不能称为完成报告。

PDF 是独立的持久任务：`POST /reports/{id}/pdf-archive` 准备，`GET` 查询，失败且从未发布才允许 `POST /retry`。POST 必须携带 UUID `Idempotency-Key`。`GET /reports/{id}/download` 只交付首次成功发布的原件，不调用模型、标准查询或 PDF renderer。缺失/损坏只能从同 SHA、同长度、同页数的备份恢复。所有历史与 PDF 响应为 `private, no-store`。

归档默认关闭：`REPORT_PDF_ENABLED=false`、`REPORT_PDF_ACCEPTING=false`。开放前配置绝对私有目录 `REPORT_ARCHIVE_ROOT`，例如 `/var/lib/surgery-rag/report-archives`，属主 surgery、目录 0700 / 文件 0600（Windows 使用仅服务账号和管理员可访问的 ACL）。不得放在 uploads、Nginx alias、网站静态目录或符号链接/目录联接下。必须是支持同卷原子替换和持久化写入的本地文件系统；网络盘和对象存储不属于当前适配器合同。

### 固定渲染制品

使用官方 [Noto Sans CJK 字体](https://github.com/notofonts/noto-cjk/blob/main/Sans/README.md) 的 Simplified Chinese Regular OTF，并保留 [SIL OFL 许可](https://github.com/notofonts/noto-cjk/blob/main/Sans/LICENSE)。在与生产相同的 OS / Python / Playwright / Chromium 环境构建，不把 Windows manifest 复制给 Linux：

```bash
python scripts/build_report_pdf_renderer_manifest.py --font-dir /opt/surgery-rag/pdf-fonts --output-dir /opt/surgery-rag/pdf-renderers
```

font-dir 内必须有 `NotoSansCJKsc-Regular.otf`、`LICENSE`，以及官方 [Noto Sans Regular](https://github.com/notofonts/noto-fonts/blob/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf) 的 `NotoSans-Regular.ttf` 和另存为 `LICENSE-latin` 的 [OFL 许可](https://github.com/notofonts/noto-fonts/blob/main/LICENSE)。补充字体覆盖 `10⁹/L` 等单位的上标字符，不改写报告原文。脚本验证字体族、许可、实际源码、FontTools、Chromium executable 及版本；输出以 manifest SHA 命名的目录。将其中 manifest.json 绝对路径配置为 `REPORT_PDF_RENDERER_MANIFEST`。发布源码、Playwright、Chromium、FontTools、模板或字体变化必须重建 manifest；运行时不自动认可漂移。旧 ready 原件持续读取原字节。资源包不可由 Web 用户写入，保留每个已发布版本与许可。

**改动源码会作废已有 renderer 制品（2026-09-20 补充）：** manifest 覆盖 `report_pdf_renderer_manifest.py` 中 `RENDERER_FILES` 列出的源码、字体与许可字节、Chromium 可执行文件哈希、平台及打印选项。该清单**包含 `services/report_document_builder.py`**——它负责生成报告正文，因此**哪怕只改一句报告文字也会令现有 manifest 失效**，预检／加载时报 `frozen_renderer_mismatch`。这不是故障，是设计如此；但维护者容易只改文字而不知道要连带处理。

改动的完整同步步骤（缺一不可）：

1. **重建 manifest**：`python scripts/build_report_pdf_renderer_manifest.py --font-dir <已核实字体目录> --output-dir <新版本根目录>`。输出根按日期分目录，脚本再按 manifest 原字节 SHA 建子目录；同 digest 已存在时只校验不覆盖。
2. **更新硬编码身份**：如 `scripts/run_numeric_history_acceptance.py` 的 `RENDERER_SHA` 及其测试中的 manifest 路径。
3. **更新文档引用**：已有的历史记录**保留原路径与 SHA 并加作废说明，不改写历史**；交接性质的块（如计划中的 `REPORT_TEST_RENDERER_MANIFEST`）则替换为新值。
4. **重跑整仓非集成回归**（见[开发指南](DEVELOPMENT.md)的阶段出口门槛）。

已发布的归档 PDF 仍是原件，**不因新 renderer 重新渲染或替换**；旧 manifest 目录保留原字节。

渲染时从已验证字体按文档实际字符生成内嵌子集，使用互不重叠的 unicode-range，避免多页页眉/页脚重复载入完整 CJK 字体导致内存放大。缺字返回安全错误，不使用系统字体静默替代。字体版本和子集实现均纳入 renderer 身份。

### 三个独立进程职责

部署本仓库 `deploy/systemd/surgery-report-pdf-worker.service`、`surgery-report-pdf-sweep.service/.timer`、`surgery-report-file-cleanup.service/.timer`。worker 执行渲染，独立 sweep 每 15 秒处理过期任务，独立 cleanup 每 15 秒处理一个到期文件补偿；worker 停机时两个 timer 仍运行。全部使用 `KillMode=control-group`、`TimeoutStopSec=15`、`UMask=0077`。PDF 候选必须位于专用持久目录，不依赖服务私有 /tmp。Windows 监督使用 Job Object 管理 Chromium 整棵进程树。

初始并发 1、全局排队 20、每用户活跃 2；排队 600 秒、总执行 120 秒、租约 45 秒、心跳 10 秒；上限 64 MiB、200 页。失败/失租显式重试产生新 attempt，running 不自动重渲染。队列与租约都由数据库时间决定，任务消息不能延长总期限。监测 queued/running、最老队龄、失租/超时、安全错误码、原件 missing/corrupt、cleanup 超一小时积压、磁盘余量和三个服务状态。无任务时不以“无心跳”判断 worker 不健康。

### 删除与恢复

删除病例保留历史报告和 PDF；删除报告先提交数据库删除并登记持久 outbox，再尝试一次有界在线清理。返回 204 表示在线文件已移除，202 表示“报告已删除，文件清理中”。两者之后报告均为 404。清理任务保留到执行期限后的最终复查，防止晚写；账号级联同样登记全部文件。不得手工删除 outbox、attempt 审计或 `report_deletion_tombstones`。

```bash
python scripts/manage_report_pdf_archives.py inspect --report-id 17
python scripts/manage_report_pdf_archives.py restore --report-id 17 --backup-file /private/backup/original.pdf
python scripts/manage_report_pdf_archives.py restore --report-id 17 --backup-file /private/backup/original.pdf --apply
python scripts/manage_report_pdf_archives.py cleanup --once
```

inspect 与 restore 无 --apply 默认只读。恢复命令先输出 report_id / hash 预检，精确匹配才落位；已删除报告、无 published identity、源内容校验失败一律拒绝。禁止调用 renderer 填补缺失原件。`cleanup --sweep` 为维护窗口连续补偿命令，只处理数据库登记的对象，不接受任意目录清空。

### 备份集合及删除事实重放

必须进入维护窗口：关闭新报告/PDF受理和所有删除入口，排空正在写文件的任务，暂停 cleanup；保持该窗口直到数据库、私有 PDF 目录、渲染制品、清理/删除事实的备份全部完成。不要只关闭 PDF_ACCEPTING 就宣称写入冻结。

```bash
python scripts/backup_report_archive_inventory.py inventory --snapshot-id reviewed-backup-set-id --maintenance-window --output /private/backup/inventory.json
```

inventory 独占创建文件，记录 backup_id、人工备份集合标识、数据库 snapshot 诊断身份、全部原件 key / SHA / 长度 / 页数 / renderer hash、清理及删除事实。逐件读取验证，前后重查事实摘要和活跃写任务；任何变化导致该备份集失败，需要重新备份。inventory 中的 pg_current_snapshot 不是可供 pg_dump 使用的 exported snapshot；外部 pg_dump 必须在同一持续维护窗口内执行。备份完成后继续维护窗口运行只读文件门禁，再恢复服务。

删除事实需要独立增量备份，覆盖每次删除；不能随着 PDF 清理成功一起删除。恢复旧 DB / 文件后保持所有业务访问关闭，先用较新的 inventory 删除日志进行 dry-run，再在明确命名的目标连接环境变量上 apply：

```bash
python scripts/backup_report_archive_inventory.py replay-deletions --inventory /private/backup/newer-inventory.json --target-env RESTORE_DATABASE_URL
python scripts/backup_report_archive_inventory.py replay-deletions --inventory /private/backup/newer-inventory.json --target-env RESTORE_DATABASE_URL --apply
```

独立删除日志可用 `python scripts/backup_report_archive_inventory.py export-deletions --output /private/backup/deletions-unique-id.json` 导出。该命令只读数据库，不依赖 PDF 文件或字体可用性，输出可直接作为 replay-deletions 的 inventory 输入；应由备份任务在每次删除后持久复制到独立备份位置。

重放报告删除会触发原生 outbox，包含没有 PDF 的报告。日志缺失或无法证明覆盖所选恢复时间点时，不开放下载。RPO、RTO、备份保留天数、删除日志增量间隔、负责人和恢复演练日期由部署记录填写，不能用本机测试值替代。

### 发布与回滚门禁

1. 备份和只读 preflight，关闭新受理、排空旧 worker；审核实际 Alembic head 后升级至 0026。
2. 部署兼容前后端、私有目录和目标 OS 构建的 renderer；启动 PDF worker、独立 sweep 和 cleanup。
3. 执行下列 postflight（--worker-ready 只能在运维实际确认服务健康后传入），完成恢复演练和目标 Linux 容量验收，再开放 PDF_ACCEPTING。

```bash
python scripts/check_operator_report_archives_readonly.py --phase preflight --verify-files
python scripts/check_operator_report_archives_readonly.py --phase postflight --verify-files --worker-ready
```

检查器只读，不标记健康状态、不清理、不自动修复。检查 schema、来源指纹、原件身份、交付计数、过期任务、审计数量、cleanup 积压、原件 SHA、未登记文件和 renderer 漂移。发现损坏先恢复，不通过重新生成历史绕过。

在真实 Linux 4 GiB 主机联合加载 PostgreSQL / Web / RAG / BGE / 模型 worker / PDF worker，以十次访视、全指标和长表压力样例采集整个服务组峰值 RSS、p95、swap/OOM。并发 1 不构成容量保证；实测后配置 systemd MemoryHigh / MemoryMax，超预算先串行重任务或扩容再验收。Windows 的本机内存采样仅记录参考，本次不宣称生产容量通过。

回滚先关闭受理、排空未发布尝试，保留新增表、原件、交付、审计、删除日志和清理服务。只回退支持归档协议的兼容应用；不得恢复同步渲染下载。0025/0026 downgrade 对已有事实拒绝破坏性回退。

本机验收需设置 `TEST_DATABASE_URL`（明确本机 _test）和 `REPORT_TEST_RENDERER_MANIFEST`，运行 `scripts/run_operator_case_e2e.ps1`。PDF 验证产物区分 archived_original 与 synthetic_layout_only，后者只测试排版，不写入业务原件。
