# Suprevizor: uzun sureli kesintisiz calisma icin her dakika tum bilesenleri denetler ve olenleri
# yeniden baslatir. Yalniz baslatma/durdurma yapar; veri silmez, commit/push yapmaz.
#  - keep_awake (uyku engeli), sentinel (kaynak + kampanya yoneticisi), docker DB kabi, API (8766),
#    toplu parcalama iscileri, disk alani, parcalama bitince otomatik bakim (post_chunk_maintenance.py)
# Durdurma: data\campaign\SUPERVISOR_STOP dosyasini olustur.
# Alarm satirlari data\logs\supervisor.log icinde "ALERT" ile baslar.

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = 'utf-8'
$py = "$root\.venv\Scripts\python.exe"
$logDir = "$root\data\logs"
$stateDir = "$root\data\campaign"
$log = "$logDir\supervisor.log"
$stopFile = "$stateDir\SUPERVISOR_STOP"
$diskFlag = "$stateDir\DISK_LOW"
$maintDone = "$stateDir\MAINT_DONE"
New-Item -ItemType Directory -Force $logDir, $stateDir | Out-Null

function Write-Log($msg) { "$(Get-Date -Format s) $msg" | Add-Content -Path $log -Encoding ascii }
function Find-Procs($pattern, $name = 'python%') {
  @(Get-CimInstance Win32_Process -Filter "Name like '$name'" | Where-Object { $_.CommandLine -match $pattern })
}

# Tek ornek
$others = @(Get-CimInstance Win32_Process -Filter "Name like 'powershell%' or Name like 'pwsh%'" |
  Where-Object { $_.CommandLine -match 'scripts.supervisor\.ps1' -and $_.ProcessId -ne $PID })
if ($others.Count -gt 0) { Write-Log "baska suprevizor var (PID $($others[0].ProcessId)); cikiliyor"; exit 0 }

$apiFails = 0
$apiLastRestart = (Get-Date).AddMinutes(-10)
$chunkRestarts = 0
$maintStarted = $false
$chunkDone = $false
$loop = 0
Write-Log "suprevizor basladi (PID $PID)"

while (-not (Test-Path $stopFile)) {
  $loop++
  try {
    # 1) uyku engeli
    if ((Find-Procs 'keep_awake\.ps1' 'powershell%').Count -eq 0) {
      Start-Process powershell.exe -ArgumentList '-NoProfile','-WindowStyle','Hidden','-File',"$root\scripts\keep_awake.ps1" -WindowStyle Hidden
      Write-Log "keep_awake yoktu, baslatildi"
    }

    # 2) nobetci (7 kaynak kolu)
    if ((Find-Procs 'scripts.sentinel\.ps1' 'powershell%').Count -eq 0) {
      Start-Process powershell.exe -ArgumentList '-NoProfile','-WindowStyle','Hidden','-File',"$root\scripts\sentinel.ps1" -WindowStyle Hidden
      Write-Log "ALERT nobetci yoktu, yeniden baslatildi"
    }

    # Kampanyalari yalniz sentinel yonetir. Guardian ayni checkpoint ve surecleri
    # izlediginde iki yonetici birbirinin saglikli kampanyasini yeniden baslatabiliyordu.

    # 3) docker DB kabi
    $running = (& docker inspect -f '{{.State.Running}}' nhr-legal-ai-db 2>$null)
    if ($running -ne 'true') {
      Write-Log "ALERT DB kabi calismiyor, baslatiliyor"
      & docker start nhr-legal-ai-db 2>&1 | Out-Null
    }

    # 4) API (8766): 3 ust uste basarisizlik + 5 dk sogumadan sonra yeniden baslat
    $ok = $false
    try { $r = Invoke-WebRequest 'http://127.0.0.1:8766/health' -UseBasicParsing -TimeoutSec 15; $ok = ($r.StatusCode -eq 200) } catch { $ok = $false }
    if ($ok) { $apiFails = 0 } else { $apiFails++ }
    if ($apiFails -ge 3 -and ((Get-Date) - $apiLastRestart).TotalMinutes -ge 5) {
      Write-Log "ALERT API $apiFails kez yanit vermedi, yeniden baslatiliyor"
      Find-Procs 'uvicorn api\.main:app' | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
      Start-Sleep -Seconds 3
      Start-Process cmd.exe -ArgumentList '/c',"cd /d $root && .venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8766 >> data\logs\api-8766.log 2>&1" -WindowStyle Hidden
      $apiLastRestart = Get-Date
      $apiFails = 0
    }

    # 5) disk alani
    $freeGb = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
    if ($freeGb -lt 40) {
      if (-not (Test-Path $diskFlag)) {
        Set-Content $diskFlag "$(Get-Date -Format s) free=$freeGb GB"
        Write-Log "ALERT disk dusuk ($freeGb GB); parcalama durduruluyor"
      }
      Find-Procs 'chunk_bulk_seed' | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    } elseif ((Test-Path $diskFlag) -and $freeGb -gt 60) {
      Remove-Item $diskFlag -ErrorAction SilentlyContinue
      Write-Log "disk duzeldi ($freeGb GB); parcalamaya izin verildi"
    }

    # 6) toplu parcalama iscileri
    if (-not $chunkDone -and -not (Test-Path $diskFlag)) {
      $state = (& $py "$root\scripts\chunk_done.py" 2>$null | Select-Object -Last 1)
      if ($state -eq 'DONE') { $chunkDone = $true; Write-Log "ALERT parcalama TAMAM (12/12 shard)" }
      elseif ($state -eq 'NOT' -and (Find-Procs 'chunk_bulk_seed').Count -eq 0) {
        if ($chunkRestarts -ge 30) { Write-Log "ALERT parcalama 30 kez yeniden baslatildi, vazgeciliyor" }
        else {
          $chunkRestarts++
          Start-Process -FilePath $py -ArgumentList '-u','scripts\chunk_bulk_seed.py','--workers','12' -WindowStyle Hidden `
            -RedirectStandardOutput "$logDir\chunk-sup-$chunkRestarts.out.log" -RedirectStandardError "$logDir\chunk-sup-$chunkRestarts.err.log"
          Write-Log "ALERT parcalama iscileri yoktu, 12 iscide yeniden baslatildi (#$chunkRestarts)"
        }
      }
    }

    # 7) parcalama bitince tek seferlik bakim
    if ($chunkDone -and -not $maintStarted -and -not (Test-Path $maintDone)) {
      $maintStarted = $true
      Start-Process -FilePath $py -ArgumentList '-u','scripts\post_chunk_maintenance.py' -WindowStyle Hidden `
        -RedirectStandardOutput "$logDir\maintenance.out.log" -RedirectStandardError "$logDir\maintenance.err.log"
      Write-Log "ALERT bakim (VACUUM/ANALYZE + arama denemesi) baslatildi"
    }
    if ($chunkDone -and (Test-Path $maintDone) -and -not $script:maintReported) {
      $script:maintReported = $true
      Write-Log "ALERT bakim TAMAM"
    }

    if ($loop % 10 -eq 0) { Write-Log "nabiz ok (disk bos=$freeGb GB, api_hata=$apiFails)" }
  } catch {
    Write-Log "suprevizor dongu hatasi: $($_.Exception.Message)"
  }
  Start-Sleep -Seconds 60
}
Write-Log "SUPERVISOR_STOP bulundu, suprevizor kapandi"
