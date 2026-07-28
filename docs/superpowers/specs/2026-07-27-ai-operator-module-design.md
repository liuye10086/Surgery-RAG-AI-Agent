# AI 操作者（ai_operator）模块 — 实施规格

> **状态**：已修订，待终审
> **创建日期**：2026-07-27
> **最后修订**：2026-07-28
> **模块代号**：`ai-operator`
> **内部别称**：「封弊者」—— 取"封闭弊端"之意，指该角色专注于从知识库中挖掘规律、发现模式，而非面向患者提供诊疗服务。本文档正式名称统一使用"AI 操作者"。

---

## 1. 概述

### 1.1 目标

在现有医生/患者端和管理员端之外，新增第三端：**AI 操作者（ai_operator）**。该角色利用知识库中的全部病例数据，通过 AI 分析生成预测报告或研究性回答，支持 PDF 下载。

### 1.2 核心原则

- **完全独立**：删除本模块不影响现有医生/患者端和管理员端的任何功能。
- **不复用接口**：后端 API、前端界面、路由均独立设计，不共享现有 chat/admin 的接口和页面组件。
- **独立数据库表**：报告存储使用新表 `ai_reports`，不耦合现有 messages/sessions 结构。
- **前后端双重权限约束**：ai_operator 对 chat/admin 接口的隔离在后端 API 层和前端路由守卫层同时生效。
- **预留扩展**：为后续预测模型接入预留清晰的接口边界。

### 1.3 业务流程

```
ai_operator 账号登录
    → 登录成功后自动跳转到独立的操作者工作台（/operator）
    → 选择科室范围（多选，默认全部） + 输入分析问题
    → 系统检索指定科室知识库 + LLM 分析
    → 流式生成固定章节模板的结构化报告
    → 点击下载按钮导出 PDF 报告文件
```

### 1.4 固定章节模板

每份报告按以下 7 章结构生成，LLM 必须在对应章节下输出内容：

```
# {报告标题}

## 1. 报告摘要
（200 字以内的核心发现概述）

## 2. 研究问题
（复述用户的分析问题，明确分析范围）

## 3. 数据来源
（由系统自动填充，非 LLM 生成。包含文档数、分块数、科室覆盖范围、检索元数据）

## 4. 数据分析与发现
（按主题分条呈现关键发现，每条附 [序号] 引用）

## 5. 检索样本中的观察性特征
（从本次检索到的片段中归纳的共性特征、模式、趋势等）
（明确标注：基于检索样本，非全量数据库统计，仅供参考）

## 6. 讨论
（发现的临床意义、局限性、与现有知识的关联）

## 7. 结论与建议
（总结性陈述 + 提示"本报告由 AI 基于知识库自动生成，仅供参考，不构成临床决策依据"）
```

章节 1、2、4、5、6、7 由 LLM 生成；章节 3 由系统根据检索结果自动填充。

> **关于第 5 章的重要说明**：RAG 检索通常只取 top 15-20 个 chunk，远不足以覆盖全库数据。因此第 5 章标题从"统计特征"改为"检索样本中的观察性特征"，LLM system prompt 中须明确要求标注"基于检索样本，非全量数据库统计"。若后续需要真正的全库统计能力，需额外设计结构化病例字段查询或接入统计/预测模型，不在本模块 MVP 范围内。

---

## 2. 数据库设计

### 2.1 现有表变更

**无。**`users.role` 已是 `String(50)`，无需迁移即可存储 `"ai_operator"`。

仅需在创建 ai_operator 账号时写入 `role = "ai_operator"`（通过脚本或手动 SQL）。

### 2.2 新表：`ai_reports`

#### 2.2.1 迁移文件

| 类型 | 路径 | 说明 |
| --- | --- | --- |
| Alembic（正式） | `backend/alembic/versions/0004_add_ai_reports.py` | 由 alembic 自动生成后编写 |
| 手动 SQL（参考） | `database/migrations/010_add_ai_operator_reports.sql` | 供手动部署参考，含幂等检查 |

> **编号说明**：当前 Alembic 最新版本为 `0003_add_departments`，手动 SQL 最新为 `009_add_departments.sql`。本模块占用 `0004`（Alembic）和 `010`（手动 SQL），避免与已有迁移冲突。

#### 2.2.2 DDL

```sql
-- 位置：database/migrations/010_add_ai_operator_reports.sql
-- 正式迁移请使用 backend/alembic/versions/0004_add_ai_reports.py

CREATE TABLE IF NOT EXISTS ai_reports (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title           VARCHAR(500),                          -- 报告标题（LLM 生成或用户输入截断）
    query           TEXT NOT NULL,                         -- 用户输入的原始分析问题
    department_ids  JSONB DEFAULT '[]'::jsonb,             -- 生成时选择的科室 ID 列表（空数组 = 全库）
    content         TEXT NOT NULL DEFAULT '',              -- 报告正文（Markdown）
    sources         JSONB DEFAULT '[]'::jsonb,             -- 引用的知识库来源
    retrieval_meta  JSONB DEFAULT '{}'::jsonb,             -- 检索元数据（详见 2.2.3）
    status          VARCHAR(50) DEFAULT 'generating',      -- pending | generating | completed | failed | cancelled
    error_message   TEXT,                                  -- 失败/取消原因
    download_count  INTEGER DEFAULT 0,                     -- 下载次数统计
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX ix_ai_reports_user_id ON ai_reports(user_id);
CREATE INDEX ix_ai_reports_created_at ON ai_reports(created_at DESC);
CREATE INDEX ix_ai_reports_status ON ai_reports(status);
```

#### 2.2.3 `retrieval_meta` 字段结构

用于保存检索过程的完整元数据，支撑报告可追溯性和审计：

```json
{
  "original_query": "所有胆囊结石患者的共同特点有哪些？",
  "rewritten_query": null,
  "department_ids": [1, 2],
  "department_names": ["肝胆外科", "神经外科"],
  "per_department_top_k": 15,
  "final_top_k": 20,
  "retrieved_chunk_ids": [101, 203, 415, ...],
  "document_count": 5,
  "chunk_count": 18,
  "model_name": "deepseek-chat",
  "temperature": 0.2,
  "max_tokens": 4096,
  "generation_started_at": "2026-07-28T10:30:00+08:00",
  "generation_completed_at": "2026-07-28T10:31:25+08:00",
  "generation_duration_ms": 85230
}
```

> 该字段为 JSONB，后续可扩展字段无需新增迁移。`sources` JSONB 保留原有格式（引用来源列表，含 document_id、title、page 等），`retrieval_meta` 存检索级元数据，两者各司其职。

#### 2.2.4 报告状态机

```
         POST /operator/reports
              │
              ▼
         ┌─ pending ──┐
         │  (可选：创建   │
         │   记录后立即    │
         │   开始检索)    │
         └──────┬──────┘
                │ 检索开始
                ▼
         ┌ generating ──────────────┐
         │  SSE 流式生成中……          │
         └──┬────────┬────────┬─────┘
            │        │        │
   生成成功  │   LLM/ │  客户端主动
            │   检索异常 │  abort/断连
            ▼        ▼        ▼
       completed   failed  cancelled
```

| 状态 | 含义 | 触发条件 |
|------|------|---------|
| `pending` | 报告已创建，等待开始生成 | POST 请求写入记录后立即设置（可选，也可直接进入 generating） |
| `generating` | 正在检索 + LLM 流式生成中 | 检索开始 |
| `completed` | 生成成功，content 完整 | SSE done 事件 |
| `failed` | 生成失败 | LLM 调用异常、检索异常等 |
| `cancelled` | 用户主动取消或 SSE 连接异常断开 | 客户端 abort() 或浏览器断连 |

**取消/断连处理**：
- 客户端调用 `AbortController.abort()`（fetch + ReadableStream 方式，见 4.8 节）→ 后端捕获 `GeneratorExit` / `asyncio.CancelledError` → 将状态更新为 `cancelled`
- 浏览器意外断连 → SSE writer 检测到连接断开 → 标记 `cancelled`
- **终态规则**：只有 `generating` 状态可转为 `cancelled`；`completed`/`failed` 已是终态，后续连接关闭不覆盖状态
- 状态为 `cancelled` 的报告，`content` 保留已生成的部分内容（不会残留永远 `generating` 的报告）
- 历史列表中对 `cancelled` 报告展示"已取消"标签，不可下载，可删除

#### 2.2.5 ORM 模型

`backend/app/db/models.py` 新增：

```python
class AIReport(Base):
    __tablename__ = "ai_reports"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(500), nullable=True)
    query = Column(Text, nullable=False)
    department_ids = Column(JSONB, default=list)
    content = Column(Text, nullable=False, default="")
    sources = Column(JSONB, default=list)
    retrieval_meta = Column(JSONB, default=dict)
    status = Column(String(50), default="generating")
    error_message = Column(Text, nullable=True)
    download_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

### 2.3 数据流

```
用户输入 query
    → 写入 ai_reports（status=generating，同时写入 retrieval_meta.original_query）
    → 查询改写 → 多科室检索（详见 3.4.1）
    → LLM 流式生成 → content 在内存中累积，按阶段/定时节流写 DB（避免每个 token 触发 commit）
    → 生成完成 → status=completed，最终 content + sources + retrieval_meta 完整落库
    → 若取消/失败 → 保存已生成的部分 content，标记 cancelled/failed
```

---

## 3. 后端设计

### 3.1 目录结构（全部新增）

```
backend/app/
├── api/
│   └── operator.py          # AI 操作者 API 路由（/api/v1/operator）
├── schemas/
│   └── operator.py          # Pydantic 请求/响应模型
├── services/
│   ├── report_generator.py  # 报告生成服务（检索 + LLM 分析链）
│   └── pdf_generator.py     # PDF 渲染服务（Markdown → HTML → PDF）
└── templates/
    └── report_pdf.html      # PDF 输出 Jinja2 模板（A4 样式）
```

### 3.2 API 路由设计（`backend/app/api/operator.py`）

**Router prefix**: `/api/v1/operator`（独立于现有的 `/api/v1/chat`、`/api/v1/admin`）

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| `POST` | `/operator/reports` | 创建并流式生成报告（SSE） | ai_operator / admin |
| `GET` | `/operator/reports` | 列出当前用户的历史报告（分页） | ai_operator / admin |
| `GET` | `/operator/reports/{id}` | 获取单个报告详情（含完整 Markdown） | ai_operator / admin（仅创建者） |
| `DELETE` | `/operator/reports/{id}` | 删除报告 | ai_operator / admin（仅创建者） |
| `GET` | `/operator/reports/{id}/download` | 下载报告为 PDF 文件 | ai_operator / admin（仅创建者） |

> **报告归属规则（MVP）**：所有角色只能查看/下载/删除**自己创建**的报告。admin 拥有进入 `/operator` 的入口和生成报告的权限，但不可窥探其他用户（包括其他 ai_operator）的报告。这与现有 chat 会话的隔离模型一致。

#### 3.2.1 `POST /operator/reports`（核心接口）

```json
// Request body
{
  "query": "所有胆囊结石患者的共同特点有哪些？",
  "department_ids": [1, 2]   // 可选，科室 ID 列表；为空或省略则检索全部
}

// Response: SSE 流
// event: stage     → {"stage": "retrieving"}
// event: stage     → {"stage": "analyzing"}
// event: delta     → {"content": "## 胆囊结石患者..."}
// event: sources   → {"sources": [...]}
// event: done      → {"status": "completed", "report_id": 1, "title": "胆囊结石患者共同特点分析"}
// event: error     → {"detail": "生成失败"}
```

#### 3.2.2 `GET /operator/reports/{id}/download`

1. 从数据库读取报告 `content`（Markdown）
2. 使用 Python `markdown` 库将 Markdown 转为 HTML
3. 对 HTML 进行安全清洗（去除 `<script>`、`<iframe>` 等危险标签，仅保留安全标签白名单）
4. 套入预定义的 PDF 样式模板（CSS，包含页眉页脚、字体、页码）
5. 通过 `weasyprint` 将 HTML 渲染为 PDF
6. 返回 `Content-Type: application/pdf`，文件名：`{title}_{date}.pdf`

PDF 生成在每次下载请求时实时执行（无需额外存储字段）。新增依赖：`markdown`、`bleach`、`weasyprint`、`Jinja2`（通常已由 FastAPI 间接依赖）。

**PDF 生成部署策略**：
| 优先级 | 方案 | 说明 |
|--------|------|------|
| 首选 | `weasyprint` | 无浏览器进程依赖，纯 Python 库；需确认目标环境已安装系统图形/字体库和中文字体 |
| 备选 A | Playwright / Chromium `printToPDF` | 对中文渲染更稳定，需额外安装 Chromium |
| 备选 B | `reportlab` | 纯 Python，无系统依赖，但需手动排版中文 |

> 验收条件中新增："目标部署环境可成功生成包含中文内容的 PDF 文件"。若首选方案在目标环境不可用，切换到备选方案时需更新本规格。

模板 CSS 设计要求：
- 中文字体支持（使用系统字体或嵌入 Noto Sans SC）
- A4 页面尺寸，页边距 20mm
- 一级标题 18pt，二级标题 14pt，正文 11pt
- 引用标记保留 `[序号]` 格式
- 页脚显示生成时间和页码

### 3.3 Pydantic Schema（`backend/app/schemas/operator.py`）

```python
class ReportCreateRequest:
    query: str                    # max_length=2000
    department_ids: list[int] | None = None  # 可选科室筛选，默认全库

class ReportOut:
    id: int
    title: str | None
    query: str
    department_ids: list[int] | None  # 生成时选择的科室
    department_names: list[str]       # 冗余展示用
    content: str
    sources: list[dict]
    retrieval_meta: dict              # 检索元数据（含查询改写、chunk IDs、耗时等）
    status: str
    error_message: str | None
    download_count: int
    created_at: datetime
    updated_at: datetime

class ReportListOut:
    total: int
    items: list[ReportOut]

class ReportGenerateResponse:
    """SSE done 事件携带的最终数据"""
    status: str                     # "completed" | "failed" | "cancelled"
    report_id: int
    title: str | None
```

### 3.4 报告生成服务（`backend/app/services/report_generator.py`）

#### 核心链路

```
用户 query + department_ids
    → 查询改写（复用 rewrite_client 的规则层，可选 LLM 层）
    → 知识库检索（多科室检索策略详见 3.4.1）
    → 研究报告型 System Prompt（不同于诊疗问答）
    → LLM 流式生成 Markdown 报告（数据来源章节注入科室名称 + 检索统计）
    → 解析引用 → 持久化（输出安全策略见 5.3：仅做输入过滤 + prompt 约束 + 末尾免责声明 + HTML 清洗，不替换正文）
```

#### 3.4.1 多科室检索与合并策略

现有 `hybrid_search` 只支持单个 `department_id`。对于多科室检索，采用以下策略：

```
输入：query, department_ids (list[int] | None), per_dept_top_k=15, final_top_k=20

1. 若 department_ids 为 None 或空列表：
   → 调用 hybrid_search(query, top_k=final_top_k, department_id=None)
   → 全库检索一次，直接返回

2. 若 department_ids 为单元素列表（如 [1]）：
   → 调用 hybrid_search(query, top_k=final_top_k, department_id=1)
   → 单科室检索一次，直接返回

3. 若 department_ids 为多元素列表（如 [1, 2, 3]）：
   → 对每个 dept_id，调用 hybrid_search(query, top_k=per_dept_top_k, department_id=dept_id)
   → 所有结果合并，按 chunk.id 去重（同一 chunk 可能在多个科室检索中重复出现，仅保留最高 RRF score）
   → 按 RRF score 降序排序
   → 截断到 final_top_k 条
   → sources 引用序号以最终上下文顺序重新编号（[1], [2], [3]...）
```

**关键参数**：
| 参数 | 建议值 | 说明 |
|------|--------|------|
| `per_dept_top_k` | 15 | 每个科室取的数量，略大于 final 以保证覆盖 |
| `REPORT_RETRIEVER_FINAL_TOP_K` | 20 | 最终上下文中的 chunk 数（报告场景比聊天需要更多上下文） |
| RRF k | 60 | 复用现有配置 |

**去重规则**：以 `chunk.id` 为 key，若同一 chunk 出现在多个科室的检索结果中，保留 RRF score 更高者。

#### 3.4.2 System Prompt 设计要点

- 角色定位：医学数据分析师（而非临床医生）
- 输出格式：严格遵循 7 章固定模板（见 1.4 节），每章必须输出内容，不可省略
- 知识边界：仅基于知识库内容，不编造
- 引用规范：使用 `[序号]` 标注来源
- 安全边界：不含确定性诊断和药物剂量信息
- **第 5 章特别要求**：标题使用"检索样本中的观察性特征"，开头必须注明"以下观察基于本次检索到的 N 个数据片段，非全量数据库统计，仅供参考"

#### 3.4.3 PDF 生成服务（`backend/app/services/pdf_generator.py`）

独立的 PDF 渲染服务，不耦合报告生成逻辑：

```
Markdown 内容
    → Python markdown 库 → HTML
    → HTML 安全清洗（去除 script/iframe/object 等危险标签）
    → Jinja2 HTML 模板（A4 样式 + 页眉页脚 + 中文字体）
    → weasyprint → PDF bytes
    → 返回 StreamingResponse
```

**安全清洗要求**：Markdown → HTML 后，PDF 生成前，使用 HTML 白名单过滤，仅允许 `h1-h6, p, ul, ol, li, table, thead, tbody, tr, th, td, strong, em, code, pre, blockquote, hr, br, sup` 等排版标签。`<script>`、`<iframe>`、`<object>`、`<embed>`、`<style>`（除模板自带 CSS 外）、事件处理器属性（`onclick` 等）必须移除。

模板文件位置：`backend/app/templates/report_pdf.html`（Jinja2 模板）。

#### 3.4.4 预测模型接口预留

`report_generator.py` 通过 `analysis_backend` 参数预留切换能力，默认 `"llm"`：

```python
# backend/app/services/report_generator.py

def generate_report(
    query: str,
    department_ids: list[int] | None = None,
    analysis_backend: str = "llm",   # "llm" | "prediction_model_v1" | ...
) -> AsyncIterator[str]:
    """生成报告的主入口。

    analysis_backend:
      - "llm": 使用 LLM（DeepSeek）分析检索结果生成报告（当前实现）
      - 未来值如 "prediction_model_v1"：调用预测模型 API
    """
    if analysis_backend == "llm":
        async for chunk in _generate_with_llm(query, department_ids):
            yield chunk
    else:
        raise ValueError(f"Unknown analysis_backend: {analysis_backend}")
```

API 层暂不暴露该参数（默认 `"llm"`），后续接入预测模型时在请求体新增一个可选字段即可。

#### 3.4.5 与现有 chat 链的差异

| 维度 | 现有 chat 链 | report_generator |
|------|-------------|-----------------|
| 角色 | 外科主任医师 | 医学数据分析师 |
| 输出格式 | 诊疗建议、分条回答 | 固定 7 章结构化 Markdown → PDF 导出 |
| 检索量 | top_k=7 | 15-20（通过 `per_dept_top_k` + `final_top_k` 控制） |
| 温度 | 0.3 | 0.2（更确定性的分析） |
| max_tokens | 2048 | 4096（报告更长） |
| 历史记忆 | 有（6轮） | 无（每次独立） |
| 知识不足 | NO_KNOWLEDGE_ANSWER | 报告中说明数据不足 |
| 权限检查 | 无（已登录即可） | ai_operator / admin 专属 |

### 3.5 认证与权限依赖

#### 3.5.1 后端权限依赖（`backend/app/api/deps.py` 新增）

> 权限依赖统一放在 `deps.py`，避免分散在各 API 模块中。

```python
# backend/app/api/deps.py 新增

def require_ai_operator(current_user: User = Depends(get_current_user)) -> User:
    """仅 ai_operator 和 admin 可访问 AI 操作者工作台。"""
    if current_user.role not in ("ai_operator", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅限 AI 操作者或管理员访问",
        )
    return current_user
```

#### 3.5.2 全栈权限矩阵

| 资源 | user（医生/患者） | admin | ai_operator |
|------|-------------------|-------|-------------|
| `/` ChatView + `/api/v1/chat/*` | ✅ | ✅ | ❌ |
| `/admin` AdminView + `/api/v1/admin/*` | ❌ | ✅ | ❌ |
| `/operator` OperatorView + `/api/v1/operator/*` | ❌ | ✅（仅自己的报告） | ✅（仅自己的报告） |
| `GET /api/v1/departments` | ✅ | ✅ | ✅ |
| `GET /api/v1/auth/me` | ✅ | ✅ | ✅ |

**后端 API 层权限实现**：

| API 模块 | 权限检查 | 说明 |
|----------|---------|------|
| `chat.py` | `get_current_user` + 拒绝 `role == "ai_operator"` | ai_operator 不可访问任何 chat 接口 |
| `admin.py` | `require_admin`（不变） | 仅 admin 可访问 |
| `operator.py` | `require_ai_operator` | ai_operator 或 admin 可访问 |
| 各 API 中报告操作 | `report.user_id == current_user.id` | 仅创建者可查看/下载/删除自己的报告 |

### 3.6 main.py 注册

```python
from app.api import operator
app.include_router(operator.router, prefix="/api/v1")
```

---

## 4. 前端设计

### 4.1 目录结构（全部新增）

```
frontend/src/
├── api/
│   └── operator.ts           # AI 操作者 API 调用（SSE + REST）
├── stores/
│   └── operator.ts           # Pinia store（报告列表、生成状态）
├── views/
│   └── OperatorView.vue      # AI 操作者工作台主页面
└── components/
    └── OperatorSidebar.vue   # AI 操作者侧边栏（报告历史列表）
```

### 4.2 路由设计

```typescript
// frontend/src/router/index.ts 新增
{
  path: '/operator',
  name: 'Operator',
  component: () => import('@/views/OperatorView.vue'),
  meta: { aiOperator: true },
}
```

**路由守卫更新**：
- `meta.aiOperator` 路由仅 `role === "ai_operator"` 或 `role === "admin"` 可访问，否则重定向到 `/`
- ai_operator 角色访问 `/` 和 `/admin` 时重定向到 `/operator`
- **登录跳转**：ai_operator 登录成功后跳转 `/operator`（而非 `/`）。admin 和普通用户维持跳转 `/`
- 登录跳转逻辑修改位置：[router/index.ts](frontend/src/router/index.ts) 第 50-52 行的 `to.path === '/login'` 守卫分支

### 4.3 前端认证 Store 扩展

`frontend/src/stores/auth.ts` 新增计算属性：

```typescript
const isAiOperator = computed(() => user.value?.role === 'ai_operator')
const canAccessOperator = computed(() => user.value?.role === 'ai_operator' || user.value?.role === 'admin')
```

### 4.4 安全渲染策略

报告内容是 LLM 生成的 Markdown。前端渲染链路：

```
Markdown 文本
    → marked（G FM 模式解析为 HTML，复用项目已有依赖）
    → DOMPurify.sanitize(dirty, { ALLOWED_TAGS: [...], ALLOWED_ATTR: [...] })
    → 安全 HTML 注入 v-html
```

**DOMPurify 配置要点**：
- `ALLOWED_TAGS`：白名单限制为排版标签（`h1-h6, p, ul, ol, li, table, thead, tbody, tr, th, td, strong, em, code, pre, blockquote, hr, br, sup, sub, a, span, div`）
- `ALLOWED_ATTR`：仅允许 `href, title, target, class, id, sup` 等安全属性
- 禁止所有事件处理器属性（`on*`）
- 禁止 `<script>`、`<iframe>`、`<object>`、`<embed>`、`<style>`、`<link>`、`<meta>` 等标签

> `marked` 和 `dompurify` 已在项目依赖中，无需新增。

### 4.5 OperatorView.vue 页面布局

```
┌──────────────────────────────────────────────────────────┐
│  Top Bar（56px）                                          │
│  🏥 AI 操作者工作台                 [用户信息] [退出]      │
├────────────┬─────────────────────────────────────────────┤
│            │                                             │
│  报告历史   │        报告内容区                             │
│  (260px)   │    ┌───────────────────────────┐            │
│            │    │ 科室：[肝胆外科] [神经外科] ▽│  多选下拉   │
│  + 新建    │    │ 输入分析问题...             │            │
│            │    │ [生成报告] [取消]           │            │
│  报告1     │    └───────────────────────────┘            │
│  报告2     │                                             │
│  报告3     │    ┌───────────────────────────┐            │
│  ...       │    │ Markdown 渲染的报告         │            │
│            │    │ （生成完成后展示）           │            │
│            │    │                           │            │
│            │    │ [下载 PDF]                 │            │
│            │    └───────────────────────────┘            │
└────────────┴─────────────────────────────────────────────┘
```

### 4.6 交互流程

1. 用户进入 `/operator`，左侧显示历史报告列表
2. 点击"+ 新建"或默认空态，右侧显示科室选择器和输入框
3. 选择科室（多选，默认全部），输入分析问题，点击"生成报告"
4. 内容区切换为流式渲染模式：显示"检索中..." → 逐字输出 Markdown 报告
5. 生成过程中可点击"取消"按钮中断生成（调用 `AbortController.abort()`，详见 4.8 节 SSE 实现方式）
6. 生成完成后显示"下载 PDF"按钮，点击可下载 PDF 文件
7. 报告自动保存到左侧历史列表

> 科室列表从现有 `GET /api/v1/departments`（公开接口）获取，复用不新增。

### 4.7 导航入口（仅 admin 可见）

在现有 ChatView 和 AdminView 的顶部导航中，为 admin 角色添加"AI 操作者工作台"入口：

- **ChatView**：顶部栏 `header-actions` 区域，在"管理后台"按钮旁增加"AI 操作者"按钮
- **AdminView**：侧边栏或顶部栏增加跳转链接
- **显示条件**：`v-if="authStore.isAdmin"`（ai_operator 角色不显示这些入口，因为 ai_operator 直接进入 /operator）

> 仅需修改 [ChatView.vue](frontend/src/views/ChatView.vue) 和 [AdminView.vue](frontend/src/views/AdminView.vue) 的 template，各加 ~3 行。

### 4.8 API 层（`frontend/src/api/operator.ts`）

```typescript
// 类型定义
interface Report { id, title, query, department_ids, department_names, content, sources, retrieval_meta, status, error_message, ... }
interface ReportCallbacks { onDelta, onSources, onStage, onDone, onError }
interface Department { id, name, is_active }      // 复用现有接口

// API 函数
fetchDepartments(): Promise<Department[]>          // GET /api/v1/departments（已有）
listReports(skip?, limit?): Promise<{total, items}>
getReport(id): Promise<Report>
deleteReport(id): Promise<void>
generateReport(query, departmentIds, callbacks): () => void  // fetch+ReadableStream SSE，返回 abort 函数
downloadReport(id): void                                     // 触发浏览器下载 PDF
```

> **SSE 实现方式**：`POST /operator/reports` 需要 JSON body，因此不能使用浏览器原生 `EventSource`（仅支持 GET）。前端使用 `fetch` + `ReadableStream` 手动解析 SSE 流，通过 `AbortController` 取消。后端 SSE 响应格式不变（`text/event-stream`）。

### 4.9 Pinia Store（`frontend/src/stores/operator.ts`）

```typescript
// 状态
reports: Report[]
currentReport: Report | null
loading: boolean
currentAbort: (() => void) | null

// 动作
loadReports()
loadReport(id)
generateReport(query)    // 管理 SSE 生命周期
deleteReport(id)
abort()                  // 取消当前生成
```

### 4.10 样式

- 遵循现有 `DESIGN_SPEC.md` 暖杏蓝方案
- 侧边栏宽度复用 `--sidebar-width: 260px`
- 报告内容区最大宽度可适当放宽（如 `960px`，因报告内容较密集）
- Markdown 渲染使用 `marked`（已在项目依赖中）
- 整体视觉风格保持专业、洁净，与医疗场景一致

---

## 5. 认证与安全

### 5.1 角色隔离

| 角色 | `/` Chat | `/admin` | `/operator` |
|------|----------|----------|-------------|
| user（医生/患者） | ✅ | ❌ | ❌ |
| admin | ✅ | ✅ | ✅（仅自己的报告） |
| ai_operator | ❌ | ❌ | ✅（仅自己的报告） |

**双重约束**：前端路由守卫 + 后端 API 层同时检查角色，不可仅依赖前端。

### 5.2 数据访问

- ai_operator 可检索**全部已索引文档**（不受 `source_access.user_can_access_document` 限制）
- 检索逻辑使用现有 `hybrid_search`，但调用方式独立（封装在 `report_generator.py` 中）
- 报告数据隔离：每份报告仅创建者可见（通过 `report.user_id == current_user.id` 校验）

### 5.3 输入安全

- 复用现有 `filter_input` 越狱/注入检测
- 复用 `detect_dangerous_symptoms` 危险症状检测
- 复用 `INPUT_MAX_LENGTH` 输入长度限制
- **不**复用 `SafeSentenceBuffer` 的输出替换逻辑（报告场景下过度屏蔽会影响分析质量），改为在报告末尾附加安全声明

### 5.4 审计日志

**MVP 方案**：复用现有 `audit_logs` 表，**不新增字段**。`ai_reports` 表保存报告业务状态和检索元数据。两者各司其职：

| 存储 | 内容 | 用途 |
|------|------|------|
| `audit_logs` | 每次报告生成操作事件 | 安全审计、操作追溯 |
| `ai_reports.retrieval_meta` | 检索参数、chunk IDs、模型配置、生成耗时 | 报告可追溯性、质量分析 |

**现有 `audit_logs` 字段映射**（无需迁移）：
- `user_id` → 操作者
- `request_body`（JSONB）→ 嵌入 `{"feature": "operator_report", "action": "generate", "report_id": 42, "query": "...", "department_ids": [...]}`
- `model` → LLM 模型名
- `latency_ms` → 生成耗时
- `retrieved_chunk_ids` → 本次检索到的 chunk ID 列表
- `safety_flags` → 安全检测结果
- `session_id` → 报告场景下为 NULL（不关联聊天会话）

> `feature`、`action`、`report_id` 等字段嵌入 `request_body` JSONB 中，不需要扩展 `audit_logs` 表结构。若后续审计查询频繁使用这些字段，可再考虑独立的迁移和索引。

---

## 6. 实现步骤（建议顺序）

| 步骤 | 内容 | 预估影响范围 |
|------|------|-------------|
| 1 | 数据库迁移：创建 `ai_reports` 表 + `backend/app/db/models.py` 新增 `AIReport` 模型 | 仅新增表，无现有数据影响 |
| 2 | 后端认证：`deps.py` 新增 `require_ai_operator` 依赖 | 1 个文件改 ~10 行 |
| 3 | 后端 Schema：`app/schemas/operator.py` | 新增文件，零影响 |
| 4 | 后端服务：`app/services/report_generator.py`（含多科室检索合并） | 新增文件，可独立删除 |
| 5 | 后端服务：`app/services/pdf_generator.py` + `app/templates/report_pdf.html` | 新增文件 |
| 6 | 后端 API：`app/api/operator.py` + main.py 注册 | 新增文件 + main.py 加 3 行 |
| 7 | 后端权限加固：`chat.py` 拒绝 ai_operator 角色 | 1 个文件改 ~3 行 |
| 8 | 创建 ai_operator 测试账号脚本 | `scripts/create_ai_operator.py` |
| 9 | 前端 Store 扩展：`auth.ts` 新增 `isAiOperator`、`canAccessOperator` | 1 个文件改 ~5 行 |
| 10 | 前端 API 层：`src/api/operator.ts` | 新增文件 |
| 11 | 前端 Store：`src/stores/operator.ts` | 新增文件 |
| 12 | 前端组件：`OperatorSidebar.vue` | 新增文件 |
| 13 | 前端页面：`OperatorView.vue`（含 marked + DOMPurify 渲染） | 新增文件 |
| 14 | 路由 + 守卫更新 + 登录跳转逻辑 | 现有 router/index.ts 改 ~15 行 |
| 15 | 导航入口：ChatView + AdminView 加"AI 操作者"按钮 | 2 个文件各改 ~3 行 |
| 16 | 编写测试（详见第 9 节） | 新增文件 |

---

## 7. 完整文件清单

### 新增文件（17 个）

```
database/migrations/010_add_ai_operator_reports.sql   # 手动 SQL 参考（幂等）
backend/alembic/versions/0004_add_ai_reports.py       # Alembic 迁移（正式）
backend/app/api/operator.py
backend/app/schemas/operator.py
backend/app/services/report_generator.py
backend/app/services/pdf_generator.py
backend/app/templates/report_pdf.html
backend/tests/test_report_generator.py
backend/tests/test_operator_api.py
backend/tests/test_operator_permissions.py
backend/tests/test_operator_state_machine.py
backend/tests/test_pdf_generation.py
scripts/create_ai_operator.py
frontend/src/api/operator.ts
frontend/src/stores/operator.ts
frontend/src/views/OperatorView.vue
frontend/src/components/OperatorSidebar.vue
```

### 新增依赖（backend/requirements.txt）

```
markdown          # Markdown → HTML 转换
weasyprint        # HTML → PDF 渲染（首选）
bleach            # HTML 安全清洗（PDF 生成前白名单过滤）
Jinja2            # PDF 模板引擎（通常已由 FastAPI 间接依赖）
```

### 修改文件（8 个）

```
backend/app/db/models.py               # 新增 AIReport ORM 模型
backend/app/api/deps.py                # 新增 require_ai_operator
backend/app/api/chat.py                # 拒绝 ai_operator 角色访问
backend/app/main.py                    # 加 1 行 import + 1 行 include_router
frontend/src/stores/auth.ts            # 新增 isAiOperator、canAccessOperator
frontend/src/router/index.ts           # 加 1 个路由定义 + 守卫条件 + 登录跳转逻辑
frontend/src/views/ChatView.vue        # 顶部栏加"AI 操作者"按钮（仅 admin 可见）
frontend/src/views/AdminView.vue       # 导航加"AI 操作者"入口（仅 admin 可见）
```

---

## 8. 验收条件

1. `role=ai_operator` 账号登录后自动跳转 `/operator`；`role=admin` 登录后跳转 `/`，可从聊天页导航进入 `/operator`
2. ai_operator 账号**无法**访问 `/`（聊天页）和 `/admin`（管理后台）——前端路由守卫拦截 + 后端 API 返回 403
3. admin 在 ChatView 和 AdminView 中可见"AI 操作者"导航入口
4. `/operator` 页面可选择科室范围（多选）+ 输入分析问题并点击生成报告
5. 报告以流式 SSE 方式逐字渲染，遵循固定 7 章模板（含 DOMPurify 安全渲染）
6. 第 5 章标题为"检索样本中的观察性特征"，明确标注非全量统计
7. 生成的报告可在左侧历史列表查看，支持删除；仅创建者可操作自己的报告
8. 生成过程中可点击"取消"中断，取消后报告状态为 `cancelled`，不残留 `generating`
9. 点击下载可导出 PDF 文件（A4 格式，含固定章节 + 页眉页脚 + 页码 + 中文正常渲染）
10. `report_generator.py` 通过 `analysis_backend` 参数预留预测模型切换能力
11. 多科室检索按规格正确去重、排序、截断
12. 禁用/移除 operator 路由、页面和相关导航入口后，现有聊天和管理功能回归测试通过（不要求物理删除文件来证明独立性）
13. 输入安全过滤正常工作
14. 目标部署环境可成功生成包含中文内容的 PDF 文件
15. 审计日志记录每次报告生成操作
16. 所有后端测试通过，前端构建通过

---

## 9. 测试矩阵

### 9.1 后端测试

| 测试文件 | 覆盖内容 |
|----------|---------|
| `test_report_generator.py` | 单科室/多科室/全库检索、检索去重排序、章节生成、引用编号、retrieval_meta 写入 |
| `test_operator_api.py` | SSE 事件顺序（stage → delta → sources → done）、报告 CRUD、分页、400/404 校验 |
| `test_operator_permissions.py` | 权限矩阵：user 访问 operator API → 403、ai_operator 访问 chat API → 403、ai_operator 访问 admin API → 403、admin 访问 operator API → 200、报告归属隔离（用户 A 不能查看用户 B 的报告） |
| `test_operator_state_machine.py` | 状态流转：generating → completed、generating → failed（LLM 异常）、generating → cancelled（客户端断连）、cancelled 报告不可下载 |
| `test_pdf_generation.py` | PDF 下载权限、中文渲染 smoke test、安全标签过滤 |

### 9.2 前端验证

- `npm run build` 通过
- `vue-tsc` 类型检查通过
- 手动验证：ai_operator 登录 → /operator、ai_operator 访问 / → 被重定向、admin 可见导航入口

---

## 10. 待讨论 / 已确定项

- [x] **报告模板**：已确定 — 固定 7 章模板（见 1.4 节），LLM 必须按章节输出
- [x] **下载格式**：已确定 — PDF（A4），通过 `markdown` + `weasyprint` + Jinja2 模板实时生成；备选 Playwright/reportlab
- [x] **检索范围**：已确定 — 前端多选科室下拉框（复用已有 `departments` 表 + `/api/v1/departments` 接口），默认全部科室；多科室按 per_dept_top_k 各取再合并去重
- [x] **admin 能否访问 /operator**：已确定 — admin 可以访问 `/operator`，但只能查看/操作自己创建的报告
- [x] **报告分享**：已确定 — 不需要分享功能，每份报告仅创建者可见
- [x] **预测模型接口预留**：已确定 — `report_generator.py` 主入口保留 `analysis_backend` 参数（默认 `"llm"`），API 层暂不暴露，后续扩展只需新增请求字段
- [x] **首页路由**：已确定 — ai_operator 登录后默认跳转 `/operator`
- [x] **导航入口**：已确定 — ChatView 和 AdminView 为 admin 添加"AI 操作者"入口（仅 admin 可见，ai_operator 不显示）
- [x] **术语**：已确定 — 正式名称为"AI 操作者"，"封弊者"保留为内部别称并在文档中说明含义
- [x] **迁移编号**：已确定 — Alembic `0004_add_ai_reports`，手动 SQL `010_add_ai_operator_reports.sql`
- [x] **权限实现**：已确定 — 集中在 `deps.py` 的 `require_ai_operator`，后端 chat/admin/operator API 三层分别校验
- [x] **状态机**：已确定 — pending → generating → completed | failed | cancelled
- [x] **审计日志**：已确定 — 复用 `audit_logs` 表记录操作事件（`feature="operator_report"`），`ai_reports.retrieval_meta` 保存检索元数据
- [x] **安全渲染**：已确定 — 前端 marked + DOMPurify.sanitize，PDF 端 HTML 白名单过滤
- [x] **第 5 章定位**：已确定 — 从"统计特征"改为"检索样本中的观察性特征"，明确非全量统计，降低用户预期

---

> **下一步**：请终审本规格。确认后我将创建正式的实施计划并开始编码。
