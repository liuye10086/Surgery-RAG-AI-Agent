# 预测模型重构阶段五：本机隔离工程演示发布实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将阶段四已验收的 C 包放入一个默认无副作用、仅面向本机隔离测试库的监督式演示会话，形成可审计的启动、交互、停止、回退和工程评价闭环。

**Architecture:** 新增严格发布记录 schema、纯预检／评价模块、监督式 CLI 和已认证 Chromium 会话；冻结身份核验复用阶段四 runner，业务执行继续复用现有 FastAPI、Vue、报告 worker、PDF worker、历史读取和归档服务。活动配置只注入 CLI 拥有的子进程，停止 CLI 即撤销活动配置，不修改 `.env`、数据库结构、API 契约或前端组件。

**Tech Stack:** Python 3.11.4、Pydantic、SQLAlchemy、FastAPI、Playwright、现有 Vue 3／Vite、PostgreSQL 隔离测试库、pytest；Node.js 22.15.0、npm 10.9.2。无新增依赖。

日期：2026-09-20；执行更新：2026-09-21。版本：0.5。状态：**S1–S4 已完成，实施4／5；当前下一步 S5（需用户单独授权隔离库与外部 LLM）。** 依据：[阶段五设计](../specs/2026-09-20-prediction-model-refactor-phase-5-local-demo-release-design.md)、[阶段四实施计划](2026-09-16-prediction-model-refactor-phase-4-history-integration.md)、[总领文档](../specs/2026-09-09-prediction-model-refactor-master-design.md)。

## Global Constraints

- 本阶段仅发布本机合成工程演示，固定 `source_kind=synthetic`、`clinical_validity_claim=false`、`clinical_status=not_assessable`、`production_enabled=false`；不得写成生产或临床发布。
- 只允许本机 loopback 和数据库 `surgery_rag_phase4_test`，Alembic 必须为 `0031`。不得创建、删除、迁移、清空或复用非空数据库，不得回退到 `DATABASE_URL`。
- 冻结输入、摘要和验收结论以设计第 3 节为准；不得扫描“最新目录”、重建近似制品、切换 B 包兜底或修改登记哈希放行。
- 默认 CLI 不连接数据库、不创建输出、不启动进程／浏览器、不调用外部 LLM、不写 Python bytecode；只有同时提供 `--apply --allow-external-llm` 才进入实际启动路径。
- C 包是演示会话唯一活动包。父进程及子进程环境必须在成功、失败和中断路径恢复；不得修改 `.env`、系统服务、默认配置或持久活动指针。
- 不修改前端业务组件、API 数据契约、Alembic、`database/schema.sql` 或模型包；发现必须修改时先停止本步并修订设计。
- 日志、控制台、`release.json` 和诊断不得包含数据库 URL、密钥、令牌、密码、请求头、完整环境、LLM 请求／响应正文或病例正文；异常只保存阶段、类型和代码位置。
- 单元测试可使用 stub 验证控制流；最终数据库、worker、浏览器、权限、历史及 PDF 链路必须在明确隔离环境实际执行，不能以 mock 结果替代。
- 本计划不授权实际 `--apply`、外部 LLM 调用、数据库写入、演示启动、提交或推送。用户逐步发出“开始下一步”后只执行对应步骤；每步完成后列出实际修改、检查、失败／跳过、剩余步骤和下一步。
- 当前工作区的阶段四计划修正文档和阶段五文档必须保留。各步开始和结束均运行 `git status --short`，不覆盖或混入其他改动。

## 1. 五步顺序与交付门槛

| 步骤 | 交付 | 依赖 | 独立验收 |
| --- | --- | --- | --- |
| S1 | 严格发布记录、冻结身份、权威验收绑定和默认只读预检 | 已批准设计 | schema 状态机、数据最小化、所有静态漂移失败关闭、dry-run 零副作用 |
| S2 | 隔离库重检、事务种子、子进程环境和监督生命周期 | S1 | 空库／0031、原子记录、C 包环境、全部进程所有权、失败清理和环境恢复 |
| S3 | 已认证浏览器会话、停止受理、在途收敛与回退 | S2 | 本机会话可交互、停止顺序确定、端口释放、历史与归档不被删除 |
| S4 | 工程评价、安全诊断和 `release.json` 闭合 | S3 | 数据库／审计／文件事实可复算，主失败优先，临床状态固定不可评价 |
| S5 | 隔离集成、实际演示总验收、运维和阶段交接 | S1–S4 | 新阶段五运行证据、整仓 0 failed、文档与制品一致 |

每步遵循“先写失败测试 → 确认测试因缺少目标行为而失败 → 最小实现 → 定向回归 → `git diff --check` → 停止复审”。各步结束不自动提交；提交与推送只按用户单独指令执行。

## 2. 文件职责与固定接口

### 2.1 新增文件

| 文件 | 职责 |
| --- | --- |
| `backend/app/schemas/numeric_demo_release.py` | `numeric_history_demo_release.v1` 严格 schema、状态转换和安全诊断契约 |
| `scripts/numeric_history_demo_release.py` | 纯身份绑定、Git 门禁、记录构造／原子写入、数据库评价和安全错误投影 |
| `scripts/run_numeric_history_demo_release.py` | 无副作用 dry-run、隔离库种子、子进程环境、监督生命周期和退出码 |
| `scripts/numeric_history_demo_browser.py` | 已认证 Chromium 会话、页面安全诊断及会话结束信号 |
| `backend/tests/test_numeric_demo_release.py` | schema 和状态机单元测试 |
| `scripts/tests/test_numeric_history_demo_release.py` | 纯预检、评价和记录写入单元测试 |
| `scripts/tests/test_run_numeric_history_demo_release.py` | CLI、生命周期、环境恢复和失败顺序测试 |
| `scripts/tests/test_numeric_history_demo_browser.py` | 认证上下文、URL 脱敏和浏览器诊断测试 |
| `backend/tests/integration/test_numeric_history_demo_release.py` | 隔离库门禁、事务种子、任务收敛和评价事实集成测试 |

### 2.2 最终步骤修改／新增文档

| 文件 | 变更 |
| --- | --- |
| `docs/OPERATOR_REPORT_OPERATIONS.md` | 增加本机演示 dry-run、前置库准备、启动、停止、失败读取和禁止事项 |
| `docs/superpowers/specs/2026-09-09-prediction-model-refactor-master-design.md` | 回填阶段五状态、证据和真实资料仍开放的边界 |
| `docs/superpowers/specs/2026-09-20-prediction-model-refactor-phase-5-local-demo-release-design.md` | 更新实施状态和计划／结果链接 |
| `docs/superpowers/plans/2026-09-20-prediction-model-refactor-phase-5-local-demo-release.md` | 逐步勾选实际完成项和验证结果 |
| `docs/superpowers/notes/2026-09-20-prediction-model-refactor-phase-5-local-demo-release-result.md` | 记录新阶段五实际演示事实、限制和真实资料交接 |

### 2.3 固定 Python 接口

实现保持以下入口，测试直接针对这些边界；不得把业务预测或报告逻辑复制进发布模块：

```python
# backend/app/schemas/numeric_demo_release.py
class SafeCodeLocation(StrictNumericModel): ...
class SafeReleaseDiagnostic(StrictNumericModel): ...
class NumericDemoReleaseIdentities(StrictNumericModel): ...
class NumericDemoReleaseRuntime(StrictNumericModel): ...
class NumericDemoReleaseMetrics(StrictNumericModel): ...
class NumericDemoReleaseRecord(StrictNumericModel): ...

# scripts/numeric_history_demo_release.py
validate_acceptance_result(path: Path, identities: dict) -> dict
validate_git_release_state(root: Path, *, apply: bool) -> str
build_release_record(run_id: str, identities: dict, git_commit: str,
                     runtime: dict, started_at: datetime) -> NumericDemoReleaseRecord
transition_release(record: NumericDemoReleaseRecord, status: str, *,
                   at: datetime, metrics: dict | None = None,
                   diagnostics: list[dict] | None = None) -> NumericDemoReleaseRecord
atomic_write_release(path: Path, record: NumericDemoReleaseRecord) -> None
inspect_demo_database(connection) -> dict
seed_demo_database(connection, source_dir: Path, identities: dict) -> dict
summarize_demo_release(session_factory, archive_root: Path,
                       seeded: dict) -> NumericDemoReleaseMetrics
safe_diagnostic(stage: str, error: BaseException) -> SafeReleaseDiagnostic

# scripts/run_numeric_history_demo_release.py
preflight(args) -> dict
build_child_environment(args, database_url: str, output: Path) -> dict[str, str]
start_services(args, owned, env) -> None
wait_for_inflight(session_factory, deadline: float) -> dict
execute(args, identities: dict) -> int
main(argv: list[str] | None = None) -> int

# scripts/numeric_history_demo_browser.py
run_authenticated_demo(*, output: Path, tokens: dict, subjects: list[dict],
                       owned, stop_event, session_ready,
                       playwright_factory=None, poll_seconds: float = 0.25) -> dict
run_session_checks(page, tokens: dict, subjects: list[dict]) -> dict
write_session_checks(output: Path, admission: dict) -> None
```

S4 相对本节初稿的实际签名：`summarize_demo_release(session_factory, archive_root, seeded)` 维持不变，`seeded` 由 CLI 补入 `identities` 供身份比对；`shutdown_demo_session` 增加 `session_factory`／`archive_root` 两个位置参数，`summarize` 改为零参可调用；`run_authenticated_demo` 的 `token: str` 改为 `tokens: dict`（`primary`／`secondary`／`doctor`），以支持第 9 节要求的权限与幂等实检。

`NumericDemoReleaseRecord` 的顶层字段固定为：`schema_version`、`run_id`、`status`、`is_synthetic`、`clinical_validity_claim`、`clinical_status`、`production_enabled`、`started_at`、`stopped_at`、`identities`、`runtime`、`metrics`、`diagnostics`、`cleanup_errors`。`identities` 固定记录来源 manifest／数据内容、B canonical、C canonical、renderer 原字节、阶段四验收原字节和 Git commit 六类 SHA；`runtime` 固定记录 Python、Node、Playwright、fonttools 和 Chromium 版本。全部模型 `extra='forbid'`；SHA 为 64 位小写十六进制，Git 提交为 40 位小写十六进制；计数为严格非负整数。

`metrics` 使用闭合子模型：`admission` 显式包含请求、幂等重放、拒绝和逐 reason 计数；`jobs` 显式包含五种终态／运行态及未收敛计数；`timings` 对五个既有执行阶段分别保存样本数、总毫秒和最大毫秒；`llm_audit` 保存 started、finished、闭合／未闭合报告数；`authorization` 保存非所有者 404、错误角色 403 和疾病权限拒绝的实际检查数；`history` 保存核验报告数和不一致数；`pdf` 保存 ready／failed／missing／corrupt、下载、字节核验和 SHA 不一致数；`identity` 保存六类实际身份是否匹配。reason code 必须来自本模块列出的固定集合，不接受自由键。

允许状态转换仅为：

```text
starting -> running -> stopped
starting -> failed
running  -> failed
```

`stopped`／`failed` 必须有 `stopped_at`；`running` 不得有 `stopped_at`。`release.json` 不保存数据库标识以外的连接信息、token、完整 URL、自由异常正文或病例内容。

## S1：严格发布记录、冻结身份与默认只读预检

**Files:** 新增 `backend/app/schemas/numeric_demo_release.py`、`backend/tests/test_numeric_demo_release.py`、`scripts/numeric_history_demo_release.py`、`scripts/tests/test_numeric_history_demo_release.py`、`scripts/run_numeric_history_demo_release.py`、`scripts/tests/test_run_numeric_history_demo_release.py`。

### S1.1 先写发布记录失败测试

- [x] 在 `backend/tests/test_numeric_demo_release.py` 写最小有效 `numeric_history_demo_release.v1` fixture，断言 `starting`、`running`、`stopped`、`failed` 的时间约束和上节唯一转换图。
- [x] 参数化拒绝未知字段、负计数、布尔值冒充整数、非冻结临床标记、错误 SHA／Git 长度、含 `url|token|secret|password|patient|prompt|response` 等禁止键的嵌套诊断。
- [x] 断言 JSON 往返只保留闭合字段，时间使用带时区 ISO 8601，`clinical_status` 永远为 `not_assessable`。
- [x] 运行并确认因模块尚不存在而失败：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_numeric_demo_release.py -q
```

预期：测试收集或导入失败，原因仅为目标 schema 尚未实现。

### S1.2 最小实现严格 schema

- [x] 复用 `app.schemas.synthetic_numeric_prediction.StrictNumericModel` 的严格配置；若该基类不适合导入，只在新文件定义一个等价私有基类，不改旧 schema。
- [x] 用 `Literal` 固定 schema、合成／临床／生产标记和状态；用 `model_validator(mode='after')` 校验时间与状态，不接受自动类型转换。
- [x] 将安全诊断限制为 `stage`、`error_type`、`error_location`；代码位置只含 `file`、`line`、`function`，文件名必须为 basename。
- [x] 运行 S1.1 命令，预期全部通过。

### S1.3 先写冻结验收和 Git 门禁失败测试

- [x] `scripts/tests/test_numeric_history_demo_release.py` 用真实冻结文件验证：权威验收原字节 SHA 为 `3dd8473c6df25aeb84c7e5c2782caef6e420e60227578062108a9edf30332c37`，且绑定来源、B/C 包、renderer、5/5/5/5 次数和空 `page_errors`。
- [x] 每次只篡改一个字段或一个字节，断言固定错误码 `frozen_acceptance_mismatch`；缺文件、过大 JSON、额外成功推断也必须失败关闭。
- [x] mock `subprocess.run` 只接收参数数组和 `shell=False`，验证 `git rev-parse HEAD` 与 `git status --porcelain=v1 --untracked-files=all`；无法解析 HEAD 时返回 `git_identity_required`。
- [x] dry-run 允许当前阶段四计划、阶段五设计／计划文档改动；`--apply` 只允许文档改动，任何 `backend/`、`frontend/`、`scripts/`、迁移或测试改动均返回 `uncommitted_release_code`。
- [x] 工作树路径采用仓库相对 POSIX 路径精确比对，不用子串或后缀白名单。
- [x] 运行并确认失败：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest ..\scripts\tests\test_numeric_history_demo_release.py -q
```

### S1.4 实现纯冻结绑定和 Git 门禁

- [x] 在 `scripts/numeric_history_demo_release.py` 定义冻结常量，解析阶段四 `result.json` 后只返回发布需要的闭合身份，不复制病例内容、报告正文或环境。
- [x] `validate_acceptance_result` 先限制普通文件、非 symlink、最大 1 MiB，再检查原字节摘要和 JSON 关键事实；使用阶段四的 canonical 身份字段重新比对。
- [x] `validate_git_release_state` 返回 HEAD SHA；dry-run 与 apply 采用两套明确白名单，apply 对未提交代码失败关闭。
- [x] 运行 S1.3 命令，预期全部通过。

### S1.5 先写 CLI 零副作用失败测试

- [x] 在 `scripts/tests/test_run_numeric_history_demo_release.py` 复用阶段四 `argv` fixture，并增加 `--acceptance-result`。
- [x] monkeypatch `sqlalchemy.create_engine`、`subprocess.Popen`、socket connect、Playwright、`Path.mkdir/write_*` 和 `execute` 为禁止调用；真实 dry-run 仍须退出 0、输出 `status=dry_run`、`database_connected=false`、`services_started=false`。
- [x] 参数化验证缺少／重复参数、缩写、未知参数、symlink、已存在输出、端口占用、`--apply` 无授权、单独授权、数据库 query／fragment／远程主机／错误库名和四个 libpq 重定向变量。
- [x] 所有错误输出仅为闭合错误码，传入的假密码和 URL 不得出现在 stdout/stderr。
- [x] 运行并确认失败：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest ..\scripts\tests\test_run_numeric_history_demo_release.py -q
```

### S1.6 实现默认只读 preflight

- [x] `SafeParser` 使用 `allow_abbrev=False` 并在解析前拒绝重复单值参数；对输入原始路径及其现有父级逐项 `lstat` 拒绝 symlink，再执行 `resolve(strict=True)` 和文件／目录类型验证。输出只验证不存在，不创建。
- [x] 复用 `scripts.run_numeric_history_acceptance.validate_database_url` 和 `preflight`，不要弱化数据库 URL、来源、B/C 包、runtime、renderer 或端口检查。
- [x] 增加权威验收和 Git HEAD／工作树门禁；将 `sys.dont_write_bytecode=True` 设在导入业务模块前。
- [x] `main()` 仅在 `args.apply` 为真时调用 `execute`；dry-run JSON 不输出绝对路径或环境值。
- [x] 顺序运行三个 S1 测试文件，预期全部通过；运行 `git diff --check`。

### S1 复审门槛

- [x] 检查新增模块没有数据库连接、进程启动、网络或业务写入发生在导入／dry-run 路径。
- [x] 对照设计第 3、5、6.1、8、10、11.1 节逐项确认覆盖。
- [x] 记录测试数量与结果，停止等待下一步；不提交、不推送。

### S1 实施结果（2026-09-20）

- 新增严格 `numeric_history_demo_release.v1` schema、闭合工程指标、合成／临床／生产固定标记、安全诊断和唯一状态转换图。
- 新增纯发布模块，冻结阶段四验收原字节 SHA 与来源、B／C 包、renderer、5／5／5／5 外部调用事实；Git 门禁只允许四份明确文档处于未提交状态。
- 新增默认静态 CLI，参数重复／缩写、输入及父级 symlink、错误隔离库、libpq 重定向、端口占用、已有输出和缺少双开关授权均失败关闭；实际执行入口仍固定返回未实现，不可能在 S1 启动服务。
- TDD 证据：schema 测试先因模块缺失 32 failed 后转绿；纯发布测试先因模块缺失 33 failed 后转绿；CLI 测试先因入口缺失 23 failed，随后补充等号形式重复参数、重复布尔参数及破损 symlink 父级用例逐项经历 RED→GREEN。
- 最终联合验证为 **143 passed／0 failed**（S1 92 项及阶段四 runner 51 项）；存在 1 条既有 Pydantic 配置弃用 warning。独立复审结论为 Critical／Important／Minor 均 0，可进入 S2。
- 真实静态命令在未提交 S1 代码状态下按设计返回 `uncommitted_release_code`，没有创建输出目录；未连接数据库、启动服务／浏览器、调用外部 LLM、提交或推送。

## S2：隔离库重检、事务种子与监督式进程生命周期

**Files:** 修改 `scripts/numeric_history_demo_release.py`、`scripts/run_numeric_history_demo_release.py` 和对应测试；新增 `backend/tests/integration/test_numeric_history_demo_release.py` 的首批数据库用例。

### S2.1 先写数据库与种子失败测试

- [x] 单元测试用受控 connection 验证 SQL 顺序：先 `SET TRANSACTION READ ONLY`，再读取 `current_database()`、Alembic 版本和 `users/operator_cases/ai_reports` 计数；任一不符均不调用种子。
- [x] 集成测试仅在 `TEST_DATABASE_URL` 明确指向 `surgery_rag_phase4_test` 时运行，验证实际数据库身份、0031、空业务表；fixture 清理规则沿用现有 integration 配置，不新增业务库回退。
- [x] 写事务种子测试：用户、疾病和三个冻结场景要么全部可见，要么注入中途失败后全部不可见；不使用 `TRUNCATE`、upgrade 或 drop/create。
- [x] 断言种子结果只返回用户 id、病例 id、匿名主体标识和认证所需的进程内值；token 不得进入发布记录。
- [x] 先运行单元测试确认失败；只有隔离库满足文档前提时才运行集成测试，否则明确记为 skipped／blocked：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest ..\scripts\tests\test_numeric_history_demo_release.py ..\scripts\tests\test_run_numeric_history_demo_release.py -q
.\.venv\Scripts\python.exe -m pytest tests/integration/test_numeric_history_demo_release.py -q
```

### S2.2 实现数据库重检和事务种子

- [x] `inspect_demo_database` 使用数据库返回的身份而不是仅信任 URL；检查 `current_database()='surgery_rag_phase4_test'`、`alembic_version='0031'` 和三张业务表为空。
- [x] `seed_demo_database` 复用阶段四 `convert_source_package`、`seed_prediction_cases` 和用户／疾病字段，不复制病例转换逻辑；在单个 `engine.begin()` 外层事务中创建用户／疾病，并把绑定该 connection 的 `sessionmaker` 交给 `seed_prediction_cases`，使用户、疾病和病例统一提交或统一回滚。
- [x] 不把种子路径、连接串或 token 保存到发布记录；异常离开事务后由 SQLAlchemy 回滚。
- [x] 运行 S2.1 测试，预期可执行项全部通过。

### S2.3 先写环境、记录和进程生命周期失败测试

- [x] 断言 `build_child_environment` 同时覆盖 `DATABASE_URL`／`VECTOR_STORE_CONNECTION_STRING`，`NUMERIC_MODEL_BUNDLE` 指向 C 包，报告／PDF开关全开，归档在本次输出，三类模型仓库离线，且不修改调用者字典。
- [x] 断言顺序固定为：重新 preflight → 连接后只读核验数据库 → 创建全新输出并原子写 `starting` → 事务种子 → 启动；身份变化时输出和数据库均 untouched，数据库门禁失败时不创建输出。
- [x] 对 API、前端、报告 worker、PDF worker 的每个启动位置注入失败，断言已经启动的拥有进程按逆序关闭、记录为 `failed`、父环境完全恢复、主失败不被 teardown 错误覆盖。
- [x] 断言子进程命令固定为参数数组：

```text
python -m uvicorn backend.tests.e2e.report_test_server:app --host 127.0.0.1 --port 18060
node frontend/node_modules/vite/bin/vite.js --host 127.0.0.1 --port 15173 --strictPort
python -m app.workers.report_worker
python -m app.workers.report_pdf_worker
```

- [x] 断言 `OwnedProcesses` 复用现有 Windows Job／POSIX process-group 所有权，固定进程名互不覆盖，任一拥有进程提前退出会使发布失败。
- [x] 子进程原始 stdout/stderr 不得直接写入输出；监督包装器将其丢弃，只把进程名、`started|ready|stopped|exited`、时间和退出码写入闭合结构化事件，测试用含连接串／token 的假输出验证不会落盘。
- [x] 运行 `scripts/tests/test_run_numeric_history_demo_release.py`，确认新增测试先失败。

### S2.4 实现原子起始记录、子进程环境和启动

- [x] `atomic_write_release` 在同目录写临时文件、flush、`os.fsync` 后 `os.replace`；序列化前再次经严格 schema 验证。写入失败不得继续开放服务。
- [x] 只在实际执行函数的受控作用域保存并恢复 `os.environ`；子进程使用显式 `env`。即使 `KeyboardInterrupt`／`SystemExit` 也进入清理。
- [x] 扩展或小幅封装现有 `OwnedProcesses`，使四个长期进程可分别命名；不得改 worker 业务行为。
- [x] 保留现有 Windows Job／POSIX process-group 关闭语义，但用安全 sink 取代原始子进程日志文件；发布诊断依赖固定事件、退出码和安全错误投影。
- [x] `start_services` 按 API → 前端 → report worker → PDF worker 顺序启动；API、前端有 loopback readiness，worker 用进程存活和一次数据库只读观察确认。
- [x] 全部就绪后才将发布记录转为 `running`。任何更早失败都保持不可用并转 `failed`。
- [x] 运行 S2 单元／可用集成测试及 `git diff --check`。

### S2 复审门槛

- [x] 对照设计第 6.2、7、8、10 节，检查没有迁移、清库、持久配置、隐式 B 包回退或秘密落盘。
- [x] 检查所有资源关闭都独立尝试，teardown 错误追加到 `cleanup_errors` 而不覆盖主失败。
- [x] 记录实际验证与未执行的数据库项，停止等待下一步；不提交、不推送。

### S2 实施结果（2026-09-21）

- 新增数据库返回事实门禁：只读事务按固定顺序核对 `current_database()`、Alembic `0031` 及 `users/operator_cases/ai_reports` 空表；错误数据库、版本或非空状态均在创建输出和种子前失败关闭。
- 新增单外层事务种子：复用 `convert_source_package` 与 `seed_prediction_cases`，通过绑定同一 connection 的 `sessionmaker` 统一提交或回滚三个演示身份、疾病与三个冻结合成病例；返回值只含用户／病例 id、匿名病例码和合成主体 id。
- 新增原子 `release.json`、C 包专属子进程环境、Windows Job／POSIX process-group 所有权、API → 前端 → report worker → PDF worker 固定启动顺序、就绪观察和闭合进程事件；子进程 stdout/stderr 丢弃，主错误优先，清理错误单独追加。
- TDD 先出现数据库／原子写 8 项失败及环境／进程 8 项失败，补齐实现后转绿。独立复审发现 POSIX 子孙进程逃逸和 runtime 失败遗留空目录两项 Important，均补回归测试修复；复核后 Critical／Important 均 0。
- 最终联合验证为 **164 passed／0 failed**（阶段五 schema、S2 模块／CLI 及阶段四 runner），存在 1 条既有 Pydantic 配置弃用 warning；S2 定向模块／CLI 为 **81 passed**。`git diff --check` 通过，仅有既有 LF/CRLF 提示。
- 隔离数据库集成测试已新增，但当前未配置精确 `TEST_DATABASE_URL`，因此 **3 skipped**；未用 mock 冒充真实数据库结果。真实静态命令仍因阶段五代码未提交按设计返回 `uncommitted_release_code`，输出目录不存在。
- 本步未实际连接或写入数据库，未启动服务／浏览器，未调用外部 LLM，未执行迁移、清库、提交或推送。阶段五实施2／5，剩 S3–S5，下一步 S3。

## S3：已认证浏览器会话、停止受理与回退

**Files:** 新增 `scripts/numeric_history_demo_browser.py`、`scripts/tests/test_numeric_history_demo_browser.py`；修改 CLI 及其测试、集成测试。

### S3.1 先写浏览器安全和会话失败测试

- [x] 复用 `numeric_history_acceptance_browser.safe_page_url` 的语义，验证 userinfo、query、fragment、无效端口和恶意字符串不会泄漏。
- [x] fake Playwright 断言 headed Chromium 只访问 `http://127.0.0.1:15173`，认证 token 仅写入 browser context／页面运行时，不写日志、截图名、`release.json` 或诊断 JSON。
- [x] 断言等待现有 AI 操作者 shell 的稳定 locator，三个冻结病例均可见；页面异常只记录异常类型、脱敏 URL、截断 body 和截图。
- [x] 断言用户关闭浏览器或 Ctrl+C 均设置同一 stop_event，函数不自行重启浏览器／API 或重新受理报告。
- [x] 运行并确认失败：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest ..\scripts\tests\test_numeric_history_demo_browser.py -q
```

### S3.2 实现已认证本机会话

- [x] 复用阶段四创建的 AI 操作者 token 生成方式；浏览器 context 初始化后立即在本机 origin 注入认证，令牌变量生命周期不越过 `run_authenticated_demo`。
- [x] 浏览器保持可交互并周期观察 owned process 存活；只在 stop_event、浏览器关闭或拥有进程失败时返回。
- [x] Playwright 的创建、页面循环和关闭都放在同一个受管浏览器子进程主线程；监督主线程只接收严格协议的 `session_ready`／`stop_event`，从而能在 Ctrl+C 时先停止 API，再通知浏览器退出，并在卡死时强制回收进程树。
- [x] 安全诊断复用阶段四截图／body 截断上限，输出只使用相对制品名和错误类型。
- [x] 运行 S3.1 测试，预期通过。

### S3.3 先写停止顺序与在途收敛失败测试

- [x] 用事件列表严格断言停止顺序：停止 API（立即关闭新受理）→ 关闭浏览器 → 停止前端 → 只读轮询 queued/running → 停止 report worker → 停止 PDF worker → 汇总 → dispose engine → 恢复环境。
- [x] `wait_for_inflight` 只观察既有 job／PDF attempt 状态，不直接更新终态；达到设计的总时限后返回未收敛事实并使发布失败。
- [x] 模拟报告 completed、failed、cancelled、租约到期和 PDF rendering；断言只在 queued/running 为零时视为收敛。
- [x] 模拟每个 stop／poll／dispose 失败，断言所有后续清理仍尝试，端口检查在最后执行，主失败优先。
- [x] 运行 CLI 单元测试，确认新增测试先失败。

### S3.4 实现停止受理、收敛和回退

- [x] 收到停止信号后立即停止 API 关闭新受理，再让 browser helper 返回并停止前端；不通过修改数据库状态或运行中 settings 假装停单。
- [x] 保留 report／PDF workers 直到在途任务按既有时限和租约收敛；轮询间隔和截止时间取自现有配置上限，不使用无限等待。
- [x] 收敛后关闭 worker；未收敛、worker 提前退出或端口未释放均写安全诊断并将最终状态设为 `failed`。
- [x] 不删除种子、报告、审计、归档或失败产物；下一次必须使用新空库状态和新输出目录。
- [x] 运行 S3 单元／可用集成测试和 `git diff --check`。

### S3 复审门槛

- [x] 对照设计第 4、6.2、7、8、10、11.2 节，确认浏览器身份、停止受理、在途收敛、进程所有权和回退均有测试。
- [x] 确认没有前端、API、迁移或数据库 schema diff。
- [x] 记录结果、剩余和下一步，停止等待；不提交、不推送。

### S3 实施结果（2026-09-21）

- 新增已认证 headed Chromium helper：首次导航完成后严格核验实际 origin 为 `http://127.0.0.1:15173`，再把临时 token 单次写入该 origin；不使用会对后续外域重复注入的 init script，重定向外域时失败关闭。
- 浏览器改为第五个 owned 子进程，Playwright 生命周期全部位于其主线程；Windows Job／POSIX process group 提供强制回收边界。token 只经匿名 stdin 管道传入，stdout 只允许 `ready|stopped|error` 闭合事件，父进程 daemon 线程不会阻止 CLI 退出。
- 停止顺序固定为 API → 浏览器 → 前端 → 只读等待在途任务 → report worker → PDF worker → 重试清理 → 汇总 → engine dispose → 环境恢复 → 端口核验；每个清理步骤独立尝试，主失败不被覆盖，不修改任务状态或删除演示事实。
- TDD 先出现浏览器模块缺失的 9 项失败、CLI 浏览器／停止控制缺失的 5 项及随后 2 项失败，补齐实现后转绿。独立复审先发现 token 跨 origin、浏览器线程卡死和首次导航重定向三个 Important，均增加回归测试并修复；最终复核为 **0 Critical／0 Important**。
- 最终联合验证为 **187 passed／0 failed**（阶段五 schema、发布模块／CLI／浏览器及阶段四 runner），存在 1 条既有 Pydantic 配置弃用 warning；S3 浏览器与 CLI 定向验证为 **63 passed**。`git diff --check` 通过，仅有既有 LF/CRLF 提示。
- 隔离数据库集成当前因未配置精确 `TEST_DATABASE_URL` 而 **4 skipped**；未以 mock 冒充真实数据库链路。本步未实际连接或写入数据库，未启动服务／浏览器，未调用外部 LLM，未执行迁移、清库、提交或推送。阶段五实施3／5，剩 S4–S5，下一步 S4。

## S4：工程评价、安全诊断与发布记录闭合

**Files:** 修改发布模块、schema、CLI 和全部对应测试；扩展隔离集成测试。

### S4.1 先写评价事实失败测试

- [x] 构造最小 ORM／数据库事实，验证任务状态 `queued/running/completed/failed/cancelled`、未收敛数、`failure_phase`／`last_execution_phase`、安全错误码的计数。
- [x] 从 `ReportGenerationAuditRecord` 逐报告统计 `invocation_started` 和 `task_finished`，要求 batch、事件顺序和闭合关系一致；不保存 audit payload 正文。
- [x] 从 `ReportPdfArchive/Attempt/Delivery` 统计 ready、failed、missing、corrupt、下载次数、renderer SHA，并逐个读取 archive 原件重新计算 SHA／字节数；原件或摘要不一致为失败事实。
- [x] 验证保存的 `generation_context`、输入／上下文／证据／文档摘要与 C 包身份可读；不得加载当前模型重算历史。
- [x] 明确断言 `AIReport.status='completed'` 不等于每个预测 `status='available'`，历史不足场景仍可正确计入 completed。
- [x] 权限、错误角色、疾病权限、幂等和取消只接受本次浏览器会话实际记录的闭合结果，不从“没有错误”反推通过。
- [x] 运行相关测试并确认因评价未实现而失败。

### S4.2 实现可复算工程评价

- [x] `summarize_demo_release` 只纳入本次 seeded 用户／病例／报告 id，避免把隔离库中意外出现的其他记录混入分母；发现外部记录即失败关闭。
- [x] 通过 ORM／参数化 SQL 聚合状态和审计，通过现有 `ArchiveStorage` 读取原件；不修改任何业务行或下载计数。
- [x] `NumericDemoReleaseMetrics` 分开保存 `admission`、`jobs`、`timings`、`llm_audit`、`authorization`、`history`、`pdf` 和 `identity`，每块字段闭合、数值非负、reason code 有闭合集。
- [x] 不计算 MAE、校准、获益、亚组或临床准确率；顶层临床状态继续固定不可评价。
- [x] 运行 S4.1 测试，预期通过。

### S4.3 先写最终记录与错误优先级失败测试

- [x] 覆盖正常 stopped、会话主失败、评价失败、teardown 失败、原子写失败、KeyboardInterrupt 和强制子进程退出。
- [x] 主失败存在时 teardown／评价错误只追加；正常路径中任一 teardown／评价错误会把最终状态变为 `failed`。
- [x] 扫描序列化 JSON，确保测试注入的数据库 URL、token、密码、HTTP header、SQL／LLM 原文均不存在。
- [x] `starting`／`running` 遗留记录不得由只读恢复函数伪造为 `stopped`；只能报告 `unconfirmed_stop` 诊断。
- [x] 运行测试并确认先失败。

### S4.4 闭合记录和诊断

- [x] `safe_diagnostic` 只使用异常类、阶段和 traceback basename／行号／函数；控制台只输出固定错误码和最终相对制品名。
- [x] 正常停止在所有清理、评价和端口释放验证后原子写 `stopped`；任何失败写 `failed`。若最终记录写入失败，退出非零且不重新开放服务。
- [x] 输出目录仅允许 `release.json`、`archive/`、拥有进程安全日志、浏览器安全诊断／截图和明确的评价附件；测试验证不存在 token 或连接串。
- [x] 运行 S4 全部定向测试、可用集成测试和 `git diff --check`。

### S4 复审门槛

- [x] 对照设计第 8–11 节检查指标、分母、错误语义和数据最小化；人工抽查一个成功 fixture 和一个失败 fixture 的 JSON。
- [x] 确认发布控制正确、演示链路可运行、临床有效性不可评价这三类结论分别表达。
- [x] 记录结果，停止等待 S5 的实际外部调用授权；不提交、不推送。


### S4 实施结果（2026-09-21）

- 新增 `numeric_demo_session_checks.v1` 严格契约与闭合结果集合；命名检查与其计数一一绑定，任一检查「零观察」即校验失败，杜绝从「没有错误」反推通过。
- 新增纯评价：`build_release_metrics` 从事实字典重算 `admission/jobs/timings/llm_audit/authorization/history/pdf/identity` 八个闭合块；`collect_demo_facts` 用参数化 SQL 读取本次 seeded 用户／病例范围，范围外任何记录即 `demo_external_records_present` 失败关闭；`summarize_demo_release` 组合两者并并入浏览器会话记录。
- 阶段耗时取自 `phase_entered` 审计事件的自身顺序（末段以 job `finished_at` 收口），不读挂钟；LLM 审计按报告要求同一 batch 且 started 先于 finished，违反即 `demo_audit_integrity_failed`；历史块只重算已保存摘要，不加载当前模型。
- 发布记录闭合：正常路径在全部清理、评价与端口核验后原子写 `stopped` 并打印相对制品名；任何主失败、teardown 或评价错误写 `failed`；最终写入失败返回非零且不重新开放。`safe_diagnostic` 只保留异常类型、阶段与 basename／行号／函数。
- 新增只读 `--inspect-release`：遗留 `starting`／`running` 记录只报告 `unconfirmed_stop`，不伪造 `stopped`，全程不连库、不写文件。
- 浏览器会话新增固定检查序列（同源 `page.request`，三个种子身份各一次）：非所有者 404、错误角色 403、幂等重放（同一 Idempotency-Key 返回同一报告）与真实 queued 取消；期望不成立即 `demo_session_check_failed`，不写记录、不宣告就绪。子进程协议由单 token 改为三个匿名令牌，仍只经 stdin 管道传递。
- TDD 先出现 schema 15 项、纯评价 29 项、CLI 4 项、浏览器 12 项失败，补齐实现后全部转绿。隔离集成用例在事务内插入真实行验证范围门禁、摘要复算与归档原件复读；因无精确 `TEST_DATABASE_URL` 而 **8 skipped**，未以 mock 冒充。
- 整仓非 integration 回归首次在 S4 运行（S1–S3 只跑定向用例），暴露 1 项**由阶段五 S1 引入、此前未被任何步骤发现**的既有失败：`tests/test_cleanup_contracts.py::test_only_current_cleanup_specs_remain` 的允许清单未登记阶段五设计文档；已按阶段一至四的同类处置补登记，该文件 19 项通过。
- 联合验证 **251 passed／0 failed**（阶段五 schema、发布模块／CLI／浏览器与阶段四 runner），存在 1 条既有 Pydantic 配置弃用 warning。`git diff --check` 通过，仅有既有 LF/CRLF 提示。
- 真实默认 dry-run 仍按设计返回 `uncommitted_release_code` 且不创建输出目录；`--inspect-release` 对 `running` 遗留记录实际执行，退出 0、报告 `unconfirmed_stop=true`、原文件字节不变。
- 独立复审（只读）结论：1 项 Critical、3 项 Important、若干 Minor，均已处理。**Critical 为真实缺陷**：`_llm_audit_metrics` 原按「每报告一对 started／finished」配对，而真实报告会为每个模型任务各写一条 `task_finished`（仅叙述有一条 `invocation_started`），因此任何真实会话都会触发 `demo_audit_integrity_failed` 并让 S5 无法达到 `stopped`。已改为**按 task 配对**（无对应 `invocation_started` 的 `task_finished` 属正常，未被闭合的 `invocation_started` 计入 unclosed），并用真实产物 `outputs/numeric-history-acceptance/2026-09-20-v2/c-ad-report.json` 的事件流补了回归用例（`REAL_REPORT_EVENTS`）。
- 复审后另做三项收紧：①`stopped` 现在受 `evaluation_blockers` 门禁——归档原件字节不符、已保存摘要不一致、在途未收敛或身份漂移任一存在时一律写 `failed` 并给出对应闭合码，而不再以 `stopped` 掩盖；②ready 归档的 `renderer_sha256` 必须等于冻结 renderer 身份，否则 `demo_renderer_identity_mismatch`；③评价失败与清理失败分开命名（`demo_evaluation_failed` / `demo_shutdown_failed`），会话级失败码（如 `demo_session_check_failed`、`owned_service_exited`）并入控制台闭合码集合。
- `JobMetrics` 增补 `phase_timeout_phases`（闭合相位、有序去重），补齐设计第 9 节「`phase_timeout` 次数与阶段」。
- 另按复审 Minor 修正阶段耗时的边界：同一报告的 `phase_entered` 现在**按 batch 内配对**，只有单次尝试的报告才以 job `finished_at` 收口；被重新领取（租约到期重排）的报告不会把两次尝试之间的空档算成某个阶段的耗时，其最后一次尝试的末段如实留空。
- 本步为验证集成用例 SQL 可用，曾在既有隔离库 `surgery_rag_phase4_test` 上以**单个事务执行用例内的插入并全部回滚**（`.tmp/probe-s4-integration-sql.py`）：复查行数与既有值一致，未留下任何写入；该探针不创建、不迁移、不清空数据库。未启动服务或浏览器，未调用外部 LLM，未提交或推送。

### S4 覆盖落点

| 设计要求 | 实际位置 |
| --- | --- |
| 工程评价可复算、分母限定 | `collect_demo_facts`、`build_release_metrics`、S4.1／S4.2 测试 |
| 权限／角色／病种／幂等／取消的实际记录 | `run_session_checks`、`NumericDemoSessionChecks`、`run_numeric_history_demo_browser` 测试 |
| 发布记录闭合与错误优先级 | `execute` 收口段、`safe_diagnostic`、S4.3／S4.4 测试 |
| 遗留记录不得伪造成 `stopped` | `inspect_release_record`、`--inspect-release` |
| 完整性事实不得以 `stopped` 掩盖 | `evaluation_blockers`、归档 renderer 身份、`demo_*_integrity_failed` |
| `phase_timeout` 次数与阶段 | `JobMetrics.phase_timeout_phases` |

## S5：隔离集成、实际演示总验收与阶段交接

**Files:** 完成 integration 测试；修改／新增第 2.2 节文档。只有用户开始 S5 后，才按本节操作隔离库和外部 LLM。

### S5.1 静态与单元总回归

- [ ] 核对 `git status --short`，确认只有阶段五实现、测试和已知文档；任何无关代码改动先报告，不混入。
- [ ] 实际 `--apply` 的 Git 门禁要求阶段五应用／脚本／测试代码已进入当前 HEAD。若 S1–S4 仍未提交，先停止并等待用户单独授权本地提交；不因执行 S5 自动提交，也不要求推送。
- [ ] 运行阶段五所有单元／CLI 测试：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest `
  tests/test_numeric_demo_release.py `
  ..\scripts\tests\test_numeric_history_demo_release.py `
  ..\scripts\tests\test_run_numeric_history_demo_release.py `
  ..\scripts\tests\test_numeric_history_demo_browser.py -q
```

- [ ] 运行默认 dry-run，确认 0 退出、无输出目录、无数据库连接／进程／外部调用；保存命令和身份摘要，不保存连接信息。

### S5.2 隔离数据库与生命周期集成

- [ ] 操作者按既有开发流程准备一个可丢弃且为空的 `surgery_rag_phase4_test`，迁移到 0031；本脚本本身不创建、迁移或清空。
- [ ] 设置当前 PowerShell 会话的 `TEST_DATABASE_URL`，确认无四个 libpq 重定向变量；不输出变量值。
- [ ] 运行：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/integration/test_numeric_history_demo_release.py -q
```

- [ ] 验证空库／错误版本／非空库、种子回滚、C 包上下文固定、停止后任务收敛、权限、幂等、取消、历史和 PDF 字节；确认退出后端口释放和父环境不变。

### S5.3 新阶段五实际演示

- [ ] 重新准备全新空隔离库状态和全新输出目录；先执行 dry-run，再执行：

```powershell
.\backend\.venv\Scripts\python.exe scripts/run_numeric_history_demo_release.py `
  --source-dir outputs/synthetic-prediction-cases/2026-09-15-switch-v2 `
  --legacy-bundle outputs/numeric-acceptance/2026-09-15/model-v2/bundle.json `
  --history-bundle outputs/numeric-history-integration/2026-09-16-v1/bundle.json `
  --renderer outputs/numeric-history-renderers/2026-09-20-v1/38f18749e2ceed29eb12273c66f2a056e701f01db01b3ada7a5582e433357558/manifest.json `
  --acceptance-result outputs/numeric-history-acceptance/2026-09-20-v2/result.json `
  --output outputs/numeric-history-demo-release/2026-09-20-v1 `
  --apply --allow-external-llm
```

- [ ] 在实际页面完成 C 包两病种和历史不足场景；覆盖一次幂等重放、一次真实 queued 取消、非所有者 404、错误角色 403、历史读取和 PDF 下载字节核对。不得临时切 B 包或修改阈值。
- [ ] 以 Ctrl+C 正常停止，确认 `release.json.status='stopped'`、无 queued/running、所有拥有进程关闭、端口空闲、父环境恢复；任何未收敛或清理错误均保留为 `failed`，不手改结果。
- [ ] 阶段四 `2026-09-20-v2` 只作为门禁；阶段五成功必须引用本次新的 release 记录、数据库事实和归档原件。

### S5.4 整仓阶段出口回归

- [ ] 从 `backend` 运行项目规定的非 integration／e2e 回归并要求 0 failed：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests ..\scripts\tests --ignore=tests/integration --ignore=tests/e2e
```

- [ ] 阶段五未改前端时，不重复把历史前端记录写成本次通过；实际浏览器验收已覆盖页面。若实施过程中出现前端 diff，必须补跑：

```powershell
cd frontend
npm run test:unit
npm run test:contracts
npm run build
```

- [ ] 运行 `git diff --check`，检查文档链接、固定 SHA、命令、状态和实际输出一致。

### S5.5 文档与阶段完成记录

- [ ] 在 `docs/OPERATOR_REPORT_OPERATIONS.md` 写入可复制的 dry-run／apply／停止命令、空库和 0031 前提、失败记录解释、不得用于生产／临床的边界。
- [ ] 新建结果文档，只记录本次实际执行的 release id、冻结摘要、计数、权限／取消／历史／PDF 事实、回归结果、失败／跳过和 `clinical_status=not_assessable`；不写 URL、token 或正文。
- [ ] 更新阶段五设计、当前计划和总领文档状态；真实资料路线继续开放，列出真实数据到位后的重新训练／评价／接入／发布步骤。
- [ ] 完成最终自审：无未决标记，无未说明失败，无把 skipped 写成 passed，无把合成工程指标写成临床结论。
- [ ] 停止并向用户报告阶段五是否满足出口。仍不自动提交或推送；等待用户单独指令。

## 3. 计划覆盖矩阵

| 设计要求 | 实施位置 |
| --- | --- |
| 本机、loopback、固定隔离库和 0031 | S1.5–S1.6、S2.1–S2.2、S5.2 |
| 冻结来源、B/C、renderer、阶段四权威验收 | S1.3–S1.4、S5.1／S5.3 |
| 默认零副作用与双开关授权 | S1.5–S1.6 |
| 严格发布记录和数据最小化 | S1.1–S1.2、S4.3–S4.4 |
| 空库、事务种子、无迁移／清理 | S2.1–S2.2 |
| C 包活动配置、进程所有权和就绪 | S2.3–S2.4 |
| 已认证浏览器和安全诊断 | S3.1–S3.2 |
| 停止受理、任务收敛和回退 | S3.3–S3.4 |
| 工程评价、LLM审计、权限、历史、PDF | S4.1–S4.2 |
| 新阶段五实际验收与整仓出口 | S5.1–S5.4 |
| 运维、总领状态和真实资料交接 | S5.5 |

## 4. 明确排除项

- 不生产部署、不开放远程访问、不注册系统服务或定时任务。
- 不新增前端模型选择、页面样式、API 字段、数据库迁移、疾病或预测任务。
- 不重训、调参、重新索引、下载模型或替换冻结制品。
- 不将 B 包设为自动备用，不在 C 包失败后静默降级。
- 不自动恢复强杀后的会话，不接管遗留 worker，不清理失败输出或数据库事实。
- 不计算或宣称临床有效性，不因后续收集数据自动训练或发布。

## 5. 每步交付模板

每次完成 S1–S5 中的一步后，回复按同一结构给出：

1. **结论：** 该步通过／未通过，是否可以进入下一步。
2. **修改：** 精确文件和行为。
3. **验证：** 实际命令、passed／failed／skipped 数量及关键事实。
4. **限制：** 未执行条件、外部调用、数据库或真实数据边界。
5. **剩余步骤：** 按 S 编号列出所有未完成步骤。
6. **下一步：** 只写一个明确步骤及其入口条件。
