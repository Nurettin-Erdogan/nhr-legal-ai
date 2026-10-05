param(
    # Yedeklerin yazılacağı klasör. Mümkünse ayrı/harici ve şifreli bir disk; müvekkil verisi içerir (KVKK).
    [string]$Destination = '',
    [int]$Keep = 14,
    [string]$At = '02:30',
    [switch]$UpdateExisting
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$backup = Join-Path $PSScriptRoot 'backup_user_data.py'
$conhost = Join-Path $env:SystemRoot 'System32\conhost.exe'
$taskName = 'NHR Legal AI User Data Backup'

if (-not (Test-Path -LiteralPath $python)) { throw "Python bulunamadı: $python" }
if (-not (Test-Path -LiteralPath (Join-Path $root '.env'))) { throw 'Yerel .env bulunamadı.' }
$arguments = '--headless "' + $python + '" "' + $backup + '" --verify --keep ' + $Keep
if ($Destination) {
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $arguments += ' --dest "' + $Destination + '"'
}
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and -not $UpdateExisting) {
    throw "Görev zaten var: $taskName. Güncellemek için -UpdateExisting kullanın."
}

$action = New-ScheduledTaskAction -Execute $conhost -Argument $arguments -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
# Bilgisayar o saatte kapalıysa açılınca çalışır; çakışan turlar atlanır.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description 'Kullanıcı verisini (hesap, müvekkil, dava, belge, sohbet) ve yüklenen dosyaları yedekler, geri yüklemeyi doğrular.' -Force | Out-Null
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
