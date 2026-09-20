# Nöbetçi: 7 resmî kaynak kolunu (Yargıtay, Danıştay, AYM, KDK, Mevzuat, Resmî Gazete
# + MBS doğrulama) ölürse yeniden başlatır. Yalnız resmî portal adaptörleri çalıştırılır;
# CAPTCHA aşılmaz, kampanya kendi beklemesini yapar. Tek örnek çalışır.
#
# Başlatma (kabuktan bağımsız):
#   Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
#     CommandLine = 'powershell.exe -NoProfile -WindowStyle Hidden -File C:\...\scripts\sentinel.ps1' }
# Durdurma: data\campaign\SENTINEL_STOP dosyasını oluştur.

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = 'utf-8'
$env:MEVZUAT_VERIFY_INLINE = 'false'
$py = "$root\.venv\Scripts\python.exe"
$logDir = "$root\data\logs"
$stateDir = "$root\data\campaign"
$log = "$logDir\sentinel.log"
$stopFile = "$stateDir\SENTINEL_STOP"
$statePath = "$stateDir\sentinel-state.json"
New-Item -ItemType Directory -Force $logDir, $stateDir | Out-Null

function Write-Log($msg) { "$(Get-Date -Format s) $msg" | Add-Content -Path $log -Encoding utf8 }

function Get-Procs($pattern) {
  @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -match $pattern -and $_.CommandLine -notmatch 'sentinel' })
}

# Tek örnek koruması
$me = $PID
$others = @(Get-CimInstance Win32_Process -Filter "Name like 'powershell%' or Name like 'pwsh%'" |
  Where-Object { $_.CommandLine -match 'scripts.sentinel\.ps1' -and $_.ProcessId -ne $me })
if ($others.Count -gt 0) { Write-Log "başka nöbetçi zaten çalışıyor (PID $($others[0].ProcessId)); çıkılıyor"; exit 0 }

# Kampanya kuyrukları: sırayla biter, sonuncusu tüm daireleri kapsar (en yeniden eskiye).
$queues = @{
  yargitay = @('Hukuk Genel Kurulu', 'Ceza Genel Kurulu', '')
  danistay = @('Vergi Dava Daireleri Kurulu', 'İdari Dava Daireleri Kurulu', '')
}
$state = @{ yargitay = 0; danistay = 0 }
if (Test-Path $statePath) {
  try { $saved = Get-Content $statePath -Raw | ConvertFrom-Json; foreach ($k in $state.Keys.Clone()) { if ($null -ne $saved.$k) { $state[$k] = [int]$saved.$k } } } catch {}
}
function Save-State { ($state | ConvertTo-Json) | Set-Content -Path $statePath -Encoding utf8 }

# Worker kolları: ad -> arama deseni + başlatma argümanları
$workers = @(
  @{ name = 'aym';       pattern = 'worker\.runner backfill --source aym';     args = @('-u','-m','worker.runner','backfill','--source','aym','--no-incremental','--no-embed') },
  @{ name = 'kdk';       pattern = 'worker\.runner backfill --source kdk';     args = @('-u','-m','worker.runner','backfill','--source','kdk','--no-incremental','--no-embed') },
  @{ name = 'mevzuat';   pattern = 'worker\.runner backfill --source mevzuat'; args = @('-u','-m','worker.runner','backfill','--source','mevzuat','--no-incremental','--no-embed') },
  # Yeni doğrulanan/eklenen resmî kayıtları sürekli embedding'e çevirir (yerel Ollama, hafif turlar).
  @{ name = 'embed';     pattern = 'embed_chunks\.py';                           args = @('-X','utf8','-u','scripts\embed_chunks.py','--batch','64','--loop') },
  @{ name = 'dogrulama'; pattern = 'worker\.verify_loop';                      args = @('-u','-m','worker.verify_loop') },
  # Uc uncu taraf kayit dogrulayicisi: kimlikle dogrudan ceker, hizini kendi ayarlar (429/CAPTCHA'da yavaslar).
  # CAPTCHA'da 3 kez ust uste durursa 20 dk sonra yeniden denenir.
  @{ name = 'dogrula-yargitay'; pattern = 'verify_seeds\.py --source yargitay'; backoff = 1200; args = @('-u','scripts\verify_seeds.py','--source','yargitay') },
  @{ name = 'dogrula-danistay'; pattern = 'verify_seeds\.py --source danistay'; backoff = 1200; args = @('-u','scripts\verify_seeds.py','--source','danistay') }
)
$pauseFile = "$stateDir\PAUSE_CAMPAIGNS"   # varsa arama-tabanli kampanyalar baslatilmaz (dogrulayici ayni portali kullanir)
$pauseVerifyFile = "$stateDir\PAUSE_VERIFY"   # varsa dogrulayicilar baslatilmaz (boslugu kapatan kampanya portali kullanir)
$pauseEmbedFile = "$stateDir\PAUSE_EMBED"    # varsa embedding kolu baslatilmaz
$nextStart = @{}   # kol adı -> en erken yeniden başlatma zamanı
$launchedAt = @{}
$restarts = @{}

Write-Log "nöbetçi başladı (PID $me)"
while (-not (Test-Path $stopFile)) {
  $now = Get-Date

  foreach ($w in $workers) {
    if ((Get-Procs $w.pattern).Count -gt 0) { continue }
    if ($w.name -like 'dogrula-*' -and (Test-Path $pauseVerifyFile)) { continue }
    if ($w.name -eq 'embed' -and (Test-Path $pauseEmbedFile)) { continue }
    if ($nextStart[$w.name] -and $now -lt $nextStart[$w.name]) { continue }
    $n = 1 + [int]$restarts[$w.name]; $restarts[$w.name] = $n
    Start-Process -FilePath $py -ArgumentList $w.args -WindowStyle Hidden `
      -RedirectStandardOutput "$logDir\sentinel-$($w.name).out.log" -RedirectStandardError "$logDir\sentinel-$($w.name).err.log"
    $wait = if ($w.backoff) { [int]$w.backoff } else { 60 }
    $nextStart[$w.name] = $now.AddSeconds($wait)
    Write-Log "$($w.name) kolu yoktu, başlatıldı (#$n)"
  }

  foreach ($src in @('yargitay','danistay')) {
    if (Test-Path $pauseFile) { continue }
    $procs = Get-Procs "backfill_campaign\.py --source $src"
    $idx = [Math]::Min($state[$src], $queues[$src].Count - 1)
    $outLog = "$logDir\sentinel-campaign-$src.out.log"
    if ($procs.Count -gt 0) {
      # Takılma koruması: 75 dk boyunca log değişmediyse yeniden başlat (CAPTCHA beklemesi 15 dk)
      if ((Test-Path $outLog) -and ($now - (Get-Item $outLog).LastWriteTime).TotalMinutes -gt 75) {
        Write-Log "$src kampanyası 75 dk sessiz, öldürülüp yeniden başlatılacak"
        $procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        $nextStart[$src] = $now.AddSeconds(30)
      }
      continue
    }
    # Süreç yok: önceki tur tamamlandı mı?
    if ((Test-Path $outLog) -and $launchedAt[$src]) {
      $tail = (Get-Content $outLog -Tail 5 -Encoding utf8) -join "`n"
      if ($tail -match 'KAMPANYA TAMAM') {
        if ($state[$src] -lt $queues[$src].Count - 1) {
          $state[$src] = $state[$src] + 1; Save-State
          $idx = $state[$src]
          $launchedAt[$src] = $null
          Write-Log "$src kampanyası tamam, sıradaki: '$($queues[$src][$idx])'"
        } else {
          $nextStart[$src] = $now.AddHours(6)   # kuyruk bitti; ara sıra yeni karar için yeniden tara
          $launchedAt[$src] = $null
          Write-Log "$src kuyruğu tamam; 6 saat sonra yeniden taranacak"
          continue
        }
      } elseif ($tail -match 'CAPTCHA' -and $tail -match 'durduruldu') {
        $nextStart[$src] = $now.AddMinutes(20)   # 3 CAPTCHA sonrası uzun mola
        $launchedAt[$src] = $null
        Write-Log "$src üst üste CAPTCHA ile durdu; 20 dk soğuma"
        continue
      }
    }
    if ($nextStart[$src] -and $now -lt $nextStart[$src]) { continue }
    $chamber = $queues[$src][$idx]
    $cliArgs = @('-u','scripts\backfill_campaign.py','--source',$src,'--newest-first','--delay','8','--cooldown','90','--pause','3','--max-records','200')
    if ($chamber -ne '') { $cliArgs += @('--chamber', "`"$chamber`"") }
    Start-Process -FilePath $py -ArgumentList $cliArgs -WindowStyle Hidden `
      -RedirectStandardOutput $outLog -RedirectStandardError "$logDir\sentinel-campaign-$src.err.log"
    $launchedAt[$src] = $now
    $nextStart[$src] = $now.AddSeconds(60)
    Write-Log "$src kampanyası başlatıldı: '$chamber' (kuyruk $idx/$($queues[$src].Count - 1))"
  }

  Start-Sleep -Seconds 30
}
Write-Log "SENTINEL_STOP bulundu, nöbetçi kapandı"
