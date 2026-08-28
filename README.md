# Surgery RAG Agent

面向外科领域的垂直 RAG AI Agent。简单来说，它是一个「会查资料的 AI 医生助手」——当用户（医生或患者）提出医学问题时，系统先从知识库中检索最相关的真实病例，再将病例片段作为参考资料喂给大语言模型，让模型基于真实、可追溯的临床数据生成回答，并在回答中标注每条信息出自哪份病例的哪个章节。

以胆囊结石场景为例：当患者问「我最近吃完饭腹部就痛，可能是什么原因？」，系统自动从 100 例病例中检索症状相似的病例，生成带引用的回答，如"根据知识库中的病例记录……病例5（女，42岁）主诉'进食油腻后右上腹隐痛'，超声提示胆囊多发结石[1]；病例8（男，38岁）主诉'饭后上腹胀痛……'[2]"，用户可点击引用编号追溯查看完整病例信息，有效规避 AI 幻觉风险。

**技术栈：** LangChain LCEL 链编排 · `langchain-postgres` PGVector 向量存储 · BGE-M3 Embeddings（1024 维）· 混合检索（向量 + PostgreSQL 全文 + RRF 融合）· DeepSeek LLM · Vue 3 + Element Plus 前端

## 快速了解

| 文档 | 说明 |
| --- | --- |
| [项目规划.md](docs/项目规划.md) | 项目背景、愿景、用户、阶段规划、风险、参考产品 |
| [MVP开发计划.md](docs/MVP开发计划.md) | MVP 技术方案与里程碑（M0–M7，全部完成） |
| [DESIGN_SPEC.md](docs/DESIGN_SPEC.md) | UI 设计规范（暖杏蓝色彩体系、排版、组件变体） |
| [DEPLOY.md](docs/DEPLOY.md) | 部署与密钥运行手册 |

## 项目结构

```
surgery-rag/
├── backend/               # FastAPI 后端
│   ├── app/
│   │   ├── api/           # 路由：auth, chat, admin, user
│   │   ├── core/          # 配置、安全、JWT
│   │   ├── data/          # M5 安全规则库（JSON）
│   │   ├── db/            # SQLAlchemy 模型
│   │   ├── ingestion/     # 文档解析（PDF/Word/OCR）、分块
│   │   ├── rag/           # RAG 检索 + LangChain 适配器
│   │   ├── services/      # Embedding、LLM 调用、内容过滤、审计
│   │   └── main.py
│   ├── alembic/            # 业务表数据库迁移
│   ├── alembic.ini
│   ├── requirements.txt
│   └── .env.example
├── frontend/              # Vue 3 + TypeScript + Element Plus
│   ├── src/
│   │   ├── views/         # 页面：Chat, Admin, Login, Settings
│   │   ├── components/    # ChatMessage, ChatSidebar, AdminSidebar 等
│   │   ├── api/           # 后端接口封装（SSE 流式）
│   │   ├── stores/        # Pinia 状态管理（chat, auth, admin）
│   │   └── router/        # 路由配置
│   ├── package.json
│   └── vite.config.ts
├── data/generated/         # 双疾病 150/300 例可复现纵向数据
├── database/               # schema.sql 参考快照；正式迁移位于 backend/alembic
├── docs/
│   ├── superpowers/plans/  # 保留的实施计划
│   └── superpowers/specs/  # 尚未落地的采集规范与本次清理规格
├── research/               # 独立方法验证子项目
├── scripts/                # 数据生成、训练、registry、readiness 和诊断工具
├── standard_manifests/     # 双疾病标准 manifest
├── outputs/                # 保留的方法验证结论
└── uploads/                # 运行时上传文件，不进入 Git
```

## 工作流程概览

### 知识入库

1. **上传**：管理员上传 PDF / Word / 图片（超声、CT 等）。
2. **解析**：pymupdf 提取 PDF 文字；python-docx 解析 Word（含 WPS 兼容修复）；PaddleOCR 识别扫描件/图片中的文字。
3. **智能分块**：病历级感知——检测到「病例1」「病例2」等标题时，将每例完整病历作为一个独立检索单元；无病历结构时回退到章节标题感知分块。
4. **向量化入库**：BGE-M3 本地推理生成 1024 维向量，存入 PostgreSQL pgvector。同时建立全文检索索引。

### 用户问答

1. **查询改写**：规则层（中文指代消解）+ LLM 层（补全省略和缩写）双层改写。
2. **混合检索**：向量相似度（pgvector 余弦）+ 全文检索（pg_trgm）+ RRF 融合排序，取 top 5–7 最相关病例。
3. **安全过滤**：输入侧检测越狱/注入（阻断）和危险症状（标记但不阻断）；输出侧检测确定性诊断/药物剂量。
4. **流式生成**：DeepSeek 基于检索病例生成回答，`[1]` `[2]` 内联引用，逐字流式输出。
5. **审计记录**：完整记录检索分块、生成文本、延迟、安全标记。

### AI 操作者纵向报告

1. 保存操作者自有纵向病例和按日期排列的访视指标。
2. 根据疾病和基线阶段选择当前激活的结局、阶段与趋势模型套件。
3. 解析当前批准的参考标准，并选择带来源标记的相似病例证据。
4. 生成严格结构化预测结果，再由确定性模板渲染 Markdown 报告。
5. 持久化输入快照、模型版本、证据、报告正文，并支持历史查看和 PDF 导出。

## 本地开发

### 前置条件

- Python 3.11+
- Node.js 18+
- PostgreSQL 15+（需启用 pgvector 扩展）
- DeepSeek API Key

### 后端

```bash
cd backend
cp .env.example .env   # 编辑填入 DB 地址、DeepSeek Key、JWT 密钥
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
```

普通注册账户固定为 `user`。首次启动前由部署人员单独创建管理员：

```bash
python scripts/create_admin.py
```

RAG 检索基线位于 `evaluation/rag_baseline_10.json`。数据库和向量索引就绪后可运行：

```bash
python scripts/evaluate_rag.py
```

### 前端

```bash
cd frontend
npm ci
npm run dev
```

### 数据库

```bash
cd backend
alembic upgrade head
```

Alembic 是业务表结构的唯一正式迁移入口。`database/schema.sql` 仅作为当前结构参考快照；LangChain 的 `langchain_pg_collection`、`langchain_pg_embedding` 两张内部表仍由 `langchain-postgres` 管理。
