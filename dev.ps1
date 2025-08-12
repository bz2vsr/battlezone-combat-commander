#requires -Version 5.1

param(
  [ValidateSet('start','stop','status','restart')]
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
  $tmpDir = Join-Path $repoRoot "tmp"
  if (-not (Test-Path $tmpDir)) { New-Item -ItemType Directory -Path $tmpDir | Out-Null }

  Write-Info "Starting worker"
  $worker = Start-Process -FilePath $py -ArgumentList @("-m","worker.runner") -WorkingDirectory $repoRoot -PassThru -WindowStyle Hidden
  Set-Content -Path (Join-Path $tmpDir 'worker.pid') -Value $worker.Id

  Write-Info "Starting web (http://127.0.0.1:$WebPort/)"
  $web = Start-Process -FilePath $py -ArgumentList @("-c","from app.main import app, socketio; socketio.run(app, host='127.0.0.1', port=$WebPort)") -WorkingDirectory $repoRoot -PassThru -WindowStyle Hidden
  Set-Content -Path (Join-Path $tmpDir 'web.pid') -Value $web.Id

  Start-Sleep -Seconds 1
  Write-Info "Processes started:"
  Write-Host ("worker pid={0}  web pid={1}" -f $worker.Id, $web.Id)
  Write-Host
  Write-Host "Open: http://localhost:$WebPort/" -ForegroundColor Green
  Write-Host "API:  http://localhost:$WebPort/api/v1/sessions/current" -ForegroundColor Green
  Write-Host "Stop: .\dev.ps1 stop" -ForegroundColor Yellow
}

function Stop-Services {
  Write-Info "Stopping jobs"
  $tmpDir = Join-Path $repoRoot "tmp"
  $workerPidPath = Join-Path $tmpDir 'worker.pid'
  $webPidPath = Join-Path $tmpDir 'web.pid'
  if (Test-Path $workerPidPath) {
    $workerProcId = Get-Content $workerPidPath
    try { Stop-Process -Id $workerProcId -Force -ErrorAction SilentlyContinue } catch {}
    Remove-Item $workerPidPath -ErrorAction SilentlyContinue
  }
  if (Test-Path $webPidPath) {
    $webProcId = Get-Content $webPidPath
    try { Stop-Process -Id $webProcId -Force -ErrorAction SilentlyContinue } catch {}
    Remove-Item $webPidPath -ErrorAction SilentlyContinue
  }
  # Fallback: kill stray processes by command line match
  $procs = Get-CimInstance Win32_Process | Where-Object { ($_.CommandLine -match 'worker.runner') -or ($_.CommandLine -match 'flask --app app.main run') }
  foreach ($p in $procs) { try { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }
  Write-Info "Services stopped"
}

function Status-Services {
  Write-Info "Job status"
  $tmpDir = Join-Path $repoRoot "tmp"
  $workerPidPath = Join-Path $tmpDir 'worker.pid'
  $webPidPath = Join-Path $tmpDir 'web.pid'
  $workerPid = $null
  if (Test-Path $workerPidPath) { $workerPid = Get-Content $workerPidPath }
  $webPid = $null
  if (Test-Path $webPidPath) { $webPid = Get-Content $webPidPath }
  Write-Host ("worker pid={0}  web pid={1}" -f $workerPid, $webPid)
}

switch ($Action) {
  'start' { Start-Services }
  'stop' { Stop-Services }
  'status' { Status-Services }
  'restart' { Stop-Services; Start-Services }
}


