param([switch]$UpdateExisting)

# Embedding'i haftada bir çalıştıran görev (kullanıcı kararı 2026-10-14: "hep çalışmasın, haftada bir gün yeter").
# Sürekli işçi `data\campaign\PAUSE_PC_EMBED` bayrağıyla kapalı tutulur; bu görev Pazar 03:00'te bir tur (`embed_chunks.py`,
# --loop olmadan) çalıştırır, düşük öncelikle, pencere açmadan. PC o saatte kapalıysa açıldığında çalışır (StartWhenAvailable).
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$py = Join-Path $root '.venv\Scripts\python.exe'
$conhost = Join-Path $env:SystemRoot 'System32\conhost.exe'
$cmd = Join-Path $env:SystemRoot 'System32\cmd.exe'
$taskName = 'NHR Legal AI Weekly Embedding'

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and -not $UpdateExisting) { throw "Görev zaten var: $taskName. Güncellemek için -UpdateExisting kullanın." }

$log = Join-Path $root 'data\logs\pc-embed-weekly.log'
$inner = "/c start `"`" /BELOWNORMAL /WAIT /B `"$py`" -X utf8 -u `"$root\scripts\embed_chunks.py`" >> `"$log`" 2>&1"
$action = New-ScheduledTaskAction -Execute $conhost -Argument ('--headless "' + $cmd + '" ' + $inner) -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 3am
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 24) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description 'Haftada bir (Pazar 03:00) yeni resmî kayıtların embeddinglerini üretir; sürekli işçi kapalıdır.' -Force | Out-Null
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
