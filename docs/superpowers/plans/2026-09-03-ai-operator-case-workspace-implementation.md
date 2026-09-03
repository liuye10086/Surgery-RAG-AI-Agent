# AI 操作者建立病例与病例工作区 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 AI 操作者“建立病例”收敛为唯一的本人纵向病例工作区，实现完整资料与至少一次首次访视原子创建、可审计聚合修改、幂等重试、模型驱动的报告就绪判断，以及真实 PostgreSQL 和浏览器端到端验收。

**Architecture:** `operator_cases` 是操作者唯一业务病例；`case_records` 只保留为模型参考数据。FastAPI 接口层只做鉴权、解析和错误映射，病例命令服务在单事务中编排所有权/状态/疾病/阶段/访视校验、差异、审计和幂等；报告就绪服务从活动 release set 的数据清单读取 `minimum_visits`。Vue 端由一个病例工作区容器组合病例列表、资料表单、访视时间线、操作栏和变更原因对话框，创建和修改均只调用一个请求，生成报告是独立操作。

**Tech Stack:** Python 3、FastAPI、Pydantic v2、SQLAlchemy ORM、PostgreSQL 16 + pgvector、Alembic、pytest、Vue 3、TypeScript、Pinia、Element Plus、Vitest、Vue Test Utils、Playwright、Vite。

## Global Constraints

- 实施前先读取并遵循 `docs/DESIGN_SPEC.md`；不改变已确认的暖杏蓝视觉体系、布局尺度和可访问性规则。
- 以 `docs/superpowers/specs/2026-09-03-ai-operator-case-workspace-design.md` 为唯一产品规格；发现冲突时停止该任务并回到规格核对，不临时扩展产品范围。
- 直接在当前 `main` 工作树按任务实施，不创建额外 worktree；每个任务先写失败测试，再做最小实现并提交。
- 新建和聚合保存始终要求年龄、性别、确定的疾病专属阶段，以及 `1–10` 次有效访视；病例绝不允许保存为零访视。
- 病例创建后疾病不可修改；匿名编号、用户 ID、状态、`patient_label` 和 `visit_index` 均不是客户端可写字段。
- `patient_label` 仅保留在数据库中兼容历史数据，纵向病例 API 响应、前端类型、日志和界面不得再次暴露。
- 历史 `age`、`sex`、`baseline_stage` 的 `NULL` 不自动回填；允许读取并明确标记不完整，补齐前不得修改其他内容或生成报告。
- 病例修改采用后保存覆盖先保存，不新增版本号或乐观锁；行锁仅保证单次事务原子性，每次实际变化必须留下不可变审计。
- 工作区只使用一个聚合 `PUT` 保存资料和完整访视时间线。删除未被内部调用的单访视公开写路由，避免出现绕过聚合审计的第二条写路径。
- 病例保存最低访视数为 `1`；报告最低访视数从活动数据清单读取，当前数据为 `3`，任何前端或病例 Schema 都不得硬编码为报告门槛。
- 创建幂等键为 UUID；相同操作者、scope、键和请求返回首次病例，相同键不同请求返回 `409`，原病例已删除时不得重新创建。
- 不连接、读取或修改生产数据库。真实数据库测试只使用明确命名的独立测试库；迁移工具只报告历史异常，不自动覆盖或推测数据。
- 日志和监控只记录稳定错误码、计数和耗时，不记录匿名编号、年龄、性别、阶段、访视日期、指标名称、指标值、请求体或审计差异。
- 既有历史报告、预测、输入快照、来源和完整性字段在病例更正后保持不变。
- 完整回归、真实 PostgreSQL 集成测试、Playwright、前端构建和双疾病验收全部通过后，才更新 `docs/AI操作者流程核查.md` 第 1 项。

---

## File Change Summary

### Create

- `backend/alembic/versions/0020_operator_case_workspace.py`
- `backend/app/schemas/operator_case_workspace.py`
- `backend/app/services/operator_case_validation.py`
- `backend/app/services/operator_case_diff.py`
- `backend/app/services/operator_case_audit.py`
- `backend/app/services/operator_case_idempotency.py`
- `backend/app/services/operator_case_commands.py`
- `backend/app/services/operator_case_readiness.py`
- `backend/tests/test_operator_case_workspace_schema.py`
- `backend/tests/test_operator_case_validation.py`
- `backend/tests/test_operator_case_diff.py`
- `backend/tests/test_operator_case_commands.py`
- `backend/tests/test_operator_case_readiness.py`
- `backend/tests/test_operator_case_workspace_migration.py`
- `backend/tests/test_operator_case_workspace_api.py`
- `backend/tests/integration/conftest.py`
- `backend/tests/integration/test_operator_case_workspace_api.py`
- `backend/tests/e2e/conftest.py`
- `backend/tests/e2e/test_operator_case_workspace.py`
- `docker-compose.test.yml`
- `scripts/check_operator_case_workspace_migration_readonly.py`
- `scripts/tests/test_check_operator_case_workspace_migration_readonly.py`
- `scripts/run_operator_case_e2e.ps1`
- `frontend/tests/setup.ts`
- `frontend/src/api/__tests__/operator-case-workspace.spec.ts`
- `frontend/src/stores/__tests__/operator-case-workspace.spec.ts`
- `frontend/src/components/operator-case/OperatorCaseList.vue`
- `frontend/src/components/operator-case/OperatorCaseProfileForm.vue`
- `frontend/src/components/operator-case/OperatorVisitTimelineEditor.vue`
- `frontend/src/components/operator-case/OperatorCaseActionBar.vue`
- `frontend/src/components/operator-case/CaseChangeReasonDialog.vue`
- `frontend/src/components/operator-case/OperatorCaseWorkspace.vue`
- `frontend/src/components/operator-case/__tests__/OperatorCaseWorkspace.spec.ts`

### Modify

- `backend/app/db/models.py`
- `backend/app/schemas/longitudinal_case.py`
- `backend/app/services/longitudinal_case_service.py`
- `backend/app/api/operator.py`
- `backend/requirements.txt`
- `backend/tests/test_alembic_contracts.py`
- `backend/tests/test_longitudinal_case_service.py`
- `backend/tests/test_longitudinal_schema_contracts.py`
- `backend/tests/test_operator_catalog_and_reports_api.py`
- `backend/tests/test_schema_contracts.py`
- `database/schema.sql`
- `scripts/check_database_readonly.py`
- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/vite.config.ts`
- `frontend/src/api/operator.ts`
- `frontend/src/stores/operator.ts`
- `frontend/src/components/OperatorSidebar.vue`
- `frontend/src/views/OperatorView.vue`

### Delete

- `frontend/src/components/CaseManageView.vue`
- `frontend/src/components/IndicatorRowsEditor.vue`
- `frontend/src/components/LongitudinalCaseEditor.vue`

---

## Task 1: Freeze the Public Contract with Failing Tests

**Files:**
- Create: `backend/app/schemas/operator_case_workspace.py`
- Create: `backend/tests/test_operator_case_workspace_schema.py`
- Modify: `backend/app/schemas/longitudinal_case.py`

**Interfaces:**
- `OperatorCaseCreate` is strict and requires `disease_id`, `age`, `sex`, `baseline_stage`, and `visits`.
- `OperatorCaseSave` is a full aggregate snapshot with optional `change_reason`; the service requires the reason only when a real diff exists.
- `OperatorCaseOut` never exposes `patient_label`.
- `OperatorCaseListOut` returns `cases`, `total`, `skip`, and `limit`.
- `OperatorCaseReportReadiness` returns stable blocker codes and a nullable `minimum_visits` only when model metadata cannot be loaded.

- [x] **Step 1: Write the failing schema tests**

Add exact cases equivalent to:

```python
def test_create_requires_complete_profile_and_first_visit():
    with pytest.raises(ValidationError):
        OperatorCaseCreate.model_validate({"disease_id": 1, "age": 56, "visits": []})

def test_create_rejects_server_owned_and_legacy_fields(valid_create):
    for forbidden in ("patient_label", "anonymous_case_code", "status", "user_id", "visit_index"):
        payload = deepcopy(valid_create)
        payload[forbidden] = "unexpected"
        with pytest.raises(ValidationError):
            OperatorCaseCreate.model_validate(payload)

def test_response_contract_does_not_expose_patient_label():
    assert "patient_label" not in OperatorCaseOut.model_fields
```

- [x] **Step 2: Run the focused tests and verify failure**

```text
cd backend
pytest tests/test_operator_case_workspace_schema.py -q
```

Expected: FAIL because the strict aggregate contracts do not yet exist.

- [x] **Step 3: Implement the schema types without service logic**

```python
class OperatorCaseSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    age: int = Field(..., ge=0, le=120, strict=True)
    sex: Literal["male", "female"]
    baseline_stage: str = Field(..., min_length=1, max_length=100)
    notes: str | None = Field(None, max_length=5000)
    visits: list[VisitCreate] = Field(..., min_length=1, max_length=10)
    change_reason: str | None = Field(None, max_length=500)

class OperatorCaseReportReadiness(BaseModel):
    ready: bool
    case_ready: bool
    timeline_ready: bool
    model_ready: bool
    visit_count: int
    minimum_visits: int | None
    blockers: list[OperatorCaseReadinessBlocker]
```

`OperatorCaseCreate`, `VisitCreate`, `OperatorCaseSave` and list-filter models all use `extra="forbid"`. Trim optional notes to `None`; trim stage and reason; reject blank required stage. Retain nullable output fields for legacy reads.

- [x] **Step 4: Re-run focused tests**

Use the same pytest command. Expected: all schema tests PASS.

- [x] **Step 5: Commit the contract slice**

```text
git add backend/app/schemas/longitudinal_case.py backend/app/schemas/operator_case_workspace.py backend/tests/test_operator_case_workspace_schema.py
git commit -m "feat: define operator case workspace contract"
```

## Task 2: Add Database Constraints, Audit, and Idempotency Storage

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/0020_operator_case_workspace.py`
- Modify: `database/schema.sql`
- Modify: `scripts/check_database_readonly.py`
- Create: `backend/tests/test_operator_case_workspace_migration.py`
- Modify: `backend/tests/test_alembic_contracts.py`
- Modify: `backend/tests/test_longitudinal_schema_contracts.py`
- Modify: `backend/tests/test_schema_contracts.py`

**Interfaces:**
- `OperatorCaseChangeLog` maps to `operator_case_change_logs` and is append-only through application services.
- `OperatorIdempotencyKey` maps to `operator_idempotency_keys` with unique `(user_id, scope, idempotency_key)`.
- `operator_cases.sex` allows historical `NULL` and only `male`/`female` otherwise.
- Alembic remains one head: `0020.down_revision == "0019"`.

- [x] **Step 1: Write failing ORM, migration, and clean-install contract tests**

Assert exact table names, columns, constraints, indexes and delete behavior. Include these invariants:

```python
assert normalized_sql(ck_sex.sqltext) == "sex is null or sex in ('male','female')"
assert idempotency_unique.columns == ("user_id", "scope", "idempotency_key")
assert change_case_fk.ondelete == "SET NULL"
assert idempotency_user_fk.ondelete == "CASCADE"
assert "operator_cases" not in foreign_keys_for("operator_idempotency_keys.resource_id")
```

Also add a regression assertion correcting the currently swapped ORM foreign-key names: `CaseRecord.disease_id` uses `fk_case_records_disease`, and `OperatorCase.disease_id` uses `fk_operator_cases_disease`, matching migrations and clean-install SQL.

- [x] **Step 2: Run focused contract tests and verify failure**

```text
cd backend
pytest tests/test_operator_case_workspace_migration.py tests/test_alembic_contracts.py tests/test_longitudinal_schema_contracts.py tests/test_schema_contracts.py -q
```

- [x] **Step 3: Implement ORM models and constraints**

Use PostgreSQL UUID/JSONB and named constraints. Material fields:

```python
class OperatorCaseChangeLog(Base):
    __tablename__ = "operator_case_change_logs"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("operator_cases.id", ondelete="SET NULL"))
    case_id_snapshot = Column(Integer, nullable=False)
    anonymous_case_code_snapshot = Column(String(14), nullable=True)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    actor_id_snapshot = Column(Integer, nullable=False)
    action = Column(String(32), nullable=False)
    reason = Column(Text, nullable=False)
    changes = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class OperatorIdempotencyKey(Base):
    __tablename__ = "operator_idempotency_keys"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    scope = Column(String(64), nullable=False)
    idempotency_key = Column(UUID(as_uuid=True), nullable=False)
    request_sha256 = Column(String(64), nullable=False)
    resource_type = Column(String(32), nullable=False)
    resource_id = Column(Integer, nullable=False)  # snapshot, deliberately no FK
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

Add CHECKs for action values, trimmed reason length `1–500`, JSON object `changes`, SHA-256 length, fixed first-version scope/resource type, and indexes on `(case_id_snapshot, created_at)`, `(actor_id_snapshot, created_at)` and `(user_id, created_at)`.

- [x] **Step 4: Implement revision `0020` and clean-install SQL**

The migration must preflight illegal historical sex without rewriting, add and validate `ck_operator_cases_sex`, create both tables and indexes, and never mutate cases/visits/reports. Downgrade refuses to drop non-empty audit/idempotency tables. Mirror the validated structure in `database/schema.sql` and the read-only baseline checker.

- [x] **Step 5: Run migration tests and commit**

```text
cd backend
pytest tests/test_operator_case_workspace_migration.py tests/test_alembic_contracts.py tests/test_longitudinal_schema_contracts.py tests/test_schema_contracts.py -q
alembic heads
git add backend/app/db/models.py backend/alembic/versions/0020_operator_case_workspace.py database/schema.sql scripts/check_database_readonly.py backend/tests/test_operator_case_workspace_migration.py backend/tests/test_alembic_contracts.py backend/tests/test_longitudinal_schema_contracts.py backend/tests/test_schema_contracts.py
git commit -m "feat: add operator case audit and idempotency storage"
```

## Task 3: Add the Read-only Migration Preflight

**Files:**
- Create: `scripts/check_operator_case_workspace_migration_readonly.py`
- Create: `scripts/tests/test_check_operator_case_workspace_migration_readonly.py`

- [x] **Step 1: Write failing checker tests**

Cover empty database, valid existing database, illegal sex, incomplete profile counts, zero-visit counts, missing tables, unexpected database head and database errors. Illegal sex is `FAIL`; incomplete historical fields are explicit warnings requiring human acknowledgement. Database/query errors are `BLOCKED`, never PASS.

Required aggregate-only output includes `operator_case_count`, `invalid_sex_counts`, `missing_age_count`, `missing_sex_count`, `missing_baseline_stage_count`, `zero_visit_case_count`, `constraint_present`, `audit_table_present`, and `idempotency_table_present`; never output row-level identifiers.

- [x] **Step 2: Run and verify failure**

```text
pytest scripts/tests/test_check_operator_case_workspace_migration_readonly.py -q
```

- [x] **Step 3: Implement read-only collection**

Start with `SET TRANSACTION READ ONLY`. Use parameterized SQL against `information_schema`, `pg_constraint`, `alembic_version`, grouped sex counts and outer-join visit counts. Do not print row-level data or generate repair SQL.

- [x] **Step 4: Run tests and commit**

```text
pytest scripts/tests/test_check_operator_case_workspace_migration_readonly.py -q
git add scripts/check_operator_case_workspace_migration_readonly.py scripts/tests/test_check_operator_case_workspace_migration_readonly.py
git commit -m "feat: add readonly operator case workspace preflight"
```

## Task 4: Centralize Profile, Stage, and Timeline Validation

**Files:**
- Create: `backend/app/services/operator_case_validation.py`
- Create: `backend/tests/test_operator_case_validation.py`
- Modify: `backend/app/services/longitudinal_case_service.py`
- Modify: `backend/tests/test_longitudinal_case_service.py`

**Interfaces:**
- `validate_operator_case_profile(disease_code, age, sex, baseline_stage) -> str` returns the normalized stable stage.
- `normalize_operator_timeline(disease_code, visits) -> list[NormalizedVisit]` validates, sorts and numbers a complete `1–10` timeline without committing.
- `get_operator_case_for_write` retains owner predicate, row lock, active status and enabled disease checks.

- [x] **Step 1: Write failing validation tests**

Cover all four fatty-liver stages and four AD stages, cross-disease rejection, missing legacy fields on write, sorted/contiguous visit indexes, zero/eleven/duplicate dates and invalid indicators/units.

- [x] **Step 2: Run and verify failure**

```text
cd backend
pytest tests/test_operator_case_validation.py tests/test_longitudinal_case_service.py -q
```

- [x] **Step 3: Implement validators and transaction-neutral persistence**

Reuse `normalize_baseline_stage()`, accepting only a non-null normalized stage in the disease allow-list. Do not use `route_outcome_task()` as the save gate: definite stages `hcc`, `dementia` and `suspected_cirrhosis` remain valid cases even if a prediction task is not applicable. Reuse existing indicator/unit validation.

Add `replace_case_visits_in_session(db, case, normalized_visits)` which deletes/reinserts the timeline, assigns indexes `1..N`, flushes, and never commits or rolls back. No helper below the command layer may own a transaction.

- [x] **Step 4: Run tests and commit**

```text
cd backend
pytest tests/test_operator_case_validation.py tests/test_longitudinal_case_service.py -q
git add backend/app/services/operator_case_validation.py backend/app/services/longitudinal_case_service.py backend/tests/test_operator_case_validation.py backend/tests/test_longitudinal_case_service.py
git commit -m "refactor: centralize operator case validation"
```

## Task 5: Implement Minimal Diffs and Immutable Audit Writes

**Files:**
- Create: `backend/app/services/operator_case_diff.py`
- Create: `backend/app/services/operator_case_audit.py`
- Create: `backend/tests/test_operator_case_diff.py`
- Create: `backend/tests/test_operator_case_commands.py`

**Interfaces:**
- `build_case_diff(case, submitted_profile, normalized_visits) -> dict[str, Any]` is deterministic and empty for a no-op.
- `classify_case_action(changes)` selects `profile_updated`, `timeline_updated`, or `case_updated`.
- `append_case_change_log(...)` adds exactly one immutable row and never commits.

- [ ] **Step 1: Write failing deterministic diff tests**

Fix the JSON shape as:

```json
{
  "profile": {"age": {"before": 56, "after": 57}},
  "timeline": {
    "added": [{"visit_date": "2026-10-01", "indicators": [], "notes": null}],
    "removed": [],
    "updated": [
      {"visit_date": "2026-09-03", "fields": {"notes": {"before": null, "after": "复查"}}}
    ]
  }
}
```

Assert unchanged sections are omitted; indicator order is canonical; date changes are one removal plus one addition; actions are stable; `patient_label`, user ID and ORM row IDs never enter the diff.

- [ ] **Step 2: Run and verify failure**

```text
cd backend
pytest tests/test_operator_case_diff.py -q
```

- [ ] **Step 3: Implement pure diffs and audit insertion**

`append_case_change_log` accepts explicit action/reason/changes, copies case/actor snapshots, calls only `db.add()`/`db.flush()`, and propagates failures. Creation uses fixed reason `系统：建立病例` plus a privacy-bounded summary (`disease_id`, normalized stage, visit count and field names), not a request-body copy. Deletion uses fixed reason `用户确认删除病例` and `{"deleted":{"before":true,"after":false}}`. Actual corrections store approved before/after diffs.

- [ ] **Step 4: Run tests and commit**

```text
cd backend
pytest tests/test_operator_case_diff.py tests/test_operator_case_commands.py -q
git add backend/app/services/operator_case_diff.py backend/app/services/operator_case_audit.py backend/tests/test_operator_case_diff.py backend/tests/test_operator_case_commands.py
git commit -m "feat: audit operator case changes"
```

## Task 6: Implement Idempotent Create and Atomic Aggregate Save Commands

**Files:**
- Create: `backend/app/services/operator_case_idempotency.py`
- Create: `backend/app/services/operator_case_commands.py`
- Modify: `backend/tests/test_operator_case_commands.py`
- Modify: `backend/app/services/longitudinal_case_service.py`

**Interfaces:**
- `parse_idempotency_key(raw: str | None) -> UUID`.
- `hash_case_create(payload) -> str` uses normalized JSON with visits sorted by date.
- `create_operator_case_command(db, user_id, payload, key) -> OperatorCase` commits exactly once.
- `save_operator_case_command(db, user_id, case_id, payload) -> OperatorCase` writes profile, complete timeline and one audit atomically.
- `delete_operator_case_command(db, user_id, case_id) -> None` preserves deletion audit.

- [ ] **Step 1: Extend failing command tests**

Cover all of the following:

- create adds case, initial visits, created audit and idempotency row before one commit;
- any validation/flush/audit/idempotency failure rolls back all four;
- same key/same normalized request returns the original case without a second audit;
- same key/different request raises `idempotency_key_reused`;
- deleted original raises `idempotency_resource_missing`;
- a concurrent unique-key loser rolls back its provisional case and returns the winner only after hash checks;
- no-op aggregate save returns current case without audit and without requiring a reason;
- real diff without a trimmed reason raises a stable validation error;
- profile, timeline and combined saves each produce one matching audit and one commit;
- failed visit replacement leaves original profile/timeline unchanged;
- disease ID, owner, anonymous code and status are never taken from request data.

- [ ] **Step 2: Run and verify failure**

```text
cd backend
pytest tests/test_operator_case_commands.py -q
```

- [ ] **Step 3: Implement canonical hashing and replay checks**

```python
normalized = payload.model_dump(mode="json")
normalized["visits"] = sorted(normalized["visits"], key=lambda item: item["visit_date"])
body = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
request_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
```

First query `(user_id, scope, key)`. On first create validate and insert case/audit, then insert the completed idempotency row with `resource_id` in the same transaction. If unique-key flush loses a concurrent race, roll back the entire losing transaction, reload the winner, compare hashes and return its owned case. Never retain a provisional orphan case.

- [ ] **Step 4: Implement the aggregate save transaction**

```python
case = get_operator_case_for_write(db, user_id, case_id)
stage = validate_operator_case_profile(case.disease.code, payload.age, payload.sex, payload.baseline_stage)
timeline = normalize_operator_timeline(case.disease.code, payload.visits)
changes = build_case_diff(case, payload, timeline)
if not changes:
    return case
reason = require_change_reason(payload.change_reason)
apply_profile(case, payload, normalized_stage=stage)
replace_case_visits_in_session(db, case, timeline)
append_case_change_log(db, case, user_id, classify_case_action(changes), reason, changes)
db.commit()
db.refresh(case)
return case
```

Catch only known uniqueness/integrity cases. Unexpected exceptions rollback then re-raise; do not mislabel every integrity error as a duplicate visit date.

- [ ] **Step 5: Implement audited deletion**

Lock and validate the owned active case, append deletion audit, flush it, delete the case and commit once. The FK sets `case_id` null while snapshot columns remain.

- [ ] **Step 6: Run command/service tests and commit**

```text
cd backend
pytest tests/test_operator_case_commands.py tests/test_longitudinal_case_service.py tests/test_operator_case_status.py -q
git add backend/app/services/operator_case_idempotency.py backend/app/services/operator_case_commands.py backend/app/services/longitudinal_case_service.py backend/tests/test_operator_case_commands.py
git commit -m "feat: add atomic operator case commands"
```

## Task 7: Add Report Readiness from the Active Data Manifest

**Files:**
- Create: `backend/app/services/operator_case_readiness.py`
- Create: `backend/tests/test_operator_case_readiness.py`
- Create: `backend/tests/test_operator_case_workspace_api.py`
- Modify: `backend/app/api/operator.py`

**Interfaces:**
- `load_active_minimum_visits(dataset, registry_root=MODEL_DIR) -> int` verifies active release and manifest hashes.
- `evaluate_operator_case_readiness(case, registry_root=MODEL_DIR) -> OperatorCaseReportReadiness` returns stable blockers.
- Report creation reuses this evaluator before inserting `AIReport`.

- [ ] **Step 1: Write failing readiness tests**

Cover valid 1/2/3-visit cases, missing age/sex/stage, cross-disease stage, archived case, disabled disease, missing/invalid active pointer, manifest hash mismatch, non-applicable prediction stage and active model load failure. Assert the checked-in release yields `minimum_visits == 3` without a hard-coded fallback.

- [ ] **Step 2: Run and verify failure**

```text
cd backend
pytest tests/test_operator_case_readiness.py tests/test_operator_case_workspace_api.py -q
```

- [ ] **Step 3: Implement verified manifest loading and blocker evaluation**

Use `load_disease_release_set(dataset, MODEL_DIR)`, resolve `datasets/<data_release_id>/manifest.json` inside `MODEL_DIR`, compare its SHA-256 with `dataset_manifest_sha256`, parse a strict positive integer `minimum_visits`, and use `load_active_model_registry()` for model availability. Never fall back to 2 or 3 when metadata is unavailable.

Blocker codes include `case_incomplete`, `case_archived`, `disease_disabled`, `invalid_baseline_stage`, `insufficient_visits`, `invalid_timeline`, `prediction_not_applicable`, and `model_unavailable`.

- [ ] **Step 4: Gate report creation before persistence**

The report route locks the owned case, evaluates readiness, returns `409` for case/timeline blockers or `503` for model blockers, and inserts the generating report/input snapshot only when ready. It never saves browser draft content and never alters old reports.

- [ ] **Step 5: Run tests and commit**

```text
cd backend
pytest tests/test_operator_case_readiness.py tests/test_operator_case_workspace_api.py -q
git add backend/app/services/operator_case_readiness.py backend/app/api/operator.py backend/tests/test_operator_case_readiness.py backend/tests/test_operator_case_workspace_api.py
git commit -m "feat: add model-driven report readiness"
```

## Task 8: Replace the Operator API with the Production Workspace Boundary

**Files:**
- Modify: `backend/app/api/operator.py`
- Modify: `backend/app/schemas/longitudinal_case.py`
- Modify: `backend/tests/test_operator_case_workspace_api.py`
- Modify: `backend/tests/test_operator_catalog_and_reports_api.py`
- Modify: `backend/tests/test_longitudinal_case_service.py`

**Interfaces:**
- `POST /api/v1/operator/longitudinal-cases` requires `Idempotency-Key`.
- `PUT /api/v1/operator/longitudinal-cases/{case_id}` is the only profile/timeline mutation route.
- `GET .../report-readiness` returns the readiness model.
- List supports `q`, `disease_id`, `status`, `skip`, `limit` and owner-first filtering.
- `/api/v1/operator/cases*` and `/longitudinal-cases/{id}/visits*` mutations are removed.

- [ ] **Step 1: Finish failing route behavior tests**

Assert stable bodies such as:

```json
{"detail":{"code":"idempotency_key_missing","message":"缺少 Idempotency-Key"}}
```

Mappings: malformed/missing idempotency `400`; non-owned/not-found `404`; archived/disabled/duplicate/idempotency conflict `409`; validation/reason/stage/indicator `422`; model unavailable `503`. No response may expose raw exceptions, SQL, paths, model internals or request bodies.

- [ ] **Step 2: Implement thin route handlers and paginated query**

Import `Header`, parse the UUID and call command services. The API module must not create visit/audit/idempotency ORM rows or own cross-table commits.

```python
q: str | None = Query(None, min_length=1, max_length=32)
disease_id: int | None = Query(None, gt=0)
status_filter: OperatorCaseStatus | None = Query(None, alias="status")
skip: int = Query(0, ge=0)
limit: int = Query(20, ge=1, le=100)
```

Apply `OperatorCase.user_id == current_user.id` before all filters; search only escaped anonymous-code exact/prefix values, never `patient_label`.

- [ ] **Step 3: Remove reference-case and alternate visit mutation APIs**

Delete imports/handlers for `CaseRecordIn`, `CaseRecordOut`, `CaseRecord`, `/operator/cases*`, `VisitUpdate`, `VisitReplaceRequest`, and public add/update/delete/replace visit functions. Keep reference-case storage/import/similarity retrieval intact.

- [ ] **Step 4: Run focused and full backend unit tests**

```text
cd backend
pytest tests/test_operator_case_workspace_api.py tests/test_operator_catalog_and_reports_api.py tests/test_operator_case_workspace_schema.py tests/test_operator_case_commands.py tests/test_operator_case_readiness.py tests/test_longitudinal_case_service.py -q
pytest -q
```

- [ ] **Step 5: Commit the API boundary**

```text
git add backend/app/api/operator.py backend/app/schemas/longitudinal_case.py backend/tests/test_operator_case_workspace_api.py backend/tests/test_operator_catalog_and_reports_api.py backend/tests/test_longitudinal_case_service.py
git commit -m "refactor: expose one operator case workspace API"
```

## Task 9: Prove Transactions and Isolation against Real PostgreSQL

**Files:**
- Create: `docker-compose.test.yml`
- Create: `backend/tests/integration/conftest.py`
- Create: `backend/tests/integration/test_operator_case_workspace_api.py`
- Modify: `backend/requirements.txt`

**Interfaces:**
- Dedicated database `surgery_rag_operator_test` on `127.0.0.1:55432` using `pgvector/pgvector:pg16`.
- The suite refuses database names not ending in `_test`.
- Tests use real FastAPI HTTP requests and PostgreSQL transactions, never SQLite or a mocked Session.

- [ ] **Step 1: Add the isolated database definition**

Use project-scoped test credentials and a named volume, publish only loopback, add `pg_isready`, and never load repository `.env` or production secrets.

- [ ] **Step 2: Write the guarded fixture and failing integration matrix**

The fixture requires `TEST_DATABASE_URL`, validates the `_test` suffix, runs `alembic upgrade head`, creates two operators and the two enabled diseases, overrides `get_db` only in process, and truncates only explicit test-database tables between tests.

Cover forced audit failure rollback, same/different-key replay, two-user same UUID, aggregate rollback, archived/disabled/cross-owner access, 1→2→3 readiness, report preflight recheck, and immutable historical report snapshots.

- [ ] **Step 3: Run against PostgreSQL and complete fixes**

```powershell
docker compose -p surgery-rag-agent-test -f docker-compose.test.yml up -d --wait
$env:TEST_DATABASE_URL='postgresql://surgery_test:surgery_test@127.0.0.1:55432/surgery_rag_operator_test'
Set-Location backend
pytest tests/integration/test_operator_case_workspace_api.py -q
```

Add `httpx` explicitly to requirements for TestClient. Do not weaken production constraints or ownership checks.

- [ ] **Step 4: Verify migration round trip on the disposable database**

```powershell
Set-Location backend
alembic upgrade head
alembic downgrade 0019
alembic upgrade head
pytest tests/integration/test_operator_case_workspace_api.py -q
```

Before downgrade assert the new tables are empty; downgrade correctly refuses evidence loss otherwise.

- [ ] **Step 5: Commit the integration harness**

```text
git add docker-compose.test.yml backend/requirements.txt backend/tests/integration/conftest.py backend/tests/integration/test_operator_case_workspace_api.py
git commit -m "test: verify operator case transactions in postgres"
```

## Task 10: Replace Frontend API and Store Contracts under Vitest

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/vite.config.ts`
- Create: `frontend/tests/setup.ts`
- Modify: `frontend/src/api/operator.ts`
- Modify: `frontend/src/stores/operator.ts`
- Create: `frontend/src/api/__tests__/operator-case-workspace.spec.ts`
- Create: `frontend/src/stores/__tests__/operator-case-workspace.spec.ts`

**Interfaces:**
- Add `test:unit` and `test:unit:watch` scripts using Vitest/jsdom.
- `createLongitudinalCase(payload, idempotencyKey)` sends the header.
- `saveLongitudinalCase(id, aggregatePayload)` makes exactly one PUT.
- `getLongitudinalCaseReportReadiness(id)` supplies all blockers and the threshold.
- Store separates case-list/loading/saving/readiness/report-generation states.

- [ ] **Step 1: Install the test stack**

```text
cd frontend
npm install --save-dev vitest @vue/test-utils jsdom
```

Use `defineConfig` from `vitest/config`, `environment: 'jsdom'`, a setup file and existing Vue alias. Setup supplies deterministic `ResizeObserver`, `matchMedia` and Element Plus transition stubs only.

- [ ] **Step 2: Write failing API/store tests**

Mock only the HTTP adapter. Assert:

- no `CaseRecord`, `listCases`, `createCase`, `updateCase`, `deleteCase` or single-visit API remains;
- list sends `q/disease_id/status/skip/limit`;
- create sends one stable UUID across retry and rotates only after success/explicit reset;
- edit makes one aggregate PUT, never profile + timeline requests;
- create success does not call report generation;
- saving remains true until the actual Promise settles;
- readiness refreshes after successful save/status change;
- ordinary errors preserve the draft and a 409 surfaces before any explicit reload.

- [ ] **Step 3: Run and verify failure**

```text
cd frontend
npm run test:unit -- src/api/__tests__/operator-case-workspace.spec.ts src/stores/__tests__/operator-case-workspace.spec.ts
```

- [ ] **Step 4: Implement strict TypeScript contracts**

```ts
export interface LongitudinalCaseCreatePayload {
  disease_id: number
  age: number
  sex: 'male' | 'female'
  baseline_stage: BaselineStage
  notes: string | null
  visits: LongitudinalVisitInput[]
}

export interface LongitudinalCaseSavePayload {
  age: number
  sex: 'male' | 'female'
  baseline_stage: BaselineStage
  notes: string | null
  visits: LongitudinalVisitInput[]
  change_reason?: string | null
}
```

`LongitudinalCase` keeps nullable legacy output fields but removes `patient_label`. Add a typed normalizer for `{detail:{code,message,field_errors?}}` that never clears draft state.

- [ ] **Step 5: Implement request lifecycles**

Generate a draft UUID with `crypto.randomUUID()` and never persist clinical draft data in localStorage. Use `try/finally` per loading flag, mutate selected/list state only after success, then fetch readiness. Report generation requires server readiness and never saves implicitly.

- [ ] **Step 6: Run tests/build and commit**

```text
cd frontend
npm run test:unit -- src/api/__tests__/operator-case-workspace.spec.ts src/stores/__tests__/operator-case-workspace.spec.ts
npm run build
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/tests/setup.ts frontend/src/api/operator.ts frontend/src/stores/operator.ts frontend/src/api/__tests__/operator-case-workspace.spec.ts frontend/src/stores/__tests__/operator-case-workspace.spec.ts
git commit -m "refactor: use aggregate operator case frontend API"
```

## Task 11: Build the Case Workspace Components Test-first

**Files:**
- Create: `frontend/src/components/operator-case/OperatorCaseList.vue`
- Create: `frontend/src/components/operator-case/OperatorCaseProfileForm.vue`
- Create: `frontend/src/components/operator-case/OperatorVisitTimelineEditor.vue`
- Create: `frontend/src/components/operator-case/OperatorCaseActionBar.vue`
- Create: `frontend/src/components/operator-case/CaseChangeReasonDialog.vue`
- Create: `frontend/src/components/operator-case/OperatorCaseWorkspace.vue`
- Create: `frontend/src/components/operator-case/__tests__/OperatorCaseWorkspace.spec.ts`

**Interfaces:**
- `OperatorCaseWorkspace` owns draft/dirty state and composes focused presentational children.
- Child components use typed props/events and never call APIs directly.
- Existing-case disease is read-only; incomplete legacy fields are visibly enumerated.

- [ ] **Step 1: Write failing component behavior tests**

Mount with testing Pinia and cover:

- new draft has profile plus exactly one initial visit;
- field errors attach to age/sex/stage/date/indicator/unit/value and are announced;
- save is disabled until required values are valid;
- first save awaits the Promise, stays on detail, shows anonymous code and does not generate;
- a real edit opens the reason dialog; no-op does not write;
- failed save preserves every typed value;
- archived/disabled/generating states are read-only;
- legacy missing fields show an incomplete banner and require complete repair;
- readiness renders API blockers/threshold rather than literal 3;
- dirty selection/new/report navigation asks for confirmation;
- keyboard focus and reduced-motion behavior remain available.

- [ ] **Step 2: Run and verify failure**

```text
cd frontend
npm run test:unit -- src/components/operator-case/__tests__/OperatorCaseWorkspace.spec.ts
```

- [ ] **Step 3: Implement list and profile components**

List: debounced anonymous-code search, disease/status filters, server pagination, skeleton/empty/error states, semantic labels and selection. Profile: disease-specific stage options with Chinese labels and stable English values; disease becomes read-only after creation.

- [ ] **Step 4: Implement timeline, action bar and reason dialog**

Timeline renders `1–10` dated cards, never deletes the last visit, prevents duplicate dates and uses the existing disease indicator/unit definitions. Sort only the submitted snapshot so focus does not jump while typing. Action bar shows dirty/saving/readiness states and a separate report button. Reason dialog trims and validates `1–500` characters without clearing draft on cancel.

- [ ] **Step 5: Implement workspace orchestration and design CSS**

Keep a deep-cloned server baseline and canonical draft for dirty comparison. Create uses the current idempotency key; edit submits one aggregate payload and reason. Register route-leave and `beforeunload` guards, remove them on unmount, and freeze editing during report generation.

Use `docs/DESIGN_SPEC.md` variables: 260/64px sidebar, 56px top bar, max 880px content, 12px cards, 10px controls, 44px targets, warm surfaces, visible focus, non-color status text and `prefers-reduced-motion`.

- [ ] **Step 6: Run tests/build and commit**

```text
cd frontend
npm run test:unit -- src/components/operator-case/__tests__/OperatorCaseWorkspace.spec.ts
npm run build
git add frontend/src/components/operator-case
git commit -m "feat: build operator case workspace"
```

## Task 12: Integrate the Workspace and Remove the Reference-case UI

**Files:**
- Modify: `frontend/src/components/OperatorSidebar.vue`
- Modify: `frontend/src/views/OperatorView.vue`
- Delete: `frontend/src/components/CaseManageView.vue`
- Delete: `frontend/src/components/IndicatorRowsEditor.vue`
- Delete: `frontend/src/components/LongitudinalCaseEditor.vue`
- Modify: `frontend/src/components/operator-case/__tests__/OperatorCaseWorkspace.spec.ts`

**Interfaces:**
- Operator shell exposes “新建病例 / 我的病例 / 历史报告” without a `case_records` view.
- Sidebar defaults to owned cases; reports remain reachable without mixing data models.
- Report viewer is separate and can return to the selected case.

- [ ] **Step 1: Add failing shell integration tests**

Assert the new workspace mounts, old editors are absent, selecting a report does not discard a dirty case without confirmation, and create success remains on case detail.

- [ ] **Step 2: Replace the view composition**

Use explicit shell modes `workspace` and `report`. Sidebar tabs switch between owned cases and historical reports; “新建病例” creates a fresh draft only after dirty confirmation. Retain report streaming/viewer components but start generation only from the workspace action bar.

- [ ] **Step 3: Delete dead UI and imports**

Remove the three obsolete components and all `CaseRecord`/single-visit imports. Confirm `IndicatorRowsEditor` has no other consumer.

- [ ] **Step 4: Run searches, tests and build**

```text
cd frontend
rg -n "CaseManageView|IndicatorRowsEditor|LongitudinalCaseEditor|CaseRecord|listCases|createCase|updateCase|deleteCase|addLongitudinalVisit|replaceLongitudinalVisits" src
npm run test:unit
npm run build
```

Expected: no obsolete-symbol matches; tests and build PASS.

- [ ] **Step 5: Commit shell integration**

```text
git add frontend/src/components/OperatorSidebar.vue frontend/src/views/OperatorView.vue frontend/src/components/operator-case/__tests__/OperatorCaseWorkspace.spec.ts frontend/src/components/CaseManageView.vue frontend/src/components/IndicatorRowsEditor.vue frontend/src/components/LongitudinalCaseEditor.vue
git commit -m "refactor: make longitudinal cases the operator workspace"
```

## Task 13: Add Playwright End-to-End Acceptance with Database Assertions

**Files:**
- Create: `backend/tests/e2e/conftest.py`
- Create: `backend/tests/e2e/test_operator_case_workspace.py`
- Create: `scripts/run_operator_case_e2e.ps1`

**Interfaces:**
- Python Playwright drives real Vue → FastAPI → test PostgreSQL.
- Runner starts/stops only explicitly named test services and never uses production config.
- E2E checks UI results and selected database invariants.

- [ ] **Step 1: Write failing browser scenarios**

For both diseases:

```text
login operator A
→ create complete case with one first visit
→ assert anonymous code/detail and no auto-report
→ assert API-driven readiness blocker
→ add second and third visits
→ save once with reason
→ assert readiness enabled
→ generate report
→ assert completion and immutable input snapshot
```

Add operator B isolation and failed-save/draft-preservation scenarios. Verify B never lists or accesses A's case/readiness/report and never receives A-attributed audit/report rows.

- [ ] **Step 2: Implement deterministic E2E fixtures**

Seed two `ai_operator` users and enabled fatty-liver/AD rows through the test SQLAlchemy session. Use semantic selectors and only add `data-testid` when role/name is insufficient. Stub only external LLM streaming at the service boundary; do not mock case APIs, database, readiness, manifest loading or authentication.

- [ ] **Step 3: Implement the guarded PowerShell runner**

It sets compose project `surgery-rag-agent-test`, starts the test database, sets test-only DB/JWT values, disables unnecessary embedding warmup through an explicit test setting, starts backend/frontend child processes, waits for health, runs E2E, stops only recorded child PIDs in `finally`, and preserves redacted logs on failure.

- [ ] **Step 4: Install browser and run E2E**

```powershell
Set-Location backend
python -m playwright install chromium
Set-Location ..
powershell -ExecutionPolicy Bypass -File scripts/run_operator_case_e2e.ps1
```

Expected: both disease flows, draft preservation and two-operator isolation PASS; DB assertions find one creation audit, one aggregate update audit, expected visits, one report and unchanged snapshot.

- [ ] **Step 5: Commit E2E acceptance**

```text
git add backend/tests/e2e/conftest.py backend/tests/e2e/test_operator_case_workspace.py scripts/run_operator_case_e2e.ps1
git commit -m "test: cover operator case workspace end to end"
```

## Task 14: Full Regression, Security Review, and Documentation Closure

**Files:**
- Modify: `docs/AI操作者流程核查.md`
- Modify: `docs/superpowers/specs/2026-09-03-ai-operator-case-workspace-design.md`
- Modify: `docs/superpowers/plans/2026-09-03-ai-operator-case-workspace-implementation.md`

- [ ] **Step 1: Run backend and frontend full regression**

```text
cd backend
pytest -q
alembic heads
cd ../frontend
npm run test:unit
npm run build
```

Record observed totals and confirm exactly one Alembic head.

- [ ] **Step 2: Re-run clean real-DB and browser acceptance**

```powershell
docker compose -p surgery-rag-agent-test -f docker-compose.test.yml down -v
docker compose -p surgery-rag-agent-test -f docker-compose.test.yml up -d --wait
$env:TEST_DATABASE_URL='postgresql://surgery_test:surgery_test@127.0.0.1:55432/surgery_rag_operator_test'
Set-Location backend
pytest tests/integration/test_operator_case_workspace_api.py -q
Set-Location ..
powershell -ExecutionPolicy Bypass -File scripts/run_operator_case_e2e.ps1
```

Before deleting the volume verify the compose project name is exactly `surgery-rag-agent-test`; only disposable test data is in scope.

- [ ] **Step 3: Run privacy, ownership, and dead-path searches**

```text
rg -n "patient_label|CaseRecord|/operator/cases|addLongitudinalVisit|replaceLongitudinalVisits" frontend/src backend/app/api/operator.py backend/app/schemas/longitudinal_case.py
rg -n "request\.body|anonymous_case_code|indicators" backend/app -g "*.py"
```

Inspect every match. Confirm no legacy UI/API exposure, no restricted-value logging, owner predicates on every case/report path, and no report insertion before readiness.

- [ ] **Step 4: Review every confirmed acceptance point**

Manually verify: first visit and definite stage; save stays on detail and does not auto-generate; `operator_cases` only; one-request/one-transaction update; last-write-wins plus audit; legacy incomplete blocking; manifest threshold; stable errors/input preservation; accessibility/loading/navigation protection; old reports unchanged.

- [ ] **Step 5: Update documents only after evidence exists**

In `docs/AI操作者流程核查.md`, mark item 1 repository-complete, cite exact implementation/test files and observed commands, and state “尚未在生产环境执行迁移/部署”. Mark the design implemented and append verification totals to this plan. Do not claim production deployment.

- [ ] **Step 6: Request code review and address findings**

Use the `requesting-code-review` skill on the complete diff from `ea8811c` through HEAD. Fix valid findings with focused tests, then rerun affected suites and final build.

- [ ] **Step 7: Commit documentation closure**

```text
git add docs/AI操作者流程核查.md docs/superpowers/specs/2026-09-03-ai-operator-case-workspace-design.md docs/superpowers/plans/2026-09-03-ai-operator-case-workspace-implementation.md
git commit -m "docs: close operator case creation checklist"
```

---

## Production Rollout Runbook (not executed by this plan)

```text
1. Back up production and verify restore readiness.
2. Run the workspace preflight in read-only mode.
3. Human-review illegal-sex, incomplete-profile and zero-visit counts.
4. If illegal sex or unexpected zero-visit rows exist, stop and use a separately approved remediation plan.
5. Run alembic upgrade head and verify 0020 constraints/indexes.
6. Deploy backend, then frontend.
7. Smoke-test fatty liver and AD with non-production test identities.
8. Verify only aggregate metrics: errors/latency, idempotency, blockers, audit failures.
9. On application rollback retain schema and evidence tables; never downgrade non-empty audit/idempotency data.
```

## Definition of Done

- Every checkbox is completed with observed command output.
- Backend suites, real PostgreSQL integration, frontend Vitest/build and Playwright E2E pass.
- One Alembic head exists at `0020`; ORM, migration, clean SQL and read-only checks agree.
- No operator API/frontend exposes or manages `case_records` or `patient_label`.
- No profile/timeline change bypasses the aggregate audited transaction.
- Both diseases pass create-with-first-visit, continued editing, manifest-driven readiness and independent report generation.
- Item 1 documentation records repository evidence and explicitly says production deployment remains outstanding.
