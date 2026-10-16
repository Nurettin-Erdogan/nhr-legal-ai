# PC'deki veri işlerini canlı tutar: Emsal toplayıcısı (emsal.uyap.gov.tr) ve mevzuat doğrulama döngüsü. Bedesten (Yargıtay/Danıştay)
# işleri 2026-10-14'ten beri AWS + Azure çekici düğümlerinde; PC Bedesten'e istek atmaz. Embedding haftalık görevle çalışır.
# Görev Zamanlayıcı 5 dakikada bir ve uykudan uyanınca çalıştırır: süreç yoksa gizli başlatır, kaldığı yerden devam eder.
#
# Geçici durdurma: data\campaign\PAUSE_PC_COLLECTORS dosyası varken portal işleri (Emsal, mevzuat doğrulama) başlatılmaz
# (çalışanları kendiniz durdurun). Örn. UYAP'tan toplu aktarım yapılırken: dosyayı oluşturup süreçleri durdurun, bitince silin.
# data\campaign\PAUSE_PC_EMBED: sürekli embedding işçisini başlatmaz (haftalık görev ayrı).
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$py = Join-Path $root '.venv\Scripts\python.exe'
$pause = Join-Path $root 'data\campaign\PAUSE_PC_COLLECTORS'
$logs = Join-Path $root 'data\logs'
$paused = Test-Path -LiteralPath $pause
if (-not (Test-Path -LiteralPath $py)) { throw "Python bulunamadı: $py" }
New-Item -ItemType Directory -Force $logs | Out-Null

function Test-Running([string]$pattern) {
    [bool](Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match $pattern })
}

function Start-Hidden([string]$name, [string]$scriptArgs) {
    $startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0 }
    $out = Join-Path $logs "$name.out.log"
    $err = Join-Path $logs "$name.err.log"
    # Günlükler eklenerek yazılır: saatlik sayaç karşılaştırması ve geçmiş korunur.
    $cmd = "cmd.exe /c `"cd /d $root && `"$py`" -X utf8 -u $scriptArgs >> `"$out`" 2>> `"$err`"`""
    Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $cmd; CurrentDirectory = $root; ProcessStartupInformation = $startup
    } | Out-Null
}

# Yargıtay/Danıştay: eksik taraması bitti (2026-10-13/14); seed doğrulaması AWS + Azure çekici düğümlerinde
# (`scripts/fetch_worker.py`, sonuçları `scripts/fetcher_hub.py` günde bir işler). PC Bedesten'e istek ATMAZ.

# PC'nin kendi işleri (kullanıcı 2026-10-14: "PC diğer eksik verileri çeksin, boş durmasın"): ayrı portallar, Bedesten kotasını paylaşmaz.
# UYAP'tan toplu aktarım yapılacağı zaman PAUSE_PC_COLLECTORS ile durdurulur.
if (-not $paused -and -not (Test-Running 'collect_emsal\.py')) {
    Start-Hidden 'pc-emsal3' 'scripts\collect_emsal.py --delay 2.0'
}
# Emsal seed doğrulaması (kullanıcı 2026-10-15: "her şey 2 sunucu + PC'de doğrulansın"): PC en yeniden eskiye gider,
# sunuculardaki Emsal şeridi (fetcher_hub) en eskiden yeniye; ortada buluşurlar. Ayrı portal: Bedesten kotasını etkilemez.
if (-not $paused -and -not (Test-Running 'verify_seeds\.py --source emsal')) {
    Start-Hidden 'pc-verify-emsal' 'scripts\verify_seeds.py --source emsal --delay 10.0 --min-delay 8.0 --cooldown 120 --captcha-wait 3600'
}
# PC artık Bedesten çekicisi DEĞİL (kullanıcı 2026-10-16: PC'yi bırak, ikinci AWS sunucusu açılsın): PC yalnız Emsal, mevzuat doğrulama ve
# embedding yapar; Bedesten çekimini AWS + Azure (+ ikinci AWS) düğümleri yapar. UYAP çakışma riski bu yüzden azalır.
# Mevzuat doğrulama döngüsü (mevzuat.gov.tr / Resmî Gazete; checkpoint 'mevzuat_verify'): eskiden Azure'da kendi veritabanında
# çalışırdı, Azure artık veritabanı tutmadığı için PC'de, doğrudan ana veritabanında çalışır.
if (-not $paused -and -not (Test-Running 'worker\.verify_loop')) {
    Start-Hidden 'pc-mevzuat-verify' '-m worker.verify_loop'
}
# Embedding (kullanıcı 2026-10-16: "embedding'i hızlandır, portalla işi yok"): 3 dilimli işçi (K/3), parça başına 64. Portala istek atmaz,
# UYAP duraklatma bayrağından etkilenmez. Önceliği BelowNormal (PC'nin diğer işlerini ezmez), Ollama Normal.
# Gürültü/yük istenmiyorsa data\campaign\PAUSE_PC_EMBED dosyası işçileri başlatmaz.
if (-not (Test-Path -LiteralPath (Join-Path $root 'data\campaign\PAUSE_PC_EMBED'))) {
    foreach ($k in 0, 1, 2) {
        if (-not (Test-Running "embed_chunks\.py.*--shard $k/3")) {
            Start-Hidden "pc-embed-$k" "scripts\embed_chunks.py --loop --shard $k/3 --batch 64"
        }
    }
    Start-Sleep -Seconds 3
    Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
        $line = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine
        if ($line -match 'embed_chunks\.py') { try { $_.PriorityClass = 'BelowNormal' } catch {} }
    }
    Get-Process ollama* -ErrorAction SilentlyContinue | ForEach-Object { try { $_.PriorityClass = 'Normal' } catch {} }
}

# Azure->PC veritabanı senkronu 2026-10-14'ten beri yok: Azure artık veritabanı tutmuyor, yalnız çekici düğüm
# (sonuçları `scripts/fetcher_hub.py` alır). Eski senkron yedeği bu yüzden kaldırıldı.
