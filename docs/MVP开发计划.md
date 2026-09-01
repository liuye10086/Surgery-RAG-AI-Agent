# Surgery RAG AI Agent — MVP 开发计划

## 1. MVP 目标

基于项目规划中的 Phase 1 目标，MVP 要交付一个**可本地/内网运行的 Web Demo**，验证以下核心假设：

1. RAG 技术能有效减少医疗问答中的幻觉。
2. 基于私有知识库的回答能提供可验证的来源。
3. 多轮对话 + 引用 + 免责声明的产品形态对用户有价值。

> **当前状态（2026-07-22）**：MVP 开发已完成 🎉。Milestone 0–7 全部完成，RAG 全链路（检索 → 生成 → 流式 → 引用 → 审计）已跑通，安全合规（内容过滤 + 危险症状 + 数据导出/删除）已接入，DEPLOY.md 部署手册已编写，内网 Demo 已可运行。

---

## 2. MVP 范围

### 2.1 In Scope

- 用户认证（JWT，支持 `user` 和 `admin` 两种角色）。
- Web 聊天界面（类 DeepSeek 风格），支持多轮对话、引用卡片、免责声明。
- 后台管理页：上传 PDF / Word / 图片，查看文档列表和索引状态，分块预览与单块删除。
- 文档解析与向量化：PDF（pymupdf）、Word（python-docx）、图片 OCR（PaddleOCR）。
- 分块策略：章节标题感知 + 病历级感知（完整病历优先作为单一块）。
- 向量存储：LangChain PGVector（`langchain-postgres`），底层 PostgreSQL + pgvector。
- RAG 检索：向量相似度 + PostgreSQL 全文检索的混合检索（**Milestone 3 实现**）。
- 答案生成：DeepSeek API（`deepseek-chat`），强制基于上下文、要求内联引用（**Milestone 3 实现**）。
- 流式输出（**Milestone 3/4 实现**）。
- 记忆：最近 4–6 轮对话上下文（**Milestone 3/4 实现**）。
- 审计日志：记录用户问题、检索片段、模型回复、延迟、安全标记（✅ 已完成，`AuditCallbackHandler` + `log_chat` + `safety_flags`）。
- 内容安全：输入过滤（越狱阻断+医疗诱导标记）、输出免责声明、危险症状提示（✅ 已完成，`content_filter.py` + 前端危险警告卡片）。

### 2.2 Out of Scope

- 视频解析。
- 复杂 Agent / 工具调用 / 多 Agent 协作。
- 真实病历数据（脱敏完成前不上传）。
- 重排序模型（reranker）。
- 生产级负载均衡 / 自动扩缩容。
- 自动化评估框架。
- 正式生产环境部署（阿里云部署作为项目后期阶段，MVP 只做到本地/内网可演示）。
- 医疗诊断/处方的最终责任判定（系统仅作参考）。

---

## 3. 系统架构（当前已实现 vs 待实现）

```
┌────────────────────────────────────────────┐
│  Vue 3 Web Frontend                        │
│  - 聊天页（多轮对话、占位回复、免责声明）  │ ✅
│  - 管理页（上传、分块、向量化、预览）      │ ✅
└──────────────┬─────────────────────────────┘
               │ HTTPS / JSON / SSE
┌──────────────▼─────────────────────────────┐
│  FastAPI Backend                           │
│  - /auth/*          登录/注册              │ ✅
│  - /chat            会话/消息 CRUD         │ ✅
│  - /chat            RAG 问答 + 记忆        │ ✅ Milestone 3–4
│  - /admin/documents 文档管理               │ ✅
│  - 中间件：审计日志、安全过滤          │ ✅ Milestone 5
└──────┬──────────────────────┬──────────────┘
       │                      │
┌──────▼────────────┐  ┌──────▼───────────────┐
│  RAG Pipeline     │  │  Ingestion Pipeline  │
│  - 查询改写       │ ✅│  - PDF/Word/OCR 解析 │ ✅
│  - 向量检索       │ ✅│  - 清洗/分块         │ ✅
│  - 全文检索       │ ✅│  - Embedding         │ ✅
│  - 混合排序       │ ✅│  - pgvector 写入     │ ✅
│  - Prompt 构建    │ ✅│  - 文档状态跟踪      │ ✅
└──────┬────────────┘  └──────────────────────┘
       │
┌──────▼────────────┐  ┌──────────────────────┐
│  DeepSeek API     │  │  PostgreSQL + pgvector│
│  - deepseek-chat  │  │  - chunks, sessions  │ ✅
│  - 流式输出       │ ✅│  - messages, users   │ ✅
│                   │  │  - audit_logs        │ ✅ 已接入
└───────────────────┘  └──────────────────────┘
```

说明：

- 入库链路（Ingestion Pipeline）与数据表已完成。
- RAG 检索、DeepSeek 调用、流式输出、多轮记忆、审计接入已在 M3–M4 完成，采用自定义 LangChain 适配器方案。
- M5 安全合规（内容过滤 + 危险症状 + 数据导出/删除 + DEPLOY.md）已完成。

---

## 4. 技术栈

| 层级 | 选型 | 理由 |
| ------ | ------ | ------ |
| 后端框架 | FastAPI + Pydantic v2 | 异步原生、自动 OpenAPI、SSE 流式友好、适合单人快速开发 |
| ORM / 迁移 | SQLAlchemy 1.x 声明式 + Alembic | 当前代码使用 `Column(...)` 声明式；`backend/alembic/` 完整管理当前全部业务表和数据库扩展，旧 SQL 仅作历史参考 |
| 认证 | python-jose + passlib | JWT 方案轻量 |
| 数据库 | PostgreSQL 18.1 + pgvector（与 15+ 兼容） | 用户已本地安装 PostgreSQL 18.1；关系数据与向量存储一体 |
| 文档解析 | pymupdf、python-docx、PaddleOCR | 分别覆盖 PDF、Word、图片中文 OCR |
| Embedding | BAAI/bge-m3（本地 sentence-transformers） | 中英双语医学检索效果好；MVP 规模本地运行足够 |
| 模型下载 | modelscope + huggingface_hub | 优先 ModelScope 国内镜像，失败回退 HuggingFace，跳过 safetensors 减少体积 |
| LLM | DeepSeek API（deepseek-chat） | 用户指定，通过 OpenAI 兼容 SDK 调用 |
| 前端 | Vue 3 + Vite + TypeScript + Element Plus | 开发者已掌握 Vue；生态成熟；未引入 Tailwind CSS |
| 部署（后期） | Git-based + 阿里云 ECS/RDS + Nginx | 不使用 Docker；代码通过 git 部署 |
| 对象存储（后期） | 阿里云 OSS（可选） | 原始文件不落数据库 |
| 监控（后期） | 阿里云 CloudMonitor / SLS | 与阿里云生态集成 |

---

## 5. 数据与 RAG 流程

### 5.1 文档入库流程

1. 管理页上传文件 → FastAPI 接收 → 记录 `documents` 表（status=`pending`）。
2. 管理员点击 **分块**：
   - 解析：PDF → pymupdf 按页提取文本；图片页走 PaddleOCR。
   - DOCX → python-docx 提取段落/表格；自动修复 WPS 生成的 `Target="NULL"` 关系。
   - 图片 → PaddleOCR 提取文本。
   - 清洗：去除 NUL 字符、统一换行、去首尾空白。
   - 分块：
     - 检测到病历标题（`病例 1 / 案例 1 / Case 1`）时，尽量把一例完整病历作为单个 chunk，上限 `CASE_CHUNK_MAX_SIZE=1500`。
     - 否则检测章节标题，按标题切分并在每块保留标题上下文。
     - 无标题时回退到段落感知分块，避免从句子中间切断。
   - 删除旧 chunks，插入新 chunks；业务表保存原文和元数据，向量由 LangChain PGVector 独立管理。
   - 更新 `documents` status=`chunked`。
3. 管理员审查分块后点击 **向量化入库**：
   - bge-m3 分批生成 1024 维归一化向量。
   - 写入 `langchain_pg_embedding`，通过向量记录 ID 关联 `chunks.id`。
   - 更新 `documents` status=`indexed`。
4. 若某 chunk 质量不合格，可在分块预览抽屉中单独删除；删除最后一块后文档状态回退到 `chunked`。
5. 重新分块会清理对应的 LangChain 向量记录，状态回到 `chunked`，需再次向量化。

### 5.2 核心数据库表

```sql
users(id, username, email, real_name, hashed_password, role, created_at)
documents(id, title, filename, file_path, file_type, file_size, status, error_message, version, is_current, active_generation, created_at, updated_at)
chunks(id, document_id, content, metadata jsonb, page_number, chunk_index, is_current, generation, created_at)
sessions(id, user_id, title, created_at, updated_at)
messages(id, session_id, role, content, lc_message jsonb, sources jsonb, is_error, is_no_knowledge, client_request_id, created_at)
audit_logs(id, user_id, session_id, request_body, retrieved_chunk_ids, response_text, latency_ms, model, safety_flags, created_at)
```

此外，`langchain-postgres` 管理 `langchain_pg_collection` 和 `langchain_pg_embedding` 两张内部向量表；程序在向量表的 `document` 列上维护全文检索索引。业务表由 Alembic 管理，`database/schema.sql` 仅作为结构参考快照。

### 5.3 检索流程（Milestone 3 实现）

1. 查询改写：基于最近对话历史，把代词和省略补全。
2. 向量检索：pgvector 取 top-K。
3. 全文检索：PostgreSQL `tsvector`/`tsquery` 取 top-K。
4. 混合排序：Reciprocal Rank Fusion（RRF）融合向量与全文结果。
5. 取 top 5–7 片段作为上下文。
6. 如果最高相似度低于阈值，触发“未在知识库中找到依据”警告。

### 5.4 引用与 grounding

- 每个上下文片段按 1 开始编号，Prompt 要求模型使用 `[1]`、`[2]` 格式内联引用。
- 后端按上下文序号映射回真实 `chunk_id`，返回 `sources` 数组（标题、页码、摘要）。
- 系统 Prompt 强制：只能基于上下文回答；信息不足时明确说明。

---

## 6. 安全与合规设计

### 6.1 数据脱敏

- MVP 不上传真实病历。
- 自动医疗脱敏尚未实现；后续可在入库流程中接入 Presidio 或医疗 NER 脱敏器。在此之前不得上传未经合规处理的真实病历。

### 6.2 审计日志

- 记录：用户 ID、会话 ID、问题、检索片段 ID、模型回复、延迟、模型名、触发安全规则情况。
- 存储于 PostgreSQL `audit_logs` 表。
- `backend/app/services/audit.py` 已提供 `log_chat()` 函数，已接入聊天接口，支持 `safety_flags` 记录安全过滤命中情况（✅ M5 完成）。

### 6.3 内容安全

- 输入：关键词/正则过滤越狱、诱导性提问；识别急诊/危险症状（✅ M5 完成，`content_filter.py` + 规则库 JSON）。
- 输出：系统 Prompt 禁止确定性诊断和处方（✅ 已接入）；输出过滤检测药物剂量/确定性诊断并记录审计（✅ M5 完成）。
- 危险症状命中时，不阻断正常问答，前端在用户消息下方展示红色（critical）或黄色（warning）警告卡片，优先提示立即就医（✅ M5 完成）。

### 6.4 访问控制

- JWT 认证，HTTPS 传输。
- 角色：`user`（聊天、看自己的历史）、`admin`（上传文档、看审计日志）。
- 普通注册用户固定为 `user`；管理员由部署人员通过脚本创建。

### 6.5 合规映射

- **个保法 / 数据安全法 / 网络安全法**：数据不出境（阿里云中国节点）、传输加密、存储加密、最小收集、审计日志、用户删除权。
- **医疗建议**：固定免责声明，明确“仅供参考，不构成医疗建议”。

---

## 7. 开发里程碑

### Milestone 0：项目脚手架（Day 1–2）

- 初始化仓库、Python 虚拟环境、`.gitignore`。
- 本地开发直接使用已安装的 PostgreSQL 18.1，安装 pgvector 扩展即可（`CREATE EXTENSION vector;`）。无需 Docker。
- 项目目录结构（已按根目录组织）：
  ```
  surgery-rag/
  ├── backend/          # FastAPI 后端
  │   ├── app/
  │   │   ├── api/      # FastAPI 路由
  │   │   ├── core/     # 配置、安全
  │   │   ├── db/       # SQLAlchemy 模型
  │   │   ├── ingestion/# 解析、分块
  │   │   ├── rag/      # RAG 检索流程（当前为空，待 M3）
  │   │   ├── services/ # 文件存储、Embedding、审计、LLM（部分待实现）
  │   │   └── main.py
  │   ├── alembic/     # 业务表迁移
  │   ├── alembic.ini
  │   ├── requirements.txt
  │   └── .env
  ├── frontend/         # Vue 3 前端
  │   ├── src/
  │   │   ├── views/    # ChatView / AdminView / LoginView
  │   │   ├── components/
  │   │   ├── api/
  │   │   ├── stores/
  │   │   ├── router/
  │   │   └── App.vue
  │   ├── package.json
  │   └── vite.config.ts
  ├── database/         # 结构参考与历史 SQL
  │   ├── schema.sql    # 当前结构参考快照
  │   ├── migrations/  # 旧版 006/007/008
  │   └── README.md
  ├── scripts/          # 管理与诊断脚本（根目录）
  │   ├── create_admin.py
  │   ├── evaluate_rag.py
  │   └── check_documents.py
  └── uploads/          # 运行时上传文件（根目录，不进入 git）
  ```
- 数据库初始化和后续升级统一从 `backend/` 执行 `alembic upgrade head`。
- `database/schema.sql` 是参考快照，`database/migrations/006–008` 是接入 Alembic 前的历史资料。

### Milestone 1：认证与基础 API（Day 3–5）— ✅ 已完成

- 用户模型、JWT 登录/注册。
- 管理员不再由首个注册用户自动获得，统一使用 `python scripts/create_admin.py` 创建。
- 会话和消息 CRUD。
- 审计日志骨架（`services/audit.py` + `audit_logs` 表），但聊天接口尚未调用。
- 健康检查接口。

### Milestone 2：文档入库（Day 6–10）— ✅ 已完成，拆分为 2A + 2B

#### Milestone 2A：上传、解析、分块（Day 6–8）— ✅ 已完成

- 上传接口和管理页。
- PDF / DOCX 解析；WPS docx `Target="NULL"` 自动修复。
- PaddleOCR 图片解析。
- 章节标题感知分块 + 病历级感知分块。
- 文档状态跟踪（`pending` → `parsing` → `chunked` / `failed`）。
- 分块预览抽屉，支持单块删除。

#### Milestone 2B：Embedding 与 pgvector 入库（Day 9–10）— ✅ 已完成

- bge-m3 生成 1024 维归一化向量。
- ModelScope 国内镜像优先下载，失败回退 HuggingFace，跳过 safetensors。
- `/documents/{id}/index` 向量化入库接口。
- 文档状态流转（`chunked` → `indexing` → `indexed` / `failed`）。
- 重新向量化、大文档 5 分钟超时前端处理。
- 删除 chunk 后状态回退逻辑。

### Milestone 3：RAG 与 DeepSeek 集成（Day 11–16）— ✅ 已完成

- 向量检索 + 全文检索 + RRF 融合（`backend/app/rag/pipeline.py`）。
- DeepSeek API 调用（OpenAI 兼容 SDK），流式输出（`backend/app/services/llm_client.py`）。
- 引用解析与来源映射（`parse_citations`）。
- “未在知识库中找到依据”警告（`has_sufficient_knowledge`）。
- LangChain 自定义适配器：`SurgeryEmbeddings`、`SurgeryRetriever`、`SurgeryChatMessageHistory`、`AuditCallbackHandler`（`backend/app/rag/adapters.py`）。

> **实现方式**：采用自定义 LangChain 适配器复用现有数据库 schema，未使用 LangChain 官方 PGVector / RunnableWithMessageHistory。后续 M3-modify 计划将升级为官方 LangChain 方案。

### Milestone 4：聊天界面与记忆（Day 17–21）— ✅ 已完成

- Vue 3 聊天页（流式展示、引用卡片、来源面板、免责声明）。
- 会话历史侧边栏（折叠/展开、会话切换、删除）。
- 多轮记忆（最近 6 轮，`SurgeryChatMessageHistory` + SSE `history`）。
- 加载动画（心跳圆点 + 状态文案）与空泡过滤。
- 欢迎页（推荐问法标签）。

### Milestone 5：安全、合规、审计（Day 22–25）— ✅ 已完成（2026-07-22）

- 输入安全过滤：越狱/注入检测（正则 + 关键词），阻断恶意输入返回 422，医疗诱导标记但不阻断。
- 输出安全过滤：检测确定性诊断/药物剂量，记录到 `safety_flags`。
- 危险症状提示：critical/warning 两级，前端红色/黄色内嵌警告卡片，不阻断正常问答。
- 审计日志完善（接入聊天接口）：已完成（`AuditCallbackHandler` + `log_chat` + `safety_flags JSONB`）。
- 数据导出/删除接口（个保法）：`GET /api/v1/user/export` + `DELETE /api/v1/user/account`（密码验证）。
- Settings 页面：`/settings` 路由，所有登录用户可访问，侧边栏 `...` 弹出菜单入口。
- 部署与密钥运行手册：`DEPLOY.md`（8 章，~400 行）。
- 当时通过 `database/migrations/007_add_safety_flags.sql` 落地；当前已纳入 Alembic 基线统一管理。

### Milestone 6：内网 Demo 与试用反馈（Day 26–30）— ✅ 已完成（2026-07-22）

- 在本地/内网环境完整运行系统（后端 + 前端 + PostgreSQL）✅。
- 邀请 3–5 名目标用户（医生/医学生）试用 ✅。
- 收集反馈并修复关键问题 ✅。
- 整理部署运行手册（`DEPLOY.md`），为后续上云做准备 ✅。

### 后续阶段（功能完整验证后）：阿里云生产部署— ⏳ 未开始

- 开通 RDS + ECS，配置环境。
- git 拉取代码，安装依赖，启动后端，构建前端。
- Nginx + SSL 部署。
- 正式上线与小范围公测。

### Milestone 7：医学专家评估与迭代（Day 31–45）— ✅ 已完成（2026-07-22）

- 准备 50–100 条外科 Q&A 评测集 ✅。
- 医学专家评分 + LLM-as-judge ✅。
- 根据反馈优化分块、Prompt、检索策略 ✅。

---

## 7.5 MVP 完成后的改进方向

以下问题在 MVP 开发过程中被识别，部分已在 M5 解决，其余作为后续迭代方向。

### 数据安全与隐私保护（高优先级）

当前知识库的病例可能包含年龄、性别、住院号等可识别信息，系统尚无自动脱敏能力。后续可在入库流程中接入 Microsoft Presidio 或医疗 NER 脱敏；在此之前必须只使用匿名、公开或已人工合规处理的资料。

### 检索与回答质量评估（中优先级）

目前缺乏量化手段衡量检索命中率和回答准确性。建议方向：
- 构建小型测试集（20 个典型问题 + 期望的检索病例编号），人工标注后用于回归测试
- 引入 RAGAS 等自动化评估框架，评估检索精度和回答忠实度
- 建立用户反馈机制（点赞/点踩），收集真实使用反馈

### 用户反馈机制

当前用户无法标记回答质量。建议在每条 AI 回答下方增加"有帮助 / 无帮助"按钮，反馈数据汇总到后台管理页面。

### 全文检索中文优化

当前使用 PostgreSQL `pg_trgm` 三元组相似度，对中文效果不如专用分词器。后续可在 PostgreSQL 中安装 zhparser 中文分词扩展，使用 `tsvector`/`tsquery` 替代 `similarity()`。

### 病例图片/视频信息利用

病例中的术中照片、超声图像、CT 影像等视觉信息当前仅通过 OCR 提取文字，图片本身的视觉诊断价值未被利用。后续方向见下方「下一步计划」。

---

## 7.6 下一步计划

MVP 完成后的核心演进方向是**从纯文字问答升级为文字+图片+视频的多模态助手**：

### 病例图片支持

**后台—图片管理**：在管理员侧边栏已有「图片管理」入口（当前为占位），后续实现图片上传、关联到具体病例和章节、图片元数据编辑（标题/描述/类型）、按病例和类型筛选。

**前端—来源面板改造**：点击引用病例时，新增「查看完整病例」入口，弹出病例详情（文字 + 关联图片缩略图网格，点击放大预览）。

### 视频素材库

自建手术教学视频素材库，按手术步骤剪辑成独立片段后上传。后台「视频管理」入口（当前为占位）支持：上传视频片段、标注结构化标签（手术类型、步骤名称、序号、关键词）、按标签筛选、预览播放。

### 聊天界面双模式

- **问答模式（默认）**：当前文字 RAG 问答
- **视频模式**：用户问手术操作过程时，LLM 按步骤给出文字讲解 + 后端从素材库匹配视频片段 → FFmpeg 拼接为完整视频 → 前端展示

---

## 7.7 关于临床预测性分析

当前 100 例胆囊结石病例只能做**描述性总结**（对已有事实的归纳，如"68 例术前 ALT 超出正常范围"），不能做**预测性/诊断性结论**（如"这个结石一定是胆固醇性结石吗？"）。原因：样本量太小（100 例按维度切开后每个子组仅几个到十几个，统计上无意义）、RAG 本质是检索+归纳而非统计分析、数据来源单一（同一医院/时期/团队）。

后续若病例积累到 300–500 例以上，可逐步推进：病例数据结构化（LLM 批量提取结构化字段）→ 描述性统计 → 相关性探索（如 BMI 与术后并发症）→ 临床预测模型（如胆总管结石预测模型、术后并发症风险分层）。预测模型仅作为决策辅助参考，不能替代医生临床判断。

---

## 8. 关键实现文件

| 文件 | 职责 | 状态 |
| ------ | ------ | ------ |
| `backend/app/db/models.py` | 核心数据模型 | ✅ 已完成 |
| `backend/app/ingestion/parser.py` | PDF/Word/图片解析与 OCR，含 WPS NULL 关系修复 | ✅ 已完成 |
| `backend/app/ingestion/chunker.py` | 文本分块：章节标题感知 + 病历级感知 | ✅ 已完成 |
| `backend/app/services/file_storage.py` | 上传文件本地存储、扩展名校验 | ✅ 已完成 |
| `backend/app/services/embedder.py` | bge-m3 向量生成、ModelScope/HF 下载 | ✅ 已完成 |
| `backend/app/services/audit.py` | 审计日志写入函数 | ✅ 已完成，已接入聊天接口 |
| `backend/app/api/admin.py` | 文档上传/管理/分块/向量化/单块删除接口 | ✅ 已完成 |
| `backend/app/api/auth.py` | 登录/注册/当前用户 | ✅ 已完成 |
| `backend/app/api/chat.py` | 会话/消息 CRUD + SSE RAG 问答 | ✅ 已完成 |
| `backend/app/rag/pipeline.py` | 混合检索（向量+全文+RRF）、查询改写、阈值判断 | ✅ 已完成 |
| `backend/app/services/llm_client.py` | DeepSeek LCEL 链、流式、引用解析 | ✅ 已完成 |
| `backend/app/rag/adapters.py` | LangChain 适配器（Embedding/Retriever/History/Callback） | ✅ 已完成 |
| `backend/app/services/rewrite_client.py` | LLM 查询改写 | ✅ 已完成 |
| `frontend/src/views/ChatView.vue` | 聊天主页面（流式、来源面板、欢迎页、加载动画） | ✅ 已完成 |
| `frontend/src/components/ChatMessage.vue` | 单条消息（Markdown、引用、免责声明） | ✅ 已完成 |
| `frontend/src/components/ChatSidebar.vue` | 会话侧边栏（折叠/展开、切换、删除） | ✅ 已完成 |
| `frontend/src/components/InfoPanel.vue` | 信息来源面板（按问题分组、展开、定位） | ✅ 已完成 |
| `frontend/src/views/AdminView.vue` | 文档管理页 | ✅ 已完成 |
| `frontend/src/api/admin.ts` | 管理后台 API 封装 | ✅ 已完成 |
| `frontend/src/api/chat.ts` | 聊天 API 封装（SSE 流式） | ✅ 已完成 |
| `frontend/src/stores/chat.ts` | 聊天状态管理（流式、重试、会话管理） | ✅ 已完成 |
| `backend/app/services/content_filter.py` | M5 内容安全过滤（越狱+危险症状+输出过滤） | ✅ M5 完成 |
| `backend/app/data/jailbreak_patterns.json` | M5 越狱模式库（正则+关键词） | ✅ M5 完成 |
| `backend/app/data/dangerous_symptoms.json` | M5 危险症状词库（critical/warning） | ✅ M5 完成 |
| `backend/app/api/user.py` | M5 用户数据导出/删除 API（个保法合规） | ✅ M5 完成 |
| `frontend/src/views/SettingsView.vue` | M5 账户设置页（导出+删除） | ✅ M5 完成 |
| `DEPLOY.md` | M5 部署与密钥运行手册（8 章） | ✅ M5 完成 |
| `scripts/check_documents.py` | 上传前 docx/pdf 检查工具 | ✅ 已完成 |
| `scripts/create_admin.py` | 由部署人员创建管理员账户 | ✅ 已完成 |
| `scripts/evaluate_rag.py` | 运行 RAG 10 条检索基线 | ✅ 已完成 |

---

## 9. 验证方式

### 9.1 本地验证（当前已可执行）

- 确保本地 PostgreSQL 18.1 已启用 pgvector 扩展（`CREATE EXTENSION vector;`）。
- 运行后端：`cd backend && uvicorn app.main:app --reload`。
- 运行前端：`cd frontend && npm run dev`。
- 登录 → 进入 `/admin` 上传 1 份 PDF/DOCX → 点击 **分块** → 状态变为 `chunked` → 点击 **向量化入库** → 状态变为 `indexed`。
- 数据库验证：

  ```sql
  SELECT c.chunk_index, e.id AS embedding_id
  FROM chunks AS c
  LEFT JOIN langchain_pg_embedding AS e
    ON e.id::text = c.id::text
  WHERE c.document_id = 1
    AND c.is_current = true
  ORDER BY c.chunk_index;
  ```

  所有当前分块都应有对应的 `embedding_id`。BGE-M3 的 1024 维配置由应用的 Embedding 模型与 PGVector 集合共同维护，不再存放在 `chunks` 表中。

### 9.2 Milestone 3 端到端测试用例（✅ 已完成）

- 上传《胆囊切除术操作规范》PDF，提问”胆囊切除术如何避免损伤胆总管？”，期望回答引用该文档具体页码。
- 提问与知识库无关的问题，期望触发”未在知识库中找到依据”提示。
- 连续追问 3 轮，验证多轮记忆生效。

### 9.3 内网 Demo 验证（✅ M6 完成）

- 在本地或内网服务器上完整启动后端、前端和 PostgreSQL。
- 邀请 3–5 名用户试用，收集反馈。

### 9.4 后续部署验证（项目后期）

- 阿里云 ECS 上通过 git 拉取代码，安装依赖，启动后端，构建前端。
- 配置 Nginx + HTTPS。
- 正式上线与小范围公测。

### 9.5 专家评估（✅ M7 完成）

- 准备 50–100 条 Q&A。
- 医学专家对回答的准确性、引用相关性、安全性打分。
- 根据评分迭代分块策略和 Prompt。

---

## 10. 部署方案（项目后期再落地）

> 本章节不作为 MVP 内容，仅在项目完整功能验证通过后实施。MVP 阶段目标为本地/内网可运行 Demo。

### 10.1 阿里云资源（试点 → 生产）

| 资源 | 用途 | 规格建议 |
|------|------|----------|
| ECS | 运行 FastAPI + Vue 3 | 4 vCPU 8 GB → 8 vCPU 32 GB |
| RDS PostgreSQL + pgvector | 数据库 | 2 vCPU 4 GB → 4 vCPU 8 GB |
| OSS | 原始文件存储 | 按量付费 |
| CloudMonitor / SLS | 监控日志 | 按量付费 |
| SLB | 负载均衡（远期） | 共享实例 |

### 10.2 部署步骤概要

1. 阿里云创建 VPC + vSwitch（上海/北京）。
2. 创建 RDS PostgreSQL 15+（兼容本地 PostgreSQL 18.1），启用 `CREATE EXTENSION vector;`。
3. 创建 ECS，安装 Python 3.11+、Node.js 18+、Nginx、PostgreSQL 客户端、git。
4. 创建 OSS bucket 并配置密钥。
5. 在 ECS 上 `git clone` 项目代码，安装后端依赖（`pip install -r requirements.txt`）和前端依赖（`npm ci`），并在 `backend/` 执行 `alembic upgrade head`。
6. 后端用 systemd / supervisor / gunicorn + uvicorn 运行；前端执行 `npm run build`，Nginx 托管 `dist/` 并反向代理到后端。
7. Nginx 配置反向代理 + SSL。
8. 环境变量管理：开发用 `.env`，生产迁移至阿里云 KMS。

### 10.3 密钥管理

- `DEEPSEEK_API_KEY`、`DATABASE_URL`、`JWT_SECRET`、`OSS_ACCESS_KEY` 等通过环境变量注入。
- 生产环境使用阿里云 KMS / 参数仓库。

---

## 11. 成本估算（月度，试点/生产阶段）

> 以下为项目后期上云后的粗略范围；MVP 阶段主要成本仅为 DeepSeek API 调用和本地开发机器。实际以阿里云和 DeepSeek 最新定价为准。

| 项目 | 小规模试点 | 较大规模试点 |
|------|-----|------|
| ECS | ¥300–600 | ¥800–1,500 |
| RDS PostgreSQL | ¥300–600 | ¥800–1,500 |
| OSS + 流量 | ¥50–300 | ¥100–500 |
| 监控/日志 | ¥100–300 | ¥200–500 |
| DeepSeek API（按 50–200 人 Demo） | ¥200–1,000 | ¥1,000–5,000 |
| Embedding（本地 bge-m3） | 含在 ECS 内 | 含在 ECS 内 |
| **合计** | **¥1,000–3,000** | **¥3,000–10,000** |

说明：
- MVP 阶段无需上云，主要跑在本地/内网，成本主要为 DeepSeek API 调用。
- 1000 并发为远期目标，试点阶段不需要按此规模部署。
- 若后续真达到 1000 并发，需要 SLB + 多 ECS 实例 + 异步队列 + 连接池，月成本预计 ¥5,000–15,000。

---

## 12. 与项目规划的衔接

本 MVP 开发计划是实现 [项目规划.md](项目规划.md) 中 Phase 1 的具体技术方案。项目规划负责回答“为什么做、做什么、做成什么样”，本文档负责回答“MVP 怎么实现、用什么技术、按什么节奏做”。
