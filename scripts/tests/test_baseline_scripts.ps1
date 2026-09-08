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

foreach ($required in @(
    'InstallDependencies',
    '-m pytest',
    "'tests'",
    "'..\scripts\tests'",
    "'--ignore=tests/integration'",
    "'--ignore=tests/e2e'",
    'npm ci',
    "npm run test:unit",
    "npm run test:contracts",
    'check_database_readonly.py',
    "'--phase'",
    "'postflight'",
    'BASELINE.md'
)) {
    if (-not $verifySource.Contains($required)) {
        throw "Baseline verifier missing contract: $required"
    }
}

if ($verifySource.Contains('unittest discover')) {
    throw 'Baseline verifier still uses unittest discovery, which misses pytest tests'
}

foreach ($required in @(
    "`$ErrorActionPreference = 'Continue'",
    '$environmentResults = $environmentOutput | ConvertFrom-Json',
    'Known Environment Limitations',
    'custom PostgreSQL installation directory',
    'no personal paths, connection strings, or secret values'
)) {
    if (-not $verifySource.Contains($required)) {
        throw "Baseline verifier missing PowerShell 5.1 behavior contract: $required"
    }
}

foreach ($forbidden in @('DROP ', 'TRUNCATE ', 'DELETE ', 'alembic upgrade', 'DEEPSEEK_API_KEY=')) {
    if ($checkSource.ToUpperInvariant().Contains($forbidden.ToUpperInvariant()) -or
        $verifySource.ToUpperInvariant().Contains($forbidden.ToUpperInvariant())) {
        throw "Forbidden operation found: $forbidden"
    }
}

Write-Output 'baseline script contracts passed'
