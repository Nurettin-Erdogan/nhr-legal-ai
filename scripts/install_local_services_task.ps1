param([switch]$UpdateExisting)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script = Join-Path $PSScriptRoot 'ensure_local_services.ps1'
$conhost = Join-Path $env:SystemRoot 'System32\conhost.exe'
$powershell = (Get-Command powershell.exe).Source
$taskName = 'JurisAI Local Services'
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and -not $UpdateExisting) {
    throw "Task already exists: $taskName (use -UpdateExisting to replace it)"
}

$action = New-ScheduledTaskAction -Execute $conhost `
    -Argument ('--headless "' + $powershell + '" -NoProfile -ExecutionPolicy Bypass -File "' + $script + '"') `
    -WorkingDirectory $root
$triggers = @(
    (New-ScheduledTaskTrigger -AtLogOn -User $user),
    (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650))
)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -Priority 4
# -Priority 4 (normal): the default task priority (7) starts its children with below-normal CPU and low I/O/memory
# priority. Measured 2026-10-07: the API then answered a trivial 404 in 0.5-1.9 s instead of 2 ms.

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers `
    -Principal $principal -Settings $settings `
    -Description 'Starts the local JurisAI web, API, PostgreSQL container, Ollama and read-only corpus dashboard after sign-in; does not start ingestion or UYAP automation.' `
    -Force | Out-Null
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
