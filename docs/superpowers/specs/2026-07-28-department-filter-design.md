# 科室分类筛选 — 设计方案

> 状态：已按评审意见修订，待审批
> 日期：2026-07-28
> 作者：Claude-Code

## 需求概述

管理员上传文档时可选择所属科室（如肝胆外科、神经外科等），用户提问时可选择科室范围进行定向检索，避免全库检索，提高检索精度和回答相关性。

---

## 1. 数据库层

### 1.1 新表：`departments`

```sql
CREATE TABLE departments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 1.2 修改表：`documents`

```sql
ALTER TABLE documents ADD COLUMN department_id INTEGER
    REFERENCES departments(id) ON DELETE RESTRICT;

CREATE INDEX idx_documents_department_id ON documents(department_id);
```

- `department_id` 可为空：兼容存量文档，存量文档的科室为 NULL（视为"未分类"）。
- `ON DELETE RESTRICT`：有关联文档的科室不允许删除，避免已归档知识的科室归属被无意清空。
- 停用科室使用 `is_active=false`，停用后不出现在用户侧/上传侧的默认可选列表中，但既有文档归属保持不变。

### 1.3 种子数据

默认预置以下外科常见科室：

| name |
|------|
| 肝胆外科 |
| 神经外科 |
| 骨科 |
| 心胸外科 |
| 泌尿外科 |
| 胃肠外科 |
| 甲状腺乳腺外科 |
| 血管外科 |
| 烧伤整形外科 |
| 麻醉科 |
| 其他 |

`id` 由数据库生成，业务代码不得硬编码种子数据 ID。

---

## 2. 后端层

### 2.1 模型层 (`backend/app/db/models.py`)

新增 `Department` 模型：

```python
class Department(Base):
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

`Document` 模型新增字段：

```python
department_id = Column(Integer, ForeignKey("departments.id", ondelete="RESTRICT"), nullable=True)
department = relationship("Department", back_populates="documents")
```

`Department` 模型补充反向关系：

```python
documents = relationship("Document", back_populates="department")
```

### 2.2 Schema 层

**`backend/app/schemas/department.py`（新文件）：**

```python
class DepartmentOut(BaseModel):
    id: int; name: str; description: Optional[str]
    is_active: bool; created_at: datetime

class DepartmentCreate(BaseModel):
    name: str  # min_length=1, max_length=100
    description: Optional[str] = None

class DepartmentUpdate(BaseModel):
    name: Optional[str] = None  # min_length=1, max_length=100
    description: Optional[str] = None
    is_active: Optional[bool] = None
```

**`backend/app/schemas/document.py` 修改：**

`DocumentOut` 新增：
```python
department_id: Optional[int] = None
department_name: Optional[str] = None
```

`DocumentUploadResponse` 新增：
```python
department_id: Optional[int] = None
```

### 2.3 API 层

#### 2.3.1 科室管理 API（`backend/app/api/admin.py`）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/admin/departments` | 列出所有科室（支持 `?active_only=true`） |
| `POST` | `/admin/departments` | 新增科室 |
| `PUT` | `/admin/departments/{id}` | 修改科室名称/描述/启用状态 |
| `DELETE` | `/admin/departments/{id}` | 删除科室（有关联文档时返回 409，提示先迁移或停用） |

校验规则：

- `POST /admin/departments`：`name` 去除首尾空白后不能为空，超过 100 字符返回 422；重名返回 409。
- `PUT /admin/departments/{id}`：科室不存在返回 404；重名返回 409；允许通过 `is_active=false` 停用科室。
- `DELETE /admin/departments/{id}`：科室不存在返回 404；存在关联文档返回 409；无关联文档时允许删除。

#### 2.3.2 文档上传 API 修改

`POST /admin/documents/upload` 新增表单参数：
```
department_id: int | None = Form(None)
```

上传前先校验 `department_id`：

- `department_id=None`：允许上传为未分类。
- `department_id` 不存在：返回 422，不保存文件、不创建文档记录。
- `department_id` 已停用：返回 422，不允许新上传文档归属到停用科室。

#### 2.3.3 文档列表 API 修改

`GET /admin/documents` 新增查询参数：
```
department_id: int | None = None  # 按科室筛选
```

返回的 `DocumentOut` 中包含 `department_id` 和 `department_name`。

#### 2.3.4 文档详情/更新 API

`PUT /admin/documents/{id}`（新增）— 允许修改文档的科室归属：
```json
{ "department_id": 1 }
```

校验规则：

- `department_id=None`：将文档改为未分类。
- `department_id` 不存在：返回 422。
- `department_id` 已停用：返回 422，不允许新归属到停用科室。

### 2.4 检索管线层 (`backend/app/rag/pipeline.py`)

#### 2.4.1 `SurgeryRetriever` 新增参数

```python
class SurgeryRetriever(BaseRetriever):
    db: Session
    top_k: int = settings.RETRIEVER_FINAL_TOP_K
    department_id: Optional[int] = None  # 新增
```

#### 2.4.2 向量检索过滤 (`_vector_search`)

在 SQL WHERE 子句中追加：
```sql
AND (:dept_id IS NULL OR business_document.department_id = :dept_id)
```

同时在 `hybrid_search` 函数签名和调用处传递 `department_id`。

#### 2.4.3 `pg_trgm` 文本检索过滤 (`_fulltext_search`)

同上，追加科室过滤条件。

### 2.5 聊天 API 层 (`backend/app/api/chat.py`)

#### 2.5.1 `AskRequest` 新增字段

```python
class AskRequest(BaseModel):
    content: str
    client_request_id: Optional[str] = None
    retry_message_id: Optional[int] = None
    department_id: Optional[int] = None  # 新增
```

#### 2.5.2 问答流中传递科室

```python
retriever = SurgeryRetriever(
    db=db,
    top_k=settings.RETRIEVER_FINAL_TOP_K,
    department_id=req.department_id,  # 新增
)
```

校验规则：

- `department_id=None`：全库检索，保持现有行为。
- `department_id` 不存在或已停用：返回 422，不进入 RAG 流式生成。
- 审计日志 `request_body` 增加 `department_id`，便于追踪检索范围。

### 2.6 配置层

无需新增配置项。科室筛选是可选行为，`department_id=None` 时退化为全库检索（兼容现有行为）。

---

## 3. 前端层

### 3.1 API 类型层 (`frontend/src/api/admin.ts`)

```typescript
// 新增
export interface DepartmentOut {
  id: number
  name: string
  description: string | null
  is_active: boolean
  created_at: string
}

// DocumentOut 新增字段
department_id: number | null
department_name: string | null

// uploadDocument 签名变更
export function uploadDocument(
  file: File,
  title?: string,
  department_id?: number  // 新增
): Promise<DocumentUploadResponse>

// 新增科室 API
export function listDepartments(activeOnly?: boolean): Promise<DepartmentOut[]>
```

### 3.2 聊天 API 层 (`frontend/src/api/chat.ts`)

```typescript
// askStream / callbacks 等：在请求体中加入 department_id
```

### 3.3 Store 层 (`frontend/src/stores/chat.ts`)

```typescript
// 新增状态
const selectedDepartmentId = ref<number | null>(null)

// sendMessage 时传递 department_id
```

### 3.4 管理员后台 (`frontend/src/views/AdminView.vue`)

#### 3.4.1 上传区域

在现有标题输入框和"选择文件"按钮之间新增科室下拉：

```
[标题输入框] [科室下拉: el-select] [选择文件] [上传]
```

- 组件：`<el-select>` 绑定 `uploadDepartmentId`
- 数据源：`GET /admin/departments?active_only=true`
- 默认选中："未分类"（值为空）

#### 3.4.2 文档表格

在"状态"列后新增"科室"列：

```html
<el-table-column label="科室" width="120">
  <template #default="{ row }">
    {{ row.department_name || '未分类' }}
  </template>
</el-table-column>
```

#### 3.4.3 搜索栏

左侧搜索区域新增科室筛选下拉，支持按科室过滤文档列表。

### 3.5 聊天界面 (`frontend/src/views/ChatView.vue`)

#### 3.5.1 科室选择器

在输入区域上方新增一行科室筛选栏：

```
[科室筛选：] [全部] [肝胆外科] [神经外科] [骨科] [心胸外科] ... [更多 ∨]
```

- 使用 `el-select` + 圆角标签样式
- 默认选中"全部科室"
- 选中特定科室后，后续提问仅在该科室范围内检索
- 选中项持久化到 `localStorage`

#### 3.5.2 视觉样式

- 科室选择器使用小号 `el-select`、圆角 Pill 样式
- 选中科室后在输入框左下角显示小标签提示当前筛选范围
- 全部科室时无提示

---

## 4. 兼容性与边界

| 场景 | 行为 |
|------|------|
| 存量文档（department_id = NULL） | 视为"未分类"，全库检索时包含 |
| 用户未选择科室（department_id = NULL） | 检索全部文档（现有行为不变） |
| 用户选择科室但该科室无文档 | 检索返回空 → AI 回复知识库无法回答 |
| 科室被停用（is_active = false） | 不再出现在用户侧/上传侧默认列表；既有文档仍保留归属 |
| 删除无关联文档的科室 | 删除成功 |
| 删除有关联文档的科室 | 后端返回 409，提示先迁移文档或停用科室 |
| 传入不存在/已停用的 department_id | 后端返回 422，不进入上传、更新或检索流程 |

---

## 5. 迁移文件

正式迁移入口为 Alembic。新建 `backend/alembic/versions/0003_add_departments.py`，并在迁移完成后同步更新 `database/schema.sql` 参考快照。

升级逻辑：

```sql
-- 1. 科室表
CREATE TABLE departments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. 文档表新增科室外键
ALTER TABLE documents ADD COLUMN department_id INTEGER
    REFERENCES departments(id) ON DELETE RESTRICT;

CREATE INDEX idx_documents_department_id ON documents(department_id);

-- 3. 种子数据
INSERT INTO departments (name) VALUES
    ('肝胆外科'), ('神经外科'), ('骨科'), ('心胸外科'),
    ('泌尿外科'), ('胃肠外科'), ('甲状腺乳腺外科'),
    ('血管外科'), ('烧伤整形外科'), ('麻醉科'), ('其他');
```

降级逻辑：

```sql
DROP INDEX IF EXISTS idx_documents_department_id;
ALTER TABLE documents DROP COLUMN department_id;
DROP TABLE departments;
```

---

## 6. 涉及文件清单

### 新建文件（2 个）
- `backend/alembic/versions/0003_add_departments.py`
- `backend/app/schemas/department.py`

### 修改文件（11 个）

| 文件 | 变更摘要 |
|------|----------|
| `backend/app/db/models.py` | 新增 Department 模型；Document 新增 department_id + relationship |
| `backend/app/schemas/document.py` | DocumentOut / DocumentUploadResponse 新增科室字段 |
| `backend/app/api/admin.py` | 上传新增 department_id；新增科室 CRUD；列表支持科室筛选；文档详情含科室 |
| `backend/app/api/chat.py` | AskRequest 新增 department_id；传递到 SurgeryRetriever |
| `backend/app/rag/pipeline.py` | SurgeryRetriever 新增 department_id；向量/`pg_trgm` 文本检索 SQL 追加科室过滤 |
| `database/schema.sql` | 同步 Alembic 最新结构快照 |
| `frontend/src/api/admin.ts` | 新增 DepartmentOut 类型；修改 uploadDocument 签名；新增科室 API |
| `frontend/src/api/chat.ts` | 请求携带 department_id |
| `frontend/src/stores/chat.ts` | 新增 selectedDepartmentId 状态 |
| `frontend/src/views/AdminView.vue` | 上传区新增科室下拉；表格新增科室列；搜索栏新增科室筛选 |
| `frontend/src/views/ChatView.vue` | 输入区上方新增科室选择器 |

---

## 7. 实施顺序

1. **数据库迁移** — 新增 Alembic revision 并同步 `database/schema.sql`
2. **模型 + Schema** — models.py → department.py schema → document.py schema
3. **后端 API** — admin.py（科室 CRUD + 文档上传/列表修改）→ chat.py（AskRequest 修改）
4. **检索管线** — pipeline.py（SurgeryRetriever + hybrid_search 科室过滤）
5. **前端 API 层** — admin.ts → chat.ts → stores/chat.ts
6. **前端 UI** — AdminView.vue → ChatView.vue
7. **集成测试** — 上传科室文档 → 按科室提问 → 验证检索范围

---

## 8. 风险与考量

- **科室分类粒度**：当前按一级科室划分。未来如需二级细分（如肝胆外科 → 肝脏外科 / 胆道外科），可通过在 departments 表中加 `parent_id` 自引用扩展。
- **自动科室识别**（本次不做）：后续可通过 LLM 对用户问题自动分类到科室，减少用户手动选择步骤。
- **多科室文档**：当前一个文档只属一个科室。如需跨科室，后续可改为多对多关系（中间表 `document_departments`）。
- **检索性能**：`department_id` 上有索引，过滤不会增加性能负担。
