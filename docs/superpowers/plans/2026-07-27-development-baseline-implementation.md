# Development Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可重复执行的 Windows 开发环境检查、后端测试、前端构建、数据库只读验证和非敏感基线报告。

**Architecture:** PowerShell 脚本负责运行时发现、可选依赖恢复、命令编排和结果汇总；Python 助手脚本通过 SQLAlchemy 执行强制只读的数据库检查。`docs/DEVELOPMENT.md` 提供可移植命令，`docs/coordination/BASELINE.md` 记录一次真实执行结果。

**Tech Stack:** PowerShell 5.1+、Python 3.11.4、Python `unittest`、SQLAlchemy、Node.js 22.15.0、npm 10.9.2、PostgreSQL 18.1、pgvector 0.8.3、Git

## Global Constraints

- 任务编号为 `development-baseline-001`，实施者为 Codex；不形成永久职责。
- 遵循 `AI_COLLABORATION.md`，使用 `codex/development-baseline-001` 独立分支和 worktree。
- 不安装新的系统 Python、Node.js、PostgreSQL 或 pgvector。
- 后端固定 Python 3.11.4，前端固定 Node.js 22.15.0 和 npm 10.9.2。
- Python 依赖只安装到 `backend/.venv`；前端依赖只通过 `frontend/package-lock.json` 和 `npm ci` 恢复。
- 不调用 DeepSeek，不输出 API 密钥，不下载 BGE-M3/PaddleOCR 模型，不重新索引文档。
- 数据库检查只能执行只读 SQL；不得运行 DDL、DML、Alembic upgrade/downgrade、`DROP`、`TRUNCATE` 或破坏性 `DELETE`。
- 不输出 `DATABASE_URL`、密码、JWT secret、API key 或个人绝对路径到已提交文档。
- Agent 可以创建本地提交，但不得未经授权推送或合并。
- 当前测试套件使用 `unittest`，因此基线命令为 `python -m unittest discover -s tests -v`；不为本任务增加 pytest 依赖。

---

## File Map

- Create: `scripts/check_database_readonly.py` — 读取现有配置并执行 PostgreSQL 只读结构检查。
- Create: `backend/tests/test_database_baseline.py` — 数据库检查脚本的无数据库单元测试。
- Create: `scripts/check_dev_environment.ps1` — 只读发现运行时、项目依赖和配置状态。
- Create: `scripts/verify_baseline.ps1` — 可选恢复项目依赖，运行后端、前端和数据库检查，生成报告。
- Create: `scripts/tests/test_baseline_scripts.ps1` — PowerShell 脚本静态安全与接口合同检查。
- Create: `docs/DEVELOPMENT.md` — 可移植的开发、安装、启动和验证说明。
- Create: `docs/coordination/BASELINE.md` — 由验证脚本生成并提交的真实基线结果。
- Modify: `docs/coordination/ACTIVE_TASKS.md` — 登记、评审和完成 `development-baseline-001`。

### Task 1: Register The Baseline Task And Create The Worktree

**Files:**
- Modify: `docs/coordination/ACTIVE_TASKS.md`
- Reference: `docs/coordination/TASK_TEMPLATE.md`

**Interfaces:**
- Consumes: 多角色协作规范和当前干净的 `main`。
- Produces: 可审计的任务范围，以及 `codex/development-baseline-001` 独立工作区。

- [ ] **Step 1: Verify and synchronize the coordination workspace**

Run from the main workspace:

```powershell
git status --short --branch
git fetch origin
git switch main
git pull --ff-only origin main
```

Expected: 工作树干净；`main` 可快进或已经最新。如果无法快进，停止并交给项目所有者处理。

- [ ] **Step 2: Add the active task record**

Append a `development-baseline-001` entry to `docs/coordination/ACTIVE_TASKS.md` with:

```yaml
task_id: development-baseline-001
title: 建立开发与测试环境基线
status: in-progress
risk: normal
owner: Codex
client: Codex-Desktop
branch: codex/development-baseline-001
worktree: .worktrees/development-baseline-001
planner: Codex
implementer: Codex
reviewer: Claude-Code
database_change: false
plan: docs/superpowers/plans/2026-07-27-development-baseline-implementation.md
review_handoff: pending
```

Use these scopes:

```text
Exact files:
- scripts/check_database_readonly.py
- backend/tests/test_database_baseline.py
- scripts/check_dev_environment.ps1
- scripts/verify_baseline.ps1
- scripts/tests/test_baseline_scripts.ps1
- docs/DEVELOPMENT.md
- docs/coordination/BASELINE.md
- docs/coordination/ACTIVE_TASKS.md

Shared resources:
- backend/.venv (Git ignored)
- frontend/node_modules (Git ignored)
- backend/.env (read-only, Git ignored)
- current PostgreSQL database (read-only)
```

Acceptance conditions must state: no system runtime install, no database writes, no external AI/model calls, and explicit `PASS`/`FAIL`/`SKIP`/`BLOCKED` output.

- [ ] **Step 3: Commit task registration on main**

```powershell
git add -- docs/coordination/ACTIVE_TASKS.md
git -c user.name="Codex Agent" -c user.email="codex-agent@local" commit -m "docs(coordination): register development baseline" -m "AI-Agent: Codex`nAI-Client: Codex-Desktop`nTask-ID: development-baseline-001"
```

Expected: 一个只包含活动任务登记的本地提交。

- [ ] **Step 4: Create the isolated worktree**

```powershell
git worktree add '.worktrees/development-baseline-001' -b 'codex/development-baseline-001'
git -C '.worktrees/development-baseline-001' status --short --branch
```

Expected: 分支为 `codex/development-baseline-001`，工作树干净。

- [ ] **Step 5: Restore backend dependencies required by the test suite**

The project owner has authorized project-local dependency installation. Run inside the task worktree:

```powershell
py -3.11 -m venv backend/.venv
backend\.venv\Scripts\python.exe -m pip install --upgrade pip
backend\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
```

Expected: `backend/.venv/Scripts/python.exe --version` reports Python 3.11.x. No package is installed into global Python.

### Task 2: Build The Read-Only Database Checker With Tests

**Files:**
- Create: `scripts/check_database_readonly.py`
- Create: `backend/tests/test_database_baseline.py`

**Interfaces:**
- Consumes: `app.core.config.settings.DATABASE_URL`，但不打印其值。
- Produces: 退出码 `0/1` 和仅含非敏感检查结果的 JSON；供 `verify_baseline.ps1` 调用。

- [ ] **Step 1: Write failing unit tests for the database checker**

Create `backend/tests/test_database_baseline.py`:

```python
import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts/check_database_readonly.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("database_baseline_checker", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载数据库基线脚本: {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.statements.append(sql)
        if "SET TRANSACTION READ ONLY" in sql:
            return _FakeResult([])
        if "server_version" in sql:
            return _FakeResult(["18.1"])
        if "pg_extension" in sql:
            return _FakeResult([
                {"extname": "pg_trgm", "extversion": "1.6"},
                {"extname": "uuid-ossp", "extversion": "1.1"},
                {"extname": "vector", "extversion": "0.8.3"},
            ])
        if "alembic_version" in sql:
            return _FakeResult(["0002"])
        if "information_schema.columns" in sql:
            return _FakeResult([
                {"table_name": table_name, "column_name": column_name}
                for table_name, columns in _load_checker().REQUIRED_COLUMNS.items()
                for column_name in columns
            ])
        raise AssertionError(f"unexpected SQL: {sql}")


class DatabaseBaselineTests(unittest.TestCase):
    def test_checker_forces_read_only_transaction(self):
        checker = _load_checker()
        connection = _FakeConnection()
        report = checker.collect_checks(connection)
        self.assertIn("SET TRANSACTION READ ONLY", connection.statements[0])
        self.assertEqual(report["status"], "PASS")

    def test_checker_requires_expected_extensions(self):
        checker = _load_checker()
        self.assertEqual(
            checker.REQUIRED_EXTENSIONS,
            {"vector", "uuid-ossp", "pg_trgm"},
        )

    def test_checker_requires_current_alembic_head(self):
        checker = _load_checker()
        self.assertEqual(checker.EXPECTED_ALEMBIC_HEAD, "0002")

    def test_checker_source_contains_no_mutating_sql(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8").upper()
        for forbidden in ("DROP ", "TRUNCATE ", "INSERT ", "UPDATE ", "DELETE ", "ALTER "):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify it fails**

Run from the worktree root with the project virtual environment:

```powershell
backend\.venv\Scripts\python.exe -m unittest discover -s backend\tests -p test_database_baseline.py -v
```

Expected: FAIL because `scripts/check_database_readonly.py` does not exist.

- [ ] **Step 3: Implement the read-only checker**

Create `scripts/check_database_readonly.py`:

```python
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402


REQUIRED_EXTENSIONS = {"vector", "uuid-ossp", "pg_trgm"}
EXPECTED_ALEMBIC_HEAD = "0002"
REQUIRED_COLUMNS = {
    "users": {"id", "username", "email", "hashed_password", "role"},
    "documents": {"id", "filename", "status", "active_generation"},
    "chunks": {"id", "document_id", "content", "generation", "is_current"},
    "sessions": {"id", "user_id", "title"},
    "messages": {"id", "session_id", "role", "content", "client_request_id"},
    "audit_logs": {"id", "user_id", "session_id", "safety_flags"},
}


def collect_checks(connection):
    connection.execute(text("SET TRANSACTION READ ONLY"))
    server_version = connection.execute(text("SHOW server_version")).scalar_one_or_none()
    extension_rows = connection.execute(
        text(
            "SELECT extname, extversion FROM pg_extension "
            "WHERE extname IN ('vector', 'uuid-ossp', 'pg_trgm') ORDER BY extname"
        )
    ).mappings().all()
    extensions = {row["extname"]: row["extversion"] for row in extension_rows}
    revision = connection.execute(
        text("SELECT version_num FROM alembic_version LIMIT 1")
    ).scalar_one_or_none()
    column_rows = connection.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = ANY(:tables)"
        ),
        {"tables": list(REQUIRED_COLUMNS)},
    ).mappings().all()
    actual_columns = {}
    for row in column_rows:
        actual_columns.setdefault(row["table_name"], set()).add(row["column_name"])
    missing_extensions = sorted(REQUIRED_EXTENSIONS - set(extensions))
    missing_columns = {
        table_name: sorted(columns - actual_columns.get(table_name, set()))
        for table_name, columns in REQUIRED_COLUMNS.items()
        if columns - actual_columns.get(table_name, set())
    }
    revision_matches = revision == EXPECTED_ALEMBIC_HEAD
    status = "PASS" if not missing_extensions and not missing_columns and revision_matches else "FAIL"
    return {
        "status": status,
        "server_version": server_version,
        "extensions": extensions,
        "alembic_revision": revision,
        "expected_alembic_head": EXPECTED_ALEMBIC_HEAD,
        "revision_matches": revision_matches,
        "missing_extensions": missing_extensions,
        "missing_columns": missing_columns,
    }


def main():
    engine = None
    try:
        engine = create_engine(settings.DATABASE_URL, future=True)
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                report = collect_checks(connection)
            finally:
                transaction.rollback()
    except Exception as exc:
        report = {"status": "BLOCKED", "error_type": type(exc).__name__}
    finally:
        if engine is not None:
            engine.dispose()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the database checker unit tests**

```powershell
backend\.venv\Scripts\python.exe -m unittest discover -s backend\tests -p test_database_baseline.py -v
```

Expected: 4 tests pass without connecting to PostgreSQL.

- [ ] **Step 5: Commit the database checker**

```powershell
git add -- scripts/check_database_readonly.py backend/tests/test_database_baseline.py
git -c user.name="Codex Agent" -c user.email="codex-agent@local" commit -m "test(database): add read-only baseline checker" -m "AI-Agent: Codex`nAI-Client: Codex-Desktop`nTask-ID: development-baseline-001"
```

### Task 3: Create PowerShell Environment And Verification Scripts

**Files:**
- Create: `scripts/check_dev_environment.ps1`
- Create: `scripts/verify_baseline.ps1`
- Create: `scripts/tests/test_baseline_scripts.ps1`

**Interfaces:**
- Consumes: installed Python/NVM/PostgreSQL tools, ignored `.env`, and database checker from Task 2.
- Produces: console status lines, non-zero exit on required failures, and `docs/coordination/BASELINE.md`.

- [ ] **Step 1: Write the failing PowerShell contract test**

Create `scripts/tests/test_baseline_scripts.ps1`:

```powershell
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$checkPath = Join-Path $projectRoot 'scripts\check_dev_environment.ps1'
$verifyPath = Join-Path $projectRoot 'scripts\verify_baseline.ps1'

foreach ($path in @($checkPath, $verifyPath)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Missing baseline script: $path"
    }
}

$checkSource = Get-Content -Raw -Encoding UTF8 $checkPath
$verifySource = Get-Content -Raw -Encoding UTF8 $verifyPath

foreach ($required in @('3.11.4', '22.15.0', '10.9.2', 'DATABASE_URL', 'JWT_SECRET')) {
    if (-not $checkSource.Contains($required)) {
        throw "Environment checker missing contract: $required"
    }
}

foreach ($required in @('InstallDependencies', 'unittest discover', 'npm ci', 'check_database_readonly.py', 'BASELINE.md')) {
    if (-not $verifySource.Contains($required)) {
        throw "Baseline verifier missing contract: $required"
    }
}

foreach ($forbidden in @('DROP ', 'TRUNCATE ', 'DELETE ', 'alembic upgrade', 'DEEPSEEK_API_KEY=')) {
    if ($checkSource.ToUpperInvariant().Contains($forbidden.ToUpperInvariant()) -or
        $verifySource.ToUpperInvariant().Contains($forbidden.ToUpperInvariant())) {
        throw "Forbidden operation found: $forbidden"
    }
}

Write-Output 'baseline script contracts passed'
```

- [ ] **Step 2: Run the contract test and verify it fails**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_baseline_scripts.ps1
```

Expected: FAIL because the two implementation scripts do not exist.

- [ ] **Step 3: Implement `check_dev_environment.ps1`**

Create `scripts/check_dev_environment.ps1`:

```powershell
param([switch]$AsJson)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$results = [System.Collections.Generic.List[object]]::new()

function Add-CheckResult([string]$Name, [string]$Status, [string]$Detail) {
    $results.Add([pscustomobject]@{ name = $Name; status = $Status; detail = $Detail })
}

function Resolve-Python311 {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if (-not $launcher) { return $null }
    $candidate = & $launcher.Source -3.11 -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $candidate) { return $candidate.Trim() }
    return $null
}

function Resolve-Node22 {
    $node = Get-Command node -ErrorAction SilentlyContinue
    if ($node -and ((& $node.Source --version) -eq 'v22.15.0')) { return $node.Source }
    $nvmHome = $env:NVM_HOME
    if (-not $nvmHome) { $nvmHome = [Environment]::GetEnvironmentVariable('NVM_HOME', 'Machine') }
    if ($nvmHome) {
        $candidate = Join-Path $nvmHome 'v22.15.0\node.exe'
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

function Read-EnvFile([string]$Path) {
    $values = @{}
    foreach ($line in Get-Content -Encoding UTF8 $Path) {
        if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
        $parts = $line -split '=', 2
        $values[$parts[0].Trim()] = $parts[1].Trim()
    }
    return $values
}

$python = Resolve-Python311
if ($python) {
    $version = (& $python --version 2>&1 | Out-String).Trim()
    Add-CheckResult 'python' $(if ($version -eq 'Python 3.11.4') { 'PASS' } else { 'FAIL' }) $version
} else { Add-CheckResult 'python' 'BLOCKED' 'Python 3.11 was not resolved' }

$node = Resolve-Node22
if ($node) {
    Add-CheckResult 'node' 'PASS' ((& $node --version).Trim())
    $npm = Join-Path (Split-Path $node) 'npm.cmd'
    if (Test-Path -LiteralPath $npm) {
        $npmVersion = (& $npm --version).Trim()
        Add-CheckResult 'npm' $(if ($npmVersion -eq '10.9.2') { 'PASS' } else { 'FAIL' }) $npmVersion
    } else { Add-CheckResult 'npm' 'BLOCKED' 'npm.cmd was not found beside Node.js' }
} else { Add-CheckResult 'node' 'BLOCKED' 'Node.js 22.15.0 was not resolved' }

$psql = Get-Command psql -ErrorAction SilentlyContinue
if ($psql) { Add-CheckResult 'postgresql-client' 'PASS' ((& $psql.Source --version).Trim()) }
else { Add-CheckResult 'postgresql-client' 'BLOCKED' 'psql was not found' }
$service = Get-Service | Where-Object { $_.Name -match '^postgresql' } | Select-Object -First 1
if ($service) { Add-CheckResult 'postgresql-service' $(if ($service.Status -eq 'Running') { 'PASS' } else { 'FAIL' }) $service.Status.ToString() }
else { Add-CheckResult 'postgresql-service' 'BLOCKED' 'PostgreSQL service was not found' }

$venvPython = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython) {
    $venvVersion = (& $venvPython --version 2>&1 | Out-String).Trim()
    Add-CheckResult 'backend-venv' $(if ($venvVersion -match '^Python 3\.11\.') { 'PASS' } else { 'FAIL' }) $venvVersion
} else { Add-CheckResult 'backend-venv' 'BLOCKED' 'backend/.venv is missing' }

$frontendRequired = @(
    'frontend\node_modules\vite\package.json',
    'frontend\node_modules\vue\package.json',
    'frontend\node_modules\.bin\vite.cmd',
    'frontend\node_modules\.bin\vue-tsc.cmd'
)
$missingFrontend = @($frontendRequired | Where-Object { -not (Test-Path -LiteralPath (Join-Path $projectRoot $_)) })
Add-CheckResult 'frontend-dependencies' $(if ($missingFrontend.Count -eq 0) { 'PASS' } else { 'BLOCKED' }) $(if ($missingFrontend.Count -eq 0) { 'required packages present' } else { "missing $($missingFrontend.Count) required paths" })

$envPath = Join-Path $projectRoot 'backend\.env'
if (Test-Path -LiteralPath $envPath) {
    $envValues = Read-EnvFile $envPath
    $databaseOk = $envValues.ContainsKey('DATABASE_URL') -and $envValues['DATABASE_URL'] -and $envValues['DATABASE_URL'] -notmatch 'your_password'
    $jwtOk = $envValues.ContainsKey('JWT_SECRET') -and $envValues['JWT_SECRET'] -and $envValues['JWT_SECRET'] -notin @('change-me-in-production', 'your_jwt_secret_here')
    Add-CheckResult 'DATABASE_URL' $(if ($databaseOk) { 'PASS' } else { 'FAIL' }) $(if ($databaseOk) { 'configured' } else { 'missing or example value' })
    Add-CheckResult 'JWT_SECRET' $(if ($jwtOk) { 'PASS' } else { 'FAIL' }) $(if ($jwtOk) { 'configured' } else { 'missing or unsafe example value' })
} else {
    Add-CheckResult 'backend-env' 'BLOCKED' 'backend/.env is missing'
}

if ($AsJson) { $results | ConvertTo-Json -Depth 4 }
else { foreach ($result in $results) { Write-Output "[$($result.status)] $($result.name): $($result.detail)" } }
$hasRequiredFailure = @($results | Where-Object { $_.status -in @('FAIL', 'BLOCKED') }).Count -gt 0
exit $(if ($hasRequiredFailure) { 1 } else { 0 })
```

- [ ] **Step 4: Implement `verify_baseline.ps1`**

Create `scripts/verify_baseline.ps1`:

```powershell
param(
    [switch]$InstallDependencies,
    [switch]$SkipDatabase,
    [string]$ReportPath = 'docs/coordination/BASELINE.md'
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$results = [System.Collections.Generic.List[object]]::new()
$backendTestLabel = 'unittest discover'
$npmInstallLabel = 'npm ci'

function Add-Result([string]$Component, [string]$Status, [string]$Evidence) {
    $results.Add([pscustomobject]@{ component = $Component; status = $Status; evidence = $Evidence })
}

function Resolve-Python311 {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if (-not $launcher) { return $null }
    $candidate = & $launcher.Source -3.11 -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $candidate) { return $candidate.Trim() }
    return $null
}

function Resolve-Node22 {
    $node = Get-Command node -ErrorAction SilentlyContinue
    if ($node -and ((& $node.Source --version) -eq 'v22.15.0')) { return $node.Source }
    $nvmHome = $env:NVM_HOME
    if (-not $nvmHome) { $nvmHome = [Environment]::GetEnvironmentVariable('NVM_HOME', 'Machine') }
    if ($nvmHome) {
        $candidate = Join-Path $nvmHome 'v22.15.0\node.exe'
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

function Invoke-Recorded([string]$Name, [scriptblock]$Command) {
    try {
        $output = (& $Command 2>&1 | Out-String).Trim()
        $exitCode = $LASTEXITCODE
        if ($null -eq $exitCode) { $exitCode = 0 }
        Add-Result $Name $(if ($exitCode -eq 0) { 'PASS' } else { 'FAIL' }) "exit code $exitCode"
        return [pscustomobject]@{ exit_code = $exitCode; output = $output }
    } catch {
        Add-Result $Name 'BLOCKED' $_.Exception.GetType().Name
        return [pscustomobject]@{ exit_code = 1; output = '' }
    }
}

$python = Resolve-Python311
$node = Resolve-Node22
if (-not $python) { Add-Result 'python' 'BLOCKED' 'Python 3.11 was not resolved' }
if (-not $node) { Add-Result 'node' 'BLOCKED' 'Node.js 22.15.0 was not resolved' }
$npm = if ($node) { Join-Path (Split-Path $node) 'npm.cmd' } else { $null }
$venvPython = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'

if ($InstallDependencies -and $python -and $npm) {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Invoke-Recorded 'create-backend-venv' { & $python -m venv (Join-Path $projectRoot 'backend\.venv') } | Out-Null
    }
    if (Test-Path -LiteralPath $venvPython) {
        Invoke-Recorded 'upgrade-pip' { & $venvPython -m pip install --upgrade pip } | Out-Null
        Invoke-Recorded 'install-backend-dependencies' { & $venvPython -m pip install -r (Join-Path $projectRoot 'backend\requirements.txt') } | Out-Null
    }
    Push-Location (Join-Path $projectRoot 'frontend')
    try { Invoke-Recorded $npmInstallLabel { & $npm ci } | Out-Null }
    finally { Pop-Location }
}

$environmentOutput = (& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot 'scripts\check_dev_environment.ps1') -AsJson 2>&1 | Out-String).Trim()
$environmentExit = $LASTEXITCODE
try {
    $environmentResults = @($environmentOutput | ConvertFrom-Json)
    foreach ($item in $environmentResults) { Add-Result $item.name $item.status $item.detail }
} catch {
    Add-Result 'environment' 'BLOCKED' 'environment JSON could not be parsed'
    $environmentExit = 1
}

if ($environmentExit -eq 0) {
    Push-Location (Join-Path $projectRoot 'backend')
    try { Invoke-Recorded $backendTestLabel { & $venvPython -m unittest discover -s tests -v } | Out-Null }
    finally { Pop-Location }
    Push-Location (Join-Path $projectRoot 'frontend')
    try { Invoke-Recorded 'frontend-build' { & $npm run build } | Out-Null }
    finally { Pop-Location }
    if ($SkipDatabase) { Add-Result 'database-readonly' 'SKIP' 'disabled by -SkipDatabase' }
    else {
        $databaseRun = Invoke-Recorded 'database-readonly-command' { & $venvPython (Join-Path $projectRoot 'scripts\check_database_readonly.py') }
        if ($databaseRun.output) {
            try {
                $database = $databaseRun.output | ConvertFrom-Json
                $extensionEvidence = @($database.extensions.psobject.Properties | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join ', '
                Add-Result 'database-readonly' $database.status "PostgreSQL $($database.server_version); Alembic $($database.alembic_revision); $extensionEvidence"
            } catch { Add-Result 'database-readonly' 'BLOCKED' 'database JSON could not be parsed' }
        }
    }
}

foreach ($skip in @('external-llm', 'model-downloads', 'ocr-gpu', 'document-reindex', 'database-write-tests')) {
    Add-Result $skip 'SKIP' 'excluded by baseline safety policy'
}

$reportFile = if ([IO.Path]::IsPathRooted($ReportPath)) { $ReportPath } else { Join-Path $projectRoot $ReportPath }
$reportDirectory = Split-Path $reportFile
if (-not (Test-Path -LiteralPath $reportDirectory)) { New-Item -ItemType Directory -Path $reportDirectory | Out-Null }
$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add('# 开发与测试环境基线')
$lines.Add('')
$lines.Add('- Task-ID: `development-baseline-001`')
$lines.Add("- 执行时间: `$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')`")
$lines.Add('- Python: `3.11.4`')
$lines.Add('- Node.js: `22.15.0`')
$lines.Add('- npm: `10.9.2`')
$lines.Add('')
$lines.Add('| 组件 | 状态 | 证据 |')
$lines.Add('|---|---|---|')
foreach ($result in $results) { $lines.Add("| $($result.component) | $($result.status) | $($result.evidence) |") }
$lines.Add('')
$lines.Add('本报告不包含绝对路径、连接串或秘密值。')
[IO.File]::WriteAllLines($reportFile, $lines, [Text.UTF8Encoding]::new($false))

$hasFailure = @($results | Where-Object { $_.status -in @('FAIL', 'BLOCKED') }).Count -gt 0
foreach ($result in $results) { Write-Output "[$($result.status)] $($result.component): $($result.evidence)" }
exit $(if ($hasFailure) { 1 } else { 0 })
```

- [ ] **Step 5: Run the PowerShell contract test**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_baseline_scripts.ps1
```

Expected: `baseline script contracts passed` and exit `0`.

- [ ] **Step 6: Run non-installing environment check**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/check_dev_environment.ps1
```

Expected before dependency restoration: runtime checks pass; missing `backend/.venv` or incomplete `frontend/node_modules` is reported as `BLOCKED`. No installation or database mutation occurs.

- [ ] **Step 7: Commit the PowerShell scripts**

```powershell
git add -- scripts/check_dev_environment.ps1 scripts/verify_baseline.ps1 scripts/tests/test_baseline_scripts.ps1
git -c user.name="Codex Agent" -c user.email="codex-agent@local" commit -m "chore(development): add baseline verification scripts" -m "AI-Agent: Codex`nAI-Client: Codex-Desktop`nTask-ID: development-baseline-001"
```

### Task 4: Document The Portable Development Workflow

**Files:**
- Create: `docs/DEVELOPMENT.md`
- Reference: `README.md`
- Reference: `docs/DEPLOY.md`
- Reference: `docs/superpowers/specs/2026-07-27-development-baseline-design.md`

**Interfaces:**
- Consumes: script interfaces from Task 3.
- Produces: commands usable by Codex, Claude Code and a normal Windows terminal without personal paths.

- [ ] **Step 1: Create `docs/DEVELOPMENT.md`**

Write these sections with the exact commands shown:

````markdown
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
````

Use an outer four-backtick fence in the plan implementation so the nested command fences remain valid Markdown.

- [ ] **Step 2: Verify portability and secret safety**

```powershell
$path = 'docs/DEVELOPMENT.md'
$forbidden = Select-String -Path $path -Pattern 'C:\\Users\\|postgresql://|DEEPSEEK_API_KEY=|JWT_SECRET='
if ($forbidden) { $forbidden; throw 'Development guide contains machine-specific or secret content' }
```

Expected: no output.

- [ ] **Step 3: Commit the development guide**

```powershell
git add -- docs/DEVELOPMENT.md
git -c user.name="Codex Agent" -c user.email="codex-agent@local" commit -m "docs(development): add local workflow guide" -m "AI-Agent: Codex`nAI-Client: Codex-Desktop`nTask-ID: development-baseline-001"
```

### Task 5: Restore Project Dependencies And Record The Real Baseline

**Files:**
- Generate: `docs/coordination/BASELINE.md`
- Modify: `docs/coordination/ACTIVE_TASKS.md`
- Runtime only, ignored: `backend/.venv`
- Runtime only, ignored: `frontend/node_modules`

**Interfaces:**
- Consumes: verified scripts and the project owner's existing authorization to install project-local dependencies.
- Produces: actual baseline evidence and a review-ready task state.

- [ ] **Step 1: Confirm ignored runtime directories**

```powershell
git check-ignore -v backend/.venv frontend/node_modules backend/.env
```

Expected: all three paths are ignored. If any is not ignored, stop before installing.

- [ ] **Step 2: Restore dependencies and execute the baseline**

Network access is required. Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/verify_baseline.ps1 -InstallDependencies
```

Expected behavior:

- `backend/.venv` uses Python 3.11.4.
- Python requirements install only inside the virtual environment.
- `npm ci` rebuilds `frontend/node_modules` with Node.js 22.15.0/npm 10.9.2.
- Backend unit tests and frontend build run.
- Database checker executes only read-only SQL and rolls back its transaction.
- `docs/coordination/BASELINE.md` is generated even if a component fails, with exact non-sensitive evidence.

- [ ] **Step 3: Inspect the generated report and runtime status**

```powershell
Get-Content -Raw -Encoding UTF8 docs/coordination/BASELINE.md
git status --short
git check-ignore -v backend/.venv frontend/node_modules backend/.env
```

Expected: only `docs/coordination/BASELINE.md` is new among runtime outputs; ignored dependencies and `.env` do not appear in status.

- [ ] **Step 4: Re-run the baseline without installation**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/verify_baseline.ps1
```

Expected: no dependency installation occurs; results are reproducible. If required checks fail, record the exact `FAIL` or `BLOCKED` evidence and stop before marking the task approved.

- [ ] **Step 5: Update the active task to review state**

Change `development-baseline-001` in `docs/coordination/ACTIVE_TASKS.md`:

- `status: review`
- `review_handoff: generated`
- record implementation commit hashes;
- record actual `PASS`/`FAIL`/`SKIP`/`BLOCKED` summary;
- state that the branch is local and not pushed;
- include the standard cross-client review handoff for Claude Code.

- [ ] **Step 6: Commit the baseline report and review state**

```powershell
git add -- docs/coordination/BASELINE.md docs/coordination/ACTIVE_TASKS.md
git -c user.name="Codex Agent" -c user.email="codex-agent@local" commit -m "docs(development): record local baseline" -m "AI-Agent: Codex`nAI-Client: Codex-Desktop`nTask-ID: development-baseline-001"
```

### Task 6: Run Final Acceptance And Prepare Cross-Client Review

**Files:**
- Verify all task files from the File Map.

**Interfaces:**
- Consumes: all implementation commits and actual baseline output.
- Produces: a review handoff; no push or merge.

- [ ] **Step 1: Verify exact tracked scope**

```powershell
git diff --name-only main...HEAD
```

Expected tracked files:

```text
backend/tests/test_database_baseline.py
docs/DEVELOPMENT.md
docs/coordination/ACTIVE_TASKS.md
docs/coordination/BASELINE.md
scripts/check_database_readonly.py
scripts/check_dev_environment.ps1
scripts/tests/test_baseline_scripts.ps1
scripts/verify_baseline.ps1
```

- [ ] **Step 2: Run all static and unit checks**

```powershell
backend\.venv\Scripts\python.exe -m unittest discover -s backend\tests -v
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_baseline_scripts.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/verify_baseline.ps1
git diff main...HEAD --check
```

Expected: required checks pass. Declared heavy/external capabilities may be `SKIP`; they must not be described as passing.

- [ ] **Step 3: Verify no secrets or machine paths are tracked**

```powershell
$tracked = git diff --name-only main...HEAD
$forbidden = Select-String -Path $tracked -Pattern 'C:\\Users\\86182|postgresql://[^\s]+:[^\s]+@|DEEPSEEK_API_KEY=|JWT_SECRET='
if ($forbidden) { $forbidden; throw 'Tracked task files contain sensitive or machine-specific content' }
```

Expected: no output.

- [ ] **Step 4: Verify commit trailers and clean worktree**

```powershell
git log main..HEAD --format='%h | %an <%ae> | %s%n%b'
git status --short --branch
```

Expected: every implementation commit contains `AI-Agent: Codex`, `AI-Client: Codex-Desktop`, and `Task-ID: development-baseline-001`; worktree is clean.

- [ ] **Step 5: Generate the Claude Code review handoff**

First compute the exact commit range:

```powershell
$firstCommit = git rev-list --reverse main..HEAD | Select-Object -First 1
$lastCommit = git rev-parse HEAD
$commitRange = "$firstCommit..$lastCommit"
Write-Output $commitRange
```

Use the printed range in this handoff:

```text
请评审任务 development-baseline-001。

实现者：Codex
评审者：Claude Code
分支：codex/development-baseline-001
基线：main
提交：使用上一步输出的完整 commit range
方案：docs/superpowers/specs/2026-07-27-development-baseline-design.md
实施计划：docs/superpowers/plans/2026-07-27-development-baseline-implementation.md
验收结果：docs/coordination/BASELINE.md
重点检查：脚本是否可能修改系统或数据库、是否泄露秘密、版本发现是否可移植、失败/跳过状态是否准确。

只输出评审意见，不直接修改实现提交。
```

- [ ] **Step 6: Stop for owner review**

Report the task branch, worktree, commits, actual baseline status, skipped checks and review handoff. Explicitly state `尚未推送`. Do not push, merge, clean the worktree or delete the branch without separate authorization.
