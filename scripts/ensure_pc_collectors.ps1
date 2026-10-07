# PC'deki hukuk korpusu toplayıcılarını (Bedesten Yargıtay boşluk taraması + Emsal) canlı tutar.
# Görev Zamanlayıcı 5 dakikada bir ve oturum açılışında çalıştırır: süreç yoksa gizli ve oturumdan bağımsız başlatır.
# PC kapanıp açılınca ya da süreç ölünce kendiliğinden kaldığı yerden devam eder (aylık/günlük imleçler durum dosyasında).
#
# Geçici durdurma: data\campaign\PAUSE_PC_COLLECTORS dosyası varken portal toplayıcıları (Bedesten/Emsal) başlatılmaz (çalışanları kendiniz durdurun);
# portala istek atmayan embedding işçisi etkilenmez.
# Örn. UYAP'a bu bilgisayardan girerken: dosyayı oluşturup süreçleri durdurun, bitince dosyayı silin.
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

if (-not $paused -and -not (Test-Running 'collect_bedesten\.py')) {
    Start-Hidden 'pc-gap-yargitay' 'scripts\collect_bedesten.py --source yargitay --by-chamber --from-year 2026 --to-year 2018'
}
if (-not $paused -and -not (Test-Running 'collect_emsal\.py')) {
    Start-Hidden 'pc-emsal3' 'scripts\collect_emsal.py --delay 2.0'
}
# Tek embedding işçisi, düşük öncelikli: toplayıcıları ve bilgisayarı yavaşlatmadan, yeni gelen kararları yavaş yavaş vektörler.
# Gürültü/yük istenmiyorsa data\campaign\PAUSE_PC_EMBED dosyası embedding işçisini de başlatmaz.
if (-not (Test-Path -LiteralPath (Join-Path $root 'data\campaign\PAUSE_PC_EMBED')) -and -not (Test-Running 'embed_chunks\.py')) {
    Start-Hidden 'pc-embed-1' 'scripts\embed_chunks.py --loop'
    Start-Sleep -Seconds 3
    Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
        $line = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine
        if ($line -match 'embed_chunks\.py') { try { $_.PriorityClass = 'BelowNormal' } catch {} }
    }
}
