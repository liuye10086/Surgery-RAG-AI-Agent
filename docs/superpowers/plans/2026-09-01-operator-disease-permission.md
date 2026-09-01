# AI Operator Disease Permission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce immutable disease codes and administrator-controlled AI-operator enablement so only supported, enabled diseases can enter the longitudinal workflow while disabled diseases remain historically readable.

**Architecture:** Extend `diseases` with `code` and `operator_enabled`, protect every disease foreign key with `RESTRICT`, and centralize disease capability/permission checks in one backend service. Separate administrator disease CRUD from the operator read-only catalog, migrate all model/data routing from Chinese display names to stable codes, and make disabled longitudinal cases read-only in both API and UI.

**Tech Stack:** PostgreSQL, Alembic, SQLAlchemy, FastAPI, Pydantic v2, Vue 3, TypeScript, Pinia, Element Plus, Node test runner, pytest.

## Global Constraints

- `diseases` remains an extensible global catalog, but only explicitly enabled and program-supported diseases may enter the AI operator longitudinal workflow.
- The initial supported codes are exactly `fatty_liver` and `ad`; do not hard-code Chinese disease names or database IDs in a database CHECK constraint.
- `diseases.code` is unique, non-null, lowercase snake case, and immutable through ordinary APIs.
- Disease catalog writes are administrator-only; AI operators receive a read-only list of currently usable diseases.
- New diseases default to `operator_enabled = false`; enabling requires a registered backend capability.
- A longitudinal case cannot change disease after creation.
- When a disease is disabled, existing cases, reports, and PDFs remain readable, but all case/visit mutations and new report generation are rejected.
- A disease referenced by any operator case, reference case, AI report, or standard cannot be physically deleted; only an entirely unused disease can be deleted.
- Existing databases must contain exactly the two expected disease names or migration stops and rolls back. A completely empty new database may initialize the two base diseases automatically.
- Old report snapshots without `disease_code` remain readable; new snapshots store disease ID, display name, and stable code.
- Do not connect to or mutate the production server during repository implementation.
- Before any frontend UI edit, read and follow `docs/DESIGN_SPEC.md`.
- Use TDD for every behavior change and run verification before claiming completion.

---

## File and Responsibility Map

**Create:**

- `backend/alembic/versions/0014_disease_codes_and_operator_permission.py` — strict empty/existing database migration and FK hardening.
- `backend/app/services/disease_catalog.py` — stable-code capability registry, permission checks, and disease usage counting.
- `backend/app/api/admin_diseases.py` — administrator-only disease CRUD, enable/disable, and safe deletion.
- `backend/tests/test_disease_catalog_service.py` — capability and permission service tests.
- `backend/tests/test_admin_diseases_api.py` — administrator API and deletion protection tests.
- `scripts/check_operator_disease_migration_readonly.py` — pre-migration read-only audit for empty versus existing databases.
- `scripts/tests/test_check_operator_disease_migration_readonly.py` — preflight checker tests.
- `frontend/src/api/adminDiseases.ts` — administrator disease API types and calls.
- `frontend/src/components/DiseaseManagementView.vue` — administrator disease management UI.
- `frontend/tests/disease-management-ui-contract.test.mjs` — administrator UI contract tests.
- `frontend/tests/operator-disease-permission-ui-contract.test.mjs` — operator list, immutable disease, stable-code routing, and disabled-case UI tests.

**Modify:**

- `backend/app/db/models.py` — disease columns and restrictive foreign keys.
- `backend/app/schemas/prediction.py` — disease create/update/output contracts.
- `backend/app/schemas/longitudinal_case.py` — immutable disease update contract and disease identity in case output.
- `backend/app/services/longitudinal_case_service.py` — centralized write gating and snapshot `disease_code`.
- `backend/app/api/operator.py` — read-only operator disease catalog, stable-code report routing, and permission error mapping.
- `backend/app/main.py` — register administrator disease router.
- `backend/app/services/longitudinal_dataset.py` — select and route cohorts by disease code.
- `backend/app/services/longitudinal_readiness.py` — identify database diseases by stable code.
- `backend/app/api/admin_standards.py` — validate standards with `disease.code`.
- `backend/app/services/standard_draft_service.py` — resolve diseases by code.
- `scripts/import_longitudinal.py` — resolve import target by code and refuse implicit disease creation.
- `scripts/seed_standard_drafts.py` — resolve standard targets by code.
- `scripts/prepare_standard_drafts.py` — pass stable code through preparation specs.
- `scripts/check_database_readonly.py` — verify post-migration columns, types, disease rows, and delete rules.
- `database/schema.sql` — align reference snapshot with Alembic head.
- `database/README.md` and `docs/DEPLOY.md` — document preflight and deployment boundaries.
- `backend/tests/test_alembic_contracts.py`, `backend/tests/test_schema_contracts.py`, `backend/tests/test_database_baseline.py` — migration/schema/readiness contracts.
- Relevant longitudinal dataset, readiness, standard draft, import, and operator API tests — stable-code regressions.
- `frontend/src/api/operator.ts` — disease and longitudinal case response types; remove operator disease write calls.
- `frontend/src/stores/operator.ts` — consume operator-usable disease list and immutable case updates.
- `frontend/src/components/CaseManageView.vue` — remove disease catalog management area.
- `frontend/src/components/LongitudinalCaseEditor.vue` — route stages by code and render disabled cases read-only.
- `frontend/src/views/OperatorView.vue` — stop Chinese-name filtering and block disabled-case save/report actions.
- `frontend/src/components/AdminSidebar.vue` and `frontend/src/views/AdminView.vue` — expose administrator disease management.
- `frontend/src/components/StandardManagementView.vue` — use administrator full disease catalog.
- Existing frontend contract tests — update expectations from display-name routing to code routing.
- `docs/AI操作者流程核查.md` — update only after implementation and verification succeed.

---

### Task 1: Add the strict Alembic migration and ORM/schema contract

**Files:**

- Create: `backend/alembic/versions/0014_disease_codes_and_operator_permission.py`
- Modify: `backend/app/db/models.py:173-230`
- Modify: `database/schema.sql:64-125`
- Modify: `backend/tests/test_alembic_contracts.py`
- Modify: `backend/tests/test_schema_contracts.py`

**Interfaces:**

- Produces database columns `Disease.code: str` and `Disease.operator_enabled: bool`.
- Produces constraints `uq_diseases_code`, `ck_diseases_code_format`.
- Produces restrictive FKs named `fk_operator_cases_disease`, `fk_case_records_disease`, and `fk_ai_reports_disease`.
- Later tasks rely on `Disease.code` being non-null and on both base diseases existing after an empty-database upgrade.

- [ ] **Step 1: Write failing Alembic and ORM contract tests**

Add tests that load revision `0014`, verify it follows `0013`, and exercise both migration branches:

```python
def test_disease_permission_migration_follows_0013():
    migration = _load_revision(
        "0014_disease_codes_and_operator_permission.py",
        "migration_0014",
    )
    assert migration.revision == "0014"
    assert migration.down_revision == "0013"


def test_disease_permission_orm_columns_and_delete_rules():
    from app.db.models import AIReport, CaseRecord, Disease, OperatorCase

    disease_columns = Disease.__table__.columns
    assert disease_columns["code"].nullable is False
    assert disease_columns["operator_enabled"].nullable is False
    assert disease_columns["operator_enabled"].server_default.arg == "false"

    for model in (OperatorCase, CaseRecord, AIReport):
        fk = next(iter(model.__table__.columns["disease_id"].foreign_keys))
        assert fk.ondelete == "RESTRICT"
```

Add migration guard tests with a fake bind:

```python
def test_disease_permission_migration_rejects_third_disease_before_constraints():
    migration = _load_revision(
        "0014_disease_codes_and_operator_permission.py",
        "migration_0014_third_disease",
    )
    bind = _DiseaseMigrationBind(
        diseases=[
            {"id": 1, "name": "脂肪肝"},
            {"id": 2, "name": "阿尔茨海默病"},
            {"id": 3, "name": "胃癌"},
        ],
        reference_counts={"operator_cases": 0, "case_records": 0, "ai_reports": 0, "reference_standards": 0},
    )
    migration_op = MagicMock()
    migration_op.get_bind.return_value = bind

    with patch.object(migration, "op", migration_op):
        with pytest.raises(RuntimeError, match="unexpected diseases"):
            migration.upgrade()

    migration_op.create_unique_constraint.assert_not_called()
```

Also test that an empty catalog with no related rows executes two INSERTs, while an empty catalog with related rows raises `RuntimeError`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
Set-Location backend
pytest tests/test_alembic_contracts.py tests/test_schema_contracts.py -q
```

Expected: failures because revision `0014`, new columns, new constraints, and restrictive FKs do not exist.

- [ ] **Step 3: Implement revision `0014`**

Use one transaction and lock the catalog plus dependent tables before inspecting data. The migration must follow this structure:

```python
revision = "0014"
down_revision = "0013"

EXPECTED = {
    "脂肪肝": "fatty_liver",
    "阿尔茨海默病": "ad",
}


def _rows(bind, sql: str):
    return [dict(row) for row in bind.execute(sa.text(sql)).mappings().all()]


def _count(bind, table: str, where: str = "TRUE") -> int:
    return int(
        bind.execute(sa.text(f"SELECT count(*) FROM {table} WHERE {where}"))
        .scalar_one()
    )


def upgrade() -> None:
    op.add_column("diseases", sa.Column("code", sa.String(64), nullable=True))
    op.add_column(
        "diseases",
        sa.Column(
            "operator_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    bind = op.get_bind()
    bind.execute(sa.text(
        "LOCK TABLE diseases, operator_cases, case_records, ai_reports, "
        "reference_standards IN SHARE ROW EXCLUSIVE MODE"
    ))
    diseases = _rows(bind, "SELECT id, name FROM diseases ORDER BY id")
    related = {
        "operator_cases": _count(bind, "operator_cases"),
        "case_records": _count(bind, "case_records"),
        "ai_reports": _count(bind, "ai_reports", "disease_id IS NOT NULL"),
        "reference_standards": _count(bind, "reference_standards"),
    }

    if not diseases:
        if any(related.values()):
            raise RuntimeError("0014 empty diseases catalog has related business data")
        for name, code in EXPECTED.items():
            bind.execute(
                sa.text(
                    "INSERT INTO diseases (name, code, operator_enabled) "
                    "VALUES (:name, :code, true)"
                ),
                {"name": name, "code": code},
            )
    elif {row["name"] for row in diseases} != set(EXPECTED) or len(diseases) != 2:
        raise RuntimeError("0014 unexpected diseases; manual review required")
    else:
        for name, code in EXPECTED.items():
            bind.execute(
                sa.text(
                    "UPDATE diseases SET code=:code, operator_enabled=true "
                    "WHERE name=:name"
                ),
                {"name": name, "code": code},
            )

    null_count = _count(bind, "diseases", "code IS NULL")
    if null_count:
        raise RuntimeError("0014 failed to assign every disease code")

    op.alter_column("diseases", "code", nullable=False)
    op.create_unique_constraint("uq_diseases_code", "diseases", ["code"])
    op.create_check_constraint(
        "ck_diseases_code_format",
        "diseases",
        "code ~ '^[a-z][a-z0-9_]*$'",
    )
    # Drop and recreate all three named FKs with ondelete="RESTRICT".
```

In `downgrade()`, restore `operator_cases` and `case_records` to `CASCADE`, restore `ai_reports` to `SET NULL`, then remove constraints and columns. Do not delete disease rows in downgrade.

- [ ] **Step 4: Align ORM and `database/schema.sql`**

Implement the ORM shape:

```python
class Disease(Base):
    __tablename__ = "diseases"
    __table_args__ = (
        CheckConstraint(
            "code ~ '^[a-z][a-z0-9_]*$'",
            name="ck_diseases_code_format",
        ),
    )

    id = Column(Integer, primary_key=True)
    code = Column(String(64), nullable=False, unique=True)
    name = Column(String(200), unique=True, nullable=False)
    description = Column(Text)
    operator_enabled = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
```

Set the three ORM foreign keys to `ondelete="RESTRICT"`. Update `database/schema.sql` with the same columns, named constraints, and delete rules. Do not add Chinese-name CHECK constraints.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```powershell
Set-Location backend
pytest tests/test_alembic_contracts.py tests/test_schema_contracts.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit the database structure**

```powershell
git add backend/alembic/versions/0014_disease_codes_and_operator_permission.py
git add backend/app/db/models.py database/schema.sql
git add backend/tests/test_alembic_contracts.py backend/tests/test_schema_contracts.py
git commit -m "feat: add stable disease codes and deletion protection"
```

---

### Task 2: Add the pre-migration and post-migration read-only database checks

**Files:**

- Create: `scripts/check_operator_disease_migration_readonly.py`
- Create: `scripts/tests/test_check_operator_disease_migration_readonly.py`
- Modify: `scripts/check_database_readonly.py`
- Modify: `backend/tests/test_database_baseline.py`

**Interfaces:**

- Produces `collect_disease_migration_checks(connection) -> dict` for pre-upgrade auditing.
- Extends the existing post-upgrade report with disease columns, exact base codes, enabled flags, and FK delete rules.

- [ ] **Step 1: Write failing tests for empty, valid-existing, and invalid-existing databases**

Create tests with fake read-only connections:

```python
def test_empty_database_is_safe_to_initialize():
    report = checker.collect_disease_migration_checks(
        FakeConnection(diseases=[], related_counts={name: 0 for name in checker.RELATED_TABLES})
    )
    assert report["mode"] == "empty_initialize"
    assert report["status"] == "PASS"


def test_existing_two_disease_database_is_safe_to_backfill():
    report = checker.collect_disease_migration_checks(
        FakeConnection(
            diseases=[{"id": 1, "name": "脂肪肝"}, {"id": 2, "name": "阿尔茨海默病"}],
            related_counts={"operator_cases": 3, "case_records": 8, "ai_reports": 2, "reference_standards": 2},
        )
    )
    assert report["mode"] == "existing_backfill"
    assert report["status"] == "PASS"


def test_third_disease_blocks_migration_without_mutating_sql():
    report = checker.collect_disease_migration_checks(
        FakeConnection(
            diseases=[{"id": 1, "name": "脂肪肝"}, {"id": 2, "name": "阿尔茨海默病"}, {"id": 3, "name": "胃癌"}],
            related_counts={name: 0 for name in checker.RELATED_TABLES},
        )
    )
    assert report["status"] == "FAIL"
    assert report["unexpected_diseases"] == [{"id": 3, "name": "胃癌"}]
```

Extend `test_database_baseline.py` so post-head checks require `diseases.code`, `diseases.operator_enabled`, exact types, two enabled base rows, and `RESTRICT` delete rules.

- [ ] **Step 2: Run the checker tests and verify RED**

Run:

```powershell
pytest scripts/tests/test_check_operator_disease_migration_readonly.py backend/tests/test_database_baseline.py -q
```

Expected: failures because the new checker and new post-head assertions do not exist.

- [ ] **Step 3: Implement the preflight checker**

The checker must begin with `SET TRANSACTION READ ONLY` and issue only SELECT/SHOW statements:

```python
EXPECTED = {"脂肪肝": "fatty_liver", "阿尔茨海默病": "ad"}
RELATED_TABLES = (
    "operator_cases",
    "case_records",
    "ai_reports",
    "reference_standards",
)


def collect_disease_migration_checks(connection):
    connection.execute(text("SET TRANSACTION READ ONLY"))
    diseases = [
        dict(row)
        for row in connection.execute(
            text("SELECT id, name FROM diseases ORDER BY id")
        ).mappings().all()
    ]
    related_counts = {
        "operator_cases": _scalar(connection, "SELECT count(*) FROM operator_cases"),
        "case_records": _scalar(connection, "SELECT count(*) FROM case_records"),
        "ai_reports": _scalar(connection, "SELECT count(*) FROM ai_reports WHERE disease_id IS NOT NULL"),
        "reference_standards": _scalar(connection, "SELECT count(*) FROM reference_standards"),
    }
    if not diseases:
        safe = not any(related_counts.values())
        return {"status": "PASS" if safe else "FAIL", "mode": "empty_initialize", "diseases": [], "related_counts": related_counts}

    actual_names = {row["name"] for row in diseases}
    expected_names = set(EXPECTED)
    return {
        "status": "PASS" if len(diseases) == 2 and actual_names == expected_names else "FAIL",
        "mode": "existing_backfill",
        "diseases": diseases,
        "missing_diseases": sorted(expected_names - actual_names),
        "unexpected_diseases": [row for row in diseases if row["name"] not in expected_names],
        "related_counts": related_counts,
    }
```

The CLI prints deterministic JSON and exits `0` only for `PASS`.

- [ ] **Step 4: Extend the post-head checker**

Add required columns/types:

```python
REQUIRED_COLUMNS["diseases"] = {"id", "code", "name", "operator_enabled"}
REQUIRED_COLUMN_TYPES.update({
    ("diseases", "code"): "character varying",
    ("diseases", "operator_enabled"): "boolean",
})
```

Query:

```sql
SELECT code, name, operator_enabled FROM diseases ORDER BY code
```

and `information_schema.referential_constraints` for the three named foreign keys. The report is `PASS` only when the base rows are exactly:

```python
[
    {"code": "ad", "name": "阿尔茨海默病", "operator_enabled": True},
    {"code": "fatty_liver", "name": "脂肪肝", "operator_enabled": True},
]
```

and every disease FK delete rule is `RESTRICT`.

- [ ] **Step 5: Run checker tests and source mutation scan**

Run:

```powershell
pytest scripts/tests/test_check_operator_disease_migration_readonly.py backend/tests/test_database_baseline.py -q
rg -n "INSERT |UPDATE |DELETE |ALTER |DROP |TRUNCATE " scripts/check_operator_disease_migration_readonly.py scripts/check_database_readonly.py
```

Expected: tests pass; `rg` returns no executable mutating SQL in either checker.

- [ ] **Step 6: Commit read-only checks**

```powershell
git add scripts/check_operator_disease_migration_readonly.py
git add scripts/tests/test_check_operator_disease_migration_readonly.py
git add scripts/check_database_readonly.py backend/tests/test_database_baseline.py
git commit -m "feat: audit disease catalog migrations read only"
```

---

### Task 3: Centralize disease capability and permission rules

**Files:**

- Create: `backend/app/services/disease_catalog.py`
- Create: `backend/tests/test_disease_catalog_service.py`
- Modify: `backend/app/schemas/prediction.py`

**Interfaces:**

- Produces `DiseaseCapability` and `DISEASE_CAPABILITIES` keyed by stable code.
- Produces `require_disease_capability(code: str) -> DiseaseCapability` for administrator enablement checks.
- Produces `require_operator_disease(db, disease_id: int, *, for_update: bool = False) -> Disease`.
- Produces `require_enabled_case_disease(case: OperatorCase) -> Disease`.
- Produces `disease_usage_counts(db, disease_id: int) -> DiseaseUsageCounts`.
- Produces `DiseaseCreate`, `DiseaseUpdate`, `DiseaseOut`, and `AdminDiseaseOut` contracts.

- [ ] **Step 1: Write failing service and schema tests**

```python
def test_capability_registry_uses_stable_codes():
    from app.services.disease_catalog import DISEASE_CAPABILITIES

    assert set(DISEASE_CAPABILITIES) == {"fatty_liver", "ad"}
    assert DISEASE_CAPABILITIES["fatty_liver"].adapter.dataset == "fatty_liver"
    assert DISEASE_CAPABILITIES["ad"].adapter.dataset == "ad"


def test_require_operator_disease_rejects_disabled_and_unsupported():
    disabled = SimpleNamespace(id=1, code="fatty_liver", operator_enabled=False)
    unsupported = SimpleNamespace(id=2, code="gastric_cancer", operator_enabled=True)

    with pytest.raises(DiseaseDisabledError):
        require_operator_disease(FakeDb(disabled), 1)
    with pytest.raises(DiseaseCapabilityMissingError):
        require_operator_disease(FakeDb(unsupported), 2)


def test_disease_update_cannot_accept_code():
    with pytest.raises(ValidationError):
        DiseaseUpdate.model_validate({"code": "renamed"})
```

Also test code normalization/rejection, new diseases default disabled, and usage counts across all four referencing models.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
Set-Location backend
pytest tests/test_disease_catalog_service.py -q
```

Expected: import and assertion failures.

- [ ] **Step 3: Implement the capability registry and errors**

```python
@dataclass(frozen=True)
class DiseaseCapability:
    code: str
    adapter: DiseaseProgressionAdapter


DISEASE_CAPABILITIES = MappingProxyType({
    "fatty_liver": DiseaseCapability("fatty_liver", FATTY_LIVER_ADAPTER),
    "ad": DiseaseCapability("ad", AD_ADAPTER),
})


class DiseaseCatalogError(ValueError):
    pass


class DiseaseNotFoundError(DiseaseCatalogError):
    pass


class DiseaseDisabledError(DiseaseCatalogError):
    pass


class DiseaseCapabilityMissingError(DiseaseCatalogError):
    pass
```

Implement `require_operator_disease` so it queries by ID, optionally locks the row, then checks `operator_enabled` and registry membership in that order. `require_enabled_case_disease` reads `case.disease` and raises `DiseaseDisabledError` when the relationship is disabled.

Define usage counts:

```python
@dataclass(frozen=True)
class DiseaseUsageCounts:
    operator_cases: int
    case_records: int
    ai_reports: int
    reference_standards: int

    @property
    def total(self) -> int:
        return self.operator_cases + self.case_records + self.ai_reports + self.reference_standards
```

- [ ] **Step 4: Implement disease schemas**

Use strict extra rejection so clients cannot smuggle immutable fields:

```python
DISEASE_CODE_PATTERN = r"^[a-z][a-z0-9_]*$"


class DiseaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(..., min_length=1, max_length=64, pattern=DISEASE_CODE_PATTERN)
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None


class DiseaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    operator_enabled: bool | None = None


class DiseaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    description: str | None = None
    operator_enabled: bool
    created_at: datetime
```

Define the administrator-only response explicitly:

```python
class DiseaseUsageCountsOut(BaseModel):
    operator_cases: int
    case_records: int
    ai_reports: int
    reference_standards: int


class AdminDiseaseOut(DiseaseOut):
    usage_counts: DiseaseUsageCountsOut
    can_delete: bool
```

`require_disease_capability` performs a dictionary lookup in `DISEASE_CAPABILITIES` and raises
`DiseaseCapabilityMissingError` when the code is absent. `require_operator_disease` reuses that
function after checking that the row exists and `operator_enabled` is true.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```powershell
Set-Location backend
pytest tests/test_disease_catalog_service.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit the service boundary**

```powershell
git add backend/app/services/disease_catalog.py
git add backend/app/schemas/prediction.py
git add backend/tests/test_disease_catalog_service.py
git commit -m "feat: centralize disease capabilities and permissions"
```

---

### Task 4: Move disease management to administrator APIs and make operator catalog read-only

**Files:**

- Create: `backend/app/api/admin_diseases.py`
- Create: `backend/tests/test_admin_diseases_api.py`
- Modify: `backend/app/api/operator.py:435-542`
- Modify: `backend/app/main.py:10-35`
- Modify: `backend/tests/test_operator_catalog_and_reports_api.py`

**Interfaces:**

- Produces administrator endpoints under `/api/v1/admin/diseases`.
- Keeps `GET /api/v1/operator/diseases` but returns only enabled, registered diseases.
- Removes operator POST/PUT/DELETE disease routes.

- [ ] **Step 1: Write failing route, permission, enablement, and deletion tests**

```python
def test_admin_disease_routes_require_admin():
    from app.api.admin_diseases import router

    for route in router.routes:
        names = {getattr(dep.call, "__name__", "") for dep in route.dependant.dependencies}
        assert "require_admin" in names


def test_operator_router_exposes_only_get_diseases():
    from app.api.operator import router

    disease_routes = [route for route in router.routes if route.path.startswith("/operator/diseases")]
    assert [(route.path, set(route.methods)) for route in disease_routes] == [
        ("/operator/diseases", {"GET"})
    ]


def test_enable_rejects_unregistered_code_without_commit():
    disease = SimpleNamespace(id=3, code="gastric_cancer", operator_enabled=False)
    db = FakeDb(disease)
    with pytest.raises(HTTPException) as error:
        update_disease(3, DiseaseUpdate(operator_enabled=True), db=db, admin=ADMIN)
    assert error.value.status_code == 422
    assert error.value.detail == "该疾病尚未配置预测能力，不能启用"
    assert db.commits == 0


def test_delete_rejects_any_usage():
    db = FakeDb(disease=DISEASE, usage=DiseaseUsageCounts(1, 0, 0, 0))
    with pytest.raises(HTTPException) as error:
        delete_disease(DISEASE.id, db=db, admin=ADMIN)
    assert error.value.status_code == 409
    assert error.value.detail == "该疾病已被业务数据引用，不能删除"
```

Also test duplicate name/code conflicts, immutable code, disable success, unused delete success, and FK-race mapping for each named disease FK.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
Set-Location backend
pytest tests/test_admin_diseases_api.py tests/test_operator_catalog_and_reports_api.py -q
```

Expected: failures because the administrator router does not exist and operator write routes still exist.

- [ ] **Step 3: Implement administrator disease endpoints**

Create:

```python
router = APIRouter(prefix="/admin/diseases", tags=["admin-diseases"])

DISEASE_REFERENCE_FKS = {
    "fk_operator_cases_disease",
    "fk_case_records_disease",
    "fk_ai_reports_disease",
    "reference_standards_disease_id_fkey",
}


def _integrity_constraint_name(exc: IntegrityError) -> str | None:
    return getattr(getattr(exc.orig, "diag", None), "constraint_name", None)


def _to_admin_out(db: Session, disease: Disease) -> AdminDiseaseOut:
    counts = disease_usage_counts(db, disease.id)
    return AdminDiseaseOut(
        id=disease.id,
        code=disease.code,
        name=disease.name,
        description=disease.description,
        operator_enabled=disease.operator_enabled,
        created_at=disease.created_at,
        usage_counts=DiseaseUsageCountsOut(
            operator_cases=counts.operator_cases,
            case_records=counts.case_records,
            ai_reports=counts.ai_reports,
            reference_standards=counts.reference_standards,
        ),
        can_delete=counts.total == 0,
    )


def _disease_or_404(db: Session, disease_id: int, *, for_update: bool = False) -> Disease:
    query = db.query(Disease).filter(Disease.id == disease_id)
    if for_update:
        query = query.with_for_update()
    disease = query.first()
    if disease is None:
        raise HTTPException(status_code=404, detail="疾病不存在")
    return disease


@router.get("", response_model=list[AdminDiseaseOut])
def list_diseases(admin=Depends(require_admin), db: Session = Depends(get_db)):
    diseases = db.query(Disease).order_by(Disease.id).all()
    return [_to_admin_out(db, disease) for disease in diseases]


@router.post("", response_model=AdminDiseaseOut, status_code=201)
def create_disease(payload: DiseaseCreate, admin=Depends(require_admin), db: Session = Depends(get_db)):
    code = payload.code.strip()
    name = payload.name.strip()
    if db.query(Disease.id).filter(Disease.code == code).first():
        raise HTTPException(status_code=409, detail="疾病代码已存在")
    if db.query(Disease.id).filter(Disease.name == name).first():
        raise HTTPException(status_code=409, detail="疾病名称已存在")
    disease = Disease(
        code=code,
        name=name,
        description=payload.description,
        operator_enabled=False,
    )
    db.add(disease)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="疾病代码或名称已存在") from exc
    db.refresh(disease)
    return _to_admin_out(db, disease)


@router.put("/{disease_id}", response_model=AdminDiseaseOut)
def update_disease(disease_id: int, payload: DiseaseUpdate, admin=Depends(require_admin), db: Session = Depends(get_db)):
    disease = _disease_or_404(db, disease_id, for_update=True)
    if payload.name is not None:
        name = payload.name.strip()
        duplicate = db.query(Disease.id).filter(
            Disease.name == name,
            Disease.id != disease.id,
        ).first()
        if duplicate:
            raise HTTPException(status_code=409, detail="疾病名称已存在")
        disease.name = name
    if "description" in payload.model_fields_set:
        disease.description = payload.description
    if payload.operator_enabled is not None:
        if payload.operator_enabled:
            try:
                require_disease_capability(disease.code)
            except DiseaseCapabilityMissingError as exc:
                raise HTTPException(
                    status_code=422,
                    detail="该疾病尚未配置预测能力，不能启用",
                ) from exc
        disease.operator_enabled = payload.operator_enabled
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="疾病名称已存在") from exc
    db.refresh(disease)
    return _to_admin_out(db, disease)


@router.delete("/{disease_id}", status_code=204)
def delete_disease(disease_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    disease = _disease_or_404(db, disease_id, for_update=True)
    if disease_usage_counts(db, disease.id).total:
        raise HTTPException(status_code=409, detail="该疾病已被业务数据引用，不能删除")
    db.delete(disease)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _integrity_constraint_name(exc) in DISEASE_REFERENCE_FKS:
            raise HTTPException(
                status_code=409,
                detail="该疾病已被业务数据引用，不能删除",
            ) from exc
        raise
    return Response(status_code=204)
```

When enabling, require a capability before mutating the row. When deleting, lock the disease, calculate all usage counts, reject any nonzero count, then rely on restrictive FKs for race protection.

- [ ] **Step 4: Convert the operator disease endpoint to a supported enabled list**

Keep only:

```python
@router.get("/diseases", response_model=list[DiseaseOut])
def list_operator_diseases(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    supported_codes = tuple(DISEASE_CAPABILITIES)
    return (
        db.query(Disease)
        .filter(
            Disease.operator_enabled.is_(True),
            Disease.code.in_(supported_codes),
        )
        .order_by(Disease.id)
        .all()
    )
```

Delete the operator create/update/delete disease functions and their old helper/count behavior. Register `admin_diseases.router` in `main.py` with prefix `/api/v1`.

- [ ] **Step 5: Run focused API tests and verify GREEN**

Run:

```powershell
Set-Location backend
pytest tests/test_admin_diseases_api.py tests/test_operator_catalog_and_reports_api.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit API ownership changes**

```powershell
git add backend/app/api/admin_diseases.py backend/app/api/operator.py backend/app/main.py
git add backend/tests/test_admin_diseases_api.py backend/tests/test_operator_catalog_and_reports_api.py
git commit -m "feat: move disease management to administrators"
```

---

### Task 5: Enforce immutable case disease and disabled-case read-only behavior

**Files:**

- Modify: `backend/app/schemas/longitudinal_case.py`
- Modify: `backend/app/services/longitudinal_case_service.py`
- Modify: `backend/app/api/operator.py:97-291`
- Modify: `backend/tests/test_longitudinal_case_service.py`
- Modify: `backend/tests/test_operator_catalog_and_reports_api.py`

**Interfaces:**

- `OperatorCaseUpdate` rejects `disease_id` as an extra field.
- `OperatorCaseOut` includes `disease: OperatorCaseDiseaseOut` with `id`, `code`, `name`, `operator_enabled`.
- Every case/visit mutation uses the same disease write guard.
- Report routing uses `case.disease.code`.
- New snapshots contain `disease_code` while preserving old snapshot compatibility.

- [ ] **Step 1: Write failing immutable-disease, disabled-write, and snapshot tests**

```python
def test_case_update_rejects_disease_id_even_from_old_client():
    with pytest.raises(ValidationError):
        OperatorCaseUpdate.model_validate({"disease_id": 12})


@pytest.mark.parametrize(
    "operation",
    [update_operator_case, delete_operator_case, add_visit, replace_visits, update_visit, delete_visit],
)
def test_disabled_disease_blocks_every_case_mutation(operation):
    case = _case()
    case.disease = SimpleNamespace(
        id=11,
        code="fatty_liver",
        name="脂肪肝",
        operator_enabled=False,
    )
    with pytest.raises(DiseaseDisabledError):
        invoke_operation(operation, case)


def test_snapshot_contains_stable_disease_code():
    case = _case()
    case.disease = SimpleNamespace(
        id=11,
        code="fatty_liver",
        name="脂肪肝新名称",
        operator_enabled=True,
    )
    snapshot = build_input_snapshot(case, [])
    assert snapshot["disease_id"] == 11
    assert snapshot["disease"] == "脂肪肝新名称"
    assert snapshot["disease_code"] == "fatty_liver"
```

Add a report API test proving that code `fatty_liver` still chooses the correct adapter after the display name changes. Add a disabled-report test that confirms no report row is inserted.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
Set-Location backend
pytest tests/test_longitudinal_case_service.py tests/test_operator_catalog_and_reports_api.py -q
```

Expected: failures for ignored `disease_id`, missing read-only guard, missing nested disease identity, and name-based report routing.

- [ ] **Step 3: Make the update contract immutable and expose disease identity**

```python
class OperatorCaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patient_label: str | None = Field(None, min_length=1, max_length=100)
    age: int | None = Field(None, ge=0, le=120, strict=True)
    sex: str | None = Field(None, pattern=r"^(male|female)$")
    baseline_stage: str | None = Field(None, max_length=100)
    notes: str | None = Field(None, max_length=5000)
    status: str | None = Field(None, pattern=r"^(active|archived)$")


class OperatorCaseDiseaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    operator_enabled: bool


class OperatorCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    disease_id: int
    patient_label: str
    age: int | None = None
    sex: str | None = None
    baseline_stage: str | None = None
    notes: str | None = None
    status: str
    visits: list[VisitOut] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    disease: OperatorCaseDiseaseOut
```

- [ ] **Step 4: Gate all mutations in the service**

Add:

```python
def get_operator_case_for_write(db, user_id: int, case_id: int) -> OperatorCase:
    case = get_operator_case(db, user_id, case_id)
    require_enabled_case_disease(case)
    return case
```

Use it in update/delete case and all visit mutations. Creation calls `require_operator_disease(db, payload.disease_id)` before constructing the row. List/get remain read-only and do not call the write guard.

- [ ] **Step 5: Route reports by stable code and add snapshot code**

Replace the display-name map with:

```python
try:
    disease = require_enabled_case_disease(case)
    adapter = DISEASE_CAPABILITIES[disease.code].adapter
except DiseaseCatalogError as exc:
    raise _disease_http_error(exc) from exc
```

In `build_input_snapshot` add:

```python
"disease_code": getattr(disease, "code", None),
```

Do not change `schema_version`; the added key is backward-compatible, and old snapshots are read as dictionaries without requiring it.

- [ ] **Step 6: Map errors to stable Chinese API messages**

Map:

```python
DiseaseDisabledError -> HTTP 409 "该疾病已停用，病例当前只读"
DiseaseCapabilityMissingError -> HTTP 422 "该疾病未开放 AI 操作者使用"
DiseaseNotFoundError -> HTTP 422 "疾病不存在"
Pydantic extra disease_id -> HTTP 422 request validation
```

Ownership lookup must happen before disease-state checks so another operator cannot infer case state.

- [ ] **Step 7: Run focused tests and verify GREEN**

Run:

```powershell
Set-Location backend
pytest tests/test_longitudinal_case_service.py tests/test_operator_catalog_and_reports_api.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit longitudinal write protection**

```powershell
git add backend/app/schemas/longitudinal_case.py
git add backend/app/services/longitudinal_case_service.py backend/app/api/operator.py
git add backend/tests/test_longitudinal_case_service.py backend/tests/test_operator_catalog_and_reports_api.py
git commit -m "feat: freeze disabled disease cases"
```

---

### Task 6: Migrate data, readiness, standards, and import routing to stable disease codes

**Files:**

- Modify: `backend/app/services/longitudinal_dataset.py`
- Modify: `backend/app/services/longitudinal_readiness.py`
- Modify: `backend/app/api/admin_standards.py`
- Modify: `backend/app/services/standard_draft_service.py`
- Modify: `scripts/import_longitudinal.py`
- Modify: `scripts/seed_standard_drafts.py`
- Modify: `scripts/prepare_standard_drafts.py`
- Modify: `backend/tests/test_longitudinal_dataset_builder.py`
- Modify: `backend/tests/test_longitudinal_readiness_service.py`
- Modify: `backend/tests/test_admin_standards_api.py`
- Modify: `backend/tests/test_standard_draft_service.py`
- Modify: `backend/tests/test_seed_standard_drafts.py`
- Modify: `scripts/tests/test_import_longitudinal.py`
- Modify: `scripts/tests/test_build_longitudinal_dataset.py`
- Modify: `scripts/tests/test_prepare_standard_drafts.py`

**Interfaces:**

- Database routing and lookup use `diseases.code`.
- Human-readable output may continue to include `diseases.name`.
- Import and standard preparation never create or infer a disease by display name.

- [ ] **Step 1: Write failing rename-resilience tests**

Add tests proving that a renamed display value does not change routing:

```python
def test_dataset_loader_routes_by_code_after_display_name_changes():
    rows = [{
        "record_id": 1,
        "disease_code": "fatty_liver",
        "disease_name": "脂肪肝（展示名已修改）",
        "patient_label": "P1",
        "indicators": [],
        "metadata": valid_metadata(),
    }]
    timelines, audit = rebuild_patient_timelines(rows)
    assert timelines[0].adapter.dataset == "fatty_liver"


def test_import_resolves_existing_disease_by_code_and_never_creates_one():
    disease = SimpleNamespace(id=7, code="ad", name="AD 展示名")
    db = ImportSession(disease=disease)
    import_dataset(db, "ad", patients=[], visits=[], source_documents={})
    assert db.added_diseases == []
```

Add readiness tests whose disease rows are keyed by `code` while names differ. Add standard validation/preparation tests that use stable code.

- [ ] **Step 2: Run focused stable-code regressions and verify RED**

Run:

```powershell
Set-Location backend
pytest tests/test_longitudinal_dataset_builder.py tests/test_longitudinal_readiness_service.py tests/test_admin_standards_api.py tests/test_standard_draft_service.py tests/test_seed_standard_drafts.py -q
Set-Location ..
pytest scripts/tests/test_import_longitudinal.py scripts/tests/test_build_longitudinal_dataset.py scripts/tests/test_prepare_standard_drafts.py -q
```

Expected: failures because queries and maps still use Chinese names.

- [ ] **Step 3: Convert longitudinal dataset loading to code**

Change the adapter map and SQL:

```python
_ADAPTERS_BY_CODE = {
    FATTY_LIVER_ADAPTER.dataset: FATTY_LIVER_ADAPTER,
    AD_ADAPTER.dataset: AD_ADAPTER,
}
```

```sql
SELECT cr.id AS record_id,
       d.code AS disease_code,
       d.name AS disease_name,
       cr.patient_label,
       cr.indicators,
       cr.metadata
FROM case_records cr
JOIN diseases d ON d.id = cr.disease_id
WHERE d.code IN ('fatty_liver', 'ad')
```

`rebuild_patient_timelines` resolves by `disease_code`; `disease_name` remains output metadata only.

- [ ] **Step 4: Convert readiness and standard paths to code**

Readiness queries select both `d.code AS disease_code` and `d.name AS disease_name`; build the disease lookup by code:

```python
diseases = {str(row["disease_code"]): dict(row) for row in snapshot["diseases"]}
disease_row = diseases.get(adapter.dataset)
```

In standard validation use:

```python
disease_key = version.standard.disease.code
```

Change `DraftPreparationSpec` to keep `dataset` as the stable database code and resolve with `Disease.code == spec.dataset`. Use `disease.name` only for generated display titles.

- [ ] **Step 5: Convert import and seed scripts to code**

In `scripts/import_longitudinal.py`, add explicit `disease_code` values to `DATASETS` and replace implicit creation:

```python
disease = db.query(Disease).filter(Disease.code == cfg["disease_code"]).first()
if disease is None:
    raise ValueError(f"数据库中缺少疾病代码：{cfg['disease_code']}")
```

Apply the same rule to standard seed/preparation scripts. Do not fall back to name aliases and do not create diseases from scripts.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run the same commands from Step 2.

Expected: all tests pass, including renamed-display-name cases.

- [ ] **Step 7: Commit stable-code routing**

```powershell
git add backend/app/services/longitudinal_dataset.py backend/app/services/longitudinal_readiness.py
git add backend/app/api/admin_standards.py backend/app/services/standard_draft_service.py
git add scripts/import_longitudinal.py scripts/seed_standard_drafts.py scripts/prepare_standard_drafts.py
git add backend/tests scripts/tests
git commit -m "refactor: route disease workflows by stable code"
```

---

### Task 7: Add administrator disease management UI

**Files:**

- Create: `frontend/src/api/adminDiseases.ts`
- Create: `frontend/src/components/DiseaseManagementView.vue`
- Create: `frontend/tests/disease-management-ui-contract.test.mjs`
- Modify: `frontend/src/components/AdminSidebar.vue`
- Modify: `frontend/src/views/AdminView.vue`
- Modify: `frontend/src/components/StandardManagementView.vue`

**Interfaces:**

- Produces `listAdminDiseases`, `createAdminDisease`, `updateAdminDisease`, and `deleteAdminDisease`.
- Administrator UI can create, rename, enable/disable, and safely delete unused diseases.
- Standard management consumes the administrator full catalog, not the operator enabled subset.

- [ ] **Step 1: Re-read the design system before UI changes**

Run:

```powershell
Get-Content -Raw docs/DESIGN_SPEC.md
```

Expected: the full design specification is reviewed before editing Vue/CSS.

- [ ] **Step 2: Write failing administrator UI contract tests**

```javascript
test('admin navigation exposes disease management', async () => {
  const sidebar = await readFile(new URL('../src/components/AdminSidebar.vue', import.meta.url), 'utf8')
  const view = await readFile(new URL('../src/views/AdminView.vue', import.meta.url), 'utf8')
  assert.match(sidebar, /key: 'diseases'/)
  assert.match(sidebar, /疾病管理/)
  assert.match(view, /activeSection === 'diseases'/)
  assert.match(view, /DiseaseManagementView/)
})


test('disease code is required on create and read only after creation', async () => {
  const source = await readFile(new URL('../src/components/DiseaseManagementView.vue', import.meta.url), 'utf8')
  assert.match(source, /固定代码/)
  assert.match(source, /operator_enabled/)
  assert.match(source, /该疾病尚未配置预测能力/)
  assert.doesNotMatch(source, /editForm\.code/)
})
```

Also assert 44px interactive targets and CSS variables from `DESIGN_SPEC.md`.

- [ ] **Step 3: Run the UI contract and verify RED**

Run:

```powershell
Set-Location frontend
node --test tests/disease-management-ui-contract.test.mjs
```

Expected: missing component/API/navigation failures.

- [ ] **Step 4: Implement administrator API bindings**

```typescript
export interface AdminDisease {
  id: number
  code: string
  name: string
  description: string | null
  operator_enabled: boolean
  usage_counts: {
    operator_cases: number
    case_records: number
    ai_reports: number
    reference_standards: number
  }
  can_delete: boolean
  created_at: string
}

export const listAdminDiseases = (): Promise<AdminDisease[]> =>
  request.get('/v1/admin/diseases')

export const createAdminDisease = (payload: { code: string; name: string; description?: string | null }): Promise<AdminDisease> =>
  request.post('/v1/admin/diseases', payload)

export const updateAdminDisease = (id: number, payload: { name?: string; description?: string | null; operator_enabled?: boolean }): Promise<AdminDisease> =>
  request.put(`/v1/admin/diseases/${id}`, payload)

export const deleteAdminDisease = (id: number): Promise<void> =>
  request.delete(`/v1/admin/diseases/${id}`)
```

- [ ] **Step 5: Implement `DiseaseManagementView.vue`**

Use a table/card consistent with the design spec:

- Show display name, immutable code, enabled status, four usage counts, and actions.
- Create dialog requires name and code; code placeholder is `例如：gastric_cancer`.
- Edit dialog excludes code.
- Enable/disable uses the update API and confirms disabling will make cases read-only.
- Delete button is disabled when `can_delete` is false and explains “该疾病已被业务数据引用，只能停用”.
- Errors display backend Chinese detail.

Register the view under `activeSection === 'diseases'` and add the sidebar item. Change `StandardManagementView.vue` to import the full list from `adminDiseases.ts`.

- [ ] **Step 6: Run UI contract and production build**

Run:

```powershell
Set-Location frontend
node --test tests/disease-management-ui-contract.test.mjs tests/standard-management-ui-contract.test.mjs
npm run build
```

Expected: tests pass and build exits `0`.

- [ ] **Step 7: Commit administrator UI**

```powershell
git add frontend/src/api/adminDiseases.ts frontend/src/components/DiseaseManagementView.vue
git add frontend/src/components/AdminSidebar.vue frontend/src/views/AdminView.vue
git add frontend/src/components/StandardManagementView.vue
git add frontend/tests/disease-management-ui-contract.test.mjs frontend/tests/standard-management-ui-contract.test.mjs
git commit -m "feat: add administrator disease management"
```

---

### Task 8: Make the AI operator UI code-driven and disabled-case read-only

**Files:**

- Create: `frontend/tests/operator-disease-permission-ui-contract.test.mjs`
- Modify: `frontend/src/api/operator.ts`
- Modify: `frontend/src/stores/operator.ts`
- Modify: `frontend/src/components/CaseManageView.vue`
- Modify: `frontend/src/components/LongitudinalCaseEditor.vue`
- Modify: `frontend/src/views/OperatorView.vue`
- Modify: `frontend/tests/longitudinal-baseline-stage.test.mjs`
- Modify: `frontend/tests/longitudinal-case-sync.test.mjs`

**Interfaces:**

- `Disease` includes `code` and `operator_enabled`.
- `LongitudinalCase` includes nested `disease` identity.
- Existing cases derive read-only state from `case.disease.operator_enabled`.
- Stage configuration is keyed by stable disease code.

- [ ] **Step 1: Re-read the design system before UI changes**

Run:

```powershell
Get-Content -Raw docs/DESIGN_SPEC.md
```

- [ ] **Step 2: Write failing operator UI contracts**

```javascript
test('operator UI has no disease catalog write controls', async () => {
  const caseView = await readFile(new URL('../src/components/CaseManageView.vue', import.meta.url), 'utf8')
  assert.doesNotMatch(caseView, /疾病字典/)
  assert.doesNotMatch(caseView, /createDisease|updateDisease|deleteDisease/)
})


test('stage routing uses stable code instead of Chinese name', async () => {
  const editor = await readFile(new URL('../src/components/LongitudinalCaseEditor.vue', import.meta.url), 'utf8')
  assert.match(editor, /selectedDisease.*\.code/)
  assert.doesNotMatch(editor, /selectedDisease\.value\?\.name === '脂肪肝'/)
  assert.doesNotMatch(editor, /selectedDisease\.value\?\.name === '阿尔茨海默病'/)
})


test('disabled existing disease renders case read only', async () => {
  const editor = await readFile(new URL('../src/components/LongitudinalCaseEditor.vue', import.meta.url), 'utf8')
  assert.match(editor, /该疾病当前已停用，病例暂时只读/)
  assert.match(editor, /readOnly/)
  assert.match(editor, /:disabled="readOnly"/)
})
```

Also assert that `updateLongitudinalCase` has an explicit payload type with no `disease_id`.

- [ ] **Step 3: Run operator UI contracts and verify RED**

Run:

```powershell
Set-Location frontend
node --test tests/operator-disease-permission-ui-contract.test.mjs tests/longitudinal-baseline-stage.test.mjs tests/longitudinal-case-sync.test.mjs
```

Expected: failures for Chinese-name routing, disease management controls, and missing read-only state.

- [ ] **Step 4: Update operator TypeScript contracts**

```typescript
export interface Disease {
  id: number
  code: string
  name: string
  description: string | null
  operator_enabled: boolean
  created_at: string
}

export interface LongitudinalCaseDisease {
  id: number
  code: string
  name: string
  operator_enabled: boolean
}

export interface LongitudinalCase {
  id: number
  user_id: number
  disease_id: number
  patient_label: string
  age: number | null
  sex?: 'male' | 'female' | null
  baseline_stage?: BaselineStage | string | null
  notes?: string | null
  status: 'active' | 'archived'
  visits: LongitudinalVisit[]
  created_at?: string
  updated_at?: string
  disease: LongitudinalCaseDisease
}

export interface LongitudinalCaseUpdatePayload {
  patient_label?: string
  age?: number
  sex?: 'male' | 'female' | null
  baseline_stage?: BaselineStage | null
  notes?: string | null
  status?: 'active' | 'archived'
}
```

Remove `createDisease`, `updateDisease`, and `deleteDisease` from `operator.ts`. Type `updateLongitudinalCase` with `LongitudinalCaseUpdatePayload` rather than `Record<string, unknown>`.

- [ ] **Step 5: Remove the disease dictionary write UI**

Delete the entire disease-management section, dialogs, handlers, and imports from `CaseManageView.vue`. Keep reference-case management using the operator-readable disease list.

- [ ] **Step 6: Make the longitudinal editor code-driven and read-only aware**

Use a stable configuration:

```typescript
const stageOptionsByCode: Record<string, Array<{ label: string; value: BaselineStage }>> = {
  fatty_liver: fattyLiverStages,
  ad: adStages,
}

const selectedDisease = computed(() => {
  if (props.modelValue?.disease) return props.modelValue.disease
  return props.diseases.find(item => item.id === draft.disease_id) || null
})
const readOnly = computed(() => Boolean(props.modelValue && !props.modelValue.disease.operator_enabled))
const stageOptions = computed(() => stageOptionsByCode[selectedDisease.value?.code || ''] || [])
```

Behavior:

- For a new case, disease select is enabled and uses the current operator disease list.
- For an existing case, disease is displayed read-only and never emitted as an update field.
- When disabled, show the warning and disable save, input fields, add/remove visit, and report generation actions.

- [ ] **Step 7: Stop filtering by Chinese names in `OperatorView.vue`**

Replace `progressionDiseases` name filtering with the store list directly. Before save/report, reject a disabled selected case with `ElMessage.error('该疾病已停用，病例当前只读')`. Ensure update payload excludes `disease_id`; creation still includes it.

- [ ] **Step 8: Run all frontend contracts and build**

Run:

```powershell
Set-Location frontend
node --test tests/*.test.mjs
npm run build
```

Expected: every contract passes and production build exits `0`.

- [ ] **Step 9: Commit operator UI changes**

```powershell
git add frontend/src/api/operator.ts frontend/src/stores/operator.ts
git add frontend/src/components/CaseManageView.vue frontend/src/components/LongitudinalCaseEditor.vue
git add frontend/src/views/OperatorView.vue
git add frontend/tests/operator-disease-permission-ui-contract.test.mjs
git add frontend/tests/longitudinal-baseline-stage.test.mjs frontend/tests/longitudinal-case-sync.test.mjs
git commit -m "feat: enforce operator disease permissions in UI"
```

---

### Task 9: Run full regression, document deployment, and update the audit appendix

**Files:**

- Modify: `database/README.md`
- Modify: `docs/DEPLOY.md`
- Modify: `docs/AI操作者流程核查.md`

**Interfaces:**

- Produces final verification evidence and deployment instructions.
- Updates the audit appendix only after implementation is actually verified.

- [ ] **Step 1: Document deployment and rollback boundaries**

Add the exact production sequence:

```text
备份数据库
→ python scripts/check_operator_disease_migration_readonly.py
→ 人工确认 PASS 和 empty_initialize/existing_backfill 模式
→ cd backend && alembic upgrade head
→ python ../scripts/check_database_readonly.py
→ 重启后端
→ AD 与脂肪肝双疾病冒烟验证
```

State explicitly:

- Do not stamp an unknown production database.
- Do not run `database/schema.sql` on an existing production database.
- Any unexpected or missing disease blocks migration and requires manual review.
- Disabling a disease is reversible and preserves history.
- Deleting a disease is allowed only when all four usage counts are zero.

- [ ] **Step 2: Run the full backend test suite**

Run:

```powershell
Set-Location backend
pytest -q
```

Expected: exit `0`, no failures.

- [ ] **Step 3: Run script tests**

Run:

```powershell
Set-Location ..
pytest scripts/tests -q
```

Expected: exit `0`, no failures.

- [ ] **Step 4: Run the full frontend contract suite and build**

Run:

```powershell
Set-Location frontend
node --test tests/*.test.mjs
npm run build
```

Expected: all Node tests pass and build exits `0`.

- [ ] **Step 5: Run migration/checker source and schema consistency scans**

Run:

```powershell
Set-Location ..
rg -n "Disease\.name\s*==|d\.name\s+IN|disease\.name\s*===|selectedDisease[^\r\n]*\.name|_ADAPTERS_BY_DISEASE" backend/app scripts frontend/src
rg -n 'ForeignKey\("diseases\.id", ondelete="(CASCADE|SET NULL)"\)' backend/app/db/models.py
rg -n 'disease_id INTEGER.*REFERENCES diseases\(id\) ON DELETE (CASCADE|SET NULL)' database/schema.sql
python scripts/check_operator_disease_migration_readonly.py
```

Expected:

- All three `rg` commands return no matches. Human-readable `disease.name` fields may still be selected or rendered, but none of the forbidden comparison/routing patterns remain.
- The focused Alembic/schema contract tests from Task 1 prove the three disease FKs are `RESTRICT` at head; migration downgrade retains the historical delete rules.
- The local checker may report `BLOCKED` if no database is configured; it must not mutate anything.

- [ ] **Step 6: Update the audit appendix with actual evidence**

Only after Steps 2-5 pass, update item 2 in `docs/AI操作者流程核查.md` to record:

- stable code and operator enablement implemented;
- administrator-only disease writes;
- operator API cannot be bypassed;
- case disease immutable;
- disabled cases historical/read-only;
- strict empty/existing migration behavior;
- exact test/build counts from fresh verification;
- production server was not contacted or modified.

Do not claim production migration is complete until the separate server deployment occurs.

- [ ] **Step 7: Review the working tree and commit final docs**

Run:

```powershell
git status --short
git diff --check
git diff --stat
```

Expected: only intended project files are changed; no generated artifacts, secrets, or unrelated user changes are staged.

Commit only this task's documentation changes:

```powershell
git add database/README.md docs/DEPLOY.md docs/AI操作者流程核查.md
git commit -m "docs: record disease permission rollout"
```

Do not include unrelated existing changes such as `outputs/report_method_validation.md`.

---

## Final Acceptance Checklist

- [ ] Empty databases initialize exactly `fatty_liver` and `ad`.
- [ ] Existing databases with missing, renamed, or third diseases stop before destructive DDL.
- [ ] `diseases.code` is non-null, unique, immutable through APIs, and format-constrained without enumerating diseases in CHECK.
- [ ] New diseases default disabled and cannot be enabled without a registered capability.
- [ ] AI operators cannot write the disease catalog.
- [ ] Direct API calls cannot create cases for disabled or unsupported diseases.
- [ ] Longitudinal case disease cannot change after creation.
- [ ] Disabled diseases preserve readable history and block every case/visit/report write.
- [ ] Used diseases cannot be physically deleted; all relevant database FKs are restrictive.
- [ ] Report, dataset, readiness, standard, and import routing use stable code rather than display name.
- [ ] Old snapshots without `disease_code` remain readable; new snapshots include it.
- [ ] Administrator and operator UIs follow `docs/DESIGN_SPEC.md` and pass production build.
- [ ] Full backend, script, frontend, and build verification passes.
- [ ] Production server remains untouched during repository implementation.
