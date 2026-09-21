# 阶段五：本机隔离工程演示发布实施与总验收记录

日期：2026-09-21。范围：阶段五 S1–S5。依据：[阶段五设计](../specs/2026-09-20-prediction-model-refactor-phase-5-local-demo-release-design.md)、[阶段五计划](../plans/2026-09-20-prediction-model-refactor-phase-5-local-demo-release.md)、[总领文档](../specs/2026-09-09-prediction-model-refactor-master-design.md)。

## 结论口径

阶段五五步全部执行完毕，**实施 5／5**。S5.3 在全新输出目录执行了一次获准的 `--apply --allow-external-llm` 会话（`outputs/numeric-history-demo-release/2026-09-21-v5`），`release.json` 为 `status=stopped`、无诊断、无清理错误，退出码 0。

**这不是临床有效性结论**：全程 `is_synthetic=true`、`clinical_validity_claim=false`、`clinical_status=not_assessable`、`production_enabled=false`。不授权业务库迁移、模型发布或生产部署。

活动配置未改变：`NUMERIC_MODEL_BUNDLE` 仍指向原有配置，C 包只在演示会话的子进程环境中临时生效；停止监督进程即完成回退。未修改 `.env`、数据库结构、API 契约或前端组件。

## 实际演示事实（S5.3）

会话 `run_id=20260921T040904Z`，`started_at=04:10:32Z`、`stopped_at=04:12:46Z`（约 2 分 14 秒），`git_commit=2959723bb33eee615bf6dd8eec336062a6803032`。

**进程生命周期（`process-events.jsonl`）**：API → 前端 → report worker／PDF worker → 浏览器依次就绪；停止顺序为 API → 浏览器 → 前端 → report worker → PDF worker，五个退出码均为 0，端口 15173／18060 释放，父进程环境恢复。

**工程评价（`release.json.metrics`，全部由数据库／审计／文件事实复算）**

| 类别 | 实际值 |
| --- | --- |
| 接单 | 请求 2、幂等重放 1、拒绝 0 |
| 任务 | completed 3、cancelled 1，其余 0；未收敛 0；`phase_timeout` 0 |
| 时限 | 五个阶段各 3 个样本；rendering 合计 13452 ms 最长，persistence 4482 ms，model_loading 6671 ms |
| LLM 审计 | `invocation_started` 3、`task_finished` 9、闭合报告 3、未闭合 0 |
| 权限 | 非所有者 404 = 1、错误角色 403 = 1、疾病权限拒绝 0 |
| 历史 | 核验 3 份、不一致 0 |
| PDF | ready 1、failed／missing／corrupt 0、下载 1、字节核验 1、SHA 不一致 0 |
| 身份 | 来源／B 包／C 包／renderer／阶段四验收／代码提交六类全部匹配 |

**会话自检（`session-checks.json`）**：同源请求、三个种子身份各一次 —— 非所有者 404、错误角色 403、幂等重放（同一 Idempotency-Key 返回同一报告）与一次真实 queued 取消，全部按预期成立后会话才宣告就绪。

**独立复核**：演示结束后另行只读重算归档原件 —— `reports/4/…/document.pdf` 288261 字节与 `pdf_sha256` 一致、以 `%PDF-` 开头、`renderer_sha256` 等于冻结身份 `38f18749…`；`report_pdf_deliveries` 计数为 1，与 `delivery_count` 一致。三份完成报告的 `generation_fingerprint_version` 均为 `v6`，取消报告为 `null`。

**演示期间发现并修复的四个缺陷**（全部由本次实际运行暴露，前三个属 S2、第四个属 S3）：

| 运行 | 失败码 | 根因 | 修复 |
| --- | --- | --- | --- |
| `2026-09-21-v1` | `owned_service_start_timeout` | 前端以仓库根为工作目录启动，Vite 服务的是工作目录，根目录没有 `index.html`，`GET /` 恒为 404 | 改用 `frontend/` 为工作目录，并补 cwd 回归断言 |
| `2026-09-21-v2` | `demo_browser_child_failed` | 种子账号邮箱用 `@test.invalid`，被响应模型 `EmailStr` 判为保留域名，`/auth/me` 返回 500，前端清除令牌退回登录页 | 种子身份抽为常量并改用 `@example.com`，补 `UserOut` 校验回归 |
| `2026-09-21-v3` | 未确认停止 | 等待循环只读 `browser.is_connected()`，该值是本地缓存标志，既不访问驱动也不派发事件，关窗永远无法被感知 | 见下 |
| `2026-09-21-v4` | 未确认停止 | 仅注册 `page.on("close")` 不足以生效：同步 API 只在自己被调用期间派发事件 | 放弃纯轮询，改为带派发的有界等待并捕获浏览器关闭 |

第四项的最终修复：等待循环改为 `page.wait_for_timeout(poll_ms)`（该调用会派发已排队事件），并捕获 `playwright.sync_api.Error` 作为「窗口已消失」的信号。用真实 Playwright 验证：外力终止 Chromium 时循环在 12 次轮询内以 `TargetClosedError` 结束，且 `page.close`／`context.close`／`browser.disconnected` 三个事件全部触发；而只读 `is_connected()` 的旧循环在同一场景下始终返回 `True`。

**保留的失败产物**：`2026-09-21-v1`（含进程事件）、`-v2`（含 `browser-failure.json` 与截图，页面 URL 脱敏为 `/login`）、`-v3`、`-v4`（`release.json` 保持 `running`，只读 `--inspect-release` 报告 `unconfirmed_stop=true`）。均按设计原样保留，未覆盖、未原地改写。

## 隔离集成（S5.2）

操作者准备：`surgery_rag_phase4_test` 先以 `pg_dump` 备份至 `outputs/numeric-history-demo-release/surgery_rag_phase4_test-phase4-leftover-2026-09-21.dump`，再重建为空库、安装 `vector`／`uuid-ossp`／`pg_trgm`、`alembic upgrade head` 至 **0031**。

`tests/integration/test_numeric_history_demo_release.py` 在该空库上实跑 **8 passed**：数据库身份／迁移／空表门禁、事务种子整体可见与整体回滚、种子失败回滚、空库无在途工作、未触动范围评价为零、范围外记录失败关闭、已保存摘要重算、归档原件复读与篡改检测。

该模块的用例现在各自在自身事务内把业务表恢复到空库状态，因此不依赖此前运行过哪个模块；`test_actual_database_identity_migration_and_empty_business_tables` 仍按设计断言操作者准备的空库前提，需按文档单独运行该模块。

## 整仓回归（S5.1／S5.4）

- 阶段五定向：schema、发布模块、CLI、浏览器与阶段四 runner 联合 **264 passed／0 failed**。
- 默认 dry-run：退出 0、`status=dry_run`、`database_connected=false`、`services_started=false`、未创建输出目录。
- 整仓非 integration／e2e 回归：**0 failed / 2517 passed / 59 skipped / 24 subtests passed（982.20 秒）**；跳过项为需显式提供原始 DOCX 资料的用例与一项符号链接用例，与原口径一致。
- `git diff --check` 通过（仅既有 LF/CRLF 提示）。

### 演示提交与当前 HEAD 的差异（如实说明）

实际演示运行于提交 `2959723bb33eee615bf6dd8eec336062a6803032`，`release.json.identities.git_commit` 即此值，`identity.git_commit_matches` 为真。此后另有两次提交，其中**只有一处改动生产代码**：`scripts/numeric_history_demo_browser.py` 的 `session_ended_errors()` 增加「首次导入失败后丢弃半导入的 `playwright` 层级并重试一次」的兜底（整仓回归中另一测试模块向 `sys.modules` 安装 mock 后移除，会使该函数静默返回空元组、把安全防护解除）。

该改动对本次运行**不可能产生影响**，两个分支均可排除：若本次停止由 `page.on("close")` 处理器触发，则循环在 `stop_event.is_set()` 处退出，`close_errors` 自始至终未被使用；若由异常触发，则说明异常确实被捕获，亦即当时防护已装上，与改动后的行为一致。演示子进程是全新进程，`playwright` 首次导入即成功，重试分支不可达。

其余两次提交只改测试；当前 HEAD 见提交历史。

## 已知失败与限制（如实保留）

- **非阶段五的既有失败 2 项**（在 S4 首次运行整仓集成时暴露，未在本阶段修改）：
  - `scripts/check_operator_report_archives_readonly.py` 把 `schema_ready` 硬编码为 `alembic_version == "0026"`，而 schema 自阶段四起即为 0031，该只读门禁脚本在当前 schema 上永远不会就绪；`tests/integration/test_report_archive_operations.py::test_gate_verifies_files_without_mutation` 因此失败。
  - `tests/integration/test_report_pdf_worker.py::test_real_chromium_worker_publishes_original_without_report_mutation` 直接取 `os.environ["REPORT_TEST_RENDERER_MANIFEST"]` 而无 skip 守卫，未设该变量时必然 KeyError。
- **疾病权限拒绝在首版固定为 0**：冻结来源的两个病种均处于 `operator_enabled`，要产生真实拒绝必须在演示中临时停用病种并改写业务行；首版不做，该计数如实保留为 0。
- **`admission` 块只描述会话自己发起的固定检查**（2 次请求），操作者在页面生成的报告由 `jobs` 块统计，两块读数天然不同。
- **浏览器关闭事件依赖等待循环派发**：已由 S5.3 实跑与独立探针验证；若未来更换 Playwright 版本，须重新确认 `page.wait_for_timeout` 仍会派发事件。
- **`outputs/` 仍被 Git 忽略**，用户已接受制品丢失后无法复现既有验收的风险；本阶段不新增外部备份策略。
- **演示的数据库行不再可复算**：本机只有一个可丢弃隔离库，而集成测试的既有 fixture 在每次用例开始时会 TRUNCATE 业务表并提交（这是阶段四就有的约定）。演示结束后为验证上面两处既有失败的修复，运行了 `test_report_archive_operations.py` 与 `test_report_pdf_worker.py`，该库因此被清空，v5 的 `users`／`operator_cases`／`ai_reports`／`report_pdf_archives` 行不再存在，且未事先单独备份。
  影响范围：`release.json` 中的工程评价是会话结束时**从这些行复算并冻结**的结果，仍然有效；`archive/` 中的归档原件完好（288261 字节、SHA-256 `7cf1f604…` 与记录一致，已再次核对）。不再能做的只是「事后重新查询这些行」。
  若要为将来的演示保留可复算的库快照，应在会话结束后立即 `pg_dump`，与本次对阶段四遗留所做的处理一致。

## 制品与记录

- 成功验收输出：`outputs/numeric-history-demo-release/2026-09-21-v5`（`release.json`、`session-checks.json`、`process-events.jsonl`、`archive/`）。
- 失败记录：`2026-09-21-v1`、`-v2`、`-v3`、`-v4`。
- 隔离库备份：`outputs/numeric-history-demo-release/surgery_rag_phase4_test-phase4-leftover-2026-09-21.dump`。
- 本机过程记录：`.tmp/run-s5-demo.py`、`.tmp/s5-*.log`。

`outputs/` 与 `.tmp/` 按仓库既有规则不入 Git；源码提交不会自动包含这些验收产物。

## 真实资料交接

阶段五完成**不关闭真实资料路线**。真实资料到位后至少需要：确认主体与时间线、冻结任务与标签、建立正式样本与独立分区、重新训练与比较、由专业人员复核临床阈值、生成新的模型／来源／评价版本、重做阶段四接入验收，并为目标部署环境单独审批发布、容量、备份与回退。旧合成 C 包及其历史报告保持原身份，不升级为真实模型。

## 三类结论分开表述

1. **发布控制是否正确**：是。默认零副作用，双开关授权，冻结身份与 Git 提交门禁、隔离库与 0031 前提、输出目录新建、停止后回退与端口释放均按设计执行并有实际证据。
2. **演示链路是否可运行**：是。真实 API／worker／检索／DeepSeek／浏览器／PDF 链路在隔离库上实际跑通，权限、幂等、取消、历史与归档语义保持。
3. **临床有效性是否可评价**：**不可评价**，固定为 `not_assessable`。本阶段不产生也不宣称任何临床结论。
