# 开发与测试环境基线设计

## 1. 目标

为 Codex、Claude Code 和项目所有者建立一套可重复执行、结果可比较的 Windows 本地开发基线，避免将既有环境故障误判为新代码回归。

本设计需要保证：

- 两个 Agent 使用相同的 Python、Node.js、依赖安装和验证入口。
- 仓库文档保持可移植，不提交个人绝对路径、密钥或数据库连接串。
- 数据库验证不删除、清空、重建或持久修改现有数据。
- 外部 LLM、模型下载、OCR 和文档索引默认不参与基线验证。
- 基线结果明确区分通过、失败、跳过和阻塞，不用模糊描述替代证据。

## 2. 已确认的本机运行时

本机已存在可用运行时，不安装新的 Python 或 Node.js：

- Python 3.11.4：项目后端的固定开发版本。
- Python 3.14.2：保留但不用于本项目，避免 AI、OCR 和科学计算依赖的兼容风险。
- Python 3.7：历史 Jupyter 环境，不用于本项目。
- Node.js 22.15.0：通过 NVM for Windows 管理，作为前端固定开发版本。
- npm 10.9.2：随 Node.js 22.15.0 使用。
- PostgreSQL 18.1：本地服务已运行，高于项目要求的 15+。
- pgvector 0.8.3：本地 PostgreSQL 扩展文件已安装。

仓库文档只记录版本选择和通用命令，例如 `py -3.11`、`nvm use 22.15.0`。本机绝对路径只用于本地配置或执行时探测，不写入已提交文档。

## 3. 环境布局

### 3.1 后端

- 使用 Python 3.11 创建 `backend/.venv`。
- 所有 Python 依赖只安装到该虚拟环境，不安装到全局 Python。
- 依赖来源为 `backend/requirements.txt`。
- 激活虚拟环境后运行 `pytest`、Alembic 检查和后端启动命令。

### 3.2 前端

- 使用 NVM 激活 Node.js 22.15.0。
- 使用项目现有 `frontend/package-lock.json` 和 `npm ci` 重建 `frontend/node_modules`。
- 不引入 pnpm lockfile，不混用包管理器。
- 前端基线至少包含 TypeScript/Vue 检查和生产构建，即 `npm run build`。

### 3.3 PostgreSQL

- 使用当前本地数据库，不创建独立测试数据库。
- 允许读取被 Git 忽略的 `backend/.env` 中的 `DATABASE_URL`，但不得输出变量值、密码或完整连接串。
- 正式数据库结构入口是 `backend/alembic/`；`database/schema.sql` 仅作结构参考快照。
- 服务器部署时应对空数据库执行 `alembic upgrade head`，而不是将 `schema.sql` 作为正式重建流程。

## 4. 落地文件

### 4.1 `docs/DEVELOPMENT.md`

面向所有开发者和 Agent 的通用开发说明，包含：

- 固定运行时版本。
- Python 虚拟环境创建和依赖安装。
- Node.js 激活、`npm ci`、开发启动和构建命令。
- 后端测试、Alembic 状态检查和服务启动命令。
- 数据库安全边界。
- 基线脚本的使用方式和结果解释。
- Windows PowerShell 执行策略可能阻止 `.ps1` 脚本时，使用仅对当前进程生效的命令运行，不修改系统或用户执行策略：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/verify_baseline.ps1
```

该文档不得包含用户名、个人绝对路径、密码、API 密钥或完整数据库连接串。

### 4.2 `docs/coordination/BASELINE.md`

记录最近一次基线执行的可共享结果：

- 执行日期和任务编号。
- Python、Node.js、npm、PostgreSQL 和 pgvector 版本。
- 后端测试、前端构建和数据库检查的通过、失败或跳过状态。
- 失败摘要和跳过原因。
- 已知环境限制。
- 负责执行和复核的 Agent。

该文件只记录非敏感证据，不复制 `.env` 内容、数据库 URL、模型令牌或个人绝对路径。

### 4.3 `scripts/check_dev_environment.ps1`

只读环境检查脚本，职责包括：

- 发现 Python 3.11、Node.js 22.15.0、npm、PostgreSQL 客户端和 Git。
- 检查 `backend/.venv` 是否存在及其解释器版本。
- 检查 `frontend/node_modules` 的关键包和命令是否完整。
- 检查 `backend/.env` 是否存在，并按以下分类验证配置，但不输出任何值：
  - 连接必需：`DATABASE_URL` 必须存在，且不能保留 `.env.example` 的示例连接串。
  - 安全必需：`JWT_SECRET` 必须存在，且不能是 `change-me-in-production`、`your_jwt_secret_here` 等默认或示例值。
  - 基线可选：`DEEPSEEK_API_KEY`、`LANGCHAIN_API_KEY`、`HF_ENDPOINT` 和 `VECTOR_STORE_CONNECTION_STRING` 可以为空，因为外部服务与模型能力默认跳过，向量连接可复用 `DATABASE_URL`。
  - 其他配置：由 `Settings` 默认值和 Pydantic 类型加载验证，不要求全部显式写入 `.env`。
- 检查 PostgreSQL 服务和 pgvector 扩展可用性，但不输出连接凭据。
- 使用清晰退出码区分通过与失败。

脚本默认不得：

- 安装或卸载系统运行时。
- 修改 PATH、NVM 当前版本或系统服务。
- 安装项目依赖。
- 修改数据库、下载模型或调用外部 AI 服务。

如果需要修复环境，脚本只输出建议命令；实际安装和变更必须由项目所有者明确授权。

### 4.4 `scripts/verify_baseline.ps1`

统一验证入口，顺序执行：

1. 调用环境检查脚本。
2. 使用 `backend/.venv` 运行后端测试。
3. 使用 Node.js 22.15.0 和 npm 10.9.2 执行前端构建。
4. 对当前数据库执行第 5.1 节规定的只读检查；只有实施计划明确需要且能够证明回滚有效时，才附加第 5.2 节的可回滚事务测试。
5. 汇总通过、失败、跳过和阻塞项。

脚本默认不自动安装依赖。只有显式参数允许时，才可以在项目目录中执行 `backend/.venv` 创建、Python 依赖安装和 `npm ci`；即使允许，也不能安装新的系统运行时。

## 5. 数据库验证边界

### 5.1 允许的只读检查

- PostgreSQL 服务和服务器版本。
- 当前数据库连接是否成功。
- `vector`、`uuid-ossp`、`pg_trgm` 扩展是否存在及其版本。
- Alembic 当前 revision 与代码中的 head 是否一致。
- 必需业务表和关键列是否存在。
- 不修改状态的简单查询。

### 5.2 可回滚事务测试

确需验证写入路径时，必须：

- 显式开始事务。
- 使用不会与真实业务记录冲突的临时标识。
- 不执行 DDL、迁移、批量索引或文件写入。
- 在 `finally` 中无条件回滚。
- 回滚后执行只读查询，确认临时记录不存在。

如果无法证明回滚有效，则跳过写入测试并记录原因，不能冒险使用现有数据库。

### 5.3 禁止操作

- 删除、清空、重建数据库或业务表。
- 执行 `DROP`、`TRUNCATE`、破坏性 `DELETE` 或不可逆迁移。
- 直接用 `database/schema.sql` 覆盖当前结构。
- 修改 PostgreSQL 配置、用户权限或密码。
- 上传、重新解析、重新向量化或重新索引现有文档。

## 6. 外部依赖与重型能力

默认基线不得：

- 调用 DeepSeek 或其他外部 LLM。
- 使用或输出 API 密钥。
- 下载 BGE-M3、PaddleOCR 或其他模型。
- 执行依赖 GPU 的验证。
- 运行会访问外部网络的集成测试。

若某些测试在导入阶段强制加载模型，基线应优先通过测试隔离、mock 或显式跳过来避免下载；是否修改测试结构需在实施计划中单独说明，不能在基线任务中顺带重构业务代码。

## 7. 结果模型

每个检查项必须归入以下状态之一：

- `PASS`：命令成功，结果满足明确条件。
- `FAIL`：命令执行完成，但结果不满足条件。
- `SKIP`：按安全边界或缺少非必需能力主动跳过，并记录原因。
- `BLOCKED`：缺少完成基线所必需的依赖、权限或配置，无法继续。

脚本总体退出规则：

- 全部必需项为 `PASS`，允许退出码 `0`。
- 存在 `FAIL` 或 `BLOCKED`，退出码非 `0`。
- 只有已声明的可选项为 `SKIP` 时，可保持退出码 `0`，但摘要必须列出跳过项。

Agent 不得把 `SKIP` 描述成通过，也不得在依赖未安装或命令未执行时宣称基线成功。

## 8. 标准执行流程

> 本节流程遵循 `AI_COLLABORATION.md` 的多角色协作规范，任务登记使用 `docs/coordination/TASK_TEMPLATE.md` 模板。

1. 在协调工作区登记 `development-baseline-001`，标记为普通风险文档与环境任务。
2. 从最新 `main` 创建 `codex/development-baseline-001` 独立 worktree。
3. 创建脚本与文档，先验证只读检查逻辑。
4. 经项目所有者授权后，仅在项目目录中创建 `backend/.venv`、安装 Python 依赖并执行 `npm ci`。
5. 运行环境检查、后端测试、前端构建和数据库安全检查。
6. 将实际结果写入 `docs/coordination/BASELINE.md`。
7. 创建带 Agent 留痕的本地提交，由项目所有者审核。
8. 审核通过后分别请求推送和合并授权。

## 9. Agent 使用规则

- 普通或高风险任务开始前，应运行统一基线命令，或引用足够新的基线结果。
- 如果基线在未修改代码的状态下失败，新任务不得把该失败归因于自己的变更。
- 如果新任务修改依赖、数据库迁移、构建配置或测试入口，完成后必须更新基线文档。
- 基线脚本发现必需项 `BLOCKED` 时，活动任务应记录阻塞原因，由项目所有者决定修复环境或继续有限范围工作。

## 10. 验收标准

- 仓库提供统一、非破坏性的 PowerShell 环境检查和基线验证入口。
- Python 固定为 3.11，Node.js 固定为 22.15.0，不安装重复运行时。
- 后端依赖仅存在于 `backend/.venv`，前端依赖通过 npm lockfile 恢复。
- 文档不包含个人绝对路径、秘密值或完整数据库连接串。
- 数据库检查只读或能够证明无条件回滚，不修改现有业务数据。
- DeepSeek、模型下载、OCR 和文档索引默认跳过。
- 基线报告明确区分 `PASS`、`FAIL`、`SKIP` 和 `BLOCKED`。
- 后续 Agent 能够用同一命令重复验证环境和项目状态。
