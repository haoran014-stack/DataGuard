[CmdletBinding()]
param(
    [switch]$Cleanup,
    [switch]$OverwriteArtifacts,
    [ValidateRange(1,65535)]
    [int]$ApiPort = 8000
)

$ErrorActionPreference = 'Stop'
$env:DATAGUARD_API_PORT = [string]$ApiPort
$apiBaseUri = "http://127.0.0.1:$ApiPort"
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root

function Invoke-DataGuard([string[]]$Arguments) {
    & .\.venv\Scripts\python -m dataguard @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'DataGuard command failed.' }
}

if ($Cleanup) {
    docker compose down
    Write-Host 'Stopped containers. The named PostgreSQL volume was preserved; use down -v only by explicit operator choice.'
    exit 0
}

foreach ($command in @('docker', 'ollama')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "Required local command is unavailable: $command" }
}
if (-not (Test-Path '.env')) { throw '.env is required by Compose only; create it from .env.example.' }
if ($env:DATAGUARD_PROFILE -ne 'evidence' -or $env:DATAGUARD_STORAGE_BACKEND -ne 'postgresql' -or
    [string]::IsNullOrWhiteSpace($env:DATAGUARD_DATABASE_DSN)) {
    throw '.env is not imported into this process. Separately set evidence profile, PostgreSQL backend, and local DSN without printing them.'
}
$env:DATAGUARD_EXPERIMENT_MANIFEST_PATH = 'artifacts/runtime/experiment-manifest.v1.json'
$tags = @(ollama list | Select-Object -Skip 1 | ForEach-Object { ($_ -split '\s+')[0] })
foreach ($tag in @('qwen2.5:3b-instruct','qwen3-embedding:0.6b')) {
    if ($tag -notin $tags) { throw "Required Ollama model is absent: $tag. The script never pulls models." }
}

Invoke-DataGuard @('validate')
$indexPath = 'artifacts/runtime/vector-index.v1.json'
$manifestPath = 'artifacts/runtime/experiment-manifest.v1.json'
$indexExists = Test-Path -LiteralPath $indexPath -PathType Leaf
$manifestExists = Test-Path -LiteralPath $manifestPath -PathType Leaf
if ($OverwriteArtifacts) {
    Invoke-DataGuard @('build-index', '--overwrite')
    Invoke-DataGuard @('generate-manifest', '--overwrite')
} elseif ($indexExists -and $manifestExists) {
    Write-Host 'Prepared index and manifest already exist; verifying without replacement.'
} elseif (-not $indexExists -and -not $manifestExists) {
    Invoke-DataGuard @('build-index')
    Invoke-DataGuard @('generate-manifest')
} else {
    throw 'Exactly one prepared artifact exists. Inspect it manually or rerun with -OverwriteArtifacts.'
}
Invoke-DataGuard @('verify-artifacts')
docker compose config --quiet
docker compose up -d --build

$health = $null
$healthDeadline = (Get-Date).AddMinutes(2)
do {
    if ((Get-Date) -gt $healthDeadline) { throw 'API health deadline exceeded.' }
    try { $health = Invoke-RestMethod "$apiBaseUri/health" -TimeoutSec 5 } catch { Start-Sleep -Seconds 2 }
} while ($null -eq $health)
if ($health.status -eq 'unhealthy') { throw 'DataGuard API is unhealthy.' }
foreach ($mode in @('baseline','guarded')) {
    $chatBody = @{subject_id='guest-01';question='What is the synthetic public fact?';mode=$mode;corpus_version='synthetic-v1'} | ConvertTo-Json -Compress
    Invoke-RestMethod "$apiBaseUri/v1/chat" -Method Post -ContentType 'application/json' -Body $chatBody -TimeoutSec 180 | Out-Null
}
$run = Invoke-RestMethod "$apiBaseUri/v1/evaluation-runs" -Method Post -ContentType 'application/json' -Body '{"scenario_set_version":"synthetic-v1","profile":"evidence"}' -TimeoutSec 30
$evaluationDeadline = (Get-Date).AddMinutes(45)
do {
    if ((Get-Date) -gt $evaluationDeadline) { throw 'Evaluation polling deadline exceeded.' }
    Start-Sleep -Seconds 2
    $state = Invoke-RestMethod "$apiBaseUri/v1/evaluation-runs/$($run.run_id)" -TimeoutSec 30
} while ($state.status -in @('queued','running'))
if ($state.status -ne 'completed') { throw "Evaluation ended without a report: $($state.status)" }
Invoke-WebRequest "$apiBaseUri/v1/reports/$($run.run_id)?format=json" -OutFile 'artifacts/report.json' -TimeoutSec 30
Invoke-WebRequest "$apiBaseUri/v1/reports/$($run.run_id)?format=html" -OutFile 'artifacts/report.html' -TimeoutSec 30
Invoke-RestMethod "$apiBaseUri/v1/audit-events?run_id=$($run.run_id)&limit=200" -TimeoutSec 30 | Out-Null
Write-Host 'Demo completed. No model was pulled and no database volume was deleted.'
