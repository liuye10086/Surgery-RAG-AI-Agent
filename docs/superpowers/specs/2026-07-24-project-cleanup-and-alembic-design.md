# 项目清理与 Alembic 接入设计

## 1. 目标

在不破坏现有 Surgery RAG Agent 功能和运行数据的前提下：

- 删除可重新生成、已经过时或确认没有调用者的文件与代码。
- 将前端包管理器统一为 npm，消除 pnpm 混合依赖状态。
- 使用 Alembic 完全管理业务数据库结构和后续迁移。
- 保留当前知识库原始文档、图片、评测数据集以及必要的架构依据。
- 清理后通过后端测试、前端构建、空数据库迁移和真实 RAG 基线验证。

本次采用保守清理原则：只有能够证明无调用者、可重新生成或已经由新实现替代的内容才删除。用途不明确、可能属于外部兼容接口或第三方间接依赖的内容不删除。

## 2. 清理边界

### 2.1 删除的文件和目录

- `.superpowers/sdd/`：Superpowers M5 执行过程报告，正式设计和计划已有独立文档保存。
- `.vscode/`：个人编辑器偏好，不参与项目运行。
- `scripts/verify_2a.py`：早期一次性端到端脚本，依赖旧的 `chunks.embedding` 架构，已被测试套件和 RAG 评测替代。
- `evaluation/rag_baseline_10_report.json`：某次评测结果快照，可由数据集和脚本重新生成。
- `docs/superpowers/specs/2026-07-22-m5-design.md`：已完成且内容被当前代码、规划和最新安全设计覆盖。
- `docs/superpowers/plans/2026-07-22-m5-implementation.md`：已完成的详细执行过程，不再作为当前实施入口。
- `frontend/pnpm-lock.yaml`、`frontend/pnpm-workspace.yaml`：项目统一使用 npm。
- 当前 `frontend/node_modules/`：pnpm 与 npm 混合安装状态，删除后使用 `npm ci` 重建。
- 当前 `frontend/dist/`：构建产物，删除后由生产构建重新生成。
- 项目内所有 `__pycache__/` 和 `.pyc`：Python 运行缓存，可自动重建。

### 2.2 保留的文件和目录

- `uploads/`：当前数据库正在引用的知识库原始文档和病例图片，完整保留并继续由 `.gitignore` 排除。
- `.git/`：当前为空，保留给后续 `git init` 使用；本次不初始化仓库。
- `.agents/`、`.claude/`：分别供 Codex 和 Claude Code 使用。
- `scripts/check_documents.py`：上传前文档检查和上传故障排查工具。
- `scripts/create_admin.py`：正式管理员创建入口。
- `scripts/evaluate_rag.py` 和 `evaluation/rag_baseline_10.json`：RAG 回归验证入口和基线数据集。
- `database/migrations/006_*`、`007_*`、`008_*`：已有手工 SQL 迁移的历史资料，不再作为新部署入口。
- 最新安全加固与版本化索引的设计和实施计划。
- `docs/MVP开发计划.md`、`docs/项目规划.md`：保留项目路线和背景，但修正已过时的操作说明。
- `database/schema.sql`：保留为当前业务结构的参考快照，不作为正式迁移入口。

## 3. 无用代码清理

### 3.1 删除旧消息写入链路

删除以下内容：

- 前端 `frontend/src/api/chat.ts` 中未调用的 `createMessage()`。
- 后端 `POST /api/v1/chat/sessions/{session_id}/messages` 接口。
- 仅供该接口使用的 `MessageCreate` 请求模型。

当前唯一的用户提问写入路径为 `/ask`：输入安全检查通过后，由后端使用 `persist_user_message()` 保存，并通过 `client_request_id` 保证幂等。删除旧接口可减少绕开统一幂等流程的入口。

### 3.2 删除已被替代的向量工具

删除 `backend/app/rag/vectorstore.py` 中：

- `delete_chunks()`：只删除旧数字 ID，已由兼容新旧 ID 的 `delete_chunk_vectors()` 替代。
- `delete_collection()`：当前没有调用者，且误用会清空整个知识库向量集合。

### 3.3 删除未接入的占位能力

删除 `backend/app/ingestion/parser.py` 中未被解析流程调用的 `deidentify_text()`。文档中继续明确：当前系统尚未实现自动医疗数据脱敏，未来需要接入 Presidio、医疗 NER 或经过验证的规则方案后再增加真实处理链路。

### 3.4 删除未使用的模型和导出

- 删除 `backend/app/schemas/user.py` 中未使用的 `UserCreate`，保留 `UserBase` 和 `UserOut`。
- 删除 `backend/app/schemas/document.py` 中未使用的 `DocumentStatus`。
- 清空 `backend/app/schemas/__init__.py` 的集中导出内容，保留空文件作为 Python 包标记。
- 删除静态分析确认的未使用导入，包括管理接口、聊天接口、用户接口、安全模块、解析器、内容过滤和文档检查脚本中的冗余导入。
- `backend/app/api/__init__.py` 的导入用于包级路由加载，保留。

## 4. npm 环境统一

`frontend/package-lock.json` 作为唯一前端锁文件。清理旧依赖后执行：

```powershell
cd frontend
npm ci
npm run build
```

`npm ci` 必须严格按照 `package-lock.json` 安装，不自动改变依赖版本。构建后允许重新产生 `frontend/dist/`，但它仍属于可重新生成产物并继续由 `.gitignore` 排除。

不再保留 pnpm 配置、pnpm 锁文件或 `.pnpm` 依赖结构。

## 5. Alembic 架构

### 5.1 管理范围

Alembic 完全管理：

- PostgreSQL 扩展：`vector`、`uuid-ossp`、`pg_trgm`。
- 业务表：`users`、`documents`、`chunks`、`sessions`、`messages`、`audit_logs`。
- 业务主键、外键、唯一约束和索引。
- 条件唯一索引 `uq_messages_session_client_request`。
- 组合索引 `idx_chunks_document_generation`。

Alembic 不管理：

- `langchain_pg_collection`。
- `langchain_pg_embedding`。
- LangChain 内部表的字段、约束和版本变化。

这两张内部表继续由 `langchain-postgres` 创建和维护。应用启动后的 `ensure_vectorstore_tables()` 继续为向量表补建中文全文检索所需的 pg_trgm 索引。

### 5.2 文件结构

新增：

```text
backend/
├── alembic.ini
└── alembic/
    ├── env.py
    ├── script.py.mako
    └── versions/
        ├── 0001_current_business_schema.py
        └── 0002_enforce_foreign_keys_and_indexes.py
```

`env.py` 从 `app.core.config.settings.DATABASE_URL` 读取数据库地址，以 `app.db.base.Base.metadata` 为目标元数据，并通过 `include_object` 排除以 `langchain_pg_` 开头的第三方内部表。

`0001` 显式创建扩展和与当前生产数据库完全一致的业务结构。`0002` 在验证无空外键数据后，将 `chunks.document_id`、`sessions.user_id`、`messages.session_id` 收紧为 `NOT NULL`，并补齐 ORM 声明的外键查询索引。两段迁移必须支持从空数据库顺序执行，不依赖 `database/schema.sql`。

### 5.3 新数据库流程

```powershell
cd backend
alembic upgrade head
```

该命令从空数据库创建全部业务结构，并在 `alembic_version` 表中记录版本。

应用首次启动或首次使用向量存储时，由 `langchain-postgres` 创建内部向量表。

### 5.4 当前数据库接入流程

当前数据库已经存在业务结构，但三个外键列的可空约束和部分索引与 ORM 不一致，不能直接标记到最终版本。实施时必须：

1. 只读核对当前业务表、字段、外键和关键索引与 `0001` 一致。
2. 检查 `chunks.document_id`、`sessions.user_id`、`messages.session_id` 是否存在空值。
3. 如果存在空值则停止，不自动删除或修改业务数据，并报告表名和空值数量。
4. `0001` 核对一致且无阻断数据后执行 `alembic stamp 0001`，只记录基线，不重复建表。
5. 执行 `alembic upgrade head`，由 `0002` 收紧约束并补齐索引。
6. 查询 `alembic current`，确认当前版本为 `head`。

不得通过删除表、清空数据或重建当前数据库来接入 Alembic。

### 5.5 旧 SQL 文件

`database/migrations/006_*`、`007_*`、`008_*` 继续作为历史记录保存。部署文档明确说明：

- 旧环境若已经执行这些 SQL，通过结构核对后使用 `alembic stamp head`。
- 新环境不再逐个执行 SQL，直接使用 `alembic upgrade head`。
- 从本次接入后的下一次结构变更开始，只新增 Alembic revision。

## 6. 文档同步

需要更新：

- `README.md`：前端统一 npm；数据库初始化改为 Alembic；保留管理员创建和 RAG 评测命令。
- `docs/DEPLOY.md`：新数据库、现有数据库基线、升级和回退流程；`schema.sql` 降级为参考快照。
- `database/README.md`：Alembic 成为正式迁移入口；旧 SQL 为历史资料。
- `docs/MVP开发计划.md`、`docs/项目规划.md`：删除对 `verify_2a.py`、占位脱敏钩子和旧手工迁移流程的现行描述；未来脱敏仍作为明确待办保留。

所有文档继续使用中文。

## 7. 验证策略

### 7.1 静态与单元验证

- 运行完整后端单元测试。
- 运行 Python `compileall`。
- 运行前端 TypeScript 类型检查和 Vite 生产构建。
- 搜索并确认被删除函数、模型、pnpm 文件和旧脚本没有残余引用。

### 7.2 Alembic 验证

- 创建隔离的临时 PostgreSQL 数据库。
- 对临时空数据库执行 `alembic upgrade head`。
- 检查六张业务表、扩展、外键和关键索引。
- 对临时数据库执行 `alembic downgrade base`，确认业务结构可回退；第三方 LangChain 表不在 Alembic 回退范围内。
- 再次执行 `alembic upgrade head`，确认迁移可重复应用到干净状态。
- 删除临时验证数据库。

### 7.3 当前数据库基线

- 只读结构核对通过后执行 `alembic stamp head`。
- 不修改现有业务数据和向量数据。
- 验证 `alembic current` 与 `alembic heads` 一致。

### 7.4 业务回归

- 运行 `scripts/evaluate_rag.py --dataset evaluation/rag_baseline_10.json`，目标为 10/10。
- 核对 `uploads/` 文件数量和路径未变化。
- 前端使用 `npm ci` 安装后的实际环境完成构建。

## 8. 错误处理与恢复

- 删除前记录目标文件清单和大小，任何超出清单的文件都不删除。
- `uploads/`、`backend/.env` 和当前数据库不属于清理目标。
- npm 安装或构建失败时保留错误现场，不切换回 pnpm。
- 临时数据库验证失败时删除临时数据库，不对当前数据库执行 `stamp`。
- 当前数据库与 `0001` 的结构核对失败时停止基线接入并报告具体差异。
- 三个待收紧外键列存在空值时停止升级，不自动修复或删除数据。
- 当前目录没有有效 Git 历史，因此不能依靠 Git 恢复；所有删除必须严格限定在本设计列出的目标内。

## 9. 完成标准

满足以下条件才视为清理完成：

- 所有已确认的无用文件和代码已删除，没有删除运行数据。
- 项目不再包含 pnpm 配置和 pnpm 安装痕迹，前端可由 `npm ci` 重建。
- Alembic 可从空数据库创建完整业务结构。
- 当前数据库已在结构一致的前提下完成 Alembic 基线标记。
- 后端测试、Python 编译、前端类型检查和生产构建全部通过。
- RAG 基线评测保持 10/10。
- README、部署文档、数据库说明和项目规划与实际流程一致。
