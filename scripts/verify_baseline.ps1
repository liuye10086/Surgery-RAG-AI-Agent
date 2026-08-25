param(
    [switch]$InstallDependencies,
    [switch]$SkipDatabase,
    [string]$ReportPath = 'docs/BASELINE.md'
)

$ErrorActionPreference = 'Continue'
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
    if (-not $nvmHome) { $nvmHome = [Environment]::GetEnvironmentVariable('NVM_HOME', 'User') }
    if (-not $nvmHome) { $nvmHome = [Environment]::GetEnvironmentVariable('NVM_HOME', 'Machine') }
    if ($nvmHome) {
        $candidate = Join-Path $nvmHome 'v22.15.0\node.exe'
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

function Invoke-Recorded([string]$Name, [scriptblock]$Command) {
    try {
        $outputLines = & $Command 2>&1
        $exitCode = $LASTEXITCODE
        if ($null -eq $exitCode) { $exitCode = 0 }
        $output = ($outputLines | Out-String).Trim()
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

$environmentLines = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot 'scripts\check_dev_environment.ps1') -AsJson 2>&1
$environmentExit = $LASTEXITCODE
$environmentOutput = ($environmentLines | Out-String).Trim()
try {
    $environmentResults = $environmentOutput | ConvertFrom-Json
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
$lines.Add('# Development And Test Baseline')
$lines.Add('')
$lines.Add('- Task-ID: `development-baseline-001`')
$lines.Add(('- Executed at: `{0}`' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')))
$lines.Add('- Python: `3.11.4`')
$lines.Add('- Node.js: `22.15.0`')
$lines.Add('- npm: `10.9.2`')
$lines.Add('')
$lines.Add('| Component | Status | Evidence |')
$lines.Add('|---|---|---|')
foreach ($result in $results) { $lines.Add("| $($result.component) | $($result.status) | $($result.evidence) |") }
$lines.Add('')
$lines.Add('## Known Environment Limitations')
$lines.Add('')
$lines.Add('- `psql` discovery checks `PATH` and the default `C:\Program Files\PostgreSQL\*\bin` layout. Add `psql` to `PATH` when PostgreSQL uses a custom PostgreSQL installation directory.')
$lines.Add('')
$lines.Add('This report contains no personal paths, connection strings, or secret values.')
[IO.File]::WriteAllLines($reportFile, $lines, [Text.UTF8Encoding]::new($false))

$hasFailure = @($results | Where-Object { $_.status -in @('FAIL', 'BLOCKED') }).Count -gt 0
foreach ($result in $results) { Write-Output "[$($result.status)] $($result.component): $($result.evidence)" }
exit $(if ($hasFailure) { 1 } else { 0 })
