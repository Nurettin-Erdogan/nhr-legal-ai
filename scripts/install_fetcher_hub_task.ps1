param([switch]$UpdateExisting)

# `fetcher_hub.py run` betiğini 10 dakikada bir çalıştıran görev kurar (pencere açmaz): çekici düğümlerden (AWS, Azure)
# sonuçları alır, PC veritabanına işler, yeni iş gönderir. PC portala istek atmaz. PC uyurken düğümler çalışmaya devam eder;
# uyanınca biriken sonuçlar ilk çalışmada alınır (uyanma tetikleyicisi, 30 sn gecikme).
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
$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 3650)
$eventClass = Get-CimClass -ClassName MSFT_TaskEventTrigger -Namespace Root/Microsoft/Windows/TaskScheduler
$resume = New-CimInstance -CimClass $eventClass -ClientOnly
$resume.Subscription = '<QueryList><Query Id="0" Path="System"><Select Path="System">*[System[Provider[@Name=''Microsoft-Windows-Power-Troubleshooter''] and EventID=1]]</Select></Query></QueryList>'
$resume.Enabled = $true
$resume.Delay = 'PT30S'
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($repeat, $resume) `
    -Principal $principal -Settings $settings `
    -Description 'Çekici düğümlerden (AWS, Azure) resmî metinleri alır, seedleri doğrular, yeni iş gönderir.' -Force | Out-Null
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
