# 访视录入与模型输入校验实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 AI 操作者的多次访视录入和模型输入校验统一为目录驱动、可追溯、可安全拒绝的生产级访视输入契约。

**Architecture:** 保留 `operator_cases` 聚合病例和单一聚合保存接口；新增目录服务从已审核 standard manifest 生成疾病指标目录，并由统一规范化服务处理别名、单位、数值、上下文和时间线。前端只负责目录驱动的编辑和即时提示，后端负责最终校验、行锁、审计、快照和报告 readiness。

**Tech Stack:** FastAPI、Pydantic v2、SQLAlchemy、Alembic、PostgreSQL JSONB、Vue 3、TypeScript、Pinia、Vitest、pytest、独立 PostgreSQL 集成 harness、浏览器 E2E。

## Global Constraints

- 访视保存范围为 `1–10` 次；报告最低访视数从活动数据清单读取，当前 AD 与脂肪肝均为 `3`，不得在前端或病例 schema 硬编码报告门槛。
- `operator_case_visits.visit_index` 由服务端按日期生成，客户端不得提交或依赖其永久稳定性。
- 创建、聚合修改、导入、快照和报告前复核必须调用同一套指标和时间线规范化服务。
- 前端遵循 `docs/DESIGN_SPEC.md` 的暖杏蓝、`880px` 内容宽度、44px 控件高度、键盘可操作和错误关联规范。
- 不新增疾病或模型，不改变报告算法、训练数据和报告模板，不恢复单访视公开写接口。
- 旧病例、旧报告和旧输入快照只读兼容；不批量修复或重算历史数据。
- 临床参考范围异常是观察状态，不是结构性输入错误；不凭经验设置实验室指标硬上限。
- 日志和新审计不得记录指标值、访视日期、上下文正文、姓名、联系方式或完整请求体。
- 生产数据库不在开发阶段连接、读取或修改；迁移只能在部署窗口执行并先完成备份和只读核查。

## File Change Summary

### Create

- `backend/app/schemas/operator_indicator_catalog.py`：目录 API 输出模型。
- `backend/app/schemas/operator_visit_context.py`：访视上下文输入/输出模型。
- `backend/app/services/operator_indicator_catalog.py`：manifest 加载、哈希校验、模型代码映射、别名和单位解析。
- `backend/alembic/versions/0021_operator_case_visit_context.py`：`visit_context` JSONB 迁移。
- `backend/tests/test_operator_indicator_catalog.py`：目录和映射单元测试。
- `backend/tests/test_operator_visit_context.py`：上下文校验单元测试。
- `backend/tests/test_operator_case_visit_contract.py`：聚合时间线契约测试。

### Modify

- `backend/app/schemas/longitudinal_case.py`：`VisitCreate`/`VisitOut` 增加 `visit_context`。
- `backend/app/services/indicator_validation.py`：改为调用目录解析 canonical code/unit。
- `backend/app/services/operator_case_validation.py`：规范化访视上下文和多错误路径。
- `backend/app/services/longitudinal_case_service.py`：快照、访视排序和旧数据兼容读取上下文。
- `backend/app/services/operator_case_commands.py`、`backend/app/services/operator_case_diff.py`：聚合保存和脱敏审计。
- `backend/app/db/models.py`、`database/schema.sql`、`scripts/check_database_readonly.py`：数据库结构和只读检查。
- `backend/app/api/operator.py`：指标目录 API、错误 issues 和保存/报告接入。
- `frontend/src/api/operator.ts`、`frontend/src/stores/operator.ts`、工作区组件和测试：目录驱动编辑器。
- `frontend/tests/longitudinal-visit-integrity.test.mjs`、`frontend/tests/longitudinal-case-sync.test.mjs`：迁移到新工作区路径或删除旧契约。
- `docs/AI操作者流程核查.md`：同步第 2、3 项真实状态。

---

### Task 1: 建立目录服务和稳定指标映射

**Files:**
- Create: `backend/app/schemas/operator_indicator_catalog.py`
- Create: `backend/app/services/operator_indicator_catalog.py`
- Create: `backend/tests/test_operator_indicator_catalog.py`
- Modify: `backend/app/services/disease_catalog.py`

**Interfaces:**
- Produces `load_operator_indicator_catalog(disease_code: str) -> OperatorIndicatorCatalog`.
- Produces `resolve_indicator(disease_code: str, raw_name: str) -> CatalogIndicator`.
- Produces `normalize_unit(disease_code: str, indicator_code: str, raw_unit: str) -> str`.
- `OperatorIndicatorCatalog` contains `disease_code`, `catalog_version`, and immutable `items`.

- [ ] **Step 1: Write failing catalog tests**

```python
def test_catalog_resolves_chinese_alt_alias_to_model_code():
    catalog = load_operator_indicator_catalog("fatty_liver")
    item = catalog.resolve_indicator("谷丙转氨酶")
    assert item.code == "alt"
    assert item.default_unit == "U/L"

def test_catalog_maps_ad_manifest_names_to_model_keys():
    catalog = load_operator_indicator_catalog("ad")
    assert catalog.resolve_indicator("NfL").code == "plasma_nfl"
    assert catalog.resolve_indicator("Plasma p-tau217").code == "plasma_ptau217"

def test_catalog_rejects_unapproved_manifest(tmp_path):
    with pytest.raises(IndicatorCatalogUnavailableError):
        load_operator_indicator_catalog("fatty_liver", root=tmp_path)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -q backend/tests/test_operator_indicator_catalog.py`
Expected: FAIL because the catalog schema, loader, and mapping functions do not exist.

- [ ] **Step 3: Implement the catalog contract**

Create immutable Pydantic output models and a loader that reads `standard_manifests/{disease}.v1.json`, requires `review_state == "approved"`, computes the manifest SHA-256, merges entries by canonical key, and applies this explicit model mapping:

```python
MODEL_CODE_ALIASES = {
    "ad": {
        "nfl": "plasma_nfl",
        "NfL": "plasma_nfl",
        "NfL/GFAP": "plasma_nfl",
        "p-tau217": "plasma_ptau217",
        "Plasma p-tau217": "plasma_ptau217",
    }
}
```

The loader must raise `IndicatorCatalogUnavailableError` for missing files, invalid JSON, non-approved manifests, duplicate conflicting definitions, or a manifest hash mismatch supplied by the caller. Unit aliases are case/Unicode normalized only; no implicit dimensional conversion is permitted.

- [ ] **Step 4: Run tests and commit**

Run: `pytest -q backend/tests/test_operator_indicator_catalog.py`
Expected: PASS.

```bash
git add backend/app/schemas/operator_indicator_catalog.py backend/app/services/operator_indicator_catalog.py backend/tests/test_operator_indicator_catalog.py backend/app/services/disease_catalog.py
git commit -m "feat: add manifest-driven operator indicator catalog"
```

### Task 2: Extend the backend visit and context validation contract

**Files:**
- Create: `backend/app/schemas/operator_visit_context.py`
- Create: `backend/tests/test_operator_visit_context.py`
- Create: `backend/tests/test_operator_case_visit_contract.py`
- Modify: `backend/app/schemas/longitudinal_case.py`
- Modify: `backend/app/services/indicator_validation.py`
- Modify: `backend/app/services/operator_case_validation.py`

**Interfaces:**
- Produces `VisitContext` with bounded common and disease-specific fields.
- Extends `normalize_operator_timeline(disease_code, visits)` to return canonical indicators and `visit_context`.
- `IndicatorValue.name` remains the serialized canonical code for compatibility.

- [ ] **Step 1: Write failing validation tests**

```python
def test_empty_numeric_input_is_not_normalized_to_zero():
    with pytest.raises(OperatorCaseValidationError, match="value"):
        normalize_operator_timeline("fatty_liver", [{
            "visit_date": "2026-01-01",
            "indicators": [{"name": "ALT", "value": None, "unit": "U/L"}],
        }])

def test_unit_alias_is_stored_as_canonical_unit():
    visits = normalize_operator_timeline("fatty_liver", [{
        "visit_date": "2026-01-01",
        "indicators": [{"name": "谷丙转氨酶", "value": 42, "unit": "u/l"}],
    }])
    assert visits[0].indicators[0]["name"] == "alt"
    assert visits[0].indicators[0]["unit"] == "U/L"

def test_context_bounds_and_duplicate_canonical_indicators_are_rejected():
    with pytest.raises(OperatorCaseValidationError):
        normalize_operator_timeline("ad", [{
            "visit_date": "2026-01-01",
            "indicators": [
                {"name": "MMSE", "value": 20, "unit": "分"},
                {"name": "mmse", "value": 19, "unit": "分"},
            ],
            "visit_context": {"education_years": 31},
        }])
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest -q backend/tests/test_operator_visit_context.py backend/tests/test_operator_case_visit_contract.py`
Expected: FAIL because `visit_context` and catalog-backed normalization are not defined.

- [ ] **Step 3: Implement schemas and normalization**

Add `VisitContext` fields with exact limits: `source_type` in `lab|imaging|assessment|clinical|other`, facility/device/method/specimen strings bounded to 200/100 characters, treatment/diagnosis changes bounded to 2000, `education_years` in `0..30`, and optional AD scale fields. Use `extra="forbid"`. Update `IndicatorValue.value` to accept `float | None` at the browser boundary but reject `None` in backend normalization with `field=visits.{i}.indicators.{j}.value`.

For each indicator, call `resolve_indicator()` then `normalize_unit()`, reject aliases that collide after canonicalization, preserve `visit_context` as a JSON-serializable dict, sort visits by date, and assign `visit_index` from 1. Return all validation failures through `OperatorCaseValidationError(code, message, field)`.

- [ ] **Step 4: Run tests and commit**

Run: `pytest -q backend/tests/test_indicator_validation.py backend/tests/test_operator_visit_context.py backend/tests/test_operator_case_visit_contract.py backend/tests/test_operator_case_validation.py`
Expected: PASS.

```bash
git add backend/app/schemas backend/app/services/indicator_validation.py backend/app/services/operator_case_validation.py backend/tests/test_operator_visit_context.py backend/tests/test_operator_case_visit_contract.py
git commit -m "feat: normalize operator visit indicators and context"
```

### Task 3: Add the additive database migration and structural checks

**Files:**
- Create: `backend/alembic/versions/0021_operator_case_visit_context.py`
- Modify: `backend/app/db/models.py`
- Modify: `database/schema.sql`
- Modify: `scripts/check_database_readonly.py`
- Modify: `backend/tests/test_alembic_contracts.py`
- Modify: `backend/tests/test_database_baseline.py`

**Interfaces:**
- `OperatorCaseVisit.visit_context` is non-null JSONB with `{}` server default.
- Migration `0021` has down revision `0020` and is additive.

- [ ] **Step 1: Write migration contract tests**

```python
def test_visit_context_column_is_json_object_with_safe_default():
    column = OperatorCaseVisit.__table__.columns["visit_context"]
    assert column.nullable is False
    assert column.server_default is not None

def test_0021_is_after_workspace_head_and_checks_json_object():
    source = Path("backend/alembic/versions/0021_operator_case_visit_context.py").read_text()
    assert 'down_revision: Union[str, Sequence[str], None] = "0020"' in source
    assert "jsonb_typeof(visit_context) = 'object'" in source
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest -q backend/tests/test_alembic_contracts.py backend/tests/test_database_baseline.py`
Expected: FAIL because the column and migration do not exist.

- [ ] **Step 3: Implement migration and structural definitions**

Create the migration with `sa.Column("visit_context", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False)`, add `ck_operator_case_visits_visit_context_object`, and remove both in downgrade. Add the same column/default/check to ORM and `database/schema.sql`; extend the read-only checker to require the column and report malformed JSON objects without rewriting rows.

- [ ] **Step 4: Run tests and commit**

Run: `pytest -q backend/tests/test_alembic_contracts.py backend/tests/test_database_baseline.py backend/tests/test_operator_case_workspace_schema.py`
Expected: PASS.

```bash
git add backend/alembic/versions/0021_operator_case_visit_context.py backend/app/db/models.py database/schema.sql scripts/check_database_readonly.py backend/tests/test_alembic_contracts.py backend/tests/test_database_baseline.py
git commit -m "feat: persist structured operator visit context"
```

### Task 4: Integrate canonical visits with aggregate commands, snapshots, and redacted audit

**Files:**
- Modify: `backend/app/services/operator_case_commands.py`
- Modify: `backend/app/services/operator_case_diff.py`
- Modify: `backend/app/services/longitudinal_case_service.py`
- Modify: `backend/app/services/report_integrity.py`
- Modify: `backend/tests/test_operator_case_commands.py`
- Modify: `backend/tests/test_longitudinal_case_service.py`
- Modify: `backend/tests/test_anonymous_case_privacy.py`

**Interfaces:**
- `replace_case_visits_in_session()` writes canonical indicators and `visit_context` atomically.
- `build_input_snapshot()` includes canonical `visit_context` while preserving old snapshot reads.
- Audit timeline changes contain field names/counts/hash, never medical values or visit dates.

- [ ] **Step 1: Write failing integration tests**

```python
def test_aggregate_save_persists_canonical_indicator_and_context(db, active_case):
    saved = save_operator_case_command(db, 7, active_case.id, payload_with_alias_and_context())
    assert saved.visits[0].indicators == [{"name": "alt", "value": 42.0, "unit": "U/L"}]
    assert saved.visits[0].visit_context["source_type"] == "lab"

def test_audit_diff_does_not_store_visit_values_or_dates():
    changes = build_case_diff(case, submitted_profile, normalized_visits)
    encoded = json.dumps(changes, ensure_ascii=False)
    assert "42" not in encoded
    assert "2026-01-01" not in encoded
    assert "indicators" in encoded
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest -q backend/tests/test_operator_case_commands.py backend/tests/test_longitudinal_case_service.py`
Expected: FAIL because context is not persisted and audit diff still contains before/after values.

- [ ] **Step 3: Implement atomic integration**

Pass the normalized timeline from `save_operator_case_command()` into `replace_case_visits_in_session()`. Add `visit_context` to ORM construction, `_ordered_visits()`, and `build_input_snapshot()`. Replace timeline audit payloads with `{"added_count", "removed_count", "updated_fields", "timeline_sha256"}`; calculate the hash from canonical data without including dates or values in the stored audit JSON. Keep report snapshots complete and include the catalog version.

- [ ] **Step 4: Run tests and commit**

Run: `pytest -q backend/tests/test_operator_case_commands.py backend/tests/test_longitudinal_case_service.py backend/tests/test_report_integrity.py backend/tests/test_anonymous_case_privacy.py`
Expected: PASS.

```bash
git add backend/app/services/operator_case_commands.py backend/app/services/operator_case_diff.py backend/app/services/longitudinal_case_service.py backend/app/services/report_integrity.py backend/tests/test_operator_case_commands.py backend/tests/test_longitudinal_case_service.py backend/tests/test_anonymous_case_privacy.py
git commit -m "feat: persist canonical visits and redact timeline audit"
```

### Task 5: Expose the catalog and structured validation errors through the operator API

**Files:**
- Modify: `backend/app/api/operator.py`
- Modify: `backend/app/schemas/operator_case_workspace.py`
- Modify: `backend/app/schemas/longitudinal_case.py`
- Create: `backend/tests/test_operator_indicator_catalog_api.py`
- Modify: `backend/tests/test_operator_case_workspace_api.py`

**Interfaces:**
- `GET /v1/operator/diseases/{disease_code}/indicators` returns `OperatorIndicatorCatalogOut`.
- Existing create/update endpoints keep their paths and return canonical `OperatorCaseOut`.
- Error detail remains `{code, message, field}` and may include `issues: [{code, message, field}]`.

- [ ] **Step 1: Write failing API tests**

```python
def test_operator_can_read_enabled_disease_indicator_catalog(client, operator_token):
    response = client.get("/v1/operator/diseases/fatty_liver/indicators", headers=operator_token)
    assert response.status_code == 200
    assert response.json()["items"][0]["code"] == "alt"

def test_invalid_visit_returns_stable_field_path(client, operator_token, case_payload):
    case_payload["visits"][0]["indicators"][0]["value"] = None
    response = client.post("/v1/operator/longitudinal-cases", json=case_payload, headers=operator_token)
    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "visits.0.indicators.0.value"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest -q backend/tests/test_operator_indicator_catalog_api.py backend/tests/test_operator_case_workspace_api.py`
Expected: FAIL because the catalog route and structured error mapping are absent.

- [ ] **Step 3: Implement API route and error mapping**

Add the operator-protected route after the disease routes. Verify `disease_code` is enabled and registered in `DISEASE_CAPABILITIES`; map catalog load failures to HTTP 503 `indicator_catalog_unavailable`. Update `_longitudinal_error()` to preserve `field` and include `issues` when supplied. Do not expose `patient_label`, internal IDs, raw aliases, or database errors.

- [ ] **Step 4: Run tests and commit**

Run: `pytest -q backend/tests/test_operator_indicator_catalog_api.py backend/tests/test_operator_case_workspace_api.py backend/tests/test_operator_permissions.py`
Expected: PASS.

```bash
git add backend/app/api/operator.py backend/app/schemas/operator_case_workspace.py backend/app/schemas/longitudinal_case.py backend/tests/test_operator_indicator_catalog_api.py backend/tests/test_operator_case_workspace_api.py
git commit -m "feat: expose operator indicator catalog API"
```

### Task 6: Implement the catalog-driven Vue visit editor

**Files:**
- Modify: `frontend/src/api/operator.ts`
- Modify: `frontend/src/stores/operator.ts`
- Modify: `frontend/src/components/operator-case/OperatorVisitTimelineEditor.vue`
- Modify: `frontend/src/components/operator-case/OperatorCaseWorkspace.vue`
- Modify: `frontend/src/views/OperatorView.vue`
- Modify: `frontend/src/components/operator-case/__tests__/OperatorCaseWorkspace.spec.ts`
- Modify: `frontend/src/stores/__tests__/operator-case-workspace.spec.ts`
- Create: `frontend/src/components/operator-case/__tests__/OperatorVisitTimelineEditor.spec.ts`

**Interfaces:**
- `listOperatorIndicatorCatalog(code: string): Promise<OperatorIndicatorCatalog>`.
- Timeline editor props include `indicatorCatalog` and `validationIssues`.
- Empty numeric input emits `null`, never `0`.

- [ ] **Step 1: Write failing component tests**

```ts
it('adds and removes indicator rows without converting blank values to zero', async () => {
  const wrapper = mount(OperatorVisitTimelineEditor, { props: { visits: [visit()], indicatorCatalog: fattyCatalog } })
  await wrapper.find('[aria-label="添加指标"]').trigger('click')
  expect(wrapper.findAll('.timeline__indicator')).toHaveLength(2)
  await wrapper.findAll('input[type="number"]')[0].setValue('')
  expect(wrapper.emitted('update')?.at(-1)?.[0][0].indicators[0].value).toBeNull()
})

it('shows disease-specific labels and default units', () => {
  const wrapper = mount(OperatorVisitTimelineEditor, { props: { visits: [visit()], indicatorCatalog: fattyCatalog } })
  expect(wrapper.text()).toContain('谷丙转氨酶')
  expect(wrapper.find('select[aria-label="指标单位"]').element.value).toBe('U/L')
})
```

- [ ] **Step 2: Run tests to verify failure**

Run: `npm run test:unit -- --run frontend/src/components/operator-case/__tests__/OperatorVisitTimelineEditor.spec.ts`
Expected: FAIL because the editor has no indicator catalog prop, add/remove controls, or null-preserving numeric handler.

- [ ] **Step 3: Implement the editor and store wiring**

Add `OperatorIndicatorCatalog` types and `listOperatorIndicatorCatalog()`. Fetch the catalog when a selected disease changes, keep it in Pinia, and pass it to the workspace. In the editor, render a `<select>` for indicator code and unit, add `aria-label="添加指标"`/`aria-label="删除指标"` buttons, filter already-selected codes, and use:

```ts
function parseNumber(value: string): number | null {
  const trimmed = value.trim()
  return trimmed === '' ? null : Number(trimmed)
}
```

Keep 1–10 visit guards, last-visit deletion protection, 44px controls, existing CSS variables, and a compact expandable context panel. Existing unknown indicators render a warning and remain editable as legacy data; they are never silently removed.

- [ ] **Step 4: Run tests and commit**

Run: `npm run test:unit -- --run` and `npm run build`
Expected: all Vitest tests PASS and Vite production build succeeds.

```bash
git add frontend/src/api/operator.ts frontend/src/stores/operator.ts frontend/src/components/operator-case frontend/src/views/OperatorView.vue
git commit -m "feat: add catalog-driven visit editor"
```

### Task 7: Add field-level errors, readiness display, and migrate stale UI contracts

**Files:**
- Modify: `frontend/src/components/operator-case/OperatorCaseWorkspace.vue`
- Modify: `frontend/src/components/operator-case/OperatorCaseActionBar.vue`
- Modify: `frontend/src/views/OperatorView.vue`
- Modify: `frontend/src/api/request.ts`
- Modify or delete: `frontend/tests/longitudinal-visit-integrity.test.mjs`
- Modify or delete: `frontend/tests/longitudinal-case-sync.test.mjs`
- Create: `frontend/tests/longitudinal-visit-input-contract.test.mjs`

**Interfaces:**
- Backend validation errors map to `Record<string, string>` keyed by stable field paths.
- Save loading remains true until aggregate save and readiness refresh both settle.
- Report readiness text uses server `minimum_visits` and does not hardcode `3`.

- [ ] **Step 1: Write failing UI contract tests**

```js
const editor = fs.readFileSync(new URL('../src/components/operator-case/OperatorVisitTimelineEditor.vue', import.meta.url), 'utf8')
if (!editor.includes('aria-label="添加指标"')) throw new Error('indicator add action missing')
if (!editor.includes('value === \'\' ? null')) throw new Error('blank numeric input is not null-safe')
const actionBar = fs.readFileSync(new URL('../src/components/operator-case/OperatorCaseActionBar.vue', import.meta.url), 'utf8')
if (actionBar.includes('至少需要 3')) throw new Error('report gate is hardcoded in UI')
```

- [ ] **Step 2: Run stale contracts to verify failure**

Run: `node frontend/tests/longitudinal-visit-integrity.test.mjs; node frontend/tests/longitudinal-case-sync.test.mjs`
Expected: the old tests fail because they reference the removed `LongitudinalCaseEditor.vue`; the new contract test fails until the new editor assertions are present.

- [ ] **Step 3: Implement error mapping and contract migration**

Normalize Axios errors into `{code, message, field, issues}` without exposing raw responses. Render field errors beside the relevant date, indicator, unit, value, and context input. Replace old tests with assertions against `OperatorVisitTimelineEditor.vue`, `OperatorCaseWorkspace.vue`, and `OperatorCaseActionBar.vue`; remove only assertions that depended on deleted components. Keep the action bar disabled while saving or while server readiness is unavailable.

- [ ] **Step 4: Run tests and commit**

Run: `node frontend/tests/longitudinal-visit-input-contract.test.mjs; npm run test:unit -- --run; npm run build`
Expected: all contract/unit tests PASS and production build succeeds.

```bash
git add frontend/src/components/operator-case frontend/src/views/OperatorView.vue frontend/src/api/request.ts frontend/tests
git commit -m "test: migrate operator visit input UI contracts"
```

### Task 8: Complete integration, E2E, documentation, and release verification

**Files:**
- Modify: `backend/tests/integration/test_operator_case_workspace_api.py`
- Modify: `backend/tests/e2e/test_operator_case_workspace.py`
- Modify: `frontend/tests/longitudinal-case-sync.test.mjs`
- Modify: `docs/AI操作者流程核查.md`
- Modify: `database/README.md` if migration instructions need the new head

**Interfaces:**
- Independent PostgreSQL test database applies Alembic `0021` and exercises both diseases.
- Browser harness verifies the same aggregate API and catalog-driven UI.

- [ ] **Step 1: Add failing dual-disease integration scenarios**

```python
@pytest.mark.parametrize("disease_id,code,indicator,unit", [
    (1, "fatty_liver", "ALT", "U/L"),
    (2, "ad", "MMSE", "分"),
])
def test_create_one_visit_then_append_to_three_and_read_canonical_context(client, disease_id, code, unit):
    created = create_case(client, disease_id, code, unit)
    assert len(created["visits"]) == 1
    payload = replace_with_three_visits(created, code, unit)
    saved = save_case(client, created["id"], payload)
    assert len(saved["visits"]) == 3
    assert saved["visits"][0]["visit_index"] == 1
```

- [ ] **Step 2: Run integration tests before implementation completion**

Run: `pytest -q backend/tests/integration/test_operator_case_workspace_api.py backend/tests/e2e/test_operator_case_workspace.py`
Expected: FAIL for the new catalog/context assertions until all previous tasks are integrated.

- [ ] **Step 3: Implement E2E and documentation updates**

Run the independent PostgreSQL harness, apply `alembic upgrade head`, create AD and fatty-liver cases, add visits out of order, verify date sorting and canonical units, attempt invalid cross-disease indicators, and verify report readiness transitions from 1 to 3 visits. Update the documentation’s second and third sections: remove the obsolete “0 visits can be saved” and “gender optional” claims, record the catalog/unit/context implementation, and keep production migration status separate from repository status.

- [ ] **Step 4: Run complete verification**

Run:

```bash
pytest -q backend/tests
pytest -q scripts/tests
Set-Location frontend
npm run test:unit -- --run
npm run build
Set-Location ..
python scripts/check_database_readonly.py --help
```

Expected: backend and script suites pass (with only explicitly documented skips), all frontend tests pass, build succeeds, and the read-only checker exposes the `visit_context` requirement. Run the real PostgreSQL and browser harnesses in their explicitly provisioned environments; do not substitute SQLite or a production database.

- [ ] **Step 5: Commit the verified documentation and release checklist**

```bash
git add backend/tests/integration backend/tests/e2e frontend/tests docs/AI操作者流程核查.md database/README.md
git commit -m "docs: close operator visit input contract"
```

## Self-Review Checklist

- [ ] Every spec section maps to at least one task: catalog (1), validation (2), database (3), snapshot/audit (4), API (5), frontend (6–7), testing and rollout (8).
- [ ] No task introduces a second visit write path or changes report/model algorithms.
- [ ] Canonical names and units are defined once and consumed consistently by backend, frontend, snapshots, and model input.
- [ ] `visit_context` is additive and old rows/snapshots remain readable.
- [ ] Error paths, audit redaction, row locking, idempotency, and readiness behavior remain explicit.
- [ ] The plan contains no placeholders or unspecified “handle edge cases” steps.
