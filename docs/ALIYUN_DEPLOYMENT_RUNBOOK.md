# Surgery RAG Agent 阿里云部署交接手册

> 最后更新：2026-07-31  
> 用途：给之后的新对话、Agent 或人工维护者快速了解当前阿里云 ECS 部署状态，并按固定流程从 GitHub 拉取更新、重启服务。

## 1. 部署概况

本项目已部署在阿里云 ECS，中国香港地域，采用裸机部署方式，不使用 Docker。

| 项目 | 当前值 |
|------|--------|
| 云厂商 | 阿里云 ECS |
| 地域 | 中国香港 |
| 公网 IP | `47.83.114.62` |
| 主私网 IP | `172.30.243.211` |
| 操作系统 | Ubuntu 22.04.5 LTS 64 位 |
| CPU | 2 vCPU |
| 内存 | 已升级到约 4 GiB |
| Swap | `/swapfile` 4 GiB，`vm.swappiness=10` |
| 系统盘 | ESSD Entry 云盘 40 GiB |
| 公网带宽 | 10 Mbps 峰值，按使用流量计费 |

线上访问地址：

| 服务 | 地址 |
|------|------|
| Surgery RAG Agent | `https://surgery.geneyoung.top/` |
| 后端健康检查 | `https://surgery.geneyoung.top/health` |
| 原小程序站点 | `https://geneyoung.top/` |

DNS：

```text
surgery.geneyoung.top A 47.83.114.62
```

## 2. 服务器上的关键路径

| 内容 | 路径 |
|------|------|
| 项目目录 | `/opt/surgery-rag` |
| 后端目录 | `/opt/surgery-rag/backend` |
| 后端虚拟环境 | `/opt/surgery-rag/backend/venv` |
| 后端环境变量 | `/opt/surgery-rag/backend/.env` |
| 上传文件目录 | `/opt/surgery-rag/uploads` |
| 前端构建产物部署目录 | `/var/www/surgery-rag` |
| Nginx 站点配置 | `/etc/nginx/sites-available/surgery-rag` |
| Systemd 后端服务 | `/etc/systemd/system/surgery-rag.service` |
| 数据库密码文件 | `/root/surgery_rag_db_password` |
| Playwright 浏览器缓存 | `/root/.cache/ms-playwright` |

`.env`、数据库密码、API Key 都是敏感信息，不能复制到聊天或提交到 Git。

## 3. 当前运行服务

Surgery RAG 后端：

```text
systemd 服务名：surgery-rag
监听地址：127.0.0.1:8000
启动命令：uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

反向代理：

```text
Nginx 监听 80/443
surgery.geneyoung.top -> /var/www/surgery-rag
/api/ 和 /health -> http://127.0.0.1:8000
```

数据库：

```text
PostgreSQL 15
数据库：surgery_rag
用户：surgery_user
扩展：vector, uuid-ossp, pg_trgm
```

同一台服务器上还运行原小程序服务，更新 Surgery RAG 时不要停止它：

```text
miniprogram.service
Nginx: geneyoung.top / www.geneyoung.top
后端监听：127.0.0.1:5000
MySQL 监听：127.0.0.1:3306
```

## 4. 已完成的部署操作记录

已完成：

- ECS 内存从 2 GiB 升级到约 4 GiB。
- 添加 4 GiB swap：`/swapfile`。
- 安装 PostgreSQL 15 和 pgvector。
- 创建数据库 `surgery_rag`、用户 `surgery_user`。
- 数据库密码已轮换为随机值，存放在 `/root/surgery_rag_db_password`。
- 创建 PostgreSQL 扩展：`vector`、`uuid-ossp`、`pg_trgm`。
- 执行 Alembic 迁移到 `0004 (head)`。
- 使用 GitHub Deploy Key 拉取仓库到 `/opt/surgery-rag`。
- 后端 Python 虚拟环境位于 `/opt/surgery-rag/backend/venv`。
- BGE-M3 embedding 模型已成功下载并可加载。
- 创建并启用 `surgery-rag.service`。
- 安装 Node.js 20，构建前端并部署到 `/var/www/surgery-rag`。
- 配置 `surgery.geneyoung.top` 的 Nginx 站点。
- 使用 Certbot 签发 `surgery.geneyoung.top` 的 Let's Encrypt 证书。
- `certbot renew --dry-run` 验证通过。
- 安装 Playwright Chromium，用于 AI 操作者报告 PDF 导出。
- 创建角色账号：1 个管理员、2 个 AI 操作者。

当前建议：

- 后端保持 `--workers 1`。4 GiB 内存下，BGE-M3 模型占用较高，多 worker 会重复加载模型，容易增加内存压力。
- 如果后续大量 OCR、向量化或报告生成并发较高，再考虑升级到 8 GiB 内存。

## 5. 日常从 GitHub 更新线上版本

这个流程用于：本地改完代码并推送到 GitHub 后，在服务器拉取最新代码并重启服务。

### 5.1 本地先提交并推送

在本地项目目录执行：

```bash
git status
git add .
git commit -m "你的提交说明"
git push origin main
```

确认 GitHub 上已经有最新 commit 后，再连接服务器。

### 5.2 服务器更新命令

连接 ECS 后执行：

```bash
cd /opt/surgery-rag

echo "=== 当前版本 ==="
git log --oneline -1

echo "=== 停止 Surgery RAG 后端 ==="
sudo systemctl stop surgery-rag

echo "=== 拉取最新代码 ==="
git pull --ff-only

echo "=== 后端依赖与数据库迁移 ==="
cd /opt/surgery-rag/backend
source venv/bin/activate
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
alembic upgrade head

echo "=== 前端构建与部署 ==="
cd /opt/surgery-rag/frontend
npm ci --registry=https://registry.npmmirror.com
npm run build
sudo rsync -a --delete /opt/surgery-rag/frontend/dist/ /var/www/surgery-rag/

echo "=== 重启后端并重载 Nginx ==="
sudo systemctl start surgery-rag
sudo systemctl reload nginx

echo "=== 验证 ==="
sleep 30
curl https://surgery.geneyoung.top/health
sudo systemctl status surgery-rag --no-pager -l
```

预期：

```text
{"status":"ok"}
surgery-rag.service Active: active (running)
```

### 5.3 小改动的快速更新

如果只是后端代码改动，没有依赖变化、没有数据库迁移、没有前端变化，可以简化为：

```bash
cd /opt/surgery-rag
sudo systemctl stop surgery-rag
git pull --ff-only
sudo systemctl start surgery-rag
sleep 30
curl https://surgery.geneyoung.top/health
```

如果只是前端改动：

```bash
cd /opt/surgery-rag
git pull --ff-only

cd /opt/surgery-rag/frontend
npm ci --registry=https://registry.npmmirror.com
npm run build
sudo rsync -a --delete /opt/surgery-rag/frontend/dist/ /var/www/surgery-rag/
sudo systemctl reload nginx
```

## 6. 常用检查命令

服务状态：

```bash
sudo systemctl status surgery-rag nginx postgresql mysql miniprogram --no-pager -l
```

后端日志：

```bash
sudo journalctl -u surgery-rag -f
```

端口监听：

```bash
ss -tlnp | grep -E ':(8000|5000|5432|3306|80|443)\b' || true
```

健康检查：

```bash
curl https://surgery.geneyoung.top/health
curl -I https://surgery.geneyoung.top/
curl -I https://geneyoung.top/
```

资源检查：

```bash
free -h
df -h /
ps aux --sort=-%mem | head
```

数据库表检查：

```bash
PGPASSWORD="$(cat /root/surgery_rag_db_password)" \
psql -h localhost -U surgery_user -d surgery_rag -c "\dt"
```

用户角色检查：

```bash
PGPASSWORD="$(cat /root/surgery_rag_db_password)" \
psql -h localhost -U surgery_user -d surgery_rag \
-c "SELECT id, username, email, role, created_at FROM users ORDER BY id;"
```

证书检查：

```bash
echo | openssl s_client -connect surgery.geneyoung.top:443 -servername surgery.geneyoung.top 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
```

证书续期演练：

```bash
sudo certbot renew --dry-run
```

Playwright PDF 导出检查：

```bash
cd /opt/surgery-rag/backend
source venv/bin/activate

python - <<'PY'
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    print("chromium ok:", browser.version)
    browser.close()
PY
```

## 7. 后端配置摘要

生产 `.env` 位于：

```text
/opt/surgery-rag/backend/.env
```

关键配置含义：

| 配置 | 当前用途 |
|------|----------|
| `DATABASE_URL` | 连接本机 PostgreSQL `surgery_rag` |
| `DEEPSEEK_API_KEY` | DeepSeek 调用密钥 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL` | `deepseek-chat` |
| `UPLOAD_DIR` | `/opt/surgery-rag/uploads` |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` |
| `EMBEDDING_DIMENSION` | `1024` |
| `HF_ENDPOINT` | `https://hf-mirror.com` |
| `VECTOR_COLLECTION_NAME` | `surgery_docs` |
| `ENABLE_AGENT_MODE` | 当前为 `False` |

如果修改 `.env`，必须重启后端：

```bash
sudo systemctl restart surgery-rag
```

## 8. 管理员与 AI 操作者账号

当前数据库中已创建：

| 用户名 | 邮箱 | 角色 |
|--------|------|------|
| `admin` | `admin@admin.com` | `admin` |
| `operator1` | `operator1@operator1.com` | `ai_operator` |
| `operator2` | `operator2@operator2.com` | `ai_operator` |

如需重新创建或修改角色，优先使用项目脚本：

```bash
cd /opt/surgery-rag/backend
source venv/bin/activate

python ../scripts/create_admin.py
python ../scripts/create_ai_operator.py
```

## 9. 常见问题记录

### 9.1 DOCX 分块失败：`There is no item named 'NULL' in the archive`

原因通常是 WPS 生成的 `.docx` 内部关系文件存在非法引用，例如 `Target="NULL"`。`.docx` 本质是 ZIP 包，解析库读取时会尝试在压缩包里寻找名为 `NULL` 的项目，从而失败。

临时处理：用 Word 或 WPS 打开该文件，重新另存为新的 `.docx` 后再上传。

### 9.2 AI 操作者 PDF 下载失败，提示 Playwright 缺少 Chromium

原因是 Python 包已安装，但 Playwright 浏览器执行文件未下载。

已在服务器执行过：

```bash
cd /opt/surgery-rag/backend
source venv/bin/activate
python -m playwright install-deps chromium
PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright python -m playwright install chromium
sudo systemctl restart surgery-rag
```

如未来依赖升级后再次出现，可重新执行上述命令。

## 10. 敏感信息与安全注意事项

- 不要在聊天、文档、Git commit 中粘贴 `.env` 的真实内容。
- 不要粘贴 DeepSeek API Key、数据库密码、JWT Secret。
- 数据库密码已不使用最初部署时手动填写的明文密码，当前随机密码在 `/root/surgery_rag_db_password`。
- 如果 API Key 曾经暴露，应该到 DeepSeek 控制台创建新 Key，更新 `.env`，重启 `surgery-rag`，再吊销旧 Key。
- 当前 `surgery-rag.service` 使用 `root` 运行，后续可优化为独立低权限用户。

## 11. 更新失败时的回退思路

如果 `git pull`、依赖安装、迁移、构建或启动失败：

1. 先不要动原小程序服务 `miniprogram.service`。
2. 查看后端日志：

```bash
sudo journalctl -u surgery-rag -n 120 --no-pager
```

3. 查看当前 commit：

```bash
cd /opt/surgery-rag
git log --oneline -5
```

4. 如果只是后端启动失败，可以先回到上一个 commit，再重启：

```bash
cd /opt/surgery-rag
git log --oneline -5
git checkout <上一版commit>
sudo systemctl start surgery-rag
curl https://surgery.geneyoung.top/health
```

5. 之后在本地修复问题，重新提交并推送，再按第 5 节更新。

注意：如果已经执行了数据库迁移，回退代码前要先确认迁移是否兼容旧代码，不要盲目降级数据库。
