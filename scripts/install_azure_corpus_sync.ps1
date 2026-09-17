param(
    [ValidateSet('SixHours', 'Daily')]
    [string]$Frequency = 'SixHours',
    [switch]$UpdateExisting
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$sync = Join-Path $PSScriptRoot 'sync_azure_corpus.py'
$taskName = 'NHR Legal AI Azure Corpus Sync'

if (-not (Test-Path -LiteralPath $python)) { throw "Python bulunamadı: $python" }
if (-not (Test-Path -LiteralPath (Join-Path $root '.env'))) { throw 'Yerel .env bulunamadı.' }
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    if (-not $UpdateExisting) {
        throw "Görev zaten var: $taskName. Güncellemek için -UpdateExisting kullanın."
    }
    if ($existing.Actions.Count -ne 1 -or
        $existing.Actions[0].Execute -ne $python -or
        -not $existing.Actions[0].Arguments.Contains($sync)) {
        throw 'Aynı adlı görevin eylemi farklı; güvenli güncelleme reddedildi.'
    }
}

$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + $sync + '" --embed-limit 500') -WorkingDirectory $root
if ($Frequency -eq 'SixHours') {
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) `
        -RepetitionInterval (New-TimeSpan -Hours 6) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
} else {
    $trigger = New-ScheduledTaskTrigger -Daily -At 03:00
}
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings `
    -Description 'Resmî hukuk korpusunu Azure üzerinden yerel PostgreSQL ile birleştirir.' `
    -Force | Out-Null
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
