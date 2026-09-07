# AI 操作者第 6 项完整预测报告 Implementation Plan
> 执行状态（2026-09-07）：仓库任务已完成并通过本机隔离验收，实际任务状态、命令与证据见 [执行记录](../notes/2026-09-07-operator-report-execution-log.md)。下文保留批准时计划；建议的逐项提交被用户要求的最终一次提交取代。涉及目标 Linux 容量及生产发布的检查仍在部署窗口执行。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付内容完整、来源固定、可恢复查询且不会错误发布完成状态的脂肪肝与 AD 报告。

**Architecture:** 使用 ReportDocument v1 固化展示事实，以 PostgreSQL 持久任务管理受理、取消、租约和终态。独立 worker 运行可终止的模型子进程，网页/SSE/PDF 消费保存结果。模块 A 负责文档，模块 B 负责执行生命周期，两者共同发布。

**Tech Stack:** 现有 Python/FastAPI/Pydantic/SQLAlchemy/Alembic/PostgreSQL、multiprocessing spawn、Vue 3/TypeScript/Pinia/Element Plus、Playwright/pytest/Vitest。

## Global Constraints

- 设计依据：`docs/superpowers/specs/2026-09-07-operator-complete-report-audit-design.md`，2026-09-07 用户已批准。
- 范围：电脑端 AI 操作者，脂肪肝与 AD。
- 固定 11 章的确定性报告；不调用 LLM 创造事实或医学结论。
- 不重做第 1～5 项，不重新训练模型，不替换两份项目已批准标准，不重算或补写旧报告。
- 页面沿用 `docs/DESIGN_SPEC.md` 的暖杏蓝、Element Plus、内容区最大 880px 和既有排版变量。
- 保留 `ai_reports.status` 的四个值：`generating/completed/failed/cancelled`。
- 本期不自动重跑已经执行中断的预测。
- 关闭页面、返回病例、AbortController 断开订阅均不取消任务。
- 主阅读区使用中文；技术代码可在第 11 节伴随中文解释出现。
- 结局预测锚点使用输入快照的最后一次有效访视日期，365 天截止日期从该锚点计算。
- 年龄明确为病例录入的年龄，不根据报告打开时间自动增长。
- 旧指纹无版本或 v1 继续按原算法验证；未知新版本失败关闭。
- 当前任务只编写计划；执行时使用 using-git-worktrees 检查隔离环境，再使用 executing-plans。只有用户选择并行 agent 执行时才采用 subagent-driven-development。
- 不自动提交、推送或部署。本计划中的提交消息是建议检查点；用户授权 Git 操作时只暂存本任务明确文件，不包含其他工作。
- 所有命令中的相对路径相对于注明工作目录；项目根目录为 `C:\Users\86182\Desktop\Surgery RAG-Agent`。生产路径/环境不从测试命令推断。

## 1. 计划文件与执行顺序

| 文件 | 任务 | 交付 |
|---|---|---|
| `2026-09-07-operator-report-document.md` | A1～A6 | 强类型契约、输入审计、完整正文、指纹与网页/PDF |
| `2026-09-07-operator-report-generation-jobs.md` | B1～B7 | 固定执行上下文、持久任务、受理、worker、接口、刷新恢复、部署验收 |

执行拓扑：

```text
P0 基线与隔离
→ A1 文档契约
→ A2 输入审计
→ B1 固定版本上下文
→ A4 正文/证据渲染纯函数
→ A3 文档构建/复核并接入 A4
→ A5 文档迁移/完整性
→ B2 任务迁移/租约仓储
→ B3 幂等受理/取消
→ B4 worker/原子发布
→ B5 API/SSE/旧入口适配
→ A6 页面/PDF
→ B6 前端任务状态/路由恢复
→ B7 真库/E2E/运维
→ P1 总体验收
```

不可提前在生产启用任一半成品路径。A 的纯函数和读兼容可先合入；新报告写入只在 B 全链路通过后切换。

## 2. 计划阶段已经解决的接入细节

1. `operator_idempotency_keys` 已有用户/scope/key 唯一约束，但 CHECK 只允许病例创建。B2 将它扩展为配对合法值：`create_longitudinal_case/operator_case` 与 `create_longitudinal_report/ai_report`，不建立重复的幂等系统。
2. 标准预检会回滚只读事务。B1 将预检放入独立 session，输出可序列化固定上下文；B3 的原子写事务不调用会 rollback/commit 的旧预检工具。
3. 当前证据 `build_evidence_bundle_with_retry` 会读新 active token 并切换版本。已受理任务必须使用新的 pinned 入口，固定 ID/哈希，不能复用这种切换行为。
4. 当前 `load_disease_model_suite` 隐式读 active。B1 抽取公共 record 加载路径，新 worker 按已固定 release ID/哈希加载，继续使用原完整性检查，不复制模型加载算法。
5. API 原 readiness 会加载模型。新受理保留同样基础输入/目录/任务准入规则，以 metadata-only 检查替代反序列化模型；实际加载在 worker 限时子进程执行。失败仍形成可查询 failed 报告。
6. 实际模型能力目录小于 30 个指标。生产 E2E 使用目录允许的全部指标与 10 次访视；30 指标 × 10 访视只用于纯展示层压力夹具，不为了凑测试数放开目录。
7. 同病例活动任务使用任务表内不可变 `source_case_id`（内部追溯键、无病例外键），病例删除不会破坏任务；用户权限始终以 `ai_reports.user_id` 为准。
8. 新受理支持当前空 `model_options`；拒绝非空或未知选项，避免让“幂等请求内容不同但执行相同”成为隐含合同。旧 SSE 适配也遵循同一请求校验。

## 3. 统一接口索引

签名的具体类型在对应任务代码块定义；实现不得更名后忘记更新消费者。

| 生产者 | 接口 | 消费者 |
|---|---|---|
| A1 | `ReportDocument`, `InputAudit`, `ModelRunAudit`, `ReportGenerationContext`, `Publication` | A2～A6、B1～B6 |
| A2 | `run_audited_prediction(snapshot, adapter, suite) -> AuditedPrediction` | B4 |
| B1 | `capture_generation_context(snapshot, session_factory, registry_root) -> ReportGenerationContext` | B3 |
| B1 | `load_pinned_model_suite(context, registry_root) -> LoadedDiseaseModelSuite` | B4 |
| B1 | `build_pinned_evidence(snapshot, context, session_factory) -> EvidenceBuildResult` | B4 |
| A3 | `build_report_document(report_id, created_at, snapshot, context, prediction, model_runs, evidence) -> ReportDocument` | B4 |
| A4 | `render_report_document(document) -> str` | B4、A5 |
| A5 | `build_publication(snapshot, prediction, evidence, document) -> Publication` | B4 |
| B2 | `claim_next(db, owner) -> JobClaim | None`；`heartbeat(db, claim) -> bool`；`publish_completed(db, claim, publication) -> bool` | B4 |
| B2 | `finish_job(db, claim, status, code) -> bool`；`reap_expired(db) -> int` | B4 |
| B3 | `submit_report_job(user_id, case_id, key, request, session_factory, registry_root) -> JobAccepted` | B5 |
| B3 | `get_generation_status(db, user_id, report_id) -> GenerationStatus`；`cancel_report_job(db, user_id, report_id) -> GenerationStatus` | B5 |
| B6 | `useReportGenerationStore().submit/observe/detach/cancel/retryDetail` | OperatorView |

## 4. P0：执行前基线

**Files:** 只读 `AGENTS.md`、批准设计、本计划与两模块计划、`docs/DESIGN_SPEC.md`、Git 状态与 Alembic revision；不读取 `.env` 内容。

- [ ] 读取上述文件，按 using-git-worktrees 建立/识别隔离工作区，保留用户已有文档修改。
- [ ] 工作目录根，分别运行：

```powershell
git status --short
git rev-parse HEAD
git branch --show-current
```

- [ ] 工作目录 backend，运行代码侧迁移头查询（不连库）：

```powershell
python -m alembic heads
```

计划基线期望 `0022 (head)`；若已变化，修改 A5/B2 迁移编号与 down_revision，不能重复使用编号或建立多 head。当前计划预留 A5=`0023`、B2=`0024`。

- [ ] 运行设计 §12 的既有后端 7 文件/前端 4 文件测试，记录实际结果，不抄旧测试数量。
- [ ] 运行 `git diff --check`；将已有失败与本任务新增失败分开。执行计划过程中若新发现阻断性缺陷，先按 systematic-debugging 定位，不靠修改断言掩盖。

## 5. P1：联合验收与发布清单

**Files:** 两模块新增 tests、`docs/AI操作者流程核查.md`、本计划与实施日志 `docs/superpowers/notes/2026-09-07-operator-report-execution-log.md`。

- [ ] A1～A6、B1～B7 每项测试结果与文件 diff 审阅完毕；每项已实现才勾选。
- [ ] 工作目录 backend：

```powershell
python -m pytest tests -q
```

- [ ] 工作目录 frontend：

```powershell
npm run test:unit
node --test tests/longitudinal-report-ui-contract.test.mjs
npm run build
```

- [ ] 工作目录根：

```powershell
python -m pytest scripts/tests/test_check_operator_report_generation_readonly.py -q
git diff --check
```

- [ ] 按 B7 仅在显式隔离 `_test` 数据库运行真实 PostgreSQL/E2E；必须执行到断进程、失租约、取消竞争等用例。关键测试 skip 不算通过。
- [ ] 按 A6/B7 逐页验证普通/极限 PDF，并保存截图/页数/结果；HTML 契约不能代替实际 PDF。
- [ ] 按 requesting-code-review 技能完成有依据的实现审查；只修本范围问题。
- [ ] 更新原流程核查第 6 项为真实完成范围，仍分别列出仓库验收与目标环境门禁。不把未来模型校准或临床验证写为已完成。
- [ ] 执行日志逐项记录：提交/工作区基线、命令、实际通过/失败/跳过数量、环境、截图文件、未达门禁。禁止保存 token/数据库 URL/临床正文。
- [ ] 发布是单独操作，按 B7 的具体清单进行。未经目标环境验收只可写“仓库实现完成，生产待验收”。

## 6. 设计覆盖与计划审查映射

| 设计要求 | 任务 | 必须覆盖的证据 |
|---|---|---|
| 八项原缺口、额外语义缺口 | A1～A4、A6 | 11 章、人口学/输入审计/完整访视、上下文、中文原因、参考信息等量 |
| 标准/模型固定，接入旧能力 | B1、B3 | active 切换、已固定标准更新/撤销、目录漂移、无跨事务 rollback |
| 强类型与完整性 | A1、A5、B4 | schema 错误、v1/v2 指纹、跨批次、篡改、未知版本拒绝 |
| 幂等、容量、状态与租约 | B2～B5 | 同 key/不同请求、同病例双任务、租约/期限、CAS=False 无 completed |
| 刷新、断线、取消、详情空档 | B5、B6 | route 恢复、EOF、乱序、401/404/429、完成读取失败、关闭非取消 |
| 只读历史与删除 | A5、A6、B2、B3 | 老报告不重算、来源病例删除后执行、活动报告不可删、owner 404 |
| 真库、极限 PDF、运维与切换 | A6、B7、P1 | `_test` 隔离、真进程故障、worker 监督/容量/期限、legacy generating 处置、保留数据回滚 |

计划编写完成后进行占位词、接口一致性、文件存在性和设计覆盖自检。这里只记录计划状态，不将上述实施复选框提前标记完成。
