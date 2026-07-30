# 活动任务登记

本文件是当前非终止任务的唯一登记源，由 `main` 协调工作区维护。实施 Agent 不在任务分支修改本文件。

开始任务前，复制 `TASK_TEMPLATE.md` 中的模板到“活动任务”部分。认领前检查所有 `planned`、`in-progress`、`review`、`changes-requested`、`approved` 和 `blocked` 任务是否存在范围重叠。

## 活动任务

### qa-scroll-follow-001

```yaml
task_id: qa-scroll-follow-001
title: 修正问答流式输出时无法上滑
status: in-progress
risk: normal
owner: Codex
client: Codex-Desktop
branch: codex/qa-scroll-follow-001
worktree: .worktrees/qa-scroll-follow-001
planner: Codex
implementer: Codex
reviewer: Claude-Code
database_change: false
plan: docs/coordination/ACTIVE_TASKS.md
review_handoff: pending
```

#### 目标

问答类页面在流式输出回答时，用户手动上滑查看前文后不再被自动拉回底部；用户仍在底部附近时继续跟随最新内容。

#### 实现说明

为聊天页和 AI 操作者报告页的滚动容器增加“是否跟随底部”的状态：滚动位置接近底部时允许自动滚动；用户离开底部后暂停自动滚动。发送新问题或打开历史内容时保留原有滚到底部行为。

#### 范围

##### Exact files

- `frontend/src/views/ChatView.vue`
- `frontend/src/views/OperatorView.vue`

##### Path patterns

- 无。

##### Symbols

- `ChatView.vue`: `messageListRef`、消息变化 watch、发送/提示点击流程
- `OperatorView.vue`: `reportAreaRef`、生成内容变化 watch、生成流程

##### Shared resources

- 无。

#### 验收条件

- 聊天页回答流式输出时，用户上滑后不会被下一段内容自动拉回底部。
- AI 操作者报告流式输出时，用户上滑后不会被下一段内容自动拉回底部。
- 用户停留在底部附近时，流式输出仍会自动跟随到底部。
- 前端类型检查通过。

#### 阻塞记录

- 无。

#### 评审记录

- 尚未评审。

#### 评审交接信息

```text
请评审任务 qa-scroll-follow-001。

实现者：Codex
评审者：Claude Code
分支：codex/qa-scroll-follow-001
基线：main
提交：<first-commit>..<last-commit>
方案或登记：docs/coordination/ACTIVE_TASKS.md
验收条件：见本任务“验收条件”部分
重点检查：聊天页和 AI 操作者页流式输出时自动滚动是否尊重用户手动上滑。

只输出评审意见，不直接修改实现提交。
```

### admin-table-scroll-001

```yaml
task_id: admin-table-scroll-001
title: 优化管理后台文档表格滚动与对齐
status: in-progress
risk: normal
owner: Codex
client: Codex-Desktop
branch: codex/admin-table-scroll-001
worktree: .worktrees/admin-table-scroll-001
planner: Codex
implementer: Codex
reviewer: Claude-Code
database_change: false
plan: docs/coordination/ACTIVE_TASKS.md
review_handoff: pending
```

#### 目标

管理后台文档表格表头/内容居中显示，操作列固定在右侧，横向滚动条在当前页面表格区域内可用。

#### 实现说明

为文档表格设置固定视口高度，使滚动发生在表格内部；统一列对齐；保持操作列 `fixed="right"`。

#### 范围

##### Exact files

- `frontend/src/views/AdminView.vue`

##### Path patterns

- 无。

##### Symbols

- `AdminView.vue`: 文档 `el-table`、文档表格列、`.table-card`

##### Shared resources

- 无。

#### 验收条件

- 文档表格列标题和单元格居中。
- 操作列在横向滚动时固定在右侧。
- 横向滚动条显示在表格区域内，不需要滚到页面底部才能左右滚动。
- 前端类型检查通过。

#### 阻塞记录

- 无。

#### 评审记录

- 尚未评审。

#### 评审交接信息

```text
请评审任务 admin-table-scroll-001。

实现者：Codex
评审者：Claude Code
分支：codex/admin-table-scroll-001
基线：main
提交：<first-commit>..<last-commit>
方案或登记：docs/coordination/ACTIVE_TASKS.md
验收条件：见本任务“验收条件”部分
重点检查：文档表格对齐、操作列固定、横向滚动条位置是否符合预期。

只输出评审意见，不直接修改实现提交。
```

### collapsed-avatar-menu-001

```yaml
task_id: collapsed-avatar-menu-001
title: 修正折叠侧边栏头像点击行为
status: in-progress
risk: normal
owner: Codex
client: Codex-Desktop
branch: codex/collapsed-avatar-menu-001
worktree: .worktrees/collapsed-avatar-menu-001
planner: Codex
implementer: Codex
reviewer: Claude-Code
database_change: false
plan: docs/coordination/ACTIVE_TASKS.md
review_handoff: pending
```

#### 目标

折叠侧边栏时点击用户头像应打开用户菜单，行为与展开态点击 `...` 一致，不应直接退出登录。

#### 实现说明

将折叠态头像包裹为 `el-popover` 触发器，复用展开态菜单项；聊天侧边栏提供设置和退出，AI 操作者侧边栏提供退出。

#### 范围

##### Exact files

- `frontend/src/components/ChatSidebar.vue`
- `frontend/src/components/OperatorSidebar.vue`

##### Path patterns

- 无。

##### Symbols

- `ChatSidebar.vue`: 折叠态 `.cs-bot` 用户头像
- `OperatorSidebar.vue`: 折叠态 `.cs-bot` 用户头像

##### Shared resources

- 无。

#### 验收条件

- 聊天侧边栏折叠态点击头像打开包含“设置 / 退出登录”的菜单。
- AI 操作者侧边栏折叠态点击头像打开包含“退出登录”的菜单。
- 折叠态头像不再直接触发退出登录。
- 前端类型检查通过。

#### 阻塞记录

- 无。

#### 评审记录

- 尚未评审。

#### 评审交接信息

```text
请评审任务 collapsed-avatar-menu-001。

实现者：Codex
评审者：Claude Code
分支：codex/collapsed-avatar-menu-001
基线：main
提交：<first-commit>..<last-commit>
方案或登记：docs/coordination/ACTIVE_TASKS.md
验收条件：见本任务“验收条件”部分
重点检查：折叠态头像点击是否打开菜单而非退出，菜单项是否与展开态一致。

只输出评审意见，不直接修改实现提交。
```

### chat-dept-nan-001

```yaml
task_id: chat-dept-nan-001
title: 修正聊天页默认科室显示 NaN
status: in-progress
risk: normal
owner: Codex
client: Codex-Desktop
branch: codex/chat-dept-nan-001
worktree: .worktrees/chat-dept-nan-001
planner: Codex
implementer: Codex
reviewer: Claude-Code
database_change: false
plan: docs/coordination/ACTIVE_TASKS.md
review_handoff: pending
```

#### 目标

未选择科室或本地缓存为空/非法时，聊天页科室选择器显示“全部科室”，不显示 `NaN`。

#### 实现说明

在聊天 store 中归一化科室 ID：只接受有限数字 ID，其余空值、`NaN`、非法字符串统一视为 `null` 并清理本地缓存。

#### 范围

##### Exact files

- `frontend/src/stores/chat.ts`

##### Path patterns

- 无。

##### Symbols

- `chat.ts`: `_loadDepartmentId()`、`setSelectedDepartmentId()`

##### Shared resources

- `localStorage.surgery_rag_selected_department_id`

#### 验收条件

- 本地缓存为 `NaN` 时初始化为未选择科室。
- 清空选择器时写入 `null` 状态并移除缓存。
- 前端类型检查通过。

#### 阻塞记录

- 无。

#### 评审记录

- 尚未评审。

#### 评审交接信息

```text
请评审任务 chat-dept-nan-001。

实现者：Codex
评审者：Claude Code
分支：codex/chat-dept-nan-001
基线：main
提交：<first-commit>..<last-commit>
方案或登记：docs/coordination/ACTIVE_TASKS.md
验收条件：见本任务“验收条件”部分
重点检查：科室筛选 localStorage 归一化是否正确，是否影响正常科室选择和发送问题。

只输出评审意见，不直接修改实现提交。
```

### case-image-preview-001

```yaml
task_id: case-image-preview-001
title: 放大完整病例图片预览
status: in-progress
risk: normal
owner: Codex
client: Codex-Desktop
branch: codex/case-image-preview-001
worktree: .worktrees/case-image-preview-001
planner: Codex
implementer: Codex
reviewer: Claude-Code
database_change: false
plan: docs/coordination/ACTIVE_TASKS.md
review_handoff: pending
```

#### 目标

点击完整病例弹窗中的病例图片时，图片预览应以更大的可视区域显示，避免被病例弹窗尺寸限制。

#### 实现说明

调整 `InfoPanel.vue` 中 `el-image` 预览配置，将预览层挂载到页面 body，并提高缩放参数；保留现有缩略图网格。

#### 范围

##### Exact files

- `frontend/src/components/InfoPanel.vue`

##### Path patterns

- 无。

##### Symbols

- `InfoPanel.vue`: `.case-image-thumb`、病例图片 `el-image`

##### Shared resources

- 无。

#### 验收条件

- 病例图片点击后预览层脱离完整病例弹窗容器限制。
- 图片预览支持更大的缩放范围。
- 前端类型检查通过。

#### 阻塞记录

- 无。

#### 评审记录

- 尚未评审。

#### 评审交接信息

```text
请评审任务 case-image-preview-001。

实现者：Codex
评审者：Claude Code
分支：codex/case-image-preview-001
基线：main
提交：<first-commit>..<last-commit>
方案或登记：docs/coordination/ACTIVE_TASKS.md
验收条件：见本任务“验收条件”部分
重点检查：完整病例弹窗内病例图片预览是否足够大，是否影响现有病例弹窗内容布局。

只输出评审意见，不直接修改实现提交。
```

### chat-dept-layout-001

```yaml
task_id: chat-dept-layout-001
title: 修正聊天页科室选择器底部布局
status: in-progress
risk: normal
owner: Codex
client: Codex-Desktop
branch: codex/chat-dept-layout-001
worktree: .worktrees/chat-dept-layout-001
planner: Codex
implementer: Codex
reviewer: Claude-Code
database_change: false
plan: docs/coordination/ACTIVE_TASKS.md
review_handoff: pending
```

#### 目标

修正登录后聊天界面科室选择器位置，使其位于输入框下方并与输入框同宽居中，避免在大屏下贴近左侧底部。

#### 实现说明

在 `ChatView.vue` 内调整输入区 DOM 顺序和样式约束：输入框先渲染，科室筛选行后渲染；科室筛选行复用输入框最大宽度并水平居中。通过静态布局检查和前端构建验证。

#### 范围

##### Exact files

- `frontend/src/views/ChatView.vue`

##### Path patterns

- 无。

##### Symbols

- `ChatView.vue`: `.chat-input-area`、`.input-wrapper`、`.dept-filter-row`

##### Shared resources

- 无。

#### 验收条件

- 科室选择器显示在聊天输入框下方。
- 科室选择器与输入框同一最大宽度容器内居中对齐，不再贴近主内容区左侧。
- `npm run build` 在 `frontend` 目录通过。

#### 阻塞记录

- 无。

#### 评审记录

- 尚未评审。

#### 评审交接信息

```text
请评审任务 chat-dept-layout-001。

实现者：Codex
评审者：Claude Code
分支：codex/chat-dept-layout-001
基线：main
提交：<first-commit>..<last-commit>
方案或登记：docs/coordination/ACTIVE_TASKS.md
验收条件：见本任务“验收条件”部分
重点检查：聊天页底部输入区布局是否符合 docs/DESIGN_SPEC.md，是否引入移动端或构建回归。

只输出评审意见，不直接修改实现提交。
```

### ai-operator-001

```yaml
task_id: ai-operator-001
title: AI 操作者模块 — 第三端报告分析系统
status: completed
risk: high
owner: Claude-Code
client: VS-Code
branch: claude/ai-operator-001
worktree: .worktrees/ai-operator-001
planner: Claude-Code
implementer: Claude-Code
reviewer: Codex
database_change: true
plan: docs/superpowers/plans/2026-07-28-ai-operator-implementation.md
review_handoff: generated
```

#### 目标

在现有医生/患者端和管理员端之外，新增第三端 AI 操作者（ai_operator）模块。该角色可检索全库病例数据，通过 LLM 分析生成结构化研究报告（固定 7 章模板），支持 SSE 流式渲染和 PDF 下载。

#### 范围

##### Exact files

- `database/migrations/010_add_ai_operator_reports.sql`
- `backend/alembic/versions/0004_add_ai_reports.py`
- `backend/app/db/models.py`
- `backend/app/api/deps.py`
- `backend/app/schemas/operator.py`
- `backend/app/services/report_generator.py`
- `backend/app/services/pdf_generator.py`
- `backend/app/templates/report_pdf.html`
- `backend/app/api/operator.py`
- `backend/app/api/chat.py`
- `backend/app/main.py`
- `scripts/create_ai_operator.py`
- `frontend/src/stores/auth.ts`
- `frontend/src/api/operator.ts`
- `frontend/src/stores/operator.ts`
- `frontend/src/components/OperatorSidebar.vue`
- `frontend/src/views/OperatorView.vue`
- `frontend/src/router/index.ts`
- `frontend/src/views/ChatView.vue`
- `frontend/src/components/AdminSidebar.vue`
- `backend/requirements.txt`
- `backend/tests/test_report_generator.py`
- `backend/tests/test_operator_api.py`
- `backend/tests/test_operator_permissions.py`
- `backend/tests/test_operator_state_machine.py`
- `backend/tests/test_pdf_generation.py`

##### Symbols

- `backend/app/api/deps.py`: `require_ai_operator()`（新增）
- `backend/app/db/models.py`: `AIReport`（新增）
- `backend/app/services/report_generator.py`: `generate_report()`（新增）
- `backend/app/services/pdf_generator.py`: `generate_pdf()`（新增）
- `backend/app/rag/pipeline.py`: `hybrid_search()`（复用，多科室调用）
- `frontend/src/stores/auth.ts`: `isAiOperator`、`canAccessOperator`（新增）
- `frontend/src/router/index.ts`: `/operator` 路由守卫（修改）

##### Shared resources

- `ai_reports` 表：新表，13 个字段 + 3 个索引。
- `users.role`：新增 `"ai_operator"` 值（已有列，无需迁移）。
- `hybrid_search`：复用现有检索管线，通过 `department_id` 参数实现多科室检索合并。
- Alembic 迁移链：新增 `0004_add_ai_reports`（head = `0003_add_departments`）。
- 前端 `marked` + `DOMPurify`：复用现有依赖做 Markdown 安全渲染。

#### 验收条件

1. `role=ai_operator` 登录自动跳转 `/operator`；admin 可从聊天页导航进入
2. ai_operator 无法访问 `/` 和 `/admin`——前端路由 + 后端 API 双重拦截
3. admin 在 ChatView 和 AdminView 中可见"AI 操作者"导航入口
4. `/operator` 支持科室多选 + 输入问题 + 流式生成报告
5. 报告流式 SSE 渲染，遵循固定 7 章模板（含 DOMPurify 安全渲染）
6. 第 5 章标题为"检索样本中的观察性特征"，明确标注非全量统计
7. 报告仅创建者可查看/下载/删除
8. 生成中可取消，状态标记为 `cancelled`，不残留 `generating`
9. PDF 下载含中文正常渲染（A4 格式 + 页眉页脚 + 页码）
10. `analysis_backend` 参数预留预测模型切换能力
11. 多科室检索正确去重、排序、截断
12. 禁用 operator 模块后，现有功能回归测试通过
13. 输入安全过滤正常
14. 目标环境可生成中文 PDF
15. 审计日志记录报告生成操作
16. 后端全部测试通过，前端构建通过

#### 阻塞记录

- 无。

#### 评审记录

- 实现提交：`d4da0ec`、`68822a3`、`bcb45ec`、`33985bd`。
- Codex 评审（第一轮）：发现 3 个 P1 阻断问题（PDF 下载 401、非法参数残留 generating、持久化函数无终态保护）+ 2 个 P2 问题（FK 未命名、header title 未转义）。修复提交 `bcb45ec`。
- Codex 评审（第二轮）：发现 1 个 P1 阻断问题（Content-Disposition 中文编码）。修复提交 `33985bd`。
- Codex 评审（第三轮）：通过，未发现新阻断问题。
- 后端 104 项测试通过，前端 vue-tsc + Vite build 通过。
- 项目所有者已授权推送和合并；任务分支已推送，合并提交为 `4a57bdd`。
- 当前状态：任务已完成。

#### 评审交接信息

```text
请评审任务 ai-operator-001。

实现者：Claude-Code
评审者：Codex
分支：claude/ai-operator-001
基线：main
提交：d4da0ec..bcb45ec
方案：docs/superpowers/plans/2026-07-28-ai-operator-implementation.md
设计规格：docs/superpowers/specs/2026-07-27-ai-operator-module-design.md
登记：docs/coordination/ACTIVE_TASKS.md
验收条件：见本任务"验收条件"部分
重点检查：数据库迁移安全性、权限隔离、状态机终态规则、前端 XSS 防护、SSE 流式、多科室检索去重、ChatView 存量功能不受影响、Playwright 系统依赖、审计日志复用

只输出评审意见，不直接修改实现提交。
```

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
status: completed
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

- 实现提交：`d28077e`、`1edeebe`、`c4d22d3`、`45c6b56`、`dadbdc2`、`ca706c9`、`ab003ff`。
- 后端 41 项单元测试、PowerShell 合同测试、前端构建和 PostgreSQL 只读检查均通过。
- 两次无安装基线的 18 个组件状态完全一致：13 项 `PASS`，5 项按安全策略 `SKIP`。
- 跳过项：外部 LLM、模型下载、OCR/GPU、文档重新索引、数据库写入测试。
- Claude Code 评审通过；非阻塞建议要求记录 `psql` 自定义安装目录的发现限制，已在提交 `ab003ff` 中处理并重新验证。
- 项目所有者已分别授权推送和合并；任务分支已推送，合并提交为 `92a3b1d`。
- 合并后的 `main` 已重新通过后端 41 项测试、PowerShell 合同测试、前端构建和 PostgreSQL 只读检查。
- 当前状态：任务已完成。

#### 评审交接信息

```text
请评审任务 development-baseline-001。

实现者：Codex
评审者：Claude Code
分支：codex/development-baseline-001
基线：main
提交：d28077e0656b320326c8985ed31303a6850b6198..ab003ff23924c220b8d295cce754e13edd1acf31
方案：docs/superpowers/specs/2026-07-27-development-baseline-design.md
实施计划：docs/superpowers/plans/2026-07-27-development-baseline-implementation.md
验收结果：docs/coordination/BASELINE.md
重点检查：脚本是否可能修改系统或数据库、是否泄露秘密、版本发现是否可移植、失败和跳过状态是否准确。

只输出评审意见，不直接修改实现提交。
```

### department-filter-001

```yaml
task_id: department-filter-001
title: 文档科室分类筛选与定向检索
status: completed
risk: high
owner: Claude-Code
client: VS-Code
branch: claude/department-filter-001
worktree: .worktrees/department-filter-001
planner: Claude-Code
implementer: Claude-Code
reviewer: Codex
database_change: true
plan: docs/superpowers/specs/2026-07-28-department-filter-design.md
review_handoff: generated
```

#### 目标

管理员上传文档时可选择所属科室（如肝胆外科、神经外科等），用户提问时可选择科室范围进行定向检索，避免全库检索，提高检索精度和回答相关性。

#### 实现说明

跨模块改动：数据库新增 departments 表 + documents.department_id 外键；后端新增科室 CRUD API + 检索管线科室过滤；前端管理后台增加科室选择器 + 聊天界面增加科室筛选。方案已按评审意见修订，详见 plan 链接。

#### 范围

##### Exact files

- `database/migrations/009_add_departments.sql`
- `backend/app/db/models.py`
- `backend/app/schemas/department.py`
- `backend/app/schemas/document.py`
- `backend/app/api/admin.py`
- `backend/app/api/chat.py`
- `backend/app/rag/pipeline.py`
- `frontend/src/api/admin.ts`
- `frontend/src/api/chat.ts`
- `frontend/src/stores/chat.ts`
- `frontend/src/views/AdminView.vue`
- `frontend/src/views/ChatView.vue`

##### Path patterns

- 无。

##### Symbols

- `backend/app/rag/pipeline.py`: `SurgeryRetriever`, `_vector_search()`, `_fulltext_search()`, `hybrid_search()`
- `backend/app/db/models.py`: `Document`, 新增 `Department`
- `backend/app/api/admin.py`: `upload_document()`, `list_documents()`
- `backend/app/api/chat.py`: `ask()`, `AskRequest`

##### Shared resources

- `documents` 表：新增 `department_id` 列（FK → departments）。
- `departments` 表：新表。
- PostgreSQL 迁移链：新增 009 号迁移。

#### 验收条件

- 管理员上传文档时可选择科室（含"未分类"选项），上传后文档列表显示科室列，支持按科室筛选。
- 科室 CRUD API 通过校验：重名/不存在/已停用/有关联文档时返回正确错误码。
- 用户在聊天界面选择科室后，RAG 检索只返回该科室文档的分块；选择"全部科室"时保持全库检索行为。
- 后端 41 项存量单元测试继续通过。
- 前端构建通过。
- 迁移脚本可在本地 PostgreSQL 执行且幂等（使用 IF NOT EXISTS / IF EXISTS）。

#### 阻塞记录

- 无。

#### 评审记录

- Codex 评审（第一轮）：发现 3 个问题 — ref 初始值类型错误、科室 API 权限隔离缺失、缺少 Alembic migration + schema 限定。
- 修复提交 `5c2943f`：修正 ref 类型、新增公开 GET /api/v1/departments、创建 Alembic revision 0003、raw SQL 限定 current_schema()。
- 验证：vue-tsc 通过、前端 Vite build 通过、后端 40 项测试通过。
- Codex 评审（第二轮）：1 个迁移回退问题 — Alembic 外键和唯一约束使用匿名名称，downgrade 无法可靠执行；schema.sql 未同步。
- 修复提交 `1946ccd`：外键和唯一约束显式命名为 `documents_department_id_fkey` / `departments_name_key`，同步 database/schema.sql。
- Codex 评审（第三轮）：未发现新阻断问题，代码审查通过，可以进入合并前环境验证。
- 环境验证（Claude Code VS Code）：vue-tsc 通过、Vite build 通过、后端 40/40 测试通过、Alembic upgrade → downgrade → re-upgrade 完整周期通过、种子数据 11 个科室正确载入。
- 项目所有者已授权推送和合并；任务分支已推送，合并提交为 `c00e1cf`。
- 当前状态：任务已完成。

#### 评审交接信息

```text
请评审任务 department-filter-001。

实现者：Claude-Code
评审者：Codex
分支：claude/department-filter-001
基线：main
提交：bb4a18f..1946ccd
方案：docs/superpowers/specs/2026-07-28-department-filter-design.md
验收条件：见本任务"验收条件"部分
重点检查：数据库迁移安全性、检索过滤正确性、向后兼容性（不选科室=全库检索）、校验边界（停用/不存在科室的处理）

只输出评审意见，不直接修改实现提交。
```

## 终止状态归档规则

- 合并完成后将任务状态改为 `completed`，保留到下一次协调整理时再移入项目历史记录或删除。
- 取消任务使用 `cancelled`，必须记录取消原因。
- 不得删除仍处于非终止状态的任务记录。
