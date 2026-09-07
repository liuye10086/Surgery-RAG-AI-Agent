param([string]$TestDatabaseUrl = $env:TEST_DATABASE_URL)
$ErrorActionPreference = 'Stop'
$projectName = 'surgery-rag-agent-test'
$composeFile = Join-Path $PSScriptRoot '..\docker-compose.test.yml'
$startedDocker = $false
$previousUrl = $env:TEST_DATABASE_URL
$previousLocation = Get-Location
try {
    if (-not $TestDatabaseUrl) {
        docker compose -p $projectName -f $composeFile up -d --wait
        if ($LASTEXITCODE -ne 0) { throw 'isolated Docker database failed to start' }
        $startedDocker = $true
        $TestDatabaseUrl = 'postgresql://surgery_test:surgery_test@127.0.0.1:55432/surgery_rag_operator_test'
    }
    $env:TEST_DATABASE_URL = $TestDatabaseUrl
    Set-Location (Join-Path $PSScriptRoot '..')
    python -X utf8 scripts/run_operator_report_e2e.py
    if ($LASTEXITCODE -ne 0) { throw 'operator E2E verification failed' }
}
finally {
    $env:TEST_DATABASE_URL = $previousUrl
    Set-Location $previousLocation
    if ($startedDocker) { docker compose -p $projectName -f $composeFile down }
}
