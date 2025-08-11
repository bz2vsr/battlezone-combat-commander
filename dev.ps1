#requires -Version 5.1

param(
  [ValidateSet('start','stop','status')]
  [string]$Action = 'start',
  [int]$WebPort = 5000,
  [switch]$NoDocker,
  [switch]$Reinstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = $PSScriptRoot
Set-Location $repoRoot

function Write-Info($msg) { Write-Host "[dev] $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "[dev] $msg" -ForegroundColor Yellow }

function Ensure-Venv {
  $py = Join-Path $repoRoot ".venv/Scripts/python.exe"
  if (-not (Test-Path $py)) {
    Write-Info "Creating virtual environment (.venv)"
    python -m venv .venv
  }
  if ($Reinstall -or -not (Test-Path (Join-Path $repoRoot ".venv/Lib/site-packages/flask"))) {
    Write-Info "Installing requirements"
    & $py -m pip install -r (Join-Path $repoRoot 'requirements.txt') --disable-pip-version-check
  }
}

function Ensure-DBSchema {
  $py = Join-Path $repoRoot ".venv/Scripts/python.exe"
  Write-Info "Ensuring database schema"
  & $py -c "from app.migrate import create_all, ensure_alter_tables; create_all(); ensure_alter_tables(); print('[schema] ready')"
}

function Try-Start-Docker {
  if ($NoDocker) { return }
  try { docker start bzcc-postgres | Out-Null } catch { Write-Warn 'Could not start docker container bzcc-postgres (ignored)' }
  try { docker start bzcc-redis | Out-Null } catch { Write-Warn 'Could not start docker container bzcc-redis (ignored)' }
}

function Start-Services {
  Ensure-Venv
  Try-Start-Docker
  Ensure-DBSchema

  $py = Join-Path $repoRoot ".venv/Scripts/python.exe"

  Write-Info "Starting worker"
  $scriptWorker = @"
Set-Location "$repoRoot"
& "$py" -m worker.runner
"@
  $workerJob = Start-Job -Name bzcc-worker -ScriptBlock { param($s) Invoke-Expression $s } -ArgumentList $scriptWorker

  Write-Info "Starting web (http://127.0.0.1:$WebPort/)"
  $scriptWeb = @"
Set-Location "$repoRoot"
& "$py" -m flask --app app.main run --port $WebPort --debug
"@
  $webJob = Start-Job -Name bzcc-web -ScriptBlock { param($s) Invoke-Expression $s } -ArgumentList $scriptWeb

  Start-Sleep -Seconds 1
  Write-Info "Jobs started:"
  Get-Job -Name bzcc-* | Select-Object Id, Name, State | Format-Table -AutoSize
  Write-Host ""
  Write-Host "Open: http://localhost:$WebPort/" -ForegroundColor Green
  Write-Host "API:  http://localhost:$WebPort/api/v1/sessions/current" -ForegroundColor Green
  Write-Host "Stop: .\dev.ps1 stop" -ForegroundColor Yellow
}

function Stop-Services {
  Write-Info "Stopping jobs"
  $jobs = Get-Job -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'bzcc-*' }
  if ($jobs) {
    $jobs | ForEach-Object { try { Stop-Job -Id $_.Id -ErrorAction SilentlyContinue } catch {} }
    $jobs | ForEach-Object { try { Remove-Job -Id $_.Id -Force -ErrorAction SilentlyContinue } catch {} }
  }
  # Fallback: kill stray processes by command line match
  $procs = Get-CimInstance Win32_Process | Where-Object {
    ($_.CommandLine -match 'worker.runner') -or ($_.CommandLine -match 'flask --app app.main run')
  }
  foreach ($p in $procs) { try { Stop-Process -Id $p.ProcessId -Force } catch {} }
  Write-Info "Services stopped"
}

function Status-Services {
  Write-Info "Job status"
  Get-Job -Name bzcc-* -ErrorAction SilentlyContinue | Select-Object Id, Name, State | Format-Table -AutoSize
}

switch ($Action) {
  'start' { Start-Services }
  'stop' { Stop-Services }
  'status' { Status-Services }
}


