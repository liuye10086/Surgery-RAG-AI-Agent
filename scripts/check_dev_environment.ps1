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
    if (-not $nvmHome) { $nvmHome = [Environment]::GetEnvironmentVariable('NVM_HOME', 'User') }
    if (-not $nvmHome) { $nvmHome = [Environment]::GetEnvironmentVariable('NVM_HOME', 'Machine') }
    if ($nvmHome) {
        $candidate = Join-Path $nvmHome 'v22.15.0\node.exe'
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

function Resolve-Psql {
    $psql = Get-Command psql -ErrorAction SilentlyContinue
    if ($psql) { return $psql.Source }
    $candidate = Get-ChildItem 'C:\Program Files\PostgreSQL\*\bin\psql.exe' -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        Select-Object -First 1
    if ($candidate) { return $candidate.FullName }
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

$psql = Resolve-Psql
if ($psql) { Add-CheckResult 'postgresql-client' 'PASS' ((& $psql --version).Trim()) }
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
