# Multi-Agent Collaboration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Codex 与 Claude Code 建立共享协作规范、活动任务登记和一致的项目入口，同时保留项目现有说明与 UI 规则。

**Architecture:** 根目录的 `AI_COLLABORATION.md` 是唯一共享规范；`AGENTS.md` 与 `CLAUDE.md` 只保留客户端入口职责并强制引用共享规范。`docs/coordination/ACTIVE_TASKS.md` 由 `main` 协调工作区维护，`TASK_TEMPLATE.md` 定义可比较的任务范围和状态字段。

**Tech Stack:** Markdown、Git、PowerShell、ripgrep (`rg`)

## Global Constraints

- 本次任务编号为 `collaboration-setup-001`，实施者为 Codex；这只是单次任务分配，不构成永久职责。
- 当前主工作区只用于协调、审核和最终合并；执行本计划时应使用 `codex/collaboration-setup-001` 独立分支和 worktree。
- Agent 可以创建本地提交，但不得自行推送远程或合并到 `main`。
- 不 amend 已有提交，不强制重置，不改写共享历史。
- `AGENTS.md` 与 `CLAUDE.md` 必须保留现有项目概述、UI 规则和通用规则。
- 两个入口文件中的 UI 规范路径统一为 `docs/DESIGN_SPEC.md`。
- 不新增 Git hooks、自动任务锁、GitHub Issues 强制流程或永久 worktree。
- 所有新增文件使用 UTF-8 Markdown，避免引入与协作流程无关的代码修改。

---

## File Map

- Create: `AI_COLLABORATION.md` — Codex 与 Claude Code 共同遵循的唯一协作规范。
- Create: `docs/coordination/ACTIVE_TASKS.md` — 仅记录当前非终止任务和维护说明。
- Create: `docs/coordination/TASK_TEMPLATE.md` — 新任务登记的完整字段、状态和示例。
- Modify: `AGENTS.md` — 保留现有内容，增加共享规范入口并修正 UI 文档路径。
- Modify: `CLAUDE.md` — 保留现有内容，增加共享规范入口并修正 UI 文档路径。

### Task 1: Create The Shared Collaboration Policy

**Files:**
- Create: `AI_COLLABORATION.md`
- Reference: `docs/superpowers/specs/2026-07-27-multi-agent-collaboration-design.md`

**Interfaces:**
- Consumes: 已批准设计中的权限边界、worktree 模型、任务状态、规划分级和评审规则。
- Produces: `AGENTS.md`、`CLAUDE.md` 和任务模板共同引用的规范文件。

- [ ] **Step 1: Verify the file does not already exist**

Run:

```powershell
Test-Path 'AI_COLLABORATION.md'
```

Expected: `False`。如果返回 `True`，停止并先比较现有文件，不能直接覆盖。

- [ ] **Step 2: Create the shared policy**

Create `AI_COLLABORATION.md` with this content:

````markdown
# AI 多角色协作规范

本文件是 Codex 与 Claude Code 的共享协作规范。`AGENTS.md` 和 `CLAUDE.md` 中与本文件冲突的协作流程，以本文件为准；项目所有者的明确指令始终优先。

## 1. 角色与权限

- 项目不固定 Codex 与 Claude Code 的长期职责；每项任务单独记录规划者、实现者和评审者。
- 当前项目目录是由项目所有者控制的协调工作区，保持在 `main`，用于任务登记、审核和经授权后的推送或合并。
- 不设置永久“协调 Agent”。项目所有者可以明确委托当前 Agent 执行一次性的登记或状态更新，但不会因此授予推送或合并权限。
- Agent 可以在自己的任务分支创建本地提交，但不得自行推送、合并到 `main`、amend 他人的提交、强制推送或重写共享历史。

## 2. 任务登记与范围

- 开始任何实现前，必须在 `docs/coordination/ACTIVE_TASKS.md` 登记唯一 `Task-ID`、负责人、客户端、分支、worktree、风险、范围、验收条件和角色分配。
- `ACTIVE_TASKS.md` 只由协调工作区维护；实施 Agent 不在任务分支修改该文件。
- 范围必须列出具体文件、路径模式及必要的函数、类或接口名称，不以易漂移的行号作为主要边界。
- 认领任务前必须检查所有非终止任务的文件、路径模式、符号和数据库等共享资源。范围重叠时，后登记任务必须等待、拆分或重新分配。
- 实现中需要越出登记范围时，先停止修改并由协调工作区更新登记，经项目所有者确认后继续。

## 3. 规划与评审

- 微小修改：在任务登记中写清目标、范围和验收条件。
- 普通功能或 Bug 修复：补充简短实现说明、影响范围和验证方式，确认后实现。
- 跨模块、数据库、认证、安全、RAG 核心链路和架构修改：先编写方案并取得项目所有者明确批准。
- 普通文档和微小配置可由项目所有者直接审核；功能、Bug、数据库、认证、安全和 RAG 核心逻辑必须由另一个 Agent 交叉评审。
- 评审者只报告问题、证据、风险和测试缺口。需要修复时，由原实现者创建新提交，不改写已有提交。

## 4. 分支与 Worktree

- Codex 分支使用 `codex/<task-id>`，Claude Code 分支使用 `claude/<task-id>`。
- 每项实现任务使用独立 worktree；两个 Agent 不得同时操作同一物理目录。
- 创建任务分支前，先确认协调工作区干净，再执行：

```powershell
git fetch origin
git switch main
git pull --ff-only origin main
```

- 无法快进时停止操作并交由项目所有者处理；不得自动 rebase、强制重置或制造隐式合并。
- 任务合并后，将状态标记为 `completed`，再清理对应 worktree 和任务分支。

## 5. 提交留痕

提交主题使用清晰的 Conventional Commit 风格。提交正文必须包含：

```text
AI-Agent: Codex 或 Claude-Code
AI-Client: Codex-Desktop 或 VS-Code
Task-ID: 对应任务编号
```

Agent 提交时使用单次命令参数设置 Git 身份，不反复修改共享仓库的 `user.name` 和 `user.email`。

## 6. 数据库与异常处理

- 涉及 schema 或迁移链时必须显式登记。默认同一时间只允许一个活动任务修改 schema 或 Alembic revision 链。
- 确需并行数据库任务时，先确定 revision 依赖和合并顺序；后登记任务必须基于已确定的前置 revision。
- 遇到无法恢复的依赖、环境、权限或执行问题时，停止扩大修改范围，将任务标记为 `blocked`，记录原因、已完成内容和未验证项目，由项目所有者决定后续处理。
- 验证环境不完整时，明确列出未运行的检查及原因，不得宣称测试或验证通过。

## 7. UI 修改

任何 UI 修改前必须完整读取并遵守 `docs/DESIGN_SPEC.md`。除非项目所有者明确要求改变风格，否则不得偏离其中的视觉和双角色体验规范。

## 8. 所有者批准

推送和合并必须获得项目所有者明确批准。单人项目中，一条清晰指令即可完成授权，例如“允许推送 `retrieval-001`”；不要求额外审批系统。
````

- [ ] **Step 3: Verify required policy clauses**

Run:

```powershell
rg -n '不得自行推送|ACTIVE_TASKS.md|git pull --ff-only|交叉评审|blocked|Alembic|docs/DESIGN_SPEC.md' AI_COLLABORATION.md
```

Expected: 每个关键词至少匹配一次，命令退出码为 `0`。

- [ ] **Step 4: Check Markdown whitespace**

Run:

```powershell
rg -n '[ \t]+$' AI_COLLABORATION.md
```

Expected: 无输出，`rg` 退出码为 `1`，表示没有尾随空白。提交前再运行 `git diff --cached --check`。

- [ ] **Step 5: Commit the shared policy locally**

```powershell
git add -- AI_COLLABORATION.md
git -c user.name="Codex Agent" -c user.email="codex-agent@local" commit -m "docs(collaboration): add shared AI policy" -m "AI-Agent: Codex`nAI-Client: Codex-Desktop`nTask-ID: collaboration-setup-001"
```

Expected: 创建一个只包含 `AI_COLLABORATION.md` 的本地提交。

### Task 2: Add Coordination Register And Task Template

**Files:**
- Create: `docs/coordination/ACTIVE_TASKS.md`
- Create: `docs/coordination/TASK_TEMPLATE.md`
- Reference: `AI_COLLABORATION.md`

**Interfaces:**
- Consumes: 共享规范中的状态、范围、权限和评审要求。
- Produces: 协调工作区可直接复制使用的任务登记格式。

- [ ] **Step 1: Verify the coordination directory is absent or empty**

Run:

```powershell
Get-ChildItem 'docs/coordination' -Force -ErrorAction SilentlyContinue
```

Expected: 无输出。若存在文件，停止并审阅，不能覆盖未知内容。

- [ ] **Step 2: Create the active task register**

Create `docs/coordination/ACTIVE_TASKS.md`:

````markdown
# 活动任务登记

本文件是当前非终止任务的唯一登记源，由 `main` 协调工作区维护。实施 Agent 不在任务分支修改本文件。

开始任务前，复制 `TASK_TEMPLATE.md` 中的模板到“活动任务”部分。认领前检查所有 `planned`、`in-progress`、`review`、`changes-requested`、`approved` 和 `blocked` 任务是否存在范围重叠。

## 活动任务

当前没有活动任务。

## 终止状态归档规则

- 合并完成后将任务状态改为 `completed`，保留到下一次协调整理时再移入项目历史记录或删除。
- 取消任务使用 `cancelled`，必须记录取消原因。
- 不得删除仍处于非终止状态的任务记录。
````

- [ ] **Step 3: Create the task template**

Create `docs/coordination/TASK_TEMPLATE.md`:

````markdown
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
worktree: ../Surgery-RAG-Agent-retrieval-001
planner: Codex
implementer: Codex
reviewer: Claude-Code
database_change: false
plan: docs/plans/retrieval-001.md
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
````

- [ ] **Step 4: Verify the register and template contract**

Run:

```powershell
rg -n '唯一登记源|当前没有活动任务|不得删除仍处于非终止状态' docs/coordination/ACTIVE_TASKS.md
rg -n 'task_id:|Exact files|Path patterns|Symbols|Shared resources|database_change|blocked|completed|cancelled' docs/coordination/TASK_TEMPLATE.md
```

Expected: 所有字段和状态均有匹配，两个命令退出码均为 `0`。

- [ ] **Step 5: Check Markdown whitespace**

Run:

```powershell
rg -n '[ \t]+$' docs/coordination/ACTIVE_TASKS.md docs/coordination/TASK_TEMPLATE.md
```

Expected: 无输出，`rg` 退出码为 `1`，表示没有尾随空白。提交前再运行 `git diff --cached --check`。

- [ ] **Step 6: Commit coordination files locally**

```powershell
git add -- docs/coordination/ACTIVE_TASKS.md docs/coordination/TASK_TEMPLATE.md
git -c user.name="Codex Agent" -c user.email="codex-agent@local" commit -m "docs(collaboration): add task coordination templates" -m "AI-Agent: Codex`nAI-Client: Codex-Desktop`nTask-ID: collaboration-setup-001"
```

Expected: 创建一个只包含两个协调文档的本地提交。

### Task 3: Connect Codex And Claude Code Entry Files

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Reference: `AI_COLLABORATION.md`
- Reference: `docs/DESIGN_SPEC.md`

**Interfaces:**
- Consumes: 共享协作规范路径和现有项目说明。
- Produces: 两个客户端进入项目时一致的强制阅读入口。

- [ ] **Step 1: Capture the existing sections that must remain**

Run:

```powershell
rg -n '^## 项目概述$|^## 前端 UI 修改规则$|^## 通用规则$' AGENTS.md CLAUDE.md
```

Expected: 每个文件均匹配三个标题，共六条匹配。

- [ ] **Step 2: Add the shared-policy notice to `AGENTS.md`**

Immediately after `# AGENTS.md`, insert:

```markdown
> 开始任何项目操作前，必须先完整阅读并遵守 `AI_COLLABORATION.md` 中的多角色协作规范。
```

Replace both existing `DESIGN_SPEC.md` references with `docs/DESIGN_SPEC.md`. Do not remove or rewrite any other existing section.

- [ ] **Step 3: Add the shared-policy notice to `CLAUDE.md`**

Immediately after `# CLAUDE.md`, insert:

```markdown
> 开始任何项目操作前，必须先完整阅读并遵守 `AI_COLLABORATION.md` 中的多角色协作规范。
```

Replace both existing `DESIGN_SPEC.md` references with `docs/DESIGN_SPEC.md`. Do not remove or rewrite any other existing section.

- [ ] **Step 4: Verify both entry files preserve content and agree**

Run:

```powershell
rg -n '必须先完整阅读并遵守 `AI_COLLABORATION.md`|docs/DESIGN_SPEC.md|^## 项目概述$|^## 前端 UI 修改规则$|^## 通用规则$' AGENTS.md CLAUDE.md
```

Expected: 两个文件都包含共享规范提示、实际 UI 文档路径和三个原有标题。

Run:

```powershell
$agentsBody = (Get-Content -Raw -Encoding UTF8 AGENTS.md) -replace '# AGENTS.md', '# ENTRY.md'
$claudeBody = (Get-Content -Raw -Encoding UTF8 CLAUDE.md) -replace '# CLAUDE.md', '# ENTRY.md'
if ($agentsBody -ne $claudeBody) { throw 'AGENTS.md and CLAUDE.md differ beyond their title' }
```

Expected: 无输出，退出码为 `0`。

- [ ] **Step 5: Check Markdown whitespace**

Run:

```powershell
git diff --check -- AGENTS.md CLAUDE.md
```

Expected: 无输出，退出码为 `0`。

- [ ] **Step 6: Commit entry file changes locally**

```powershell
git add -- AGENTS.md CLAUDE.md
git -c user.name="Codex Agent" -c user.email="codex-agent@local" commit -m "docs(collaboration): connect agent entry files" -m "AI-Agent: Codex`nAI-Client: Codex-Desktop`nTask-ID: collaboration-setup-001"
```

Expected: 创建一个只包含 `AGENTS.md` 和 `CLAUDE.md` 的本地提交。

### Task 4: Run Acceptance Verification And Prepare Owner Review

**Files:**
- Verify: `AI_COLLABORATION.md`
- Verify: `docs/coordination/ACTIVE_TASKS.md`
- Verify: `docs/coordination/TASK_TEMPLATE.md`
- Verify: `AGENTS.md`
- Verify: `CLAUDE.md`

**Interfaces:**
- Consumes: Tasks 1–3 的全部文档。
- Produces: 可供项目所有者批准推送或要求修订的本地提交序列和验证证据。

- [ ] **Step 1: Verify exact changed-file scope**

Run from the task branch:

```powershell
git diff --name-only main...HEAD
```

Expected output contains exactly:

```text
AGENTS.md
AI_COLLABORATION.md
CLAUDE.md
docs/coordination/ACTIVE_TASKS.md
docs/coordination/TASK_TEMPLATE.md
```

- [ ] **Step 2: Verify all policy acceptance criteria**

Run:

```powershell
rg -n '不得自行推送|独立 worktree|git pull --ff-only|交叉评审|数据库|blocked|项目所有者明确批准' AI_COLLABORATION.md
rg -n 'Exact files|Path patterns|Symbols|Shared resources|database_change' docs/coordination/TASK_TEMPLATE.md
rg -n 'AI_COLLABORATION.md|docs/DESIGN_SPEC.md' AGENTS.md CLAUDE.md
```

Expected: 每组要求均有匹配，所有命令退出码为 `0`。

- [ ] **Step 3: Verify there are no placeholders or malformed whitespace**

Run:

```powershell
rg -n 'TBD|TODO|待定|占位' AI_COLLABORATION.md docs/coordination AGENTS.md CLAUDE.md
```

Expected: 无输出，`rg` 退出码为 `1`，表示没有匹配。

Run:

```powershell
git diff main...HEAD --check
```

Expected: 无输出，退出码为 `0`。

- [ ] **Step 4: Verify local commit identity and trailers**

Run:

```powershell
git log main..HEAD --format='%h | %an <%ae> | %s%n%b'
```

Expected: 三个实施提交均由 `Codex Agent <codex-agent@local>` 创建，且正文包含：

```text
AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: collaboration-setup-001
```

- [ ] **Step 5: Stop for project-owner authorization**

Report the branch name, worktree path, commit hashes, changed files and verification results. Do not run `git push`, merge into `main`, remove the worktree or delete the branch until the project owner gives an explicit instruction.
