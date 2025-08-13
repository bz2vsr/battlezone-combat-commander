#requires -Version 5.1

param(
  [ValidateSet('start','stop','status','restart')]
  [string]$Action = 'start',
  [int]$WebPort = 5000,
  [switch]$NoDocker,
  [switch]$Reinstall,
  [switch]$Realtime
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
  $dbu = $env:DATABASE_URL
  $envPath = Join-Path $repoRoot ".env"
  if (-not $dbu) {
    if (Test-Path $envPath) {
      Write-Info "No DATABASE_URL in shell; .env detected - the app will load it at runtime (see TECHNICAL_SPEC.md Section 10)."
    } else {
      Write-Warn "DATABASE_URL is not set and no .env found. Create a .env (see TECHNICAL_SPEC.md Section 10) or export DATABASE_URL."
    }
  }
  try {
    $code = 'from app.migrate import create_all, ensure_alter_tables; create_all(); ensure_alter_tables(); print("[schema] ready")'
    & $py -c $code
  } catch {
    Write-Warn "Schema initialization failed. Likely causes: Postgres not running or DATABASE_URL incorrect."
    if ($dbu) { Write-Warn ("Current DATABASE_URL: {0}" -f $dbu) }
    Write-Warn "If you use Docker Desktop, start it and ensure containers 'bzcc-postgres' and 'bzcc-redis' are running."
    Write-Warn "Alternatively, point DATABASE_URL at a native Postgres."
    throw
  }
}

function Try-Start-Docker {
  if ($NoDocker) { Write-Info 'NoDocker specified; skipping Docker checks'; return $true }
  # Detect Docker CLI
  $dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
  if (-not $dockerCmd) {
    Write-Warn 'Docker CLI not found. Install Docker Desktop: https://www.docker.com/products/docker-desktop'
    return $false
  }
  # Check engine availability
  $engineOk = $true
  try { docker info | Out-Null } catch { $engineOk = $false }
  if (-not $engineOk) {
    Write-Warn 'Docker Desktop appears to be stopped or the engine is unavailable. Start Docker Desktop, then rerun .\dev.ps1 start.'
    Write-Warn "Skipping container start; if DATABASE_URL points to Docker Postgres, schema init will fail."
    return $false
  }
  # Attempt to start expected containers; warn if missing
  try { docker start bzcc-postgres | Out-Null } catch { Write-Warn 'Could not start docker container bzcc-postgres (missing or error). You may need to create it.' }
  try { docker start bzcc-redis | Out-Null } catch { Write-Warn 'Could not start docker container bzcc-redis (missing or error). You may need to create it.' }
  return $true
}

function Start-Services {
  Ensure-Venv
  $dockerReady = Try-Start-Docker
  if (-not $NoDocker -and -not $dockerReady) {
    Write-Warn 'Docker Desktop is not running. Please start Docker Desktop and re-run .\dev.ps1 start.'
    return
  }
  Ensure-DBSchema

  $py = Join-Path $repoRoot ".venv/Scripts/python.exe"
  $tmpDir = Join-Path $repoRoot "tmp"
  if (-not (Test-Path $tmpDir)) { New-Item -ItemType Directory -Path $tmpDir | Out-Null }

  Write-Info "Starting worker"
  $workerOut = Join-Path $tmpDir 'worker.out.log'
  $workerErr = Join-Path $tmpDir 'worker.err.log'
  $worker = Start-Process -FilePath $py -ArgumentList @("-m","worker.runner") -WorkingDirectory $repoRoot -PassThru -WindowStyle Hidden -RedirectStandardOutput $workerOut -RedirectStandardError $workerErr
  Set-Content -Path (Join-Path $tmpDir 'worker.pid') -Value $worker.Id

  $webOut = Join-Path $tmpDir 'web.out.log'
  $webErr = Join-Path $tmpDir 'web.err.log'
  if ($Realtime) {
    # Ensure env for SocketIO
    if (-not $env:REDIS_URL) { $env:REDIS_URL = "redis://127.0.0.1:6379/0" }
    if (-not $env:WS_ALLOWED_ORIGINS) { $env:WS_ALLOWED_ORIGINS = "http://localhost:$WebPort" }
    $env:PORT = "$WebPort"
    Write-Info "Starting web (SocketIO) (http://127.0.0.1:$WebPort/)"
    $web = Start-Process -FilePath $py -ArgumentList @("-m","app.run_socketio") -WorkingDirectory $repoRoot -PassThru -WindowStyle Hidden -RedirectStandardOutput $webOut -RedirectStandardError $webErr
  } else {
    Write-Info "Starting web (Flask dev) (http://127.0.0.1:$WebPort/)"
    $web = Start-Process -FilePath $py -ArgumentList @("-m","flask","--app","app.main","run","--port","$WebPort") -WorkingDirectory $repoRoot -PassThru -WindowStyle Hidden -RedirectStandardOutput $webOut -RedirectStandardError $webErr
  }
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
  $procs = Get-CimInstance Win32_Process | Where-Object { ($_.CommandLine -match 'worker.runner') -or ($_.CommandLine -match 'flask --app app.main run') -or ($_.CommandLine -match 'app.run_socketio') }
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


