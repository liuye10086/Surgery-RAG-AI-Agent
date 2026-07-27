# 数据库结构与迁移说明

项目的正式数据库迁移入口位于 `backend/alembic/`。新建数据库、日常升级和版本回退都应通过 Alembic 执行，不再手工运行本目录中的 SQL 作为常规部署步骤。

## 正式迁移方式

新数据库或已经接入 Alembic 的数据库：

```bash
cd backend
alembic upgrade head
```

Alembic 管理 `vector`、`uuid-ossp`、`pg_trgm` 扩展和以下 6 张业务表：

| 表 | 说明 |
| --- | --- |
| `users` | 用户账户 |
| `documents` | 上传文档、处理状态和当前代次 |
| `chunks` | 文档分块内容和元数据，不直接存储向量 |
| `sessions` | 用户聊天会话 |
| `messages` | 对话消息、LangChain 标准消息和引用来源 |
| `audit_logs` | RAG 请求、安全标记和响应审计 |

`langchain_pg_collection`、`langchain_pg_embedding` 是 `langchain-postgres` 的内部表，由应用和依赖库管理，不纳入 Alembic 迁移。向量表 `document` 列上的全文检索索引由程序维护。

## 本目录文件职责

| 文件 | 作用 |
| --- | --- |
| `schema.sql` | 当前业务结构的人工核对参考快照，不是正式建库入口 |
| `migrations/006_*.sql` | Alembic 接入前的历史迁移资料 |
| `migrations/007_*.sql` | Alembic 接入前的历史迁移资料 |
| `migrations/008_*.sql` | Alembic 接入前的历史迁移资料 |

如参考快照与 Alembic 迁移链不一致，以 `backend/alembic/` 的最新迁移为准，并同步修正快照。

## 旧数据库首次接入

由 `schema.sql` 和旧版 006/007/008 SQL 创建的数据库，不能直接重复执行 `0001`。应先核对结构和数据，再执行：

```bash
cd backend
alembic stamp 0001
alembic upgrade head
```

`0002` 会在收紧外键前检查 `chunks.document_id`、`sessions.user_id`、`messages.session_id` 是否存在空值。发现异常时迁移会停止，不会自动删除或修复业务数据。
