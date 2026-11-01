param([switch]$CheckOnly)

# Starts only the local application stack. Corpus ingestion and UYAP sessions are
# deliberately outside this task. Safe to run repeatedly after Windows sign-in.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$logs = Join-Path $root 'data\logs'
$python = Join-Path $root '.venv\Scripts\python.exe'
$node = 'C:\Program Files\nodejs\node.exe'
$vite = Join-Path $root 'web\node_modules\vite\bin\vite.js'
$dockerDesktop = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
$ollama = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
New-Item -ItemType Directory -Path $logs -Force | Out-Null

function Write-LocalLog([string]$message) {
    $line = "$(Get-Date -Format s) $message"
    Add-Content -LiteralPath (Join-Path $logs 'local-services.log') -Value $line -Encoding UTF8
    if ($CheckOnly) { Write-Output $line }
}

function Test-Http([string]$url) {
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 4
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400)
    } catch { return $false }
}

function Test-Port([int]$port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $pending = $client.BeginConnect('127.0.0.1', $port, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne(500)) { return $false }
        $client.EndConnect($pending)
        return $true
    } catch { return $false }
    finally { $client.Dispose() }
}

function Test-Exists([string]$path) {
    try { return [bool](Test-Path -LiteralPath $path -ErrorAction Stop) }
    catch { return $false }
}

Write-LocalLog 'startup check begin'

function Start-MissingService([string]$name, [string]$healthUrl, [int]$port,
                              [string]$executable, [string[]]$arguments, [string]$directory) {
    if (Test-Http $healthUrl) {
        if ($CheckOnly) { Write-LocalLog "$name healthy" }
        return
    }
    if (Test-Port $port) {
        Write-LocalLog "$name unhealthy, but port $port is occupied; leaving the existing process alone"
        return
    }
    if (-not (Test-Exists $executable)) {
        Write-LocalLog "$name executable missing: $executable"
        return
    }
    if ($CheckOnly) { Write-LocalLog "$name stopped"; return }
    try {
        $process = Start-Process -FilePath $executable -ArgumentList $arguments `
            -WorkingDirectory $directory -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $logs "$name.stdout.log") `
            -RedirectStandardError (Join-Path $logs "$name.stderr.log")
        Write-LocalLog "$name started (PID $($process.Id))"
    } catch { Write-LocalLog "$name start failed: $($_.Exception.Message)" }
}

function Test-Docker {
    try {
        & docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

# Ollama may already have its own autostart. Do not spawn a duplicate.
Start-MissingService 'ollama' 'http://127.0.0.1:11434/api/version' 11434 `
    $ollama @('serve') $root
Start-MissingService 'web-3000' 'http://127.0.0.1:3000/' 3000 `
    $node @($vite, '--host', '127.0.0.1', '--port', '3000', '--strictPort') (Join-Path $root 'web')

if (-not (Test-Docker)) {
    if ($CheckOnly) {
        Write-LocalLog 'Docker daemon stopped'
    } elseif (Test-Exists $dockerDesktop) {
        if (-not (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)) {
            try {
                Start-Process -FilePath $dockerDesktop -WindowStyle Hidden | Out-Null
                Write-LocalLog 'Docker Desktop started'
            } catch { Write-LocalLog "Docker Desktop start failed: $($_.Exception.Message)" }
        }
        # Docker Desktop needs time after sign-in. The scheduled task also retries
        # every five minutes if the daemon is not ready during this invocation.
        for ($attempt = 0; $attempt -lt 24 -and -not (Test-Docker); $attempt++) {
            Start-Sleep -Seconds 5
        }
    } else {
        Write-LocalLog "Docker Desktop missing: $dockerDesktop"
    }
}

if (Test-Docker) {
    try {
        $running = (& docker inspect -f '{{.State.Running}}' nhr-legal-ai-db 2>$null | Select-Object -First 1)
        if ($running -ne 'true') {
            if ($CheckOnly) { Write-LocalLog 'database container stopped' }
            else {
                & docker compose --project-directory $root up -d db 2>&1 | Out-Null
                if ($LASTEXITCODE -ne 0) { throw "docker compose exit code $LASTEXITCODE" }
                Write-LocalLog 'database container started'
            }
        } elseif ($CheckOnly) { Write-LocalLog 'database container running' }
    } catch { Write-LocalLog "database start failed: $($_.Exception.Message)" }
} elseif (-not $CheckOnly) {
    Write-LocalLog 'Docker daemon not ready; database will be retried at the next scheduled run'
}

Start-MissingService 'api-8766' 'http://127.0.0.1:8766/health' 8766 `
    $python @('-X', 'utf8', '-m', 'uvicorn', 'api.main:app', '--host', '127.0.0.1', '--port', '8766') $root
Start-MissingService 'corpus-3010' 'http://127.0.0.1:3010/health' 3010 `
    $python @('scripts\corpus_dashboard.py', '--host', '127.0.0.1', '--port', '3010') $root
Write-LocalLog 'startup check complete'
