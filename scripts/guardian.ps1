# Bekci: sen yokken dis veri cekme kampanyalarini ve yerel Ollama'yi ayakta tutar, kampanya
# asamalarini sirayla ilerletir, hepsi bitince dogrulama + embedding'i acar.
#  - Yargitay/Danistay bosluk kampanyalari (backfill_campaign.py): olurse yeniden baslatir;
#    3 ust uste CAPTCHA ile durursa 20 dk sonra; "KAMPANYA TAMAM" ise siradaki asamaya gecer.
#  - Ollama (11434): yanit vermezse paralel modda yeniden baslatir.
#  - Iki kampanya da tum asamalari bitirince PAUSE_VERIFY ve PAUSE_EMBED silinir (nobetci
#    dogrulayicilari ve embedding kolunu baslatir).
# Yalniz baslatma/durdurma yapar; veri silmez, commit/push yapmaz, CAPTCHA/429 asmaz.
# Durdurma: data\campaign\GUARDIAN_STOP dosyasini olustur. Log: data\logs\guardian.log

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = "$root\.venv\Scripts\python.exe"
$logDir = "$root\data\logs"
$stateDir = "$root\data\campaign"
$log = "$logDir\guardian.log"
$stopFile = "$stateDir\GUARDIAN_STOP"
$statePath = "$stateDir\guardian-state.json"
New-Item -ItemType Directory -Force $logDir, $stateDir | Out-Null

function Write-Log($msg) { "$(Get-Date -Format s) $msg" | Add-Content -Path $log -Encoding utf8 }
function Find-Procs($pattern) {
  @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match $pattern -and $_.CommandLine -notmatch 'guardian' })
}

# Tek ornek
$others = @(Get-CimInstance Win32_Process -Filter "Name like 'powershell%' or Name like 'pwsh%'" |
  Where-Object { $_.CommandLine -match 'scripts.guardian\.ps1' -and $_.ProcessId -ne $PID })
if ($others.Count -gt 0) { Write-Log "baska bekci var (PID $($others[0].ProcessId)); cikiliyor"; exit 0 }

# Asamalar: her asama bir --from tarihi. Yeni asama = eski yillar; yillik "done.json" kayitlari
# tamamlanan yillari atlatir. Yargitay'da 2012 oncesi ~%99+ dolu oldugu icin 2022'de biter.
$phases = @{
  yargitay = @('2026-01-01', '2022-01-01')
  danistay = @('2024-01-01', '2012-01-01')
}
$state = @{ yargitay = 0; danistay = 0; finished = @{}; verifyOpened = $false }
if (Test-Path $statePath) {
  try {
    $saved = Get-Content $statePath -Raw | ConvertFrom-Json
    foreach ($k in 'yargitay','danistay') { if ($null -ne $saved.$k) { $state[$k] = [int]$saved.$k } }
    if ($saved.finished) { foreach ($p in $saved.finished.PSObject.Properties) { $state.finished[$p.Name] = [bool]$p.Value } }
    if ($saved.verifyOpened) { $state.verifyOpened = [bool]$saved.verifyOpened }
  } catch {}
}
function Save-State { ($state | ConvertTo-Json -Depth 4) | Set-Content -Path $statePath -Encoding utf8 }

$nextStart = @{}
$ollamaFails = 0
Write-Log "bekci basladi (PID $PID); asama durumu yargitay=$($state.yargitay) danistay=$($state.danistay)"

while (-not (Test-Path $stopFile)) {
  $now = Get-Date
  try {
    foreach ($src in 'yargitay','danistay') {
      if ($state.finished[$src]) { continue }
      if ((Find-Procs "backfill_campaign\.py --source $src").Count -gt 0) { continue }
      $out = "$logDir\gap2-$src.out.log"
      $tail = if (Test-Path $out) { (Get-Content $out -Tail 3 -ErrorAction SilentlyContinue) -join "`n" } else { '' }
      $idx = $state[$src]
      if ($tail -match 'KAMPANYA TAMAM') {
        if ($idx -lt $phases[$src].Count - 1) {
          $state[$src] = $idx + 1; Save-State
          Write-Log "$src asama $idx tamam; siradaki asama $($state[$src]) ($($phases[$src][$state[$src]]))"
          "== $src asama gecisi ==" | Add-Content -Path $out -Encoding utf8
        } else {
          $state.finished[$src] = $true; Save-State
          Write-Log "$src tum asamalar tamam"
        }
        continue
      }
      if ($nextStart[$src] -and $now -lt $nextStart[$src]) { continue }
      $wait = 60
      if ($tail -match 'kampanya durduruldu') { $wait = 1200 }   # 3 ust uste CAPTCHA: 20 dk sogut
      if ((Test-Path $out) -and (((Get-Date) - (Get-Item $out).LastWriteTime).TotalSeconds -lt $wait)) { continue }
      $env:PYTHONIOENCODING = 'utf-8'; $env:INGEST_SEEDS_AS_KNOWN = '1'
      $from = $phases[$src][$state[$src]]
      Start-Process -FilePath $py -WindowStyle Hidden -WorkingDirectory $root `
        -ArgumentList @('-u','scripts\backfill_campaign.py','--source',$src,'--from',$from,'--newest-first','--delay','5.5','--cooldown','90','--pause','3','--max-records','300') `
        -RedirectStandardOutput $out -RedirectStandardError "$logDir\gap2-$src.err.log"
      $env:INGEST_SEEDS_AS_KNOWN = $null
      $nextStart[$src] = $now.AddSeconds(120)
      Write-Log "$src kampanyasi baslatildi (from=$from, asama $($state[$src]))"
    }

    # Kampanyalar bitmeden PAUSE_VERIFY / PAUSE_EMBED kaybolursa geri koy (biri silerse sira bozulmasin)
    if (-not $state.verifyOpened) {
      foreach ($f in 'PAUSE_VERIFY','PAUSE_EMBED') {
        if (-not (Test-Path "$stateDir\$f")) {
          New-Item -ItemType File -Path "$stateDir\$f" -Force | Out-Null
          Write-Log "ALERT $f silinmisti, geri konuldu (kampanyalar suruyor)"
          Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match 'embed_chunks|verify_seeds' } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        }
      }
    }

    # Ollama
    $ok = $false
    try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/version' -UseBasicParsing -TimeoutSec 8; $ok = ($r.StatusCode -eq 200) } catch {}
    if ($ok) { $ollamaFails = 0 } else {
      $ollamaFails++
      if ($ollamaFails -ge 3) {
        $env:OLLAMA_NUM_PARALLEL = '4'; $env:OLLAMA_MAX_LOADED_MODELS = '2'
        Start-Process -FilePath "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" -ArgumentList 'serve' -WindowStyle Hidden `
          -RedirectStandardOutput "$logDir\ollama-serve.log" -RedirectStandardError "$logDir\ollama-serve.err.log"
        Write-Log "ALERT Ollama yanit vermiyordu, yeniden baslatildi"
        $ollamaFails = 0
      }
    }

    # Iki kampanya da bitti: dogrulama + embedding'i ac
    if ($state.finished['yargitay'] -and $state.finished['danistay'] -and -not $state.verifyOpened) {
      Remove-Item "$stateDir\PAUSE_VERIFY","$stateDir\PAUSE_EMBED" -ErrorAction SilentlyContinue
      $state.verifyOpened = $true; Save-State
      Write-Log "ALERT dis veri cekme kampanyalari bitti; PAUSE_VERIFY ve PAUSE_EMBED kaldirildi (dogrulama + embedding basliyor)"
    }
  } catch {
    Write-Log "hata: $($_.Exception.Message)"
  }
  Start-Sleep -Seconds 60
}
Write-Log "GUARDIAN_STOP bulundu, bekci kapandi"
