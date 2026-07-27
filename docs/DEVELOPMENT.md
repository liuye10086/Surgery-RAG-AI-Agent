# 本地开发指南

## 固定运行时

- Python 3.11.4
- Node.js 22.15.0
- npm 10.9.2
- PostgreSQL 15+，本机基线为 18.1
- pgvector 0.5+，本机基线为 0.8.3

不要使用 Python 3.14 或历史 Python 3.7 环境运行本项目。

## 首次恢复项目依赖

```powershell
nvm use 22.15.0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/verify_baseline.ps1 -InstallDependencies
```

该命令只创建 `backend/.venv`、安装 Python 项目依赖并根据 `package-lock.json` 执行 `npm ci`，不会安装系统运行时。

如果 Windows 未启用长路径且 worktree 绝对路径较长，PyTorch 安装可能触发 `WinError 206`。可临时将项目目录映射为短盘符后重试安装，完成后解除映射；不要为本项目修改全局 Python 或 Node.js 安装。

## 日常基线验证

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/verify_baseline.ps1
```

结果写入 `docs/coordination/BASELINE.md`。`PASS` 表示通过，`FAIL` 表示检查完成但不满足条件，`SKIP` 表示按安全边界跳过，`BLOCKED` 表示缺少必需环境或配置。

## 后端

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m unittest discover -s tests -v
alembic current
uvicorn app.main:app --reload
```

数据库正式结构以 Alembic 为准。新建空数据库执行 `alembic upgrade head`；`database/schema.sql` 只作参考。

## 前端

```powershell
nvm use 22.15.0
cd frontend
npm ci
npm run dev
npm run build
```

项目只使用 npm，不提交 pnpm lockfile，也不混用包管理器。

## 数据库安全边界

- 基线默认只执行扩展、Alembic revision、表和关键列检查。
- 不删除、清空、重建或迁移现有数据库。
- 不输出 `.env`、数据库连接串、密码或密钥。

## 默认跳过

- DeepSeek 或其他外部 LLM 调用
- BGE-M3、PaddleOCR 等模型下载
- OCR 集成、GPU 测试和文档重新索引
- 数据库写入测试
