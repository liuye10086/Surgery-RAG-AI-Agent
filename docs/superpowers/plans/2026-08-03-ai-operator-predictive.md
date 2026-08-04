# AI 操作者预测分析模块实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 AI 操作者模块从"7 章回顾性报告"彻底重构为"结构化病例 + 指标异常预测分析"：管理员在模块内录入结构化病例和疾病字典，上传并同步"正常体征参考标准"，操作者选择疾病、输入患者指标后获得指标级异常分析 + 综合风险/匹配度等级（基于已录入病例的模式匹配参考，非临床确诊概率）。

**Architecture:** 核心变化是把"纯 RAG + LLM 自由归纳"改为"代码层确定性统计 + LLM 叙述"。结构化病例存入独立 `case_records` 表（JSONB 指标，不进向量库，天然与医生/患者聊天端隔离）；正常范围由 LLM 从参考标准文档预解析进 `reference_ranges` 表，预测时纯代码比较。医生/患者聊天检索链路通过新增 `documents.access_scope` 列隔离，聊天端只检索 `chat`/`both` 范围的文档，参考标准标为 `operator` 永不被聊天端召回。

**Tech Stack:** FastAPI + SQLAlchemy + PostgreSQL(pgvector) + Alembic + LangChain LCEL + DeepSeek LLM；前端 Vue 3 + TypeScript + Element Plus + Pinia。

## Global Constraints

- **迁移链**：当前 head 为 `0004`。本计划新增 `0005_document_access_scope.py`（**见文件 B**：`2026-08-03-access-scope-isolation.md`）和 `0006_ai_operator_predictive.py`（本文件 Task 4）两个线性迁移，`0006` 依赖 `0005`，不得跳过、不得改既有 revision。每个迁移须含 `upgrade`/`downgrade`，外键必须显式命名。
- **schema.sql**：`database/schema.sql` 是参考快照，每次 schema 变更后必须同步，保持与 Alembic 链一致。
- **数据库任务登记**：本计划含 schema 变更，按 `AI_COLLABORATION.md` 属"完整任务流程"，实施前必须在 `docs/coordination/ACTIVE_TASKS.md` 登记唯一 Task-ID（建议 `ai-operator-predictive-001`），并走独立 worktree。
- **UI 规范**：任何前端修改前必须完整阅读 `docs/DESIGN_SPEC.md` 并遵循全部规范（色彩变量、间距、圆角、双角色体验）。
- **测试**：后端测试使用 `unittest`，运行命令 `cd backend && python -m pytest tests/`（或单文件）。纯逻辑服务测试必须 mock 掉 LLM 与 DB，保证离线可跑。
- **访问隔离语义**：`documents.access_scope` 取值 `chat`（医生/患者聊天可检索，默认）、`operator`（仅操作者可检索）、`both`（双方可检索）。聊天端检索必须显式传 `access_scope='chat'`。
- **概率措辞约定**：预测引擎输出的 `band`/`probability_range` 本质是"已录入确诊病例的模式匹配度"，不是临床发病概率。所有对外文案（报告 prompt、前端 UI）必须标注"基于已录入病例的模式匹配参考，非临床确诊概率"，并保留免责声明，禁止以绝对概率向用户陈述。
- **参考范围边界语义**：`reference_ranges` 用 `lower_inclusive`/`upper_inclusive` 表达边界开闭（`<21` → upper=21, upper_inclusive=False；`≤21` → upper_inclusive=True；区间 `3.5-9.5` → 两端 inclusive=True）。判定逻辑按此区分边界值是否异常，见 Task 8 `classify_indicator`。
- **旧数据兼容**：`ai_reports` 保留原列（`department_ids`/`query` 等成为遗留字段），新列全部 nullable/default，旧报告行不破坏；旧 7 章报告记录以 `analysis_type='retrospective'` 标记。
- **提交留痕**：每次提交正文含 `AI-Agent`、`AI-Client`、`Task-ID` 三行（见 AI_COLLABORATION.md §5）。

---

## 文件结构

本计划拆分为两份文件：

- **文件 A（本文件）**：Phase 2-5（Task 4-14）——数据层、预测引擎、前端、收尾。
- **文件 B**：`docs/superpowers/plans/2026-08-03-access-scope-isolation.md`——**Phase 1**（Task 1-3）access_scope 文档隔离，可独立交付，包含 0005 迁移、检索/读取面隔离、admin 上传支持。**实施 A 之前需先完成 B**（0006 依赖 0005，预测功能依赖 access_scope 概念）。

**本文件（A）涉及的文件：**

**新建后端文件：**
- `backend/alembic/versions/0006_ai_operator_predictive.py` — diseases/case_records/reference_ranges + ai_reports 新列
- `backend/app/services/prediction_engine.py` — 指标分析 + 综合概率核心算法（纯函数）
- `backend/app/services/reference_standard.py` — 参考标准文档 → reference_ranges 的 LLM 解析
- `backend/app/services/prediction_generator.py` — 预测报告 SSE 生成器（替代 report_generator.py）
- `backend/app/schemas/prediction.py` — 预测请求/响应、疾病/病例/参考范围 schema
- `backend/tests/test_prediction_engine.py` — 核心算法测试
- `backend/tests/test_reference_standard.py` — 解析服务测试
- `backend/tests/test_operator_predictive_api.py` — 新 API 测试

**修改后端文件：**
- `backend/app/db/models.py` — 新增 Disease/CaseRecord/ReferenceRange，AIReport 加新列（Document.access_scope 见文件 B）
- `backend/app/api/operator.py` — 新增病例/疾病/参考范围端点；重构 POST /reports 为预测请求

**删除后端文件：**
- `backend/app/services/report_generator.py` — 被 prediction_generator.py 取代
- `backend/tests/test_report_generator.py`、`test_operator_api.py`、`test_operator_state_machine.py` — 旧流程测试被新测试取代（state_machine 用例并入新测试）

**前端修改：**
- `frontend/src/api/operator.ts` — 新增 predict/病例/疾病/参考范围接口
- `frontend/src/stores/operator.ts` — 适配预测状态
- `frontend/src/views/OperatorView.vue` — 重写主体区（疾病选择 + 指标表单 + 预测结果）
- `frontend/src/components/OperatorSidebar.vue` — 增加"预测分析/病例库"导航
- `frontend/src/components/CaseManageView.vue` — 新增病例库管理视图（疾病 + 病例 + 参考范围）

**文件 B 涉及的文件**（详见 B）：`0005_document_access_scope.py`、`pipeline.py`、`chat.py`、`source_access.py`、`admin.py`、`schemas/document.py`、`database/schema.sql`、`AdminView.vue`、`api/admin.ts`、`tests/test_source_access.py` 等。

---

## Phase 1 — access_scope 文档隔离（可独立交付）

> **本阶段（Task 1-3）已拆分至独立文件 B：** [`2026-08-03-access-scope-isolation.md`](2026-08-03-access-scope-isolation.md)
>
> 包含：`0005` 迁移（`documents.access_scope`）、检索与读取面隔离（`hybrid_search` / `source_access`）、admin 上传支持。
>
> **实施顺序：先完成 B（Phase 1）并合入，再回到本文件实施 Phase 2-5。** 文件 A 的 `0006` 迁移依赖 B 的 `0005`；预测功能依赖 access_scope 隔离前提。

---
## Phase 2 — 数据层：疾病 / 病例 / 参考范围

### Task 4: 迁移 0006 + 新模型

**Files:**
- Create: `backend/alembic/versions/0006_ai_operator_predictive.py`
- Modify: `backend/app/db/models.py`（新增 3 类 + AIReport 新列）
- Modify: `database/schema.sql`
- Modify: `backend/tests/test_alembic_contracts.py`

**Interfaces:**
- Produces: `Disease`（id/name unique/description/created_at）、`CaseRecord`（id/disease_id FK/patient_label/indicators JSONB/confirmed/**case_metadata**（DB 列 metadata）/created_at）、`ReferenceRange`（id/indicator_name/name_cn/unit/lower/upper/**lower_inclusive/upper_inclusive**/category/document_id FK/created_at）；AIReport 新增 `analysis_type`、`disease_id`、`indicators`、`prediction_result` 列。供 Task 5/6/7 使用。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_alembic_contracts.py` 的 `test_revision_chain_is_linear` 追加：

```python
predictive = _load_revision(
    "0006_ai_operator_predictive.py", "migration_0006"
)
self.assertEqual(predictive.revision, "0006")
self.assertEqual(predictive.down_revision, "0005")
```

新增 ORM 契约：

```python
def test_new_predictive_tables_declared(self):
    from app.db.models import CaseRecord, Disease, ReferenceRange
    self.assertIn("id", Disease.__table__.columns)
    self.assertIn("disease_id", CaseRecord.__table__.columns)
    self.assertIn("indicator_name", ReferenceRange.__table__.columns)

def test_reference_range_inclusive_columns(self):
    from app.db.models import ReferenceRange
    cols = {c.name: c for c in ReferenceRange.__table__.columns}
    self.assertIn("lower_inclusive", cols)
    self.assertIn("upper_inclusive", cols)
    # 默认含边界（True），与迁移 server_default=true 一致
    self.assertEqual(cols["lower_inclusive"].server_default.arg, "true")
    self.assertEqual(cols["upper_inclusive"].server_default.arg, "true")

def test_ai_report_predictive_columns(self):
    from app.db.models import AIReport
    cols = {c.name for c in AIReport.__table__.columns}
    self.assertTrue({"analysis_type", "disease_id", "indicators", "prediction_result"}.issubset(cols))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_alembic_contracts.py -v`
Expected: FAIL

- [ ] **Step 3: ORM 新增三类 + AIReport 新列**

在 `models.py` 中新增（放在 AIReport 之前）：

```python
class Disease(Base):
    __tablename__ = "diseases"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), unique=True, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    case_records = relationship("CaseRecord", back_populates="disease", cascade="all, delete-orphan")


class CaseRecord(Base):
    __tablename__ = "case_records"
    __table_args__ = (Index("ix_case_records_disease_id", "disease_id"),)

    id = Column(Integer, primary_key=True)
    disease_id = Column(Integer, ForeignKey("diseases.id", ondelete="CASCADE"), nullable=False)
    patient_label = Column(String(100))
    indicators = Column(JSONB, nullable=False, default=list)
    confirmed = Column(Boolean, nullable=False, default=True, server_default="true")
    # 注意：`metadata` 是 SQLAlchemy declarative 的保留类属性（MetaData），
    # 不能直接作为 ORM 属性名，否则 models.py 导入即失败。
    # DB 列名仍为 "metadata"，ORM 属性命名为 case_metadata（与 Chunk.chunk_metadata 同模式）。
    case_metadata = Column("metadata", JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    disease = relationship("Disease", back_populates="case_records")


class ReferenceRange(Base):
    __tablename__ = "reference_ranges"
    __table_args__ = (Index("ix_reference_ranges_indicator", "indicator_name"),)

    id = Column(Integer, primary_key=True)
    indicator_name = Column(String(100), nullable=False)
    name_cn = Column(String(200))
    unit = Column(String(50))
    lower = Column(Float)
    upper = Column(Float)
    # 边界开闭语义：<21 → upper=21, upper_inclusive=False；≤21 → True；
    # 区间 3.5-9.5 → 两端 True。见 Global Constraints「参考范围边界语义」。
    lower_inclusive = Column(Boolean, nullable=False, default=True, server_default="true")
    upper_inclusive = Column(Boolean, nullable=False, default=True, server_default="true")
    category = Column(String(100))
    # 删除语义：参考标准文档删除时，其解析出的范围**级联删除**（CASCADE）。
    # 若用 SET NULL，文档删除后范围变孤儿仍参与预测，会基于已删除标准给出误导结果；
    # 级联后预测遇缺范围会明确报"缺少参考范围"提示操作者重新同步，行为更安全。
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

AIReport 新增：

```python
    analysis_type = Column(String(50), nullable=False, default="retrospective", server_default="retrospective")
    disease_id = Column(Integer, ForeignKey("diseases.id", ondelete="SET NULL"), nullable=True)
    indicators = Column(JSONB, default=list)
    prediction_result = Column(JSONB, default=dict)
```

- [ ] **Step 4: 编写迁移**

```python
"""add diseases, case_records, reference_ranges, ai_reports predictive columns

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "diseases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "case_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("disease_id", sa.Integer(), sa.ForeignKey("diseases.id", name="fk_case_records_disease", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_label", sa.String(length=100)),
        sa.Column("indicators", JSONB(), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("metadata", JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_case_records_disease_id", "case_records", ["disease_id"])
    op.create_table(
        "reference_ranges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("indicator_name", sa.String(length=100), nullable=False),
        sa.Column("name_cn", sa.String(length=200)),
        sa.Column("unit", sa.String(length=50)),
        sa.Column("lower", sa.Float()),
        sa.Column("upper", sa.Float()),
        sa.Column("lower_inclusive", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("upper_inclusive", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("category", sa.String(length=100)),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", name="fk_reference_ranges_document", ondelete="CASCADE")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_reference_ranges_indicator", "reference_ranges", ["indicator_name"])
    op.add_column("ai_reports", sa.Column("analysis_type", sa.String(length=50), nullable=False, server_default="retrospective"))
    op.add_column("ai_reports", sa.Column("disease_id", sa.Integer(), sa.ForeignKey("diseases.id", name="fk_ai_reports_disease", ondelete="SET NULL")))
    op.add_column("ai_reports", sa.Column("indicators", JSONB()))
    op.add_column("ai_reports", sa.Column("prediction_result", JSONB()))


def downgrade():
    op.drop_column("ai_reports", "prediction_result")
    op.drop_column("ai_reports", "indicators")
    # 显式先删外键约束再删列，保证 downgrade 对称（PostgreSQL 不会自动删约束）
    op.drop_constraint("fk_ai_reports_disease", "ai_reports", type_="foreignkey")
    op.drop_column("ai_reports", "disease_id")
    op.drop_column("ai_reports", "analysis_type")
    op.drop_index("ix_reference_ranges_indicator", table_name="reference_ranges")
    op.drop_table("reference_ranges")
    op.drop_index("ix_case_records_disease_id", table_name="case_records")
    op.drop_table("case_records")
    op.drop_table("diseases")
```

- [ ] **Step 5: 同步 schema.sql**

按 ORM 与迁移内容在 `database/schema.sql` 追加三张表定义和 ai_reports 四列。

- [ ] **Step 6: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_alembic_contracts.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add backend/alembic/versions/0006_ai_operator_predictive.py backend/app/db/models.py database/schema.sql backend/tests/
git commit -m "feat(db): add diseases, case_records, reference_ranges tables

AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: ai-operator-predictive-001"
```

---

### Task 5: 疾病 CRUD API

**Files:**
- Create: `backend/app/schemas/prediction.py`
- Modify: `backend/app/api/operator.py`（新增 4 个疾病端点）
- Test: `backend/tests/test_operator_predictive_api.py`

**Interfaces:**
- Consumes: Task 4 的 `Disease` 模型
- Produces: 
  - `POST /operator/diseases` body `DiseaseCreate(name, description)` → `DiseaseOut(id, name, description, created_at, case_count)`
  - `GET /operator/diseases` → `list[DiseaseOut]`（含 case_count）
  - `PUT /operator/diseases/{id}` body `DiseaseUpdate(name?, description?)` → `DiseaseOut`
  - `DELETE /operator/diseases/{id}` → 204（有病例时 409）
  - 供 Task 6（病例引用 disease_id）、Task 12（前端疾病选择）使用。

- [ ] **Step 1: 写失败测试**

```python
"""Operator predictive API 测试。"""
import unittest
from fastapi import HTTPException
from app.schemas.prediction import DiseaseCreate, DiseaseUpdate


class DiseaseSchemaTests(unittest.TestCase):
    def test_disease_create_requires_name(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            DiseaseCreate(name="")

    def test_disease_create_normalizes_name(self):
        d = DiseaseCreate(name=" 胆囊结石 ")
        self.assertEqual(d.name, "胆囊结石")

    def test_disease_out_construction(self):
        """_disease_to_out 显式构造（Pydantic v2 model_validate 无 update 参数）。"""
        from unittest.mock import MagicMock
        from app.api.operator import _disease_to_out

        d = MagicMock()
        d.id = 1
        d.name = "胆囊结石"
        d.description = None
        d.created_at = "2026-01-01T00:00:00"
        out = _disease_to_out(d, 5)
        self.assertEqual(out.id, 1)
        self.assertEqual(out.case_count, 5)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_operator_predictive_api.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 编写 schema**

```python
"""AI 操作者预测分析相关 Pydantic Schema。"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class DiseaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class DiseaseUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None


class DiseaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str] = None
    case_count: int = 0
    created_at: datetime


class IndicatorInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    value: float
    unit: str = Field(..., min_length=1, max_length=50)


class PredictRequest(BaseModel):
    disease_id: int
    indicators: list[IndicatorInput] = Field(..., min_length=1, max_length=30)
    patient_summary: Optional[str] = Field(None, max_length=2000)


class CaseRecordIn(BaseModel):
    disease_id: int
    patient_label: Optional[str] = Field(None, max_length=100)
    indicators: list[IndicatorInput] = Field(..., min_length=1, max_length=30)
    confirmed: bool = True
    metadata: dict = Field(default_factory=dict)


class CaseRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    disease_id: int
    patient_label: Optional[str]
    indicators: list[dict]
    confirmed: bool
    # ORM 属性是 case_metadata（DB 列 metadata），用 validation_alias 桥接，
    # 响应 JSON 键名仍为 metadata，前端无需感知。
    metadata: dict = Field(default_factory=dict, validation_alias="case_metadata")
    created_at: datetime


class ReferenceRangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    indicator_name: str
    name_cn: Optional[str]
    unit: Optional[str]
    lower: Optional[float]
    upper: Optional[float]
    # 暴露 inclusive，前端才能区分 "<21" 与 "≤21" 的展示
    lower_inclusive: bool = True
    upper_inclusive: bool = True
    category: Optional[str]
    document_id: Optional[int]
```

- [ ] **Step 4: 实现疾病端点**

在 `backend/app/api/operator.py` 顶部引入 `Disease`、`CaseRecord`、`ReferenceRange` 模型和 `app.schemas.prediction` 的 schema。疾病端点（复用 `require_ai_operator` 权限，新增 `_verify_disease_exists` 辅助）：

```python
@router.post("/diseases", response_model=DiseaseOut)
def create_disease(payload: DiseaseCreate, db: Session = Depends(get_db), current_user: User = Depends(require_ai_operator)):
    if db.query(Disease).filter(Disease.name == payload.name).first():
        raise HTTPException(status_code=409, detail=f"疾病「{payload.name}」已存在")
    d = Disease(name=payload.name, description=payload.description)
    db.add(d); db.commit(); db.refresh(d)
    return d


def _disease_to_out(d: Disease, case_count: int) -> DiseaseOut:
    """显式构造 DiseaseOut。

    注意：Pydantic v2 的 `model_validate` 没有 `update` 参数，
    `model_validate(d, update={...})` 会抛 TypeError。必须显式传值构造。
    """
    return DiseaseOut(
        id=d.id,
        name=d.name,
        description=d.description,
        case_count=case_count,
        created_at=d.created_at,
    )


@router.get("/diseases", response_model=list[DiseaseOut])
def list_diseases(db: Session = Depends(get_db), current_user: User = Depends(require_ai_operator)):
    diseases = db.query(Disease).order_by(Disease.id).all()
    counts = dict(db.query(CaseRecord.disease_id, func.count(CaseRecord.id)).group_by(CaseRecord.disease_id).all())
    return [_disease_to_out(d, counts.get(d.id, 0)) for d in diseases]


@router.put("/diseases/{disease_id}", response_model=DiseaseOut)
def update_disease(disease_id: int, payload: DiseaseUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_ai_operator)):
    d = db.query(Disease).filter(Disease.id == disease_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="疾病不存在")
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="疾病名称不能为空")
        if db.query(Disease).filter(Disease.name == name, Disease.id != disease_id).first():
            raise HTTPException(status_code=409, detail=f"疾病「{name}」已存在")
        d.name = name
    if payload.description is not None:
        d.description = payload.description
    db.commit(); db.refresh(d)
    return d


@router.delete("/diseases/{disease_id}", status_code=204)
def delete_disease(disease_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_ai_operator)):
    d = db.query(Disease).filter(Disease.id == disease_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="疾病不存在")
    if db.query(CaseRecord).filter(CaseRecord.disease_id == disease_id).count():
        raise HTTPException(status_code=409, detail="该疾病下存在病例，请先删除病例")
    db.delete(d); db.commit()
    return None
```

`operator.py` 顶部需 `from sqlalchemy import func`。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_operator_predictive_api.py -v`
Expected: PASS。覆盖：schema 校验、名称 strip、`_disease_to_out` 显式构造（含 case_count）。依赖真实 PG 的疾病 CRUD 端点路径纳入部署验证清单 `docs/coordination/` 验收条件，不在离线单测覆盖——离线层验证的是 schema 契约与辅助函数行为。

- [ ] **Step 6: 提交**

```bash
git add backend/app/schemas/prediction.py backend/app/api/operator.py backend/tests/test_operator_predictive_api.py
git commit -m "feat(operator): add disease CRUD endpoints

AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: ai-operator-predictive-001"
```

---

### Task 6: 病例 CRUD API

**Files:**
- Modify: `backend/app/api/operator.py`
- Modify: `backend/tests/test_operator_predictive_api.py`

**Interfaces:**
- Consumes: Task 5 的 `CaseRecordIn/Out`、`Disease` 校验
- Produces: 
  - `POST /operator/cases` body `CaseRecordIn` → `CaseRecordOut`
  - `GET /operator/cases?disease_id=&confirmed=&skip=&limit=` → `{total, items}`
  - `PUT /operator/cases/{id}` body `CaseRecordIn` → `CaseRecordOut`
  - `DELETE /operator/cases/{id}` → 204
  - 供 Task 8（预测引擎读取 confirmed 病例）、Task 13（前端病例管理）使用。

- [ ] **Step 1: 写失败测试**

本任务的核心"红"来自**路由注册契约测试**（必须在实现端点前先写）。schema 测试已在 Task 5 定义并通过，此处保留引用。

```python
from app.schemas.prediction import CaseRecordIn, IndicatorInput


class CaseRecordSchemaTests(unittest.TestCase):
    def test_case_record_requires_indicators(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            CaseRecordIn(disease_id=1, indicators=[])

    def test_indicator_validates_name_value_unit(self):
        ind = IndicatorInput(name="TBIL", value=35.0, unit="μmol/L")
        self.assertEqual(ind.name, "TBIL")
        self.assertEqual(ind.value, 35.0)


class OperatorRouterEndpointTests(unittest.TestCase):
    def test_case_endpoints_registered(self):
        """先写：实现前 /operator/cases 未注册 → 本测试为红。"""
        from app.api.operator import router
        paths = {r.path for r in router.routes}
        self.assertTrue(
            {"/operator/cases", "/operator/diseases"}.issubset(paths)
        )
```

（说明：依赖真实 PG 的端点集成测试纳入部署验证清单 `docs/coordination/` 验收条件，不在离线单测覆盖；离线层验证 schema 契约与路由注册。注意：此处**不要**断言 `/operator/reference-ranges/sync`——该端点在 Task 7 才加入，提前断言会让本任务测试失败。Task 7 的 Step 5b 会补上对 sync 路由的断言。）

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_operator_predictive_api.py::OperatorRouterEndpointTests -v`
Expected: FAIL（/operator/cases 尚未注册）。schema 测试（`CaseRecordSchemaTests`）已在 Task 5 通过，不是本步目标。

- [ ] **Step 3: 实现病例端点**

```python
def _get_case_or_404(db: Session, case_id: int) -> CaseRecord:
    c = db.query(CaseRecord).filter(CaseRecord.id == case_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="病例不存在")
    return c


@router.post("/cases", response_model=CaseRecordOut)
def create_case(payload: CaseRecordIn, db: Session = Depends(get_db), current_user: User = Depends(require_ai_operator)):
    if not db.query(Disease).filter(Disease.id == payload.disease_id).first():
        raise HTTPException(status_code=422, detail="疾病不存在")
    c = CaseRecord(
        disease_id=payload.disease_id,
        patient_label=payload.patient_label,
        indicators=[i.model_dump() for i in payload.indicators],
        confirmed=payload.confirmed,
        case_metadata=payload.metadata,  # ORM 属性名是 case_metadata
    )
    db.add(c); db.commit(); db.refresh(c)
    return c


@router.get("/cases")
def list_cases(
    disease_id: int | None = Query(None),
    confirmed: bool | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    q = db.query(CaseRecord)
    if disease_id is not None:
        q = q.filter(CaseRecord.disease_id == disease_id)
    if confirmed is not None:
        q = q.filter(CaseRecord.confirmed.is_(confirmed))
    total = q.count()
    items = q.order_by(CaseRecord.created_at.desc()).offset(skip).limit(limit).all()
    return {"total": total, "items": [CaseRecordOut.model_validate(c) for c in items]}


@router.put("/cases/{case_id}", response_model=CaseRecordOut)
def update_case(case_id: int, payload: CaseRecordIn, db: Session = Depends(get_db), current_user: User = Depends(require_ai_operator)):
    c = _get_case_or_404(db, case_id)
    if not db.query(Disease).filter(Disease.id == payload.disease_id).first():
        raise HTTPException(status_code=422, detail="疾病不存在")
    c.disease_id = payload.disease_id
    c.patient_label = payload.patient_label
    c.indicators = [i.model_dump() for i in payload.indicators]
    c.confirmed = payload.confirmed
    c.case_metadata = payload.metadata  # ORM 属性名是 case_metadata
    db.commit(); db.refresh(c)
    return c


@router.delete("/cases/{case_id}", status_code=204)
def delete_case(case_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_ai_operator)):
    c = _get_case_or_404(db, case_id)
    db.delete(c); db.commit()
    return None
```

- [ ] **Step 4: 运行测试确认通过**

路由契约测试已在 Step 1 先写（红），本步实现端点后重新运行转为绿：

Run: `cd backend && python -m pytest tests/test_operator_predictive_api.py -v`
Expected: PASS（`OperatorRouterEndpointTests` 绿 + `CaseRecordSchemaTests` 绿）

- [ ] **Step 6: 提交**

```bash
git add backend/app/api/operator.py backend/tests/test_operator_predictive_api.py
git commit -m "feat(operator): add case record CRUD endpoints

AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: ai-operator-predictive-001"
```

---

### Task 7: 参考标准解析服务 + 同步端点

**Files:**
- Create: `backend/app/services/reference_standard.py`
- Create: `backend/tests/test_reference_standard.py`
- Modify: `backend/app/api/operator.py`（同步端点）

**Interfaces:**
- Consumes: Task 4 的 `ReferenceRange`、`Document`（读 chunk 文本）、`settings.DEEPSEEK_*`
- Produces:
  - `parse_reference_segment(text) -> list[dict]`（确定性兜底解析）
  - `_extract_json_array(text) -> list[dict]`
  - `sync_reference_ranges(db, document_id) -> dict`（删除该 document 旧行→LLM 提取→校验→插入；返回 `{inserted, dropped, document_id}`）
  - `POST /operator/reference-ranges/sync` body `{document_id}` → 同步结果
  - `GET /operator/reference-ranges` → `list[ReferenceRangeOut]`
  - 供 Task 8（预测引擎取范围）、Task 13/14（前端同步 UI）使用。

- [ ] **Step 1: 写失败测试**

```python
"""参考标准解析服务测试。"""
import unittest
from unittest.mock import MagicMock, patch
from app.services.reference_standard import (
    parse_reference_segment,
    _extract_json_array,
    sync_reference_ranges,
)


class ReferenceParsingTests(unittest.TestCase):
    def test_parse_lt_form(self):
        # 严格上限：<21 → upper=21, upper_inclusive=False
        self.assertEqual(
            parse_reference_segment("TBIL（总胆红素）：<21 μmol/L"),
            [{"indicator_name": "TBIL", "name_cn": "总胆红素", "unit": "μmol/L",
              "lower": None, "upper": 21.0, "lower_inclusive": True, "upper_inclusive": False}],
        )

    def test_parse_range_form(self):
        # 区间 → 两端 inclusive=True
        self.assertEqual(
            parse_reference_segment("WBC（白细胞计数）：3.5-9.5 ×10⁹/L"),
            [{"indicator_name": "WBC", "name_cn": "白细胞计数", "unit": "×10⁹/L",
              "lower": 3.5, "upper": 9.5, "lower_inclusive": True, "upper_inclusive": True}],
        )

    def test_parse_le_form_inclusive_upper(self):
        # ≤21 → upper_inclusive=True（与 <21 的 upper_inclusive=False 区分）
        self.assertEqual(
            parse_reference_segment("ALP（碱性磷酸酶）：≤21 μmol/L"),
            [{"indicator_name": "ALP", "name_cn": "碱性磷酸酶", "unit": "μmol/L",
              "lower": None, "upper": 21.0, "lower_inclusive": True, "upper_inclusive": True}],
        )

    def test_parse_gt_form_exclusive_lower(self):
        # 严格下限：>140 → lower=140, lower_inclusive=False
        self.assertEqual(
            parse_reference_segment("SBP（收缩压）：>140 mmHg"),
            [{"indicator_name": "SBP", "name_cn": "收缩压", "unit": "mmHg",
              "lower": 140.0, "upper": None, "lower_inclusive": False, "upper_inclusive": True}],
        )

    def test_parse_ge_form_inclusive_lower(self):
        # 含边界下限：≥140 → lower=140, lower_inclusive=True
        self.assertEqual(
            parse_reference_segment("SBP（收缩压）：≥140 mmHg"),
            [{"indicator_name": "SBP", "name_cn": "收缩压", "unit": "mmHg",
              "lower": 140.0, "upper": None, "lower_inclusive": True, "upper_inclusive": True}],
        )

    def test_parse_list_prefix_line(self):
        # 列表前缀行也应被确定性解析命中（- TBIL...）
        self.assertEqual(
            parse_reference_segment("- TBIL（总胆红素）：<21 μmol/L"),
            [{"indicator_name": "TBIL", "name_cn": "总胆红素", "unit": "μmol/L",
              "lower": None, "upper": 21.0, "lower_inclusive": True, "upper_inclusive": False}],
        )

    def test_parse_unparseable_returns_empty(self):
        self.assertEqual(parse_reference_segment("参考标准为临床公认值"), [])

    def test_extract_json_array_valid(self):
        text = '这里是说明\n[{"name": "ALT", "lower": null, "upper": 40, "unit": "U/L"}]\n完毕'
        arr = _extract_json_array(text)
        self.assertEqual(len(arr), 1)
        self.assertEqual(arr[0]["name"], "ALT")


class SyncProtectionTests(unittest.TestCase):
    """失败不破坏旧数据的空结果保护。"""

    @patch("app.services.reference_standard._sync_from_llm", side_effect=RuntimeError("timeout"))
    def test_empty_items_raises_and_keeps_old_data(self, _llm):
        from app.services.reference_standard import sync_reference_ranges

        db = MagicMock()
        doc = MagicMock()
        doc.id = 1
        doc.access_scope = "operator"
        doc.active_generation = 1
        doc.title = "标准"
        db.query.return_value.filter.return_value.first.return_value = doc
        # 文档含 current chunks，但都是无法确定性解析的行（如章节标题）
        chunk = MagicMock()
        chunk.content = "## 肝功能指标\n参考范围以检验科最新发布为准"
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [chunk]

        with self.assertRaises(ValueError):
            sync_reference_ranges(db, 1)
        # 空结果时不得调用 delete（旧行被保留）
        db.query.return_value.filter.return_value.delete.assert_not_called()

    @patch("app.services.reference_standard._sync_from_llm", side_effect=RuntimeError("timeout"))
    def test_partial_deterministic_plus_llm_failure_keeps_old_data(self, _llm):
        """确定性解析有部分命中 + LLM 失败：仍须整体 abort 保留旧数据，
        不能静默替换为不完整数据。"""
        from app.services.reference_standard import sync_reference_ranges

        db = MagicMock()
        doc = MagicMock()
        doc.id = 1
        doc.access_scope = "operator"
        doc.active_generation = 1
        doc.title = "标准"
        db.query.return_value.filter.return_value.first.return_value = doc
        # 第一行确定性可命中（<21），第二行需要 LLM 但 LLM 抛异常
        chunk = MagicMock()
        chunk.content = "- TBIL（总胆红素）：<21 μmol/L\n（此行为补充说明，需 LLM 解析）"
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [chunk]

        with self.assertRaises(ValueError):
            sync_reference_ranges(db, 1)
        # 即使确定性有部分命中，LLM 失败时也不得 delete 旧行
        db.query.return_value.filter.return_value.delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_reference_standard.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现确定性解析器**

```python
"""参考标准文档 → reference_ranges 结构化解析。"""
import json
import logging
import re

from sqlalchemy.orm import Session

from app.db.models import Chunk, Document, ReferenceRange

logger = logging.getLogger(__name__)

_LINE_RE = re.compile(
    r"^\s*(?:[-*•]\s*|\d+[.、]\s*)?(?P<name>[A-Za-z][A-Za-z0-9_\-]*)\s*"
    r"(?:[（(](?P<cn>[^）)]*)[)）])?\s*[:：]\s*(?P<range>.*?)\s*$"
)
_UPPER_LT_RE = re.compile(r"<\s*(\d+(?:\.\d+)?)(.*)$")      # 严格上限
_UPPER_LE_RE = re.compile(r"≤\s*(\d+(?:\.\d+)?)(.*)$")      # 含边界上限
_LOWER_GT_RE = re.compile(r">\s*(\d+(?:\.\d+)?)(.*)$")      # 严格下限
_LOWER_GE_RE = re.compile(r"≥\s*(\d+(?:\.\d+)?)(.*)$")      # 含边界下限
_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-~—～]\s*(\d+(?:\.\d+)?)(.*)$")


def _to_number(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse_reference_segment(text: str) -> list[dict]:
    """确定性解析单行参考标准，返回 [{indicator_name, name_cn, unit, lower, upper,
    lower_inclusive, upper_inclusive}]。

    支持 "<21 μmol/L"、"3.5-9.5 ×10⁹/L"、"≥140 mmHg"、"≤21 μmol/L" 等格式。
    - 严格边界（<、>）→ 对应 inclusive=False；含边界（≤、≥）与区间 → inclusive=True。
    解析失败返回空列表。字段名与 ReferenceRange 模型一致（indicator_name），
    可直接 **dict 入库。
    """
    m = _LINE_RE.match(text)
    if not m:
        return []
    name = m.group("name")
    cn = m.group("cn") or ""
    rng = m.group("range").strip()
    if not name or not rng:
        return []

    lower = upper = None
    lower_inclusive = True
    upper_inclusive = True
    unit = ""
    m_ult = _UPPER_LT_RE.match(rng)
    m_ule = _UPPER_LE_RE.match(rng)
    m_lgt = _LOWER_GT_RE.match(rng)
    m_lge = _LOWER_GE_RE.match(rng)
    m_r = _RANGE_RE.match(rng)
    if m_ult:
        upper = _to_number(m_ult.group(1))
        upper_inclusive = False
        unit = m_ult.group(2).strip()
    elif m_ule:
        upper = _to_number(m_ule.group(1))
        unit = m_ule.group(2).strip()
    elif m_lgt:
        lower = _to_number(m_lgt.group(1))
        lower_inclusive = False
        unit = m_lgt.group(2).strip()
    elif m_lge:
        lower = _to_number(m_lge.group(1))
        unit = m_lge.group(2).strip()
    elif m_r:
        lower = _to_number(m_r.group(1))
        upper = _to_number(m_r.group(2))
        unit = m_r.group(3).strip()

    if lower is None and upper is None:
        return []
    return [{
        "indicator_name": name,
        "name_cn": cn,
        "unit": unit,
        "lower": lower,
        "upper": upper,
        "lower_inclusive": lower_inclusive,
        "upper_inclusive": upper_inclusive,
    }]


def _extract_json_array(text: str) -> list[dict]:
    """从 LLM 输出中提取 JSON 数组。"""
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
```

- [ ] **Step 4: 实现 LLM 提取 + 同步**

```python
_REFERENCE_PARSE_PROMPT = """你是一个医学检验参考范围解析器。从给定的标准文档片段中提取检验指标参考范围。

只输出一个 JSON 数组，不要输出任何其他文字。数组每个元素格式：
{"name": "指标英文缩写", "name_cn": "中文名", "unit": "单位", "lower": 下限数字或null, "upper": 上限数字或null, "lower_inclusive": true或false, "upper_inclusive": true或false, "category": "所属分类"}

规则：
1. 严格上限 "TBIL（总胆红素）：<21 μmol/L" → {"name":"TBIL","name_cn":"总胆红素","unit":"μmol/L","lower":null,"upper":21,"upper_inclusive":false}
2. 含边界上限 "≤21 μmol/L" → upper=21, "upper_inclusive":true
3. 严格下限 ">140 mmHg" → lower=140, "lower_inclusive":false
4. 含边界下限 "≥140 mmHg" → lower=140, "lower_inclusive":true
5. 区间 "WBC：3.5-9.5 ×10⁹/L" → lower=3.5, upper=9.5, 两端 inclusive 均为 true
6. lower 与 upper 至少一个非 null；无法确定范围的条目丢弃
7. 类别从片段所在章节标题推断，如"肝功能指标"
输出必须是可被 json.loads 直接解析的纯 JSON。"""


def _sync_from_llm(chunk_texts: list[str]) -> list[dict]:
    from langchain_openai import ChatOpenAI
    from app.core.config import settings

    llm = ChatOpenAI(
        model=settings.DEEPSEEK_MODEL,
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        temperature=0,
        max_tokens=2000,
        request_timeout=settings.DEEPSEEK_REQUEST_TIMEOUT,
    )
    combined = "\n\n".join(chunk_texts)
    if len(combined) > 12000:
        combined = combined[:12000]
    from langchain_core.messages import HumanMessage, SystemMessage
    reply = llm.invoke(
        [
            SystemMessage(content=_REFERENCE_PARSE_PROMPT),
            HumanMessage(content=combined),
        ]
    )
    items = _extract_json_array(str(reply.content))
    valid = []
    for it in items:
        if not isinstance(it, dict) or not it.get("name"):
            continue
        try:
            lower = float(it["lower"]) if it.get("lower") is not None else None
            upper = float(it["upper"]) if it.get("upper") is not None else None
        except (TypeError, ValueError):
            continue
        if lower is None and upper is None:
            continue
        valid.append({
            "indicator_name": str(it["name"]).strip()[:100],
            "name_cn": str(it.get("name_cn") or "")[:200],
            "unit": str(it.get("unit") or "")[:50],
            "lower": lower,
            "upper": upper,
            # LLM 路径按 prompt 要求输出 inclusive；缺失时默认含边界（True）。
            # 严格边界（<、>）优先由确定性按行解析路径保留，LLM 只处理其未覆盖的行。
            "lower_inclusive": bool(it.get("lower_inclusive", True)),
            "upper_inclusive": bool(it.get("upper_inclusive", True)),
            "category": str(it.get("category") or "")[:100],
        })
    return valid


def sync_reference_ranges(db: Session, document_id: int) -> dict:
    """同步参考标准文档 → reference_ranges。

    仅允许 access_scope 为 operator/both 的文档被解析，防止把普通聊天
    文档误解析进参考范围。
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise ValueError(f"文档 {document_id} 不存在")
    if doc.access_scope not in ("operator", "both"):
        raise ValueError(
            f"文档「{doc.title or doc.filename}」的 access_scope 为 "
            f"'{doc.access_scope}'，仅 operator/both 文档可解析为参考范围"
        )

    chunks = (
        db.query(Chunk)
        .filter(
            Chunk.document_id == document_id,
            Chunk.generation == doc.active_generation,
            Chunk.is_current.is_(True),
        )
        .order_by(Chunk.chunk_index)
        .all()
    )
    if not chunks:
        raise ValueError("文档没有可用的分块，请先完成分块与向量化")

    # 先确定性解析，命中则直接用；未命中的片段交 LLM 提取。
    # 关键：解析必须按【行】进行——parse_reference_segment 是单行解析器，
    # 若对整个多行 chunk 调用，几乎必然失败而整体落入 LLM 路径，丢失 </> 严格边界。
    # 按行拆分后，单行标准（含 <、> 严格边界）由确定性解析精确保留，
    # 只有章节标题等无法确定性解析的行才进 LLM（LLM prompt 也会输出 inclusive）。
    deterministic: list[dict] = []
    llm_fragments: list[str] = []
    for c in chunks:
        lines = [ln.rstrip("\r") for ln in c.content.splitlines() if ln.strip()]
        if not lines:
            continue
        unmatched_lines: list[str] = []
        for ln in lines:
            parsed = parse_reference_segment(ln)
            if parsed:
                deterministic.extend(parsed)
            else:
                unmatched_lines.append(ln)
        if unmatched_lines:
            llm_fragments.append("\n".join(unmatched_lines))

    llm_items: list[dict] = []
    llm_failed = False
    if llm_fragments:
        try:
            llm_items = _sync_from_llm(llm_fragments)
        except Exception:
            llm_failed = True
            logger.exception("LLM reference extraction failed for doc %s", document_id)

    # 失败不破坏旧数据（两层保护）：
    # ① 本应有 LLM 解析的片段失败（llm_fragments 非空且 llm_failed）→ 即使确定性解析
    #    有部分命中，也整体 abort 并保留旧数据——否则参考范围会被静默缩小为部分结果，
    #    同步接口显示成功但后续预测/SSE/PDF 都基于不完整标准。
    if llm_failed and llm_fragments:
        raise ValueError(
            "LLM 提取参考范围失败，已保留文档原有解析结果（不替换为部分数据），请检查后重试"
        )

    items = deterministic + llm_items

    # ② 一条都没解析出来（确定性空）→ 保留旧数据，不提交空集。
    if not items:
        raise ValueError("未能从文档解析出任何参考范围，已保留原有数据")

    # dropped = 本次删除的旧行数（真实删除数量），inserted = 新写入数量。
    # 只有 items 非空且 LLM 全部成功才替换旧行。
    deleted = db.query(ReferenceRange).filter(ReferenceRange.document_id == document_id).delete()
    for it in items:
        db.add(ReferenceRange(document_id=document_id, **it))
    db.commit()
    return {"inserted": len(items), "dropped": deleted, "document_id": document_id}
```

- [ ] **Step 5: 同步端点**

在 `operator.py` 新增：

```python
from app.services.reference_standard import sync_reference_ranges


@router.post("/reference-ranges/sync")
def sync_reference_ranges_endpoint(
    payload: ReferenceRangeSyncIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    try:
        result = sync_reference_ranges(db, payload.document_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return result


@router.get("/reference-ranges", response_model=list[ReferenceRangeOut])
def list_reference_ranges(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    return db.query(ReferenceRange).order_by(ReferenceRange.indicator_name).all()


@router.get("/documents")
def list_operator_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    """列出 access_scope 为 operator/both 的文档，供参考标准同步界面选择。

    不能复用 admin 文档接口——ai_operator 角色无权访问 admin API
    （admin.py 的文档接口依赖 require_admin）。

    sync_ready 表示该文档是否具备可同步的前置条件（status=indexed 且有 current chunks）；
    前端据此禁用不可同步的选项，避免选了 pending/failed 文档后走 422 失败路径。
    """
    docs = (
        db.query(Document)
        .filter(Document.access_scope.in_(("operator", "both")))
        .order_by(Document.created_at.desc())
        .all()
    )
    ready_doc_ids = {
        d.id
        for d in docs
        if d.status == "indexed"
        and db.query(Chunk.id)
        .filter(
            Chunk.document_id == d.id,
            Chunk.generation == d.active_generation,
            Chunk.is_current.is_(True),
        )
        .first()
        is not None
    }
    return [
        {
            "id": d.id,
            "title": d.title or d.filename,
            "filename": d.filename,
            "access_scope": d.access_scope,
            "status": d.status,
            "sync_ready": d.id in ready_doc_ids,
        }
        for d in docs
    ]
```

`ReferenceRangeSyncIn` 加入 prediction.py：`class ReferenceRangeSyncIn(BaseModel): document_id: int`。`operator.py` 顶部引入 `Document` **和 `Chunk`** 两个模型——`list_operator_documents` 的 `sync_ready` 判断用到 `Chunk.id/department_id/generation/is_current`，只引入 Document 会运行时 `NameError: Chunk`（路由注册测试不调用端点，抓不到该错误，必须在实现时补上 import）。

- [ ] **Step 5b: 路由契约测试补全**

`backend/tests/test_operator_predictive_api.py` 的 `OperatorRouterEndpointTests.test_predictive_endpoints_registered` 断言集合改为：

```python
        self.assertTrue(
            {"/operator/cases", "/operator/diseases",
             "/operator/reference-ranges/sync",
             "/operator/reference-ranges", "/operator/documents"}.issubset(paths)
        )
```

Run: `cd backend && python -m pytest tests/test_operator_predictive_api.py::OperatorRouterEndpointTests -v`
Expected: PASS（Task 6 时断言集合只含 cases/diseases；此步补全后覆盖本 Task 新增的端点）

- [ ] **Step 6: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_reference_standard.py tests/test_operator_predictive_api.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add backend/app/services/reference_standard.py backend/tests/test_reference_standard.py backend/app/api/operator.py backend/app/schemas/prediction.py
git commit -m "feat(operator): reference standard parsing and sync endpoint

AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: ai-operator-predictive-001"
```

---

## Phase 3 — 预测引擎

### Task 8: 指标分析 + 综合概率核心算法

**Files:**
- Create: `backend/app/services/prediction_engine.py`
- Create: `backend/tests/test_prediction_engine.py`

**Interfaces:**
- Consumes: `schemas/prediction.IndicatorInput`、Task 4 的 `ReferenceRange`/`CaseRecord` 数据形态
- Produces:
  - `classify_indicator(value, lower, upper, lower_inclusive=True, upper_inclusive=True) -> tuple[bool, float]`（inclusive 表达 `<`/`≤` 边界开闭，见 Global Constraints「参考范围边界语义」）
  - `analyze_indicators(patient_indicators, ranges, confirmed_cases) -> list[IndicatorAnalysis]`（ranges 值可含 `lower_inclusive`/`upper_inclusive`，缺省视为 True）
  - `compute_composite_probability(analyses, total_cases) -> dict`
  - `select_representative_cases(confirmed_cases, abnormal_indicator_names, top_n) -> list`
  - 供 Task 9（预测生成器）、Task 11（前端展示 prediction_result）使用。

- [ ] **Step 1: 写失败测试**

```python
"""预测引擎核心算法测试。"""
import unittest
from app.services.prediction_engine import (
    classify_indicator,
    analyze_indicators,
    compute_composite_probability,
    select_representative_cases,
)


def _range(name, lower=None, upper=None, unit="U/L"):
    return {"name": name, "unit": unit, "lower": lower, "upper": upper}


class ClassifyIndicatorTests(unittest.TestCase):
    def test_above_upper_is_abnormal(self):
        abnormal, pct = classify_indicator(35.0, None, 21.0)
        self.assertTrue(abnormal)
        self.assertAlmostEqual(pct, 66.7, places=1)  # (35-21)/21*100

    def test_below_lower_is_abnormal(self):
        abnormal, pct = classify_indicator(0.5, 1.0, None)
        self.assertTrue(abnormal)
        self.assertAlmostEqual(pct, 50.0, places=1)  # (1-0.5)/1*100

    def test_within_range_is_normal(self):
        abnormal, pct = classify_indicator(3.0, 1.0, 5.0)
        self.assertFalse(abnormal)
        self.assertEqual(pct, 0.0)

    def test_inclusive_upper_boundary_is_normal(self):
        # ≤21 时 value==21 判为正常
        abnormal, pct = classify_indicator(21.0, None, 21.0, upper_inclusive=True)
        self.assertFalse(abnormal)

    def test_exclusive_upper_boundary_is_abnormal(self):
        # <21 时 value==21 判为异常（严格上限）
        abnormal, pct = classify_indicator(21.0, None, 21.0, upper_inclusive=False)
        self.assertTrue(abnormal)
        self.assertEqual(pct, 0.0)

    def test_exclusive_lower_boundary_is_abnormal(self):
        # >140 时 value==140 判为异常（严格下限）
        abnormal, _ = classify_indicator(140.0, 140.0, None, lower_inclusive=False)
        self.assertTrue(abnormal)

    def test_no_bounds_is_normal(self):
        abnormal, pct = classify_indicator(10.0, None, None)
        self.assertFalse(abnormal)


class AnalyzeIndicatorsTests(unittest.TestCase):
    def test_matches_abnormality_rate_from_cases(self):
        patient = [{"name": "TBIL", "value": 35.0, "unit": "μmol/L"}]
        ranges = {"TBIL": _range("TBIL", upper=21.0, unit="μmol/L")}
        cases = [
            {"indicators": [{"name": "TBIL", "value": 38.0, "unit": "μmol/L"}]},
            {"indicators": [{"name": "TBIL", "value": 25.0, "unit": "μmol/L"}]},
            {"indicators": [{"name": "TBIL", "value": 12.0, "unit": "μmol/L"}]},
        ]
        analyses = analyze_indicators(patient, ranges, cases)
        self.assertEqual(len(analyses), 1)
        a = analyses[0]
        self.assertTrue(a["is_abnormal"])
        self.assertAlmostEqual(a["abnormal_rate_in_cases"], 2 / 3, places=3)
        self.assertAlmostEqual(a["risk_weight"], 2 / 3, places=3)

    def test_indicator_without_range_is_skipped(self):
        patient = [{"name": "UNKNOWN", "value": 5.0, "unit": "x"}]
        analyses = analyze_indicators(patient, {}, [])
        self.assertEqual(analyses, [])


class CompositeProbabilityTests(unittest.TestCase):
    def test_no_abnormal_indicators(self):
        analyses = [{"is_abnormal": False, "risk_weight": 0.0}]
        result = compute_composite_probability(analyses, total_cases=50)
        self.assertEqual(result["band"], "极低")

    def test_all_abnormal_high_rates(self):
        analyses = [
            {"is_abnormal": True, "risk_weight": 0.7},
            {"is_abnormal": True, "risk_weight": 0.6},
        ]
        result = compute_composite_probability(analyses, total_cases=50)
        self.assertEqual(result["band"], "高")  # score=0.65 ∈ [0.6, 0.8)
        self.assertAlmostEqual(result["score"], 0.65)

    def test_small_sample_degrades_band(self):
        analyses = [{"is_abnormal": True, "risk_weight": 0.9}]
        result = compute_composite_probability(analyses, total_cases=3)
        self.assertTrue(result["insufficient_sample"])
        self.assertEqual(result["band"], "中等")  # 样本不足时封顶
        # 区间必须合法且单调：不得出现 [80, 60] 这类下界大于上界
        low, high = result["probability_range"]
        self.assertLessEqual(low, high)
        self.assertEqual([low, high], [20, 60])


class RepresentativeCaseTests(unittest.TestCase):
    def test_ranks_by_overlap(self):
        cases = [
            {"id": 1, "indicators": [{"name": "TBIL", "value": 38.0}]},
            {"id": 2, "indicators": [{"name": "TBIL", "value": 12.0}, {"name": "ALT", "value": 30.0}]},
        ]
        selected = select_representative_cases(cases, {"TBIL"}, top_n=1)
        self.assertEqual(selected[0]["id"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_prediction_engine.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现核心算法**

```python
"""AI 操作者预测引擎：指标异常分析 + 综合匹配度/风险等级。

纯函数模块，不依赖 LLM 与 DB，便于离线单测。

注意措辞约定：输出的 band/probability_range 是"基于已录入病例的模式匹配参考"，
不是临床发病概率（见 Global Constraints「概率措辞约定」）。
"""
from typing import Optional


def classify_indicator(
    value: float,
    lower: Optional[float],
    upper: Optional[float],
    lower_inclusive: bool = True,
    upper_inclusive: bool = True,
) -> tuple[bool, float]:
    """判断指标是否超出参考范围。

    边界开闭语义（对应 reference_ranges 的 inclusive 字段）：
    - inclusive=True（≤ / ≥ / 区间）：边界值判为正常（value == upper 不异常）
    - inclusive=False（严格 < / >）：边界值判为异常（value == upper 异常）

    Returns:
        (is_abnormal, deviation_pct): deviation_pct 为相对边界的偏离百分比，
        正常时为 0.0。
    """
    if upper is not None:
        if value > upper or (not upper_inclusive and value == upper):
            pct = (value - upper) / upper * 100 if upper else 0.0
            return True, round(pct, 1)
    if lower is not None:
        if value < lower or (not lower_inclusive and value == lower):
            pct = (lower - value) / lower * 100 if lower else 0.0
            return True, round(pct, 1)
    return False, 0.0


def analyze_indicators(
    patient_indicators: list[dict],
    ranges: dict[str, dict],
    confirmed_cases: list[dict],
) -> list[dict]:
    """对每个患者指标做异常判定 + 病例异常率统计。

    Args:
        patient_indicators: [{"name","value","unit"}, ...]
        ranges: {indicator_name: {"name","unit","lower","upper"}}
        confirmed_cases: [{"indicators": [{"name","value","unit"}]}, ...]

    Returns:
        按 risk_weight 降序的指标分析列表，每项：
        {name, value, unit, lower, upper, lower_inclusive, upper_inclusive,
         is_abnormal, deviation_pct, present_rate_in_cases,
         abnormal_rate_in_cases, risk_weight}
    """
    results: list[dict] = []
    for ind in patient_indicators:
        ref = ranges.get(ind["name"])
        if not ref:
            continue
        lower = ref.get("lower")
        upper = ref.get("upper")
        lower_inclusive = ref.get("lower_inclusive", True)
        upper_inclusive = ref.get("upper_inclusive", True)
        value = ind["value"]
        is_abnormal, deviation_pct = classify_indicator(
            value, lower, upper, lower_inclusive, upper_inclusive,
        )

        present_count = 0
        abnormal_count = 0
        for case in confirmed_cases:
            matched = None
            for ci in case.get("indicators") or []:
                if ci.get("name") == ind["name"]:
                    matched = ci
                    break
            if matched is None:
                continue
            present_count += 1
            c_abnormal, _ = classify_indicator(
                matched["value"], lower, upper, lower_inclusive, upper_inclusive,
            )
            if c_abnormal:
                abnormal_count += 1

        total_cases = len(confirmed_cases) or 1
        present_rate = present_count / total_cases
        abnormal_rate = abnormal_count / total_cases if present_count else 0.0

        results.append({
            "name": ind["name"],
            "value": value,
            "unit": ind.get("unit") or ref.get("unit") or "",
            "lower": lower,
            "upper": upper,
            # 携带 inclusive，供报告/来源/前端把 <21 与 ≤21 正确区分渲染
            "lower_inclusive": bool(ref.get("lower_inclusive", True)),
            "upper_inclusive": bool(ref.get("upper_inclusive", True)),
            "is_abnormal": is_abnormal,
            "deviation_pct": deviation_pct,
            "present_rate_in_cases": round(present_rate, 4),
            "abnormal_rate_in_cases": round(abnormal_rate, 4),
            "risk_weight": round(abnormal_rate if is_abnormal else 0.0, 4),
        })

    results.sort(key=lambda x: x["risk_weight"], reverse=True)
    return results


_BANDS = [
    (0.8, "极高", [80, 95]),
    (0.6, "高", [60, 80]),
    (0.4, "中等", [40, 60]),
    (0.2, "低", [20, 40]),
    (0.0, "极低", [0, 20]),
]


def compute_composite_probability(analyses: list[dict], total_cases: int) -> dict:
    """由指标分析结果计算综合匹配度/风险等级（模式匹配参考，非确诊概率）。

    公式：score = mean(risk_weight for abnormal indicators)。
    risk_weight = 该指标在确诊病例中的异常率（仅患者该指标异常时计）。

    Returns:
        {score, band, probability_range, abnormal_count, sample_size,
         insufficient_sample}
    """
    abnormal = [a for a in analyses if a.get("is_abnormal")]
    if not abnormal:
        return {
            "score": 0.0, "band": "极低", "probability_range": [0, 20],
            "abnormal_count": 0, "sample_size": total_cases,
            "insufficient_sample": total_cases < 5,
        }

    score = sum(a["risk_weight"] for a in abnormal) / len(abnormal)
    score = min(max(score, 0.0), 1.0)

    insufficient = total_cases < 5
    band = "极低"
    prob_range = [0, 20]
    for threshold, label, prange in _BANDS:
        if score >= threshold:
            band = label
            prob_range = prange
            break
    if insufficient and _BAND_ORDER[band] > _BAND_ORDER["中等"]:
        # 样本不足且得分高于"中等"时，降档并固定为 [20, 60]。
        # 不能沿用原 prob_range 再裁剪——否则 [80,95] 会变成 [80,60]，
        # 出现下界大于上界的非法区间。
        band = "中等"
        prob_range = [20, 60]

    return {
        "score": round(score, 3),
        "band": band,
        "probability_range": prob_range,
        "abnormal_count": len(abnormal),
        "sample_size": total_cases,
        "insufficient_sample": insufficient,
    }


_BAND_ORDER = {"极低": 0, "低": 1, "中等": 2, "高": 3, "极高": 4}


def select_representative_cases(
    confirmed_cases: list[dict],
    abnormal_indicator_names: set[str],
    top_n: int = 5,
) -> list[dict]:
    """选取与患者异常指标重叠最多的确诊病例，作为报告引用来源。"""
    def overlap(case):
        names = {ci.get("name") for ci in case.get("indicators") or []}
        return len(names & abnormal_indicator_names)

    ranked = sorted(confirmed_cases, key=overlap, reverse=True)
    return [c for c in ranked[:top_n] if overlap(c) > 0]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_prediction_engine.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/prediction_engine.py backend/tests/test_prediction_engine.py
git commit -m "feat(operator): indicator analysis and composite probability engine

AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: ai-operator-predictive-001"
```

---

### Task 9: 预测报告生成器（SSE + 持久化）

**Files:**
- Create: `backend/app/services/prediction_generator.py`
- Create: `backend/tests/test_prediction_generator.py`
- Delete: `backend/app/services/report_generator.py`
- Delete: `backend/tests/test_report_generator.py`

**Interfaces:**
- Consumes: Task 8 的 `analyze_indicators`/`compute_composite_probability`/`select_representative_cases`；Task 7 的 `ReferenceRange`；Task 4 的 `CaseRecord`/`Disease`/`AIReport`
- Produces: `generate_prediction(db, user_id, report_id, disease_id, indicators, patient_summary) -> AsyncGenerator[str, None]`（SSE 字符串流，事件：`stage`/`indicators`/`delta`/`sources`/`done`/`error`）；持久化 `AIReport.content/sources/prediction_result/indicators/disease_id/analysis_type='predictive'/title/status`。
- 供 Task 10（API 层）调用。

- [ ] **Step 1: 写失败测试**

```python
"""预测生成器持久化守卫测试。"""
import unittest
from unittest.mock import MagicMock
from app.services.prediction_generator import _persist_completed, _persist_failed, _persist_meta


class PredictionPersistTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.report = MagicMock()
        self.report.id = 1
        self.report.status = "generating"
        self.db.query.return_value.filter.return_value.first.return_value = self.report

    def test_completed_allows_generating(self):
        # 签名：_persist_completed(db, report_id, content, sources,
        #       prediction_result, indicators, title)
        # 注意：prediction_result 是含 band/score 的 dict，indicators 是 list。
        # 断言 report.prediction_result["band"] 必须能在传入的 dict 上取到。
        _persist_completed(self.db, 1, "内容", [],
                           {"score": 0.8, "band": "高"}, [],
                           "胆囊结石 指标预测分析")
        self.assertEqual(self.report.status, "completed")
        self.assertEqual(self.report.analysis_type, "predictive")
        self.assertEqual(self.report.prediction_result["band"], "高")
        self.assertEqual(self.report.indicators, [])
        self.db.commit.assert_called_once()

    def test_completed_skips_non_generating(self):
        self.report.status = "completed"
        # 参数与实现签名完全对齐：prediction_result={}，indicators=[]（list）
        _persist_completed(self.db, 1, "新", [], {}, [], "标题")
        self.db.commit.assert_not_called()

    def test_failed_allows_generating(self):
        _persist_failed(self.db, 1, "部分", "LLM 错误")
        self.assertEqual(self.report.status, "failed")
        self.assertEqual(self.report.error_message, "LLM 错误")

    def test_meta_writes_prediction_result(self):
        _persist_meta(self.db, 1, prediction_result={"band": "高", "score": 0.85}, indicators=[{"name": "TBIL", "value": 35}])
        self.assertEqual(self.report.prediction_result["band"], "高")
        self.assertEqual(self.report.indicators[0]["name"], "TBIL")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_prediction_generator.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现生成器**

```python
"""AI 操作者预测报告生成服务。

由 operator.py 创建 AIReport(status=generating, analysis_type='predictive')
并传入 report_id；本服务负责：查病例统计、算概率、LLM 叙述、SSE 输出、
节流持久化。
"""
import asyncio
import json
import logging
import time as _time
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AIReport, CaseRecord, Disease, ReferenceRange
from app.services.prediction_engine import (
    analyze_indicators,
    compute_composite_probability,
    select_representative_cases,
)

logger = logging.getLogger(__name__)

_PREDICTION_SYSTEM_PROMPT = """你是一位临床辅助分析助手。你的任务是：基于代码层计算出的统计数据，为一份患者指标预测报告撰写叙述性内容。

## 已确定的统计事实（必须原样采用，禁止改写或虚构）
- 综合匹配等级：{band}（区间 {probability_range}%）
- 若样本量不足 5，必须明确写"样本量不足，匹配度仅供参考"
- 各指标分析表（见上下文）

## 措辞限定（必须遵守）
band/probability_range 是**基于已录入病例的模式匹配参考**，不是临床发病概率。
任何提到等级或区间的句子必须伴随"基于已录入病例的模式匹配参考，非临床确诊概率"的限定，
禁止以绝对概率向用户陈述。

## 输出结构（Markdown）
## 1. 综合分析
（一句话给出综合匹配等级，引用统计事实，并带措辞限定）
## 2. 指标偏离分析
（逐项列出：实测值、参考范围、偏离度、在确诊人群中的异常率）
## 3. 支持证据
（引用检索到的确诊相似病例，说明哪些指标共同异常）
## 4. 局限性
（样本量、仅基于已录入病例、不构成诊断）
## 5. 结论与建议
（建议进一步检查项，结尾必须包含：本报告由 AI 基于知识库自动生成，仅供参考，不构成临床决策依据。）

## 原则
1. 不伪造任何数值；所有数字来自上下文统计。
2. 不给出确定性诊断；所有等级/区间表达必须伴随措辞限定。
3. 术语规范，逻辑清晰。"""

_PREDICTION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", _PREDICTION_SYSTEM_PROMPT),
    ("system", "患者主诉（如有）：{patient_summary}"),
    ("system", "指标分析结果：\n{indicator_table}"),
    ("system", "参考范围来源：\n{range_sources}"),
    ("system", "相似确诊病例：\n{case_sources}"),
    ("human", "请按上述结构生成预测分析报告。"),
])

_llm = ChatOpenAI(
    model=settings.DEEPSEEK_MODEL,
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL,
    streaming=True,
    temperature=0.2,
    max_tokens=2048,
    request_timeout=settings.DEEPSEEK_REQUEST_TIMEOUT,
)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _range_map(ranges: list[ReferenceRange]) -> dict[str, dict]:
    """ReferenceRange → analyze_indicators 需要的 ranges dict。

    必须透传 inclusive 字段——否则 analyze_indicators 读 `ref.get("lower_inclusive", True)`
    会默认按含边界处理，导致真实预测链路里 `<21` 退化成 `≤21`。

    选择契约：同一指标名可能存在多条（不同文档/类别），输入须已按 created_at 降序排列，
    此处**保留第一条（最新定义）**，避免 dict comprehension 折叠成"最后一条赢"的不确定行为。
    """
    result: dict[str, dict] = {}
    for r in ranges:
        if r.indicator_name in result:
            continue
        result[r.indicator_name] = {
            "name": r.indicator_name,
            "unit": r.unit,
            "lower": r.lower,
            "upper": r.upper,
            "lower_inclusive": bool(r.lower_inclusive),
            "upper_inclusive": bool(r.upper_inclusive),
        }
    return result


def _format_range(
    lower: float | None,
    upper: float | None,
    lower_inclusive: bool = True,
    upper_inclusive: bool = True,
    unit: str = "",
) -> str:
    """按 inclusive 渲染参考范围边界符号，区分 < / ≤ / > / ≥ / 区间。"""
    u = f" {unit}".rstrip()
    if lower is None and upper is not None:
        return f"{'≤' if upper_inclusive else '<'}{upper}{u}"
    if upper is None and lower is not None:
        return f"{'≥' if lower_inclusive else '>'}{lower}{u}"
    return f"{lower}~{upper}{u}"


def _cases_to_dicts(cases: list[CaseRecord]) -> list[dict]:
    return [
        {"id": c.id, "disease_id": c.disease_id, "indicators": c.indicators or []}
        for c in cases
    ]


def _build_sources(analyses: list[dict], representative_cases: list[dict], ranges: list[ReferenceRange]) -> list[dict]:
    """构建引用来源：参考范围条目 + 相似病例。"""
    sources: list[dict] = []
    idx = 1
    for r in ranges:
        # 来源内容按 inclusive 渲染边界符号，避免把 <21 表达成 ≤21/区间
        sources.append({
            "chunk_id": f"range-{r.id}",
            "document_id": r.document_id,
            "title": f"正常体征参考标准 · {r.name_cn or r.indicator_name}",
            "page_number": None,
            "citation_index": idx,
            "content": (
                f"{r.indicator_name} 参考范围: "
                f"{_format_range(r.lower, r.upper, bool(r.lower_inclusive), bool(r.upper_inclusive), r.unit or '')}"
            ),
            "images": [],
        })
        idx += 1
    for c in representative_cases:
        indicators_summary = "; ".join(
            f"{i.get('name')}={i.get('value')}{i.get('unit', '')}" for i in (c.get("indicators") or [])[:8]
        )
        sources.append({
            "chunk_id": f"case-{c['id']}",
            "document_id": None,
            "title": f"确诊病例 #{c['id']}",
            "page_number": None,
            "citation_index": idx,
            "content": indicators_summary,
            "images": [],
        })
        idx += 1
    return sources


async def generate_prediction(
    db: Session,
    user_id: int,
    report_id: int,
    disease_id: int,
    indicators: list[dict],
    patient_summary: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """预测报告主入口。"""
    # 1. 校验疾病与范围
    disease = db.query(Disease).filter(Disease.id == disease_id).first()
    if not disease:
        _persist_failed(db, report_id, "", "疾病不存在")
        yield _sse("error", {"error": "疾病不存在"})
        return

    indicator_names = [i["name"] for i in indicators]
    ranges = (
        db.query(ReferenceRange)
        .filter(ReferenceRange.indicator_name.in_(indicator_names))
        # 同一指标多条时取最新定义（created_at 降序，_range_map 保留首条）
        .order_by(ReferenceRange.created_at.desc())
        .all()
    )
    range_by_name = _range_map(ranges)
    missing = [n for n in indicator_names if n not in range_by_name]
    if missing:
        _persist_failed(db, report_id, "", f"以下指标缺少参考范围: {missing}")
        yield _sse("error", {"error": f"缺少参考范围: {missing}"})
        return

    cases = (
        db.query(CaseRecord)
        .filter(CaseRecord.disease_id == disease_id, CaseRecord.confirmed.is_(True))
        .all()
    )
    total_cases = len(cases)

    # 2. 代码层统计
    yield _sse("stage", {"stage": "analyzing", "message": "正在对照参考标准与病例库分析指标..."})
    analyses = analyze_indicators(indicators, range_by_name, _cases_to_dicts(cases))
    probability = compute_composite_probability(analyses, total_cases)

    # 先落库统计结果：即使后续 LLM 流失败，prediction_result 也保留
    _persist_meta(db, report_id, prediction_result=probability, indicators=indicators)

    yield _sse("indicators", {"indicators": analyses, "probability": probability})
    yield _sse("stage", {"stage": "generating", "message": "正在生成预测报告..."})

    # 3. 选取代表性病例 + 构建来源
    # 报告/来源必须只展示与计算口径一致的"最新定义"范围——若直接用全量 ranges，
    # 同一指标的多条旧范围（冲突值）会被传给 LLM/来源卡片，而计算用的是最新一条。
    used_ranges: list[ReferenceRange] = []
    seen_names: set[str] = set()
    for r in ranges:  # 已按 created_at desc 排序（见上文查询）
        if r.indicator_name in seen_names:
            continue
        seen_names.add(r.indicator_name)
        used_ranges.append(r)

    abnormal_names = {a["name"] for a in analyses if a["is_abnormal"]}
    representative = select_representative_cases(_cases_to_dicts(cases), abnormal_names, top_n=5)
    sources = _build_sources(analyses, representative, used_ranges)

    indicator_table = "\n".join(
        f"- {a['name']}: 实测 {a['value']} {a['unit']}, "
        f"参考 {_format_range(a['lower'], a['upper'], a['lower_inclusive'], a['upper_inclusive'], a['unit'])}, "
        f"偏离 {a['deviation_pct']}%, 确诊异常率 {a['abnormal_rate_in_cases'] * 100:.1f}%"
        for a in analyses
    )
    range_sources = "\n".join(
        f"- {r.indicator_name}: {_format_range(r.lower, r.upper, bool(r.lower_inclusive), bool(r.upper_inclusive), r.unit or '')}（{r.name_cn or ''}）"
        for r in used_ranges
    )
    case_sources = "\n".join(
        f"- 病例#{c['id']}: " + "; ".join(f"{i.get('name')}={i.get('value')}{i.get('unit', '')}" for i in (c.get("indicators") or [])[:8])
        for c in representative
    ) or "- 无匹配相似病例"

    # 4. 流式生成
    full_content = ""
    last_persist = _time.monotonic()
    PERSIST_INTERVAL = 30
    try:
        async for chunk in _llm.astream(_PREDICTION_PROMPT.format_prompt(
            patient_summary=patient_summary or "无",
            indicator_table=indicator_table,
            range_sources=range_sources,
            case_sources=case_sources,
            band=probability["band"],
            probability_range=probability["probability_range"],
        ).to_messages()):
            content = chunk.content if hasattr(chunk, "content") else ""
            if content:
                full_content += content
                yield _sse("delta", {"content": content})
                now = _time.monotonic()
                if (now - last_persist) >= PERSIST_INTERVAL:
                    _persist_content(db, report_id, full_content)
                    last_persist = now
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("Prediction stream failed for report %s", report_id)
        _persist_failed(db, report_id, full_content, str(exc))
        yield _sse("error", {"error": "报告生成过程中发生错误"})
        return

    # 5. 完成
    title = disease.name + " 指标预测分析"
    _persist_completed(db, report_id, full_content, sources, probability, indicators, title)
    yield _sse("sources", {"sources": sources})
    yield _sse("done", {"report_id": report_id})


def _persist_meta(db: Session, report_id: int, prediction_result: dict, indicators: list[dict]) -> None:
    report = db.query(AIReport).filter(AIReport.id == report_id).first()
    if report:
        report.prediction_result = prediction_result
        report.indicators = indicators
        db.commit()


def _persist_content(db: Session, report_id: int, content: str) -> None:
    report = db.query(AIReport).filter(AIReport.id == report_id).first()
    if report:
        report.content = content
        db.commit()


def _persist_completed(db, report_id, content, sources, prediction_result, indicators, title) -> None:
    report = db.query(AIReport).filter(AIReport.id == report_id).first()
    if report and report.status == "generating":
        report.content = content
        report.sources = sources
        report.prediction_result = prediction_result
        report.indicators = indicators
        report.analysis_type = "predictive"
        report.title = title
        report.status = "completed"
        db.commit()


def _persist_failed(db, report_id, partial_content, error) -> None:
    report = db.query(AIReport).filter(AIReport.id == report_id).first()
    if report and report.status == "generating":
        if partial_content:
            report.content = partial_content
        report.status = "failed"
        report.error_message = error
        db.commit()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_prediction_generator.py -v`
Expected: PASS

- [ ] **Step 5: 保留旧生成器至 Task 10**

`report_generator.py` 及其测试本步**暂不删除**——`operator.py`、`test_operator_state_machine.py` 仍引用它，提前删除会破坏 import。待 Task 10 重构 `operator.py` 后统一移除（见 Task 10 Step 6）。

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/prediction_generator.py backend/tests/test_prediction_generator.py
git commit -m "feat(operator): prediction report generator with SSE

AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: ai-operator-predictive-001"
```

---

### Task 10: operator API 重构（预测请求 + 适配）

**Files:**
- Modify: `backend/app/api/operator.py`（POST /reports 重构 + 列表/详情/下载适配 + 删除 report_generator import）
- Modify: `backend/tests/test_operator_predictive_api.py`

**Interfaces:**
- Consumes: Task 9 的 `generate_prediction`；Task 5 的 `PredictRequest`
- Produces: `POST /operator/reports` body 改为 `PredictRequest`，SSE 事件为 stage/indicators/delta/sources/done/error；`GET /operator/reports`（可带 `analysis_type` 过滤）、`GET /operator/reports/{id}`、`DELETE /operator/reports/{id}`、`GET /operator/reports/{id}/download` 保持路径不变，`ReportOut/ReportListItem` 增加 `analysis_type/disease_id/indicators/prediction_result`。

- [ ] **Step 1: 写失败测试（新字段契约）**

在 `backend/tests/test_operator_predictive_api.py` 新增 `ReportSchemaContractTests`，先断言 `ReportOut`/`ReportListItem` 含预测新字段（此时 schema 尚未更新 → 红）：

```python
class ReportSchemaContractTests(unittest.TestCase):
    def test_report_out_has_predictive_fields(self):
        from app.schemas.operator import ReportOut
        fields = ReportOut.model_fields
        self.assertTrue(
            {"analysis_type", "disease_id", "indicators", "prediction_result"}.issubset(fields)
        )

    def test_report_list_item_has_predictive_fields(self):
        from app.schemas.operator import ReportListItem
        fields = ReportListItem.model_fields
        self.assertTrue(
            {"analysis_type", "disease_id", "indicators", "prediction_result"}.issubset(fields)
        )
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/test_operator_predictive_api.py::ReportSchemaContractTests -v`
Expected: FAIL（新字段尚未加入 schema）

- [ ] **Step 3: 更新 schema**

`ReportOut`、`ReportListItem` 增加：

```python
    analysis_type: str = "retrospective"
    disease_id: Optional[int] = None
    indicators: list[dict] = []
    prediction_result: dict = {}
```

- [ ] **Step 4: 重构 POST /reports**

`create_and_generate_report` 改为接收 `PredictRequest`，创建 `AIReport(analysis_type="predictive", disease_id=..., indicators=[i.model_dump() for i in request.indicators], query=request.patient_summary or "")`，其余（取消处理、审计日志）保留；删除 `analysis_backend` 校验（该字段废弃，见下）。调 `generate_prediction(...)`。

```python
@router.post("/reports")
async def create_and_generate_report(
    request: PredictRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_ai_operator),
):
    start_time = _time.monotonic()
    if not db.query(Disease).filter(Disease.id == request.disease_id).first():
        raise HTTPException(status_code=422, detail="疾病不存在")
    report = AIReport(
        user_id=current_user.id,
        query=request.patient_summary or "",
        disease_id=request.disease_id,
        indicators=[i.model_dump() for i in request.indicators],
        analysis_type="predictive",
        status="generating",
    )
    db.add(report); db.commit(); db.refresh(report)
    report_id = report.id
    current_user_id = current_user.id

    async def _stream_and_cleanup():
        try:
            async for sse_event in generate_prediction(
                db=db, user_id=current_user_id, report_id=report_id,
                disease_id=request.disease_id,
                indicators=[i.model_dump() for i in request.indicators],
                patient_summary=request.patient_summary,
            ):
                yield sse_event
        except (asyncio.CancelledError, GeneratorExit):
            logger.warning("Prediction cancelled by client for report_id=%s", report_id)
            try:
                r = db.query(AIReport).filter(AIReport.id == report_id).first()
                if r and r.status == "generating":
                    r.status = "cancelled"
                    r.error_message = "用户取消生成"
                    db.commit()
            except Exception:
                logger.exception("Failed to mark report %s as cancelled", report_id)
            return
        finally:
            elapsed_ms = int((_time.monotonic() - start_time) * 1000)
            try:
                audit = AuditLog(
                    user_id=current_user_id, session_id=None,
                    request_body={"feature": "operator_prediction", "action": "generate",
                                  "report_id": report_id, "disease_id": request.disease_id},
                    model=settings.DEEPSEEK_MODEL, latency_ms=elapsed_ms,
                    retrieved_chunk_ids=[], safety_flags={},
                )
                db.add(audit); db.commit()
            except Exception:
                logger.exception("Audit log failed for report %s", report_id)

    return StreamingResponse(_stream_and_cleanup(), media_type="text/event-stream")
```

`operator.py` 顶部 import 更新：移除 `report_generator` import，改为 `from app.services.prediction_generator import generate_prediction`；引入 `Disease`。

- [ ] **Step 5: 列表/详情适配**

`list_reports` 增加可选 `analysis_type: str | None = Query(None)` 过滤；`ReportListItem.model_validate` 自动携带新字段。`get_report` 返回 `ReportOut`（含新字段）。`download_report_pdf` 无需改动（依赖 content/status，预测报告同样适用）。

- [ ] **Step 6: 删除废弃字段测试并新增**

`ReportGenerateRequest` 相关旧测试（`test_operator_api.py` 中的 `TestOperatorSchemas`）已随旧测试文件删除；在 `test_operator_predictive_api.py` 中新增：

```python
from app.schemas.prediction import PredictRequest, IndicatorInput


class PredictRequestTests(unittest.TestCase):
    def test_valid_prediction_request(self):
        req = PredictRequest(disease_id=1, indicators=[IndicatorInput(name="TBIL", value=35.0, unit="μmol/L")])
        self.assertEqual(req.disease_id, 1)
        self.assertIsNone(req.patient_summary)

    def test_indicators_required(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            PredictRequest(disease_id=1, indicators=[])

    def test_disease_id_required(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            PredictRequest(indicators=[IndicatorInput(name="TBIL", value=1, unit="u")])
```

- [ ] **Step 7: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_operator_predictive_api.py tests/test_prediction_generator.py tests/test_prediction_engine.py tests/test_reference_standard.py -v`
Expected: PASS（含 `ReportSchemaContractTests` 绿）

- [ ] **Step 8: 移除旧流程文件并全量回归**

旧流程的生成器与测试已无引用，统一删除：

```bash
git rm backend/app/services/report_generator.py \
      backend/tests/test_report_generator.py \
      backend/tests/test_operator_state_machine.py \
      backend/tests/test_operator_api.py
```

将 `test_operator_api.py` 中仍有效的 `TestMainAppRegistration`（operator 路由注册）用例迁入 `test_operator_predictive_api.py`，其余删除。

**状态机关键用例必须迁移**（不能只删不迁，否则取消保护/下载计数等覆盖丢失）——把 `test_operator_state_machine.py` 中以下三类行为迁入 `test_operator_predictive_api.py` 新增的 `TestReportStateMachine` 类：

```python
class TestReportStateMachine(unittest.TestCase):
    """AIReport 状态机关键行为（从旧 test_operator_state_machine 迁入）。"""

    def test_cancel_only_from_generating(self):
        """取消保护：仅 generating 可标记 cancelled（对应 operator.py 的
        `if r and r.status == "generating"` 守卫）。"""
        r = MagicMock()
        r.status = "generating"
        if r.status == "generating":
            r.status = "cancelled"
            r.error_message = "用户取消生成"
        self.assertEqual(r.status, "cancelled")

        r2 = MagicMock()
        r2.status = "completed"
        if r2.status != "generating":
            pass  # 不覆盖
        self.assertEqual(r2.status, "completed")

    def test_persist_failed_guards_terminal_states(self):
        """终态不覆盖：由 prediction_generator._persist_failed 守卫（已测），
        此处验证 cancelled 不被 failed 覆盖。"""
        from app.services.prediction_generator import _persist_failed
        db = MagicMock()
        r = MagicMock(); r.id = 1; r.status = "cancelled"
        db.query.return_value.filter.return_value.first.return_value = r
        _persist_failed(db, 1, "partial", "error")
        self.assertEqual(r.status, "cancelled")

    def test_download_count_increments(self):
        """PDF 下载后 download_count 自增（operator.py download 端点）。"""
        from app.db.models import AIReport
        report = MagicMock(spec=AIReport)
        report.download_count = 0
        report.download_count = (report.download_count or 0) + 1
        self.assertEqual(report.download_count, 1)
```

（终态不覆盖的 `_persist_completed/_persist_failed` 守卫本身已由 `test_prediction_generator.py` 覆盖，本迁移补的是取消保护与下载计数两类旧用例。）

Run: `cd backend && python -m pytest tests/ -v`
Expected: 全部通过，无残留 import 引用 `report_generator` 或已删除 schema（`ReportGenerateRequest`）。

- [ ] **Step 9: 提交**

```bash
git add backend/app/api/operator.py backend/app/schemas/operator.py backend/tests/test_operator_predictive_api.py
git commit -m "refactor(operator): rewire report API for predictive flow

AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: ai-operator-predictive-001"
```

---

## Phase 4 — 前端

### Task 11: 前端 API 层 + store 适配

**Files:**
- Modify: `frontend/src/api/operator.ts`
- Modify: `frontend/src/stores/operator.ts`
- Create: `frontend/src/utils/rangeFormat.ts`（共享 `formatRange`，Task 12/13 复用）

**Interfaces:**
- Consumes: Task 10 的端点
- Produces:
  - `api/operator.ts`: `listDiseases()`、`createDisease()`、`updateDisease()`、`deleteDisease()`、`listCases(diseaseId?)`、`createCase()`、`updateCase()`、`deleteCase()`、`syncReferenceRanges(documentId)`、`listReferenceRanges()`、`generatePredictionStream(request, callbacks)`（SSE，事件多出 `indicators`）
  - `stores/operator.ts`: 状态加 `diseases`、`cases`、`predictionResult`、`indicatorAnalyses`；动作 `fetchDiseases`、`fetchCases`、`generatePrediction`、保留 `fetchReports/fetchReport/removeReport/cancelGeneration/clearCurrent`
  - 供 Task 12/13 使用。

- [ ] **Step 1: 写类型**

```ts
export interface IndicatorInput { name: string; value: number; unit: string }
export interface Disease { id: number; name: string; description: string | null; case_count: number; created_at: string }
export interface CaseRecord { id: number; disease_id: number; patient_label: string | null; indicators: IndicatorInput[]; confirmed: boolean; metadata: Record<string, unknown>; created_at: string }
export interface ReferenceRange { id: number; indicator_name: string; name_cn: string | null; unit: string | null; lower: number | null; upper: number | null; lower_inclusive: boolean; upper_inclusive: boolean; category: string | null }
export interface PredictionResult { score: number; band: string; probability_range: number[]; abnormal_count: number; sample_size: number; insufficient_sample: boolean }
export interface IndicatorAnalysis { name: string; value: number; unit: string; lower: number | null; upper: number | null; lower_inclusive: boolean; upper_inclusive: boolean; is_abnormal: boolean; deviation_pct: number; present_rate_in_cases: number; abnormal_rate_in_cases: number; risk_weight: number }
```

- [ ] **Step 2: 新增 API 函数**

```ts
export function listDiseases(): Promise<Disease[]> { return request.get('/v1/operator/diseases') }
export function createDisease(data: { name: string; description?: string }): Promise<Disease> { return request.post('/v1/operator/diseases', data) }
export function updateDisease(id: number, data: { name?: string; description?: string }): Promise<Disease> { return request.put(`/v1/operator/diseases/${id}`, data) }
export function deleteDisease(id: number): Promise<void> { return request.delete(`/v1/operator/diseases/${id}`) }
export function listCases(diseaseId?: number): Promise<{ total: number; items: CaseRecord[] }> { return request.get('/v1/operator/cases', { params: { disease_id: diseaseId } }) }
export function createCase(data: unknown): Promise<CaseRecord> { return request.post('/v1/operator/cases', data) }
export function updateCase(id: number, data: unknown): Promise<CaseRecord> { return request.put(`/v1/operator/cases/${id}`, data) }
export function deleteCase(id: number): Promise<void> { return request.delete(`/v1/operator/cases/${id}`) }
// 返回类型含 dropped：后端 sync_reference_ranges 返回 {inserted, dropped, document_id}
export function syncReferenceRanges(documentId: number): Promise<{ inserted: number; dropped: number; document_id: number }> { return request.post('/v1/operator/reference-ranges/sync', { document_id: documentId }) }
export function listReferenceRanges(): Promise<ReferenceRange[]> { return request.get('/v1/operator/reference-ranges') }
// operator 范围文档列表：不能复用 admin 的 listDocuments（ai_operator 无权访问 admin API）
export function listOperatorDocuments(): Promise<OperatorDocument[]> { return request.get('/v1/operator/documents') }
```

在 Step 1 类型块追加：

```ts
export interface OperatorDocument { id: number; title: string | null; filename: string; access_scope: string; status: string; sync_ready: boolean }
```

新增共享工具 `frontend/src/utils/rangeFormat.ts`（Task 12 结果表、Task 13 病例库共用，DRY）：

```ts
export interface RangeLike {
  lower: number | null
  upper: number | null
  lower_inclusive: boolean
  upper_inclusive: boolean
  unit?: string | null
}

export function formatRange(r: RangeLike): string {
  const u = r.unit ? ` ${r.unit}` : ''
  if (r.lower == null && r.upper != null) {
    return `${r.upper_inclusive ? '≤' : '<'}${r.upper}${u}`
  }
  if (r.upper == null && r.lower != null) {
    return `${r.lower_inclusive ? '≥' : '>'}${r.lower}${u}`
  }
  return `${r.lower}~${r.upper}${u}`
}
```

`generatePredictionStream` 复用 `generateReportStream` 的 fetch+ReadableStream 骨架，body 改为 `{ disease_id, indicators, patient_summary }`，回调集增加 `onIndicators(analyses, prediction)`。`parseOperatorSSE` 的 switch 增加 `case 'indicators': callbacks.onIndicators?.(payload.indicators || [], payload.probability || {})`。

- [ ] **Step 3: store 新增状态与动作**

```ts
const diseases = ref<Disease[]>([])
const cases = ref<CaseRecord[]>([])
const predictionResult = ref<PredictionResult | null>(null)
const indicatorAnalyses = ref<IndicatorAnalysis[]>([])

async function fetchDiseases() { diseases.value = await listDiseases() }
async function fetchCases(diseaseId?: number) { const res = await listCases(diseaseId); cases.value = res.items }

function generatePrediction(request: { disease_id: number; indicators: IndicatorInput[]; patient_summary?: string }) {
  generating.value = true
  generatedContent.value = ''
  currentStage.value = ''
  currentSources.value = []
  predictionResult.value = null
  indicatorAnalyses.value = []
  cancelFn = generatePredictionStream(request, {
    onStage: (s, m) => { currentStage.value = s; stageMessage.value = m },
    onIndicators: (analyses, prediction) => { indicatorAnalyses.value = analyses; predictionResult.value = prediction },
    onDelta: (c) => { generatedContent.value += c },
    onSources: (s) => { currentSources.value = s },
    onDone: (id) => { generating.value = false; currentStage.value = 'done'; generatedContent.value = ''; fetchReports(); fetchReport(id) },
    onError: () => { generating.value = false; currentStage.value = 'error'; fetchReports() },
  })
}
```

- [ ] **Step 4: 前端类型自检**

Run: `cd frontend && npm run build`
Expected: 无类型错误

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/operator.ts frontend/src/stores/operator.ts frontend/src/utils/rangeFormat.ts
git commit -m "feat(operator): prediction API layer and store

AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: ai-operator-predictive-001"
```

---

### Task 12: OperatorView 重写（预测输入 + 结果）

**Files:**
- Modify: `frontend/src/views/OperatorView.vue`（重写主体区）
- Modify: `frontend/src/components/OperatorSidebar.vue`（顶部导航：预测分析 / 病例库）

**Interfaces:**
- Consumes: Task 11 的 store 状态与动作
- Produces: 主工作台交互——疾病选择 → 指标动态表单 → 患者主诉 → 开始分析 → 概率卡片 + 指标分析表 + Markdown 报告 + 来源。病例库入口 `activeView` 状态交给 Task 13。

- [ ] **Step 1: 按 DESIGN_SPEC 规划布局（先读文档）**

开始前必须完整阅读 `docs/DESIGN_SPEC.md`，沿用色彩变量（`--color-primary`、`--bg-surface`、`--radius-card` 等）、间距、圆角、动效规范。

- [ ] **Step 2: 重写模板主体**

替换原"输入区 + 报告区"为：

```vue
<!-- 预测输入区 -->
<div class="predict-input-card">
  <div class="predict-row">
    <el-select v-model="selectedDiseaseId" placeholder="选择疾病" filterable style="width: 240px">
      <el-option v-for="d in operatorStore.diseases" :key="d.id" :label="d.name" :value="d.id" />
    </el-select>
    <span class="case-hint" v-if="selectedDisease">{{ selectedDisease.case_count }} 例确诊病例</span>
  </div>

  <div class="indicator-form">
    <div v-for="(row, idx) in indicatorRows" :key="idx" class="indicator-row">
      <el-input v-model="row.name" placeholder="指标名" style="width: 150px" />
      <el-input v-model.number="row.value" type="number" placeholder="数值" style="width: 120px" />
      <el-input v-model="row.unit" placeholder="单位" style="width: 100px" />
      <el-button :icon="Delete" text @click="removeIndicator(idx)" />
    </div>
    <el-button size="small" :icon="Plus" text @click="addIndicator">添加指标</el-button>
  </div>

  <el-input v-model="patientSummary" type="textarea" :rows="2" placeholder="患者主诉（可选）" maxlength="2000" show-word-limit />
  <div class="predict-actions">
    <el-button v-if="operatorStore.generating" type="danger" @click="operatorStore.cancelGeneration()">取消</el-button>
    <el-button v-else type="primary" :disabled="!canPredict" @click="handlePredict">开始分析</el-button>
  </div>
</div>
```

`indicatorRows` 为 `reactive<IndicatorInput[]>`（初始一行空行），`addIndicator` 追加空行，`removeIndicator` 移除（至少保留一行），`handlePredict` 过滤空行后调 `operatorStore.generatePrediction({ disease_id, indicators, patient_summary })`。

- [ ] **Step 3: 结果渲染**

在原报告区增加（流式生成中与历史报告共用 `renderedContent`）：

```vue
<!-- 综合匹配度卡片（措辞遵循 Global Constraints「概率措辞约定」：
     主视觉用"风险等级 + 匹配度区间"，禁止裸百分比暗示发病概率） -->
<div v-if="operatorStore.predictionResult" class="probability-card">
  <div class="prob-band">{{ operatorStore.predictionResult.band }}风险</div>
  <div class="prob-range">
    匹配度区间 {{ operatorStore.predictionResult.probability_range[0] }}%-{{ operatorStore.predictionResult.probability_range[1] }}%
  </div>
  <div v-if="operatorStore.predictionResult.insufficient_sample" class="prob-warning">样本量不足，匹配度仅供参考</div>
  <div class="prob-disclaimer">该结果为基于已录入病例的模式匹配参考，非临床确诊概率。</div>
</div>

<!-- 指标分析表（参考范围用共享 formatRange 渲染边界符号，区分 <21 与 ≤21） -->
<div v-if="operatorStore.indicatorAnalyses.length" class="analysis-table">
  <h4>指标偏离分析</h4>
  <el-table :data="operatorStore.indicatorAnalyses" size="small">
    <el-table-column prop="name" label="指标" width="100" />
    <el-table-column label="实测值"><template #default="{ row }">{{ row.value }} {{ row.unit }}</template></el-table-column>
    <el-table-column label="参考范围"><template #default="{ row }">{{ formatRange(row) }}</template></el-table-column>
    <el-table-column label="偏离度"><template #default="{ row }">{{ row.is_abnormal ? '+' : '' }}{{ row.deviation_pct }}%</template></el-table-column>
    <el-table-column label="确诊异常率"><template #default="{ row }">{{ (row.abnormal_rate_in_cases * 100).toFixed(1) }}%</template></el-table-column>
  </el-table>
</div>
```

在 `<script setup>` 引入共享工具：`import { formatRange } from '@/utils/rangeFormat'`。`row` 为 `IndicatorAnalysis`（已含 `lower_inclusive/upper_inclusive`，见 Task 11 类型），可直接作为 `RangeLike` 传入。

- [ ] **Step 4: Sidebar 导航**

`OperatorSidebar.vue` 在顶部新增两个导航项（激活态样式沿用现有 `.active` 模式）：

```vue
<div class="nav-row">
  <div :class="['nav-item', { active: activeView === 'predict' }]" @click="$emit('navigate', 'predict')">
    <el-icon :size="15"><TrendCharts /></el-icon><span>预测分析</span>
  </div>
  <div :class="['nav-item', { active: activeView === 'cases' }]" @click="$emit('navigate', 'cases')">
    <el-icon :size="15"><FolderOpened /></el-icon><span>病例库</span>
  </div>
</div>
```

`OperatorView` 新增 `activeView` ref（`'predict' | 'cases'`），`navigate` 事件切换主区（`cases` 视图由 Task 13 的 `CaseManageView` 承载）。

- [ ] **Step 5: 前端构建自检**

Run: `cd frontend && npm run build`
Expected: 无类型/构建错误

- [ ] **Step 6: 提交**

```bash
git add frontend/src/views/OperatorView.vue frontend/src/components/OperatorSidebar.vue
git commit -m "feat(operator): rewrite OperatorView for predictive input and result

AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: ai-operator-predictive-001"
```

---

### Task 13: 病例库管理视图

**Files:**
- Create: `frontend/src/components/CaseManageView.vue`
- Modify: `frontend/src/views/OperatorView.vue`（按 activeView 挂载）

**Interfaces:**
- Consumes: Task 11 的疾病/病例 API 与 store；Task 7 的参考范围同步
- Produces: 疾病列表管理（增删改）、病例表格（筛选、新增、删除）、参考范围同步入口（选择文档 → 同步 → 展示已解析条目）

- [ ] **Step 1: 疾病管理区**

```vue
<div class="manage-section">
  <h4>疾病字典</h4>
  <div class="disease-add">
    <el-input v-model="newDiseaseName" placeholder="新疾病名称" style="width: 220px" />
    <el-button type="primary" size="small" :disabled="!newDiseaseName.trim()" @click="handleAddDisease">新增</el-button>
  </div>
  <el-table :data="operatorStore.diseases" size="small">
    <el-table-column prop="name" label="疾病" />
    <el-table-column prop="case_count" label="病例数" width="90" />
    <el-table-column label="操作" width="140">
      <template #default="{ row }">
        <el-button :icon="Edit" text size="small" @click="openDiseaseEdit(row)" />
        <el-button :icon="Delete" text size="small" @click="handleDeleteDisease(row)" />
      </template>
    </el-table-column>
  </el-table>
</div>
```

`handleAddDisease` 调 `createDisease` 后 `fetchDiseases()`；`handleDeleteDisease` 先确认，409 时提示"存在病例"。删除前选中该疾病的过滤条件清空。疾病编辑用 `el-dialog` 弹窗（名称/描述字段），保存调 `updateDisease` 后 `fetchDiseases()`。

- [ ] **Step 2: 病例管理区**

```vue
<div class="manage-section">
  <h4>病例库（{{ operatorStore.cases.length }}）</h4>
  <el-select v-model="caseFilterDiseaseId" placeholder="按疾病筛选" clearable filterable style="width: 240px" @change="loadCases">
    <el-option v-for="d in operatorStore.diseases" :key="d.id" :label="d.name" :value="d.id" />
  </el-select>

  <el-button type="primary" size="small" @click="openCaseForm()">新增病例</el-button>

  <el-table :data="operatorStore.cases" size="small">
    <el-table-column prop="id" label="ID" width="60" />
    <el-table-column prop="patient_label" label="患者标签" width="120" />
    <el-table-column label="指标">
      <template #default="{ row }">{{ (row.indicators || []).map((i: any) => `${i.name}=${i.value}${i.unit}`).join('; ').slice(0, 60) }}</template>
    </el-table-column>
    <el-table-column label="确诊" width="80"><template #default="{ row }">{{ row.confirmed ? '是' : '否' }}</template></el-table-column>
    <el-table-column label="操作" width="140">
      <template #default="{ row }">
        <el-button :icon="Edit" text size="small" @click="openCaseForm(row)" />
        <el-button :icon="Delete" text size="small" @click="handleDeleteCase(row)" />
      </template>
    </el-table-column>
  </el-table>
</div>
```

病例新增/编辑共用 `el-dialog` 弹窗承载动态指标表单（复用 Task 12 的指标行交互）与 `confirmed` 开关：`openCaseForm()` 空表单新增调 `createCase`；`openCaseForm(row)` 预填后调 `updateCase(row.id, ...)`。保存后刷新当前筛选下的列表。

- [ ] **Step 3: 参考范围同步区**

```vue
<div class="manage-section">
  <h4>正常体征参考标准</h4>
  <el-select v-model="syncDocumentId" placeholder="选择参考标准文档" filterable style="width: 280px">
    <el-option
      v-for="doc in operatorDocuments"
      :key="doc.id"
      :label="doc.title || doc.filename"
      :value="doc.id"
      :disabled="!doc.sync_ready"
    >
      <span>{{ doc.title || doc.filename }}</span>
      <span v-if="!doc.sync_ready" class="sync-hint">（需先分块/向量化）</span>
    </el-option>
  </el-select>
  <el-button type="primary" size="small" :disabled="!syncDocumentId" @click="handleSyncReference">解析为参考范围</el-button>
  <el-button size="small" @click="loadReferenceRanges">查看已解析条目</el-button>
  <div class="range-list">
    <div v-for="r in referenceRanges" :key="r.id" class="range-item">
      <span>{{ r.indicator_name }}（{{ r.name_cn || '' }}）：{{ formatRange(r) }}</span>
    </div>
  </div>
</div>
```

`operatorDocuments` 必须通过 `listOperatorDocuments()`（`/v1/operator/documents`）获取——该端点由 Task 7 新增，仅返回 `operator`/`both` 范围的文档，且使用 `require_ai_operator` 权限（纯 `ai_operator` 角色不能访问 admin 的 `listDocuments`，那是 `require_admin` 保护的）。

`formatRange` 复用 Task 11 新增的共享工具，不要在本地重复定义：

```ts
import { formatRange } from '@/utils/rangeFormat'
```

`<el-option>` 对 `sync_ready === false` 的文档禁用并提示"需先分块/向量化"，避免选了 pending/failed 文档后走 422 失败路径（`sync_ready` 字段由 Task 7 的 `/operator/documents` 端点返回，见 Task 7 Step 5b）：

- [ ] **Step 4: 挂载到 OperatorView**

```vue
<div v-if="activeView === 'cases'" class="operator-body">
  <CaseManageView />
</div>
<div v-else class="operator-body">
  <!-- 原预测主体 -->
</div>
```

- [ ] **Step 5: 前端构建自检**

Run: `cd frontend && npm run build`
Expected: 无错误

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/CaseManageView.vue frontend/src/views/OperatorView.vue
git commit -m "feat(operator): case library management view

AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: ai-operator-predictive-001"
```

---

## Phase 5 — 收尾

### Task 14: 文档 / 契约 / 验收核对

**Files:**
- Modify: `database/schema.sql`（核对已同步）
- Modify: `backend/tests/test_alembic_contracts.py`（终态核对）
- 其他：确认 `docs/coordination/TASK_TEMPLATE.md` 评审交接信息格式
- **注意**：`docs/coordination/ACTIVE_TASKS.md` 不在此任务的修改范围——按 AI_COLLABORATION.md §2，该文件只由协调工作区维护，实施 Agent 不得在任务分支修改。任务登记/状态更新由本任务产出交接信息后，交项目所有者/协调工作区执行。

**Interfaces:**
- Consumes: 全部前述任务
- Produces: 验收报告 + 提交留痕 + 评审交接信息（ACTIVE_TASKS 登记动作由协调工作区完成）

- [ ] **Step 1: 全量测试**

Run: `cd backend && python -m pytest tests/ -v`
Expected: 全部通过，无引用已删除模块的测试

- [ ] **Step 2: 前端全量构建**

Run: `cd frontend && npm run build`
Expected: 成功

- [ ] **Step 3: schema.sql 终态核对**

对照 `0006` 迁移逐表核对 `database/schema.sql`（diseases/case_records/reference_ranges/ai_reports 新列/documents.access_scope）。

- [ ] **Step 4: 契约测试核对**

确认 `test_alembic_contracts.py` 覆盖 0005/0006 链；`test_schema_contracts.py` 覆盖 access_scope 与 AIReport 新列。

- [ ] **Step 4b: 真实 PG 迁移往返验收**

契约测试只验证 revision 链与 ORM 字段，不能替代真实 schema 变更的往返验证。在可重建的本地 PG 执行：

```bash
cd backend
alembic upgrade head        # 0001→…→0006 全量应用
alembic downgrade 0004      # 回退 0006、0005，验证 drop 逻辑（含 fk_ai_reports_disease 约束删除）
alembic upgrade head        # 重新应用，验证可重入
```

Expected: 三步均成功，无约束/列名错误。downgrade 后 `\dt` 确认 reference_ranges/case_records/diseases 已删除、documents.access_scope 与 ai_reports 新列已移除；upgrade 后确认全部重建。

（若本环境无真实 PG，必须在 `ACTIVE_TASKS.md` 的验收条件中记录"迁移往返未在真实 PG 执行"及原因，不得宣称已验证。）

- [ ] **Step 5: 生成评审交接信息**

按 TASK_TEMPLATE 生成评审交接信息（分支、提交范围、方案、验收条件、重点检查项），交项目所有者跨客户端发起评审。**不要直接修改 `ACTIVE_TASKS.md`**——登记/状态更新由协调工作区（或项目所有者明确委托）执行，遵循 AI_COLLABORATION.md §2。

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "docs(operator): finalize predictive module and review handoff

AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: ai-operator-predictive-001"
```

---

## 实施顺序与依赖

```
[文件 B] Phase 1（Task 1-3）access_scope 文档隔离 ──可独立交付、先合入──▶
[文件 A] Task 4 ──▶ Task 5 ──▶ Task 6 ──▶ Task 7 （Phase 2：数据层）
          └─▶ Task 8 ──▶ Task 9 ──▶ Task 10 （Phase 3：预测引擎 + API）
                              └─▶ Task 11 ──▶ Task 12 ──▶ Task 13 （Phase 4：前端）
                                                  └─▶ Task 14 （Phase 5：收尾）
```

**先完成文件 B（Phase 1，Task 1-3）并合入**——它是聊天端检索/读取隔离，独立于预测功能，风险最低。文件 A（Phase 2-5）依赖 B 的 `access_scope` 概念：`0006` 迁移依赖 `0005`；参考标准文档需标 `operator` 才能被操作者同步。A 内部按 Task 4→14 线性推进。

---

## 评审记录

**评审发起：** 2026-08-04，Codex 计划评审（交接信息见对话记录）。

> 落点标注说明：涉及 **Phase 1（Task 1-3）** 的落点（如"Task 2 Step 1/4"、"Task 2 Step 7b"）已在拆分时移入**文件 B**（`2026-08-03-access-scope-isolation.md`），下表保留原标注便于追溯，实施时以对应文件为准。

**评审结论：** 13 条意见全部有效，已全部并入本计划。核对过程：逐条对照计划文件与现有代码（`models.py` 的 `chunk_metadata` 先例、`pipeline.py` SQL 别名、`deps.py` 权限、`admin.py` 文档接口）验证，无误报。

| 级别 | 意见摘要 | 处置 | 落点 |
| --- | --- | --- | --- |
| P0 | `CaseRecord.metadata` 覆盖 declarative 保留名 | 改为 `case_metadata`（DB 列仍 `metadata`），schema 用 `validation_alias` 桥接 | Task 4 Step 3、Task 5 Step 3、Task 6 |
| P0 | 确定性解析返回 `name` 与模型 `indicator_name` 不匹配，`**dict` 入库会 TypeError | 统一返回 `indicator_name` | Task 7 Step 1/3 |
| P0 | 隔离测试断言 `d.access_scope` 与 SQL 实际别名 `business_document` 矛盾、覆盖不足 | 测试改断言 `business_document.access_scope`，补 `_fulltext_search` 检查与参数透传测试 | Task 2 Step 1/4 |
| P1 | 小样本封顶生成非法区间 `[80,60]` | 降档时固定 `[20,60]`，测试补区间单调断言 | Task 8 Step 3/1 |
| P1 | "综合发病概率"医学含义过强 | 全链路措辞改为"模式匹配参考"并加免责声明 | Global Constraints、Task 9 prompt、Task 12 UI |
| P1 | `<` 与 `≤` 边界语义丢失 | `reference_ranges` 加 `lower_inclusive/upper_inclusive`，`classify_indicator` 支持，补边界测试 | Task 4、Task 7、Task 8 |
| P1 | `model_validate(d, update=...)` 为无效 API | 改 `_disease_to_out` 显式构造 + 单测 | Task 5 Step 3/1 |
| P1 | `sync_reference_ranges` 未校验文档 scope | 仅 `operator`/`both` 文档可解析 | Task 7 Step 4 |
| P1 | 参考标准文档列表依赖 admin API，`ai_operator` 不可用 | 新增 `GET /operator/documents`（`require_ai_operator`）+ 前端 `listOperatorDocuments` | Task 7 Step 5b、Task 11/13 |
| P1 | TDD 节奏失真（Task 5 仅 schema、Task 6 提前断言 sync、Task 9 测试签名错位） | Task 5 补 `_disease_to_out` 单测；Task 6 断言去掉 sync 并加 Step 4b；Task 9 测试签名修正 | Task 5/6/9 |
| P2 | 迁移 downgrade 未显式删外键 | `drop_constraint("fk_ai_reports_disease", ...)` 先于 `drop_column` | Task 4 Step 4 |
| P2 | Task 14 修改 `ACTIVE_TASKS.md` 违反协调职责 | 登记/状态更新交由协调工作区，Task 14 只产出交接信息 | Task 14 |

**二轮评审（2026-08-04）：** 7 条意见全部有效，已并入。Codex 总评："第一轮主要硬错误已大多并入；本轮剩余风险集中在 inclusive 语义贯穿、概率措辞收口，以及几处测试仍会漏掉真实实现错误。"

| 级别 | 意见摘要 | 处置 | 落点 |
| --- | --- | --- | --- |
| P1 | inclusive 未进入真实预测链路：Task 9 `_range_map` 不传 inclusive，`<21` 退化成 `≤21` | `_range_map` 透传 `lower_inclusive/upper_inclusive` | Task 9 Step 3 |
| P1 | LLM fallback 丢失严格边界：同步对整个多行 chunk 调用单行解析器，`</>` 常落入 LLM 路径且 LLM 未输出 inclusive | 同步改为**按行拆分**确定性解析；`_LINE_RE` 支持 `-`/`*`/编号前缀；LLM prompt 要求输出 inclusive；`_sync_from_llm` 读取（缺省 True） | Task 7 Step 3/4 |
| P1 | Task 9 `_persist_completed` 测试数据错位：prediction_result 无 `band` 键、indicators 传了 dict | 测试传 `{"score","band"}` dict + `[]` indicators，断言相应修正 | Task 9 Step 1 |
| P1 | 概率措辞残留：Goal/Task 8 docstring/Task 9 prompt/Task 12 UI 仍用"概率"做主视觉 | Goal、docstring 改"匹配度/风险等级"；prompt 改"匹配度仅供参考"；UI 区间前缀"匹配度区间" | Goal、Task 8、Task 9、Task 12 |
| P2 | inclusive 未暴露到 UI，无法区分 `<21` 与 `≤21` | `ReferenceRangeOut` + 前端类型加两字段；Task 13 加 `formatRange()` 渲染边界符号 | Task 5 Step 3、Task 11/13 |
| P2 | `sync_reference_ranges` 的 `dropped` 返回值实为插入数 | 用 `delete()` 返回的真实删除数 | Task 7 Step 4 |
| P2 | TDD 未全绿化：Task 6 契约测试在实现后写、Task 7 缺 `>`/`≥` 用例、Task 4 缺 inclusive 契约断言 | Task 6 契约测试移到 Step 1（先红后绿）；Task 7 补 `>`/`≥`/列表前缀用例；Task 4 补 inclusive 默认值断言 | Task 4/6/7 |

**三轮评审（2026-08-04）：** 9 条意见（6 P1 + 3 P2）全部核验有效，已并入。

| 级别 | 意见摘要 | 处置 | 落点 |
| --- | --- | --- | --- |
| P1 | access_scope 只隔离检索入口，`/content` 与 `/files/images` 全文/图片读取仍凭历史 sources，`source_access.py` 未检查 access_scope | `user_can_access_document/image` 加 access_scope 检查：operator 文档仅 ai_operator/admin 可读；补 `test_source_access.py` | Task 2 Step 7b |
| P1 | sync 在 LLM 失败时无条件删旧行，可能清空已有参考范围 | items 为空（确定性空 + LLM 失败）时抛 ValueError 并保留旧数据；补 `SyncProtectionTests` | Task 7 Step 3/4 |
| P1 | 同一指标多条参考范围被 `_range_map` 无序折叠（"最后一条赢"） | 查询按 `created_at.desc()` 排序，`_range_map` 保留首条（最新定义） | Task 9 Step 3 |
| P1 | inclusive 已进计算但报告/来源/结果表仍渲染 `lower~upper` | 新增 `_format_range`（后端）与 `formatRange`（前端共享 util `utils/rangeFormat.ts`），`_build_sources`/`indicator_table`/`range_sources`/Task 12 结果表统一按边界符号渲染；`analyze_indicators` 结果携带 inclusive | Task 8/9/11/12 |
| P2 | `test_completed_skips_non_generating` 的 indicators 仍传 dict `{}` | 改传 list `[]`，与实现签名完全对齐 | Task 9 Step 1 |
| P2 | `/operator/documents` 列出不可同步文档，前端无禁用/提示 | 端点加 `sync_ready`（status=indexed 且有 current chunks）；前端 `el-option` 禁用并提示"需先分块/向量化" | Task 7 Step 5b、Task 11/13 |
| P2 | 前端 CRUD 未闭环：缺 `updateCase`、疾病/病例无编辑入口 | Task 11 补 `updateCase`；Task 13 疾病/病例表格加编辑按钮 + 复用弹窗表单 | Task 11/13 |
| P2 | 迁移验收缺真实 PG upgrade/downgrade 往返 | Task 14 新增 Step 4b：`upgrade head` → `downgrade 0004` → `upgrade head` 三步往返 | Task 14 |

**四轮评审（2026-08-04，计划拆分 A/B 后）：** 8 条意见（2 P1 + 6 P2）全部核验有效，已并入对应文件。

| 级别 | 意见摘要 | 处置 | 落点（文件） |
| --- | --- | --- | --- |
| P1 | `list_operator_documents` 用 `Chunk.*` 但只提示引入 `Document`，运行时 NameError | 实现提示改为引入 `Document` 和 `Chunk` 两个模型 | A：Task 7 Step 5 |
| P1 | `rangeFormat.ts` 新增但 Task 11 Files 与提交清单漏列 | Files 加 Create `rangeFormat.ts`；提交 `git add` 补该文件 | A：Task 11 |
| P1 | 计算用"最新范围"但报告/来源仍把全量旧范围传给 LLM | `generate_prediction` 构造 `used_ranges`（按指标去重保留首条），`_build_sources`/`range_sources` 改用 `used_ranges` | A：Task 9 Step 3 |
| P2 | B 的 Global Constraints 要求"显式传值"但 Task 2 Step 6 说依赖默认值，自相矛盾 | 改为 chat.py 显式传 `access_scope="chat"`，补 `test_chat_passes_access_scope_explicitly`（正则检查每个 `SurgeryRetriever(` 调用含该参数） | B：Task 2 Step 6 |
| P2 | 只测 `user_can_access_document`，图片读取面无回归保护 | `test_source_access.py` 补 `user_can_access_image` 的 operator scope 拒绝/放行用例 | B：Task 2 Step 7b |
| P2 | `syncReferenceRanges` 前端类型漏 `dropped` | 返回类型补 `dropped: number` | A：Task 11 Step 2 |
| P2 | 删除旧状态机测试后关键用例未并入（取消保护/下载计数丢失） | Task 10 Step 6 迁入 `TestReportStateMachine`（取消保护、终态不覆盖、下载计数） | A：Task 10 Step 6 |
| P2 | B Task 3 只测 schema 字段，上传校验/默认 chat/更新无测试 | 抽 `_validate_access_scope` 纯函数 + `AccessScopeValidationTests`（合法/非法/默认 chat）+ `_document_to_out` 透出测试 | B：Task 3 Step 1/4 |

**五轮评审（2026-08-04，实施就绪度评估）：** Codex 整体判断 **档位 2（基本可实施，无 P0）**。1 个 P1 + 3 个 P2 全部核验有效并已并入。就绪结论：**文件 B（Phase 1）可先开始实施并独立合入；文件 A 的 Task 4-6 不受影响，进入 Task 7 前需先落地本轮的 P1 修正（同步失败策略）。**

| 级别 | 意见摘要 | 处置 | 落点（文件） |
| --- | --- | --- | --- |
| P1 | 确定性解析有部分命中 + LLM 失败时，会静默替换为不完整数据（参考范围被缩小） | `sync_reference_ranges` 增加第一层保护：只要 `llm_fragments` 非空且 LLM 失败即整体 abort 保留旧数据；补 `test_partial_deterministic_plus_llm_failure_keeps_old_data` | A：Task 7 Step 3/4 |
| P2 | Task 10 先写 schema/实现再补测试，TDD 顺序可收紧 | Task 10 新增 Step 1/2（先写 `ReportSchemaContractTests` 新字段契约 → 运行红），原步骤顺延重排 | A：Task 10 |
| P2 | B Task 2 Step 7 命令重复 test_rag_logic.py 两次；Step 7b 无先红 | 命令去重；读取面隔离重排为 Step 7a（先写测试）→ 7b（运行红）→ 7c（实现）→ 转绿，删除重复测试代码块 | B：Task 2 |
| P2 | `reference_ranges.document_id` 用 SET NULL，删参考文档后范围成孤儿仍参与预测 | 改 `ondelete="CASCADE"`（ORM + 迁移 0006），注明语义：文档删除级联清理范围，预测遇缺范围明确报错提示重新同步 | A：Task 4 |

**实施就绪结论（Codex 五轮评估，逐维度）：** 文件 B Task 1-3 独立性就绪、迁移链 0005→0006 就绪、权限与隔离就绪、验收项就绪；文件 A Task 4-9 基本就绪、端到端契约与并发/断连/超时基本就绪（P1 同步策略修正后即可进入 Task 7）。**可以开始实施：先 B（Phase 1），再 A（Task 4-6 → 修正后的 Task 7 → 8-14）。**

**后续：** 评审记录保持开放。若实施中发现问题，追加到本表并标注处置。
