# Versioned Standard Rules Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an administrator-controlled, versioned DOCX standard rules layer for fatty-liver and AD standards, with audited review, safe `reference_ranges` projections, and resolver-backed longitudinal report evidence.

**Architecture:** Add normalized ORM entities for standards, immutable versions, indicators, DOCX segments, parse candidates, rules, condition trees, and change logs. A deterministic DOCX parser produces reviewable candidates; LLM output is isolated as candidate data. Approval atomically retires the previous version, publishes a read-only compatibility projection, and makes the new version available to a resolver used by longitudinal report evidence without changing model features.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, Alembic, PostgreSQL JSONB, `python-docx`, Pydantic v2, Vue 3, TypeScript, Element Plus, Node test runner, pytest.

## Global Constraints

- 首期只迁移脂肪肝标准、AD 标准；源文件只支持 DOCX。
- 管理员拥有标准版本完整生命周期权限；AI 操作者只能读取已批准版本。
- 版本状态固定为 `draft -> review -> approved -> retired`；新版本批准后立即生效并自动退役旧版本。
- `draft`/`review` 可逐条编辑且必须记录修改前后值、操作者、时间和原因；`approved`/`retired` 不可原地修改。
- 方向性、影像、研究发现、框架冲突或适用条件不足的内容必须是 `evidence-only`，不得进入机器投影。
- `<`、`>` 为开区间；`≤`、`≥` 为闭区间；多个研究阈值不得平均、合并或按写入时间覆盖。
- 标准内容不进入病例 `Chunk` 或病例向量库；标准解析直接读取 DOCX 结构。
- 不修改现有纵向模型 `.joblib`、`meta.json`、特征顺序或风险计算逻辑。
- 所有前端 UI 修改前遵循 `docs/DESIGN_SPEC.md` 的暖杏蓝、侧边栏、间距、无障碍和动效规范。
- 不在本计划中恢复单时点指标预测报告；AI 操作者保留纵向病例、进展预测和预测报告生成/查看/下载/删除。

## File Map

- `backend/app/db/models.py`: 新增标准层 ORM 实体，扩展 `ReferenceRange` 投影字段。
- `backend/alembic/versions/0009_versioned_standard_rules.py`: 新表、外键、索引、约束和投影字段迁移。
- `backend/app/schemas/standard.py`: 标准、版本、片段、候选、规则、校验和 API 输入输出契约。
- `backend/app/services/standard_parser.py`: DOCX 结构解析和确定性候选生成。
- `backend/app/services/standard_validation.py`: 规则、条件树、适用条件和投影资格校验。
- `backend/app/services/standard_lifecycle.py`: 版本状态、逐条编辑、变更日志、批准事务和投影生成。
- `backend/app/services/standard_resolver.py`: 当前批准版本的规则解析和上下文匹配。
- `backend/app/api/admin_standards.py`: 管理员标准 API。
- `backend/app/api/operator.py`, `backend/app/services/longitudinal_evidence.py`, `backend/app/services/longitudinal_report_generator.py`: resolver 接入和操作者同步入口清理。
- `backend/tests/test_standard_models.py`, `test_standard_parser.py`, `test_standard_validation.py`, `test_standard_lifecycle.py`, `test_standard_resolver.py`, `test_admin_standards_api.py`: 后端单元/API/契约测试。
- `scripts/seed_standard_drafts.py`: 使用明确 DOCX 路径创建首期 draft 版本的可重复脚本。
- `frontend/src/api/adminStandards.ts`: 管理员标准 API 客户端。
- `frontend/src/components/StandardManagementView.vue`: 标准集合、版本和审核工作台。
- `frontend/src/components/AdminSidebar.vue`, `frontend/src/views/AdminView.vue`: 标准管理导航和区块挂载。
- `frontend/src/components/CaseManageView.vue`, `frontend/src/api/operator.ts`: 删除 AI 操作者标准同步入口。
- `frontend/tests/standard-management-ui-contract.test.mjs`: 管理员和操作者 UI 契约测试。

---

### Task 1: Standard ORM and Alembic Contract

**Files:**
- Create: `backend/alembic/versions/0009_versioned_standard_rules.py`
- Modify: `backend/app/db/models.py`
- Test: `backend/tests/test_standard_models.py`, `backend/tests/test_alembic_contracts.py`

**Interfaces:**
- Produces ORM classes `ReferenceStandard`, `ReferenceStandardVersion`, `StandardIndicator`, `StandardSegment`, `StandardParseCandidate`, `StandardRule`, `StandardRuleCondition`, `StandardChangeLog`.
- Produces `ReferenceRange.standard_id`, `standard_version_id`, `standard_rule_id`, `applicability_hash`, and `is_current_projection`.

- [ ] **Step 1: Write failing model contract tests**

```python
def test_standard_entities_and_projection_columns_exist():
    from app.db.models import (
        ReferenceStandard, ReferenceStandardVersion, StandardIndicator,
        StandardSegment, StandardParseCandidate, StandardRule,
        StandardRuleCondition, StandardChangeLog, ReferenceRange,
    )
    assert ReferenceStandard.__table__.columns["disease_id"].unique
    assert ReferenceStandardVersion.__table__.columns["content_hash"].nullable is False
    assert {"status", "document_id", "supersedes_version_id"}.issubset(ReferenceStandardVersion.__table__.columns)
    assert {"source_segment_id", "machine_actionability", "target_state_type"}.issubset(StandardRule.__table__.columns)
    assert {"standard_id", "standard_version_id", "standard_rule_id", "is_current_projection"}.issubset(ReferenceRange.__table__.columns)
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `cd backend; pytest tests/test_standard_models.py -q`

Expected: FAIL because the standard ORM classes and projection columns do not exist.

- [ ] **Step 3: Add ORM entities and migration**

Define foreign keys to `diseases`, `documents`, and `users` with explicit `ondelete` behavior; define indexes for version status, segment lookup, rule indicator, candidate segment, change-log entity, and current projections. Use PostgreSQL `JSONB` for `applicability`, structured candidate payloads, and condition payloads. Add a check constraint for the four version statuses and a partial unique index ensuring one current projection per standard/indicator/sex/category/applicability hash.

- [ ] **Step 4: Run model and migration contract tests**

Run: `cd backend; pytest tests/test_standard_models.py tests/test_alembic_contracts.py -q`

Expected: PASS, including a linear `0008 -> 0009` revision assertion and the projection column/default checks.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/0009_versioned_standard_rules.py backend/tests/test_standard_models.py backend/tests/test_alembic_contracts.py
git commit -m "feat: add versioned standard rule schema"
```

### Task 2: DOCX Structure Parser and Candidate Contract

**Files:**
- Create: `backend/app/services/standard_parser.py`
- Create: `backend/app/schemas/standard.py`
- Test: `backend/tests/test_standard_parser.py`
- Fixture input: `backend/tests/fixtures/standards/AD标准.docx`, `backend/tests/fixtures/standards/脂肪肝标准.docx`

**Interfaces:**
- Produces `parse_standard_docx(path: str, *, parser_version: str) -> ParsedStandardDocument`.
- Produces `parse_numeric_expression(text: str) -> NumericExpression | None`.
- Produces `build_rule_candidates(parsed: ParsedStandardDocument) -> list[RuleCandidate]`.

- [ ] **Step 1: Add parser tests for both real document shapes**

```python
def test_parse_both_standards_preserves_table_locations():
    ad = parse_standard_docx("backend/tests/fixtures/standards/AD标准.docx", parser_version="v1")
    fatty = parse_standard_docx("backend/tests/fixtures/standards/脂肪肝标准.docx", parser_version="v1")
    assert len(ad.tables) == 8 and len(fatty.tables) == 4
    assert any(segment.table_index == 5 and segment.row_index == 6 for segment in ad.segments)
    assert any("MAFLD" in segment.raw_text for segment in fatty.segments)

def test_parse_numeric_expression_preserves_open_and_closed_bounds():
    assert parse_numeric_expression("< 1.158").upper_inclusive is False
    assert parse_numeric_expression("≥ 5% ").lower_inclusive is True
    assert parse_numeric_expression("5%–10%").lower == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend; pytest tests/test_standard_parser.py -q`

Expected: FAIL because the parser module and schemas do not exist.

- [ ] **Step 3: Implement structure-aware parsing**

Read paragraphs and tables directly with `python-docx`; emit segment type, section text, table/row/column coordinates, and raw cell text. Parse English identifiers, Chinese display names, numeric ranges, strict/inclusive comparisons, units, sex segments, target-state columns, and explicit applicability phrases. Preserve qualitative text as candidates instead of forcing numeric output. Do not call the generic chunker or vector store.

- [ ] **Step 4: Implement deterministic candidates and isolated LLM candidate hook**

Return deterministic candidates with `source_type="deterministic"`; expose a pure hook accepting `(segment_text, context) -> dict | None` for the later LLM adapter, but do not persist or publish LLM output in this task. Candidate payloads must carry `machine_actionability` and `evidence_type`.

- [ ] **Step 5: Run parser tests and commit**

Run: `cd backend; pytest tests/test_standard_parser.py -q`

Expected: PASS with exact boundary semantics and complete source locations.

```bash
git add backend/app/services/standard_parser.py backend/app/schemas/standard.py backend/tests/test_standard_parser.py backend/tests/fixtures/standards
git commit -m "feat: add structured standard docx parser"
```

### Task 3: Validation, Conditions, Editing, and Audit Service

**Files:**
- Create: `backend/app/services/standard_validation.py`
- Create: `backend/app/services/standard_lifecycle.py`
- Modify: `backend/app/schemas/standard.py`
- Test: `backend/tests/test_standard_validation.py`, `backend/tests/test_standard_lifecycle.py`

**Interfaces:**
- Produces `validate_version(db, version_id: int) -> ValidationReport`.
- Produces `update_draft_rule(db, admin_id: int, rule_id: int, patch: RulePatch, reason: str) -> StandardRule`.
- Produces `transition_version(db, admin_id: int, version_id: int, target_status: str) -> ReferenceStandardVersion`.
- Produces `build_condition_tree(payload: ConditionPayload) -> StandardRuleCondition`.

- [ ] **Step 1: Write failing validation and lifecycle tests**

```python
def test_incomplete_platform_threshold_is_not_calculable():
    report = validate_rule(RuleDraft(rule_type="threshold", upper=1.158, unit="", applicability={}))
    assert report.errors == []
    assert report.actionability == "evidence-only"

def test_approved_rule_cannot_be_edited(db, admin_id, approved_rule):
    with pytest.raises(ImmutableVersionError):
        update_draft_rule(db, admin_id, approved_rule.id, RulePatch(upper=2), "校正边界")

def test_rule_edit_writes_before_after_and_reason(db, admin_id, draft_rule):
    update_draft_rule(db, admin_id, draft_rule.id, RulePatch(upper=2.0), "修正原文边界")
    log = db.query(StandardChangeLog).one()
    assert log.before_json["upper"] != log.after_json["upper"]
    assert log.reason == "修正原文边界"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend; pytest tests/test_standard_validation.py tests/test_standard_lifecycle.py -q`

Expected: FAIL because validation, condition, lifecycle, and audit services are absent.

- [ ] **Step 3: Implement condition-tree validation**

Validate `all`, `any`, `not`, `at_least_n`, and `at_most_n` nodes; reject missing child references and cycles. Validate sex/age/platform/tracer/scale/framework predicates and ensure fatty-liver `steatosis` rules cannot be combined with `fibrosis_risk` rules in one classification result.

- [ ] **Step 4: Implement rule validation and lifecycle transitions**

Return `error`, `warning`, and `info` findings. Mark direction/影像/研究/缺失适用条件 as `evidence-only`; reject incomplete calculable numeric rules. Allow only `draft -> review -> approved -> retired`, with `approved` requiring no errors and a publishable projection count. Persist every rule edit as a change log with before/after JSON and reason.

- [ ] **Step 5: Run focused tests and commit**

Run: `cd backend; pytest tests/test_standard_validation.py tests/test_standard_lifecycle.py -q`

Expected: PASS for actionability, condition-tree validation, immutable versions, state transitions, and audit records.

```bash
git add backend/app/services/standard_validation.py backend/app/services/standard_lifecycle.py backend/app/schemas/standard.py backend/tests/test_standard_validation.py backend/tests/test_standard_lifecycle.py
git commit -m "feat: validate and audit standard rule review"
```

### Task 4: Administrator API and Atomic Projection Publishing

**Files:**
- Create: `backend/app/api/admin_standards.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/services/standard_lifecycle.py`
- Test: `backend/tests/test_admin_standards_api.py`, `backend/tests/test_standard_lifecycle.py`

**Interfaces:**
- Produces the `/v1/admin/reference-standards*` routes defined in the approved spec.
- Produces `publish_approved_version(db, admin_id: int, version_id: int) -> PublishResult`.

- [ ] **Step 1: Write failing API and publish tests**

```python
def test_non_admin_cannot_create_standard(client, user_token):
    response = client.post("/api/v1/admin/reference-standards", headers=auth(user_token), json={"disease_id": 1, "name": "AD标准"})
    assert response.status_code == 403

def test_approve_retires_previous_version_and_projects_only_calculable(db, admin_id, old_version, new_version):
    result = publish_approved_version(db, admin_id, new_version.id)
    assert result.version.status == "approved"
    assert db.refresh(old_version).status == "retired"
    assert all(row.is_current_projection for row in result.projections)
    assert all(row.standard_rule.machine_actionability == "calculable" for row in result.projections)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend; pytest tests/test_admin_standards_api.py tests/test_standard_lifecycle.py -q`

Expected: FAIL because routes and atomic publishing are not registered.

- [ ] **Step 3: Implement admin schemas and routes**

Use `require_admin` for every route. Enforce DOCX extension and stable file hash when creating a version. Return `409` for edits or transitions that violate the state machine. Expose standard collections, versions, segments, rules, candidates, validation, rule history, parse, submit-review, approve, and retire endpoints. The parse endpoint persists deterministic candidates immediately and, for unresolved segments, invokes the existing DeepSeek client through an injectable adapter, then persists the raw response and normalized candidate as `source_type="llm"`; malformed or timed-out LLM output remains a failed candidate and never becomes a rule.

- [ ] **Step 4: Implement atomic projection publishing**

In one transaction: validate version, mark it approved, set `effective_from`, retire the previous current version, set `is_current_projection=false` on old rows, insert only calculable compatible rules with standard/version/rule/applicability provenance, set new projection rows current, update `current_version_id`, and write a publish change log. Roll back all mutations on validation or projection failure.

- [ ] **Step 5: Run API tests and commit**

Run: `cd backend; pytest tests/test_admin_standards_api.py tests/test_standard_lifecycle.py -q`

Expected: PASS for admin authorization, lifecycle routes, immutable-state errors, hash checks, and atomic projection behavior.

```bash
git add backend/app/api/admin_standards.py backend/app/main.py backend/app/services/standard_lifecycle.py backend/tests/test_admin_standards_api.py backend/tests/test_standard_lifecycle.py
git commit -m "feat: add admin standard lifecycle API"
```

### Task 5: Resolver and Longitudinal Evidence Migration

**Files:**
- Create: `backend/app/services/standard_resolver.py`
- Modify: `backend/app/services/longitudinal_evidence.py`
- Modify: `backend/app/services/longitudinal_report_generator.py`
- Modify: `backend/app/api/operator.py`
- Test: `backend/tests/test_standard_resolver.py`, `backend/tests/test_longitudinal_evidence.py`, `backend/tests/test_longitudinal_report_generator.py`

**Interfaces:**
- Produces `resolve_standard_rules(db, disease_id: int, indicator_names: list[str], context: dict) -> ResolvedStandardRules`.
- Replaces direct `ReferenceRange` lookup inside `build_reference_range_sources()` while preserving its source list shape plus version/rule provenance.

- [ ] **Step 1: Write failing resolver tests**

```python
def test_resolver_rejects_missing_platform_context(db, approved_version, threshold_rule):
    result = resolve_standard_rules(db, 2, ["FDG-PET SUVR"], {})
    assert result.calculable_rules == []
    assert result.evidence_rules[0].machine_actionability == "evidence-only"

def test_resolver_preserves_two_study_thresholds(db, approved_version, study_rules):
    result = resolve_standard_rules(db, 2, ["CSF Aβ42/Aβ40"], {"cohort": "DELCODE"})
    assert len(result.calculable_rules) == 1
    assert result.calculable_rules[0].standard_rule_id == study_rules.delcode.id

def test_report_source_contains_version_and_rule_snapshot(db, approved_case):
    sources = build_reference_range_sources(db, ["ALT"], "male")
    assert {"standard_version_id", "standard_rule_id", "applicability_hash"}.issubset(sources[0])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend; pytest tests/test_standard_resolver.py tests/test_longitudinal_evidence.py tests/test_longitudinal_report_generator.py -q`

Expected: FAIL because evidence still queries `ReferenceRange` directly and no resolver result type exists.

- [ ] **Step 3: Implement context matching and conflict handling**

Load only the disease's `current_version_id`; match indicator canonical keys and applicability predicates; return calculable, evidence-only, unmatched, version metadata, and warnings. Never select by `created_at`, average thresholds, or silently break ties. Include strict boundary fields and provenance in each source.

- [ ] **Step 4: Migrate report evidence without changing model input**

Change `build_reference_range_sources()` and report rendering to include evidence-only explanations and applicability warnings. Keep the existing prediction feature extraction untouched. Persist the resolver snapshot in `AIReport.sources` and `prediction_result` before streaming `done`.

- [ ] **Step 5: Run longitudinal tests and commit**

Run: `cd backend; pytest tests/test_standard_resolver.py tests/test_longitudinal_evidence.py tests/test_longitudinal_report_generator.py -q`

Expected: PASS with unchanged longitudinal model outputs and versioned evidence sources.

```bash
git add backend/app/services/standard_resolver.py backend/app/services/longitudinal_evidence.py backend/app/services/longitudinal_report_generator.py backend/app/api/operator.py backend/tests/test_standard_resolver.py backend/tests/test_longitudinal_evidence.py backend/tests/test_longitudinal_report_generator.py
git commit -m "feat: resolve versioned standard evidence in reports"
```

### Task 6: Seed Initial Draft Versions

**Files:**
- Create: `scripts/seed_standard_drafts.py`
- Create: `backend/tests/test_seed_standard_drafts.py`
- Modify: `backend/app/services/standard_lifecycle.py` only if the script needs a public helper

**Interfaces:**
- Produces CLI `python scripts/seed_standard_drafts.py --ad PATH --fatty-liver PATH --admin-id ID`.
- Produces idempotent `seed_standard_draft(db, disease_id: int, document_id: int, version_label: str) -> ReferenceStandardVersion`.

- [ ] **Step 1: Write failing idempotency tests**

```python
def test_seed_draft_is_idempotent_for_same_content_hash(db, admin_id, ad_docx):
    first = seed_standard_draft(db, 2, ad_docx.id, "AD-2026-08-24")
    second = seed_standard_draft(db, 2, ad_docx.id, "AD-2026-08-24")
    assert first.id == second.id
    assert first.status == "draft"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend; pytest tests/test_seed_standard_drafts.py -q`

Expected: FAIL because the seed helper does not exist.

- [ ] **Step 3: Implement explicit-path draft seeding**

Resolve each DOCX by path, create or reuse the corresponding `Document`, compute its content hash, create the disease-linked standard collection if absent, and create a draft version without calling approve or generating projections. Fail with a clear non-zero exit code for missing files, non-DOCX files, missing diseases, or hash mismatch.

- [ ] **Step 4: Run seed tests and commit**

Run: `cd backend; pytest tests/test_seed_standard_drafts.py -q`

Expected: PASS for idempotency, no auto-approval, and missing-file/type errors.

```bash
git add scripts/seed_standard_drafts.py backend/tests/test_seed_standard_drafts.py backend/app/services/standard_lifecycle.py
git commit -m "feat: add initial standard draft seeding"
```

### Task 7: Administrator Standard Management UI

**Files:**
- Create: `frontend/src/api/adminStandards.ts`
- Create: `frontend/src/components/StandardManagementView.vue`
- Modify: `frontend/src/components/AdminSidebar.vue`
- Modify: `frontend/src/views/AdminView.vue`
- Test: `frontend/tests/standard-management-ui-contract.test.mjs`

**Interfaces:**
- Produces typed clients for the admin standard endpoints and a `StandardManagementView` component mounted when `activeSection === 'standards'`.

- [ ] **Step 1: Write failing UI contract tests**

```javascript
test('admin navigation exposes standard management', async () => {
  const sidebar = await readFile(new URL('../src/components/AdminSidebar.vue', import.meta.url), 'utf8')
  const view = await readFile(new URL('../src/views/AdminView.vue', import.meta.url), 'utf8')
  assert.match(sidebar, /key: 'standards'/)
  assert.match(sidebar, /标准管理/)
  assert.match(view, /activeSection === 'standards'/)
})

test('review UI exposes editable rules and lifecycle actions', async () => {
  const source = await readFile(new URL('../src/components/StandardManagementView.vue', import.meta.url), 'utf8')
  assert.match(source, /提交审核/)
  assert.match(source, /批准发布/)
  assert.match(source, /修改原因/)
  assert.match(source, /evidence-only/)
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend; node --test tests/standard-management-ui-contract.test.mjs`

Expected: FAIL because the navigation entry, API client, and component do not exist.

- [ ] **Step 3: Implement typed admin API client**

Define TypeScript interfaces for standard collections, versions, segments, candidates, rules, validation findings, and publish results. Add functions for list/create/get, parse, submit-review, approve, retire, list segments/rules/candidates, patch rule with reason, history, and validation.

- [ ] **Step 4: Implement the standards workbench**

Create a four-area Element Plus workbench: collections, versions, source segments, and rule review/publish summary. Disable lifecycle buttons according to `draft/review/approved/retired`; require a non-empty change reason before PATCH; show errors/warnings and projection counts. Follow `docs/DESIGN_SPEC.md`, preserve 260/64px navigation, use accessible labels and 44px hit areas.

- [ ] **Step 5: Mount navigation and run frontend verification**

Add the `standards` nav item with a standards icon, mount the component from `AdminView.vue`, and ensure switching sections does not disturb document management state.

Run: `cd frontend; node --test tests/standard-management-ui-contract.test.mjs; npm run build`

Expected: PASS and a successful Vue/TypeScript production build.

```bash
git add frontend/src/api/adminStandards.ts frontend/src/components/StandardManagementView.vue frontend/src/components/AdminSidebar.vue frontend/src/views/AdminView.vue frontend/tests/standard-management-ui-contract.test.mjs
git commit -m "feat: add administrator standard management UI"
```

### Task 8: Remove Operator Standard Mutation and Complete Contracts

**Files:**
- Modify: `backend/app/api/operator.py`
- Modify: `frontend/src/components/CaseManageView.vue`
- Modify: `frontend/src/api/operator.ts`
- Modify: `frontend/src/views/OperatorView.vue` only if the removed component contract requires it
- Test: `backend/tests/test_operator_predictive_api.py`, `frontend/tests/standard-management-ui-contract.test.mjs`, `frontend/tests/progression-ui-contract.test.mjs`

**Interfaces:**
- Removes the AI-operator mutation route `/v1/operator/reference-ranges/sync` and its client/action.
- Preserves longitudinal case, progression prediction, report generation, report listing, download, and delete contracts.

- [ ] **Step 1: Write failing cleanup contracts**

```javascript
test('operator cannot mutate standards', async () => {
  const api = await readFile(new URL('../src/api/operator.ts', import.meta.url), 'utf8')
  const caseManage = await readFile(new URL('../src/components/CaseManageView.vue', import.meta.url), 'utf8')
  assert.doesNotMatch(api, /syncReferenceRanges/)
  assert.doesNotMatch(caseManage, /解析为参考范围/)
})
```

- [ ] **Step 2: Run cleanup tests to verify they fail**

Run: `cd frontend; node --test tests/standard-management-ui-contract.test.mjs tests/progression-ui-contract.test.mjs`

Expected: FAIL while the old operator sync action remains.

- [ ] **Step 3: Remove operator mutation and preserve read-only report behavior**

Delete the operator sync route, sync schema/client, and CaseManageView controls. Keep read-only compatibility data only where existing report contracts require it; all new evidence must come from resolver. Assert that longitudinal routes and the single-timepoint removal remain intact.

- [ ] **Step 4: Run backend and frontend contract suites**

Run: `cd backend; pytest tests/test_operator_predictive_api.py tests/test_progression_api.py -q`; then `cd frontend; node --test tests/progression-ui-contract.test.mjs tests/longitudinal-case-sync.test.mjs tests/standard-management-ui-contract.test.mjs; npm run build`.

Expected: PASS with no operator standard mutation path and no regression to longitudinal operator flow.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/operator.py frontend/src/components/CaseManageView.vue frontend/src/api/operator.ts frontend/src/views/OperatorView.vue backend/tests/test_operator_predictive_api.py frontend/tests/progression-ui-contract.test.mjs frontend/tests/standard-management-ui-contract.test.mjs
git commit -m "refactor: remove operator standard mutation path"
```

### Task 9: Full Verification and Migration Dry Run

**Files:**
- Create: `scripts/check_model_artifacts.py`
- Test: `scripts/tests/test_check_model_artifacts.py`
- Modify only test/doc files if verification exposes a contract defect.
- Test: all backend and frontend suites, migration contract tests, and standard fixtures.

**Interfaces:**
- Produces a verified `0009` migration, complete standard lifecycle, resolver-backed report evidence, and no changed longitudinal artifact checksums.

- [ ] **Step 1: Run all backend tests**

Run: `cd backend; pytest -q`

Expected: PASS; if PostgreSQL is unavailable, report the exact skipped integration tests and run all pure/unit/contract tests.

- [ ] **Step 2: Run all frontend tests and build**

Run: `cd frontend; node --test tests/*.test.mjs; npm run build`

Expected: PASS and successful TypeScript/Vite build.

- [ ] **Step 3: Verify Alembic upgrade/downgrade contract**

Run: `cd backend; alembic upgrade head; alembic current; alembic downgrade 0008; alembic upgrade 0009`

Expected: `0009` is the single head, downgrade removes only standard-layer tables/columns, and re-upgrade recreates them without duplicate indexes.

- [ ] **Step 4: Run DOCX fixture smoke checks**

Run: `cd backend; pytest tests/test_standard_parser.py tests/test_standard_validation.py tests/test_standard_resolver.py -q`

Expected: both real document fixtures preserve table counts, source locations, boundary semantics, AD A/T/N/stage structures, and fatty-liver dimension/condition rules.

- [ ] **Step 5: Compare longitudinal artifact checksums**

First add `scripts/check_model_artifacts.py` with a `sha256_manifest(directory: Path, patterns: tuple[str, ...]) -> dict[str, str]` helper and a CLI that scans the configured model directory, prints sorted SHA-256 values for `.joblib` and `.meta.json`, and exits non-zero when a supplied baseline manifest differs. Add `scripts/tests/test_check_model_artifacts.py` covering a matching manifest and a tampered artifact.

Run: `python scripts/check_model_artifacts.py --models-dir backend/app/models --baseline scripts/tests/fixtures/model-artifact-baseline.json`

Expected: existing `.joblib` and `meta.json` checksums and feature-order metadata remain unchanged.

- [ ] **Step 6: Record verification-only fixes if needed**

```bash
git diff --name-only
git commit -am "test: verify versioned standard rules layer"
```
