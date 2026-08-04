# access_scope 文档隔离实现计划（Phase 1）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**所属主计划（文件 A）：** `docs/superpowers/plans/2026-08-03-ai-operator-predictive.md`。本文件是 A 的 **Phase 1（Task 1-3）**，可独立交付。三轮评审的全部意见与处置见 A 的"评审记录"表。

**Goal:** 通过新增 `documents.access_scope` 列实现检索面与读取面的文档访问隔离：聊天端检索只命中 `chat`/`both` 文档，`operator` 文档（如"正常体征参考标准"）永不被聊天端召回，且全文/图片读取入口同样受 scope 约束。为文件 A（AI 操作者预测分析模块）的 Phase 2-5 铺平隔离前提。

**Architecture:** 两个层面隔离：① 检索面——`hybrid_search`/`_vector_search`/`_fulltext_search` 增加 `access_scope` 参数，SQL 加 `business_document.access_scope` 过滤，聊天端 `SurgeryRetriever` 默认传 `'chat'`；② 读取面——`source_access.user_can_access_document/image` 检查 `Document.access_scope`，`operator` 文档仅 `ai_operator`/`admin` 可读全文与图片。

**Tech Stack:** FastAPI + SQLAlchemy + PostgreSQL + Alembic；前端 Vue 3 + TypeScript + Element Plus。

## Global Constraints

- **迁移链**：当前 head 为 `0004`。本文件新增 `0005_document_access_scope.py`，不得跳过、不得改既有 revision。每个迁移须含 `upgrade`/`downgrade`。文件 A 的 `0006` 依赖本文件的 `0005`。
- **schema.sql**：`database/schema.sql` 是参考快照，schema 变更后必须同步，保持与 Alembic 链一致。
- **数据库任务登记**：含 schema 变更，按 `AI_COLLABORATION.md` 属"完整任务流程"，实施前必须在 `docs/coordination/ACTIVE_TASKS.md` 登记 Task-ID（沿用 `ai-operator-predictive-001`），并走独立 worktree。
- **UI 规范**：任何前端修改前必须完整阅读 `docs/DESIGN_SPEC.md` 并遵循全部规范。
- **测试**：后端测试使用 `unittest`，运行命令 `cd backend && python -m pytest tests/`（或单文件）。纯逻辑服务测试必须 mock 掉 LLM 与 DB，保证离线可跑。
- **访问隔离语义**：`documents.access_scope` 取值 `chat`（医生/患者聊天可检索，默认）、`operator`（仅操作者可检索）、`both`（双方可检索）。聊天端检索必须显式传 `access_scope='chat'`。
- **提交留痕**：每次提交正文含 `AI-Agent`、`AI-Client`、`Task-ID` 三行（见 AI_COLLABORATION.md §5）。

## 文件结构（Phase 1）

**新建后端文件：**
- `backend/alembic/versions/0005_document_access_scope.py` — access_scope 迁移

**修改后端文件：**
- `backend/app/db/models.py` — Document 加 `access_scope` 列
- `backend/app/rag/pipeline.py` — `hybrid_search`/`_vector_search`/`_fulltext_search`/`SurgeryRetriever` 加 access_scope
- `backend/app/api/chat.py` — 构造 SurgeryRetriever 时显式 access_scope='chat'
- `backend/app/services/source_access.py` — 读取面隔离（全文/图片入口）
- `backend/app/api/admin.py` — 文档上传/更新接口支持 access_scope
- `backend/app/schemas/document.py` — DocumentOut/DocumentUploadResponse/DocumentUpdateIn 加 access_scope
- `database/schema.sql`

**测试文件：**
- Create: `backend/tests/test_source_access.py`
- Modify: `backend/tests/test_alembic_contracts.py`、`backend/tests/test_schema_contracts.py`、`backend/tests/test_rag_logic.py`

**前端修改：**
- `frontend/src/views/AdminView.vue` — 上传表单加 access_scope 下拉
- `frontend/src/api/admin.ts` — 类型加 access_scope

---
## Phase 1 — access_scope 文档隔离（可独立交付）

### Task 1: 迁移 0005 + Document.access_scope 模型

**Files:**
- Create: `backend/alembic/versions/0005_document_access_scope.py`
- Modify: `backend/app/db/models.py:36-55`（Document 类）
- Modify: `database/schema.sql`
- Modify: `backend/tests/test_alembic_contracts.py:21-46`
- Modify: `backend/tests/test_schema_contracts.py`（若引用 Document 字段集合）

**Interfaces:**
- Consumes: 无（独立于后续任务）
- Produces: `Document.access_scope` 列（String(20) NOT NULL DEFAULT 'chat'），供 Task 2/3 使用

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_alembic_contracts.py` 的 `test_revision_chain_is_linear` 中追加断言：

```python
predictive = _load_revision(
    "0005_document_access_scope.py", "migration_0005"
)
self.assertEqual(predictive.revision, "0005")
self.assertEqual(predictive.down_revision, "0004")
```

在 `test_foreign_key_indexes_are_declared_in_orm` 的 `expected` 集合中不需要改（access_scope 无索引）。新增一个 ORM 字段契约测试：

```python
def test_document_has_access_scope(self):
    from app.db.models import Document
    cols = {c.name: c for c in Document.__table__.columns}
    self.assertIn("access_scope", cols)
    self.assertEqual(cols["access_scope"].server_default.arg, "chat")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_alembic_contracts.py -v`
Expected: FAIL（`_load_revision` 抛文件不存在；`access_scope` 不在 ORM）

- [ ] **Step 3: 编写迁移**

```python
"""add documents.access_scope

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "documents",
        sa.Column(
            "access_scope",
            sa.String(length=20),
            nullable=False,
            server_default="chat",
        ),
    )


def downgrade():
    op.drop_column("documents", "access_scope")
```

- [ ] **Step 4: 更新 ORM 模型**

在 `backend/app/db/models.py` 的 Document 类加列（放在 department_id 之后）：

```python
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="RESTRICT"), nullable=True)
    access_scope = Column(String(20), nullable=False, default="chat", server_default="chat")
```

- [ ] **Step 5: 同步 schema.sql**

在 `database/schema.sql` 的 `documents` 表定义中添加：`access_scope VARCHAR(20) NOT NULL DEFAULT 'chat',`

- [ ] **Step 6: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_alembic_contracts.py tests/test_schema_contracts.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add backend/alembic/versions/0005_document_access_scope.py backend/app/db/models.py database/schema.sql backend/tests/
git commit -m "feat(db): add documents.access_scope for retrieval isolation

AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: ai-operator-predictive-001"
```

---

### Task 2: hybrid_search 支持 access_scope 过滤 + 聊天端隔离

**Files:**
- Modify: `backend/app/rag/pipeline.py:30-61, 63-140, 143-225, 264-327`
- Modify: `backend/app/api/chat.py`（SurgeryRetriever 构造处）
- Modify: `backend/app/services/source_access.py`（Step 7a-7c：全文/图片读取面隔离）
- Create: `backend/tests/test_source_access.py`（Step 7a：先写失败测试）

**Interfaces:**
- Consumes: Task 1 的 `Document.access_scope` 列
- Produces: `hybrid_search(db, query, top_k, department_id, access_scope=None)` 新签名；`SurgeryRetriever` 增加 `access_scope: Optional[str] = "chat"` 字段。Task 7/9 不依赖此函数（预测核心不 RAG），但聊天端隔离依赖它。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_rag_logic.py` 的 `HybridSearchTests` 中新增两组测试。第一组验证两个检索函数的 SQL 文本都含 access_scope 条件（注意 SQL 中 documents 表的实际别名是 `business_document`，不是 `d`）：

```python
def test_retrieval_sql_contains_access_scope_filter(self):
    from app.rag.pipeline import _fulltext_search, _vector_search
    import inspect

    for fn in (_vector_search, _fulltext_search):
        source = inspect.getsource(fn)
        self.assertIn("business_document.access_scope", source)
        self.assertNotIn("d.access_scope", source)

@patch("app.rag.pipeline._fulltext_search", return_value=[])
@patch("app.rag.pipeline._vector_search", return_value=[])
def test_hybrid_search_passes_access_scope_to_branches(self, mock_vec, mock_full):
    from app.rag.pipeline import hybrid_search

    hybrid_search(object(), "q", access_scope="chat")
    self.assertEqual(mock_vec.call_args.kwargs["access_scope"], "chat")
    self.assertEqual(mock_full.call_args.kwargs["access_scope"], "chat")

    hybrid_search(object(), "q", access_scope=None)
    self.assertIsNone(mock_vec.call_args.kwargs["access_scope"])
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_rag_logic.py -v`
Expected: FAIL（源码无 `business_document.access_scope`；`hybrid_search` 未透传 access_scope）

- [ ] **Step 3: 修改 pipeline.py 三个检索函数签名**

`_vector_search`、`_fulltext_search`、`hybrid_search` 均加参数：

```python
def _vector_search(
    db: Session,
    query: str,
    top_k: int,
    department_id: Optional[int] = None,
    access_scope: Optional[str] = None,
) -> List[RetrievedChunk]:
```

`_fulltext_search` 同样。`hybrid_search`：

```python
def hybrid_search(
    db: Session,
    query: str,
    top_k: int = settings.RETRIEVER_FINAL_TOP_K,
    department_id: Optional[int] = None,
    access_scope: Optional[str] = None,
) -> List[RetrievedChunk]:
```

- [ ] **Step 4: 两处 SQL 各加一个 WHERE 条件**

`_vector_search` 的 SQL 在 `(:dept_id IS NULL OR business_document.department_id = :dept_id)` 之后追加：

```sql
          AND (:scope IS NULL OR business_document.access_scope = :scope OR business_document.access_scope = 'both')
```

（SQL 中 documents 表别名固定为 `business_document`，不存在 `d` 别名——与 Step 1 测试断言一致，避免无效 SQL。）

`_fulltext_search` 同理追加同一条件。两处 execute 参数 dict 增加 `"scope": access_scope`。

- [ ] **Step 5: 修改 hybrid_search 内部调用透传 scope**

`hybrid_search` 内两处调用改为：

```python
vector_results = _vector_search(
    db, query, settings.RETRIEVER_TOP_K_VECTOR,
    department_id=department_id, access_scope=access_scope,
)
fulltext_results = _fulltext_search(
    db, query, settings.RETRIEVER_TOP_K_FULLTEXT,
    department_id=department_id, access_scope=access_scope,
)
```

- [ ] **Step 6: SurgeryRetriever 加字段 + chat 端显式传值**

`pipeline.py` 的 `SurgeryRetriever` 增加：

```python
class SurgeryRetriever(BaseRetriever):
    db: Session
    top_k: int = settings.RETRIEVER_FINAL_TOP_K
    department_id: Optional[int] = None
    access_scope: Optional[str] = "chat"

    def _get_relevant_documents(self, query: str) -> List[Document]:
        results = hybrid_search(
            self.db,
            query,
            top_k=self.top_k,
            department_id=self.department_id,
            access_scope=self.access_scope,
        )
```

`backend/app/api/chat.py` 中所有 `SurgeryRetriever(...)` 构造处**显式传 `access_scope="chat"`**（不依赖默认值，避免未来默认值变更导致隔离静默失效——与 Global Constraints「聊天端检索必须显式传 `access_scope='chat'`」一致）。搜索 chat.py 中所有 `SurgeryRetriever(` 出现处逐一补上。

在 `backend/tests/test_rag_logic.py` 新增源码检查测试，锁定"chat 端显式传值"（防止后续改动回退到依赖默认值）：

```python
def test_chat_passes_access_scope_explicitly(self):
    import re
    import pathlib
    chat_source = (
        pathlib.Path(__file__).resolve().parents[1]
        / "app/api/chat.py"
    ).read_text(encoding="utf-8")
    # 每个 SurgeryRetriever( 构造都必须在同一调用内显式带 access_scope="chat"
    calls = re.findall(r"SurgeryRetriever\(([^)]*)\)", chat_source, re.S)
    self.assertTrue(calls, "chat.py 中未找到 SurgeryRetriever 构造")
    for call in calls:
        self.assertIn('access_scope="chat"', call,
                      f"SurgeryRetriever 构造未显式传 access_scope: {call[:80]}...")
```

- [ ] **Step 7: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_rag_logic.py -v`
Expected: PASS

- [ ] **Step 7a: 读取面隔离——先写失败测试**

`/api/v1/documents/{id}/content`（main.py:69）和 `/api/v1/files/images/...`（files.py）基于 `source_access.user_can_access_document` / `user_can_access_image` 授权，而这两个函数只看历史 sources、**不检查 `Document.access_scope`**。若某文档被聊天引用后改为 `operator`，普通用户仍能凭历史引用读取全文/图片，绕过检索隔离。

先建 `backend/tests/test_source_access.py`（此时 `source_access.py` 尚未检查 scope → 红）：

```python
"""source_access 的 access_scope 隔离测试。"""
import unittest
from unittest.mock import MagicMock

from app.services.source_access import (
    user_can_access_document,
    user_can_access_image,
)


class AccessScopeIsolationTests(unittest.TestCase):
    def _mock_db(self, access_scope):
        db = MagicMock()
        doc = MagicMock()
        doc.access_scope = access_scope
        db.query.return_value.filter.return_value.first.return_value = doc
        return db

    def test_operator_scope_document_rejected_for_chat_user(self):
        db = self._mock_db("operator")
        user = MagicMock(); user.id = 1; user.role = "patient"
        self.assertFalse(user_can_access_document(db, user, 42))

    def test_operator_scope_document_allowed_for_operator(self):
        db = self._mock_db("operator")
        user = MagicMock(); user.id = 1; user.role = "ai_operator"
        self.assertTrue(user_can_access_document(db, user, 42))

    def test_chat_scope_document_falls_through_to_sources(self):
        db = self._mock_db("chat")
        user = MagicMock(); user.id = 1; user.role = "patient"
        # 无历史 sources → 拒绝（chat 范围仍需被引用过才能读全文）
        db.query.return_value.join.return_value.filter.return_value.all.return_value = []
        self.assertFalse(user_can_access_document(db, user, 42))

    def test_operator_scope_image_rejected_for_chat_user(self):
        """图片读取面同样受 scope 约束（/files/images/... 绕过路径回归保护）。"""
        db = self._mock_db("operator")
        user = MagicMock(); user.id = 1; user.role = "patient"
        self.assertFalse(user_can_access_image(db, user, 42, 1, "p1_0.png"))

    def test_operator_scope_image_allowed_for_operator(self):
        db = self._mock_db("operator")
        user = MagicMock(); user.id = 1; user.role = "ai_operator"
        self.assertTrue(user_can_access_image(db, user, 42, 1, "p1_0.png"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 7b: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_source_access.py -v`
Expected: FAIL（`user_can_access_document` 未检查 access_scope，operator 文档对 patient 仍放行）

- [ ] **Step 7c: 修改 `backend/app/services/source_access.py`**

```python
from app.db.models import Document, Message, Session as ChatSession, User


def user_can_access_document(db, user, document_id):
    if user.role == "admin":
        return True
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        return False
    if doc.access_scope == "operator":
        # operator 专属文档仅 ai_operator/admin 可读，普通聊天用户不可读
        return user.role == "ai_operator"
    return any(
        source_grants_document(source, document_id)
        for (sources,) in _user_sources(db, user.id)
        for source in (sources or [])
        if isinstance(source, dict)
    )


def user_can_access_image(db, user, document_id, generation, filename):
    if user.role == "admin":
        return True
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        return False
    if doc.access_scope == "operator":
        return user.role == "ai_operator"
    return any(
        source_grants_image(source, document_id, generation, filename)
        for (sources,) in _user_sources(db, user.id)
        for source in (sources or [])
        if isinstance(source, dict)
    )
```

测试文件已在 Step 7a 编写（红）；本步实现 `source_access.py` 后重新运行确认转绿：

Run: `cd backend && python -m pytest tests/test_source_access.py -v`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add backend/app/rag/pipeline.py backend/app/api/chat.py backend/app/services/source_access.py backend/tests/test_rag_logic.py backend/tests/test_source_access.py
git commit -m "feat(retrieval): isolate chat retrieval and document access via access_scope

AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: ai-operator-predictive-001"
```

---

### Task 3: admin 文档接口支持 access_scope

**Files:**
- Modify: `backend/app/schemas/document.py`
- Modify: `backend/app/api/admin.py:88-130, 413-430`
- Modify: `frontend/src/views/AdminView.vue`（上传表单加下拉 + 文档列表展示）
- Modify: `frontend/src/api/admin.ts`（类型加 access_scope）

**Interfaces:**
- Consumes: Task 1 的列
- Produces: `DocumentOut.access_scope`；上传接口 `upload_document(..., access_scope: str = Form("chat"))`；`DocumentUpdateIn.access_scope`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_operator_predictive_api.py`（本任务先创建空文件，Task 6 起填充）之外，先用轻量契约测试放 `backend/tests/test_schema_contracts.py`：

```python
def test_document_out_has_access_scope(self):
    from app.schemas.document import DocumentOut
    self.assertIn("access_scope", DocumentOut.model_fields)
```

**行为测试**（不只测 schema 字段，覆盖上传/更新的关键行为）。抽一个可离线单测的纯函数 `_validate_access_scope(value: str) -> str`（见 Step 4 实现），放入 `backend/tests/test_rag_logic.py`：

```python
class AccessScopeValidationTests(unittest.TestCase):
    def test_validate_accepts_all_three_scopes(self):
        from app.api.admin import _validate_access_scope
        for scope in ("chat", "operator", "both"):
            self.assertEqual(_validate_access_scope(scope), scope)

    def test_validate_rejects_invalid_scope(self):
        from app.api.admin import _validate_access_scope
        with self.assertRaises(ValueError):
            _validate_access_scope("public")

    def test_validate_default_is_chat(self):
        # 上传接口默认 access_scope="chat"：空字符串或省略按 chat 处理
        from app.api.admin import _validate_access_scope
        self.assertEqual(_validate_access_scope(""), "chat")

    def test_document_to_out_exposes_access_scope(self):
        from unittest.mock import MagicMock
        from app.api.admin import _document_to_out
        doc = MagicMock()
        doc.access_scope = "operator"
        out = _document_to_out(doc)
        self.assertEqual(out.access_scope, "operator")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_schema_contracts.py tests/test_rag_logic.py -v`
Expected: FAIL（schema 无 access_scope 字段；`_validate_access_scope` 与 `_document_to_out` 尚未实现）

- [ ] **Step 3: 更新 schema**

`DocumentUploadResponse`、`DocumentOut` 各加 `access_scope: str = "chat"`；`DocumentUpdateIn` 加 `access_scope: Optional[str] = None`。

- [ ] **Step 4: 更新 admin 上传接口**

新增可离线单测的纯函数，供 `upload_document`/`update_document` 复用：

```python
_ALLOWED_ACCESS_SCOPES = {"chat", "operator", "both"}


def _validate_access_scope(value: str) -> str:
    """校验并归一化 access_scope；省略/空串 → 'chat'；非法值抛 ValueError。"""
    if not value:
        return "chat"
    if value not in _ALLOWED_ACCESS_SCOPES:
        raise ValueError(f"非法的 access_scope: {value}")
    return value
```

`upload_document` 签名加 `access_scope: str = Form("chat")`，用 `_validate_access_scope` 校验（`ValueError` → 422），写入 `doc.access_scope = access_scope`。`update_document` 支持 payload.access_scope 更新（同样走 `_validate_access_scope`）。`_document_to_out` 透出 `access_scope`。

- [ ] **Step 5: 前端 AdminView 上传表单加下拉**

在上传区 department 选择旁增加：

```vue
<el-select v-model="uploadAccessScope" size="small" style="width: 120px">
  <el-option label="聊天可见" value="chat" />
  <el-option label="仅操作者" value="operator" />
  <el-option label="均可" value="both" />
</el-select>
```

`api/admin.ts` 上传 FormData 时追加 `access_scope: uploadAccessScope.value`，`DocumentItem` 类型加字段。

- [ ] **Step 6: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_schema_contracts.py tests/test_rag_logic.py -v`
Expected: PASS（含 Step 1 新增的 `AccessScopeValidationTests`：合法/非法/默认 chat + `_document_to_out` 透出）

- [ ] **Step 7: 前端构建自检**

Run: `cd frontend && npm run build`（或 `vue-tsc --noEmit`，按项目现状）
Expected: 无类型错误

- [ ] **Step 8: 提交**

```bash
git add backend/app/schemas/document.py backend/app/api/admin.py backend/tests/ frontend/src/views/AdminView.vue frontend/src/api/admin.ts
git commit -m "feat(admin): support access_scope on document upload

AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: ai-operator-predictive-001"
```

---

## 实施顺序与依赖

```
Task 1 ──▶ Task 2 ──▶ Task 3
 0005 迁移   检索+读取隔离   admin 上传支持
```

Phase 1（本文件）可单独交付并先合入——它只做聊天端检索/读取隔离，不触碰预测功能，风险最低。合入后再回到文件 A 实施 Phase 2-5（文件 A 的 `0006` 依赖本文件 `0005`）。

## 评审说明

本阶段的四轮评审意见与处置已记录在**文件 A** 的"评审记录"表中（Phase 1 相关条目：一轮 P0 隔离测试矛盾、三轮 P1 读取面隔离、四轮 P2 chat 显式传值 / 图片授权测试 / admin 上传行为测试等）。

**五轮就绪评估：** Codex 判定本文件（Phase 1，Task 1-3）**可先开始实施并独立合入**（无 P0，无阻塞）。实施本文件时如发现问题，在文件 A 的评审记录中追加并标注处置。
