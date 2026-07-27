# 活动任务登记

本文件是当前非终止任务的唯一登记源，由 `main` 协调工作区维护。实施 Agent 不在任务分支修改本文件。

开始任务前，复制 `TASK_TEMPLATE.md` 中的模板到“活动任务”部分。认领前检查所有 `planned`、`in-progress`、`review`、`changes-requested`、`approved` 和 `blocked` 任务是否存在范围重叠。

## 活动任务

### collaboration-setup-001

```yaml
task_id: collaboration-setup-001
title: 建立 Codex 与 Claude Code 多角色协作规范
status: in-progress
risk: low
owner: Codex
client: Codex-Desktop
branch: codex/collaboration-setup-001
worktree: .worktrees/collaboration-setup-001
planner: Codex
implementer: Codex
reviewer: Project-Owner
database_change: false
plan: docs/superpowers/plans/2026-07-27-multi-agent-collaboration-implementation.md
review_handoff: not-required
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

## 终止状态归档规则

- 合并完成后将任务状态改为 `completed`，保留到下一次协调整理时再移入项目历史记录或删除。
- 取消任务使用 `cancelled`，必须记录取消原因。
- 不得删除仍处于非终止状态的任务记录。
