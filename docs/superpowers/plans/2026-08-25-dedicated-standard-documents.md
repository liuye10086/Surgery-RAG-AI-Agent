# Dedicated Standard Documents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将标准 DOCX 从普通 `documents` 领域中分离到独立 `standard_documents` 表，并让管理员完成“上传标准文档 -> 选择疾病创建标准集合 -> 手动选择文档创建版本 -> 手动解析/审核/发布”的完整链路。

**Architecture:** 数据库迁移 `0010` 新建 `standard_documents`，并把 `reference_standard_versions.document_id` 替换为唯一的 `standard_document_id`。后端增加标准文档专用 schema、存储封装和管理员 API，标准版本生命周期只读取 `StandardDocument`；前端仅改造标准管理 API 与页面，普通文档上传、分块、向量化和检索保持原样。物理文件继续复用现有 `UPLOAD_DIR` 和底层保存能力，不进行普通文档目录重构。

**Tech Stack:** PostgreSQL, Alembic, SQLAlchemy, FastAPI, Pydantic v2, pytest, Vue 3, TypeScript, Element Plus, Node.js test runner, Vite

## Global Constraints

- 本任务是跨数据库、后端和前端的高风险任务，执行前必须采用 `完整任务流程`，在协调工作区登记 `Task-ID: standard-documents-001`，创建 `codex/standard-documents-001` 分支和 `.worktrees/standard-documents-001` 独立 worktree。
- `docs/coordination/ACTIVE_TASKS.md` 只在协调工作区维护；实施 worktree 不修改该文件。登记前检查所有非终止任务，若 `backend/app/db/models.py`、Alembic revision 链、`frontend/src/components/StandardManagementView.vue` 或标准 API 范围重叠，先由项目所有者协调。
- 数据迁移 revision 固定为 `0010`，`down_revision = "0009"`；升级发现任意 `reference_standard_versions` 记录必须中止，不迁移、不删除、不静默转换。
- 降级发现任意 `reference_standard_versions` 或 `standard_documents` 记录必须中止，防止业务数据丢失。
- 不迁移 `documents` 中的任何历史记录；`standard_documents` 从空数据开始。
- `standard_documents.content_hash` 全局唯一；`reference_standard_versions.standard_document_id` 非空、唯一、外键删除策略为 `RESTRICT`。
- 一个标准文档最多关联一个版本；删除 `draft` 或 `review` 版本后文档解锁；`approved`、`retired` 版本及其文档永久保留。
- 标准集合只能按 `disease_id` 创建，名称固定为 `${disease.name}标准`；不提供改名和删除接口。
- 上传和创建版本保持两阶段；创建版本后不自动解析，解析仍由管理员手动触发。
- 标准文档只允许 `.docx`；大小限制复用 `settings.MAX_UPLOAD_SIZE_MB`，物理保存复用 `settings.UPLOAD_DIR`，不改变普通 `file_storage`、普通文档目录或普通文档 API 行为。
- 普通文档上传、分块、向量化、检索、内容读取和文档管理页面不修改；纵向模型、报告、规则结构、发布投影和 resolver 语义不修改。
- 所有行为修改严格按 TDD 执行：先写失败测试并确认预期失败，再写最小实现，再运行聚焦测试。
- UI 修改前重新完整读取 `docs/DESIGN_SPEC.md`；使用现有暖杏蓝变量、Element Plus 组件和图标，保持紧凑管理工作台布局，不引入新视觉体系。
- 单元测试不得调用真实 DeepSeek；通过 monkeypatch 或注入假 adapter 验证解析。真实文件验收只在明确配置外部 API 时调用现有 DeepSeek adapter。
- PostgreSQL 迁移往返和真实 DOCX 验收必须使用隔离测试数据库，通过进程级 `STANDARD_DOCUMENT_TEST_DATABASE_URL` 注入；不得对正式 `DATABASE_URL` 写测试记录。
- 每个实现提交正文必须包含 `AI-Agent: Codex`、`AI-Client: Codex-Desktop`、`Task-ID: standard-documents-001`。不得自行推送或合并；完成评审与验证后分别请求项目所有者授权。
- 功能完成后必须由另一个 Agent/Claude Code 交叉评审，评审者只报告问题；修复由原实现者创建新提交。

---

## File Map

- `backend/alembic/versions/0010_dedicated_standard_documents.py`: 新表、外键替换及升降级数据保护。
- `backend/app/db/models.py`: `StandardDocument` ORM 以及 `ReferenceStandardVersion.standard_document` 一对一关系。
- `database/schema.sql`: 同步 `0009 + 0010` 的终态参考 DDL；正式部署仍以 Alembic 为准。
- `backend/app/schemas/standard_document.py`: 标准文档上传、列表和锁定信息响应契约。
- `backend/app/services/standard_document_storage.py`: DOCX 专用校验、复用保存、SHA-256 和严格删除封装。
- `backend/app/api/admin_standard_documents.py`: 管理员标准文档上传、列表和删除 API。
- `backend/app/schemas/standard.py`: 标准集合与版本请求/响应字段调整。
- `backend/app/api/admin_standards.py`: 自动命名、标准文档选取、版本删除和解析入口适配。
- `backend/app/services/standard_lifecycle.py`: 初始化草稿改用 `standard_document_id`。
- `scripts/seed_standard_drafts.py`: 显式 DOCX 路径导入 `standard_documents` 并创建幂等草稿。
- `frontend/src/api/adminStandards.ts`: 标准文档、集合和版本的专用 TypeScript API。
- `frontend/src/components/StandardManagementView.vue`: 两阶段标准管理工作流。
- `backend/tests/test_alembic_contracts.py`, `backend/tests/test_standard_models.py`, `backend/tests/test_schema_contracts.py`: 数据层契约。
- `backend/tests/test_admin_standard_documents_api.py`: 标准文档 API 和文件一致性测试。
- `backend/tests/test_admin_standards_api.py`, `backend/tests/test_standard_lifecycle.py`, `backend/tests/test_seed_standard_drafts.py`: 集合、版本、解析和脚本测试。
- `frontend/tests/standard-management-ui-contract.test.mjs`: 前端 API 与页面静态合同测试。

---

### Task 1: Add the `0010` Migration and ORM Boundary

**Files:**
- Create: `backend/alembic/versions/0010_dedicated_standard_documents.py`
- Modify: `backend/app/db/models.py`
- Modify: `database/schema.sql`
- Modify: `backend/tests/test_alembic_contracts.py`
- Modify: `backend/tests/test_standard_models.py`
- Modify: `backend/tests/test_schema_contracts.py`

**Interfaces:**
- Consumes: Alembic head `0009`; existing `User`, `ReferenceStandard`, `ReferenceStandardVersion` models.
- Produces: `StandardDocument`; `ReferenceStandardVersion.standard_document_id`; `ReferenceStandardVersion.standard_document`; `StandardDocument.version`.
- Produces database constraints: `uq_standard_documents_content_hash`, `uq_reference_standard_versions_standard_document`, `fk_standard_documents_uploaded_by`, `fk_reference_standard_versions_standard_document`.

- [ ] **Step 1: Write failing migration and model contract tests**

Add assertions equivalent to:

```python
def test_dedicated_standard_documents_revision_follows_0009():
    migration = _load_revision(
        "0010_dedicated_standard_documents.py",
        "migration_0010",
    )
    assert migration.revision == "0010"
    assert migration.down_revision == "0009"


def test_standard_document_model_and_one_to_one_version_link():
    from app.db.models import ReferenceStandardVersion, StandardDocument

    columns = StandardDocument.__table__.columns
    assert {
        "id", "title", "filename", "file_path", "file_type", "file_size",
        "content_hash", "uploaded_by", "created_at",
    }.issubset(columns.keys())
    assert columns["content_hash"].nullable is False
    assert "document_id" not in ReferenceStandardVersion.__table__.columns
    assert ReferenceStandardVersion.__table__.columns["standard_document_id"].nullable is False
    assert any(
        constraint.name == "uq_reference_standard_versions_standard_document"
        for constraint in ReferenceStandardVersion.__table__.constraints
    )
```

Extend `test_schema_contracts.py` to require the literal tables/columns `standard_documents`, `content_hash`, `standard_document_id`, and the named unique constraint in `database/schema.sql`.

- [ ] **Step 2: Run the data contracts and confirm red state**

Run from `backend/`:

```powershell
pytest tests/test_alembic_contracts.py tests/test_standard_models.py tests/test_schema_contracts.py -q
```

Expected: FAIL because `0010_dedicated_standard_documents.py` and `StandardDocument` do not exist and `ReferenceStandardVersion` still exposes `document_id`.

- [ ] **Step 3: Implement the guarded Alembic revision**

Create the revision with explicit protection and named constraints:

```python
"""separate standard documents from the knowledge document domain"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _row_count(table_name: str) -> int:
    bind = op.get_bind()
    return int(bind.execute(sa.text(f"SELECT count(*) FROM {table_name}")).scalar_one())


def upgrade() -> None:
    if _row_count("reference_standard_versions"):
        raise RuntimeError(
            "0010 requires reference_standard_versions to be empty; "
            "manual review is required and no rows were changed"
        )

    op.create_table(
        "standard_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=500)),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("file_path", sa.String(length=1000), nullable=False),
        sa.Column("file_type", sa.String(length=50), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("content_hash", name="uq_standard_documents_content_hash"),
    )
    op.create_foreign_key(
        "fk_standard_documents_uploaded_by",
        "standard_documents",
        "users",
        ["uploaded_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint(
        "reference_standard_versions_document_id_fkey",
        "reference_standard_versions",
        type_="foreignkey",
    )
    op.drop_column("reference_standard_versions", "document_id")
    op.add_column(
        "reference_standard_versions",
        sa.Column("standard_document_id", sa.Integer(), nullable=False),
    )
    op.create_unique_constraint(
        "uq_reference_standard_versions_standard_document",
        "reference_standard_versions",
        ["standard_document_id"],
    )
    op.create_foreign_key(
        "fk_reference_standard_versions_standard_document",
        "reference_standard_versions",
        "standard_documents",
        ["standard_document_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    if _row_count("reference_standard_versions") or _row_count("standard_documents"):
        raise RuntimeError(
            "0010 downgrade requires reference_standard_versions and "
            "standard_documents to be empty; no rows were changed"
        )

    op.drop_constraint(
        "fk_reference_standard_versions_standard_document",
        "reference_standard_versions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_reference_standard_versions_standard_document",
        "reference_standard_versions",
        type_="unique",
    )
    op.drop_column("reference_standard_versions", "standard_document_id")
    op.add_column(
        "reference_standard_versions",
        sa.Column("document_id", sa.Integer(), nullable=False),
    )
    op.create_foreign_key(
        "reference_standard_versions_document_id_fkey",
        "reference_standard_versions",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "fk_standard_documents_uploaded_by",
        "standard_documents",
        type_="foreignkey",
    )
    op.drop_table("standard_documents")
```

Do not use dynamic table names beyond the two fixed internal calls above. Both calls are developer-owned constants, not request input.

- [ ] **Step 4: Implement the SQLAlchemy entities**

Add `StandardDocument` next to `Document`, and change the version relationship:

```python
class StandardDocument(Base):
    __tablename__ = "standard_documents"
    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_standard_documents_content_hash"),
    )

    id = Column(Integer, primary_key=True)
    title = Column(String(500))
    filename = Column(String(500), nullable=False)
    file_path = Column(String(1000), nullable=False)
    file_type = Column(String(50), nullable=False)
    file_size = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False)
    uploaded_by = Column(
        Integer,
        ForeignKey("users.id", name="fk_standard_documents_uploaded_by", ondelete="SET NULL"),
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    version = relationship(
        "ReferenceStandardVersion",
        back_populates="standard_document",
        uselist=False,
    )


class ReferenceStandardVersion(Base):
    __tablename__ = "reference_standard_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'review', 'approved', 'retired')",
            name="ck_reference_standard_versions_status",
        ),
        UniqueConstraint(
            "standard_document_id",
            name="uq_reference_standard_versions_standard_document",
        ),
        Index("ix_reference_standard_versions_standard_status", "standard_id", "status"),
    )

    standard_document_id = Column(
        Integer,
        ForeignKey(
            "standard_documents.id",
            name="fk_reference_standard_versions_standard_document",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    standard_document = relationship("StandardDocument", back_populates="version")
```

Remove only `ReferenceStandardVersion.document_id` and `ReferenceStandardVersion.document`. Do not alter `ReferenceRange.document_id`; it belongs to the legacy compatibility table and may remain nullable for existing ordinary-document projections.

- [ ] **Step 5: Synchronize `database/schema.sql` to the terminal schema**

Add the complete terminal DDL for the standard rules layer, which is currently absent from the reference file. At minimum the dependency order must be:

```sql
CREATE TABLE IF NOT EXISTS reference_standards (
    id SERIAL PRIMARY KEY,
    disease_id INTEGER NOT NULL REFERENCES diseases(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    current_version_id INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_reference_standards_disease UNIQUE (disease_id)
);
CREATE TABLE IF NOT EXISTS standard_documents (
    id SERIAL PRIMARY KEY,
    title VARCHAR(500),
    filename VARCHAR(500) NOT NULL,
    file_path VARCHAR(1000) NOT NULL,
    file_type VARCHAR(50) NOT NULL,
    file_size INTEGER NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    uploaded_by INTEGER,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_standard_documents_content_hash UNIQUE (content_hash),
    CONSTRAINT fk_standard_documents_uploaded_by
        FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS reference_standard_versions (
    id SERIAL PRIMARY KEY,
    standard_id INTEGER NOT NULL REFERENCES reference_standards(id) ON DELETE CASCADE,
    standard_document_id INTEGER NOT NULL,
    version_label VARCHAR(100) NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    parser_version VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    supersedes_version_id INTEGER REFERENCES reference_standard_versions(id) ON DELETE SET NULL,
    effective_from TIMESTAMP WITH TIME ZONE,
    retired_at TIMESTAMP WITH TIME ZONE,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    approved_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    approved_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT ck_reference_standard_versions_status
        CHECK (status IN ('draft', 'review', 'approved', 'retired')),
    CONSTRAINT uq_reference_standard_versions_standard_document
        UNIQUE (standard_document_id),
    CONSTRAINT fk_reference_standard_versions_standard_document
        FOREIGN KEY (standard_document_id) REFERENCES standard_documents(id) ON DELETE RESTRICT
);
```

Complete that section with the remaining terminal DDL, preserving dependency order:

```sql
ALTER TABLE reference_standards
    ADD CONSTRAINT fk_reference_standards_current_version
    FOREIGN KEY (current_version_id)
    REFERENCES reference_standard_versions(id)
    ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_reference_standard_versions_standard_status
ON reference_standard_versions(standard_id, status);

CREATE TABLE IF NOT EXISTS standard_indicators (
    id SERIAL PRIMARY KEY,
    canonical_key VARCHAR(200) NOT NULL,
    name_en VARCHAR(200) NOT NULL,
    name_cn VARCHAR(200),
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    domain VARCHAR(100),
    specimen_or_modality VARCHAR(100),
    data_type VARCHAR(50) NOT NULL DEFAULT 'qualitative',
    scale_or_method VARCHAR(200),
    default_unit VARCHAR(50),
    clinical_dimension VARCHAR(100),
    allows_numeric_comparison BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_standard_indicators_canonical_key UNIQUE (canonical_key)
);

CREATE TABLE IF NOT EXISTS standard_segments (
    id SERIAL PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES reference_standard_versions(id) ON DELETE CASCADE,
    section_title VARCHAR(300),
    paragraph_index INTEGER,
    table_index INTEGER,
    row_index INTEGER,
    column_index INTEGER,
    raw_text TEXT NOT NULL,
    segment_type VARCHAR(50) NOT NULL,
    parse_status VARCHAR(50) NOT NULL DEFAULT 'pending',
    review_status VARCHAR(50) NOT NULL DEFAULT 'pending',
    source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_standard_segments_version_location
ON standard_segments(version_id, table_index, row_index);

CREATE TABLE IF NOT EXISTS standard_parse_candidates (
    id SERIAL PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES reference_standard_versions(id) ON DELETE CASCADE,
    segment_id INTEGER NOT NULL REFERENCES standard_segments(id) ON DELETE CASCADE,
    source_type VARCHAR(50) NOT NULL,
    parser_version VARCHAR(100) NOT NULL,
    model_name VARCHAR(100),
    prompt_version VARCHAR(100),
    raw_output TEXT,
    candidate_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence DOUBLE PRECISION,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_standard_parse_candidates_segment
ON standard_parse_candidates(segment_id);

CREATE TABLE IF NOT EXISTS standard_rules (
    id SERIAL PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES reference_standard_versions(id) ON DELETE CASCADE,
    indicator_id INTEGER REFERENCES standard_indicators(id) ON DELETE SET NULL,
    source_segment_id INTEGER REFERENCES standard_segments(id) ON DELETE SET NULL,
    rule_type VARCHAR(50) NOT NULL,
    comparator VARCHAR(5),
    lower DOUBLE PRECISION,
    upper DOUBLE PRECISION,
    lower_inclusive BOOLEAN NOT NULL DEFAULT TRUE,
    upper_inclusive BOOLEAN NOT NULL DEFAULT TRUE,
    unit VARCHAR(50),
    sex VARCHAR(10),
    category VARCHAR(100),
    applicability JSONB NOT NULL DEFAULT '{}'::jsonb,
    target_state_type VARCHAR(50) NOT NULL,
    target_state_value VARCHAR(200),
    clinical_dimension VARCHAR(100),
    evidence_type VARCHAR(100),
    machine_actionability VARCHAR(50) NOT NULL DEFAULT 'evidence-only',
    interpretation TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    conflict_group VARCHAR(100),
    framework VARCHAR(100),
    biomarker_axis VARCHAR(10),
    biomarker_state VARCHAR(100),
    stage VARCHAR(100),
    clinical_function TEXT,
    conditions JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_standard_rules_version_indicator
ON standard_rules(version_id, indicator_id);

CREATE INDEX IF NOT EXISTS ix_standard_rules_conflict_group
ON standard_rules(version_id, conflict_group);

CREATE TABLE IF NOT EXISTS standard_rule_conditions (
    id SERIAL PRIMARY KEY,
    rule_id INTEGER NOT NULL REFERENCES standard_rules(id) ON DELETE CASCADE,
    parent_id INTEGER REFERENCES standard_rule_conditions(id) ON DELETE CASCADE,
    node_type VARCHAR(50) NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS ix_standard_rule_conditions_rule_parent
ON standard_rule_conditions(rule_id, parent_id);

CREATE TABLE IF NOT EXISTS standard_change_logs (
    id SERIAL PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES reference_standard_versions(id) ON DELETE CASCADE,
    entity_type VARCHAR(50) NOT NULL,
    entity_id INTEGER NOT NULL,
    action VARCHAR(50) NOT NULL,
    before_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    after_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT NOT NULL,
    actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_standard_change_logs_entity
ON standard_change_logs(entity_type, entity_id);

ALTER TABLE reference_ranges
    ADD COLUMN IF NOT EXISTS standard_id INTEGER REFERENCES reference_standards(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS standard_version_id INTEGER REFERENCES reference_standard_versions(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS standard_rule_id INTEGER REFERENCES standard_rules(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS applicability_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS is_current_projection BOOLEAN NOT NULL DEFAULT FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS uq_reference_ranges_current_projection
ON reference_ranges(standard_id, indicator_name, sex, category, applicability_hash)
WHERE is_current_projection IS TRUE;
```

Do not add executable migration logic to `schema.sql`; it remains a clean-install reference.

- [ ] **Step 6: Run the focused contracts in green state**

Run:

```powershell
pytest tests/test_alembic_contracts.py tests/test_standard_models.py tests/test_schema_contracts.py -q
```

Expected: PASS with revision chain `0009 -> 0010`, no `document_id` on `ReferenceStandardVersion`, and terminal SQL containing the dedicated table and unique link.

- [ ] **Step 7: Commit the data layer**

```powershell
git add backend/alembic/versions/0010_dedicated_standard_documents.py backend/app/db/models.py database/schema.sql backend/tests/test_alembic_contracts.py backend/tests/test_standard_models.py backend/tests/test_schema_contracts.py
$commitBody = "AI-Agent: Codex`nAI-Client: Codex-Desktop`nTask-ID: standard-documents-001"
git -c user.name="Codex" -c user.email="codex@local" commit -m "feat(db): add dedicated standard documents" -m $commitBody
```

---

### Task 2: Add Standard Document Storage and Admin APIs

**Files:**
- Create: `backend/app/schemas/standard_document.py`
- Create: `backend/app/services/standard_document_storage.py`
- Create: `backend/app/api/admin_standard_documents.py`
- Create: `backend/tests/test_admin_standard_documents_api.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas/__init__.py`

**Interfaces:**
- Consumes: `file_storage.save_upload(file) -> str`, `settings.MAX_UPLOAD_SIZE_MB`, `StandardDocument`, `require_admin`.
- Produces: `validate_standard_docx(filename: str | None) -> None`, `hash_standard_file(path: str) -> str`, `save_standard_upload(file: UploadFile) -> StoredStandardFile`, `delete_standard_file(path: str) -> None`.
- Produces effective HTTP endpoints: `POST /api/v1/admin/standard-documents/upload`, `GET /api/v1/admin/standard-documents?available_only=false`, `DELETE /api/v1/admin/standard-documents/{document_id}`.

- [ ] **Step 1: Write failing schema, router and storage tests**

Cover these cases in `test_admin_standard_documents_api.py` using `tmp_path`, `UploadFile`, monkeypatch and small fake sessions:

```python
def test_standard_document_router_exposes_admin_only_endpoints():
    from app.api.admin_standard_documents import router

    paths = {(route.path, next(iter(route.methods))) for route in router.routes}
    assert any(path == "/admin/standard-documents/upload" for path, _ in paths)
    assert any(path == "/admin/standard-documents" for path, _ in paths)
    assert any(path == "/admin/standard-documents/{document_id}" for path, _ in paths)


def test_standard_upload_rejects_non_docx_before_saving(monkeypatch):
    saved = []
    monkeypatch.setattr(
        "app.services.file_storage.save_upload",
        lambda file: saved.append(file) or "unused",
    )
    with pytest.raises(ValueError, match="DOCX"):
        save_standard_upload(_upload_file("standard.pdf", b"pdf"))
    assert saved == []


def test_standard_document_out_derives_unlocked_state():
    output = standard_document_to_out(
        SimpleNamespace(
            id=1,
            title="AD标准",
            filename="ad.docx",
            file_path="x",
            file_type="docx",
            file_size=4,
            content_hash="a" * 64,
            uploaded_by=7,
            created_at=None,
            version=None,
        )
    )
    assert output.is_locked is False
    assert output.version_id is None
```

Also test SHA-256, title fallback, duplicate hash cleanup, `available_only`, 409 on linked deletion, strict disk deletion failure rollback, successful unlinked deletion, and all routes using `require_admin`.

- [ ] **Step 2: Run the new test file and confirm red state**

Run:

```powershell
pytest tests/test_admin_standard_documents_api.py -q
```

Expected: FAIL because the schema, service and router modules do not exist.

- [ ] **Step 3: Implement the standard document response schema**

```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class StandardDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None = None
    filename: str
    file_type: str
    file_size: int
    content_hash: str
    uploaded_by: int | None = None
    created_at: datetime | None = None
    is_locked: bool
    standard_id: int | None = None
    standard_name: str | None = None
    version_id: int | None = None
    version_label: str | None = None
```

Do not expose `file_path` to the browser.

- [ ] **Step 4: Implement the focused storage wrapper**

```python
from dataclasses import dataclass
import hashlib
from pathlib import Path

from fastapi import UploadFile

from app.services import file_storage


@dataclass(frozen=True)
class StoredStandardFile:
    path: str
    file_type: str
    file_size: int
    content_hash: str


def validate_standard_docx(filename: str | None) -> None:
    if not filename or Path(filename).suffix.lower() != ".docx":
        raise ValueError("标准源文件只支持 DOCX")


def hash_standard_file(path: str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save_standard_upload(file: UploadFile) -> StoredStandardFile:
    validate_standard_docx(file.filename)
    path = file_storage.save_upload(file)
    return StoredStandardFile(
        path=path,
        file_type="docx",
        file_size=file_storage.get_file_size(path),
        content_hash=hash_standard_file(path),
    )


def delete_standard_file(path: str) -> None:
    target = Path(path)
    if target.exists():
        target.unlink()
```

Do not change `file_storage.delete_upload`; the strict semantics belong only to standard documents.

- [ ] **Step 5: Implement upload/list/delete router behavior**

Use this response mapper and transaction shape:

```python
def standard_document_to_out(document: StandardDocument) -> StandardDocumentOut:
    version = document.version
    standard = version.standard if version else None
    return StandardDocumentOut(
        id=document.id,
        title=document.title,
        filename=document.filename,
        file_type=document.file_type,
        file_size=document.file_size,
        content_hash=document.content_hash,
        uploaded_by=document.uploaded_by,
        created_at=document.created_at,
        is_locked=version is not None,
        standard_id=getattr(standard, "id", None),
        standard_name=getattr(standard, "name", None),
        version_id=getattr(version, "id", None),
        version_label=getattr(version, "version_label", None),
    )
```

`upload_standard_document()` must return 201, validate `.docx`, save, calculate the hash, reject existing hash with 409, persist `uploaded_by`, normalize `file_type="docx"`, and remove the newly saved file on duplicate or database failure. `list_standard_documents()` must eager-load `version.standard`, order newest first, and apply `StandardDocument.version == None` when `available_only=true`. `delete_standard_document()` must return 409 when linked; for an unlinked row call `db.delete(document)`, `db.flush()`, then strict file deletion, commit only after deletion succeeds, and rollback on any failure.

Catch `IntegrityError` around the unique hash commit, rollback, clean the new file and return 409 without exposing SQL text. Convert extension errors to 422 and size errors from the existing save helper to 400.

- [ ] **Step 6: Register the router without changing ordinary routes**

Add the import and registration only:

```python
from app.api import admin_standard_documents

app.include_router(admin_standard_documents.router, prefix="/api/v1")
```

Keep `admin.router` and `admin_standards.router` registrations unchanged.

- [ ] **Step 7: Run focused API tests and ordinary document regression tests**

Run:

```powershell
pytest tests/test_admin_standard_documents_api.py tests/test_document_indexing.py tests/test_source_access.py -q
```

Expected: PASS. The regression files demonstrate that the new standard router did not alter ordinary document indexing or access scope.

- [ ] **Step 8: Commit standard document APIs**

```powershell
git add backend/app/schemas/standard_document.py backend/app/services/standard_document_storage.py backend/app/api/admin_standard_documents.py backend/app/main.py backend/app/schemas/__init__.py backend/tests/test_admin_standard_documents_api.py
$commitBody = "AI-Agent: Codex`nAI-Client: Codex-Desktop`nTask-ID: standard-documents-001"
git -c user.name="Codex" -c user.email="codex@local" commit -m "feat(api): add standard document library" -m $commitBody
```

---

### Task 3: Adapt Standard Collections, Versions and Parsing

**Files:**
- Modify: `backend/app/schemas/standard.py`
- Modify: `backend/app/api/admin_standards.py`
- Modify: `backend/app/services/standard_lifecycle.py`
- Modify: `backend/tests/test_admin_standards_api.py`
- Modify: `backend/tests/test_standard_lifecycle.py`

**Interfaces:**
- Consumes: `StandardDocument`, `StandardDocument.content_hash`, `ReferenceStandardVersion.standard_document`.
- Produces: `StandardCreate(disease_id: int)`, `StandardVersionCreate(standard_document_id: int, version_label: str, parser_version: str = "v1")`, `StandardVersionOut.standard_document_id`.
- Produces: `DELETE /api/v1/admin/reference-standard-versions/{version_id}` returning HTTP 204 for `draft`/`review`.
- Produces: `seed_standard_draft(db, disease_id: int, standard_document_id: int, version_label: str, *, admin_id: int | None = None, parser_version: str = "v1") -> ReferenceStandardVersion`.

- [ ] **Step 1: Write failing request and lifecycle tests**

Add contracts:

```python
def test_standard_create_accepts_only_disease_id():
    payload = StandardCreate(disease_id=2)
    assert payload.model_dump() == {"disease_id": 2}
    assert "name" not in StandardCreate.model_fields


def test_standard_version_contract_uses_standard_document_id():
    payload = StandardVersionCreate(
        standard_document_id=9,
        version_label="AD-2026-08",
    )
    assert payload.standard_document_id == 9
    assert "document_id" not in StandardVersionOut.model_fields


def test_version_delete_route_is_registered():
    from app.api.admin_standards import router

    route = next(
        route for route in router.routes
        if route.path == "/admin/reference-standard-versions/{version_id}"
        and "DELETE" in route.methods
    )
    assert route.status_code == 204
```

Add behavior tests for disease 404, auto-name, disease conflict 409, missing/locked/missing-file standard document, unique-constraint `IntegrityError` mapped to 409, successful draft creation, draft/review deletion, approved/retired deletion 409, and document unlock after deletion. Add a parse regression in which a deterministic candidate is present and the LLM adapter is not referenced from the deterministic branch.

- [ ] **Step 2: Run the standard API/lifecycle tests and confirm red state**

Run:

```powershell
pytest tests/test_admin_standards_api.py tests/test_standard_lifecycle.py -q
```

Expected: FAIL because schemas still require `name`/`document_id`, the API queries `Document`, and no delete route exists.

- [ ] **Step 3: Change the Pydantic contracts**

Replace the affected classes with:

```python
class StandardCreate(BaseModel):
    disease_id: int


class StandardVersionCreate(BaseModel):
    standard_document_id: int
    version_label: str = Field(..., min_length=1, max_length=100)
    parser_version: str = Field("v1", min_length=1, max_length=100)

    @field_validator("version_label")
    @classmethod
    def strip_version_label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("版本标签不能为空")
        return value


class StandardVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    standard_id: int
    standard_document_id: int
    version_label: str
    content_hash: str
    parser_version: str
    status: str
    supersedes_version_id: int | None = None
    effective_from: datetime | None = None
    retired_at: datetime | None = None
    created_by: int | None = None
    approved_by: int | None = None
    approved_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
```

- [ ] **Step 4: Make standard creation disease-driven**

In `create_standard()` query `Disease` first, return 404 when missing, reject an existing collection with 409, and construct:

```python
standard = ReferenceStandard(
    disease_id=disease.id,
    name=f"{disease.name}标准",
)
```

Catch the named disease unique-constraint race as 409 after rollback. Do not accept `name` or `description` from this endpoint.

- [ ] **Step 5: Make version creation consume and lock `StandardDocument`**

The handler must perform these checks in order:

```python
standard = db.query(ReferenceStandard).filter(ReferenceStandard.id == standard_id).first()
if standard is None:
    raise HTTPException(status_code=404, detail="标准集合不存在")

document = db.query(StandardDocument).filter(
    StandardDocument.id == payload.standard_document_id
).first()
if document is None:
    raise HTTPException(status_code=404, detail="标准文档不存在")
if document.file_type != "docx":
    raise HTTPException(status_code=422, detail="标准源文件只支持 DOCX")
if not Path(document.file_path).is_file():
    raise HTTPException(status_code=400, detail="标准文件不存在")
if document.version is not None:
    raise HTTPException(status_code=409, detail="标准文档已关联版本")

version = ReferenceStandardVersion(
    standard_id=standard.id,
    standard_document_id=document.id,
    version_label=payload.version_label,
    content_hash=document.content_hash,
    parser_version=payload.parser_version,
    created_by=getattr(admin, "id", None),
    supersedes_version_id=standard.current_version_id,
)
```

On the unique `standard_document_id` race, rollback and return 409. Keep `content_hash` on the version as an immutable snapshot; do not reread the file to create another hash.

- [ ] **Step 6: Adapt parsing and fix the deterministic-candidate branch regression**

Replace `version.document` with `version.standard_document`. Before parsing, validate normalized type and `Path(file_path).is_file()`. Within each segment, compute deterministic candidates once:

```python
segment_candidates = [
    item for item in parsed.rule_candidates if item.segment == segment
]
for candidate in segment_candidates:
    db.add(StandardParseCandidate(
        version_id=version.id,
        segment_id=db_segment.id,
        source_type="deterministic",
        parser_version=version.parser_version,
        candidate_json={
            "indicator_name": candidate.indicator_name,
            "rule_type": candidate.rule_type,
            "target_state_type": candidate.target_state_type,
            "target_state_value": candidate.target_state_value,
            "machine_actionability": candidate.machine_actionability,
            "evidence_type": candidate.evidence_type,
            "applicability": candidate.applicability,
            "interpretation": candidate.interpretation,
            "numeric": candidate.numeric.__dict__ if candidate.numeric else None,
        },
        status="pending",
        status="pending",
    ))

if not segment_candidates:
    llm_payload = build_llm_candidate(
        segment.raw_text,
        {
            "section_title": segment.section_title,
            "table_index": segment.table_index,
        },
        LLM_CANDIDATE_ADAPTER,
    )
    raw_output = llm_payload.pop("_raw_output", None) if llm_payload else None
    model_name = llm_payload.pop("_model_name", None) if llm_payload else None
    db.add(StandardParseCandidate(
        version_id=version.id,
        segment_id=db_segment.id,
        source_type="llm",
        parser_version=version.parser_version,
        model_name=model_name,
        raw_output=raw_output,
        candidate_json=llm_payload or {},
        status="pending" if llm_payload else "failed",
    ))
```

This removes the current read of `llm_payload` before assignment in the deterministic branch. Preserve the existing candidate payload fields and LLM success/failure persistence semantics.

- [ ] **Step 7: Add protected version deletion**

```python
@router.delete(
    "/admin/reference-standard-versions/{version_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_version(
    version_id: int,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    version = _version_or_404(db, version_id)
    if version.status not in {"draft", "review"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已批准或已退役版本不可删除",
        )
    db.delete(version)
    db.commit()
    return None
```

Rely on existing ORM/DB cascades for segments, candidates, rules, conditions and change logs. Never delete `version.standard_document`; the unique link disappears and the document becomes available.

- [ ] **Step 8: Adapt `seed_standard_draft()` to the new identifier**

Query `StandardDocument`, validate its normalized type and path, use its stored hash, return the existing associated version only when it belongs to the same disease standard, and raise `ValueError("标准文档已关联其他版本")` for a different association. New versions must set `standard_document_id=document.id`; remove all imports and queries of `Document` from this function.

- [ ] **Step 9: Run standard lifecycle and parser regressions**

Run:

```powershell
pytest tests/test_admin_standards_api.py tests/test_standard_lifecycle.py tests/test_standard_parser.py tests/test_standard_llm_adapter.py tests/test_standard_validation.py tests/test_standard_resolver.py -q
```

Expected: PASS; parse tests do not call the external DeepSeek API.

- [ ] **Step 10: Commit the standard lifecycle adaptation**

```powershell
git add backend/app/schemas/standard.py backend/app/api/admin_standards.py backend/app/services/standard_lifecycle.py backend/tests/test_admin_standards_api.py backend/tests/test_standard_lifecycle.py
$commitBody = "AI-Agent: Codex`nAI-Client: Codex-Desktop`nTask-ID: standard-documents-001"
git -c user.name="Codex" -c user.email="codex@local" commit -m "feat(standards): bind versions to standard documents" -m $commitBody
```

---

### Task 4: Adapt the Draft Seeding Script

**Files:**
- Modify: `scripts/seed_standard_drafts.py`
- Delete: `scripts/upload_standards.py`
- Modify: `backend/tests/test_seed_standard_drafts.py`

**Interfaces:**
- Consumes: explicit `Path` values from `--ad` and `--fatty-liver`; `StandardDocument`; Task 3 `seed_standard_draft()` signature.
- Produces: `_standard_document(db, path: Path, admin_id: int) -> StandardDocument`; unchanged CLI `python scripts/seed_standard_drafts.py --ad PATH --fatty-liver PATH --admin-id ID`.

- [ ] **Step 1: Write failing script idempotency tests**

Update fixtures to return `StandardDocument`, and add source contracts:

```python
def test_seed_script_uses_standard_documents_not_knowledge_documents():
    source = Path(__file__).parents[2].joinpath(
        "scripts/seed_standard_drafts.py"
    ).read_text(encoding="utf-8")
    assert "from app.db.models import StandardDocument" in source
    assert "from app.db.models import Document" not in source
    assert "access_scope" not in source
    assert not Path(__file__).parents[2].joinpath(
        "scripts/upload_standards.py"
    ).exists()


def test_seed_draft_is_idempotent_for_same_standard_document(tmp_path):
    # Arrange one StandardDocument with a stable content_hash.
    # Call seed_standard_draft twice and assert the same version id is returned.
```

Also assert `_standard_document()` rejects non-DOCX and missing files, hashes content once, reuses a row with the same hash, and records `uploaded_by=admin_id`.

- [ ] **Step 2: Run the script tests and confirm red state**

Run from `backend/`:

```powershell
pytest tests/test_seed_standard_drafts.py -q
```

Expected: FAIL because the script imports and creates ordinary `Document` rows and passes `document.id`.

- [ ] **Step 3: Implement path import into `StandardDocument`**

Replace `_document()` with:

```python
def _standard_document(db, path: Path, admin_id: int) -> StandardDocument:
    if path.suffix.lower() != ".docx":
        raise ValueError(f"标准源文件只支持 DOCX：{path}")
    if not path.is_file():
        raise ValueError(f"标准文件不存在：{path}")
    digest = hash_standard_file(str(path))
    item = db.query(StandardDocument).filter(
        StandardDocument.content_hash == digest
    ).first()
    if item is None:
        item = StandardDocument(
            title=path.name,
            filename=path.name,
            file_path=str(path),
            file_type="docx",
            file_size=path.stat().st_size,
            content_hash=digest,
            uploaded_by=admin_id,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
    return item
```

The CLI then calls `seed_standard_draft(db, disease.id, document.id, label, admin_id=args.admin_id)`. This script imports explicit operator-supplied paths for controlled initialization; the web upload API remains the normal managed-file path. Delete `scripts/upload_standards.py`: it hard-codes a local account/path and invokes the obsolete ordinary-document upload/chunk/index/reference-range flow, which conflicts with the new domain boundary and duplicates the maintained seed CLI.

- [ ] **Step 4: Run script and lifecycle tests**

Run:

```powershell
pytest tests/test_seed_standard_drafts.py tests/test_standard_lifecycle.py -q
```

Expected: PASS with no `Document` creation.

- [ ] **Step 5: Commit the script adaptation**

```powershell
git add scripts/seed_standard_drafts.py scripts/upload_standards.py backend/tests/test_seed_standard_drafts.py
$commitBody = "AI-Agent: Codex`nAI-Client: Codex-Desktop`nTask-ID: standard-documents-001"
git -c user.name="Codex" -c user.email="codex@local" commit -m "fix(scripts): seed dedicated standard documents" -m $commitBody
```

---

### Task 5: Replace the Frontend Standard API Contract

**Files:**
- Modify: `frontend/src/api/adminStandards.ts`
- Modify: `frontend/tests/standard-management-ui-contract.test.mjs`

**Interfaces:**
- Consumes: backend endpoints from Tasks 2 and 3; existing `request` instance whose `baseURL` is `/api`.
- Produces: `StandardDocument`, `uploadStandardDocument`, `listStandardDocuments`, `deleteStandardDocument`, `deleteVersion`.
- Produces changed calls: `createStandard({ disease_id })`, `createVersion(standardId, { standard_document_id, version_label, parser_version? })`.

- [ ] **Step 1: Add failing API-source contract tests first**

Replace the old assertion that requires ordinary `uploadDocument` and `accessScope` with:

```javascript
test('admin standards API exposes dedicated standard document contracts', async () => {
  const api = await readFile(
    new URL('../src/api/adminStandards.ts', import.meta.url),
    'utf8',
  )

  assert.match(api, /uploadStandardDocument/)
  assert.match(api, /listStandardDocuments/)
  assert.match(api, /deleteStandardDocument/)
  assert.match(api, /deleteVersion/)
  assert.match(api, /disease_id: number/)
  assert.match(api, /standard_document_id/)
  assert.doesNotMatch(api, /document_id: number/)
  assert.match(api, /available_only/)
})
```

Also assert that `createStandard` accepts a payload typed only as `{ disease_id: number }` and `createVersion` accepts `standard_document_id`.

- [ ] **Step 2: Run the frontend contract and confirm red state**

Run from `frontend/`:

```powershell
node --test tests/standard-management-ui-contract.test.mjs
```

Expected: FAIL because the API lacks dedicated document methods and still exposes `document_id`.

- [ ] **Step 3: Implement dedicated TypeScript types and calls**

Add:

```typescript
export interface StandardDocument {
  id: number
  title?: string | null
  filename: string
  file_type: 'docx'
  file_size: number
  content_hash: string
  uploaded_by?: number | null
  created_at?: string | null
  is_locked: boolean
  standard_id?: number | null
  standard_name?: string | null
  version_id?: number | null
  version_label?: string | null
}

export interface StandardVersion {
  id: number
  standard_id: number
  standard_document_id: number
  version_label: string
  status: 'draft' | 'review' | 'approved' | 'retired'
  content_hash: string
  parser_version: string
  effective_from?: string | null
}

export const uploadStandardDocument = (
  file: File,
  title?: string,
): Promise<StandardDocument> => {
  const formData = new FormData()
  formData.append('file', file)
  if (title) formData.append('title', title)
  return request.post('/v1/admin/standard-documents/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export const listStandardDocuments = (
  availableOnly = false,
): Promise<StandardDocument[]> => request.get(
  '/v1/admin/standard-documents',
  { params: { available_only: availableOnly } },
)

export const deleteStandardDocument = (documentId: number): Promise<void> =>
  request.delete(`/v1/admin/standard-documents/${documentId}`)

export const createStandard = (payload: { disease_id: number }): Promise<Standard> =>
  request.post('/v1/admin/reference-standards', payload)

export const createVersion = (
  standardId: number,
  payload: {
    standard_document_id: number
    version_label: string
    parser_version?: string
  },
): Promise<StandardVersion> => request.post(
  `/v1/admin/reference-standards/${standardId}/versions`,
  payload,
)

export const deleteVersion = (versionId: number): Promise<void> =>
  request.delete(`/v1/admin/reference-standard-versions/${versionId}`)
```

Keep all existing parse, review, approve, retire, segment, rule, candidate and history calls unchanged.

- [ ] **Step 4: Run the frontend contract and type/build checks**

Run:

```powershell
node --test tests/standard-management-ui-contract.test.mjs
npm run build
```

Expected: the API-source contract PASS and the production build PASS. The existing page still uses the ordinary document API until Task 6, but no Task 6 page contract is introduced in this task.

- [ ] **Step 5: Commit the API contract**

```powershell
git add frontend/src/api/adminStandards.ts frontend/tests/standard-management-ui-contract.test.mjs
$commitBody = "AI-Agent: Codex`nAI-Client: Codex-Desktop`nTask-ID: standard-documents-001"
git -c user.name="Codex" -c user.email="codex@local" commit -m "feat(frontend): add standard document API contract" -m $commitBody
```

---

### Task 6: Implement the Two-Stage Standard Management Workflow

**Files:**
- Modify: `frontend/src/components/StandardManagementView.vue`
- Modify: `frontend/tests/standard-management-ui-contract.test.mjs`

**Interfaces:**
- Consumes: Task 5 API methods; `listDiseases(): Promise<Disease[]>` from `frontend/src/api/operator.ts`; Element Plus `ElMessageBox`; Element Plus `Collection`, `Delete`, `Plus`, `Upload` icons.
- Produces: standard document library with derived lock state, disease-only collection dialog, available-document version dialog, protected delete actions, unchanged manual parse/review/publish workspace.

- [ ] **Step 1: Add failing UI workflow contracts**

Replace the existing ordinary-upload assertions with a dedicated-page contract, and require all of these observable contracts:

```javascript
assert.match(source, /uploadStandardDocument/)
assert.match(source, /listStandardDocuments/)
assert.doesNotMatch(source, /from '@\/api\/admin'/)
assert.doesNotMatch(source, /uploadDocument/)
assert.match(source, /新建标准集合/)
assert.match(source, /选择疾病/)
assert.doesNotMatch(source, /标准名称.*el-input/)
assert.match(source, /新建版本/)
assert.match(source, /standard_document_id/)
assert.match(source, /可用|已关联/)
assert.match(source, /deleteStandardDocument/)
assert.match(source, /deleteVersion/)
assert.match(source, /ElMessageBox/)
assert.match(source, /parseVersion/)
```

Keep existing lifecycle/evidence-only contracts.

- [ ] **Step 2: Run the UI contract and confirm red state**

Run:

```powershell
node --test tests/standard-management-ui-contract.test.mjs
```

Expected: FAIL because collection/version dialogs and dedicated document APIs are not implemented in the view.

- [ ] **Step 3: Replace ordinary document state and upload flow**

Remove imports from `@/api/admin`. Import the Task 5 standard methods and define:

```typescript
const standardDocuments = ref<StandardDocument[]>([])
const availableDocuments = computed(() =>
  standardDocuments.value.filter(document => !document.is_locked),
)

async function loadStandardDocuments() {
  standardDocuments.value = await listStandardDocuments()
}

async function submitUpload() {
  if (!selectedFile.value) return
  uploading.value = true
  try {
    await uploadStandardDocument(
      selectedFile.value,
      uploadTitle.value.trim() || undefined,
    )
    ElMessage.success('标准文档上传成功')
    selectedFile.value = null
    uploadTitle.value = ''
    uploadRef.value?.clearFiles()
    await loadStandardDocuments()
  } finally {
    uploading.value = false
  }
}
```

Render title/filename, first 12 hash characters, formatted bytes/time, and an Element Plus tag labeled `可用` or `已关联`. For linked documents show `standard_name` and `version_label`; for unlinked documents show a delete icon/button.

- [ ] **Step 4: Add standard collection creation**

Load diseases on mount with existing `listDiseases()`. Derive selectable diseases by excluding IDs already present in `standards`. The dialog contains one `el-select` labeled `选择疾病`; it has no name or description input.

```typescript
async function submitStandard() {
  if (!newStandardDiseaseId.value) return
  const created = await createStandard({ disease_id: newStandardDiseaseId.value })
  standards.value = await listStandards()
  standardDialogVisible.value = false
  newStandardDiseaseId.value = null
  await selectStandard(created)
  ElMessage.success('标准集合已创建')
}
```

Disable the create action when no disease remains available.

- [ ] **Step 5: Add manual version creation**

The dialog contains an available standard document select and a version label input. Opening it refreshes the standard document list; if none are available, disable the action and show `请先上传 DOCX 标准文档`.

```typescript
async function submitVersion() {
  if (!selectedStandard.value || !newVersionDocumentId.value) return
  const created = await createVersion(selectedStandard.value.id, {
    standard_document_id: newVersionDocumentId.value,
    version_label: newVersionLabel.value.trim(),
  })
  versionDialogVisible.value = false
  newVersionDocumentId.value = null
  newVersionLabel.value = ''
  await Promise.all([
    loadStandardDocuments(),
    loadVersions(selectedStandard.value.id),
  ])
  selectedVersionId.value = created.id
  await loadVersionData()
  ElMessage.success('草稿版本已创建，请手动解析')
}
```

Do not call `parseVersion()` here.

- [ ] **Step 6: Add protected document and version deletion**

For an unlinked document, show a confirmation explaining that the source file will be removed. For `draft`/`review`, show a version delete command and this confirmation: `删除后解析片段、候选和规则将一并删除，标准文档会恢复为可用。`

```typescript
async function confirmDeleteVersion() {
  if (!selectedVersion.value) return
  await ElMessageBox.confirm(
    '删除后解析片段、候选和规则将一并删除，标准文档会恢复为可用。',
    '删除标准版本',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
  )
  await deleteVersion(selectedVersion.value.id)
  await Promise.all([
    loadStandardDocuments(),
    selectedStandard.value
      ? loadVersions(selectedStandard.value.id)
      : Promise.resolve(),
  ])
  selectedVersionId.value = null
  clearVersionWorkspace()
  ElMessage.success('标准版本已删除')
}
```

Do not render version deletion for `approved` or `retired`. Backend 409 remains the authority.

- [ ] **Step 7: Preserve and tighten lifecycle refresh behavior**

Split `loadVersions(standardId)` from `selectStandard()` so creation/deletion/lifecycle actions can refresh without clearing unrelated state. After parse, submit review, approve or retire, reload versions, preserve the selected version ID when it still exists, then reload its segments/rules/validation. Keep existing rule editing visible. Candidate review and change-history backend APIs remain unchanged; adding new page panels for them is outside this database-boundary task.

- [ ] **Step 8: Apply design and responsive requirements**

Use existing `--space-*`, `--bg-*`, `--border-*`, `--radius-card`, `--shadow-sm`, `--text-*` and `--color-*` variables. Keep stable action button heights, allow toolbar wrapping, set table columns with minimum widths, and retain the current single-column breakpoint at 900px. Use Element Plus icons instead of custom SVG. Ensure dialogs fit a 390px mobile viewport with `width="min(520px, calc(100vw - 32px))"` or equivalent CSS.

- [ ] **Step 9: Run frontend tests and production build**

Run:

```powershell
node --test tests/*.test.mjs
npm run build
```

Expected: all Node tests PASS; `vue-tsc` and Vite production build complete without errors.

- [ ] **Step 10: Verify the page visually at desktop and mobile sizes**

Start the existing frontend dev server and backend configured for the isolated test database. Inspect `/admin` standard management at 1440x900 and 390x844. Confirm no overlapping text/actions, upload remains first-screen visible, dialogs fit, linked status is readable, and manual parse remains separate from version creation. Capture screenshots for the implementation record; do not commit credentials or database URLs.

- [ ] **Step 11: Commit the UI workflow**

```powershell
git add frontend/src/components/StandardManagementView.vue frontend/tests/standard-management-ui-contract.test.mjs
$commitBody = "AI-Agent: Codex`nAI-Client: Codex-Desktop`nTask-ID: standard-documents-001"
git -c user.name="Codex" -c user.email="codex@local" commit -m "feat(ui): complete standard document workflow" -m $commitBody
```

---

### Task 7: PostgreSQL Migration, Real DOCX and Full Regression Verification

**Files:**
- Modify only if verification exposes a scoped defect: files already owned by Tasks 1-6 and their tests.
- Do not modify: `docs/coordination/ACTIVE_TASKS.md` from the implementation worktree.

**Interfaces:**
- Consumes: process-level `STANDARD_DOCUMENT_TEST_DATABASE_URL` pointing to an explicitly isolated PostgreSQL database; `C:\Users\86182\Downloads\AD标准.docx`; `C:\Users\86182\Downloads\脂肪肝标准.docx`.
- Produces: verified `0009 -> 0010 -> 0009 -> 0010` empty-data migration, verified upgrade/downgrade blockers with data, real two-file workflow evidence, full backend/frontend results, cross-client review handoff.

- [ ] **Step 1: Verify the database target before any migration**

From `backend/`, require the test URL and check its database name without printing credentials:

```powershell
if (-not $env:STANDARD_DOCUMENT_TEST_DATABASE_URL) { throw 'STANDARD_DOCUMENT_TEST_DATABASE_URL is required' }
$testUri = [System.Uri]$env:STANDARD_DOCUMENT_TEST_DATABASE_URL
$testDatabaseName = $testUri.AbsolutePath.TrimStart('/')
if ($testDatabaseName -notmatch 'test') { throw 'Refusing non-test database target' }
$env:DATABASE_URL = $env:STANDARD_DOCUMENT_TEST_DATABASE_URL
alembic current
```

Expected: the printed revision belongs to the isolated database and the database name contains `test`. Stop if either check fails.

- [ ] **Step 2: Verify the empty migration round trip**

Run from `backend/`:

```powershell
alembic upgrade 0009
alembic upgrade 0010
alembic current
alembic downgrade 0009
alembic current
alembic upgrade 0010
alembic current
```

Expected revision sequence: `0010`, `0009`, `0010`, with no data-protection exception because both standard tables are empty.

- [ ] **Step 3: Verify upgrade blocking when old standard versions exist**

Reset only the explicitly checked test database to `0009`, insert the minimal test user/disease/document/standard/version fixture in a transaction, and run:

```powershell
alembic upgrade 0010
```

Expected: non-zero exit with `0010 requires reference_standard_versions to be empty`; confirm the old `document_id` column and fixture row still exist. Remove the fixture from the test database, then upgrade to `0010`.

- [ ] **Step 4: Verify downgrade blocking when new standard data exists**

Create one `standard_documents` test row at `0010`, then run:

```powershell
alembic downgrade 0009
```

Expected: non-zero exit with `0010 downgrade requires reference_standard_versions and standard_documents to be empty`; confirm the row and `standard_document_id` schema remain intact. Remove the test row, complete `downgrade 0009`, then `upgrade 0010`.

- [ ] **Step 5: Run backend focused and full suites**

Run:

```powershell
pytest tests/test_alembic_contracts.py tests/test_standard_models.py tests/test_admin_standard_documents_api.py tests/test_admin_standards_api.py tests/test_standard_lifecycle.py tests/test_seed_standard_drafts.py -q
pytest -q
```

Expected: both commands PASS. Record exact passed/failed/skipped counts.

- [ ] **Step 6: Run frontend full contracts and production build**

From `frontend/`:

```powershell
node --test tests/*.test.mjs
npm run build
```

Expected: all Node tests PASS; TypeScript and Vite build PASS.

- [ ] **Step 7: Exercise both real DOCX files in the isolated database**

Create an admin in the isolated database with `scripts/create_admin.py`, start the backend with the process-scoped test URL, and use the standard management page to perform this exact sequence for both source files:

1. Upload `AD标准.docx` and `脂肪肝标准.docx` through the dedicated upload control.
2. Confirm neither file appears in ordinary document management and both appear as `可用` in standard management.
3. Create the disease-backed standard collections for 阿尔茨海默病 and 脂肪肝; confirm names are generated by the backend.
4. Select one different available document for each collection and create a draft version.
5. Confirm each linked document is `已关联`, cannot be selected for another version and cannot be deleted.
6. Click `解析` manually; confirm segments and candidates retain source locations and no unbound-local error occurs for deterministic candidates.
7. Delete one `draft` version and confirm its document becomes `可用`; recreate the draft and parse again.
8. Drive one version through review and approval, then confirm version deletion and source document deletion are unavailable and backend calls return 409.

Do not write either file or any test row to the formal database.

- [ ] **Step 8: Confirm ordinary-document and longitudinal regressions**

Run the ordinary document, resolver and longitudinal contract groups explicitly:

```powershell
pytest tests/test_document_indexing.py tests/test_source_access.py tests/test_rag_logic.py tests/test_standard_resolver.py tests/test_longitudinal_end_to_end.py tests/test_longitudinal_report_generator.py -q
```

Expected: PASS, demonstrating no regression in upload/index/retrieval, standard resolution, longitudinal prediction or report generation.

- [ ] **Step 9: Run diff and secret checks**

From repository root:

```powershell
git diff --check main...HEAD
rg -n "postgresql://|DEEPSEEK_API_KEY=|JWT_SECRET=" docs/superpowers/plans/2026-08-25-dedicated-standard-documents.md backend frontend scripts
git status --short
```

Expected: `git diff --check` is clean; the secret scan contains no committed credential values; status contains no generated uploads, screenshots with sensitive data, build output or test database dumps.

- [ ] **Step 10: Request cross-client review**

Generate this handoff with actual commit range and verification counts:

```text
请评审任务 standard-documents-001。

实现者：Codex
评审者：Claude Code
分支：codex/standard-documents-001
基线：main
提交：使用 `git log --reverse --format=%H main..HEAD` 输出中的首个和最后一个提交组成范围
方案：docs/superpowers/specs/2026-08-25-dedicated-standard-documents-design.md
实施计划：docs/superpowers/plans/2026-08-25-dedicated-standard-documents.md
登记：docs/coordination/ACTIVE_TASKS.md
验收条件：独立 standard_documents 表；0010 升降级数据保护；标准专用上传/列表/删除；疾病自动命名；文档唯一锁定；draft/review 删除解锁；approved/retired 永久保留；两份真实 DOCX 在隔离数据库完成手动解析；普通文档和纵向链路无回归。
重点检查：0010 约束和阻断逻辑、磁盘与数据库失败一致性、并发唯一冲突到 409、删除级联边界、解析是否只读取 standard_document、前端是否彻底停止调用普通文档 API、普通文档链路是否保持不变。

只输出评审意见，不直接修改实现提交。
```

- [ ] **Step 11: Apply review fixes as new commits and re-run affected plus full checks**

For every valid finding, first add a reproducing test, confirm red, implement the smallest correction, run the affected suite, then run `pytest -q`, `node --test tests/*.test.mjs`, and `npm run build`. Create new commits; do not amend implementation commits.

- [ ] **Step 12: Report completion without pushing or merging**

Report the branch, commit range, changed modules, migration evidence, exact test/build counts, real DOCX results, review result and any residual risk. State `尚未推送` and request explicit push authorization. After push, request a separate merge authorization.

---

## Acceptance Traceability

| Requirement | Implemented and verified by |
| --- | --- |
| Standards no longer use `documents` | Tasks 1, 3, 4, 5, 6 |
| Dedicated upload/list/delete | Task 2, Task 6 |
| Manual document selection creates version | Tasks 3, 5, 6 |
| One document locks to one version | Tasks 1, 3, 7 |
| Disease-derived immutable collection name | Tasks 3, 6 |
| Unlinked document deletion | Tasks 2, 6 |
| Draft/review deletion unlocks document | Tasks 3, 6, 7 |
| Approved/retired retention | Tasks 2, 3, 6, 7 |
| Manual parsing remains separate | Tasks 3, 6, 7 |
| Empty-data migration round trip and data blockers | Tasks 1, 7 |
| Real AD/fatty-liver DOCX acceptance | Task 7 |
| Ordinary documents and longitudinal behavior unchanged | Tasks 2, 7 |
| Cross-client review and owner-controlled integration | Task 7 |
