# 项目清理与 Alembic 接入实施计划

> **供执行代理使用：** 必须使用 `subagent-driven-development`（推荐）或 `executing-plans`，按任务逐项实施本计划。所有步骤使用复选框跟踪。

**目标：** 删除已经确认的无用文件和代码，将前端统一为 npm，并让 Alembic 从空数据库完整创建业务结构、让现有数据库安全接入迁移链。

**架构：** 清理工作分为可证明的死代码删除、可重新生成文件清理、npm 依赖重建、Alembic 两段迁移和文档同步五部分。`0001` 精确描述当前数据库结构，`0002` 在验证无空外键数据后收紧三个外键列并补齐五个查询索引；LangChain 内部向量表始终由 `langchain-postgres` 管理。

**技术栈：** Python 3.11、FastAPI、SQLAlchemy、Alembic、PostgreSQL 18、Vue 3、TypeScript、npm、Vite、LangChain PGVector。

## 全局约束

- 所有说明、计划、迁移注释和最终汇报使用中文。
- 不删除或改写 `uploads/`、`backend/.env` 和现有业务数据。
- 不初始化 Git，不删除空 `.git/`，不执行提交步骤。
- 保留 `.agents/`、`.claude/`、旧 SQL 迁移 006/007/008、最新安全设计和计划。
- 前端只使用 npm；`package-lock.json` 是唯一锁文件。
- Alembic 不管理 `langchain_pg_collection` 和 `langchain_pg_embedding`。
- 当前数据库若存在空外键数据或与 `0001` 不一致，停止基线接入，不自动修复或删除数据。
- 删除目录前必须解析绝对路径，并确认目标位于项目目录且与本计划清单完全一致。
- UI 视觉样式不在本次范围内；若意外涉及 UI，必须遵守 `docs/DESIGN_SPEC.md`。

---

## 文件职责规划

### 新增文件

- `backend/alembic.ini`：Alembic 命令入口和日志配置。
- `backend/alembic/env.py`：加载项目配置与 ORM metadata，排除 LangChain 内部表。
- `backend/alembic/script.py.mako`：迁移文件模板。
- `backend/alembic/versions/0001_current_business_schema.py`：当前真实业务结构基线，同时支持空库建表。
- `backend/alembic/versions/0002_enforce_foreign_keys_and_indexes.py`：外键非空约束和五个外键索引。
- `backend/tests/test_cleanup_contracts.py`：确认旧接口、死代码和过时文件不再存在。
- `backend/tests/test_alembic_contracts.py`：验证 Alembic 配置、迁移链、表管理边界和 ORM 索引声明。

### 修改文件

- `backend/app/api/chat.py`：删除旧手动消息写入接口和冗余导入。
- `backend/app/schemas/chat.py`：删除 `MessageCreate` 和不再需要的 `Literal`。
- `frontend/src/api/chat.ts`：删除 `createMessage()`。
- `backend/app/rag/vectorstore.py`：删除两个旧向量删除函数。
- `backend/app/ingestion/parser.py`：删除未接入的脱敏占位函数和冗余导入。
- `backend/app/schemas/user.py`：删除 `UserCreate`。
- `backend/app/schemas/document.py`：删除 `DocumentStatus` 和 `Enum`。
- `backend/app/schemas/__init__.py`：清空集中导出，保留包标记。
- `backend/app/db/models.py`：去掉冗余的主键/唯一字段 `index=True`，显式声明五个有价值的外键索引。
- `backend/app/api/admin.py`、`backend/app/api/user.py`、`backend/app/core/security.py`、`backend/app/services/content_filter.py`、`scripts/check_documents.py`：清理已确认的未使用导入。
- `README.md`、`docs/DEPLOY.md`、`database/README.md`、`docs/MVP开发计划.md`、`docs/项目规划.md`：同步 npm、Alembic、脚本和脱敏现状。
- `database/schema.sql`：保留参考快照，并同步三个非空外键和五个外键索引。

### 删除文件和目录

- `.superpowers/sdd/`
- `.vscode/`
- `scripts/verify_2a.py`
- `evaluation/rag_baseline_10_report.json`
- `docs/superpowers/specs/2026-07-22-m5-design.md`
- `docs/superpowers/plans/2026-07-22-m5-implementation.md`
- `frontend/pnpm-lock.yaml`
- `frontend/pnpm-workspace.yaml`
- 清理时存在的 `frontend/node_modules/`
- 清理时存在的 `frontend/dist/`
- 项目内所有 `__pycache__/` 和 `.pyc`

---

### 任务 1：建立清理行为回归测试

**文件：**

- 新建：`backend/tests/test_cleanup_contracts.py`
- 新建：`backend/tests/test_alembic_contracts.py`

**接口：**

- 使用源码和文件系统契约验证清理结果。
- 不连接生产数据库，不依赖前端依赖已经安装。

- [ ] **步骤 1：编写清理契约测试**

`backend/tests/test_cleanup_contracts.py` 写入：

```python
import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _class_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}


class CleanupContractTests(unittest.TestCase):
    def test_removed_files_do_not_exist(self):
        removed = [
            ".superpowers/sdd",
            ".vscode",
            "scripts/verify_2a.py",
            "evaluation/rag_baseline_10_report.json",
            "docs/superpowers/specs/2026-07-22-m5-design.md",
            "docs/superpowers/plans/2026-07-22-m5-implementation.md",
            "frontend/pnpm-lock.yaml",
            "frontend/pnpm-workspace.yaml",
        ]
        for relative_path in removed:
            self.assertFalse((PROJECT_ROOT / relative_path).exists(), relative_path)

    def test_old_chat_and_vector_functions_are_removed(self):
        chat_api = _function_names(PROJECT_ROOT / "backend/app/api/chat.py")
        frontend_chat = (
            PROJECT_ROOT / "frontend/src/api/chat.ts"
        ).read_text(encoding="utf-8")
        vectorstore = _function_names(PROJECT_ROOT / "backend/app/rag/vectorstore.py")
        parser = _function_names(PROJECT_ROOT / "backend/app/ingestion/parser.py")

        self.assertNotIn("create_message", chat_api)
        self.assertNotIn("createMessage", frontend_chat)
        self.assertNotIn("delete_chunks", vectorstore)
        self.assertNotIn("delete_collection", vectorstore)
        self.assertNotIn("deidentify_text", parser)

    def test_unused_schema_types_are_removed(self):
        chat_types = _class_names(PROJECT_ROOT / "backend/app/schemas/chat.py")
        user_types = _class_names(PROJECT_ROOT / "backend/app/schemas/user.py")
        document_types = _class_names(PROJECT_ROOT / "backend/app/schemas/document.py")

        self.assertNotIn("MessageCreate", chat_types)
        self.assertNotIn("UserCreate", user_types)
        self.assertNotIn("DocumentStatus", document_types)

    def test_runtime_data_and_tools_remain(self):
        self.assertTrue((PROJECT_ROOT / "uploads").is_dir())
        self.assertTrue((PROJECT_ROOT / "scripts/check_documents.py").is_file())
        self.assertTrue((PROJECT_ROOT / "scripts/create_admin.py").is_file())
        self.assertTrue((PROJECT_ROOT / "scripts/evaluate_rag.py").is_file())
        self.assertTrue((PROJECT_ROOT / "evaluation/rag_baseline_10.json").is_file())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **步骤 2：编写 Alembic 契约测试**

`backend/tests/test_alembic_contracts.py` 写入：

```python
import importlib.util
import unittest
from pathlib import Path

from app.db.models import AuditLog, Chunk, Message, Session


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _load_revision(filename: str, module_name: str):
    path = BACKEND_ROOT / "alembic/versions" / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class AlembicContractTests(unittest.TestCase):
    def test_alembic_files_exist(self):
        for relative_path in [
            "alembic.ini",
            "alembic/env.py",
            "alembic/script.py.mako",
            "alembic/versions/0001_current_business_schema.py",
            "alembic/versions/0002_enforce_foreign_keys_and_indexes.py",
        ]:
            self.assertTrue((BACKEND_ROOT / relative_path).is_file(), relative_path)

    def test_revision_chain_is_linear(self):
        baseline = _load_revision(
            "0001_current_business_schema.py", "migration_0001"
        )
        hardening = _load_revision(
            "0002_enforce_foreign_keys_and_indexes.py", "migration_0002"
        )
        self.assertEqual(baseline.revision, "0001")
        self.assertIsNone(baseline.down_revision)
        self.assertEqual(hardening.revision, "0002")
        self.assertEqual(hardening.down_revision, "0001")

    def test_env_excludes_langchain_internal_tables(self):
        env_source = (BACKEND_ROOT / "alembic/env.py").read_text(encoding="utf-8")
        self.assertIn('name.startswith("langchain_pg_")', env_source)

    def test_foreign_key_indexes_are_declared_in_orm(self):
        expected = {
            "ix_chunks_document_id",
            "ix_sessions_user_id",
            "ix_messages_session_id",
            "ix_audit_logs_user_id",
            "ix_audit_logs_session_id",
        }
        actual = {
            index.name
            for table in (Chunk.__table__, Session.__table__, Message.__table__, AuditLog.__table__)
            for index in table.indexes
        }
        self.assertTrue(expected.issubset(actual))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **步骤 3：运行测试并确认按预期失败**

运行：

```powershell
cd backend
$env:PYTHONPATH='.'
python -m unittest discover -s tests -p 'test_cleanup_contracts.py' -v
python -m unittest discover -s tests -p 'test_alembic_contracts.py' -v
```

预期：清理测试因待删除文件和函数仍存在而失败；Alembic 测试因配置和迁移文件尚不存在而失败。

---

### 任务 2：删除旧接口、死代码和冗余模型

**文件：**

- 修改：`backend/app/api/chat.py`
- 修改：`backend/app/schemas/chat.py`
- 修改：`frontend/src/api/chat.ts`
- 修改：`backend/app/rag/vectorstore.py`
- 修改：`backend/app/ingestion/parser.py`
- 修改：`backend/app/schemas/user.py`
- 修改：`backend/app/schemas/document.py`
- 修改：`backend/app/schemas/__init__.py`
- 修改：`backend/app/api/admin.py`
- 修改：`backend/app/api/user.py`
- 修改：`backend/app/core/security.py`
- 修改：`backend/app/services/content_filter.py`
- 修改：`scripts/check_documents.py`
- 测试：`backend/tests/test_cleanup_contracts.py`

**接口：**

- 保留 `/ask`、`persist_user_message()`、`delete_chunk_vectors()` 和真实解析流程。
- 删除旧 `/messages` 路由及所有仅供旧路径使用的符号。

- [ ] **步骤 1：删除旧消息接口**

在 `backend/app/api/chat.py`：

- 从 schema 导入中删除 `MessageCreate`、`MessageOut` 之外仅属于旧端点的引用。
- 删除整个 `create_message()` 路由函数。
- 删除未使用的 `AIMessage` 导入。
- 将“前端先保存用户消息”等旧注释改为“用户消息由 `/ask` 在安全过滤通过后保存”。

在 `backend/app/schemas/chat.py`：

- 删除 `MessageCreate` 类。
- 把 `from typing import List, Literal, Optional` 改为 `from typing import List, Optional`。

在 `frontend/src/api/chat.ts` 删除：

```typescript
export function createMessage(sessionId: number, role: string, content: string): Promise<Message> {
  return request.post(`/v1/chat/sessions/${sessionId}/messages`, { role, content })
}
```

- [ ] **步骤 2：删除被替代的向量函数**

从 `backend/app/rag/vectorstore.py` 删除完整的 `delete_chunks()` 和 `delete_collection()`，保留：

```python
def delete_chunk_vectors(store: PGVector, chunks) -> None:
    """删除代次化向量，同时兼容清理旧版数字 ID。"""
    chunks = list(chunks)
    if not chunks:
        return
    ids = [vector_id_for_chunk(chunk) for chunk in chunks]
    ids.extend(str(chunk.id) for chunk in chunks)
    store.delete(ids=ids)
    logger.info("Deleted vectors for %d business chunks", len(chunks))
```

- [ ] **步骤 3：删除占位脱敏函数和无用模型**

- 从 `backend/app/ingestion/parser.py` 删除 `deidentify_text()`，不改变任何 `parse_*` 函数。
- 从 `backend/app/schemas/user.py` 删除 `UserCreate`。
- 从 `backend/app/schemas/document.py` 删除 `DocumentStatus` 和 `Enum` 导入。
- 清空 `backend/app/schemas/__init__.py`，保留空文件。

- [ ] **步骤 4：清理静态分析确认的未使用导入**

精确删除：

- `backend/app/api/admin.py`：`os`、`Path`、`List`、`settings`、`ImageRef`。
- `backend/app/api/user.py`：`Message`。
- `backend/app/core/security.py`：`JWTError`。
- `backend/app/ingestion/parser.py` 的 `_extract_docx_images()`：`qn`。
- `backend/app/services/content_filter.py`：`field`。
- `scripts/check_documents.py`：`scrolledtext`。

不要修改 `backend/app/api/__init__.py` 和空包 `__init__.py`。

- [ ] **步骤 5：运行清理契约和现有后端测试**

运行：

```powershell
cd backend
$env:PYTHONPATH='.'
python -m unittest discover -s tests -p 'test_cleanup_contracts.py' -v
python -m unittest discover -s tests -v
```

预期：代码相关契约通过；文件删除相关断言仍会等到任务 5 才全部通过；现有业务测试无回归。

---

### 任务 3：对齐 ORM 索引声明和参考 schema

**文件：**

- 修改：`backend/app/db/models.py`
- 修改：`database/schema.sql`
- 测试：`backend/tests/test_alembic_contracts.py`

**接口：**

- ORM metadata 是 Alembic 自动比对的唯一业务结构来源。
- 只保留唯一约束、条件唯一索引和有查询价值的外键索引。

- [ ] **步骤 1：调整 ORM 索引声明**

在 `backend/app/db/models.py`：

- 所有主键列删除 `index=True`。
- `User.username`、`User.email` 保留 `unique=True`，删除 `index=True`，避免唯一约束和唯一索引重复表达。
- 给以下类增加或扩展 `__table_args__`：

```python
class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_document_id", "document_id"),
        Index("idx_chunks_document_generation", "document_id", "generation"),
    )


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (Index("ix_sessions_user_id", "user_id"),)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_session_id", "session_id"),
        Index(
            "uq_messages_session_client_request",
            "session_id",
            "client_request_id",
            unique=True,
            postgresql_where=text("client_request_id IS NOT NULL"),
        ),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_id", "user_id"),
        Index("ix_audit_logs_session_id", "session_id"),
    )
```

同时删除这些外键列自身的 `index=True`，避免重复声明。

- [ ] **步骤 2：同步 `database/schema.sql` 参考快照**

将三个列明确为非空：

```sql
document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE
user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE
```

在表创建完成后增加：

```sql
CREATE INDEX IF NOT EXISTS ix_chunks_document_id ON chunks(document_id);
CREATE INDEX IF NOT EXISTS ix_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS ix_messages_session_id ON messages(session_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_session_id ON audit_logs(session_id);
```

保留 `idx_chunks_document_generation` 和条件唯一索引。

- [ ] **步骤 3：运行 ORM 索引契约测试**

运行：

```powershell
cd backend
$env:PYTHONPATH='.'
python -m unittest tests.test_alembic_contracts.AlembicContractTests.test_foreign_key_indexes_are_declared_in_orm -v
```

如果 `tests` 不是包，使用：

```powershell
python -m unittest discover -s tests -p 'test_alembic_contracts.py' -v
```

预期：索引声明断言通过，Alembic 文件存在性断言仍失败。

---

### 任务 4：建立 Alembic 两段迁移

**文件：**

- 新建：`backend/alembic.ini`
- 新建：`backend/alembic/env.py`
- 新建：`backend/alembic/script.py.mako`
- 新建：`backend/alembic/versions/0001_current_business_schema.py`
- 新建：`backend/alembic/versions/0002_enforce_foreign_keys_and_indexes.py`
- 测试：`backend/tests/test_alembic_contracts.py`

**接口：**

- `0001.revision == "0001"`，`down_revision is None`。
- `0002.revision == "0002"`，`down_revision == "0001"`。
- `env.py` 使用 `settings.DATABASE_URL`，并排除 `langchain_pg_*`。

- [ ] **步骤 1：创建 `backend/alembic.ini`**

使用标准 Alembic 配置，关键值固定为：

```ini
[alembic]
script_location = %(here)s/alembic
prepend_sys_path = .
path_separator = os

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

不要在文件中写数据库密码或固定连接串。

- [ ] **步骤 2：创建 `backend/alembic/env.py`**

实现以下完整行为：

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.db.base import Base
from app.db import models  # noqa: F401


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))
target_metadata = Base.metadata


def include_object(object_, name, type_, reflected, compare_to):
    if type_ == "table" and name.startswith("langchain_pg_"):
        return False
    return True


def run_migrations_offline():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **步骤 3：创建标准 `script.py.mako`**

模板必须生成 `revision`、`down_revision`、`branch_labels`、`depends_on`，并包含 `upgrade()`、`downgrade()`，使用 Alembic 默认 Python 模板，不加入业务逻辑。

- [ ] **步骤 4：创建 `0001_current_business_schema.py`**

`upgrade()` 顺序：

1. `op.execute('CREATE EXTENSION IF NOT EXISTS vector')`
2. `op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')`
3. `op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')`
4. 创建 `users`
5. 创建 `documents`
6. 创建 `chunks`，其中 `document_id` 为 `nullable=True`
7. 创建 `sessions`，其中 `user_id` 为 `nullable=True`
8. 创建 `messages`，其中 `session_id` 为 `nullable=True`
9. 创建 `audit_logs`
10. 创建 `idx_chunks_document_generation`
11. 创建 `uq_messages_session_client_request`，使用：

```python
postgresql_where=sa.text("client_request_id IS NOT NULL")
```

字段类型、长度、默认值、外键删除规则必须逐项复制当前数据库取证结果和 `database/schema.sql`；不要创建任何 `langchain_pg_*` 表，也不要创建 `0002` 的五个外键索引。

`downgrade()` 反序删除条件索引、组合索引和六张业务表。扩展不删除，避免影响同数据库中的其他对象。

- [ ] **步骤 5：创建 `0002_enforce_foreign_keys_and_indexes.py`**

`upgrade()` 先阻断空值：

```python
for table_name, column_name in (
    ("chunks", "document_id"),
    ("sessions", "user_id"),
    ("messages", "session_id"),
):
    count = op.get_bind().execute(
        sa.text(
            f'SELECT COUNT(*) FROM "{table_name}" '
            f'WHERE "{column_name}" IS NULL'
        )
    ).scalar_one()
    if count:
        raise RuntimeError(
            f"无法收紧 {table_name}.{column_name}：存在 {count} 条空值记录"
        )
```

然后执行：

```python
op.alter_column("chunks", "document_id", existing_type=sa.Integer(), nullable=False)
op.alter_column("sessions", "user_id", existing_type=sa.Integer(), nullable=False)
op.alter_column("messages", "session_id", existing_type=sa.Integer(), nullable=False)
op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
op.create_index("ix_messages_session_id", "messages", ["session_id"])
op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
op.create_index("ix_audit_logs_session_id", "audit_logs", ["session_id"])
```

`downgrade()` 先删除五个索引，再把三个列恢复为 `nullable=True`。

- [ ] **步骤 6：运行 Alembic 契约测试**

运行：

```powershell
cd backend
$env:PYTHONPATH='.'
python -m unittest discover -s tests -p 'test_alembic_contracts.py' -v
```

预期：全部通过。

---

### 任务 5：删除已确认的文件、缓存和混合前端环境

**文件：**

- 删除：设计清单中的目录、文件、缓存和前端依赖。
- 保留：`uploads/`、`.git/`、`.agents/`、`.claude/`。

**接口：**

- 删除操作只针对显式绝对路径。
- `frontend/node_modules/` 会在任务 6 使用 npm 重建。

- [ ] **步骤 1：删除前验证目标路径**

对每个目标执行 `Resolve-Path`，确认都以项目根目录绝对路径开头。额外断言：

```powershell
Test-Path uploads
Test-Path backend\.env
Test-Path .agents
Test-Path .claude
```

预期全部为 `True`，且这些路径不进入删除列表。

- [ ] **步骤 2：删除明确文件和目录**

使用 PowerShell `Remove-Item -LiteralPath` 删除：

- `.superpowers/sdd`
- `.vscode`
- `scripts/verify_2a.py`
- `evaluation/rag_baseline_10_report.json`
- 两份 2026-07-22 M5 文档
- `frontend/pnpm-lock.yaml`
- `frontend/pnpm-workspace.yaml`
- `frontend/node_modules`
- `frontend/dist`

目录删除前再次检查解析后的绝对路径位于项目根目录；不要使用通配符进行递归删除。

- [ ] **步骤 3：删除 Python 缓存**

用单一 PowerShell 流程枚举项目内名为 `__pycache__` 的目录，逐个验证其绝对路径位于项目根目录，再使用 `Remove-Item -LiteralPath -Recurse -Force`。随后只在项目根目录内枚举 `.pyc` 文件并删除。

- [ ] **步骤 4：运行清理契约测试**

运行：

```powershell
cd backend
$env:PYTHONPATH='.'
python -m unittest discover -s tests -p 'test_cleanup_contracts.py' -v
```

预期：全部通过。

---

### 任务 6：使用 npm 重建前端环境

**文件：**

- 保留：`frontend/package.json`
- 保留：`frontend/package-lock.json`
- 生成：`frontend/node_modules/`
- 生成：`frontend/dist/`

**接口：**

- 唯一安装命令为 `npm ci`。
- 不使用 pnpm，不生成 pnpm 配置。

- [ ] **步骤 1：确认锁文件状态**

```powershell
Test-Path frontend\package-lock.json
Test-Path frontend\pnpm-lock.yaml
Test-Path frontend\pnpm-workspace.yaml
```

预期依次为 `True`、`False`、`False`。

- [ ] **步骤 2：安装 npm 依赖**

运行：

```powershell
cd frontend
npm ci
```

预期：退出码 0；`node_modules/.pnpm` 和 `node_modules/.ignored` 不存在。

- [ ] **步骤 3：运行类型检查和生产构建**

运行：

```powershell
npx vue-tsc --noEmit
npm run build
```

预期：类型检查和构建退出码均为 0。允许保留现有的大包体积警告，但不得有编译错误。

---

### 任务 7：验证 Alembic 可从空数据库完整建库

**文件：**

- 使用：`backend/alembic.ini`
- 使用：`backend/alembic/versions/0001_current_business_schema.py`
- 使用：`backend/alembic/versions/0002_enforce_foreign_keys_and_indexes.py`

**接口：**

- 临时数据库名称使用随机后缀，例如 `surgery_rag_alembic_test_<8位十六进制>`。
- 只使用本机 PostgreSQL 管理连接创建和删除临时数据库。

- [ ] **步骤 1：解析当前连接但不输出密码**

从 `backend/.env` 读取 `DATABASE_URL`，通过 URI 解析获得主机、端口、用户和维护数据库。日志只输出临时数据库名，不输出完整连接串或密码。

- [ ] **步骤 2：创建隔离临时数据库**

使用 `createdb` 或 `psql` 创建随机命名数据库。创建后用 `SELECT current_database()` 确认连接目标正确。

- [ ] **步骤 3：在临时数据库执行升级**

临时设置本进程 `DATABASE_URL` 指向临时数据库，然后运行：

```powershell
cd backend
alembic upgrade head
```

预期：依次执行 `0001` 和 `0002`，退出码 0。

- [ ] **步骤 4：验证结构和管理边界**

查询并确认：

- 六张业务表和 `alembic_version` 存在。
- 三个外键列均为 `NOT NULL`。
- 五个外键索引、`idx_chunks_document_generation`、`uq_messages_session_client_request` 存在。
- `vector`、`uuid-ossp`、`pg_trgm` 扩展存在。
- `langchain_pg_collection`、`langchain_pg_embedding` 未由 Alembic 创建。
- `alembic_version.version_num = '0002'`。

- [ ] **步骤 5：验证降级和重新升级**

运行：

```powershell
alembic downgrade base
alembic upgrade head
```

预期：两条命令均退出 0；重新升级后结构验证仍通过。

- [ ] **步骤 6：删除临时数据库**

先终止仅属于该临时数据库的连接，再删除精确随机数据库名。不得删除当前业务数据库。

---

### 任务 8：让现有数据库安全接入 Alembic

**文件：**

- 使用：`backend/.env`
- 使用：Alembic 两段迁移。

**接口：**

- 当前数据库只在结构核对成功且空值计数为 0 后写入 Alembic 版本。
- 不删除、不重建任何现有业务表或向量表。

- [ ] **步骤 1：核对当前数据库与 `0001`**

只读查询六张业务表的字段、类型、可空性、默认值、外键和已有索引，必须与 `0001` 完全一致。允许存在 Alembic 不管理的 LangChain 表和向量全文索引。

- [ ] **步骤 2：检查三个外键列空值**

执行：

```sql
SELECT COUNT(*) FROM chunks WHERE document_id IS NULL;
SELECT COUNT(*) FROM sessions WHERE user_id IS NULL;
SELECT COUNT(*) FROM messages WHERE session_id IS NULL;
```

预期全部为 0。任意结果非 0 时停止任务，不执行 `stamp`。

- [ ] **步骤 3：标记基线并升级**

运行：

```powershell
cd backend
alembic stamp 0001
alembic upgrade head
```

预期：`stamp` 不创建业务表；`upgrade` 只执行 `0002`。

- [ ] **步骤 4：验证现有数据库最终状态**

运行：

```powershell
alembic current
alembic heads
```

两者都应指向 `0002`。再次查询三个非空约束和五个索引，并确认业务表记录数及 `langchain_pg_embedding` 记录数没有减少。

---

### 任务 9：同步项目文档

**文件：**

- 修改：`README.md`
- 修改：`docs/DEPLOY.md`
- 修改：`database/README.md`
- 修改：`docs/MVP开发计划.md`
- 修改：`docs/项目规划.md`

**接口：**

- 新部署只使用 `alembic upgrade head`。
- 旧 SQL 迁移明确标记为历史资料。
- 当前未实现自动脱敏必须写明，不得暗示已有能力。

- [ ] **步骤 1：更新 README**

将数据库初始化改为：

```powershell
cd backend
alembic upgrade head
```

将前端安装固定为：

```powershell
cd frontend
npm ci
npm run dev
```

保留 `python scripts/create_admin.py` 和 `python scripts/evaluate_rag.py`。

- [ ] **步骤 2：更新部署文档**

`docs/DEPLOY.md` 增加四段明确流程：

1. 新数据库：`alembic upgrade head`。
2. 已执行旧 SQL 的数据库：结构核对、空值检查、`alembic stamp 0001`、`alembic upgrade head`。
3. 日常升级：备份后执行 `alembic upgrade head`。
4. 回退：先在测试环境验证，再执行指定 revision；禁止在未备份的生产库直接降级。

把 `schema.sql` 描述为参考快照，不再作为正式部署入口。

- [ ] **步骤 3：更新数据库说明**

`database/README.md` 明确：

- 正式迁移入口在 `backend/alembic/`。
- 006/007/008 是 Alembic 接入前的历史 SQL。
- LangChain 内部表由库管理。
- `schema.sql` 只用于查看最终业务结构。

表数量修正为六张业务表，不再写“7 张业务表”。

- [ ] **步骤 4：修正规划文档**

在 `docs/MVP开发计划.md` 和 `docs/项目规划.md`：

- 删除 `scripts/verify_2a.py` 作为现行工具的描述。
- 删除“已经预留并可用 `deidentify_text()`”的描述。
- 改为“自动医疗数据脱敏尚未实现，是后续必须完成的隐私能力”。
- 将数据库迁移入口改为 Alembic。

- [ ] **步骤 5：搜索过时描述**

运行：

```powershell
rg -n "verify_2a|pnpm|首次建库用.*schema.sql|deidentify_text|7 张业务表" README.md docs database
```

预期：只允许设计/历史说明中明确标注为历史资料的匹配，不得保留现行操作指引。

---

### 任务 10：最终全量验证和残余扫描

**文件：**

- 验证整个项目。

**接口：**

- 使用实际项目 Python、PostgreSQL 和 npm 环境。
- 不把生成的评测报告写回仓库，除非用户另行要求。

- [ ] **步骤 1：运行完整后端测试和编译检查**

```powershell
cd backend
$env:PYTHONPATH='.'
python -m unittest discover -s tests -v
python -m compileall -q app alembic
```

预期：全部测试通过，编译退出码 0。

- [ ] **步骤 2：运行前端验证**

```powershell
cd frontend
npx vue-tsc --noEmit
npm run build
```

预期：退出码 0。

- [ ] **步骤 3：运行 RAG 基线**

```powershell
python scripts/evaluate_rag.py --dataset evaluation/rag_baseline_10.json
```

预期：`passed=10`、`total=10`。

- [ ] **步骤 4：核对运行数据未变化**

比较实施前记录的 `uploads/` 文件相对路径、大小和数量，必须完全一致。查询当前数据库六张业务表和向量表记录数，确认清理过程没有减少业务数据。

- [ ] **步骤 5：扫描残余文件和引用**

运行：

```powershell
rg -n "createMessage|def create_message|def delete_chunks|def delete_collection|def deidentify_text|class MessageCreate|class UserCreate|class DocumentStatus" backend frontend scripts
rg --files frontend | rg "pnpm-lock|pnpm-workspace"
Get-ChildItem frontend\node_modules -Force | Where-Object Name -In '.pnpm','.ignored'
```

预期：均无匹配。

- [ ] **步骤 6：清除验证产生的 Python 缓存**

验证完成后再次删除项目内 `__pycache__/` 和 `.pyc`。保留 npm 安装后的 `node_modules/` 和最终生产构建生成的 `dist/`，方便用户立即运行；二者继续由 `.gitignore` 排除。

- [ ] **步骤 7：生成中文完成报告**

报告必须包含：

- 删除的文件、目录和死代码。
- Alembic 两段迁移及现有数据库接入结果。
- npm 重建结果。
- 后端测试数量、前端构建、空库迁移、当前库迁移和 RAG 10 条评测结果。
- 保留的运行数据和历史资料。
- 未处理的残余风险，例如前端大包体积警告和自动医疗数据脱敏尚未实现。

当前不是有效 Git 仓库，因此跳过提交、分支、合并和 PR 操作。
