# 活动任务登记

本文件是当前非终止任务的唯一登记源，由 `main` 协调工作区维护。实施 Agent 不在任务分支修改本文件。

开始任务前，复制 `TASK_TEMPLATE.md` 中的模板到“活动任务”部分。认领前检查所有 `planned`、`in-progress`、`review`、`changes-requested`、`approved` 和 `blocked` 任务是否存在范围重叠。

## 活动任务

### collaboration-setup-001

```yaml
task_id: collaboration-setup-001
title: 建立 Codex 与 Claude Code 多角色协作规范
status: completed
risk: low
owner: Codex
client: Codex-Desktop
branch: codex/collaboration-setup-001
worktree: .worktrees/collaboration-setup-001
planner: Codex
implementer: Codex
reviewer: Project-Owner, Claude-Code
database_change: false
plan: docs/superpowers/plans/2026-07-27-multi-agent-collaboration-implementation.md
review_handoff: generated
```

#### 目标

建立共享协作规范、任务登记模板和两个客户端的一致入口，不修改业务代码。

#### 范围

##### Exact files

- `AI_COLLABORATION.md`
- `docs/coordination/ACTIVE_TASKS.md`
- `docs/coordination/TASK_TEMPLATE.md`
- `AGENTS.md`
- `CLAUDE.md`

##### Path patterns

- 无。

##### Symbols

- 无。

##### Shared resources

- Git 分支和 worktree 命名规范。
- AI Agent 推送与合并授权边界。

#### 验收条件

- 两个客户端入口均强制引用共享规范。
- 任务模板覆盖负责人、范围、风险、状态、评审和阻塞信息。
- 共享规范明确独立 worktree、跨客户端评审、推送与合并分开授权。
- 所有目标 Markdown 文件通过内容和尾随空白检查。

#### 阻塞记录

- 无。

#### 评审记录

- 本任务只修改协作文档，按低风险规则由项目所有者直接审核。
- 实施提交：`5f58fd2`、`b1985e0`、`985bbc1`。
- 已验证变更范围、共享规范关键条款、任务模板字段、两个入口文件一致性和 Markdown 格式。
- 项目所有者与 Claude Code 已完成协同评审；4 项文档一致性意见已在提交 `924c482` 中处理。
- 项目所有者已批准评审结果。
- 项目所有者已授权推送并合并到 `main`，合并提交为 `ba13272`。
- 当前状态：任务已完成。

### development-baseline-001

```yaml
task_id: development-baseline-001
title: 建立开发与测试环境基线
status: review
risk: normal
owner: Codex
client: Codex-Desktop
branch: codex/development-baseline-001
worktree: .worktrees/development-baseline-001
planner: Codex
implementer: Codex
reviewer: Claude-Code
database_change: false
plan: docs/superpowers/plans/2026-07-27-development-baseline-implementation.md
review_handoff: generated
```

#### 目标

建立可重复执行的 Windows 开发与测试环境基线，覆盖运行时发现、项目依赖恢复、后端测试、前端构建、数据库只读检查和非敏感结果报告。

#### 实现说明

按照已批准的设计与实施计划，在独立 worktree 中以测试先行方式实现检查脚本和开发指南，并使用现有本地 PostgreSQL 执行只读验证。

#### 范围

##### Exact files

- `scripts/check_database_readonly.py`
- `backend/tests/test_database_baseline.py`
- `scripts/check_dev_environment.ps1`
- `scripts/verify_baseline.ps1`
- `scripts/tests/test_baseline_scripts.ps1`
- `docs/DEVELOPMENT.md`
- `docs/coordination/BASELINE.md`
- `docs/coordination/ACTIVE_TASKS.md`

##### Path patterns

- 无。

##### Symbols

- 无。

##### Shared resources

- `backend/.venv`（Git 忽略）。
- `frontend/node_modules`（Git 忽略）。
- `backend/.env`（只读，Git 忽略）。
- 当前 PostgreSQL 数据库（只读）。

#### 验收条件

- 不安装新的系统级 Python、Node.js、PostgreSQL 或 pgvector。
- 不执行数据库写入、迁移、重建、删除、清空或索引操作。
- 不调用外部 AI 服务，不下载 BGE-M3、PaddleOCR 等模型。
- 所有检查明确输出 `PASS`、`FAIL`、`SKIP` 或 `BLOCKED`。
- 后端单元测试、PowerShell 合同测试、前端构建和基线重复性检查具有可复现结果。
- 已提交文件不包含密钥、数据库连接串或个人绝对路径。

#### 阻塞记录

- 无。

#### 评审记录

- 实现提交：`d28077e`、`1edeebe`、`c4d22d3`、`45c6b56`、`dadbdc2`、`ca706c9`。
- 后端 41 项单元测试、PowerShell 合同测试、前端构建和 PostgreSQL 只读检查均通过。
- 两次无安装基线的 18 个组件状态完全一致：13 项 `PASS`，5 项按安全策略 `SKIP`。
- 跳过项：外部 LLM、模型下载、OCR/GPU、文档重新索引、数据库写入测试。
- 分支仅存在于本地，尚未推送或合并。

#### 评审交接信息

```text
请评审任务 development-baseline-001。

实现者：Codex
评审者：Claude Code
分支：codex/development-baseline-001
基线：main
提交：d28077e0656b320326c8985ed31303a6850b6198..ca706c9bffe607e60db614eabe8de5c368ebd18d
方案：docs/superpowers/specs/2026-07-27-development-baseline-design.md
实施计划：docs/superpowers/plans/2026-07-27-development-baseline-implementation.md
验收结果：docs/coordination/BASELINE.md
重点检查：脚本是否可能修改系统或数据库、是否泄露秘密、版本发现是否可移植、失败和跳过状态是否准确。

只输出评审意见，不直接修改实现提交。
```

## 终止状态归档规则

- 合并完成后将任务状态改为 `completed`，保留到下一次协调整理时再移入项目历史记录或删除。
- 取消任务使用 `cancelled`，必须记录取消原因。
- 不得删除仍处于非终止状态的任务记录。
