# 参考标准上传/解析链路现状留痕（重构前审计）

- 记录时间：2026-08-21
- 状态：**纯记录，未决定是否重构，未开始任何实施**
- 背景：Task A（预测统计患者去重 + 参考范围表格解析/性别分列修复）已完成并通过测试。实施过程中发现"参考标准文档上传→解析为 reference_ranges"这条链路存在多处临时/手工设计（详见下文"设计层面的别扭之处"）。用户判断这条链路需要彻底重构（从数据库到前端），但核心思路不变；决定先继续 Task B（纵向进展预测），等整体链路跑通后再专门回来重构这一段。
- 本文档目的：把当前链路涉及的**全部文件**和**完整数据流**记录清楚，作为未来重构的起点参考，避免遗漏。

---

## 一、完整链路（端到端数据流）

```
① 操作者/管理员在 AdminView 上传文档（通用文档上传表单，手动选择 access_scope=operator/both）
        │  POST /admin/documents/upload
        ▼
② Document 行创建（status 初始，file_path 落盘到 uploads/）
        │  操作者在 AdminView 点击"分块"
        │  POST /admin/documents/{id}/chunk
        ▼
③ parser.py: parse_file() → parse_docx()
   - 段落文本逐条提取
   - 表格逐行序列化为 "| 单元格 | 单元格 |" 文本行，拼接进同一文本流
        │
        ▼
④ chunker.py: chunk_pages() 按策略切块 → Chunk 行（新 generation，未激活/is_current=False）
        │  操作者在 AdminView 点击"索引"
        │  POST /admin/documents/{id}/index
        ▼
⑤ embedder.py + adapters.py(SurgeryEmbeddings) + vectorstore.py(add_chunks)
   → 写入 PGVector，激活该 generation（document_indexing.py: activate_generation）
        │
        ▼
⑥ 操作者在 CaseManageView（OperatorView 的一个 tab）选择"sync_ready"文档，点击"解析为参考范围"
        │  POST /operator/reference-ranges/sync  { document_id }
        ▼
⑦ reference_standard.py: sync_reference_ranges(db, document_id)
   a) 校验 access_scope ∈ {operator, both}（此处才校验，上传时不校验）
   b) 表格解析：_parse_tables_from_docx() 重新从磁盘打开原始 docx 文件（不复用②③④的 Chunk/向量结果），
      按硬编码的两种表头关键词（"正常范围"/"脂肪肝" 或 "normal"/"ad_pattern"）识别表格类型并逐行提取
   c) 段落解析：对 Chunk.content 按行跑确定性正则 parse_reference_segment()
      （含性别分段"男性...；女性..."、en-dash、约/常见为等修饰词处理）
   d) 未命中确定性正则的行 → 交给 DeepSeek LLM 兜底解析（_sync_from_llm）
   e) 合并 表格结果 + 确定性结果 + LLM结果，按 (指标名小写, 性别, 边界值, 单位, 开闭区间) 去重
   f) 整表 DELETE document_id 对应旧 ReferenceRange 行，再整批 INSERT 新结果（无版本、无预览、不可回滚）
        │
        ▼
⑧ ReferenceRange 表（indicator_name, name_cn, unit, lower/upper, lower/upper_inclusive, sex, category, document_id）
        │
        ▼
⑨ CaseManageView 展示已解析的 ReferenceRange 列表（只读，无编辑/删除单条能力）
        │
        ▼
⑩ 预测时消费：prediction_generator.py: generate_prediction()
   - 按小写 indicator_name 模糊匹配查询 ReferenceRange
   - _range_map() 按 patient_sex 解析出该用哪条（性别专属 or 通用）
   - 缺失任一指标范围 → 直接报错"缺少参考范围"
   - 结果喂给 prediction_engine.py: analyze_indicators() / compute_composite_probability()
```

---

## 二、涉及文件清单（按阶段）

### 阶段1：前端 —— 上传、分块/索引触发、参考范围同步 UI

| 文件 | 行数 | 在本链路中的作用 |
|---|---|---|
| `frontend/src/views/AdminView.vue` | 854 | 管理员文档管理页。通用上传表单（文件、标题、部门、access_scope 下拉，默认 `chat`），文档列表 + 每行"分块"/"索引"按钮。 |
| `frontend/src/api/admin.ts` | 118 | `uploadDocument`（含 access_scope 字段）、`chunkDocument`、`indexDocument`（5分钟超时）、`updateDocument`（可改 access_scope）等。 |
| `frontend/src/components/CaseManageView.vue` | 447 | 操作者端面板（挂在 OperatorView 下）：疾病字典、病例库、"正常体征参考标准"三个区块——文档选择器（仅 sync_ready 可选）+"解析为参考范围"按钮 + 只读的已解析 ReferenceRange 列表。 |
| `frontend/src/api/operator.ts` | 356 | `syncReferenceRanges(documentId)`、`listReferenceRanges()`（只读）、`listOperatorDocuments()`（过滤 access_scope ∈ operator/both），以及预测报告 SSE 相关。 |
| `frontend/src/utils/rangeFormat.ts` | 18 | `formatRange()`：把 `{lower, upper, inclusive, unit}` 渲染成 `≤21`/`≥140`/`9~50` 等展示字符串。 |
| `frontend/src/views/OperatorView.vue` | — | 承载 `CaseManageView.vue` 作为一个 tab。 |

**备注**：没有专门的"参考标准上传"入口，操作者复用与聊天文档相同的通用上传表单，仅靠手动选 access_scope 区分。没有单条编辑/纠错 ReferenceRange 的 UI，只能整表重新同步。

### 阶段2：后端 API 层

| 文件 | 行数 | 在本链路中的作用 |
|---|---|---|
| `backend/app/api/admin.py` | 575 | `POST /admin/documents/upload`（落盘+建 Document 行，access_scope 来自表单默认 "chat"）、`POST /admin/documents/{id}/chunk`、`POST /admin/documents/{id}/index`，以及文档/部门 CRUD。`_validate_access_scope` 校验枚举 `{chat, operator, both}`。 |
| `backend/app/api/operator.py` | 554 | `POST /operator/reference-ranges/sync`、`GET /operator/reference-ranges`（不按文档过滤）、`GET /operator/documents`（过滤 access_scope，现场计算 sync_ready 标记——与 admin 端逻辑有重复），以及疾病/病例 CRUD 和 `POST /operator/reports`（消费端，预测生成入口）。 |

**备注**：`sync_ready` 判定逻辑在 `/operator/documents` handler 里现场拼装（`status==indexed` 且存在当前 generation 的 chunk），与 `document_indexing.py` 的 generation 概念有重叠但未复用。

### 阶段3：后端服务层

| 文件 | 行数 | 在本链路中的作用 |
|---|---|---|
| `backend/app/ingestion/parser.py` | 285 | `parse_file()` 按扩展名分发到 `parse_pdf`/`parse_docx`/`parse_image`。`parse_docx` 把段落文本和**每个表格的每一行序列化为 `"\| 单元格 \| 单元格 \|"` 文本行**，拼进同一文本流——这是表格内容能进入 Chunk.content、进而进入参考范围解析器兜底路径的机制。另含 WPS 损坏 docx 关系修复、PDF OCR 兜底。 |
| `backend/app/ingestion/chunker.py` | 482 | `chunk_pages()` 按策略（case-aware/header-aware/paragraph-aware）切块。通用 RAG 切块逻辑，非标准文档专用——表格行只是作为普通文本行随大流被切块。 |
| `backend/app/services/document_indexing.py` | 61 | Generation 记账：`next_generation`/`staged_generation`/`activate_generation`/`delete_generation_chunks`/`delete_obsolete_chunks`，供 admin.py 的分块/索引端点实现"先分块staged、索引成功后再激活"的流程。 |
| `backend/app/services/embedder.py` | 110 | `embed_texts()`：懒加载 sentence-transformers 模型（ModelScope下载、HF兜底），输出归一化 1024 维向量。 |
| `backend/app/rag/adapters.py` | 233 | `SurgeryEmbeddings`（LangChain Embeddings 适配器，包装 embed_texts）。 |
| `backend/app/rag/vectorstore.py` | 155 | `get_vectorstore()`（PGVector 单例）、`add_chunks()`（嵌入+写入，ID 规则 `document-{id}-generation-{gen}-chunk-{id}`）、`delete_chunk_vectors()`。 |
| `backend/app/services/reference_standard.py` | 487 | 核心：`parse_reference_segment()`（确定性单行解析，支持 `<`/`≤`/`>`/`≥`/区间/en-dash/性别分段）、`_parse_tables_from_docx()`（**重新从磁盘打开原始 docx**，硬编码识别脂肪肝/AD 两种表格布局）、`_sync_from_llm()`（DeepSeek 兜底）、`sync_reference_ranges()`（编排：校验scope→表格解析+逐行确定性解析+LLM兜底→合并去重→整表删除重建）。 |

### 阶段4：数据层

| 文件 | 在本链路中的作用 |
|---|---|
| `backend/app/db/models.py`（233行） | `Document`（`access_scope` 字符串，默认"chat"，DB 层无枚举约束，只在 Python 代码校验；`active_generation`、`status`）；`Chunk`（`document_id`/`content`/`chunk_metadata`/`generation`/`is_current`）；`ReferenceRange`（`indicator_name`/`name_cn`/`unit`/`lower`/`upper`/`lower_inclusive`/`upper_inclusive`/`sex`/`category`/`document_id`，FK `ON DELETE CASCADE`——文档删除则范围级联消失）。 |
| `database/schema.sql`（181行） | 权威 schema 镜像：`documents.access_scope VARCHAR(20)`（第44行）、`reference_ranges` 表定义（第84行起）+ 索引。 |
| `backend/alembic/versions/0005_document_access_scope.py` | 新增 `documents.access_scope` 迁移。 |
| `backend/alembic/versions/0006_ai_operator_predictive.py` | 新增 `diseases`/`case_records`/`reference_ranges`（含 FK CASCADE）/`ai_reports` 预测字段迁移。 |
| `backend/alembic/versions/0007_reference_range_sex.py` | 新增 `reference_ranges.sex` 列迁移（本次 Task A 修复引入）。 |

### 阶段5：消费端（预测时读取，本次未改动此部分逻辑本身，仅记录读取路径）

| 文件 | 在本链路中的作用 |
|---|---|
| `backend/app/services/prediction_generator.py`（408行） | `generate_prediction()` 按小写 indicator_name 模糊查询 ReferenceRange，`_range_map()` 按 patient_sex 解析出该用哪条（性别专属/通用），缺失任一指标范围直接报错，结果喂给 prediction_engine，并在报告来源中引用已解析范围。 |
| `backend/app/services/prediction_engine.py`（189行） | `analyze_indicators()` 等纯函数，只读 `range_by_name` 字典做异常判定/综合概率计算，不直接访问 DB。 |

### 阶段6：Schema

| 文件 | 在本链路中的作用 |
|---|---|
| `backend/app/schemas/document.py`（59行） | `DocumentUploadResponse`/`DocumentOut`（含 `access_scope`）、`DocumentUpdateIn`、`ChunkOut`。 |
| `backend/app/schemas/prediction.py`（86行） | `ReferenceRangeOut`（含 sex/category）、`ReferenceRangeSyncIn`、`PredictRequest`（含 patient_sex）。 |

### 阶段7：一次性脚本

| 文件 | 行数 | 在本链路中的作用 |
|---|---|---|
| `scripts/upload_standards.py` | 121 | 独立脚本，用硬编码的 admin/123456 登录，对硬编码的本机桌面路径两份标准文档跑完整链路（上传→分块→索引→同步参考范围）。这是因为 UI 没有"一键上传并跑完整链路"的能力而产生的手工替代方案，路径/账号均不可移植。 |

---

## 三、设计层面的别扭之处（供未来重构参考，非本次结论）

1. **access_scope 是自由文本校验，不是一等概念**：上传表单里 operator/chat/both 是个普通下拉，没有"这是一份参考标准文档"的语义区分；上传时不校验，只在同步时才报 422，容易在上传后很久才发现选错了 scope。
2. **表格解析硬编码两种疾病专属布局**：`_parse_tables_from_docx` 靠表头关键词字符串（"正常范围"/"脂肪肝"、"normal"/"ad_pattern"）识别表格类型，新增第三种标准格式需要改代码，不是配置/UI层面的事。
3. **同步是整表删除重建，无版本、无预览、不可回滚**：操作者点一次"解析为参考范围"按钮，该文档的所有旧范围立即被删除并替换，没有 diff 展示、没有历史版本、UI 层面不可撤销。
4. **表格解析绕开了已有的 Chunk/向量表示，重新读原始文件**：`_parse_tables_from_docx` 独立于②③④步骤，直接从磁盘按 `file_path` 重新打开 docx——耦合在文件必须仍存在于磁盘且 python-docx 能打开它这个前提上，是与主流程并行的第二条解析路径。
5. **没有"一键上传并跑完整链路"的 UI 动作**：上传→分块→索引→同步是 4 次独立点击，只能靠 `scripts/upload_standards.py` 这种硬编码脚本一次性跑完，不具备可复用性。
6. **没有单条 ReferenceRange 编辑/纠错入口**：只能整份重新同步，无法针对某一条解析错误的范围单独修正。
7. **`/operator/documents` 现场计算 sync_ready，与 document_indexing.py 的 generation 概念有重复但未复用**。

---

## 四、当前状态

- Task A（去重 + 表格解析 + 性别分列 + 大小写贯穿修复）：代码已实现，全部测试通过（158 passed），已针对真实两份标准文档重新同步验证（脂肪肝 34 条、AD 52 条参考范围，性别分列、多词指标名、en-dash 范围均已正确解析）。
- 本文档记录的重构范围：**尚未开始，等 Task B 及整体链路跑通后再决定是否启动**。
- 下一步（如用户确认）：继续 Task B（纵向进展预测），设计文档已存在（`docs/superpowers/specs/2026-08-20-longitudinal-progression-prediction-design.md`、`docs/superpowers/plans/2026-08-20-longitudinal-progression-prediction.md`），尚未提交 Codex 评审。
