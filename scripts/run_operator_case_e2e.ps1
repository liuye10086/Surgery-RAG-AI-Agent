param([string]$TestDatabaseUrl = $env:TEST_DATABASE_URL, [string]$RendererManifest = $env:REPORT_TEST_RENDERER_MANIFEST)
$ErrorActionPreference = 'Stop'
$projectName = 'surgery-rag-agent-test'
$composeFile = Join-Path $PSScriptRoot '..\docker-compose.test.yml'
$startedDocker = $false
$previousUrl = $env:TEST_DATABASE_URL
$previousManifest = $env:REPORT_TEST_RENDERER_MANIFEST
$previousLocation = Get-Location
try {
    if (-not $RendererManifest -or -not (Test-Path -LiteralPath $RendererManifest -PathType Leaf)) { throw 'Build and supply REPORT_TEST_RENDERER_MANIFEST before browser verification' }
    $env:REPORT_TEST_RENDERER_MANIFEST = $RendererManifest
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
    $env:REPORT_TEST_RENDERER_MANIFEST = $previousManifest
    Set-Location $previousLocation
    if ($startedDocker) { docker compose -p $projectName -f $composeFile down }
}
