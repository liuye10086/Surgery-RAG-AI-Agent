$ErrorActionPreference = 'Stop'

$projectName = 'surgery-rag-agent-test'
$composeFile = Join-Path $PSScriptRoot '..\docker-compose.test.yml'
$backendRoot = Join-Path $PSScriptRoot '..\backend'
$frontendRoot = Join-Path $PSScriptRoot '..\frontend'
$processes = @()

try {
    docker compose -p $projectName -f $composeFile up -d --wait
    $env:TEST_DATABASE_URL = 'postgresql://surgery_test:surgery_test@127.0.0.1:55432/surgery_rag_operator_test'
    $env:DATABASE_URL = $env:TEST_DATABASE_URL

    $backend = Start-Process -FilePath 'python' -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory $backendRoot -WindowStyle Hidden -PassThru
    $processes += $backend
    $frontend = Start-Process -FilePath 'npm' -ArgumentList 'run','dev','--','--host','127.0.0.1' -WorkingDirectory $frontendRoot -WindowStyle Hidden -PassThru
    $processes += $frontend

    $deadline = (Get-Date).AddSeconds(60)
    do {
        try { Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing | Out-Null; break } catch { Start-Sleep -Seconds 1 }
    } while ((Get-Date) -lt $deadline)
    if ((Get-Date) -ge $deadline) { throw 'backend health check timed out' }

    Set-Location $backendRoot
    pytest tests/e2e/test_operator_case_workspace.py -q
}
finally {
    foreach ($process in $processes) {
        if ($process -and !$process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    }
    docker compose -p $projectName -f $composeFile down
}
