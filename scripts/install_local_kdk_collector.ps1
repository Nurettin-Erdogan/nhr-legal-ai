$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$script = Join-Path $PSScriptRoot 'collect_kdk_local.py'
$name = 'NHR Legal AI Local KDK Collector'

if (-not (Test-Path -LiteralPath $python)) { throw "Python bulunamadı: $python" }
if (-not (Test-Path -LiteralPath (Join-Path $root '.env'))) { throw 'Yerel .env bulunamadı.' }
if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
    throw "Görev zaten var: $name. Üzerine yazılmıyor."
}
$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + $script + '"') -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings `
    -Description 'KDK resmî kararlarını yerel erişim üzerinden checkpoint ile toplar.' | Out-Null
Get-ScheduledTask -TaskName $name | Select-Object TaskName, State
