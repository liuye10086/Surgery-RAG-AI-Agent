# 阿里云服务器部署计划 — Surgery RAG Agent

> **场景：** 将 Surgery RAG Agent 部署到阿里云 ECS 服务器，与现有微信小程序后端共存。
> **部署方式：** 裸机直部署（非 Docker） | **最后更新：** 2026-07-29

---

## 目录

1. [现状分析与共存策略](#1-现状分析与共存策略)
2. [前提条件确认](#2-前提条件确认)
3. [端口与域名规划](#3-端口与域名规划)
4. [数据库部署](#4-数据库部署)
5. [后端部署](#5-后端部署)
6. [前端部署](#6-前端部署)
7. [Nginx 多站点配置](#7-nginx-多站点配置)
8. [Systemd 服务管理](#8-systemd-服务管理)
9. [阿里云安全组配置](#9-阿里云安全组配置)
10. [依赖服务启动顺序](#10-依赖服务启动顺序)
11. [环境变量安全](#11-环境变量安全)
12. [监控与日志](#12-监控与日志)
13. [备份策略](#13-备份策略)
14. [部署验证清单](#14-部署验证清单)
15. [故障回滚方案](#15-故障回滚方案)
16. [时间线估算](#16-时间线估算)

---

## 1. 现状分析与共存策略

### 1.1 假设的现有架构

在开始部署前，需先确认服务器上已有的微信小程序后端的实际架构。以下为典型场景，部署时需逐项核实：

| 须确认项 | 可能的现状 | 需采取的措施 |
|----------|-----------|-------------|
| Web 服务器 | Nginx（已在运行） | 新增一个 server 块，不改动现有配置 |
| 后端端口 | 3000 / 8080 / 9000 等 | Surgery RAG 使用 **8000**，避免冲突 |
| 数据库类型 | MySQL（常见） | Surgery RAG 使用 **PostgreSQL + pgvector**，需新装 |
| 数据库端口 | MySQL: 3306 | PostgreSQL: **5432**，不冲突 |
| Node.js 版本 | 可能较旧 | Surgery RAG 前端构建需 Node 18+，后端 Python 3.11+ |
| 内存占用 | 小程序后端约 200MB–1GB | Surgery RAG 需额外 **2–4 GB**（BGE-M3 模型 ~2.2 GB + OCR ~200 MB） |
| 磁盘空间 | 未知 | Surgery RAG 需 **~5 GB**（依赖 + 模型 + 数据） |

### 1.2 共存架构总览

```
┌──────────────────────────────────────────────────────┐
│                   阿里云 ECS 服务器                    │
│                                                      │
│  ┌──────────────┐  ┌──────────────┐                  │
│  │   Nginx :80  │  │   Nginx :80  │                  │
│  │  (已存在)     │  │  (新增)      │                  │
│  │  小程序前端   │  │  Surgery前端  │                  │
│  └──────┬───────┘  └──────┬───────┘                  │
│         │                  │                          │
│         ▼                  ▼                          │
│  ┌──────────────┐  ┌──────────────┐                  │
│  │ 小程序后端    │  │ FastAPI:8000 │                  │
│  │ :3000/:8080  │  │ Surgery后端   │                  │
│  └──────┬───────┘  └──────┬───────┘                  │
│         │                  │                          │
│         ▼                  ▼                          │
│  ┌──────────────┐  ┌──────────────┐                  │
│  │    MySQL      │  │ PostgreSQL   │                  │
│  │    :3306      │  │    :5432     │                  │
│  └──────────────┘  └──────────────┘                  │
│                                                      │
│  ┌─────────────────────────────────────────────┐     │
│  │          阿里云安全组（新增端口规则）          │     │
│  └─────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────┘
```

### 1.3 关键共存原则

1. **端口隔离**：Surgery RAG 所有端口避开现有服务
2. **域名/路径隔离**：通过 Nginx 的 `server_name` 或 `location` 区分两个项目
3. **数据库独立**：PostgreSQL 与现有 MySQL 完全解耦
4. **内存规划**：确认服务器总内存 ≥ 4 GB，否则需先升级 ECS 配置
5. **不碰现有配置**：所有 Nginx、systemd 配置独立新建，不动已有的

---

## 2. 前提条件确认

### 2.1 线上摸底——部署前必须在服务器上执行

**第一步：登录服务器**

```bash
ssh root@<你的阿里云ECS公网IP>
# 或使用阿里云 Workbench / VNC 登录
```

**第二步：系统信息收集**

```bash
# 操作系统版本
cat /etc/os-release

# 内存总量（MB）
free -m

# CPU 核数
nproc

# 磁盘可用空间
df -h /

# 已监听端口（找出小程序后端使用的端口）
ss -tlnp | grep LISTEN

# Nginx 是否在运行
systemctl status nginx 2>/dev/null || service nginx status 2>/dev/null

# 现有 Nginx 配置
nginx -t 2>&1
ls -la /etc/nginx/sites-enabled/ 2>/dev/null || ls -la /etc/nginx/conf.d/ 2>/dev/null
cat /etc/nginx/nginx.conf

# 是否有 MySQL
systemctl status mysqld 2>/dev/null || systemctl status mysql 2>/dev/null

# Python 版本（Surgery RAG 需 ≥ 3.11）
python3 --version

# Node.js 版本（Surgery RAG 前端构建需 ≥ 18）
node --version
```

**第三步：记录现状**

将上述命令的输出全部记录下来，填入下表，作为部署基准：

| 项目 | 当前值 | Surgery RAG 需要 | 是否需要变更 |
|------|--------|-----------------|-------------|
| 操作系统 | | Ubuntu 20.04+ / CentOS 7+ | |
| 总内存 | | ≥ 4 GB | |
| 可用磁盘 | | ≥ 10 GB | |
| Python 版本 | | ≥ 3.11 | |
| Node.js 版本 | | ≥ 18 LTS | |
| 小程序后端端口 | | 不冲突即可 | |
| MySQL 端口 | | 不冲突即可 | |
| Nginx 是否运行 | | 需要运行 | |

### 2.2 资源规划

| 组件 | 预计内存占用 | 预计磁盘占用 |
|------|------------|------------|
| PostgreSQL + pgvector | ~200 MB | ~500 MB（数据） |
| BGE-M3 Embedding 模型 | ~2.2 GB（加载到内存） | ~2.5 GB（模型文件） |
| PaddleOCR 模型 | ~200 MB（按需加载） | ~50 MB（模型文件） |
| FastAPI (4 workers) | ~600 MB | ~500 MB（虚拟环境） |
| Nginx | ~50 MB | — |
| 上传文件目录 | — | 视使用量而定 |
| **新增总计** | **~3–4 GB** | **~5–7 GB** |

> ⚠️ **关键判断：** 如果服务器总内存 < 4 GB, 部署后可能因 OOM 导致服务不稳定。建议：
> - 在阿里云控制台升级 ECS 实例规格（至少 4 GB 内存）
> - 或使用 swap 临时缓解（不推荐，会严重降低性能）：`sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`

---

## 3. 端口与域名规划

### 3.1 端口分配

| 服务 | 端口 | 协议 | 说明 |
|------|------|------|------|
| 小程序后端 | **已有端口**（需确认） | HTTP | **不动** |
| Nginx | 80 / 443 | HTTP/HTTPS | **不动**，新增 server 块 |
| Surgery RAG 后端 | **8000** | HTTP | 仅监听 `127.0.0.1`，不对外 |
| PostgreSQL | **5432** | TCP | 仅监听 `127.0.0.1`，不对外 |

### 3.2 域名方案（三选一）

**方案 A — 子域名（推荐，如果已有域名）：**

| 子域名 | 指向 |
|--------|------|
| `api.example.com`（已有） | 小程序后端 |
| `surgery.example.com` | Surgery RAG 前端 |
| `surgery-api.example.com` | Surgery RAG 后端（或统一走 surgery.example.com/api/） |

**方案 B — 同域名不同路径（无额外域名时）：**

| 路径 | 指向 |
|------|------|
| `/` | 小程管理后台（已有） |
| `/surgery/` | Surgery RAG 前端（Vue Router `base: '/surgery/'`） |
| `/surgery/api/` | Surgery RAG 后端代理 |
| `/api/`（已有） | 小程序后端 API（不动） |

**方案 C — IP + 端口（临时/测试，不推荐生产）：**

直接通过 `http://<公网IP>:8000` 访问，需在安全组开放 8000 端口。

> **本文档后续章节默认采用方案 A（子域名方式），如采用方案 B 或 C，Nginx 配置部分需相应调整。**

---

## 4. 数据库部署

### 4.1 安装 PostgreSQL 15+ 和 pgvector

> ⚠️ 此步骤不影响现有 MySQL，可以安全执行。

**Ubuntu/Debian：**

```bash
# 添加 PostgreSQL 官方仓库（阿里云 ECS 可直接用 apt，但建议用官方源获取最新版）
sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo apt-key add -
sudo apt update

# 安装 PostgreSQL 15 + pgvector
sudo apt install -y postgresql-15 postgresql-15-pgvector

# 如果 postgresql-15-pgvector 包不存在，从源码编译 pgvector
# 见 docs/DEPLOY.md 第 2.1 节「手动安装 pgvector」
```

**CentOS/RHEL/Rocky：**

```bash
sudo dnf install -y https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm
sudo dnf install -y postgresql15-server postgresql15-contrib
sudo /usr/pgsql-15/bin/postgresql-15-setup initdb
sudo systemctl enable --now postgresql-15

# pgvector 从源码编译安装
sudo dnf install -y git gcc make postgresql15-devel
git clone --branch v0.7.4 https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install
cd .. && rm -rf pgvector
```

### 4.2 创建数据库和用户

```bash
# 启动 PostgreSQL（Ubuntu）
sudo systemctl enable --now postgresql

# 进入 psql
sudo -u postgres psql
```

在 psql 中执行（**替换占位符密码**）：

```sql
-- 创建专属用户（替换 <strong-password> 为强密码，参考 docs/DEPLOY.md 第 5.3 节生成方法）
CREATE USER surgery_user WITH PASSWORD '<strong-password>';

-- 创建数据库
CREATE DATABASE surgery_rag OWNER surgery_user;

-- 授予权限
GRANT ALL PRIVILEGES ON DATABASE surgery_rag TO surgery_user;
\c surgery_rag
GRANT ALL ON SCHEMA public TO surgery_user;
\q
```

### 4.3 配置 PostgreSQL 仅监听本地

确认 `postgresql.conf` 中 `listen_addresses` 设为 `localhost`（安全起见，不对外暴露数据库端口）：

```bash
# 找到 postgresql.conf
sudo -u postgres psql -c "SHOW config_file;"

# 确认 listen_addresses = 'localhost'
sudo grep "^listen_addresses" /etc/postgresql/15/main/postgresql.conf
# 预期输出：listen_addresses = 'localhost'
```

### 4.4 执行 Alembic 迁移

在部署后端后执行（见第 5 节），此处先记录命令：

```bash
cd /opt/surgery-rag/backend
source venv/bin/activate
alembic upgrade head
```

---

## 5. 后端部署

### 5.1 目录规划

```
/opt/surgery-rag/          # 项目根目录（建议放 /opt/，与现有项目隔离）
├── backend/
│   ├── app/               # FastAPI 应用
│   ├── alembic/           # 数据库迁移
│   ├── venv/              # Python 虚拟环境
│   ├── .env               # 环境变量（敏感，权限 600）
│   └── requirements.txt
├── frontend/
│   └── dist/              # 构建产物（或仅构建产物）
└── uploads/               # 用户上传文件目录
```

### 5.2 上传项目代码

**方式一：Git 拉取（推荐）**

```bash
# 在服务器上
cd /opt
git clone <your-repo-url> surgery-rag
cd surgery-rag
```

**方式二：本地打包上传**

在本机 Windows 上：

```powershell
# 先构建前端（见第 6 节），然后打包
cd "c:\Users\86182\Desktop\Surgery RAG-Agent"
# 将整个项目压缩（不含 node_modules、.venv、.git）
# 或通过 SCP 上传
```

```bash
# 在服务器上
cd /opt
# 方式二-1：SCP 上传（在本机执行）
scp -r "c:\Users\86182\Desktop\Surgery RAG-Agent" root@<服务器IP>:/opt/surgery-rag

# 方式二-2：OSS / FTP 上传后解压
unzip surgery-rag.zip -d /opt/surgery-rag
```

### 5.3 安装 Python 环境

```bash
# 确认 Python 版本 ≥ 3.11
python3 --version

# 如果版本不够，安装 Python 3.11（Ubuntu）
sudo apt install -y python3.11 python3.11-venv python3.11-dev

# 创建虚拟环境
cd /opt/surgery-rag/backend
python3.11 -m venv venv
source venv/bin/activate

# 升级 pip
pip install --upgrade pip

# 安装依赖（首次需要下载，耗时取决于网络，约 5–15 分钟）
pip install -r requirements.txt
```

> ⚠️ **国内服务器加速：** 在安装依赖前设置 pip 镜像：
> ```bash
> pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
> ```
>
> 同时设置 Hugging Face 镜像（模型下载）：
> ```bash
> export HF_ENDPOINT=https://hf-mirror.com
> ```

### 5.4 配置 .env 文件

```bash
cd /opt/surgery-rag/backend
cp .env.example .env
chmod 600 .env          # 严格权限：仅所有者可读写
```

编辑 `.env`，以下为**关键必填项**（其他配置项详见 `docs/DEPLOY.md`）：

```ini
# ── 数据库 ────────────────────────────────────────────
DATABASE_URL=postgresql://surgery_user:<strong-password>@localhost:5432/surgery_rag

# ── JWT ──────────────────────────────────────────────
# 务必生成新的强随机字符串！方法：openssl rand -base64 64
JWT_SECRET=<生成一个64位以上随机字符串>

# ── LLM ──────────────────────────────────────────────
DEEPSEEK_API_KEY=<你的 DeepSeek API Key>
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

# ── Hugging Face 镜像（国内服务器必须设置）────────────
HF_ENDPOINT=https://hf-mirror.com

# ── 上传文件目录（放到 /opt 下与代码同级）─────────────
UPLOAD_DIR=/opt/surgery-rag/uploads
```

### 5.5 执行数据库迁移

```bash
cd /opt/surgery-rag/backend
source venv/bin/activate
alembic upgrade head
```

预期输出：迁移成功，无报错。验证：

```bash
PGPASSWORD='<password>' psql -h localhost -U surgery_user -d surgery_rag -c "\dt"
# 预期至少看到：users, documents, chunks, sessions, messages, audit_logs
```

### 5.6 预热 Embedding 模型（首次启动）

```bash
cd /opt/surgery-rag/backend
source venv/bin/activate

# 手动预热一次，确保模型能正常下载和加载
python3 -c "
from app.services.embedder import warmup_embedder
warmup_embedder()
print('Embedding model loaded successfully.')
"
```

> 首次运行会从 Hugging Face 下载 BGE-M3 模型（约 2.2 GB），耗时取决于网络速度，约 5–20 分钟。如果设置了 `HF_ENDPOINT=https://hf-mirror.com`，下载速度会快很多。模型存放在 `~/.cache/huggingface/hub/`。

### 5.7 手动启动验证

```bash
cd /opt/surgery-rag/backend
source venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4
```

另开一个终端验证：

```bash
curl http://127.0.0.1:8000/health
# 预期：{"status":"ok"}
```

验证通过后 `Ctrl+C` 停止，接下来配置 systemd 自动管理。

---

## 6. 前端部署

### 6.1 构建方式选择

| 方式 | 操作 | 适用场景 |
|------|------|----------|
| **A — 服务器直接构建** | 在 ECS 上安装 Node.js 后 `npm ci && npm run build` | 服务器有 Node 环境 |
| **B — 本地构建上传** | 本机 `npm run build` 后 SCP 上传 `dist/` | 服务器不装 Node.js（推荐，节省服务器内存） |

> **推荐方式 B：** 服务器上不需要永久安装 Node.js，只需上传构建产物，节省 ~500 MB 空间，也避免构建时 CPU 峰值影响小程序后端。

### 6.2 方式 B — 本地构建 + 上传（推荐）

**在本机 Windows 上：**

```powershell
cd "c:\Users\86182\Desktop\Surgery RAG-Agent\frontend"

# 确认 API 基础地址（需要在构建前配置）
# 如果使用子域名方案，需要在前端代码中配置 axios baseURL
# 或在 vite.config.ts 中配置构建时的环境变量

# 安装依赖
npm ci

# 构建生产版本
npm run build
```

> ⚠️ **构建前的 API 地址配置：**
> 生产环境中前端通过 Nginx 反向代理访问后端。如果前端和后端部署在同一域名下（方案 A），
> axios 的 `baseURL` 应设为 `/` 或空字符串，通过 Nginx 的 `/api/` 路径转发。
> 检查 `frontend/src/` 中的 axios 实例配置，确保 `baseURL` 在生产环境正确。

构建完成后，产物在 `frontend/dist/`：

```bash
# 目录结构：
# frontend/dist/
# ├── index.html
# └── assets/
#     ├── index-xxxxx.js
#     ├── index-xxxxx.css
#     └── ...
```

**上传到服务器：**

```bash
# 在服务器上创建目录
sudo mkdir -p /var/www/surgery-rag

# 本机 Windows 上执行 SCP 上传
scp -r "c:\Users\86182\Desktop\Surgery RAG-Agent\frontend\dist\*" root@<服务器IP>:/var/www/surgery-rag/

# 设置权限
ssh root@<服务器IP> "chown -R www-data:www-data /var/www/surgery-rag"
# 如果是 CentOS，用户组可能是 nginx:nginx
```

### 6.3 方式 A — 服务器构建

```bash
# 安装 Node.js 18+（使用 nvm 管理版本，不影响已有环境）
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.bashrc
nvm install 18
nvm use 18

# 构建前端
cd /opt/surgery-rag/frontend
npm ci
npm run build

# 部署到 Nginx 目录
sudo mkdir -p /var/www/surgery-rag
sudo cp -r dist/* /var/www/surgery-rag/
sudo chown -R www-data:www-data /var/www/surgery-rag  # Ubuntu
# sudo chown -R nginx:nginx /var/www/surgery-rag       # CentOS
```

---

## 7. Nginx 多站点配置

> ⚠️ **绝对不要直接修改现有的 Nginx 配置文件。** 所有 Surgery RAG 相关配置独立新建文件。

### 7.1 备份现有配置

```bash
# 备份整个 Nginx 配置目录
sudo cp -r /etc/nginx /etc/nginx.backup.$(date +%Y%m%d)

# 查看现有配置入口
nginx -t 2>&1
ls -la /etc/nginx/sites-enabled/    # Ubuntu/Debian
ls -la /etc/nginx/conf.d/           # CentOS/RHEL
cat /etc/nginx/nginx.conf           # 找到 include 行
```

### 7.2 新建 Surgery RAG 站点配置

**方案 A：子域名方式（surgery.example.com）**

创建 `/etc/nginx/sites-available/surgery-rag`（Ubuntu）或 `/etc/nginx/conf.d/surgery-rag.conf`（CentOS）：

```nginx
# Surgery RAG Agent — Nginx 站点配置
# 与现有小程序后端 server 块独立，互不影响

server {
    listen 80;
    server_name surgery.example.com;   # 替换为实际子域名

    # 前端静态文件
    root /var/www/surgery-rag;
    index index.html;

    # 访问日志（独立文件，与现有日志分离）
    access_log /var/log/nginx/surgery-rag-access.log;
    error_log  /var/log/nginx/surgery-rag-error.log;

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

        # SSE 流式响应必须关闭缓冲
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;

        # 上传文件大小限制
        client_max_body_size 50m;
    }

    # 健康检查
    location /health {
        proxy_pass http://127.0.0.1:8000;
    }
}
```

**方案 B：同域名子路径方式（example.com/surgery/）**

在**现有** Nginx 配置的 server 块中新增 location 块（注意不要重复 server 块）：

```nginx
# 以下内容添加到已有的 server { } 块内部，不要创建新的 server 块

# Surgery RAG 前端
location /surgery/ {
    alias /var/www/surgery-rag/;
    try_files $uri $uri/ /surgery/index.html;
}

# Surgery RAG 后端 API
location /surgery/api/ {
    # 注意：后端实际收到的是去掉 /surgery 前缀后的路径
    rewrite ^/surgery/api/(.*)$ /api/v1/$1 break;
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 300s;
    client_max_body_size 50m;
}
```

> **方案 B 注意事项：** Vue Router 需要设置 `base: '/surgery/'`（在 `vite.config.ts` 中配置），需要重新构建前端。Axios baseURL 也要相应调整。

### 7.3 启用站点并重载 Nginx

```bash
# Ubuntu/Debian
sudo ln -s /etc/nginx/sites-available/surgery-rag /etc/nginx/sites-enabled/

# 检查配置语法
sudo nginx -t

# 如果输出 "syntax is ok" 和 "test is successful"，重载 Nginx
sudo systemctl reload nginx
# 或 sudo service nginx reload

# 验证 Nginx 状态
sudo systemctl status nginx
```

> ⚠️ **如果 `nginx -t` 报错，不要 `reload`，先排查错误。**
> 常见错误：端口冲突、`server_name` 重复、语法错误、路径不存在。
> 如果确实有问题且无法立即解决，先删除新建的配置文件，确保现有小程序服务不受影响。

---

## 8. Systemd 服务管理

### 8.1 创建 Surgery RAG 后端服务

创建 `/etc/systemd/system/surgery-rag.service`：

```ini
[Unit]
Description=Surgery RAG Agent Backend
After=network.target postgresql.service
# 如果 PostgreSQL 服务名不同，修改这里
# Ubuntu: postgresql.service
# CentOS: postgresql-15.service

[Service]
Type=simple
User=www-data
# 根据服务器实际 web 用户调整：Ubuntu=www-data, CentOS=nginx
Group=www-data
WorkingDirectory=/opt/surgery-rag/backend
Environment=PATH=/opt/surgery-rag/backend/venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=HF_ENDPOINT=https://hf-mirror.com
ExecStart=/opt/surgery-rag/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4
Restart=always
RestartSec=5

# 安全加固
PrivateTmp=true
NoNewPrivileges=true

# 日志
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### 8.2 启动并验证

```bash
# 重载 systemd 配置
sudo systemctl daemon-reload

# 启动服务
sudo systemctl enable --now surgery-rag

# 查看状态（确保 Active: active (running)）
sudo systemctl status surgery-rag

# 验证健康检查
curl http://127.0.0.1:8000/health

# 查看实时日志
sudo journalctl -u surgery-rag -f
```

### 8.3 常用运维命令

```bash
sudo systemctl restart surgery-rag   # 重启
sudo systemctl stop surgery-rag      # 停止
sudo systemctl start surgery-rag     # 启动
sudo journalctl -u surgery-rag -n 50 # 最近 50 行日志
sudo journalctl -u surgery-rag --since "1 hour ago"  # 最近 1 小时日志
```

---

## 9. 阿里云安全组配置

### 9.1 需要确认/新增的端口规则

登录阿里云控制台 → ECS → 安全组 → 配置规则：

| 方向 | 端口 | 协议 | 源 IP | 用途 | 操作 |
|------|------|------|-------|------|------|
| 入方向 | 80 | TCP | 0.0.0.0/0 | HTTP（已有） | **不动** |
| 入方向 | 443 | TCP | 0.0.0.0/0 | HTTPS（如已配） | **不动** |
| 入方向 | 22 | TCP | 办公 IP 段 | SSH | **不动** |
| 入方向 | 8000 | TCP | — | **不要开放！** 后端仅监听 127.0.0.1 | **不新增** |
| 入方向 | 5432 | TCP | — | **不要开放！** 数据库仅监听 localhost | **不新增** |

> ✅ **好消息：Surgery RAG 的后端和数据库都不对外暴露端口，Nginx 端口（80/443）已存在，通常不需要新增任何安全组规则。**

### 9.2 需要出方向访问

确保服务器可以出站访问以下地址（阿里云安全组默认允许所有出方向，一般无需调整）：

| 目标 | 端口 | 用途 |
|------|------|------|
| `api.deepseek.com` | 443 | DeepSeek LLM API 调用 |
| `hf-mirror.com`（或 `huggingface.co`） | 443 | BGE-M3 模型下载（仅首次） |
| `mirrors.aliyun.com` | 443 | pip 依赖安装 |
| GitHub（PaddleOCR 模型下载，仅首次） | 443 | OCR 模型初始化 |

---

## 10. 依赖服务启动顺序

服务器重启后，服务应按以下顺序自动启动：

```
系统启动
  │
  ├── 1. PostgreSQL    (enabled, after network)
  ├── 2. MySQL         (已存在, 不动)
  ├── 3. Nginx         (enabled, after network)
  ├── 4. 小程序后端     (已存在, enabled)
  └── 5. Surgery RAG   (enabled, after postgresql)
```

设置开机自启：

```bash
# PostgreSQL（通常已在安装时自动启用）
sudo systemctl is-enabled postgresql   # Ubuntu
sudo systemctl is-enabled postgresql-15  # CentOS

# Nginx（通常已在安装时自动启用）
sudo systemctl is-enabled nginx

# Surgery RAG 后端（上一步已设置）
sudo systemctl is-enabled surgery-rag

# 如果某项未启用：
sudo systemctl enable <service-name>
```

---

## 11. 环境变量安全

### 11.1 敏感文件权限检查清单

```bash
# .env 文件必须 600（仅所有者可读写）
ls -la /opt/surgery-rag/backend/.env
# 预期：-rw------- 1 www-data www-data ...

# 如果权限不对
chmod 600 /opt/surgery-rag/backend/.env

# 确认 .env 不在 Git 跟踪中
cd /opt/surgery-rag
git ls-files --error-unmatch backend/.env 2>/dev/null && echo "WARNING: .env is tracked!" || echo "OK: .env not tracked"
```

### 11.2 生产环境安全建议

1. **JWT_SECRET** 和 **DEEPSEEK_API_KEY** 不要在日志中打印
2. 定期轮换密钥（每季度一次，流程见 `docs/DEPLOY.md` 第 5.2 节）
3. 后端 CORS 当前为 `allow_origins=["*"]`，生产稳定后可收窄为实际前端域名
4. 考虑使用阿里云 KMS 或 Secrets Manager 管理密钥（长期优化，首次部署可跳过）

---

## 12. 监控与日志

### 12.1 日志位置

| 日志 | 路径 | 查看命令 |
|------|------|----------|
| Surgery 后端 | systemd journal | `journalctl -u surgery-rag -f` |
| Nginx 访问日志 | `/var/log/nginx/surgery-rag-access.log` | `tail -f /var/log/nginx/surgery-rag-access.log` |
| Nginx 错误日志 | `/var/log/nginx/surgery-rag-error.log` | `tail -f /var/log/nginx/surgery-rag-error.log` |
| PostgreSQL | 系统 journal 或 `/var/log/postgresql/` | `journalctl -u postgresql` |

### 12.2 日志轮转配置

创建 `/etc/logrotate.d/surgery-rag`：

```
/var/log/nginx/surgery-rag-*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 640 www-data adm
    sharedscripts
    postrotate
        [ -f /var/run/nginx.pid ] && kill -USR1 $(cat /var/run/nginx.pid)
    endscript
}
```

### 12.3 基础资源监控

```bash
# 实时内存使用（观察是否有 OOM 风险）
watch -n 5 free -h

# 磁盘使用（关注模型文件、上传文件增长）
df -h /opt

# 后端进程内存占用
ps aux --sort=-%mem | head -10
```

> **建议：** 在阿里云控制台为 ECS 实例开启「云监控」，设置内存 > 80% 和磁盘 > 85% 的告警规则。免费版即可满足基本需求。

---

## 13. 备份策略

### 13.1 数据库自动备份

```bash
# 创建备份脚本
sudo mkdir -p /opt/backups
sudo tee /opt/backups/backup-surgery-db.sh > /dev/null << 'SCRIPT'
#!/bin/bash
BACKUP_DIR="/opt/backups"
DB_NAME="surgery_rag"
DB_USER="surgery_user"
DB_PASS="<数据库密码>"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

PGPASSWORD="$DB_PASS" pg_dump -h localhost -U "$DB_USER" -d "$DB_NAME" \
  -Fc -f "$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.dump"

# 保留最近 14 天的备份
find "$BACKUP_DIR" -name "${DB_NAME}_*.dump" -mtime +14 -delete

echo "[$(date)] Backup completed: ${DB_NAME}_${TIMESTAMP}.dump"
SCRIPT

sudo chmod +x /opt/backups/backup-surgery-db.sh
```

**设置 crontab 定时执行：**

```bash
# 编辑 www-data 用户（或其他执行用户）的 crontab
sudo crontab -u root -e

# 添加：每天凌晨 3:00 备份（避开小程序备份的时间，假设小程序在 2:00）
0 3 * * * /opt/backups/backup-surgery-db.sh >> /opt/backups/backup.log 2>&1
```

### 13.2 上传文件备份

```bash
# 备份 uploads 目录
sudo tee /opt/backups/backup-surgery-uploads.sh > /dev/null << 'SCRIPT'
#!/bin/bash
BACKUP_DIR="/opt/backups"
TIMESTAMP=$(date +%Y%m%d)

tar -czf "$BACKUP_DIR/uploads_${TIMESTAMP}.tar.gz" -C /opt/surgery-rag uploads/

# 保留最近 7 天的备份（上传文件可能很大，不宜保留过多）
find "$BACKUP_DIR" -name "uploads_*.tar.gz" -mtime +7 -delete

echo "[$(date)] Uploads backup completed"
SCRIPT

sudo chmod +x /opt/backups/backup-surgery-uploads.sh
```

Crontab 中添加（每周日凌晨 4:00）：

```
0 4 * * 0 /opt/backups/backup-surgery-uploads.sh >> /opt/backups/backup.log 2>&1
```

### 13.3 阿里云快照（额外保险）

在阿里云控制台为 ECS 系统盘配置自动快照策略（建议每周一次），快照保留 2 周。这是最后的防线——即使误删文件，也能从快照恢复。

---

## 14. 部署验证清单

按以下顺序逐项执行，每项通过后打勾。

### 阶段 1：环境准备

| # | 验证项 | 命令 | 预期 | ✓ |
|---|--------|------|------|---|
| 1.1 | PostgreSQL 运行中 | `sudo systemctl status postgresql` | active (running) | |
| 1.2 | pgvector 扩展可用 | `sudo -u postgres psql -c "SELECT * FROM pg_available_extensions WHERE name='vector'"` | 有一行结果 | |
| 1.3 | 数据库和用户已创建 | `PGPASSWORD='<pwd>' psql -h localhost -U surgery_user -d surgery_rag -c "\dt"` | 无连接错误 | |
| 1.4 | Python ≥ 3.11 | `python3.11 --version` | ≥ 3.11.x | |
| 1.5 | 可用内存 ≥ 1 GB 剩余 | `free -m` | available ≥ 1000 | |

### 阶段 2：后端部署

| # | 验证项 | 命令 | 预期 | ✓ |
|---|--------|------|------|---|
| 2.1 | 所有 pip 依赖安装成功 | `cd /opt/surgery-rag/backend && source venv/bin/activate && pip check` | No broken requirements | |
| 2.2 | Alembic 迁移成功 | `alembic current` | 显示当前 revision，无报错 | |
| 2.3 | 业务表已创建 | 查 psql `\dt` | 6 张表：users, documents, chunks, sessions, messages, audit_logs | |
| 2.4 | BGE-M3 模型加载成功 | 见 5.6 节预热命令 | 无报错 | |
| 2.5 | 后端健康检查 | `curl http://127.0.0.1:8000/health` | `{"status":"ok"}` | |

### 阶段 3：前端部署

| # | 验证项 | 命令 | 预期 | ✓ |
|---|--------|------|------|---|
| 3.1 | 构建产物存在 | `ls /var/www/surgery-rag/index.html` | 文件存在 | |
| 3.2 | 静态资源可访问（先不通过域名） | `curl -I http://127.0.0.1:80/` 或临时测试 | HTTP 200 | |

### 阶段 4：Nginx 与服务集成

| # | 验证项 | 命令 | 预期 | ✓ |
|---|--------|------|------|---|
| 4.1 | Nginx 配置语法正确 | `sudo nginx -t` | syntax is ok | |
| 4.2 | Nginx 重载成功 | `sudo systemctl reload nginx` | 无报错 | |
| 4.3 | Surgery RAG systemd 服务运行 | `sudo systemctl status surgery-rag` | active (running) | |
| 4.4 | 前端可通过 Nginx 访问 | 浏览器打开配置的域名/IP | 显示登录/注册页 | |
| 4.5 | API 代理正常工作 | 浏览器 DevTools Network 检查 `/api/` 请求 | 返回 JSON，非 502/504 | |
| 4.6 | 小程管理后台仍正常 | 确认原有小程页面可正常访问 | 不受影响 | |

### 阶段 5：功能验证

| # | 验证项 | 操作 | 预期 | ✓ |
|---|--------|------|------|---|
| 5.1 | 用户注册 | 注册新用户 | 注册成功，自动跳转 | |
| 5.2 | 用户登录 | 登录已注册用户 | 进入对话页 | |
| 5.3 | 文档上传 | 上传 PDF/DOCX 文件 | 状态变为 completed | |
| 5.4 | RAG 问答 | 提问与文档相关的问题 | 返回带引用的回答 | |
| 5.5 | 流式输出 | 提交问题 | 逐字流式呈现 | |
| 5.6 | 多轮对话 | 连续提问含上下文的问题 | 回答能引用上文 | |
| 5.7 | 管理面板 | admin 角色登录 | 文档/用户/日志管理可用 | |

---

## 15. 故障回滚方案

### 15.1 回滚触发条件

- Nginx 配置导致现有小程序站点不可用
- Surgery RAG 后端 OOM 导致服务器整体不稳定
- PostgreSQL 安装影响其他服务

### 15.2 快速回滚步骤

**第 1 步：停止 Surgery RAG 后端**

```bash
sudo systemctl stop surgery-rag
sudo systemctl disable surgery-rag
```

**第 2 步：移除 Nginx Config**

```bash
sudo rm /etc/nginx/sites-enabled/surgery-rag
sudo nginx -t && sudo systemctl reload nginx
```

**第 3 步：释放内存**

```bash
# 如果不需要，可以停止 PostgreSQL 释放 ~200 MB
sudo systemctl stop postgresql
```

**第 4 步（可选）：彻底清理**

```bash
# 删除项目文件
sudo rm -rf /opt/surgery-rag

# 删除数据库
sudo -u postgres psql -c "DROP DATABASE surgery_rag;"
sudo -u postgres psql -c "DROP USER surgery_user;"

# 删除 systemd 服务文件
sudo rm /etc/systemd/system/surgery-rag.service
sudo systemctl daemon-reload
```

### 15.3 最小化风险原则

- **每次只做一步**，验证通过后再进行下一步
- **不在业务高峰期部署**——建议选择凌晨或周末
- **永远不要 `nginx -t` 失败后 `reload`**——先排查错误
- **修改任何文件前先备份**——已创建的 `/etc/nginx.backup.*` 是救命稻草

---

## 16. 时间线估算

| 阶段 | 步骤 | 预计耗时 | 风险等级 |
|------|------|----------|----------|
| 1 | 服务器摸底 + 安全组确认 | 15 分钟 | 低 |
| 2 | 安装 PostgreSQL + pgvector | 20 分钟 | 低 |
| 3 | 上传代码 + 安装 Python 依赖 | 20 分钟 | 低 |
| 4 | 配置 .env + 数据库迁移 | 10 分钟 | 中（注意密码） |
| 5 | 下载 BGE-M3 模型（国内服务器较慢） | 5–20 分钟 | 低（依赖网络） |
| 6 | 构建并上传前端 | 10 分钟 | 低 |
| 7 | Nginx 配置 + 重载 | 10 分钟 | **高**（影响现有服务） |
| 8 | Systemd 配置 + 启动 | 5 分钟 | 低 |
| 9 | 功能验证 | 30 分钟 | 低 |
| 10 | 备份配置 | 15 分钟 | 低 |
| **总计** | | **约 2.5–3 小时** | |

---

## 附录 A：绝对不要做的事情

1. ❌ **不要在 `nginx -t` 失败时 `reload`**——这会导致现有小程序也挂掉
2. ❌ **不要删除或修改现有的 Nginx server 块**——只新增，不删除
3. ❌ **不要将后端端口（8000）暴露到公网**——通过安全组和 Nginx 隔离
4. ❌ **不要将 PostgreSQL 端口（5432）暴露到公网**——只监听 127.0.0.1
5. ❌ **不要在高峰期执行部署**——选在凌晨或周末
6. ❌ **不要将 `.env` 文件提交到 Git**——密码泄露
7. ❌ **不要跳过第 2.1 节的摸底步骤**——不了解现状就开始部署是最大风险

---

## 附录 B：部署前置会议 Check List

在开始部署前，与现有小程后端负责人确认以下事项：

- [ ] 服务器 SSH 登录方式（密码/密钥/跳板机）
- [ ] 当前服务器资源使用情况（内存空闲多少、磁盘空闲多少）
- [ ] 小程后端使用的端口列表（避免冲突）
- [ ] 小程后端的 Nginx 配置内容（提前了解，好规划新增内容）
- [ ] 小程后端的高峰时段（避开那个时间段部署）
- [ ] 数据库是否已有 PostgreSQL？如果没有，是否允许安装？
- [ ] 域名是否已备案？如果需要子域名，谁来配置 DNS？
- [ ] 是否有内部 CI/CD 流程需要考虑？
- [ ] 阿里云账号权限（是否需要主账号授权操作安全组/E CS？）

---

> **参考文档：** 本文档与 `docs/DEPLOY.md` 互补——`docs/DEPLOY.md` 提供了详细的各组件配置说明、密钥管理和故障排查；本文档聚焦于阿里云服务器上与现有服务共存的端到端部署流程。
>
> **首次部署建议：** 在第 2.1 节摸底完成后，根据实际环境调整本文档中的路径和命令，再做执行。
