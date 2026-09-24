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
$env:INGESTION_RATE_LIMIT_RETRY_MINUTES = '10'   # 429 sonrasi soguma (varsayilan 2 dk portal kilidini uzatiyor)
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
$state = @{ yargitay = 0; danistay = 0; yargitay_done = $false; danistay_done = $false }
if (Test-Path $statePath) {
  try {
    $saved = Get-Content $statePath -Raw | ConvertFrom-Json
    foreach ($k in @('yargitay','danistay')) { if ($null -ne $saved.$k) { $state[$k] = [int]$saved.$k } }
    foreach ($k in @('yargitay_done','danistay_done')) { if ($null -ne $saved.$k) { $state[$k] = [bool]$saved.$k } }
  } catch {}
}
function Save-State { ($state | ConvertTo-Json) | Set-Content -Path $statePath -Encoding utf8 }

# Worker kolları: ad -> arama deseni + başlatma argümanları
$workers = @(
  @{ name = 'aym';       pattern = 'worker\.runner backfill --source aym';     args = @('-u','-m','worker.runner','backfill','--source','aym','--no-incremental','--no-embed') },
  @{ name = 'kdk';       pattern = 'worker\.runner backfill --source kdk';     args = @('-u','-m','worker.runner','backfill','--source','kdk','--no-incremental','--no-embed') },
  @{ name = 'mevzuat';   pattern = 'worker\.runner backfill --source mevzuat'; args = @('-u','-m','worker.runner','backfill','--source','mevzuat','--no-incremental','--no-embed') },
  # Yeni doğrulanan/eklenen resmî kayıtları sürekli embedding'e çevirir (yerel Ollama, hafif turlar).
  # Embedding: uc dilimli isci. 5 isci denendi (2026-09-21): hiz ayni (~31 parca/sn),
  # tavan GPU (dizustu, ~86C/54W); uc isci bu makinede olculen en yuksek verimli duzeydir.
  @{ name = 'embed0';    pattern = 'embed_chunks\.py.*--shard 0/3'; args = @('-X','utf8','-u','scripts\embed_chunks.py','--batch','64','--loop','--include-seeds','--shard','0/3') },
  @{ name = 'embed1';    pattern = 'embed_chunks\.py.*--shard 1/3'; args = @('-X','utf8','-u','scripts\embed_chunks.py','--batch','64','--loop','--include-seeds','--shard','1/3') },
  @{ name = 'embed2';    pattern = 'embed_chunks\.py.*--shard 2/3'; args = @('-X','utf8','-u','scripts\embed_chunks.py','--batch','64','--loop','--include-seeds','--shard','2/3') },
  # Sayistay yargi kararlari (resmi site, tam metin): yeniden baslatilabilir; bitince 6 saatte bir yeni karar icin taranir.
  # Iki paralel isci: Temyiz Kurulu (29 bin) ayri, Daire + Genel Kurul (22 bin) ayri.
  @{ name = 'sayistay-temyiz'; pattern = 'collect_sayistay\.py.*--kind temyiz'; backoff = 21600; args = @('-X','utf8','-u','scripts\collect_sayistay.py','--delay','0.6','--kind','temyiz') },
  @{ name = 'sayistay-daire';  pattern = 'collect_sayistay\.py.*--kind daire';  backoff = 21600; args = @('-X','utf8','-u','scripts\collect_sayistay.py','--delay','0.6','--kind','genelkurul','--kind','daire') },
  # Uyusmazlik Mahkemesi (PDF): TLS sertifikasi suresi dolmus; yalniz sabit parmak izi kabul edilir (bkz. ingestion/uyusmazlik/portal.py).
  @{ name = 'uyusmazlik'; pattern = 'collect_uyusmazlik\.py'; backoff = 21600; args = @('-X','utf8','-u','scripts\collect_uyusmazlik.py','--delay','0.8') },
  # Rekabet Kurulu kararlari (resmi site, PDF tam metin): yeniden baslatilabilir; bitince 6 saatte bir yeni karar icin taranir.
  # Iki paralel isci: sayfa 1-522 ve 523-son.
  @{ name = 'rekabet-a'; pattern = 'collect_rekabet\.py.*--to-page 522'; backoff = 21600; args = @('-X','utf8','-u','scripts\collect_rekabet.py','--delay','0.8','--to-page','522') },
  @{ name = 'rekabet-b'; pattern = 'collect_rekabet\.py.*--from-page 523'; backoff = 21600; args = @('-X','utf8','-u','scripts\collect_rekabet.py','--delay','0.8','--from-page','523') },
  @{ name = 'dogrulama'; pattern = 'worker\.verify_loop';                      args = @('-u','-m','worker.verify_loop') },
  # Uc uncu taraf kayit dogrulayicisi: kimlikle dogrudan ceker, hizini kendi ayarlar (429/CAPTCHA'da yavaslar).
  # CAPTCHA'da 3 kez ust uste durursa 20 dk sonra yeniden denenir.
  @{ name = 'dogrula-yargitay'; pattern = 'verify_seeds\.py --source yargitay'; backoff = 1200; args = @('-u','scripts\verify_seeds.py','--source','yargitay') },
  @{ name = 'dogrula-danistay'; pattern = 'verify_seeds\.py --source danistay'; backoff = 1200; args = @('-u','scripts\verify_seeds.py','--source','danistay') },
  # UYAP Emsal (istinaf) dogrulayicisi: ayri sunucu (emsal.uyap.gov.tr), Yargitay/Danistay kampanyalariyla portal paylasmaz ama cekim bitmeden dogrulama acilmaz: PAUSE_VERIFY bunu da durdurur.
  # UYAP Emsal: veri setinde olmayan (resmi portalda olan) kararlari ceker; en yeni aydan eskiye. Cekim suruyorken Emsal dogrulayicisi PAUSE_VERIFY_EMSAL ile beklemede.
  @{ name = 'emsal-cekim'; pattern = 'collect_emsal\.py'; backoff = 1200; args = @('-X','utf8','-u','scripts\collect_emsal.py','--delay','2.0') },
  @{ name = 'dogrula-emsal'; pattern = 'verify_seeds\.py --source emsal'; backoff = 1200; args = @('-X','utf8','-u','scripts\verify_seeds.py','--source','emsal') }
)
$pauseFile = "$stateDir\PAUSE_CAMPAIGNS"   # varsa arama-tabanli kampanyalar baslatilmaz (dogrulayici ayni portali kullanir)
$pauseVerifyFile = "$stateDir\PAUSE_VERIFY"   # varsa dogrulayicilar baslatilmaz (boslugu kapatan kampanya portali kullanir)
$pauseEmbedFile = "$stateDir\PAUSE_EMBED_ARM"    # varsa embedding kolu baslatilmaz
$pauseDoneFile = "$stateDir\PAUSE_DONE_SOURCES"  # 2026-09-22: kullanici istegiyle %100 biten kollari durdurmak icin (aym, sayistay, uyusmazlik)
$doneSources = @('aym', 'sayistay-temyiz', 'sayistay-daire', 'uyusmazlik', 'rekabet-a', 'rekabet-b')
$nextStart = @{}   # kol adı -> en erken yeniden başlatma zamanı
$launchedAt = @{}
$restarts = @{}

Write-Log "nöbetçi başladı (PID $me)"
while (-not (Test-Path $stopFile)) {
  $now = Get-Date

  # Once bosluk toplama devam ederken eski bir nobetci tarafindan acilmis ayni-domain
  # dogrulayicisi kalmasin. Embedding ve diger resmî kaynaklar bundan etkilenmez.
  foreach ($src in @('yargitay','danistay')) {
    if (-not $state["${src}_done"]) {
      Get-Procs "verify_seeds\.py --source $src" |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    }
  }

  foreach ($w in $workers) {
    if ((Test-Path $pauseDoneFile) -and ($doneSources -contains $w.name)) { continue }
    if ((Get-Procs $w.pattern).Count -gt 0) { continue }
    # Dogrulama onceligi: kucuk isler once (mevzuat, Danistay, Emsal); Yargitay (9,8M kayit) en sona kalir.
    # PAUSE_VERIFY yalniz Yargitay dogrulayicisini durdurur.
    if ($w.name -eq 'dogrula-yargitay' -and (Test-Path $pauseVerifyFile)) { continue }
    if ($w.name -eq 'dogrula-emsal' -and (Test-Path "$stateDir\PAUSE_VERIFY_EMSAL")) { continue }
    if ($w.name -eq 'dogrula-danistay' -and (Test-Path "$stateDir\PAUSE_VERIFY_DANISTAY")) { continue }
    # Bosluk kampanyasi once yalniz korpusta olmayan kayitlari toplar. Ayni resmî
    # domaine giden seed dogrulayicisi kampanya bitene kadar 429/CAPTCHA butcesini tuketmesin.
    if ($w.name -eq 'dogrula-yargitay' -and -not $state.yargitay_done) { continue }
    if ($w.name -eq 'dogrula-danistay' -and -not $state.danistay_done) { continue }
    if ($w.name -like 'embed*' -and (Test-Path $pauseEmbedFile)) { continue }
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
    if ($state["${src}_done"]) { continue }
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
          $state["${src}_done"] = $true; Save-State
          $launchedAt[$src] = $null
          Write-Log "$src bosluk kuyrugu tamam; resmî dogrulayiciya geciliyor"
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
    $sourceDelay = if ($src -eq 'yargitay') { '7.5' } else { '5.5' }
    $cliArgs = @('-u','scripts\backfill_campaign.py','--source',$src,'--newest-first','--delay',$sourceDelay,'--cooldown','90','--pause','3','--max-records','300')
    if ($chamber -ne '') { $cliArgs += @('--chamber', "`"$chamber`"") }
    # Hazir bulk corpus kayitlari gap taramasinda bilinen sayilir. Portal butcesi
    # milyonlarca mevcut kaydi tekrar indirmeye degil gercek bosluklara gider.
    $env:INGEST_SEEDS_AS_KNOWN = '1'
    Start-Process -FilePath $py -ArgumentList $cliArgs -WindowStyle Hidden `
      -RedirectStandardOutput $outLog -RedirectStandardError "$logDir\sentinel-campaign-$src.err.log"
    $env:INGEST_SEEDS_AS_KNOWN = $null
    $launchedAt[$src] = $now
    $nextStart[$src] = $now.AddSeconds(60)
    Write-Log "$src kampanyası başlatıldı: '$chamber' (kuyruk $idx/$($queues[$src].Count - 1))"
  }

  Start-Sleep -Seconds 30
}
Write-Log "SENTINEL_STOP bulundu, nöbetçi kapandı"
