# Task Scheduler runs this periodically. It only starts the collector sentinel
# when no sentinel is running; it never bypasses a deliberate SENTINEL_STOP.
$root = Split-Path -Parent $PSScriptRoot
$sentinel = Join-Path $PSScriptRoot 'sentinel.ps1'
$stopFile = Join-Path $root 'data\campaign\SENTINEL_STOP'
$logDir = Join-Path $root 'data\logs'
if (Test-Path -LiteralPath $stopFile) { exit 0 }

try {
  $running = @(Get-CimInstance Win32_Process -Filter "Name like 'powershell%' or Name like 'pwsh%'" -ErrorAction Stop |
    Where-Object { $_.CommandLine -match 'scripts[\\/]sentinel\.ps1' })
} catch {
  # Do not risk launching a duplicate collector when process inventory fails.
  exit 1
}
if ($running.Count -gt 0) { exit 0 }

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -WorkingDirectory $root `
  -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', "`"$sentinel`"") `
  -RedirectStandardOutput (Join-Path $logDir 'sentinel-watchdog.out.log') `
  -RedirectStandardError (Join-Path $logDir 'sentinel-watchdog.err.log')
"$(Get-Date -Format s) sentinel yeniden başlatıldı" | Add-Content -Path (Join-Path $logDir 'sentinel-watchdog.log') -Encoding utf8
