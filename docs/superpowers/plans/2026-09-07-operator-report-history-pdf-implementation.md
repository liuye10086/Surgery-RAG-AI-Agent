# AI 操作者第 7～9 项合并改造 Implementation Plan

## 实施交付状态（2026-09-07）

- [x] P0：已确认 main 基线及用户直接执行授权。
- [x] A1～A5：保存读取、审计及历史工作区完成。
- [x] B1～B6：PDF 归档、交付、删除/恢复及前端完成。
- [x] C1～C3：本机真库、浏览器/PDF、运维交付完成。
- [x] P1：最终检查完成，保留 main 未提交改动。
- [ ] 生产迁移、目标 OS 制品、Linux 联合容量、监督服务和 postflight：待获准部署窗口执行。

实际命令、57 项真库/1135 项后端/69 项前端等验收结果及过程调整见 [实施记录](../notes/2026-09-07-operator-history-pdf-execution-log.md)。下文保留原计划过程步骤供追溯，不把未留存的逐条红灯过程补记为已执行；Git 检查点未自动提交。


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐报告保存审计、稳定历史读取和永久 PDF 原件归档，使现有第 1～6 项生成链路与历史/下载/删除/恢复形成完整生命周期。

**Architecture:** 保留 ReportDocument/EvidenceBundle/原子发布和现有模型 worker。新增统一历史读取投影、受限生成审计及独立 PostgreSQL PDF 任务，原件写入私有持久目录；下载只交付已校验原件，删除通过数据库事务和持久清理任务协调。

**Tech Stack:** 现有 Python 3.11、FastAPI、Pydantic v2、SQLAlchemy、Alembic、PostgreSQL 18、Playwright/Chromium、multiprocessing spawn、Vue 3/TypeScript/Pinia/Element Plus、pytest/Vitest。

## Global Constraints

- 设计依据：[批准设计](../specs/2026-09-07-operator-report-history-pdf-archive-design.md)，用户已明确“设计通过，开始编写实施计划”。后续用户已批准实施：直接在 main 分支、本会话逐项执行。
- 范围：AI 操作者、脂肪肝与 AD、电脑端；衔接已经完成的附录 12 项及主流程第 1～6 项。
- 首次成功导出的 PDF 永久归档，此后下载同一份文件。
- 主动删除报告时清理对应 PDF；删除病例仍保留报告与 PDF。
- 旧报告按原算法验证；缺少旧哈希标为 unverifiable，允许查看已保存内容，显示“历史资料未完整保存，无法验证完整性”。
- 不补签、不回写、不重新解析标准。未知文档或指纹版本失败关闭。
- PDF 的 hash、下载次数、尝试记录等运行元数据放独立表，不加入原报告生成指纹，也不因下载更新报告内容/生成完成时间。
- 原件不是缓存：不能 TTL/LRU 淘汰。
- 所有新 UI 遵循 `docs/DESIGN_SPEC.md` 全部规范，复用暖杏蓝、260/64px 侧栏、56px 顶栏、880px 内容区、44px 交互区域和现有 CSS 变量。
- 新报告最大输入仍为 1～10 次访视、每次最多 30 指标；10×30 为展示压力夹具，业务输入仍受病种目录约束。
- 现有合成模型、未校准分数和 AD evidence-only 限制保持不变；本任务不训练模型、不替换标准、不添加新医学推断。
- 代码基线 `main / 7a2e3e7`，当前 Alembic head `0024`。执行前再核对；不读取生产 `.env`、不执行生产迁移、不推送或部署。
- 后续用户明确要求直接在 main 分支执行，覆盖工作树建议；保留已有设计与计划文档，不自动提交、推送或部署。
- 当前没有并行代理授权。按任务顺序执行；只有用户选择子代理方式才使用 subagent-driven-development。
- 根目录 `C:\Users\86182\Desktop\Surgery RAG-Agent`。下文文件均为相对该根目录的精确位置；命令注明工作目录。Git 消息为检查点建议，提交方式服从用户后续指令，不自动提交其他改动。

## 1. 计划入口与依赖

| 计划 | 任务 | 交付 |
|---|---|---|
| [历史与审计](2026-09-07-operator-report-history-audit.md) | A1～A5 | 保存身份、读取隔离、审计、游标、历史工作区 |
| [PDF 归档](2026-09-07-operator-report-pdf-archive.md) | B1～B6 | 持久 schema、受理/worker、存储、下载、清理、前端 |
| [集成与发布门禁](2026-09-07-operator-report-archive-validation.md) | C1～C3 | 真实数据库、E2E/PDF、故障与运维 |

顺序：`P0 → A1 → A2 → A3 → A4 → A5 → B1 → B2 → B3 → B4 → B5 → B6 → C1 → C2 → C3 → P1`。

A2 的 schema 在 A3 worker 写审计前完成；B1 schema 在所有 PDF 接口启用前完成；B5 删除闭环与 B6 前端更新未完成前不得开放 B2 归档受理。单个任务可独立验收不表示半成品可发布。

## 2. 计划阶段锁定的接入细节

1. 统一历史端点 `GET /operator/report-history`，与既有 `GET /operator/reports` 分开，避免整数 `/{report_id}` 路由与字符串 `history` 歧义；新页使用 items/next_cursor/has_more，旧列表保留轻量 offset 兼容。
2. `AIReport.anonymous_case_code` 改为只解析 input_snapshot；页面、PDF 标题、旧版 fallback 共用 `saved_report_identity`。报告没有匿名编号就显示报告编号，绝不访问当前病例关系。
3. `get_report` 不先 `ReportOut.model_validate(orm)`；先收集原始保存字段、校验，再构造安全 DTO。`ReportDetail` 不再错误继承与详情 API 不一致的列表字段集合，定义公共 identity/meta 类型供两者复用。
4. 新审计任务 last phase、失败 phase、事件序号与总字节计数属于 job；不是改写最终 ReportDocument 的运行补丁。终态记录事件和报告状态一起提交。
5. `supervise_execution` 当前丢弃 error.phase 且 ExecutionOutcome 没有 phase；A3 同时修 child IPC、父监督返回及 `_terminal`，不能只补数据库列。
6. PDF 幂等复用 `operator_idempotency_keys`，增加 `prepare_report_pdf/report_pdf_attempt` 与 `retry_report_pdf/report_pdf_attempt` 两组合法 scope/resource_type；不另造第二套请求幂等表。归档行按 report_id 唯一，多个新 key 也复用同一活动尝试/原件。
7. PDF source hash 同时覆盖 v2 身份和实际导出保存数据；无原始指纹旧版记录 export source hash，但标明 legacy unverifiable，不能升级为原报告完整性 valid。
8. PDF 输出不走现有 8 MiB Publication IPC；子进程写预登记候选路径，只回传有界元数据。IPC 包含 PDF bytes 会放大内存且撞限。
9. 字体/Chromium 精确版本由实际安装制品生成 manifest 并校验，计划不编造 SHA。manifest 创建是制品构建任务，运行期间不重新计算并接受漂移。
10. 旧下载计数保留在报告字段，新增交付表记录新次数；详情/列表返回旧基数 + 新增值，不再 UPDATE `ai_reports.download_count`。
11. 删除文件不能与数据库形成原子事务。204 只表示报告删除且当前文件清理完成；202 表示报告已不可读取但清理在补偿中。异常不能被前端 catch 当作“用户取消”。

## 3. 状态、锁与事务合同

### 3.1 状态分离

| 对象 | 状态 |
|---|---|
| ai_reports | 保留 generating/completed/failed/cancelled |
| report_generation_jobs | 保留 queued/running/completed/failed/cancelled；增加 last_execution_phase/failure_phase |
| report_pdf_archives | queued/rendering/ready/failed/missing/corrupt；无行由 API 投影 not_requested |
| report_pdf_attempts | queued/running/completed/failed；删除直接级联至清理任务 |
| report_file_cleanup_tasks | pending/running/settling/done；失败重试为 pending 并保留 code/count |

ready→missing/corrupt→ready 仅是原件存储健康变化；`published_attempt_id/pdf_sha256/size_bytes/page_count/archived_at/source_sha256/renderer_sha256` 一经发布不可变，恢复不能替换文件身份。第一次发布失败允许显式新 attempt；已有 published_attempt_id 时 retry 一律拒绝。

### 3.2 统一加锁顺序

- 生成原路径维持 `generation job → report → audit event`。
- PDF 受理/领取需要全局配额锁时先取它，然后 `report → archive → attempt`。
- PDF 发布/故障/下载只取 `report → archive → attempt` 中所需锁，不反过来。
- 报告删除为 `generation job（若存在）→ report → archive → attempt`；清理登记由同事务触发器执行，不获取全局配额锁。
- worker 不能先锁 attempt 后等 report。领取时先发现候选，再锁其 report，重查 archive/attempt 状态；锁不到用 SKIP LOCKED 或有界回退，不持其他行锁等待。
- 所有状态判断在持锁后用数据库时钟重查。连接 5 秒、语句 5 秒、锁 3 秒、池 5 秒沿用现有有界 factory；死锁/连接不确定先 rollback/读取事实，不覆盖已提交终态。
- 浏览器渲染、文件读取/hash、同步清理均在短数据库事务之外；提交后文件交付只持打开文件句柄。

### 3.3 配置初值

```python
REPORT_PDF_ENABLED: bool = False
REPORT_PDF_ACCEPTING: bool = False
REPORT_PDF_CONCURRENCY: int = 1
REPORT_PDF_QUEUE_LIMIT: int = 20
REPORT_PDF_USER_ACTIVE_LIMIT: int = 2
REPORT_PDF_QUEUE_SECONDS: int = 600
REPORT_PDF_RUN_SECONDS: int = 120
REPORT_PDF_LEASE_SECONDS: int = 45
REPORT_PDF_HEARTBEAT_SECONDS: int = 10
REPORT_PDF_SWEEP_SECONDS: int = 15
REPORT_PDF_MAX_BYTES: int = 64 * 1024 * 1024
REPORT_PDF_MAX_PAGES: int = 200
REPORT_AUDIT_MAX_EVENTS: int = 256
REPORT_AUDIT_MAX_EVENT_BYTES: int = 256 * 1024
REPORT_AUDIT_MAX_FIELDS: int = 1024
REPORT_AUDIT_MAX_TOTAL_BYTES: int = 8 * 1024 * 1024
REPORT_ARCHIVE_ROOT: str = ""
REPORT_PDF_RENDERER_MANIFEST: str = ""
REPORT_HISTORY_CURSOR_SECRET: str = ""
```

空 root/manifest/secret 时对应新功能 fail closed；测试通过 monkeypatch 提供临时目录/虚构专用 secret。secret 至少 32 个随机字节，不复用 JWT 密钥；不开启功能时不能因此阻断旧报告读取。64 MiB/200 页是新增归档资源上界，C2 必须证明已批准最大报告全部可容纳，不通过裁剪报告满足限制。

## 4. 跨模块接口索引

所有 schema 定义在拥有该任务的计划中；字段名不得在消费者处另起名字。

| 生产者 | 接口 | 消费者 |
|---|---|---|
| A1 | `saved_report_identity(report_id: int, snapshot: object) -> SavedReportIdentity` | ORM、列表、详情、PDF |
| A1 | `read_owned_report(db, user_id: int, report_id: int) -> ReportReadDetail` | API、B2/B3/B4 |
| A1 | `build_pdf_source(detail: ReportReadDetail) -> PdfSource` | B2 受理、B3 执行、B4 下载 |
| A2/A3 | `append_generation_audit(db, claim, event: GenerationAuditEvent) -> bool` | worker IPC 回调 |
| A4 | `list_report_history(db, user_id, filters: HistoryFilters, cursor: str | None, limit: int) -> ReportHistoryPage` | 历史路由 |
| B1 | `PdfArchiveStatus`, `PdfClaim`, `PdfCandidate`, `PdfError` | B2～B6 |
| B2 | `prepare_pdf_archive(factory, user_id, report_id, key, *, retry=False) -> PdfArchiveStatus` | POST 接口 |
| B2 | `read_pdf_archive_status(db, user_id, report_id) -> PdfArchiveStatus` | GET、B6 |
| B2/B3 | `claim_pdf(db, owner) -> PdfClaim | None`；`heartbeat_pdf(db, claim) -> bool`；`publish_pdf(db, claim, candidate) -> bool`；`fail_pdf(db, claim, phase, code) -> bool` | PDF worker |
| B3 | `render_pdf_candidate(source: PdfSource, manifest_path: Path, target: Path, emit) -> PdfCandidate` | PDF child |
| B3 | `ArchiveStorage.open_verified(key, sha256, size_bytes) -> BinaryIO` | B4 下载、B5 恢复 |
| B4 | `prepare_delivery(factory, storage, user_id, report_id, delivery_id) -> PdfDelivery` | 下载路由 |
| B5 | `delete_owned_report(factory, user_id, report_id, storage) -> DeleteReportResult`；`run_cleanup_once(factory, storage) -> int` | DELETE、sweep |
| B5 | `restore_pdf_original(factory, storage, report_id, backup_file: Path) -> bool` | 维护 CLI，无普通用户恢复端点 |
| A5/B6 | `useReportHistoryStore`、`useReportArchiveStore` | OperatorView 和历史/详情组件 |

## 5. 迁移分配与数据保留

| revision（执行前复核） | 文件 | 内容 |
|---|---|---|
| 0025 | `backend/alembic/versions/0025_report_history_audit.py` | last/failure phase、受限审计表、历史复合/匿名编号索引 |
| 0026 | `backend/alembic/versions/0026_report_pdf_archives.py` | archive/attempt/交付/清理表、最小报告删除墓碑、幂等作用域、发布不可变和删除清理触发器 |

ORM 仍在 `backend/app/db/models.py` 注册，避免引入 Base/import 注册问题；业务服务按职责拆文件。同步 `database/schema.sql` 和 `scripts/check_database_readonly.py`、现有 Alembic/schema 契约测试；不能仅让新业务测试通过而忽略当前 head 假设。

旧行 last/failure phase 保持 NULL；不根据 terminal 猜测过去 phase。审计事件不补造。新归档表初始为空，不扫描业务库批量生成 PDF。0025/0026 downgrade 在存在审计/归档/交付/清理/对应幂等数据时拒绝，生产应用回滚保留新增 schema。

## 6. Task P0：实施前基线与隔离

**Files:** 只读 AGENTS、DESIGN_SPEC、批准设计、四份计划、Git/Alembic；执行时创建隔离 checkout，保留本次文档。

- [ ] **Step 1：确认代码与迁移头。** 根目录运行：

```powershell
git status --short
git rev-parse HEAD
git branch --show-current
```

backend 工作目录单独运行 `python -m alembic heads`，只读代码侧迁移图，不连接数据库。预期单 head 0024；如果后续已有迁移，统一调整两份迁移编号及所有测试预期后再实施。

- [x] **Step 2：执行位置确认。** 按用户后续明确指令直接使用 main，未创建工作树；批准文档均保留。
- [ ] **Step 3：运行已有基线。** 根目录：

```powershell
python -m pytest backend/tests --ignore=backend/tests/integration --ignore=backend/tests/e2e -q --tb=short
```

frontend 目录：

```powershell
npm run test:unit
node --test tests/longitudinal-report-ui-contract.test.mjs
```

预期 exit 0；旧记录 1081/52 只作历史参考，记录本次真实数目，不拿历史数替代运行结果。

- [ ] **Step 4：登记基线结果和已有失败。** 新建 `docs/superpowers/notes/2026-09-07-operator-history-pdf-execution-log.md`，记录 SHA、命令、输出摘要、环境边界。未跑真库写未执行，不写通过。

## 7. Task P1：交付核对

**Files:** 四份计划、批准设计、核查文档、执行记录、实际变更清单。

- [ ] **Step 1：按覆盖表核对已完成任务，不只汇总测试个数。**

| 设计节 | 对应任务 |
|---|---|
| 5.1～5.2 保存/身份/受限读取 | A1、A2、B4 |
| 5.3～5.4 历史查询/页面/旧版 | A4、A5 |
| 6 失败阶段和已确认审计 | A2、A3 |
| 7.1 API/前端体验 | B2、B4、B6 |
| 7.2～7.4 schema/存储/永久原件 | B1、B2、B3、B4、B5 |
| 7.5 资源/字体/日志 | B3、C2、C3 |
| 8.1 交付计数 | B1、B4 |
| 8.2 删除/账号级联/补偿 | B1、B5、B6、C1 |
| 8.3 备份/删除记录/恢复 | B5、C3 |
| 9 发布/回滚 | C3 |
| 10 全部验收矩阵 | C1、C2、C3 |

- [ ] **Step 2：运行 C1～C3 定义的最终命令并记录实测结果。** 不用 skip 作为新关键链路验收完成；目标主机未测则明确生产待验收。
- [ ] **Step 3：文档状态分别写仓库完成/隔离验收/生产未部署。** 当前第 7～9 项状态仅在对应任务与门禁确实通过后更新。
- [ ] **Step 4：检查 diff。** 根目录执行 `git diff --check`，检查无 .env、数据库备份、真实病例、token、PDF 运行文件和本机路径进入提交。
- [ ] **Step 5：按用户选择提交策略处理 Git；交付未完成生产门禁。** 建议最终主题 `feat: archive operator report PDFs and harden history lifecycle`，不自动推送或部署。

## 8. 本轮计划自审记录

编写阶段只修改 Markdown。已按批准设计逐节检查任务覆盖、生产者/消费者名称、状态边界、迁移依赖、旧版兼容与删除补偿；没有执行本计划的业务任务。后续实施任务用复选框和实际日志追踪，不能把计划写完标成业务完成。

本轮文档检查：16 个任务标识唯一（14 个模块任务及 P0/P1），本地交叉链接均存在；29 个 Python 代码块经 AST 语法检查、4 个 TypeScript 代码块经 TypeScript 解析器检查通过，UTF-8/尾随空白及 `git diff --check` 通过。这是计划语法与结构检查，不是业务代码运行、SQL真库验证或前端类型/构建验收。

自审修正：翻页不能在首屏刷新期间并发开始；发布字段的 CHECK 显式处理 NULL；父进程返回真实错误阶段；账号级联保留清理任务；无 PDF 报告删除也保留最小墓碑，供恢复旧备份时重放删除事实。审计容量配置只能在数据库硬上界内收紧，提高上界必须配套迁移与资源验收。
