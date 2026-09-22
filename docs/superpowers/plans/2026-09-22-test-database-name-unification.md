# 测试数据库名称统一实施计划

> **执行方式：** 当前会话内按步骤实施；保留现有未提交修改，不创建提交或推送。

**Goal:** 将当前有效测试链路统一到本机 `surgery_rag_test`，安全配置 `TEST_DATABASE_URL`，并删除不再使用的 `surgery_rag_phase4_test`。

**Architecture:** 先用现有脚本单测锁定新的数据库名和通用错误码，再修改运行脚本、integration 门禁与当前运维文档。环境变量从已有 `backend/.env` 凭据派生但不输出密钥，只做只读连接验证；最后对精确旧库执行删除并复查 PostgreSQL 目录。

**Tech Stack:** Python 3.11、pytest、SQLAlchemy、PostgreSQL、PowerShell。

## Global Constraints

- 保留 `docs/superpowers/specs`、`docs/superpowers/plans`、`docs/superpowers/notes` 中既有历史记录。
- 保留 `outputs/numeric-history-demo-release/surgery_rag_phase4_test-phase4-leftover-2026-09-21.dump`。
- 不迁移、不清空、不写入 `surgery_rag_test`；不运行 integration/E2E 套件。
- 不输出数据库连接串、用户名或密码。
- 不提交、不推送，不覆盖当前前端未提交修改。

---

### Task 1: 用测试定义新数据库名与通用错误码

**Files:**
- Modify: `scripts/tests/test_run_numeric_history_acceptance.py`
- Modify: `scripts/tests/test_run_numeric_history_demo_release.py`
- Modify: `scripts/tests/test_numeric_history_demo_release.py`

**Interfaces:**
- `validate_database_url()` 只接受 database=`surgery_rag_test`。
- `inspect_demo_database()` 返回 database=`surgery_rag_test`，迁移不匹配抛出 `test_database_migration_required`。

- [ ] 将成功 fixture 的 URL 改为 `postgresql://test:secret@127.0.0.1/surgery_rag_test`。
- [ ] 将 `surgery_rag_phase4_test` 加入拒绝列表；query/fragment 用例改为基于 `surgery_rag_test`。
- [ ] 将数据库身份与迁移错误断言改为新名称和 `test_database_migration_required`。
- [ ] 运行：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest ..\scripts\tests\test_run_numeric_history_acceptance.py ..\scripts\tests\test_run_numeric_history_demo_release.py ..\scripts\tests\test_numeric_history_demo_release.py -q
```

Expected: 因生产代码仍只接受旧库名而出现预期失败，证明测试能捕获问题。

### Task 2: 修改运行脚本与数据库门禁

**Files:**
- Modify: `scripts/run_numeric_history_acceptance.py`
- Modify: `scripts/run_numeric_history_demo_release.py`
- Modify: `scripts/numeric_history_demo_release.py`
- Modify: `backend/tests/integration/test_numeric_report_v3.py`
- Modify: `backend/tests/integration/test_numeric_report_v3_admission.py`
- Modify: `backend/tests/integration/test_numeric_report_pdf.py`
- Modify: `backend/tests/integration/test_numeric_history_demo_release.py`

**Interfaces:**
- 精确目标库：`surgery_rag_test`。
- URL 安全条件保持不变：loopback、无 query/fragment、无 `PGHOSTADDR`/`PGSERVICE`/`PGSERVICEFILE`/`PGOPTIONS`。
- 错误码统一为 `test_database_target_rejected` 和 `test_database_migration_required`。

- [ ] 将运行常量和数据库身份判断改为 `surgery_rag_test`。
- [ ] 将数据库专属的阶段四错误码、fixture 名称和提示改为通用测试数据库表述。
- [ ] 同步 integration 门禁和断言，但不收集或运行这些会写库的用例。
- [ ] 重跑 Task 1 命令，Expected: 全部通过。

### Task 3: 更新当前运维文档并审计活动引用

**Files:**
- Modify: `docs/OPERATOR_REPORT_OPERATIONS.md`

- [ ] 将当前阶段四验收和阶段五演示的前置数据库名称改为 `surgery_rag_test`。
- [ ] 用 `rg` 扫描 `scripts`、`backend/tests/integration` 和当前运维文档，确认不存在旧库名和旧数据库错误码。
- [ ] 明确排除历史 `docs/superpowers`、备份 `outputs`、临时 `.tmp` 和 Git 历史。

### Task 4: 配置并只读验证 `TEST_DATABASE_URL`

**Files:** None（Windows 用户环境变量）。

- [ ] 从 `backend/.env` 的 `DATABASE_URL` 读取现有本机凭据，只替换数据库 path 为 `/surgery_rag_test`。
- [ ] 校验派生 URL 主机为 loopback、无 query/fragment，数据库名精确匹配后，用 .NET API 写入 Windows 用户级 `TEST_DATABASE_URL`；命令不打印 URL。
- [ ] 在同一安全进程中连接派生 URL，只执行 `SELECT current_database()`、读取 Alembic 版本和三张业务表行数，不执行迁移或写入。
- [ ] 输出仅包含数据库名、版本、行数和用户环境变量是否存在。

### Task 5: 精确删除旧数据库

**Files:** None（本机 PostgreSQL）。

- [ ] 再次查询 `pg_database` 和 `pg_stat_activity`，要求 `surgery_rag_phase4_test` 存在且活动连接为 0，同时 `surgery_rag_test` 存在。
- [ ] 通过连接到其他数据库并使用 AUTOCOMMIT 执行固定 SQL：

```sql
DROP DATABASE "surgery_rag_phase4_test";
```

- [ ] 再查 PostgreSQL 目录，确认旧库不存在、新库仍存在；确认备份文件仍存在。

### Task 6: 最终验证与交付

**Files:** 所有本次修改文件。

- [ ] 运行 Task 1 的脚本测试。
- [ ] 运行后端非集成回归：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests ..\scripts\tests --ignore=tests/integration --ignore=tests/e2e
```

- [ ] 运行 `git diff --check`、活动范围旧名称扫描和 `git status --short`。
- [ ] 汇报修改、测试、数据库删除、保留的历史记录/备份，以及未运行 integration/E2E 的限制；不提交。
