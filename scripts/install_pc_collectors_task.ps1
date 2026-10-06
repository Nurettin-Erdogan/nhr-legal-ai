param([switch]$UpdateExisting)

# `ensure_pc_collectors.ps1` betiğini 5 dakikada bir çalıştıran görev kurar (pencere açmaz). Oturum açılışı tetikleyicisi yönetici izni ister;
# 5 dakikalık yinelenen tetikleyici (StartWhenAvailable) açılıştan en geç 5 dakika sonra toplayıcıları başlatır.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script = Join-Path $PSScriptRoot 'ensure_pc_collectors.ps1'
$conhost = Join-Path $env:SystemRoot 'System32\conhost.exe'
$pwsh = (Get-Command powershell.exe).Source
$taskName = 'NHR Legal AI PC Collectors'

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and -not $UpdateExisting) { throw "Görev zaten var: $taskName. Güncellemek için -UpdateExisting kullanın." }

$action = New-ScheduledTaskAction -Execute $conhost `
    -Argument ('--headless "' + $pwsh + '" -NoProfile -ExecutionPolicy Bypass -File "' + $script + '"') -WorkingDirectory $root
$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $repeat `
    -Principal $principal -Settings $settings `
    -Description 'Yargıtay/Emsal toplayıcılarını canlı tutar; PC kapanıp açılınca kaldığı yerden devam eder.' -Force | Out-Null
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
