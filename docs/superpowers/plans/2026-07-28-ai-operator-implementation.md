# AI 操作者模块 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有医生/患者端和管理员端之外，新增第三端 AI 操作者（ai_operator）模块。该角色可检索全库病例数据，通过 LLM 分析生成结构化研究报告并支持 PDF 下载。

**Architecture:** 独立 API 路由（`/api/v1/operator`）、独立数据库表（`ai_reports`）、独立前端页面（`/operator`）。后端使用 FastAPI + LangChain LCEL + DeepSeek LLM，前端使用 Vue 3 + TypeScript + Element Plus。报告生成采用 SSE 流式响应，PDF 通过 markdown + bleach + weasyprint 渲染。

**Tech Stack:** Python 3.11.4、FastAPI、SQLAlchemy、Alembic、PostgreSQL 18.1、pgvector、DeepSeek LLM、BGE-M3 Embeddings、Node.js 22.15.0、Vue 3、TypeScript、Element Plus、marked、DOMPurify

**Design Spec:** [2026-07-27-ai-operator-module-design.md](../specs/2026-07-27-ai-operator-module-design.md)

---

## Global Constraints

- 任务编号为 `ai-operator-001`，实施者为 Claude Code；不形成永久职责。
- 遵循 `AI_COLLABORATION.md`，使用 `claude/ai-operator-001` 独立分支和 worktree。
- 新增模块删除后不影响现有 chat/admin 功能。
- 不修改现有 `messages`/`sessions` 表结构。
- 后端权限在 API 层和前端路由守卫层双重约束。
- 不引入新的 LLM 服务依赖（复用现有 DeepSeek）。
- Alembic 迁移必须可 upgrade → downgrade → re-upgrade 完整循环。
- Agent 可以创建本地提交，但不得未经授权推送或合并。

---

## File Map

### Create (17 files)

| # | File | Task |
|---|------|------|
| 1 | `database/migrations/010_add_ai_operator_reports.sql` | Task 1 |
| 2 | `backend/alembic/versions/0004_add_ai_reports.py` | Task 1 |
| 3 | `backend/app/schemas/operator.py` | Task 2 |
| 4 | `backend/app/services/report_generator.py` | Task 3 |
| 5 | `backend/app/services/pdf_generator.py` | Task 4 |
| 6 | `backend/app/templates/report_pdf.html` | Task 4 |
| 7 | `backend/app/api/operator.py` | Task 5 |
| 8 | `scripts/create_ai_operator.py` | Task 6 |
| 9 | `frontend/src/api/operator.ts` | Task 7 |
| 10 | `frontend/src/stores/operator.ts` | Task 8 |
| 11 | `frontend/src/components/OperatorSidebar.vue` | Task 9 |
| 12 | `frontend/src/views/OperatorView.vue` | Task 9 |
| 13 | `backend/tests/test_report_generator.py` | Task 10 |
| 14 | `backend/tests/test_operator_api.py` | Task 10 |
| 15 | `backend/tests/test_operator_permissions.py` | Task 10 |
| 16 | `backend/tests/test_operator_state_machine.py` | Task 10 |
| 17 | `backend/tests/test_pdf_generation.py` | Task 10 |

### Modify (8 files)

| # | File | Change | Task |
|---|------|--------|------|
| 1 | `backend/app/db/models.py` | 新增 `AIReport` ORM 模型 | Task 1 |
| 2 | `backend/app/api/deps.py` | 新增 `require_ai_operator` 依赖 | Task 2 |
| 3 | `backend/app/api/chat.py` | 拒绝 `role == "ai_operator"` 访问 | Task 5 |
| 4 | `backend/app/main.py` | 注册 operator router | Task 5 |
| 5 | `frontend/src/stores/auth.ts` | 新增 `isAiOperator`、`canAccessOperator` | Task 7 |
| 6 | `frontend/src/router/index.ts` | 新增 `/operator` 路由 + 守卫 + 登录跳转 | Task 9 |
| 7 | `frontend/src/views/ChatView.vue` | 顶部栏加"AI 操作者"入口（admin only） | Task 9 |
| 8 | `frontend/src/views/AdminView.vue` | 导航加"AI 操作者"入口（admin only） | Task 9 |

### New Dependencies

```
# backend/requirements.txt 新增
markdown          # Markdown → HTML 转换
weasyprint        # HTML → PDF 渲染（首选）
bleach            # HTML 安全清洗（PDF 生成前白名单过滤）
Jinja2            # PDF 模板引擎（通常已由 FastAPI 间接依赖，显式列入以防部署环境差异）
```

---

## Task 1: Database Migration + ORM Model

**Files:**
- Create: `database/migrations/010_add_ai_operator_reports.sql`
- Create: `backend/alembic/versions/0004_add_ai_reports.py`
- Modify: `backend/app/db/models.py`

**Interfaces:**
- Produces: `ai_reports` 表（含 13 个字段 + 3 个索引），`AIReport` SQLAlchemy 模型。
- Consumes: 现有 `users` 表（FK 引用）、Alembic 迁移链（head = `0003_add_departments`）。

**Verification:** Alembic upgrade → downgrade → re-upgrade 完整循环；`AIReport` 模型可通过 SQLAlchemy 正常查询。

### Steps

- [ ] **Step 1: Verify clean baseline**

```powershell
git status --short --branch
git fetch origin
git switch main
git pull --ff-only origin main
```

Expected: 工作树干净；`main` 可快进或已最新。

- [ ] **Step 2: Create Alembic migration**

```bash
cd backend
alembic revision -m "add ai_reports"
```

Rename to `0004_add_ai_reports.py`，编写 `upgrade()` 和 `downgrade()`。

DDL 内容参考设计规格 2.2.2 节：
- `ai_reports` 表：`id`、`user_id`（FK → users）、`title`、`query`、`department_ids`（JSONB）、`content`、`sources`（JSONB）、`retrieval_meta`（JSONB）、`status`、`error_message`、`download_count`、`created_at`、`updated_at`
- 3 个索引：`ix_ai_reports_user_id`、`ix_ai_reports_created_at`、`ix_ai_reports_status`
- 外键和约束使用显式命名（`ai_reports_user_id_fkey`）

- [ ] **Step 3: Create manual SQL migration**

`database/migrations/010_add_ai_operator_reports.sql`，含 `IF NOT EXISTS` 幂等检查和 schema 限定。

- [ ] **Step 4: Add AIReport ORM model**

在 `backend/app/db/models.py` 末尾新增 `AIReport` 类，字段与迁移一致。

- [ ] **Step 5: Verify migration cycle**

```bash
cd backend
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

Expected: 完整循环无错误。验证 `ai_reports` 表存在且结构正确。

- [ ] **Step 6: Verify model import**

```bash
cd backend
python -c "from app.db.models import AIReport; print(AIReport.__tablename__)"
```

Expected: 输出 `ai_reports`，无 ImportError。

---

## Task 2: Backend Auth Dependency (deps.py)

**Files:**
- Modify: `backend/app/api/deps.py`
- Create: `backend/app/schemas/operator.py`

**Interfaces:**
- Produces: `require_ai_operator` 依赖函数（供 `operator.py` 使用）。
- Consumes: 现有 `get_current_user` 依赖、`User` 模型。

**Verification:** `require_ai_operator` 正确放行 `ai_operator` 和 `admin`，拒绝 `user`。

### Steps

- [ ] **Step 1: Add require_ai_operator to deps.py**

在 `require_admin` 函数下方新增：

```python
def require_ai_operator(current_user: User = Depends(get_current_user)) -> User:
    """仅 ai_operator 和 admin 可访问 AI 操作者工作台。"""
    if current_user.role not in ("ai_operator", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅限 AI 操作者或管理员访问",
        )
    return current_user
```

- [ ] **Step 2: Create operator Pydantic schemas**

`backend/app/schemas/operator.py` 新增：
- `ReportCreateRequest`（query + department_ids）
- `ReportOut`（含 retrieval_meta）
- `ReportListOut`
- `ReportGenerateResponse`

完整字段参考设计规格 3.3 节。

- [ ] **Step 3: Verify schema import and deps import**

```bash
cd backend
python -c "from app.schemas.operator import ReportCreateRequest, ReportOut; print('OK')"
python -c "from app.api.deps import require_ai_operator; print('OK')"
```

---

## Task 3: Report Generator Service

**Files:**
- Create: `backend/app/services/report_generator.py`

**Interfaces:**
- Produces: `generate_report(db, user_id, report_id, query, department_ids, analysis_backend)` → `AsyncIterator[str]`（SSE 事件流）。
- Consumes: `hybrid_search`（`backend/app/rag/pipeline.py`）、`rewrite_client`（复用规则层）、`DeepSeek` LLM chat model、`AIReport` 模型。
- **生命周期约定**：由 `operator.py`（API 层）负责创建 `ai_reports` 记录（status=generating），将 `report_id`、`user_id`、`db` 传入 service；service 负责检索、LLM 生成、更新 content/status/sources/retrieval_meta；API 层在 finally 块中处理断连检测和 cancelled 标记。

**Key Design Points:**
- 多科室检索合并策略（设计规格 3.4.1）
- System Prompt 角色定位：医学数据分析师，7 章固定模板
- 温度 0.2，max_tokens 4096
- 第 5 章要求标注"基于检索样本，非全量数据库统计"
- content 在内存中累积，按阶段/定时节流写 DB

**Verification:** 可导入模块，检索链路正常调用，LLM 调用参数正确。

### Steps

- [ ] **Step 1: Implement generate_report skeleton**

```python
# backend/app/services/report_generator.py

async def generate_report(
    db: Session,
    user_id: int,
    report_id: int,
    query: str,
    department_ids: list[int] | None = None,
    analysis_backend: str = "llm",
) -> AsyncIterator[str]:
    """生成报告的主入口。

    由 operator.py 调用方负责：
    1. 创建 ai_reports 记录（status=generating）
    2. 传入 db、user_id、report_id
    3. 在 finally 中处理断连/取消的状态标记

    analysis_backend:
      - "llm": 使用 LLM（DeepSeek）分析检索结果生成报告（当前实现）
      - 未来值如 "prediction_model_v1"：调用预测模型 API
    """
    if analysis_backend == "llm":
        async for event in _generate_with_llm(db, user_id, report_id, query, department_ids):
            yield event
    else:
        raise ValueError(f"Unknown analysis_backend: {analysis_backend}")
```

- [ ] **Step 2: Implement department_ids validation**

在对 `hybrid_search` 的任何调用前，先校验 department_ids：

```python
def _validate_department_ids(db: Session, department_ids: list[int] | None) -> list[int] | None:
    """校验科室 ID 列表，返回有效 ID 或 None（全库检索）。"""
    if not department_ids:
        return None
    depts = db.query(Department).filter(
        Department.id.in_(department_ids),
        Department.is_active.is_(True),
    ).all()
    found_ids = {d.id for d in depts}
    invalid = [did for did in department_ids if did not in found_ids]
    if invalid:
        raise HTTPException(status_code=422, detail=f"无效或已停用的科室 ID: {invalid}")
    return department_ids  # 全部校验通过，原样返回
```

此函数在 `_retrieve_for_report` 调用前执行。非法/停用科室 ID 返回 422，不进入检索。

- [ ] **Step 3: Implement multi-department retrieval**

`_retrieve_for_report(db, query, department_ids)` 函数，实现三分支逻辑：
1. `department_ids` 为 None/空 → `hybrid_search(top_k=20, department_id=None)`
2. 单科室 → `hybrid_search(top_k=20, department_id=n)`
3. 多科室 → 每科室 `hybrid_search(top_k=15)` → 按 `chunk.id` 去重 → RRF score 降序 → 截断到 20

- [ ] **Step 4: Implement LLM chain with SSE streaming**

- 构建 System Prompt（角色定位 + 7 章模板要求 + 第 5 章特别要求 + 安全约束）
- 构建 Human Prompt（检索上下文 + 用户问题）
- 使用 LangChain LCEL 链调用 DeepSeek
- 流式输出封装为 SSE 事件格式（stage / delta / sources / done / error）

- [ ] **Step 5: Implement persistence logic**

- 生成前：由 API 层（operator.py）创建 ai_reports 初始记录（status=generating），service 只更新该 report_id
- 生成中：内存缓冲 content，按阶段（每章完结）或每 30 秒节流写 DB
- 完成时：status=completed，最终 content + sources + retrieval_meta 完整落库
- 异常/取消时：保存已有内容，标记 failed/cancelled

- [ ] **Step 6: Verify import and dry-run structure**

```bash
cd backend
python -c "from app.services.report_generator import generate_report; print('OK')"
```

---

## Task 4: PDF Generator Service + Template

**Files:**
- Create: `backend/app/services/pdf_generator.py`
- Create: `backend/app/templates/report_pdf.html`

**Interfaces:**
- Produces: `generate_pdf(markdown_content, title)` → `bytes`（PDF）。
- Consumes: `markdown` library、`bleach`、`weasyprint`、Jinja2 模板。

**Verification:** 含中文的 Markdown 可成功生成 PDF，危险 HTML 标签被过滤。

### Steps

- [ ] **Step 1: Implement pdf_generator.py**

三阶段管道：
1. `markdown.markdown(content)` → HTML
2. `bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS)` → 安全 HTML
3. Jinja2 渲染完整 HTML → `weasyprint.HTML(string=...).write_pdf()` → PDF bytes

ALLOWED_TAGS 白名单：`h1-h6, p, ul, ol, li, table, thead, tbody, tr, th, td, strong, em, code, pre, blockquote, hr, br, sup, sub, a, span, div`

- [ ] **Step 2: Create Jinja2 PDF template**

`backend/app/templates/report_pdf.html`：
- A4 页面（@page size: A4, margin: 20mm）
- 中文字体声明（`font-family: 'Noto Sans SC', 'Microsoft YaHei', 'SimSun', sans-serif`）
- 标题层级样式（h1: 18pt, h2: 14pt, body: 11pt）
- 页脚：生成时间 + 页码（CSS `@bottom-center`）
- 安全声明水印/脚注

- [ ] **Step 3: Verify PDF generation with Chinese content**

```bash
cd backend
python -c "
from app.services.pdf_generator import generate_pdf
pdf = generate_pdf('# 测试报告\n\n这是中文测试内容。\n\n## 第二节\n\n数据摘要。', '测试报告')
assert pdf.startswith(b'%PDF')
print(f'PDF generated: {len(pdf)} bytes')
"
```

---

## Task 5: Operator API Routes + Permission Hardening

**Files:**
- Create: `backend/app/api/operator.py`
- Modify: `backend/app/api/chat.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Produces: 5 个 API 端点（`/api/v1/operator/*`）。
- Consumes: `require_ai_operator`（from deps）、`generate_report`、`generate_pdf`、`AIReport` 模型。

**Verification:** 所有端点返回正确状态码；ai_operator 访问 chat API 返回 403。

### Steps

- [ ] **Step 1: Implement operator API routes**

`backend/app/api/operator.py`，router prefix 为空（由 main.py 统一加 `/api/v1`）：

| 方法 | 路径 | 功能 |
|------|------|------|
| `POST` | `/operator/reports` | 创建并流式生成报告（SSE，`media_type="text/event-stream"`） |
| `GET` | `/operator/reports` | 列出当前用户报告（分页，`skip`/`limit`） |
| `GET` | `/operator/reports/{id}` | 获取单个报告详情 |
| `DELETE` | `/operator/reports/{id}` | 删除报告（校验 `user_id`） |
| `GET` | `/operator/reports/{id}/download` | 下载 PDF（`media_type="application/pdf"`，自增 `download_count`） |

所有端点使用 `require_ai_operator` 依赖；GET/DELETE 单个报告时校验 `report.user_id == current_user.id`。

- [ ] **Step 2: Harden chat.py against ai_operator**

在 `deps.py` 中新增一个统一依赖：

```python
def require_not_ai_operator(current_user: User = Depends(get_current_user)) -> User:
    """拒绝 ai_operator 角色访问聊天功能。"""
    if current_user.role == "ai_operator":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI 操作者不可访问聊天功能",
        )
    return current_user
```

在 `chat.py` 的**全部 5 个端点**中使用此依赖：
- `POST /sessions`
- `GET /sessions`
- `GET /sessions/{session_id}`
- `DELETE /sessions/{session_id}`
- `POST /sessions/{session_id}/ask`

实现方式：在 router 级别或各端点参数中注入 `Depends(require_not_ai_operator)`。

- [ ] **Step 3: Write audit log on report generation**

`operator.py` 的 `POST /operator/reports` 中，生成完成后写入 `audit_logs`：

```python
audit = AuditLog(
    user_id=current_user.id,
    session_id=None,  # 报告不关联聊天会话
    request_body={
        "feature": "operator_report",
        "action": "generate",
        "report_id": report_id,
        "query": request.query,
        "department_ids": request.department_ids,
    },
    model=settings.DEEPSEEK_MODEL,
    latency_ms=elapsed_ms,
    retrieved_chunk_ids=retrieved_chunk_ids,
    safety_flags=safety_flags,
)
db.add(audit)
db.commit()
```

> 使用现有 `audit_logs` 表，不新增字段。`feature`/`action`/`report_id` 嵌入 `request_body` JSONB。

- [ ] **Step 4: Register operator router in main.py**

```python
from app.api import operator
app.include_router(operator.router, prefix="/api/v1")
```

- [ ] **Step 5: Verify all endpoints import cleanly**

```bash
cd backend
python -c "from app.main import app; print([r.path for r in app.routes if 'operator' in str(r.path)])"
```

Expected: 输出 5 条 operator 路由。

---

## Task 6: Create AI Operator Account Script

**Files:**
- Create: `scripts/create_ai_operator.py`

**Interfaces:**
- Produces: 数据库中一条 `role="ai_operator"` 的用户记录。
- Consumes: 现有 User 模型和数据库连接。

**Verification:** 脚本执行后可用该账号登录并访问 `/operator`。

### Steps

- [ ] **Step 1: Write the script**

```python
# scripts/create_ai_operator.py
# 用法: python scripts/create_ai_operator.py <username> <email> <password> [real_name]
# 创建 role="ai_operator" 的用户账号
```

复用现有密码哈希逻辑（`backend/app/core/security.py` 的 `hash_password`）。

- [ ] **Step 2: Verify script executes**

```bash
cd backend
python ../scripts/create_ai_operator.py test_operator op@test.com TestPass123 "测试操作者"
```

Expected: 输出成功信息，数据库 `users` 表出现新记录且 `role = "ai_operator"`。

---

## Task 7: Frontend Auth Store Extension + API Layer

**Files:**
- Modify: `frontend/src/stores/auth.ts`
- Create: `frontend/src/api/operator.ts`

**Interfaces:**
- Produces: `isAiOperator`、`canAccessOperator` 计算属性；operator API 调用函数。
- Consumes: 现有 `auth.ts` store、`request.ts` HTTP 客户端。

**Verification:** `vue-tsc` 类型检查通过，API 函数可正确调用后端。

### Steps

- [ ] **Step 1: Extend auth store**

在 `frontend/src/stores/auth.ts` 中新增：

```typescript
const isAiOperator = computed(() => user.value?.role === 'ai_operator')
const canAccessOperator = computed(() => user.value?.role === 'ai_operator' || user.value?.role === 'admin')
```

将两者加入 return 对象。

- [ ] **Step 2: Create operator API module**

`frontend/src/api/operator.ts`：
- TypeScript 接口：`Report`、`ReportCallbacks`（`onDelta`、`onSources`、`onStage`、`onDone`、`onError`）、`Department`
- `listReports(skip?, limit?)` — `GET /api/v1/operator/reports`
- `getReport(id)` — `GET /api/v1/operator/reports/{id}`
- `deleteReport(id)` — `DELETE /api/v1/operator/reports/{id}`
- `generateReport(query, departmentIds, callbacks)` — `POST /api/v1/operator/reports`，使用 `fetch` + `ReadableStream` 解析 SSE（非 EventSource，见设计规格 4.8 节说明），返回 abort 函数
- `downloadReport(id)` — 触发浏览器下载 PDF（`GET /api/v1/operator/reports/{id}/download`）

- [ ] **Step 3: Verify TypeScript compilation**

```bash
cd frontend
npx vue-tsc --noEmit
```

Expected: 无新增类型错误。

---

## Task 8: Frontend Operator Store

**Files:**
- Create: `frontend/src/stores/operator.ts`

**Interfaces:**
- Produces: 报告列表状态管理 + SSE 生命周期管理。
- Consumes: `frontend/src/api/operator.ts`、`frontend/src/stores/auth.ts`。

**Verification:** Store 可正确初始化，actions 可调用。

### Steps

- [ ] **Step 1: Implement operator Pinia store**

```typescript
// frontend/src/stores/operator.ts
// 状态：reports[], currentReport, loading, currentAbort
// 动作：loadReports(), loadReport(id), generateReport(query, departmentIds), deleteReport(id), abort()
```

`generateReport` 管理完整 SSE 生命周期：
1. 创建 `AbortController`
2. 调用 `fetch` + `ReadableStream` 解析 SSE
3. 根据 event 类型分发到 callbacks（stage → onStage, delta → onDelta, sources → onSources, done → onDone, error → onError）
4. 返回 abort 清理函数

- [ ] **Step 2: Verify store import**

```bash
cd frontend
npx vue-tsc --noEmit
```

---

## Task 9: Frontend Components + Router + Navigation

**Files:**
- Create: `frontend/src/components/OperatorSidebar.vue`
- Create: `frontend/src/views/OperatorView.vue`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/views/ChatView.vue`
- Modify: `frontend/src/views/AdminView.vue`

**Interfaces:**
- Produces: `/operator` 完整页面（侧边栏 + 报告内容区 + Markdown 渲染）。
- Consumes: `operator.ts` store、`operator.ts` API、`auth.ts` store、`marked`、`DOMPurify`、`DESIGN_SPEC.md`。

**Verification:** `npm run build` 通过；ai_operator 登录跳转 `/operator`；admin 可见导航入口。

### Steps

- [ ] **Step 1: Create OperatorSidebar component**

`frontend/src/components/OperatorSidebar.vue`：
- 报告历史列表（按 `created_at` 倒序）
- "+ 新建"按钮
- 每个列表项显示标题（截断）+ 状态标签 + 创建时间
- 点击切换当前报告
- 删除按钮（带确认）
- 宽度 260px，遵循 DESIGN_SPEC 侧边栏规范

- [ ] **Step 2: Create OperatorView page**

`frontend/src/views/OperatorView.vue`：
- 顶部栏（56px）：标题"AI 操作者工作台"+ 用户信息 + 退出
- 左侧：`OperatorSidebar`（260px）
- 右侧内容区（max 960px）：
  - 科室多选下拉框（调用 `GET /api/v1/departments`，多选，默认全部）
  - 问题输入框（max 2000 字）
  - "生成报告"按钮 + "取消"按钮（生成中显示）
  - Markdown 渲染区：`marked` 解析 → `DOMPurify.sanitize` → `v-html`
  - "下载 PDF"按钮（生成完成后显示）
- 安全渲染配置：ALLOWED_TAGS 白名单，禁止 on* 属性、script/iframe/object/embed/style/link/meta 标签
- 样式遵循 DESIGN_SPEC 暖杏蓝方案

- [ ] **Step 3: Update router**

`frontend/src/router/index.ts`：
- 新增 `/operator` 路由定义（`meta: { aiOperator: true }`）
- 守卫逻辑更新：
  - `meta.aiOperator` 路由：仅 `ai_operator` / `admin` 可访问，否则 → `/`
  - ai_operator 访问 `/` 或 `/admin` → 重定向到 `/operator`
  - 登录跳转（`to.path === '/login'` 分支）：ai_operator → `/operator`，其他 → `/`

- [ ] **Step 4: Add navigation entries**

- `ChatView.vue`：顶部栏 `header-actions` 区域，`v-if="authStore.isAdmin"` 加"AI 操作者"按钮 → `/operator`
- `AdminView.vue`：导航区，`v-if="authStore.isAdmin"` 加"AI 操作者"入口 → `/operator`

- [ ] **Step 5: Verify frontend build**

```bash
cd frontend
npx vue-tsc --noEmit
npm run build
```

Expected: 类型检查通过，构建成功。

---

## Task 10: Tests

**Files:**
- Create: `backend/tests/test_report_generator.py`
- Create: `backend/tests/test_operator_api.py`
- Create: `backend/tests/test_operator_permissions.py`
- Create: `backend/tests/test_operator_state_machine.py`
- Create: `backend/tests/test_pdf_generation.py`

**Interfaces:**
- Produces: 5 个测试文件，覆盖检索、API、权限、状态机、PDF 生成。
- Consumes: FastAPI `TestClient`、pytest、现有测试 fixtures。

**Verification:** 全部新增测试通过；存量 40 项测试继续通过。

### Steps

- [ ] **Step 1: test_report_generator.py**

覆盖：
- 单科室检索正确过滤
- 多科室检索去重排序
- 全库检索（`department_ids=None`）
- 检索结果截断到 `final_top_k`
- 章节生成完整性（7 章均含内容）
- 引用编号正确（`[1]`, `[2]`...）
- `retrieval_meta` 字段完整写入

- [ ] **Step 2: test_operator_api.py**

覆盖：
- SSE 事件顺序：stage(retrieving) → stage(analyzing) → delta* → sources → done
- 报告 CRUD：创建 → 列表包含 → 详情可查 → 删除 → 404
- 分页参数正确
- 400 校验（空 query、超长 query）
- 404 校验（不存在的报告 ID）

- [ ] **Step 3: test_operator_permissions.py**

覆盖权限矩阵：
- `user` 访问 `POST /operator/reports` → 403
- `user` 访问 `GET /operator/reports` → 403
- `ai_operator` 访问 `POST /api/v1/chat/ask` → 403
- `ai_operator` 访问 `GET /api/v1/admin/*` → 403
- `admin` 访问 `POST /operator/reports` → 200
- 用户 A 无法查看用户 B 的报告 → 403/404
- 用户 A 无法删除用户 B 的报告 → 403/404

- [ ] **Step 4: test_operator_state_machine.py**

覆盖状态流转：
- `generating` → `completed`（正常结束）
- `generating` → `failed`（LLM 异常，含 error_message）
- `generating` → `cancelled`（客户端 abort，含部分 content）
- **终态规则**：仅 `generating` 可转为 `cancelled`；`completed`/`failed` 后即使连接关闭也不覆盖状态
- `cancelled` 报告不可下载 → 404/400

- [ ] **Step 5: test_pdf_generation.py**

覆盖：
- 基本 Markdown → PDF 生成（含中文）
- 危险标签过滤（`<script>`, `<iframe>`, `<object>` 不出现在 HTML 中）
- PDF 下载权限：非创建者 → 403
- `download_count` 自增

- [ ] **Step 6: Run full test suite**

```bash
cd backend
python -m pytest tests/ -v
```

Expected: 存量 40 项 + 新增测试全部通过。

---

## Task 11: Final Integration Verification

**Verification:** 完整端到端流程可走通，存量功能不受影响。

### Steps

- [ ] **Step 1: Full Alembic cycle**

```bash
cd backend
alembic downgrade base
alembic upgrade head
```

Expected: 所有迁移（0001-0004）完整执行，无错误。

- [ ] **Step 2: Backend test suite**

```bash
cd backend
python -m pytest tests/ -v
```

Expected: 全部通过。

- [ ] **Step 3: Frontend build**

```bash
cd frontend
npm run build
```

Expected: 构建成功，无警告。

- [ ] **Step 4: Create ai_operator test account**

```bash
cd backend
python ../scripts/create_ai_operator.py demo_operator operator@test.com Demo123456 "演示操作者"
```

- [ ] **Step 5: Manual smoke test checklist**

- [ ] ai_operator 登录 → 自动跳转 `/operator`
- [ ] ai_operator 手动访问 `/` → 被重定向到 `/operator`
- [ ] ai_operator 手动访问 `/admin` → 被重定向到 `/operator`
- [ ] admin 登录 → 跳转 `/`，可见"AI 操作者"导航按钮
- [ ] `/operator` 页面科室多选下拉正常
- [ ] 输入问题 → 生成报告 → SSE 流式渲染
- [ ] 生成完成后下载 PDF → 文件可打开，中文正常
- [ ] 取消生成 → 列表中出现"已取消"报告，可删除
- [ ] 删除报告 → 列表更新
- [ ] admin 看不到其他用户创建的报告

- [ ] **Step 6: Run existing backend tests to verify no regression**

```bash
cd backend
python -m pytest tests/ -v -k "not operator"
```

Expected: 存量 40 项测试继续通过。

---

## Summary

| Task | Description | Files | Est. Effort |
|------|-------------|-------|-------------|
| 1 | DB Migration + ORM | 3 | Small |
| 2 | Auth Dependency + Schemas | 2 | Small |
| 3 | Report Generator Service | 1 | Large |
| 4 | PDF Generator + Template | 2 | Medium |
| 5 | API Routes + Permission Hardening | 3 | Medium |
| 6 | AI Operator Account Script | 1 | Small |
| 7 | Frontend Auth Store + API Layer | 2 | Small |
| 8 | Frontend Operator Store | 1 | Small |
| 9 | Frontend Components + Router + Nav | 5 | Large |
| 10 | Tests | 5 | Medium |
| 11 | Final Integration Verification | 0 | Small |

> **下一步**：项目所有者审阅本实施计划。确认后进入任务登记（`ACTIVE_TASKS.md`）并开始编码。
