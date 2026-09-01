# AI Operator Case Age Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a production-compatible integer age field to AI operator longitudinal cases and carry it from data entry through the persisted report snapshot into model inference.

**Architecture:** Alembic revision `0013` adds a nullable database column for legacy compatibility while application schemas require age for new cases. The report endpoint rejects legacy cases without age before creating a report row, and both inference paths consume the snapshot age without treating `0` as missing. The existing UI gains one bounded integer input and submits the value through the current API/store flow.

**Tech Stack:** PostgreSQL, Alembic, SQLAlchemy, FastAPI, Pydantic v2, pytest, Vue 3, TypeScript, Element Plus, Node contract tests

## Global Constraints

- The valid age range is exactly `0–120` in the database, backend, frontend, and existing training data Schema.
- `operator_cases.age` remains nullable at the database and response boundary so existing production rows remain readable.
- `OperatorCaseCreate.age` is required; `OperatorCaseUpdate.age` may be omitted but explicit `null` is rejected.
- A legacy case with `age IS NULL` cannot generate a new report, and the rejection occurs before any `AIReport` row is inserted.
- No migration backfill, guessed age, birth date, model retraining, model replacement, or server operation is in scope.
- `database/schema.sql` is a clean-install reference snapshot; existing databases are upgraded only with `alembic upgrade head`.
- Frontend work must follow `docs/DESIGN_SPEC.md` and preserve the existing operator-page visual structure.
- Preserve unrelated working-tree changes and stage only the files intended for each task.

---

## File Map

- Create `backend/alembic/versions/0013_operator_case_age.py`: production schema upgrade and downgrade.
- Modify `backend/app/db/models.py`: ORM age column and named check constraint.
- Modify `database/schema.sql`: clean-install snapshot for age and its range constraint.
- Modify `scripts/check_database_readonly.py`: require the age column and verify its PostgreSQL type.
- Modify `backend/app/schemas/longitudinal_case.py`: create, partial-update, and output contracts.
- Modify `backend/app/services/longitudinal_case_service.py`: persist age and include it in report snapshots.
- Modify `backend/app/api/operator.py`: legacy-case report-generation gate.
- Modify `backend/app/services/longitudinal_features.py`: supply age to fixed-window inference.
- Modify `backend/app/services/longitudinal_prediction.py`: preserve age `0` while retaining `patient_age` compatibility.
- Modify `frontend/src/api/operator.ts`: age types and create payload.
- Modify `frontend/src/stores/operator.ts`: age in the save contract.
- Modify `frontend/src/components/LongitudinalCaseEditor.vue`: bounded integer input, refill, and client validation.
- Modify `frontend/src/views/OperatorView.vue`: include age in the saved payload.
- Create `frontend/tests/longitudinal-age.test.mjs`: frontend age-flow contract.
- Modify the backend contract tests listed in each task.
- Modify `docs/AI操作者流程核查.md`: mark only this appendix issue complete after verification.

---

### Task 1: Database Migration and Four-Way Schema Contract

**Files:**
- Create: `backend/alembic/versions/0013_operator_case_age.py`
- Modify: `backend/app/db/models.py`
- Modify: `database/schema.sql`
- Modify: `scripts/check_database_readonly.py`
- Test: `backend/tests/test_alembic_contracts.py`
- Test: `backend/tests/test_longitudinal_schema_contracts.py`
- Test: `backend/tests/test_schema_contracts.py`
- Test: `backend/tests/test_database_baseline.py`

**Interfaces:**
- Consumes: Alembic head `0012` and existing `operator_cases` rows.
- Produces: nullable `OperatorCase.age: int | None`, constraint `ck_operator_cases_age_range`, and read-only type reporting through `column_type_mismatches`.

- [ ] **Step 1: Write failing migration and schema contract tests**

Add tests that load the new revision, inspect the ORM constraint, inspect the clean-install SQL, and make the read-only checker reject a wrong type:

```python
def test_operator_case_age_migration_follows_0012():
    migration = _load_revision("0013_operator_case_age.py", "migration_0013")
    assert migration.revision == "0013"
    assert migration.down_revision == "0012"


def test_operator_case_age_migration_is_nullable_and_bounded():
    migration = _load_revision("0013_operator_case_age.py", "migration_0013_age")
    migration_op = MagicMock()
    with patch.object(migration, "op", migration_op):
        migration.upgrade()
    added = migration_op.add_column.call_args.args
    assert added[0] == "operator_cases"
    assert added[1].name == "age"
    assert added[1].nullable is True
    migration_op.create_check_constraint.assert_called_once_with(
        "ck_operator_cases_age_range",
        "operator_cases",
        "age IS NULL OR age BETWEEN 0 AND 120",
    )
```

```python
def test_operator_case_age_matches_database_contract():
    from app.db.models import OperatorCase

    age = OperatorCase.__table__.columns["age"]
    assert str(age.type) == "INTEGER"
    assert age.nullable is True
    assert any(
        constraint.name == "ck_operator_cases_age_range"
        for constraint in OperatorCase.__table__.constraints
    )
```

Extend `test_database_baseline.py` with a fake row whose `operator_cases.age` type is `character varying` and assert:

```python
assert report["column_type_mismatches"] == [
    {
        "table_name": "operator_cases",
        "column_name": "age",
        "expected": "integer",
        "actual": "character varying",
    }
]
assert report["status"] == "FAIL"
```

- [ ] **Step 2: Run the database tests and verify the intended failures**

Run from `backend/`:

```powershell
python -m pytest tests/test_alembic_contracts.py tests/test_longitudinal_schema_contracts.py tests/test_schema_contracts.py tests/test_database_baseline.py -q
```

Expected: failures report missing `0013_operator_case_age.py`, missing `OperatorCase.age`, missing SQL age declaration, and missing type mismatch reporting.

- [ ] **Step 3: Add Alembic revision `0013`**

Create the revision with no data update:

```python
"""add age to AI operator longitudinal cases"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("operator_cases", sa.Column("age", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_operator_cases_age_range",
        "operator_cases",
        "age IS NULL OR age BETWEEN 0 AND 120",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_operator_cases_age_range", "operator_cases", type_="check"
    )
    op.drop_column("operator_cases", "age")
```

- [ ] **Step 4: Align ORM and clean-install SQL**

Add the named ORM constraint and nullable column:

```python
__table_args__ = (
    CheckConstraint(
        "age IS NULL OR age BETWEEN 0 AND 120",
        name="ck_operator_cases_age_range",
    ),
    Index("ix_operator_cases_user_id", "user_id"),
    Index("ix_operator_cases_disease_id", "disease_id"),
)

age = Column(Integer, nullable=True)
```

Add the matching clean-install column directly after `sex`, and place the table constraint after the timestamp columns:

```sql
    sex VARCHAR(10),
    age INTEGER,
    baseline_stage VARCHAR(100),
    notes TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT ck_operator_cases_age_range
        CHECK (age IS NULL OR age BETWEEN 0 AND 120)
```

- [ ] **Step 5: Extend the read-only database checker without adding mutating SQL**

Add age to `REQUIRED_COLUMNS` and define the narrow type contract:

```python
REQUIRED_COLUMN_TYPES = {
    ("operator_cases", "age"): "integer",
}
```

Select `data_type` from `information_schema.columns`, collect actual types, and report mismatches:

```python
actual_types = {
    (row["table_name"], row["column_name"]): row["data_type"]
    for row in column_rows
}
column_type_mismatches = [
    {
        "table_name": table_name,
        "column_name": column_name,
        "expected": expected,
        "actual": actual_types.get((table_name, column_name)),
    }
    for (table_name, column_name), expected in REQUIRED_COLUMN_TYPES.items()
    if actual_types.get((table_name, column_name)) != expected
]
```

Include `not column_type_mismatches` in PASS calculation and include the list in the returned report. Update `_FakeConnection` rows in `test_database_baseline.py` to provide `data_type`, using `"integer"` for `operator_cases.age`.

- [ ] **Step 6: Run database contracts and Alembic head inspection**

```powershell
python -m pytest tests/test_alembic_contracts.py tests/test_longitudinal_schema_contracts.py tests/test_schema_contracts.py tests/test_database_baseline.py -q
python -m alembic heads
```

Expected: all selected tests pass and Alembic prints one head, `0013 (head)`.

- [ ] **Step 7: Commit the database boundary**

Stage only the Task 1 paths after reviewing their complete diffs. If a path contains pre-existing approved alignment changes, keep those changes and mention them in the commit body rather than reverting them.

```powershell
git commit -m "feat: add operator case age migration"
```

---

### Task 2: Backend Case Contracts, Persistence, and Snapshot

**Files:**
- Modify: `backend/app/schemas/longitudinal_case.py`
- Modify: `backend/app/services/longitudinal_case_service.py`
- Test: `backend/tests/test_longitudinal_case_service.py`

**Interfaces:**
- Consumes: `OperatorCase.age` from Task 1.
- Produces: `OperatorCaseCreate.age: int`, omit-or-integer `OperatorCaseUpdate.age`, nullable `OperatorCaseOut.age`, and snapshot key `age`.

- [ ] **Step 1: Write failing Schema and service tests**

Update `_case()` to accept an age and add boundary tests:

```python
def test_case_age_is_required_and_bounded():
    from app.schemas.longitudinal_case import OperatorCaseCreate

    assert OperatorCaseCreate(disease_id=11, patient_label="case-0", age=0).age == 0
    assert OperatorCaseCreate(disease_id=11, patient_label="case-120", age=120).age == 120
    for age in (-1, 121, 1.5, None):
        with pytest.raises(ValidationError):
            OperatorCaseCreate(disease_id=11, patient_label="case-invalid", age=age)


def test_case_update_age_may_be_omitted_but_not_cleared():
    from app.schemas.longitudinal_case import OperatorCaseUpdate

    assert OperatorCaseUpdate(patient_label="renamed").model_dump(exclude_unset=True) == {
        "patient_label": "renamed"
    }
    assert OperatorCaseUpdate(age=0).age == 0
    with pytest.raises(ValidationError):
        OperatorCaseUpdate(age=None)
```

Update every pre-existing `OperatorCaseCreate(...)` construction in this test file to pass a valid fixture age such as `age=65`. This includes the label normalization, invalid-sex, canonical-stage, and legacy-stage cases; their assertions remain unchanged.

Extend the snapshot test with `case = _case(age=0)` and:

```python
assert snapshot["age"] == 0
```

Add a create-service test that passes `age=67` and asserts the object sent to `db.add()` has `case.age == 67`.

- [ ] **Step 2: Run the focused test and verify failure**

```powershell
python -m pytest tests/test_longitudinal_case_service.py -q
```

Expected: failures show that create rejects no age contract, update accepts explicit null, persistence omits age, and snapshot lacks `age`.

- [ ] **Step 3: Implement Pydantic contracts**

Import `model_validator` and add:

```python
class OperatorCaseCreate(BaseModel):
    disease_id: int = Field(..., gt=0)
    patient_label: str = Field(..., min_length=1, max_length=100)
    age: int = Field(..., ge=0, le=120)


class OperatorCaseUpdate(BaseModel):
    age: int | None = Field(None, ge=0, le=120)

    @model_validator(mode="after")
    def reject_explicit_null_age(self):
        if "age" in self.model_fields_set and self.age is None:
            raise ValueError("年龄不能置空")
        return self


class OperatorCaseOut(BaseModel):
    age: int | None = None
```

Keep each declaration with the surrounding existing fields; do not duplicate the classes.

- [ ] **Step 4: Persist and snapshot age**

Pass the required age into the ORM constructor:

```python
case = OperatorCase(
    user_id=user_id,
    disease_id=payload.disease_id,
    patient_label=payload.patient_label,
    age=payload.age,
    sex=payload.sex,
    baseline_stage=payload.baseline_stage,
    notes=payload.notes,
    status="active",
)
```

Add the snapshot value next to sex:

```python
"age": getattr(case, "age", None),
"sex": getattr(case, "sex", None),
```

No custom update branch is needed; `model_dump(exclude_unset=True)` already preserves omitted age and applies a supplied integer.

- [ ] **Step 5: Run backend case tests**

```powershell
python -m pytest tests/test_longitudinal_case_service.py tests/test_longitudinal_schema_contracts.py -q
```

Expected: all selected tests pass, including ages `0` and `120` and snapshot age `0`.

- [ ] **Step 6: Commit the backend case contract**

```powershell
git commit -m "feat: persist operator case age"
```

---

### Task 3: Report Generation Gate for Legacy Cases

**Files:**
- Modify: `backend/app/api/operator.py`
- Test: `backend/tests/test_longitudinal_case_service.py`

**Interfaces:**
- Consumes: nullable persisted age and `create_longitudinal_report(...)`.
- Produces: HTTP `422` with detail `请先补录患者年龄（0–120岁）` before evidence lookup, report insertion, or SSE startup.

- [ ] **Step 1: Write the failing endpoint-unit test**

Add imports for `asyncio`, `HTTPException`, and `patch`, then add:

```python
def test_report_generation_rejects_legacy_case_without_age_before_insert():
    from app.api.operator import create_longitudinal_report

    db = MagicMock()
    legacy_case = SimpleNamespace(age=None)
    with patch("app.api.operator.get_operator_case", return_value=legacy_case), patch(
        "app.api.operator.get_progression_adapter",
        side_effect=AssertionError("adapter must not load"),
    ):
        with pytest.raises(HTTPException) as error:
            asyncio.run(
                create_longitudinal_report(
                    case_id=3,
                    request=None,
                    db=db,
                    current_user=SimpleNamespace(id=7),
                )
            )

    assert error.value.status_code == 422
    assert error.value.detail == "请先补录患者年龄（0–120岁）"
    db.add.assert_not_called()
    db.commit.assert_not_called()
```

- [ ] **Step 2: Run the test and verify it reaches later code**

```powershell
python -m pytest tests/test_longitudinal_case_service.py::test_report_generation_rejects_legacy_case_without_age_before_insert -q
```

Expected: FAIL because the current endpoint proceeds to `get_progression_adapter`.

- [ ] **Step 3: Add the early report gate**

Immediately after the owned case lookup succeeds, add:

```python
if case.age is None:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="请先补录患者年龄（0–120岁）",
    )
```

Do not place this after the report constructor or database commit.

- [ ] **Step 4: Run endpoint and report regression tests**

```powershell
python -m pytest tests/test_longitudinal_case_service.py tests/test_operator_catalog_and_reports_api.py tests/test_longitudinal_report_acceptance.py -q
```

Expected: all selected tests pass and the missing-age test observes no database write.

- [ ] **Step 5: Commit the report gate**

```powershell
git commit -m "fix: require age before longitudinal reports"
```

---

### Task 4: Fixed-Window and Model-Suite Age Propagation

**Files:**
- Modify: `backend/app/services/longitudinal_features.py`
- Modify: `backend/app/services/longitudinal_prediction.py`
- Test: `backend/tests/test_longitudinal_features.py`
- Test: `backend/tests/test_longitudinal_prediction_contract.py`

**Interfaces:**
- Consumes: snapshot `case["age"]` from Task 2.
- Produces: model feature `age` equal to the submitted integer, including `0`; uses `patient_age` only when `age is None`.

- [ ] **Step 1: Write failing age propagation tests**

Keep the existing “never guess age from text” test and add:

```python
def test_online_age_uses_the_explicit_case_value():
    from app.services.longitudinal_features import build_fixed_window_inference_features

    frame = build_fixed_window_inference_features(
        {"age": 70, "sex": "male"},
        [_visit("2024-01-01", 10), _visit("2024-06-01", 20), _visit("2024-12-31", 30)],
        _inference_metadata(required_features=["age", "visit_count"]),
    )
    assert frame.loc[0, "age"] == 70
```

In `test_longitudinal_prediction_contract.py`, add:

```python
def test_suite_frame_preserves_zero_age_before_legacy_fallback():
    from types import SimpleNamespace
    from app.services.longitudinal_prediction import _suite_frame

    metadata = SimpleNamespace(
        feature_contract=SimpleNamespace(feature_names=["age"])
    )
    frame = _suite_frame({"age": 0, "patient_age": 77}, [], metadata)
    assert frame.loc[0, "age"] == 0
```

- [ ] **Step 2: Run the model-feature tests and verify failure**

```powershell
python -m pytest tests/test_longitudinal_features.py::test_online_age_uses_the_explicit_case_value tests/test_longitudinal_prediction_contract.py::test_suite_frame_preserves_zero_age_before_legacy_fallback -q
```

Expected: the fixed-window value is missing and the suite fallback returns `77` instead of `0`.

- [ ] **Step 3: Read explicit age in both inference paths**

In `build_fixed_window_inference_features`, replace the hard-coded missing value:

```python
values: dict[str, Any] = {
    "age": case.get("age"),
    "sex": case.get("sex"),
```

In `_suite_frame`, use a `None` check rather than boolean fallback:

```python
age = case.get("age")
fixed = {
    "age": case.get("patient_age") if age is None else age,
    "sex": case.get("sex"),
```

- [ ] **Step 4: Run feature, prediction, and report regressions**

```powershell
python -m pytest tests/test_longitudinal_features.py tests/test_longitudinal_prediction_contract.py tests/test_longitudinal_end_to_end.py tests/test_longitudinal_report_generator.py -q
```

Expected: all selected tests pass; missing age is still never guessed from labels or notes, while explicit age reaches both inference frames.

- [ ] **Step 5: Commit model input propagation**

```powershell
git commit -m "fix: pass case age into longitudinal models"
```

---

### Task 5: Frontend Age Entry and Save Flow

**Files:**
- Modify: `frontend/src/api/operator.ts`
- Modify: `frontend/src/stores/operator.ts`
- Modify: `frontend/src/components/LongitudinalCaseEditor.vue`
- Modify: `frontend/src/views/OperatorView.vue`
- Create: `frontend/tests/longitudinal-age.test.mjs`

**Interfaces:**
- Consumes: backend create/update/output age contracts.
- Produces: `LongitudinalCase.age: number | null`, required save input age, and an Element Plus integer control bounded to `0–120`.

- [ ] **Step 1: Write the failing static frontend contract**

Create `frontend/tests/longitudinal-age.test.mjs`:

```javascript
import fs from 'node:fs'

const api = fs.readFileSync(new URL('../src/api/operator.ts', import.meta.url), 'utf8')
const store = fs.readFileSync(new URL('../src/stores/operator.ts', import.meta.url), 'utf8')
const view = fs.readFileSync(new URL('../src/views/OperatorView.vue', import.meta.url), 'utf8')
const editor = fs.readFileSync(new URL('../src/components/LongitudinalCaseEditor.vue', import.meta.url), 'utf8')

if (!/age:\s*number \| null/.test(api)) throw new Error('case response age is missing')
if (!/createLongitudinalCase\([\s\S]*age:\s*number/.test(api)) throw new Error('create payload does not require age')
if (!/saveLongitudinalCase\([\s\S]*age:\s*number/.test(store)) throw new Error('store save contract does not require age')
if (!view.includes('age: draft.age')) throw new Error('view drops age from save payload')
if (!editor.includes('v-model="draft.age"')) throw new Error('age input is missing')
if (!editor.includes(':min="0"') || !editor.includes(':max="120"')) throw new Error('age bounds are missing')
if (!editor.includes('Number.isInteger(draft.age)')) throw new Error('integer age validation is missing')
if (!editor.includes('value?.age ?? null')) throw new Error('zero age is not preserved during refill')

console.log('longitudinal age contract passed')
```

- [ ] **Step 2: Run the contract and verify failure**

Run from `frontend/`:

```powershell
node tests/longitudinal-age.test.mjs
```

Expected: FAIL with `case response age is missing`.

- [ ] **Step 3: Add API and store types**

Add the response field:

```typescript
export interface LongitudinalCase {
  id: number
  user_id: number
  disease_id: number
  patient_label: string
  age: number | null
```

Require age in `createLongitudinalCase` and `saveLongitudinalCase` inputs:

```typescript
data: {
  disease_id: number
  patient_label: string
  age: number
  sex?: string | null
  baseline_stage?: BaselineStage | null
  notes?: string | null
}
```

The existing `const { visits, ...caseData } = data` then forwards age to both create and update without another branch.

- [ ] **Step 4: Add the bounded editor control and validation**

Add to `toDraft()`:

```typescript
age: value?.age ?? null,
```

Add the control to the existing basic-information grid:

```vue
<el-input-number
  v-model="draft.age"
  :min="0"
  :max="120"
  :precision="0"
  placeholder="年龄"
  aria-label="年龄"
/>
```

Import `ElMessage` from Element Plus and reject invalid values before changing `saving` or emitting:

```typescript
async function saveCase() {
  if (!Number.isInteger(draft.age) || draft.age < 0 || draft.age > 120) {
    ElMessage.error('请填写0–120岁的整数年龄')
    return
  }
  saving.value = true
  try {
    emit('saved', draft as LongitudinalCase)
    emit('update:modelValue', draft as LongitudinalCase)
  } finally {
    saving.value = false
  }
}
```

- [ ] **Step 5: Include age in the page save payload**

Expand the existing call without changing its save-then-report behavior:

```typescript
const saved = await operatorStore.saveLongitudinalCase({
  disease_id: draft.disease_id,
  patient_label: draft.patient_label,
  age: draft.age,
  sex: draft.sex,
  baseline_stage: draft.baseline_stage || null,
  visits,
})
```

- [ ] **Step 6: Run frontend contracts and production build**

```powershell
node tests/longitudinal-age.test.mjs
node tests/longitudinal-case-sync.test.mjs
node tests/longitudinal-baseline-stage.test.mjs
node tests/longitudinal-report-ui-contract.test.mjs
npm run build
```

Expected: all four contract scripts print their pass messages and Vite completes a production build without TypeScript errors.

- [ ] **Step 7: Commit frontend age entry**

```powershell
git commit -m "feat: collect age for operator cases"
```

---

### Task 6: Documentation, Integrated Verification, and Appendix Closure

**Files:**
- Modify: `docs/AI操作者流程核查.md`
- Verify: all files modified in Tasks 1–5

**Interfaces:**
- Consumes: verified migration, backend, model, and frontend behavior.
- Produces: an accurate appendix state and deployable repository changes; no server-side mutation.

- [ ] **Step 1: Run the complete focused backend suite**

Run from `backend/`:

```powershell
python -m pytest tests/test_alembic_contracts.py tests/test_schema_contracts.py tests/test_database_baseline.py tests/test_longitudinal_schema_contracts.py tests/test_longitudinal_case_service.py tests/test_longitudinal_features.py tests/test_longitudinal_prediction_contract.py tests/test_operator_catalog_and_reports_api.py tests/test_longitudinal_report_acceptance.py tests/test_longitudinal_end_to_end.py tests/test_longitudinal_report_generator.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Re-run frontend verification**

Run from `frontend/`:

```powershell
node tests/longitudinal-age.test.mjs
node tests/longitudinal-case-sync.test.mjs
node tests/longitudinal-baseline-stage.test.mjs
node tests/longitudinal-report-ui-contract.test.mjs
npm run build
```

Expected: all contract scripts and production build pass.

- [ ] **Step 3: Update the appendix only after verification passes**

Change the database appendix item from the unresolved statement to a completed record that states:

```markdown
1. **已完成：`operator_cases` 单独保存年龄。** 已通过 Alembic `0013` 增加可空整数列和 `0–120` 检查约束；新病例必须填写年龄，旧病例保留空值但生成新报告前必须补录。年龄已进入报告输入快照和两条纵向模型特征路径。
```

Also revise earlier present-tense statements in the same document that still claim the current table, Schema, form, or inference flow has no age. Keep historical rationale, but do not leave contradictory current-state claims.

- [ ] **Step 4: Check migration identity and repository diffs**

```powershell
python -m alembic heads
git diff --check
git status --short
```

Expected: one `0013 (head)`, no whitespace errors, and only intended task changes plus preserved pre-existing user changes.

- [ ] **Step 5: Attempt the full backend suite and record unrelated blockers accurately**

```powershell
python -m pytest -q
```

Expected for this repository state: collection may still stop at the pre-existing `ModuleNotFoundError: No module named 'scripts.check_model_artifacts'`. Do not modify or delete unrelated tests to make this pass; report the exact result alongside the passing focused suite.

- [ ] **Step 6: Review migration deployment semantics**

Confirm from the final diff that the deployment action documented for the server is only:

```powershell
alembic upgrade head
```

Do not connect to the server, execute `schema.sql` on an existing database, stamp an unknown database revision, or add a fabricated age backfill.

- [ ] **Step 7: Commit the verified appendix closure**

```powershell
git commit -m "docs: close operator case age audit item"
```

The completion report must include the new Alembic head, focused backend test count, frontend contract/build result, full-suite blocker if still present, and a reminder that the production database has not been modified in this workspace.
