r"""Yerel, salt-okunur NHR korpus izleme ekranı.

Ana web uygulamasından bağımsız çalışır ve yalnız loopback'e bağlanır:

    .\.venv\Scripts\python.exe scripts\corpus_dashboard.py --port 3010

Tarayıcı: http://127.0.0.1:3010
"""

from __future__ import annotations

import argparse
import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LOGGER = logging.getLogger("corpus-dashboard")

HTML = r"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>NHR Korpus Canlı Durum</title>
  <style>
    :root{color-scheme:dark;--bg:#071511;--panel:#0d211b;--line:#234239;--text:#eff8f4;--muted:#91aaa1;--green:#42d392;--gold:#e7ba62;--red:#ff8b7b}
    *{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 85% 0,#183c30 0,transparent 32%),var(--bg);color:var(--text);font:14px Inter,system-ui,sans-serif}
    main{width:min(1180px,calc(100% - 32px));margin:0 auto;padding:28px 0 50px}header{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;margin-bottom:22px}
    h1{font:600 clamp(26px,4vw,42px) Georgia,serif;margin:3px 0 7px}.eyebrow{color:var(--gold);font-size:11px;letter-spacing:.2em;text-transform:uppercase}.muted{color:var(--muted)}
    .live{display:flex;align-items:center;gap:8px;border:1px solid var(--line);background:#0a1b16;padding:9px 12px;border-radius:999px;white-space:nowrap}.dot{width:9px;height:9px;border-radius:50%;background:var(--green);box-shadow:0 0 12px var(--green)}
    .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card,.panel{border:1px solid var(--line);background:linear-gradient(145deg,rgba(18,46,37,.96),rgba(9,27,22,.96));border-radius:15px;box-shadow:0 12px 32px #0004}
    .card{padding:17px}.label{color:var(--muted);font-size:12px}.value{font-size:clamp(22px,3vw,31px);font-weight:700;margin-top:8px;font-variant-numeric:tabular-nums}.hint{font-size:11px;color:var(--muted);margin-top:5px}
    .layout{display:grid;grid-template-columns:1.25fr .75fr;gap:14px;margin-top:14px}.panel{padding:19px}.panel h2{font:600 20px Georgia,serif;margin:0 0 14px}
    table{width:100%;border-collapse:collapse}th,td{text-align:right;padding:10px 7px;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}th:first-child,td:first-child{text-align:left}th{color:var(--muted);font-size:11px;font-weight:500}tr:last-child td{border-bottom:0}
    .official{color:var(--green)}.pending{color:var(--gold)}.bar{height:10px;background:#1a332b;border-radius:999px;overflow:hidden;margin:12px 0 8px}.fill{height:100%;background:linear-gradient(90deg,#278b66,var(--green));transition:width .5s}
    .split{display:flex;justify-content:space-between;gap:12px;margin-top:9px}.notice{margin-top:14px;border:1px solid #715d2f;background:#372d1666;color:#f1d395;padding:12px 14px;border-radius:11px;font-size:12px;line-height:1.5}
    .error{display:none;margin-bottom:14px;border:1px solid #7c392f;background:#3a1815;color:#ffb5aa;padding:11px 14px;border-radius:10px}button{border:1px solid var(--line);background:#123329;color:var(--text);border-radius:9px;padding:8px 11px;cursor:pointer}button:hover{border-color:#3c6d5c}
    @media(max-width:850px){.grid{grid-template-columns:repeat(2,1fr)}.layout{grid-template-columns:1fr}header{flex-direction:column}}@media(max-width:480px){.grid{grid-template-columns:1fr}}
  </style>
</head>
<body><main>
  <header><div><div class="eyebrow">NHR Legal AI</div><h1>Türk Hukuku Korpusu</h1><div class="muted">PostgreSQL + pgvector canlı veri durumu</div></div><div class="live"><span class="dot"></span><span id="status">Bağlanıyor…</span><button id="refresh">Yenile</button></div></header>
  <div id="error" class="error"></div>
  <section class="grid">
    <div class="card"><div class="label">Toplam yargı kararı</div><div class="value" id="courtTotal">—</div><div class="hint">resmî + doğrulanmamış arşiv</div></div>
    <div class="card"><div class="label">Resmî doğrulanmış karar</div><div class="value official" id="official">—</div><div class="hint" id="latest">son karar: —</div></div>
    <div class="card"><div class="label">Doğrulanmamış arşiv</div><div class="value pending" id="pending">—</div><div class="hint">ayrı etiketle kullanılır</div></div>
    <div class="card"><div class="label">Aranabilir metin parçası</div><div class="value" id="chunks">—</div><div class="hint">RAG chunk toplamı</div></div>
  </section>
  <section class="layout">
    <div class="panel"><h2>Karar kaynakları</h2><table><thead><tr><th>Kaynak</th><th>Resmî</th><th>Doğrulanmadı</th><th>Toplam</th></tr></thead><tbody id="sources"></tbody></table></div>
    <div class="panel"><h2>Embedding</h2><div class="value" id="embedPercent">—</div><div class="bar"><div class="fill" id="embedBar"></div></div><div class="split"><span><span class="muted">Hazır</span><br><b id="embedReady">—</b></span><span style="text-align:right"><span class="muted">Bekleyen</span><br><b id="embedPending">—</b></span></div><div class="notice">Embedding arama kabiliyetini artırır; kaynağın resmî doğruluğunu değiştirmez.</div></div>
    <div class="panel"><h2>Mevzuat</h2><table><tbody><tr><td>Bedesten maddesi</td><td id="laws">—</td></tr><tr><td>Çift doğrulanmış</td><td class="official" id="lawsBoth">—</td></tr><tr><td>Yalnız MBS</td><td id="lawsMbs">—</td></tr><tr><td>Yalnız Resmî Gazete</td><td id="lawsGazette">—</td></tr><tr><td>Doğrulama bekleyen</td><td class="pending" id="lawsPending">—</td></tr></tbody></table></div>
    <div class="panel"><h2>Diğer resmî kaynaklar</h2><table><tbody id="otherSources"></tbody></table><div class="notice">Ekran salt okunurdur. Veri silmez, değiştirmez veya dışarı göndermez.</div></div>
  </section>
</main><script>
const nf=new Intl.NumberFormat('tr-TR');const $=id=>document.getElementById(id);const n=v=>nf.format(v||0);
function row(name,official,pending=0){return `<tr><td>${name}</td><td class="official">${n(official)}</td><td class="pending">${pending?n(pending):'—'}</td><td>${n(official+pending)}</td></tr>`}
function other(name,value){return `<tr><td>${name}</td><td class="official">${n(value)}</td></tr>`}
async function load(){try{$('error').style.display='none';const r=await fetch('/api/stats',{cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);const s=await r.json();
 const total=s.decision_count+s.seed_count, et=s.embeddings.ready+s.embeddings.pending, ep=et?s.embeddings.ready/et*100:0;
 $('courtTotal').textContent=n(total);$('official').textContent=n(s.decision_count);$('pending').textContent=n(s.seed_count);$('chunks').textContent=n(s.chunk_count);$('latest').textContent=`son karar: ${s.latest_decision_date||'—'}`;
 $('sources').innerHTML=row('Yargıtay',s.court_decisions.yargitay,s.third_party.yargitay)+row('Danıştay',s.court_decisions.danistay,s.third_party.danistay)+row('AYM',s.court_decisions.anayasa_mahkemesi,s.third_party.aym_norm_denetimi)+row('İstinaf / Emsal',s.court_decisions.istinaf_emsal,s.third_party.istinaf_emsal);
 $('embedPercent').textContent=`%${ep.toFixed(1)} tamamlandı`;$('embedBar').style.width=`${ep}%`;$('embedReady').textContent=n(s.embeddings.ready);$('embedPending').textContent=n(s.embeddings.pending);
 const l=s.legislation_verification;$('laws').textContent=n(l.bedesten);$('lawsBoth').textContent=n(l.both_verified);$('lawsMbs').textContent=n(l.mbs_only);$('lawsGazette').textContent=n(l.gazette_only);$('lawsPending').textContent=n(l.neither);
 const a=s.administrative;$('otherSources').innerHTML=other('KDK',a.kamu_denetciligi_kurumu)+other('Sayıştay',a.sayistay)+other('Uyuşmazlık Mahkemesi',a.uyusmazlik_mahkemesi);
 $('status').textContent=`Canlı · ${new Date().toLocaleTimeString('tr-TR')}`;
 }catch(e){$('status').textContent='Bağlantı hatası';$('error').textContent=`Veri alınamadı: ${e.message}`;$('error').style.display='block'}}
$('refresh').addEventListener('click',load);load();setInterval(load,10000);
</script></body></html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    api_url = "http://127.0.0.1:8766/api/legal/stats"

    def _send(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP API
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send(HTTPStatus.OK, "text/html; charset=utf-8", HTML.encode("utf-8"))
            return
        if path == "/health":
            self._send(HTTPStatus.OK, "application/json", b'{"status":"ok"}')
            return
        if path == "/api/stats":
            self._proxy_stats()
            return
        self._send(HTTPStatus.NOT_FOUND, "application/json", b'{"detail":"not found"}')

    def _proxy_stats(self) -> None:
        try:
            request = Request(self.api_url, headers={"Accept": "application/json"})
            with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed loopback URL
                body = response.read()
            json.loads(body)
            self._send(HTTPStatus.OK, "application/json; charset=utf-8", body)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            LOGGER.warning("Korpus API okunamadı: %s", exc)
            body = json.dumps({"detail": "Korpus API şu anda okunamadı"}).encode("utf-8")
            self._send(HTTPStatus.BAD_GATEWAY, "application/json; charset=utf-8", body)

    def log_message(self, template: str, *args: object) -> None:
        LOGGER.info("%s - %s", self.client_address[0], template % args)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3010)
    parser.add_argument("--api-url", default=DashboardHandler.api_url)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Güvenlik nedeniyle yalnız loopback adresine bağlanılabilir")
    DashboardHandler.api_url = args.api_url
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    LOGGER.info("NHR korpus ekranı: http://%s:%s", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
