# 数据库结构与迁移说明

项目的正式数据库迁移入口位于 `backend/alembic/`。新建数据库、日常升级和版本回退都应通过 Alembic 执行，不再手工运行本目录中的 SQL 作为常规部署步骤。

## 正式迁移方式

新数据库或已经接入 Alembic、且满足对应迁移前置条件的数据库：

```bash
cd backend
alembic upgrade head
```

Alembic 管理 `vector`、`uuid-ossp`、`pg_trgm` 扩展和当前业务表结构（基础用户/文档/会话表、AI 操作者病例/访视/报告表，以及标准版本化相关表）：

| 表 | 说明 |
| --- | --- |
| `users` | 用户账户 |
| `documents` | 上传文档、处理状态和当前代次 |
| `chunks` | 文档分块内容和元数据，不直接存储向量 |
| `sessions` | 用户聊天会话 |
| `messages` | 对话消息、LangChain 标准消息和引用来源 |
| `audit_logs` | RAG 请求、安全标记和响应审计 |

AI 操作者链路还包括 `diseases`、`case_records`、`reference_ranges`、
`operator_cases`、`operator_case_visits`、`ai_reports`；标准版本化链路还包括
`reference_standards`、`standard_documents`、`reference_standard_versions`、
`standard_indicators`、`standard_segments`、`standard_parse_candidates`、
`standard_rules`、`standard_rule_conditions`、`standard_change_logs`。

`langchain_pg_collection`、`langchain_pg_embedding` 是 `langchain-postgres` 的内部表，由应用和依赖库管理，不纳入 Alembic 迁移。向量表 `document` 列上的全文检索索引由程序维护。

## 本目录文件职责

| 文件 | 作用 |
| --- | --- |
| `schema.sql` | Alembic 当前 head 的人工核对参考快照，不是正式建库入口 |

所有正式版本变更都位于 `backend/alembic/versions/`。如参考快照与 Alembic 迁移链不一致，以 Alembic 最新 head 为准，并同步修正快照。

## 疾病许可迁移（0014）

修订 `0014` 为 `diseases` 增加稳定 `code` 和 `operator_enabled`，并将
`operator_cases`、`case_records`、`ai_reports` 的疾病外键统一为
`ON DELETE RESTRICT`。疾病中文名称仍是可修改的显示信息，不写入数据库 CHECK；
`code` 才是模型、数据集、标准和前端疾病配置的稳定路由键。

生产升级必须按以下顺序执行：

```text
备份数据库
→ python scripts/check_operator_disease_migration_readonly.py
→ 人工确认 status=PASS，并确认 mode 为 empty_initialize 或 existing_backfill
→ cd backend && alembic upgrade head
→ python ../scripts/check_database_readonly.py
→ 重启后端
→ 对 AD 和脂肪肝分别执行病例读取、病例写入和报告生成冒烟验证
```

迁移边界：

- 只读预检要求当前 revision 与迁移前置版本一致；不一致时必须停止。
- 全新空库只有在疾病目录和四类关联业务数据都为空时，才自动初始化 AD 与脂肪肝。
- 既有库必须恰好存在“阿尔茨海默病”和“脂肪肝”；疾病缺失、改名或出现第三种疾病都会阻止迁移并要求人工复核。
- 不得对版本不明的生产库执行 `alembic stamp`，也不得在既有生产库重新运行 `database/schema.sql`。
- 停用疾病只改变操作者许可，操作可逆，历史病例、报告和 PDF 均保留并可读。
- 只有 `operator_cases`、`case_records`、`ai_reports`、`reference_standards` 四类使用计数全部为零时，管理员才可物理删除疾病；数据库限制型外键提供最终保护。
- 回退前必须再次备份并停止写入。`0014` downgrade 只恢复旧结构，不删除疾病、病例、报告或标准数据；回退后也不得主动删除已被引用的疾病。

## 旧数据库首次接入

既有数据库接入 Alembic 前，必须先核对真实表结构、数据约束与已有版本。只有确认数据库结构与某一 revision 完全一致时，才能 stamp 到该 revision，然后继续升级：

```bash
cd backend
alembic stamp <与真实结构匹配的 revision>
alembic upgrade head
```

不得默认所有旧数据库都可直接 stamp `0001`。结构不一致、版本无法确认或存在异常数据时，应停止升级并先人工核查；迁移不会自动删除或修复业务数据。涉及 `0014` 时还必须先执行上述疾病许可只读预检，不能用 stamp 绕过前置检查。
