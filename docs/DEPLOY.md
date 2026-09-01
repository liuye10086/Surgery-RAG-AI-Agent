# Surgery RAG Agent — 部署与运维手册

> 版本：M5 完成态 | 部署方式：裸机直部署（非 Docker） | 最后更新：2026-07-24

本文档面向内网部署人员，假设读者具备终端操作能力和 PostgreSQL 基础知识。所有命令以 Linux（Ubuntu/Debian）为基准，Windows 环境需自行调整路径分隔符和包管理器命令。

---

## 1. 环境要求

### 1.1 硬件

| 资源 | 最低要求 | 建议配置 |
|------|----------|----------|
| 内存 | 4 GB | 8 GB+ |
| 磁盘 | 10 GB 可用 | 20 GB+（含模型和上传文件） |
| CPU | 4 核 | 8 核+ |
| GPU | 无硬性要求（PaddleOCR 默认 CPU） | NVIDIA GPU + CUDA 可加速 OCR |

### 1.2 软件

| 软件 | 版本要求 | 说明 |
|------|----------|------|
| Python | 3.11+ | 后端运行环境 |
| Node.js | 18 LTS+ | 前端构建环境 |
| PostgreSQL | 15+ | 数据库，**必须安装 pgvector 扩展** |
| pgvector | 0.5+ | PostgreSQL 向量扩展 |
| pip | 23.0+ | Python 包管理器 |
| npm | 9.0+ | 前端包管理器 |
| Git | 2.30+ | 代码获取（可选） |
| Nginx | 1.24+ | 生产环境前端托管与反向代理 |

### 1.3 外部服务

| 服务 | 用途 | 获取方式 |
|------|------|----------|
| DeepSeek API | LLM 对话与推理 | [platform.deepseek.com](https://platform.deepseek.com) 注册并获取 API Key |

### 1.4 网络要求

- 后端需出站访问 `api.deepseek.com`（HTTPS 443）
- 首次启动需出站访问 `huggingface.co`（下载 BGE-M3 模型，约 2.2 GB）；若无法直连，需配置 Hugging Face 镜像（见 3.4 节 `HF_ENDPOINT`）
- PaddleOCR 首次运行会自动下载模型文件（约 50 MB），需出站访问 GitHub 或配置镜像
- 内网部署时前端与后端需互通（后端监听端口 8000，前端开发端口 5173）

---

## 2. 数据库初始化

### 2.1 安装 PostgreSQL 15+

**Ubuntu/Debian：**

```bash
sudo apt update
sudo apt install -y postgresql-15 postgresql-15-pgvector
```

**CentOS/RHEL/Rocky：**

```bash
sudo dnf install -y https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm
sudo dnf install -y postgresql15-server postgresql15-contrib
sudo /usr/pgsql-15/bin/postgresql-15-setup initdb
sudo systemctl enable --now postgresql-15
# pgvector 需从源码安装或通过发行版仓库
```

**手动安装 pgvector（如果发行版未提供 pgvector 包）：**

```bash
git clone --branch v0.7.4 https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install
```

### 2.2 启动 PostgreSQL 并创建数据库和用户

```bash
sudo systemctl enable --now postgresql
sudo -u postgres psql
```

在 psql 中执行：

```sql
-- 创建用户（替换 your_password 为强密码）
CREATE USER surgery_user WITH PASSWORD 'your_password';

-- 创建数据库
CREATE DATABASE surgery_rag OWNER surgery_user;

-- 授予权限
GRANT ALL PRIVILEGES ON DATABASE surgery_rag TO surgery_user;
\c surgery_rag
GRANT ALL ON SCHEMA public TO surgery_user;
\q
```

### 2.3 使用 Alembic 创建业务结构

```bash
cd backend
source venv/bin/activate
alembic upgrade head
```

Alembic 会创建 `vector`、`uuid-ossp`、`pg_trgm` 扩展及当前版本的全部业务表（基础用户/文档/会话表、AI 操作者病例/访视/报告表、标准版本化相关表）：

| 表名 | 用途 |
|------|------|
| `users` | 用户账户（含角色字段） |
| `documents` | 上传文档元信息（状态跟踪、版本号） |
| `chunks` | 文档分块内容与元数据 |
| `sessions` | 对话会话 |
| `messages` | 会话消息（含 LangChain 标准格式 lc_message、引用来源 sources） |
| `audit_logs` | 审计日志（请求体、检索片段 ID、安全标记） |

AI 操作者和标准版本化相关表包括：`diseases`、`case_records`、`reference_ranges`、
`operator_cases`、`operator_case_visits`、`ai_reports`、`reference_standards`、
`standard_documents`、`reference_standard_versions`、`standard_indicators`、
`standard_segments`、`standard_parse_candidates`、`standard_rules`、
`standard_rule_conditions`、`standard_change_logs`。

> **注意：** 启动后端时，`ensure_vectorstore_tables()` 会自动创建 `langchain_pg_collection` 和 `langchain_pg_embedding` 两张 LangChain PGVector 管理表，并在 embedding 表的 `document` 列上创建 pg_trgm GIN 索引。无需手动干预。

`database/schema.sql` 是当前业务结构的参考快照，不是正式迁移入口。所有正式版本变更均位于 `backend/alembic/versions/`，部署和升级统一使用 Alembic。

### 2.4 验证表结构

```bash
PGPASSWORD='your_password' psql -h localhost -U surgery_user -d surgery_rag -c "\dt"
```

预期输出至少包含上述基础表，以及 AI 操作者和标准版本化相关表。

---

## 3. 后端部署

### 数据库迁移

新数据库直接执行：

```bash
cd backend
alembic upgrade head
```

既有数据库首次接入 Alembic 前，必须先核对真实表结构、数据约束与已有版本，并检查以下三列没有空值：

```sql
SELECT COUNT(*) FROM chunks WHERE document_id IS NULL;
SELECT COUNT(*) FROM sessions WHERE user_id IS NULL;
SELECT COUNT(*) FROM messages WHERE session_id IS NULL;
```

三项结果都为 `0` 后，只能在确认真实结构与某一 Alembic revision 完全一致时执行：

```bash
cd backend
alembic stamp <与真实结构匹配的 revision>
alembic upgrade head
alembic current
```

不得默认所有旧数据库都可直接 stamp `0001`。如果结构不一致、版本无法确认或存在空值，停止接入并先人工核查；迁移不会自动删除或修复业务数据。日常升级统一执行 `alembic upgrade head`。需要回退时，先备份数据库并查看当前版本，再按迁移版本逐级执行 `alembic downgrade <revision>`；不要在生产库直接使用 `downgrade base`。

文档重新处理采用版本化切换：新分块、向量和图片全部构建成功后才替换当前代次；构建失败时原代次继续提供服务。新图片目录格式为：

```text
uploads/images/{document_id}/{generation}/{filename}
```

历史第一代图片 URL 继续兼容。

### 3.1 获取项目代码

```bash
# 方式一：克隆仓库（如使用 Git）
git clone <repository_url> surgery-rag
cd surgery-rag

# 方式二：解压项目包
unzip surgery-rag.zip -d surgery-rag
cd surgery-rag
```

### 3.2 创建 Python 虚拟环境

```bash
cd backend
python3.11 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
```

### 3.3 安装依赖

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**完整依赖列表（requirements.txt）：**

- **Web 框架：** fastapi、uvicorn[standard]、pydantic、pydantic-settings、email-validator、python-multipart
- **数据库：** sqlalchemy、alembic、psycopg2-binary、pgvector
- **认证：** python-jose[cryptography]、bcrypt==4.0.1、passlib[bcrypt]
- **AI / RAG：** openai、langchain>=0.2.0、langchain-core>=0.2.0、langchain-openai>=0.1.0、langchain-postgres>=0.0.10、langchain-text-splitters>=0.2.0、langsmith>=0.1.0
- **Embedding：** sentence-transformers、modelscope
- **文档解析：** pymupdf、python-docx
- **OCR：** paddleocr
- **配置：** python-dotenv

**PaddleOCR 注意：**
- 首次 `import paddleocr` 会尝试下载模型（~50 MB），若网络不通，可提前设置环境变量：`export PADDLEOCR_HOME=/path/to/model_cache`
- Windows 环境下 PaddleOCR 可能遇到 VC++ 运行时依赖问题，请安装 [Microsoft Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe)

**sentence-transformers 注意：**
- 首次加载 `BAAI/bge-m3` 会自动从 Hugging Face 下载模型（约 2.2 GB），下载路径为 `~/.cache/huggingface/hub/`
- 若网络受限，可在 `.env` 中设置 `HF_ENDPOINT=https://hf-mirror.com` 使用镜像加速

### 3.4 配置 .env 文件

```bash
cp .env.example .env
chmod 600 .env   # 设置安全权限（仅所有者可读写）
```

编辑 `backend/.env`，填入真实值。下面逐项说明：

```ini
# ── 数据库 ────────────────────────────────────────────
# 格式：postgresql://用户名:密码@主机:端口/数据库名
DATABASE_URL=postgresql://surgery_user:your_password@localhost:5432/surgery_rag

# ── JWT ──────────────────────────────────────────────
# JWT_SECRET：用于签名访问令牌的密钥，必须修改为强随机字符串（生成方法见 5.3 节）
JWT_SECRET=your_jwt_secret_here
JWT_ALGORITHM=HS256
# ACCESS_TOKEN_EXPIRE_MINUTES：令牌有效期，默认 10080（7 天）
ACCESS_TOKEN_EXPIRE_MINUTES=10080

# ── LLM ──────────────────────────────────────────────
# DEEPSEEK_API_KEY：DeepSeek 平台 API Key（必填，获取方法见 5.4 节）
DEEPSEEK_API_KEY=sk-your-deepseek-api-key-here
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
# 请求超时（秒），可根据网络状况调整
DEEPSEEK_REQUEST_TIMEOUT=60

# ── 文件上传 ─────────────────────────────────────────
# 上传文件存储目录（相对于 backend/ 目录，或使用绝对路径）
UPLOAD_DIR=../uploads
MAX_UPLOAD_SIZE_MB=50
# 允许的文件扩展名：.pdf .docx .doc .jpg .jpeg .png
# 注意：ALLOWED_EXTENSIONS 在 config.py 中硬编码，不在 .env 中配置

# ── 分块 ─────────────────────────────────────────────
CHUNK_SIZE=400                # 每个 text chunk 的字符数
CHUNK_OVERLAP=50              # chunk 之间的重叠字符数
CASE_CHUNK_MAX_SIZE=1500      # 完整病历上限（尽量不拆分超限病历）

# ── Embedding ────────────────────────────────────────
EMBEDDING_MODEL=BAAI/bge-m3           # 模型来自 Hugging Face / ModelScope
EMBEDDING_DIMENSION=1024              # bge-m3 输出维度，必须与模型匹配
EMBEDDING_BATCH_SIZE=32               # 批量向量化大小
# Hugging Face 镜像地址，国内服务器推荐设为 https://hf-mirror.com
HF_ENDPOINT=

# ── OCR ──────────────────────────────────────────────
PDF_OCR_MIN_TEXT_LENGTH=50     # PDF 最少文本字符数，低于此值触发 OCR
PDF_OCR_DPI=150                # OCR 时 PDF 转图片的 DPI
PADDLEOCR_LANG=ch              # 识别语言，'ch' 为中英文混合
PADDLEOCR_USE_GPU=False        # 是否使用 GPU 加速

# ── 检索 ─────────────────────────────────────────────
RETRIEVER_TOP_K_VECTOR=10           # 向量检索返回的候选数
RETRIEVER_TOP_K_FULLTEXT=10         # 全文检索返回的候选数
RETRIEVER_FUSION_K=30               # RRF 融合常数（越小向量检索权重越高）
RETRIEVER_FINAL_TOP_K=7             # 最终送入 LLM 的片段数
RETRIEVER_SIMILARITY_THRESHOLD=0.62 # 由 10 条 RAG 基线初步校准
RETRIEVER_DUAL_MATCH_MARGIN=0.08
RETRIEVER_FULLTEXT_THRESHOLD=0.12
CHAT_MEMORY_ROUNDS=6                # 携带最近 N 轮对话历史

# ── 内容安全（M5）─────────────────────────────────────
INPUT_MAX_LENGTH=2000               # 单条用户消息最大字符数
ENABLE_CONTENT_FILTER=True          # 启用越狱 / 诱导检测
ENABLE_DANGER_SYMPTOM_CHECK=True    # 启用危险症状关键词检测
ENABLE_OUTPUT_FILTER=True           # 启用输出内容安全检测

# ── 查询改写 ─────────────────────────────────────────
ENABLE_LLM_QUERY_REWRITE=True       # 开启多轮对话查询改写
REWRITE_MAX_HISTORY=6               # 改写时参考的历史轮数
REWRITE_MODEL=deepseek-chat         # 改写模型（可改为更轻量的模型降低成本）

# ── PGVector ─────────────────────────────────────────
VECTOR_COLLECTION_NAME=surgery_docs       # 向量集合名称
# VECTOR_STORE_CONNECTION_STRING 留空则自动复用 DATABASE_URL
VECTOR_STORE_CONNECTION_STRING=

# ── LangSmith 链路追踪（默认关闭）─────────────────────
LANGCHAIN_TRACING_V2=False
LANGCHAIN_API_KEY=
LANGCHAIN_PROJECT=surgery-rag
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com

# ── Agent 模式（预留，默认关闭）───────────────────────
ENABLE_AGENT_MODE=False
AGENT_MAX_ITERATIONS=5
```

### 3.5 启动后端

```bash
# 确保在 backend/ 目录下且虚拟环境已激活
cd backend
source venv/bin/activate

# 开发模式（热重载）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 生产模式（多 worker，建议由 systemd 管理，见下文）
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

启动时会自动执行：
1. `ensure_upload_dir()` — 创建 `uploads/` 目录
2. `warmup_embedder()` — 后台加载 BGE-M3 模型到内存（避免首次请求冷启动等待）
3. `ensure_vectorstore_tables()` — 创建 PGVector 管理表和 GIN 索引

### 3.6 健康检查

```bash
curl http://localhost:8000/health
# 预期返回：{"status":"ok"}
```

### 3.7 Systemd 服务（推荐）

创建 `/etc/systemd/system/surgery-rag.service`：

```ini
[Unit]
Description=Surgery RAG Agent Backend
After=network.target postgresql.service

[Service]
Type=simple
User=surgery
WorkingDirectory=/opt/surgery-rag/backend
Environment=PATH=/opt/surgery-rag/backend/venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/opt/surgery-rag/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now surgery-rag
sudo systemctl status surgery-rag
```

---

## 4. 前端部署

### 4.1 安装依赖

```bash
cd frontend
npm ci
```

核心依赖：Vue 3.4+、TypeScript 5.3+、Vite 5、Element Plus 2.5、Pinia、Vue Router、Axios、marked、dompurify。

### 4.2 配置 API 地址

开发模式下 Vite 配置 `frontend/vite.config.ts` 中已配置代理：

```ts
server: {
  port: 5173,
  proxy: {
    '/api': {
      target: 'http://localhost:8000',
      changeOrigin: true,
    },
  },
},
```

若后端部署在其他主机，修改 `target` 为目标地址。生产构建模式下，需确保 Nginx 反向代理将 `/api` 请求转发至后端（见 4.5 节）。

### 4.3 开发模式

```bash
npm run dev
# 访问 http://localhost:5173
```

### 4.4 生产构建

```bash
npm run build
```

构建产物输出至 `frontend/dist/`，包含 `index.html` 及 `assets/` 静态资源目录。

### 4.5 Nginx 托管与反向代理

将构建产物放置到 Nginx 静态目录：

```bash
sudo cp -r frontend/dist/* /var/www/surgery-rag/
```

Nginx 配置示例 `/etc/nginx/sites-available/surgery-rag`：

```nginx
server {
    listen 80;
    server_name your-domain.com;   # 替换为实际域名或 IP

    # 前端静态文件
    root /var/www/surgery-rag;
    index index.html;

    # Vue Router history 模式回退
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 反向代理后端 API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE 流式响应需要关闭缓冲
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }
}
```

启用站点：

```bash
sudo ln -s /etc/nginx/sites-available/surgery-rag /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

> **SSE 重要提示：** RAG 对话的流式输出依赖 Server-Sent Events。Nginx 必须设置 `proxy_buffering off`，否则客户端将收不到逐步生成的 token，只在响应完成后一次性返回。

---

## 5. 密钥管理

### 5.1 .env 文件安全

`.env` 文件包含数据库密码、JWT 密钥和 API Key 等敏感信息，必须严格保护：

```bash
chmod 600 backend/.env       # 仅所有者可读写
chown <deploy_user> backend/.env
```

- **永远不要**将 `.env` 提交到版本控制系统（已通过 `.gitignore` 排除，`backend/.env.example` 作为模板可提交）
- 定期审计文件权限
- 生产环境考虑使用系统级环境变量或密钥管理服务替代 `.env` 文件

### 5.2 密钥轮换流程

**数据库密码轮换：**

1. 在 PostgreSQL 中修改用户密码：
   ```sql
   ALTER USER surgery_user WITH PASSWORD 'new_password';
   ```
2. 更新 `.env` 中 `DATABASE_URL` 的密码部分
3. 重启后端服务

**JWT_SECRET 轮换：**

1. 生成新的 JWT secret（见 5.3 节）
2. 更新 `.env` 中 `JWT_SECRET`
3. 重启后端服务
4. 注意：旧签名的令牌将立即失效，所有用户需要重新登录

**DeepSeek API Key 轮换：**

1. 在 [DeepSeek 平台](https://platform.deepseek.com) 生成新 Key
2. 更新 `.env` 中 `DEEPSEEK_API_KEY`
3. 重启后端服务
4. 在 DeepSeek 平台吊销旧 Key

### 5.3 JWT_SECRET 生成方法

**方法一（推荐）：**

```bash
openssl rand -base64 64
```

**方法二：**

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

**方法三：**

```bash
uuidgen | sha256sum | base64 | head -c 64; echo
```

生成的密钥应至少 64 字节，包含大小写字母、数字和特殊字符的混合。

### 5.4 DeepSeek API Key 获取与配置

1. 访问 [platform.deepseek.com](https://platform.deepseek.com)
2. 注册/登录账号
3. 进入「API Keys」页面，点击「创建 API Key」
4. 复制生成的 Key（格式：`sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`）
5. 将 Key 填入 `backend/.env` 的 `DEEPSEEK_API_KEY` 字段
6. 确保账户余额充足，否则 API 调用将返回 `402 Payment Required`
7. 重启后端服务使配置生效

---

## 6. 验证清单

部署完成后，按以下步骤逐项验证：

| 序号 | 验证项 | 操作 | 预期结果 |
|------|--------|------|----------|
| 1 | 后端健康检查 | `curl http://localhost:8000/health` | 返回 `{"status":"ok"}` |
| 2 | 前端可访问 | 浏览器打开 `http://<IP>` | 显示登录/注册页面 |
| 3 | 用户注册 | 在注册页面填写用户名、邮箱、密码并提交 | 提示注册成功，自动跳转登录 |
| 4 | 用户登录 | 使用注册的账号登录 | 进入主界面（对话页） |
| 5 | 文档上传 | 上传一份 PDF 或 DOCX 文档 | 文档状态变为 `completed`，分块入库 |
| 6 | RAG 问答 | 在对话中输入与文档相关的问题 | 返回带引用的回答，引用卡片显示来源文档和片段 |
| 7 | 流式输出 | 提交问题后观察响应 | 回答逐字流式呈现（SSE），非一次性返回 |
| 8 | 多轮对话 | 在同一会话中连续提问（涉及上下文） | 回答能引用上一轮内容，历史记录正确显示 |
| 9 | 管理面板 | 使用 admin 角色账号登录，访问管理功能 | 可查看文档列表、用户列表、审计日志 |
| 10 | 内容安全 | 输入含危险症状描述或诱导性提示词 | 触发安全拦截提示 |
| 11 | 查询改写 | 使用代词或省略表达提问（如"上一段说的是什么"） | 回答正确关联上文内容 |

### 验证通过标准

- 后端所有 API 返回正常（HTTP 2xx）
- 前端页面加载完整，页面间导航无 404
- 文档上传到向量化全流程不超过 2 分钟（普通 10 页 PDF）
- RAG 回答引用准确，格式规范
- 流式输出首 token 延迟 < 5 秒
- 管理面板功能可用且权限隔离正确

---

## 7. 故障排查

### 7.1 pgvector 扩展加载失败

**错误信息：**
```
ERROR:  could not open extension control file "/usr/share/postgresql/15/extension/vector.control"
ERROR:  extension "vector" is not available
```

**原因：** pgvector 扩展未安装或版本不匹配。

**解决步骤：**

1. 确认 PostgreSQL 版本：`psql --version`
2. 安装对应版本的 pgvector 包：
   ```bash
   # Ubuntu/Debian
   sudo apt install postgresql-15-pgvector
   
   # 或从源码编译
   git clone --branch v0.7.4 https://github.com/pgvector/pgvector.git
   cd pgvector
   make
   sudo make install
   ```
3. 重启 PostgreSQL：`sudo systemctl restart postgresql`
4. 重新执行 `CREATE EXTENSION vector;`

### 7.2 BGE-M3 模型下载失败

**错误信息：**
```
OSError: Can't load model 'BAAI/bge-m3'. 
ConnectionError: (MaxRetryError("HTTPSConnectionPool(host='huggingface.co', port=443)"), ...)
```

**原因：** 无法访问 Hugging Face 服务器（网络限制或墙）。

**解决步骤：**

1. 在 `.env` 中设置镜像：
   ```ini
   HF_ENDPOINT=https://hf-mirror.com
   ```
2. 如果镜像不可用，手动下载模型：
   ```bash
   pip install huggingface_hub
   # 通过代理或可访问环境下载
   huggingface-cli download BAAI/bge-m3 --local-dir ~/.cache/huggingface/hub/models--BAAI--bge-m3/
   ```
3. 模型文件约 2.2 GB，确保磁盘空间充足（`df -h`）
4. 也可通过 ModelScope 下载（项目依赖中已包含 modelscope）：
   ```python
   from modelscope import snapshot_download
   snapshot_download('BAAI/bge-m3', cache_dir='~/.cache/huggingface/hub')
   ```

### 7.3 PaddleOCR 初始化失败

**错误信息：**
```
ImportError: DLL load failed while importing _paddleocr: The specified module could not be found.
```

或者：

```
RuntimeError: Can't download model from paddleocr...
```

**原因：** Windows 缺少 VC++ 运行时，或模型下载失败。

**解决步骤：**

1. **Windows：** 安装 [VC++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe)
2. **模型下载失败：** 手动下载并放置到 `~/.paddleocr/`：
   ```bash
   # 设置模型缓存目录
   export PADDLEOCR_HOME=/path/to/model_cache
   # 或通过代理
   pip install paddlepaddle  # 确保 PaddlePaddle 基础包正确安装
   ```
3. **Linux：** 确保安装了必要的系统库：
   ```bash
   sudo apt install -y libgomp1 libgl1-mesa-glx libglib2.0-0 libsm6 libxrender1 libxext6
   ```
4. 如果 OCR 不是必需功能，可在代码中跳过 OCR 初始化（不影响对话和向量检索功能）

### 7.4 DeepSeek API 连接失败

**错误信息：**
```
openai.APIConnectionError: Connection error.
openai.AuthenticationError: Error code: 401 - Invalid API key
openai.RateLimitError: Error code: 429 - Rate limit reached
```

**原因与解决方案：**

| 错误码 | 原因 | 解决方案 |
|--------|------|----------|
| `401 Unauthorized` | API Key 无效或过期 | 检查 `DEEPSEEK_API_KEY` 是否正确；在 DeepSeek 平台确认 Key 状态 |
| `402 Payment Required` | 账户余额不足 | 访问 platform.deepseek.com 充值 |
| `429 Rate Limit` | 请求频率过高 | 降低并发请求；联系 DeepSeek 提升限额 |
| `Connection Error` | 网络不通 | `curl -v https://api.deepseek.com/v1/models` 测试连通性；检查防火墙/代理设置 |
| `Timeout` | 请求超时 | 增大 `DEEPSEEK_REQUEST_TIMEOUT`（`backend/app/core/config.py`，默认 60s） |

### 7.5 前端 SSE 连接中断

**现象：** RAG 对话中，回答不再逐字流式输出，而是等待很久后一次性出现，或显示"网络错误"。

**原因：** 反向代理未正确配置流式传输支持。

**解决步骤：**

1. **Nginx：** 确保 `proxy_buffering off;` 已设置（见 4.5 节 Nginx 配置）
2. **Nginx timeout：** 增加 `proxy_read_timeout` 到 300s 或更长
3. **CDN/网关：** 如果前端前还有 CDN 或企业网关，需确认它们支持 SSE（`Content-Type: text/event-stream`）
4. **浏览器 DevTools：** 检查 Network 标签页中 SSE 连接的状态码和响应头，确认无 502/504
5. **CORS：** 确认后端 CORS 配置允许前端的域名（当前 `allow_origins=["*"]`，生产环境应收窄）

### 7.6 PostgreSQL 连接池耗尽

**错误信息：**
```
sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) 
FATAL: remaining connection slots are reserved for non-replication superuser connections
```

**原因：** PostgreSQL 连接数达到 `max_connections` 上限（默认 100）。

**解决步骤：**

1. 查看当前连接数：
   ```sql
   SELECT count(*) FROM pg_stat_activity;
   ```
2. 查看最大连接数：
   ```sql
   SHOW max_connections;
   ```
3. 找到空闲但未释放的连接：
   ```sql
   SELECT pid, state, query, age(now(), query_start) AS duration
   FROM pg_stat_activity
   WHERE state = 'idle' OR state = 'idle in transaction';
   ```
4. 如果需要，终止空闲连接：
   ```sql
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE state = 'idle' AND pid <> pg_backend_pid();
   ```
5. 调整 PostgreSQL 连接池 `postgresql.conf`：
   ```ini
   max_connections = 200
   ```
6. 重启 PostgreSQL：`sudo systemctl restart postgresql`
7. 或在应用层使用连接池（uvicorn 的 `--limit-max-requests` 参数定期回收 worker）

---

## 8. 备份与恢复

### 8.1 数据库备份

**完整备份：**

```bash
PGPASSWORD='your_password' pg_dump -h localhost -U surgery_user -d surgery_rag \
  -Fc -f surgery_rag_$(date +%Y%m%d_%H%M%S).dump
```

- `-Fc`：自定义压缩格式，体积小，支持并行恢复
- 建议每天定时执行（crontab）：

```bash
# crontab -e，每天凌晨 2:00 备份
0 2 * * * PGPASSWORD='your_password' pg_dump -h localhost -U surgery_user -d surgery_rag -Fc -f /backup/surgery_rag_$(date +\%Y\%m\%d).dump
```

**仅备份结构（不含数据）：**

```bash
pg_dump -h localhost -U surgery_user -d surgery_rag --schema-only -f schema_backup.sql
```

### 8.2 uploads/ 目录备份

上传文件存储在项目根目录下的 `uploads/` 目录（由 `UPLOAD_DIR` 配置项指定，默认值为 `<项目根>/uploads/`）。

```bash
# 压缩备份
tar -czf uploads_backup_$(date +%Y%m%d).tar.gz uploads/

# rsync 同步到远程
rsync -avz uploads/ backup-server:/backup/surgery-rag/uploads/
```

### 8.3 数据库恢复

```bash
# 先清空或确保目标数据库存在
PGPASSWORD='your_password' psql -h localhost -U surgery_user -d surgery_rag -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

# 从备份恢复
PGPASSWORD='your_password' pg_restore -h localhost -U surgery_user -d surgery_rag \
  -c --if-exists surgery_rag_YYYYMMDD_HHMMSS.dump
```

- `-c`：恢复前清空（drop）目标对象
- `--if-exists`：避免因对象不存在而出错

### 8.4 恢复后验证

恢复完成后，按以下步骤验证数据完整性：

1. **检查表行数：**
   ```sql
   SELECT schemaname, relname, n_live_tup
   FROM pg_stat_user_tables
   ORDER BY relname;
   ```

2. **验证向量表完整性：**
   ```sql
   SELECT c.name AS collection, count(e.id) AS embeddings
   FROM langchain_pg_collection c
   LEFT JOIN langchain_pg_embedding e ON e.collection_id = c.uuid
   GROUP BY c.name;
   ```

3. **启动后端并执行健康检查：**
   ```bash
   curl http://localhost:8000/health
   ```

4. **执行端到端验证（参考第 6 章验证清单）：**
   - 登录已有账号
   - 检查文档列表是否完整
   - 执行一次 RAG 提问，验证向量检索正常返回引用

5. **恢复 uploads/ 文件：**
   ```bash
   tar -xzf uploads_backup_YYYYMMDD.tar.gz
   ```

6. **重启后端服务：**
   ```bash
   sudo systemctl restart surgery-rag
   ```

---

## 附录：常用命令速查

```bash
# 查看后端日志
sudo journalctl -u surgery-rag -f

# 重启后端
sudo systemctl restart surgery-rag

# 查看 PostgreSQL 状态
sudo systemctl status postgresql

# 测试 DeepSeek API 连通性
curl -H "Authorization: Bearer $DEEPSEEK_API_KEY" https://api.deepseek.com/v1/models

# 查看磁盘使用
df -h

# 查看内存使用
free -h
```
