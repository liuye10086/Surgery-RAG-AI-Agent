# 任务登记模板

将以下模板复制到 `ACTIVE_TASKS.md`。删除不适用的示例值，但不得删除必填字段。

```yaml
task_id: retrieval-001
title: 优化混合检索排序
status: planned
risk: high
owner: Codex
client: Codex-Desktop
branch: codex/retrieval-001
worktree: .worktrees/retrieval-001
planner: Codex
implementer: Codex
reviewer: Claude-Code
database_change: false
plan: docs/plans/retrieval-001.md
review_handoff: pending
```

## 目标

用一至三句话描述可观察的任务结果。

## 实现说明

说明拟采用的方法、影响范围和验证方式。微小任务可简写；高风险任务必须链接已批准方案。

## 范围

### Exact files

- `backend/app/rag/pipeline.py`

### Path patterns

- `backend/tests/test_rag_*.py`

### Symbols

- `backend/app/rag/pipeline.py: hybrid_search()`

### Shared resources

- 无；如涉及数据库 schema、Alembic revision、共享配置或 API contract，必须逐项列出。

## 验收条件

- 指定行为具有可复现的验证结果。
- 列出需要运行的测试、构建或静态检查命令。
- 未运行的验证必须记录原因。

## 阻塞记录

- 无。状态为 `blocked` 时，记录原因、已完成内容、未验证项目和需要项目所有者决定的事项。

## 评审记录

- 尚未评审。评审者只记录问题、证据、风险和测试缺口，不直接改写实现者提交。

## 评审交接信息

```text
请评审任务 retrieval-001。

实现者：Codex
评审者：Claude Code
分支：codex/retrieval-001
基线：main
提交：<first-commit>..<last-commit>
方案或登记：docs/coordination/ACTIVE_TASKS.md
验收条件：见本任务“验收条件”部分
重点检查：行为回归、安全风险、缺失测试

只输出评审意见，不直接修改实现提交。
```

Allowed status values:

- `planned`
- `in-progress`
- `review`
- `changes-requested`
- `approved`
- `blocked`
- `completed`
- `cancelled`

Risk guidance:

- `low`: 文案、注释、小范围文档、无行为变化的配置。
- `normal`: 常规功能和一般 Bug 修复。
- `high`: 跨模块、数据库、认证、安全、RAG 核心链路或架构修改。
