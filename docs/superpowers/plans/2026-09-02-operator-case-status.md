# Operator Case Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将纵向病例状态收敛为 `active`/`archived`，在数据库、后端、前端和测试中实现生产级合法值约束、可逆状态接口、归档只读、审计和并发保护。

**Architecture:** 保留 `operator_cases.status` 为 `VARCHAR(50)`，由数据库 CHECK 约束提供最终合法值防线；后端以 `OperatorCaseStatus` 和集中状态服务实现状态转换、行锁、原因校验和专用审计。普通资料更新不再修改状态，所有病例写路径统一检查 `active`，报告启动只在病例锁定且仍为 `active` 时创建快照。

**Tech Stack:** Python 3、FastAPI、Pydantic v2、SQLAlchemy ORM、PostgreSQL、Alembic、Vue 3、TypeScript、Element Plus、pytest、前端生产构建。

## Global Constraints

- 直接在 `main` 分支实施，不创建 worktree。
- 先按 TDD 编写失败测试，再写最小实现。
- 不连接、读取或修改生产服务器；生产迁移只写入执行说明和只读检查器。
- 状态数据库 key 只能是 `active` 与 `archived`；中文“使用中/已归档”只在前端显示层映射。
- 不使用 PostgreSQL ENUM，不创建可配置状态字典表，不引入通用工作流引擎。
- 普通病例资料更新接口彻底删除 `status` 字段；旧客户端提交该字段返回 422，不兼容转发。
- `archived` 可恢复为 `active`，但归档期间病例资料、访视、删除和新报告均禁止。
- 状态实际变化必须填写 1～500 字符原因，并在专用审计表中留痕；相同目标状态请求幂等成功且不重复审计。
- 状态读取、检查、更新和审计插入在一个事务内完成；状态接口和其他病例写路径使用病例行锁。
- 不修改 `docs/AI操作者流程核查.md`，直到仓库实现和完整回归完成。
- 所有前端 UI 修改前必须遵循 `docs/DESIGN_SPEC.md`。

---

## 文件变更总览

### 新建

- `backend/app/schemas/operator_case_status.py`：状态枚举、状态变更请求模型。
- `backend/app/services/operator_case_status_service.py`：锁定病例、转换、审计和状态写资格服务。
- `backend/alembic/versions/0015_operator_case_status_constraint.py`：预检、审计结构和 `NOT VALID` CHECK。
- `backend/alembic/versions/0016_validate_operator_case_status.py`：独立事务验证 CHECK。
- `scripts/check_operator_case_status_migration_readonly.py`：迁移前/迁移后只读检查器。
- `backend/tests/test_operator_case_status.py`：状态枚举、服务、并发和审计测试。
- `backend/tests/test_operator_case_status_migration.py`：迁移结构和失败安全测试。
- `scripts/tests/test_check_operator_case_status_migration_readonly.py`：检查器输出与阻断测试。

### 修改

- `backend/app/db/models.py`：ORM 状态 CHECK、状态审计模型和索引。
- `backend/app/schemas/longitudinal_case.py`：删除普通更新中的 `status`，响应和状态请求改用枚举。
- `backend/app/services/longitudinal_case_service.py`：统一病例锁定和 `active` 写资格检查。
- `backend/app/api/operator.py`：状态接口、状态筛选、归档只读错误映射、报告启动锁定。
- `database/schema.sql`：状态 CHECK、审计表和索引。
- `scripts/check_database_readonly.py`：加入状态约束和审计结构契约。
- `backend/tests/test_longitudinal_case_service.py`：更新既有测试并补充 archived 写保护。
- `backend/tests/test_longitudinal_schema_contracts.py`：增加状态约束和审计列契约。
- `backend/tests/test_schema_contracts.py`：增加 clean-install SQL 断言。
- `frontend/src/api/operator.ts`：状态类型、筛选参数和状态接口。
- `frontend/src/stores/operator.ts`：状态筛选、归档、恢复和刷新逻辑。
- `frontend/src/views/OperatorView.vue`：状态操作、报告按钮禁用和冲突刷新。
- `frontend/src/components/LongitudinalCaseEditor.vue`：归档只读界面。
- `frontend/src/components/OperatorSidebar.vue` 或病例选择器所在组件：状态标签映射。

---

## Task 1: 建立状态契约与失败测试

**Files:**
- Create: `backend/app/schemas/operator_case_status.py`
- Modify: `backend/app/schemas/longitudinal_case.py`
- Test: `backend/tests/test_operator_case_status.py`
- Modify: `backend/tests/test_longitudinal_case_service.py`

**Interfaces:**
- Produces `OperatorCaseStatus(str, Enum)` with `ACTIVE = "active"` and `ARCHIVED = "archived"`.
- Produces `OperatorCaseStatusChangeRequest(expected_status, status, reason)`.
- `OperatorCaseUpdate` no longer exposes `status` and keeps `extra="forbid"`.

- [ ] **Step 1: Write failing schema tests**

测试必须覆盖：

```python
def test_status_enum_has_only_two_stable_keys():
    assert {item.value for item in OperatorCaseStatus} == {"active", "archived"}

def test_status_change_request_trims_reason_and_rejects_unknown_values():
    request = OperatorCaseStatusChangeRequest(
        expected_status="active", status="archived", reason="  随访结束  "
    )
    assert request.reason == "随访结束"
    with pytest.raises(ValidationError):
        OperatorCaseStatusChangeRequest(
            expected_status="active", status="paused", reason="原因"
        )

def test普通资料更新拒绝_status字段():
    with pytest.raises(ValidationError):
        OperatorCaseUpdate.model_validate({"status": "archived"})
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```text
cd backend
pytest tests/test_operator_case_status.py tests/test_longitudinal_case_service.py -q
```

Expected: FAIL because the new module and the revised contract do not yet exist.

- [ ] **Step 3: Implement the minimum schema contract**

使用 `str, Enum` 定义状态；状态请求模型使用枚举字段，`reason` 使用字符串并在 validator 中 trim；实际变化的必填原因由服务层判断，因为幂等请求可以不产生审计。

从 `OperatorCaseUpdate` 删除 `status`，保留 `extra="forbid"`，不改变其他字段校验。

- [ ] **Step 4: Re-run focused tests**

Run the same pytest command. Expected: PASS for schema tests and any still-compatible existing tests.

- [ ] **Step 5: Commit the isolated contract change**

```text
git add backend/app/schemas/operator_case_status.py backend/app/schemas/longitudinal_case.py backend/tests/test_operator_case_status.py backend/tests/test_longitudinal_case_service.py
git commit -m "feat: define operator case status contract"
```

## Task 2: 增加 ORM 状态约束和专用审计模型

**Files:**
- Modify: `backend/app/db/models.py`
- Test: `backend/tests/test_longitudinal_schema_contracts.py`
- Modify: `backend/tests/test_schema_contracts.py`

**Interfaces:**
- Produces `OperatorCaseStatusLog` mapped to `operator_case_status_logs`.
- `OperatorCase` table metadata includes `ck_operator_cases_status` with `status IN ('active', 'archived')`.

- [ ] **Step 1: Write failing ORM contract tests**

覆盖：状态 CHECK 名称和表达式、审计模型字段、`from_status <> to_status`、外键 `SET NULL`、快照列和两个时间索引。

- [ ] **Step 2: Run focused contract tests and verify failure**

```text
cd backend
pytest tests/test_longitudinal_schema_contracts.py tests/test_schema_contracts.py -q
```

- [ ] **Step 3: Implement ORM metadata**

在 `OperatorCase.__table_args__` 增加命名 CHECK。新增 `OperatorCaseStatusLog`，字段为 `case_id`、`case_id_snapshot`、`actor_id`、`actor_id_snapshot`、`from_status`、`to_status`、`reason`、`created_at`，外键删除策略均为 `SET NULL`，状态和原因约束与规格一致。

- [ ] **Step 4: Run tests and inspect metadata**

```text
cd backend
pytest tests/test_longitudinal_schema_contracts.py tests/test_schema_contracts.py -q
```

Expected: PASS and no existing table/column contract regressions.

- [ ] **Step 5: Commit ORM contract**

```text
git add backend/app/db/models.py backend/tests/test_longitudinal_schema_contracts.py backend/tests/test_schema_contracts.py
git commit -m "feat: add operator case status audit model"
```

## Task 3: 编写迁移前只读检查器

**Files:**
- Create: `scripts/check_operator_case_status_migration_readonly.py`
- Test: `scripts/tests/test_check_operator_case_status_migration_readonly.py`

**Interfaces:**
- Produces `collect_checks(connection, code_heads)` and CLI JSON output.
- Output includes `status`, `mode`, `operator_case_count`, `status_counts`, `null_status_count`, `unknown_status_counts`, `constraint_present`, `constraint_validated`, and `audit_table_present`.

- [ ] **Step 1: Write failing checker tests**

覆盖三种场景：

1. 空库：`mode="empty_initialize"`，没有未知值，返回可继续迁移。
2. 既有合法数据：`mode="existing_validate"`，状态数量正确，返回可继续迁移。
3. 存在 `NULL` 或第三种状态：返回 `FAIL`，只报告值和数量，不生成 UPDATE/DDL。

- [ ] **Step 2: Run checker tests and verify failure**

```text
pytest scripts/tests/test_check_operator_case_status_migration_readonly.py -q
```

- [ ] **Step 3: Implement read-only SQL collection**

事务开始后执行 `SET TRANSACTION READ ONLY`。使用 `GROUP BY status`、NULL/unknown 统计、`information_schema`、`pg_constraint` 和 `pg_class` 查询；数据库异常输出 `BLOCKED`，禁止吞掉异常伪装为 PASS。

- [ ] **Step 4: Run checker tests**

```text
pytest scripts/tests/test_check_operator_case_status_migration_readonly.py -q
```

Expected: PASS for empty, valid-existing, unknown, NULL and database-error cases.

- [ ] **Step 5: Commit checker**

```text
git add scripts/check_operator_case_status_migration_readonly.py scripts/tests/test_check_operator_case_status_migration_readonly.py
git commit -m "feat: add readonly operator case status preflight"
```

## Task 4: 创建两阶段 Alembic 迁移和 clean-install SQL

**Files:**
- Create: `backend/alembic/versions/0015_operator_case_status_constraint.py`
- Create: `backend/alembic/versions/0016_validate_operator_case_status.py`
- Modify: `database/schema.sql`
- Modify: `backend/tests/test_alembic_contracts.py`
- Modify: `backend/tests/test_schema_contracts.py`
- Modify: `scripts/check_database_readonly.py`
- Test: `backend/tests/test_operator_case_status_migration.py`

**Interfaces:**
- Revision `0015` creates audit table/indexes and adds `ck_operator_cases_status` as `NOT VALID` after migration-internal preflight.
- Revision `0016` runs `VALIDATE CONSTRAINT ck_operator_cases_status` and confirms PostgreSQL reports `convalidated = true`.

- [ ] **Step 1: Write failing migration contract tests**

断言：

- `0015.down_revision == "0014"`；`0016.down_revision == "0015"`；
- 迁移包含未知值/NULL 阻断逻辑；
- `0015` 使用相同约束名、审计字段、外键删除规则和索引名；
- `0016` 只验证约束，不改写病例；
- downgrade 不删除病例；审计表非空时不静默删除历史审计；
- `schema.sql` 包含已验证语义相同的 CHECK 和审计表；
- `check_database_readonly.py` 的 required columns/constraints 包含新结构。

- [ ] **Step 2: Run migration tests and verify failure**

```text
cd backend
pytest tests/test_operator_case_status_migration.py tests/test_alembic_contracts.py tests/test_schema_contracts.py -q
```

- [ ] **Step 3: Implement revision `0015`**

在 DDL 前重新执行 `SELECT status, count(*)` 和 NULL/unknown 检查；异常直接抛出并回滚。创建 `operator_case_status_logs`、快照列、合法值 CHECK、`from_status <> to_status`、reason 长度/非空约束和 `(case_id_snapshot, created_at)`、`(actor_id_snapshot, created_at)` 索引；增加 `operator_cases` 的 `NOT VALID` CHECK。保留当前 `NOT NULL DEFAULT 'active'`。

- [ ] **Step 4: Implement revision `0016`**

只执行 `ALTER TABLE operator_cases VALIDATE CONSTRAINT ck_operator_cases_status`，失败时回滚并保留数据不变。不要在第二阶段自动修改未知数据。

- [ ] **Step 5: Update clean-install schema and read-only baseline**

在 `database/schema.sql` 建表时直接声明已验证 CHECK；在 `scripts/check_database_readonly.py` 中检查约束、审计表字段、外键和索引。

- [ ] **Step 6: Run focused migration and baseline tests**

```text
cd backend
pytest tests/test_operator_case_status_migration.py tests/test_alembic_contracts.py tests/test_schema_contracts.py -q
```

- [ ] **Step 7: Commit migration structures**

```text
git add backend/alembic/versions/0015_operator_case_status_constraint.py backend/alembic/versions/0016_validate_operator_case_status.py database/schema.sql backend/tests/test_alembic_contracts.py backend/tests/test_schema_contracts.py backend/tests/test_operator_case_status_migration.py scripts/check_database_readonly.py
git commit -m "feat: constrain operator case statuses in database"
```

## Task 5: 实现集中状态服务、行锁和审计原子性

**Files:**
- Create: `backend/app/services/operator_case_status_service.py`
- Modify: `backend/app/services/longitudinal_case_service.py`
- Modify: `backend/app/db/models.py` if relationship wiring is needed
- Test: `backend/tests/test_operator_case_status.py`
- Modify: `backend/tests/test_longitudinal_case_service.py`

**Interfaces:**
- `change_operator_case_status(db, user_id, case_id, request) -> OperatorCase`
- `get_owned_case_for_write(db, user_id, case_id, *, allow_archived=False, allow_disabled_archive=False) -> OperatorCase`
- `get_owned_case_for_read(db, user_id, case_id) -> OperatorCase`

- [ ] **Step 1: Write failing service tests**

覆盖：

- active→archived 和 archived→active 写一条日志；
- 相同目标状态幂等成功且不写日志；
- expected_status 冲突返回专用异常；
- 缺少、空白、超过 500 字符原因被拒绝；
- archived 的资料、访视、删除和报告写资格被拒绝；
- 疾病停用允许 active→archived，拒绝 archived→active；
- 病例锁查询使用 `with_for_update()`；
- 状态更新和日志插入任一失败都回滚。

- [ ] **Step 2: Run focused service tests and verify failure**

```text
cd backend
pytest tests/test_operator_case_status.py tests/test_longitudinal_case_service.py -q
```

- [ ] **Step 3: Implement enum-based transition service**

按“所有权查询 → 行锁 → 幂等判断 → expected_status 校验 → 疾病启用规则 → 原因校验 → 更新病例 → 插入日志 → commit”的顺序执行。使用 `case_id_snapshot`/`actor_id_snapshot` 保留不可变 ID。相同状态不写审计。

- [ ] **Step 4: Route all case write paths through the shared active check**

修改病例资料、删除病例、访视增删改替换和报告创建前，统一锁定病例并确认 `status == active`，同时保留疾病停用检查。删除接口对 archived 返回 409；状态接口是唯一允许写 status 的入口。

- [ ] **Step 5: Run focused tests**

```text
cd backend
pytest tests/test_operator_case_status.py tests/test_longitudinal_case_service.py -q
```

Expected: PASS, including existing disease-disabled behavior.

- [ ] **Step 6: Commit status service**

```text
git add backend/app/services/operator_case_status_service.py backend/app/services/longitudinal_case_service.py backend/app/db/models.py backend/tests/test_operator_case_status.py backend/tests/test_longitudinal_case_service.py
git commit -m "feat: enforce operator case status transitions"
```

## Task 6: 增加 API 接口、筛选、报告启动保护和错误语义

**Files:**
- Modify: `backend/app/api/operator.py`
- Modify: `backend/app/schemas/longitudinal_case.py`
- Modify: `backend/app/schemas/operator_case_status.py`
- Test: `backend/tests/test_operator_catalog_and_reports_api.py`
- Modify: `backend/tests/test_longitudinal_case_service.py`

**Interfaces:**
- `PUT /operator/longitudinal-cases/{case_id}/status`
- `GET /operator/longitudinal-cases?status=active|archived`

- [ ] **Step 1: Write failing API tests**

覆盖：合法归档/恢复、幂等请求、expected_status 冲突 409、原因错误 422、未知状态 422、普通更新携带 status 422、状态筛选、疾病停用归档/恢复边界、archived 写操作 409。

- [ ] **Step 2: Run API tests and verify failure**

```text
cd backend
pytest tests/test_operator_catalog_and_reports_api.py tests/test_longitudinal_case_service.py -q
```

- [ ] **Step 3: Implement status endpoint and error mapping**

在 `operator.py` 中调用集中状态服务；把资源不存在映射 404、契约错误映射 422、状态冲突/归档只读/疾病停用恢复映射 409。不要在路由中复制状态转换逻辑。

- [ ] **Step 4: Add status query parameter**

列表接口将可选 `status: OperatorCaseStatus | None` 转为数据库过滤；未提供时返回当前用户全部病例。

- [ ] **Step 5: Protect report creation**

报告创建事务中锁定病例并确认 active、疾病启用和能力存在，再写入 `AIReport(status="generating")` 与输入快照；提交后释放锁，流式生成继续使用已保存快照。

- [ ] **Step 6: Run API tests**

```text
cd backend
pytest tests/test_operator_catalog_and_reports_api.py tests/test_longitudinal_case_service.py -q
```

- [ ] **Step 7: Commit API behavior**

```text
git add backend/app/api/operator.py backend/app/schemas/longitudinal_case.py backend/app/schemas/operator_case_status.py backend/tests/test_operator_catalog_and_reports_api.py backend/tests/test_longitudinal_case_service.py
git commit -m "feat: expose operator case status API"
```

## Task 7: 修改前端状态显示、筛选和只读操作

**Files:**
- Modify: `frontend/src/api/operator.ts`
- Modify: `frontend/src/stores/operator.ts`
- Modify: `frontend/src/views/OperatorView.vue`
- Modify: `frontend/src/components/LongitudinalCaseEditor.vue`
- Modify: `frontend/src/components/OperatorSidebar.vue` or the component rendering longitudinal case options
- Read before editing: `docs/DESIGN_SPEC.md`

**Interfaces:**
- `LongitudinalCaseStatus = 'active' | 'archived'`
- `updateLongitudinalCaseStatus(id, payload)` sends `expected_status`, `status`, `reason`.
- `listLongitudinalCases(diseaseId?, status?)` sends server-side status filter.

- [ ] **Step 1: Write failing frontend tests/type checks**

检查：状态标签映射、筛选参数、归档/恢复请求体、archived 禁用保存/访视/报告/删除、409 后刷新病例、未知状态不显示为 active。

- [ ] **Step 2: Run frontend checks and verify failure**

```text
cd frontend
npm run type-check
npm run test -- --run
```

Expected: FAIL for missing API/store/UI behavior or type changes.

- [ ] **Step 3: Implement API and store methods**

新增状态联合类型和 API 方法；store 增加 `caseStatusFilter`、按筛选重新加载、状态变更后替换当前病例并刷新列表。状态请求必须携带当前显示的 `expected_status`。

- [ ] **Step 4: Implement UI under the design spec**

在病例选择器显示“使用中/已归档”；提供“全部/使用中/已归档”筛选；归档和恢复使用原因弹窗；archived 编辑器和访视控件只读；报告生成和删除入口禁用并说明“请先恢复病例”；疾病停用时仍允许归档但禁用恢复。

- [ ] **Step 5: Implement error and unknown-state handling**

409 提示状态已变化并重新加载；422 展示后端原因校验；未知状态显示“未知状态”并停止写操作，不回退为 active。

- [ ] **Step 6: Run frontend checks and production build**

```text
cd frontend
npm run type-check
npm run test -- --run
npm run build
```

- [ ] **Step 7: Commit frontend behavior**

```text
git add frontend/src/api/operator.ts frontend/src/stores/operator.ts frontend/src/views/OperatorView.vue frontend/src/components/LongitudinalCaseEditor.vue frontend/src/components/OperatorSidebar.vue
git commit -m "feat: add operator case status controls"
```

## Task 8: 补齐端到端测试和并发回归

**Files:**
- Modify: `backend/tests/test_operator_case_status.py`
- Modify: `backend/tests/test_longitudinal_case_service.py`
- Modify: `backend/tests/test_operator_catalog_and_reports_api.py`
- Modify: `scripts/tests/test_check_operator_case_status_migration_readonly.py`
- Add or modify frontend tests beside affected components according to existing test layout.

- [ ] **Step 1: Add database-backed status tests**

使用测试 PostgreSQL 或项目既有数据库 fixture 验证非法 INSERT/UPDATE 被 CHECK 拒绝，审计约束生效，病例和用户删除后审计保留且外键置空。

- [ ] **Step 2: Add transition and concurrency tests**

验证两个并发状态请求不会产生双重错误审计；expected_status 冲突返回 409；状态变更与访视/报告启动不会绕过病例行锁和 active 检查。

- [ ] **Step 3: Add report snapshot regression**

验证状态不进入 `input_snapshot`，报告创建后归档不会取消已开始的报告，历史报告查看和 PDF 下载保持原行为。

- [ ] **Step 4: Run focused full backend/script suites**

```text
cd backend
pytest -q
cd ..
pytest scripts/tests -q
```

- [ ] **Step 5: Commit regression coverage**

```text
git add backend/tests scripts/tests
git commit -m "test: cover operator case status lifecycle"
```

## Task 9: 运行完整验证并进行代码/文档审查

**Files:**
- No product-code changes unless verification finds a concrete defect.
- Review: `docs/superpowers/specs/2026-09-01-operator-case-status-design.md`
- Later update only after approval: `docs/AI操作者流程核查.md` Appendix item 3.

- [ ] **Step 1: Run backend regression**

```text
cd backend
pytest -q
```

Expected: PASS with no skipped status-critical tests.

- [ ] **Step 2: Run scripts and read-only checker tests**

```text
cd ..
pytest scripts/tests -q
python scripts/check_operator_case_status_migration_readonly.py
```

The checker must report `BLOCKED` if no configured database is available; this is not evidence of a production migration.

- [ ] **Step 3: Run frontend checks and build**

```text
cd frontend
npm run type-check
npm run test -- --run
npm run build
```

- [ ] **Step 4: Run application smoke tests**

在非生产测试环境完成：active/archived 归档恢复、重复请求、并发冲突、疾病停用、访视写入、报告生成、历史查看和 PDF 下载；同时验证 AD 与脂肪肝。

- [ ] **Step 5: Review migration SQL and downgrade**

确认未知状态不会被自动改写；确认 `NOT VALID`、独立验证、锁超时、非空审计降级保护和生产暂停写流量说明与规格一致。

- [ ] **Step 6: Only after repository verification, update Appendix item 3**

更新 `docs/AI操作者流程核查.md` 时明确区分：

- 仓库实现已完成并通过哪些测试；
- 生产数据库迁移是否尚未执行；
- 生产迁移仍需只读预检、人工确认、备份、分阶段 Alembic、迁移后核验。

## Task 10: 生产部署执行边界（单独审批，不在本计划自动执行）

**Files:**
- No automatic production commands.
- Operational reference: `docs/superpowers/specs/2026-09-01-operator-case-status-design.md` sections 9, 10 and 14.

- [ ] **Step 1: Obtain explicit production approval and backup confirmation**

没有明确审批、备份和恢复演练证据时停止。

- [ ] **Step 2: Run the read-only preflight on production**

人工审核完整 distinct status 和数量；任何未知值、NULL、schema 偏差或 revision 不符均停止。

- [ ] **Step 3: Pause longitudinal case write traffic**

在迁移和新后端切换窗口禁止病例资料、访视、删除和报告启动写入。

- [ ] **Step 4: Run Alembic `0015`, then `0016` separately**

设置合理 `lock_timeout`/`statement_timeout`；抢不到锁或验证失败时安全失败，不自动改数据。

- [ ] **Step 5: Deploy backend and frontend together, then run post-migration checker**

确认 CHECK 已验证、状态数量未变、归档只读和审计均正确后恢复写流量。

- [ ] **Step 6: Record repository completion and production migration completion separately**

未执行生产迁移前，不得在核查文档中写成已上线。

---

## Plan Self-Review

- **Spec coverage:** 当前实现、绕过路径、稳定英文 key、CHECK/ENUM/字典/应用白名单比较、状态矩阵、疾病停用、删除、访视、报告快照、前端权限、审计、并发、迁移前检查、旧客户端、测试、部署和回滚均映射到任务 1～10。
- **Placeholder scan:** 计划没有未解决的占位内容；每个代码任务包含具体文件、接口、测试命令和预期结果。
- **Type consistency:** `OperatorCaseStatus`、`OperatorCaseStatusChangeRequest`、`change_operator_case_status`、`get_owned_case_for_write` 和前端 `updateLongitudinalCaseStatus` 在任务之间使用同一命名和语义。
- **Scope check:** 计划只覆盖病例状态约束及其直接依赖，不引入新的疾病、报告状态、模型字段或审计查询页面。
- **Safety check:** 生产服务器不在自动执行范围；未知状态不自动改写；downgrade 不删除病例、不改写历史业务数据；非空审计表禁止破坏性降级。
