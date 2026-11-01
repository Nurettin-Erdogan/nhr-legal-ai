param([switch]$UpdateExisting)

# `fetcher_hub.py run` betiğini GÜNDE BİR (09:00) çalıştıran görev kurar (pencere açmaz; kullanıcı 2026-10-14: "10 dk'da bir
# çekmesin, günde bir kere"). Çekici düğümlerden (AWS, Azure) sonuçları alır, PC veritabanına işler, düğümlere ~2,5 günlük iş
# bırakır. PC portala istek atmaz. PC o saatte kapalıysa açıldığında bir kez çalışır (StartWhenAvailable).
# Geçici durdurma: data\campaign\PAUSE_FETCHER_HUB dosyası varken betik hiçbir şey yapmaz.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$py = Join-Path $root '.venv\Scripts\python.exe'
$conhost = Join-Path $env:SystemRoot 'System32\conhost.exe'
$cmd = Join-Path $env:SystemRoot 'System32\cmd.exe'
$taskName = 'NHR Legal AI Fetcher Hub'

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and -not $UpdateExisting) { throw "Görev zaten var: $taskName. Güncellemek için -UpdateExisting kullanın." }

$log = Join-Path $root 'data\logs\fetcher-hub.out.log'
$inner = "/c if not exist `"$root\data\campaign\PAUSE_FETCHER_HUB`" `"$py`" -X utf8 `"$root\scripts\fetcher_hub.py`" run >> `"$log`" 2>&1"
$action = New-ScheduledTaskAction -Execute $conhost -Argument ('--headless "' + $cmd + '" ' + $inner) -WorkingDirectory $root
$daily = New-ScheduledTaskTrigger -Daily -At 9am
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $daily `
    -Principal $principal -Settings $settings `
    -Description 'Çekici düğümlerden (AWS, Azure) resmî metinleri alır, seedleri doğrular, yeni iş gönderir.' -Force | Out-Null
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
