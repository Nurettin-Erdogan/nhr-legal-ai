"""UYAP eklentisi gerçek Chromium'da: sahte UYAP (yerel HTTPS) + sahte NHR API. Ağ ve veritabanı yok.

`*.uyap.gov.tr` adresleri tarayıcıda yerel sunucuya yönlendirilir; gerçek UYAP'a hiçbir istek gitmez.
Bu sayfalar gerçek UYAP'ın DOM'unu kanıtlamaz; eklentinin mantığını (yanlış düğme, onay, otomatik
aktarım kapısı) doğrular. Yavaş olduğundan ve Chromium gerektirdiğinden yalnız istenince çalışır:

    $env:NHR_BROWSER_TESTS = "1"
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_uyap_extension_browser.py -q
"""

from __future__ import annotations

import datetime
import io
import json
import os
import shutil
import ssl
import tempfile
import threading
import time
import zipfile
from email import message_from_bytes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("NHR_BROWSER_TESTS") != "1", reason="Tarayıcı testleri için NHR_BROWSER_TESTS=1 gerekir"
)

# NHR_EXTENSION_DIR: başka bir eklenti sürümünü (örn. eski commit) aynı testlerle sınamak için.
EXTENSION_DIR = Path(
    os.getenv("NHR_EXTENSION_DIR")
    or Path(__file__).resolve().parents[1] / "web" / "public" / "jurisai-avukat"
)
TOKEN = "jsai_" + "a" * 44
BASE = "https://avukat.uyap.gov.tr"
CASE_TITLE = "Dava Dosyası 2025/412 Esas - İstanbul 5. İş Mahkemesi"


def _pdf(tag: str) -> bytes:
    return f"%PDF-1.4\n% fixture {tag}\n%%EOF\n".encode()


def _odt(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        archive.writestr(
            "content.xml",
            '<?xml version="1.0" encoding="UTF-8"?><office:document-content '
            'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:text>'
            f"<text:p>{text}</text:p></office:text></office:body></office:document-content>",
        )
    return buffer.getvalue()


def _udf(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("content.xml", f"<template><content><![CDATA[{text}]]></content></template>")
    return buffer.getvalue()


_EVRAK_ROWS = f"""
<table>
  <tr><th>Evrak</th><th>Tarih</th><th></th></tr>
  <tr><td>Dava Dilekçesi</td><td>01.03.2025</td><td><a href="{BASE}/evrak/indir?id=101">İndir</a></td></tr>
  <tr><td>Bilirkişi Raporu</td><td>10.04.2025</td><td><a href="{BASE}/evrak/indir?id=102&tip=udf">İndir</a></td></tr>
  <tr><td>Tensip Zaptı</td><td>12.05.2025</td>
      <td><a href="{BASE}/evrak/goster?id=103">Görüntüle</a> <a href="{BASE}/evrak/indir?id=103">İndir</a></td></tr>
</table>
"""

PAGES = {
    # Giriş sayfası: liste öğelerinde PDF bağlantıları var ama dava bağlamı yok.
    "/giris": """<html><body><nav><ul><li><a href="/dokumanlar/sozlesme.pdf">Kullanım Sözleşmesi</a></li></ul></nav>
      <ul><li><a href="/dokumanlar/nasil-kullanirim.pdf">Nasıl Kullanırım?</a></li></ul></body></html>""",
    # Vatandaş ana sayfası: .row içindeki paragrafta kılavuz PDF'i (gerçek ekranda yanlış düğme çıkmıştı).
    "/main": """<html><body><div class="row"><h3>Dava ve Cevap Dilekçesi Örnekleri</h3>
      <p>Duyuru. Kılavuzu indirmek için <a href="/files/kilavuz.pdf">tıklayınız!</a></p></div></body></html>""",
    # Aynı sayfa ama metinde bir esas numarası geçiyor: .row yine evrak satırı sayılmamalı.
    "/main-numbered": """<html><body><div class="row"><p>Duyuru 2025/9 sayılı karar. Kılavuz:
      <a href="/files/kilavuz.pdf">tıklayınız!</a></p></div></body></html>""",
    # Gerçek Vatandaş Portalı "Dosya Sorgulama" ekranı (canlıda görülen hata): davaların listesi, evrak yok.
    # Sayfada yardım/kılavuz PDF'leri (yan panelde, içerikte ve alt bilgide) bulunur; bunlar evrak değildir.
    "/vatandas/dosya-sorgulama": """<html><body>
      <aside class="sidebar"><ul><li><a href="/main/jsp/vatandas/index.jsp?menuId=12573">Dosya Sorgulama</a></li>
        <li><a href="/yardim/menu-kilavuz.pdf">Menü kılavuzu</a></li></ul></aside>
      <h2>Dosya Sorgulama</h2>
      <table id="liste"><tr><th>Taraf Rolü</th><th>Mahkeme Adı</th><th>Esas No</th><th>Dosya Görüntüle</th></tr>
        <tr id="r1"><td>Katılan</td><td>Ankara 33. Ağır Ceza Mahkemesi</td><td>2024/124</td>
            <td><button onclick="void(0)">Dosya Görüntüle</button></td></tr>
        <tr id="r2"><td>Katılan</td><td>Ankara Bölge Adliye Mahkemesi 19. Ceza Dairesi</td><td>2024/2000</td>
            <td><button onclick="void(0)">Dosya Görüntüle</button></td></tr></table>
      <div class="duyuru"><a href="/yardim/ornek-dilekce.pdf">Örnek dilekçe</a>
        <a href="/files/kullanim-kilavuzu.pdf">Kullanım kılavuzu</a>
        <a href="https://cdn.e-devlet.gov.tr/downloads/portal/IkiAsamaliGirisIslemleri_Web_Kilavuz.pdf">Kılavuz</a></div>
      <footer><a href="/dokumanlar/kullanim-sozlesmesi.pdf">Sözleşme</a></footer></body></html>""",
    # Gerçek Vatandaş Portalı dosya penceresi: evrak listesi tablo değil, klasör AĞACI (yapraklar bağlantı değil).
    "/vatandas/evrak-agaci": """<html><body><h2>Dosya Sorgulama</h2>
      <div role="dialog" class="modal in" style="display:block"><h4 class="modal-title">2024/2000 - Test Mahkemesi</h4>
        <ul class="nav nav-tabs"><li><a>Taraf Bilgileri</a></li><li class="active"><a>Evrak</a></li></ul>
        <button type="button">Ön İzlemeyi Aktifleştir</button>
        <div id="tree"><ul><li class="jstree-node"><a class="jstree-anchor" href="#" onclick="openNode('1234567')">Gizli Klasör Ahmet</a>
          <ul><li class="jstree-node jstree-leaf"><a class="jstree-anchor" href="#" data-evrak-id="99887">SIRRI-EVRAK-ADI Mehmet</a></li></ul></li></ul></div>
      </div></body></html>""",
    # Yaprağa tıklayınca XHR + iframe ile ön izleme açan ağaç (tıklama kaydı testi).
    "/vatandas/evrak-agaci-tikla": """<html><body><h2>Dosya Sorgulama</h2>
      <div role="dialog" class="modal in" style="display:block"><h4 class="modal-title">2024/2000 - Test</h4>
        <div id="tree"><ul><li class="jstree-node jstree-leaf"><a class="jstree-anchor" id="yaprak" href="#"
            data-evrak-id="55">SIRRI-YAPRAK-ADI Mehmet</a></li></ul></div>
        <div id="onizleme"></div></div>
      <script>
        document.getElementById('yaprak').addEventListener('click', function (event) {
          event.preventDefault();
          var xhr = new XMLHttpRequest();
          xhr.open('GET', '/evrak/onizleme-verisi?evrakId=55');
          xhr.onload = function () {
            var frame = document.createElement('iframe');
            frame.src = '/evrak/onizleme?id=55';
            document.getElementById('onizleme').appendChild(frame);
          };
          xhr.send();
        });
      </script></body></html>""",
    # Ön izleme: yaprağa tıklayınca gizli form iframe'e POST edilir, evrak iframe'in İÇİNDE gelir
    # (gerçek Vatandaş Portalı böyle: ana sayfadan görünmeyen, iframe içi istek).
    "/vatandas/onizleme-post": """<html><body><h2>Dosya Sorgulama</h2>
      <div role="dialog" class="modal in" style="display:block"><h4 class="modal-title">2024/2000 - Test</h4>
        <span class="file" id="yaprak2" evrak_id="77">SIRRI-ONIZLEME-ADI Mehmet</span>
        <form id="f" method="post" action="/evrak/onizleme-gonder" target="ifr" style="display:none">
          <input type="hidden" name="evrakId" value="77"><input type="hidden" name="gizliDeger" value="TOPSECRET">
        </form>
        <iframe name="ifr" id="ifr"></iframe></div>
      <script>
        document.getElementById('yaprak2').addEventListener('click', function () { document.getElementById('f').submit(); });
      </script></body></html>""",
    # Gerçek Vatandaş Portalı dosya penceresi: jQuery-treeview benzeri klasör ağacı, ön izleme düğmesi, ön izleme
    # iframe'i ve ODT yanıtı (view_document_brd.uyap). Ön izleme kapalıyken yaprağa tıklamak hiçbir şey yapmaz.
    "/vatandas/dosya-agaci": """<html><body><h2>Dosya Sorgulama</h2>
      <div role="dialog" class="modal in" style="display:block">
        <h4 class="modal-title">2024/2000 - Ankara Bölge Adliye Mahkemesi 19. Ceza Dairesi - Ceza Dava Dosyası</h4>
        <button type="button" id="onizleme" onclick="onIzlemeDurumu(this)">Ön İzlemeyi Aktifleştir</button>
        <ul id="tree" class="treeview"><li class="collapsable"><span class="folder">Ankara Bölge Adliye Mahkemesi 19. Ceza Dairesi 2024/2000</span><ul>
          <li class="expandable"><div class="hitarea"></div><span class="folder">Dosyaya Eklenen Son 20 Evrak</span><ul style="display:none">
            <li><span class="file" evrak_id="201">Kesinleşme Şerhleri 30/06/2025</span></li>
            <li><span class="file" evrak_id="202">Kesinleşme Şerhleri 30/06/2025</span></li>
            <li><span class="file" evrak_id="203">Gerekçeli Karar 30/06/2025</span></li></ul></li>
          <li class="collapsable"><span class="folder">Tüm Evraklar</span><ul>
            <li class="expandable"><div class="hitarea"></div><span class="folder">2024/2000 (Ceza Dava Dosyası)</span><ul style="display:none">
              <li class="expandable"><div class="hitarea"></div><span class="folder">Kesinleşme Şerhleri (2)</span><ul style="display:none">
                <li><span class="file" evrak_id="101">Kesinleşme Şerhleri 30/06/2025</span></li>
                <li><span class="file" evrak_id="102">Kesinleşme Şerhleri 30/06/2025</span></li></ul></li>
              <li class="expandable"><div class="hitarea"></div><span class="folder">Gerekçeli Karar (1)</span><ul style="display:none">
                <li class="expandable"><div class="hitarea"></div><span class="file" evrak_id="103">Gerekçeli Karar 30/06/2025</span><ul style="display:none">
                  <li><span class="file" evrak_id="104" ana_evrak_id="103">Ek 1</span></li></ul></li></ul></li>
            </ul></li></ul></li></ul></li></ul>
        <div id="viewer"></div>
      </div>
      <script>
        var preview = false;
        function onIzlemeDurumu(button) {
          preview = !preview;
          button.textContent = preview ? 'Ön İzlemeyi Kapat' : 'Ön İzlemeyi Aktifleştir';
        }
        function toggle(li) {
          var ul = li.querySelector(':scope > ul');
          if (!ul) return;
          var closed = li.classList.contains('expandable');
          li.classList.toggle('expandable', !closed);
          li.classList.toggle('collapsable', closed);
          ul.style.display = closed ? 'block' : 'none';
        }
        document.addEventListener('click', function (event) {
          var target = event.target;
          if (target.classList.contains('hitarea') || target.classList.contains('folder')) {
            toggle(target.closest('li'));
          } else if (target.classList.contains('file') && preview) {
            var frame = document.createElement('iframe');
            // Gerçek portalda yaprağın evrak_id'si ile isteğin evrakId'sinin eşit olduğu varsayılamaz: isteğe ENC öneki eklenir.
            frame.src = '/main/jsp/viewer.jsp?mimeType=odt&evrakId=ENC' + target.getAttribute('evrak_id') + '&dosyaId=9&yargiTuru=Ceza';
            document.getElementById('viewer').replaceChildren(frame);
          }
        });
      </script></body></html>""",
    # Gerçekçi evrak listesi.
    "/dosya/evraklar": f"<html><body><h2>{CASE_TITLE}</h2>{_EVRAK_ROWS}</body></html>",
    # Dosya penceresi: Evrak sekmesine basılınca liste AJAX ile gelir.
    "/dosya/pencere": f"""<html><body><div role="dialog" class="modal">
      <h4 class="modal-title">{CASE_TITLE}</h4>
      <ul class="nav"><li><a id="t1">Taraf Bilgileri</a></li><li><a id="t2">Evrak</a></li></ul>
      <div id="panel">Davacı: Ahmet Yılmaz Davalı: Örnek İnşaat A.Ş.</div></div>
      <script>
        // Sekme tıklaması sekme çubuğunda yakalanır (li ya da a'ya tıklansa da aynı).
        document.querySelector('.nav').addEventListener('click', function (event) {{
          if (event.target.textContent.trim() !== 'Evrak') return;
          setTimeout(function () {{ document.getElementById('panel').innerHTML = `{_EVRAK_ROWS}`; }}, 150);
        }});
      </script></body></html>""",
}


class _UyapHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        if self.path.startswith("/evrak/onizleme-gonder"):
            data = _pdf("onizleme")
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", "inline; filename=gizli-ad.pdf")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._send(404, b"yok", "text/plain")

    def do_GET(self):  # noqa: N802
        path, _, query = self.path.partition("?")
        if path in PAGES:
            return self._send(200, PAGES[path].encode(), "text/html; charset=utf-8")
        if path == "/evrak/indir":
            doc_id = query.split("id=")[-1].split("&")[0]
            if "tip=udf" in query:
                return self._send(200, _udf(f"Bilirkişi raporu {doc_id}"), "application/zip")
            return self._send(200, _pdf(doc_id), "application/pdf")
        if path == "/main/jsp/viewer.jsp":
            page = "<html><body><script>fetch('/main/jsp/view_document_brd.uyap' + location.search, {credentials: 'include'});</script></body></html>"
            return self._send(200, page.encode(), "text/html; charset=utf-8")
        if path == "/main/jsp/view_document_brd.uyap":
            evrak_id = query.split("evrakId=")[-1].split("&")[0].removeprefix("ENC")
            data = _odt(f"Evrak {evrak_id} metni")
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.oasis.opendocument.text")
            self.send_header("Content-Disposition", "attachment; filename=evrak.odt")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path.startswith("/evrak/onizleme"):
            return self._send(200, _pdf(path), "application/pdf")
        if path.endswith(".pdf"):
            return self._send(200, _pdf(path), "application/pdf")
        return self._send(404, b"yok", "text/plain")

    def _send(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _ApiHandler(BaseHTTPRequestHandler):
    uploads: list[dict] = []

    def log_message(self, *args):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        status, payload = 200, {"ok": True, "id": "fixture"}
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            status, payload = 401, {"error": "Geçersiz bağlantı anahtarı"}
        else:
            message = message_from_bytes(
                b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body
            )
            fields, file = {}, None
            for part in message.get_payload() if message.is_multipart() else []:
                name = part.get_param("name", header="content-disposition")
                if part.get_filename():
                    file = {"name": part.get_filename(), "data": part.get_payload(decode=True)}
                else:
                    fields[name] = part.get_payload(decode=True).decode("utf-8")
            if file is None:
                status, payload = 400, {"error": "Dosya eksik"}
            else:
                type(self).uploads.append({"file": file, "fields": fields})
        data = json.dumps(payload).encode()
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _self_signed(directory: Path) -> tuple[Path, Path]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "uyap-fixture")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("*.uyap.gov.tr")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = directory / "cert.pem", directory / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


class _Lab:
    def __init__(self, context, worker, api_port):
        self.context, self.worker, self.api_port = context, worker, api_port

    @property
    def uploads(self) -> list[dict]:
        return _ApiHandler.uploads

    def configure(self, **overrides):
        settings = {
            "apiUrl": f"http://127.0.0.1:{self.api_port}/api/public/v1/documents/upload",
            "apiKey": TOKEN,
            "throttleMs": 500,
            "autoSync": False,
            "saveLocal": False,
            **overrides,
        }
        self.worker.evaluate("(settings) => chrome.storage.sync.set(settings)", settings)
        self.worker.evaluate("() => sentHashes.clear()")  # testler birbirinin "gönderildi" kaydını görmesin
        _ApiHandler.uploads.clear()

    def downloads(self) -> list[str]:
        return self.worker.evaluate("() => chrome.downloads.search({}).then((r) => r.map((x) => x.filename))")

    def open(self, path: str):
        page = self.context.new_page()
        page.goto(BASE + path)
        page.wait_for_timeout(1800)  # içerik betiği + 600 ms'lik MutationObserver beklemesi
        return page

    def wait_for_uploads(self, count: int, timeout: float = 25.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.uploads) >= count:
                return True
            time.sleep(0.2)
        return False


@pytest.fixture(scope="module")
def lab():
    sync_api = pytest.importorskip("playwright.sync_api")
    workdir = Path(tempfile.mkdtemp(prefix="nhr-uyap-"))
    cert, key = _self_signed(workdir)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)

    uyap = ThreadingHTTPServer(("127.0.0.1", 0), _UyapHandler)
    uyap.socket = tls.wrap_socket(uyap.socket, server_side=True)
    api = ThreadingHTTPServer(("127.0.0.1", 0), _ApiHandler)
    for server in (uyap, api):
        threading.Thread(target=server.serve_forever, daemon=True).start()

    playwright = sync_api.sync_playwright().start()
    context = None
    try:
        context = playwright.chromium.launch_persistent_context(
            str(workdir / "profile"),
            headless=False,
            ignore_https_errors=True,
            args=[
                "--headless=new",
                f"--disable-extensions-except={EXTENSION_DIR}",
                f"--load-extension={EXTENSION_DIR}",
                f"--host-resolver-rules=MAP *.uyap.gov.tr 127.0.0.1:{uyap.server_address[1]}",
                "--ignore-certificate-errors",
            ],
        )
        context.set_default_timeout(30000)
        worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker")
        yield _Lab(context, worker, api.server_address[1])
    finally:
        if context is not None:
            context.close()
        playwright.stop()
        uyap.shutdown()
        api.shutdown()
        shutil.rmtree(workdir, ignore_errors=True)


def _buttons(page) -> int:
    return page.locator(".jurisai-send-btn").count()


def _toolbar(page) -> int:
    return page.locator(".jurisai-toolbar").count()


def test_no_buttons_on_login_or_home_pages(lab):
    lab.configure()
    for path in ("/giris", "/main", "/main-numbered"):
        page = lab.open(path)
        assert (_buttons(page), _toolbar(page)) == (0, 0), path
        page.close()
    assert lab.uploads == []


def test_evrak_list_gets_one_button_per_row_with_correct_metadata(lab):
    lab.configure()
    page = lab.open("/dosya/evraklar")
    assert _buttons(page) == 3
    assert _toolbar(page) == 1

    page.locator(".jurisai-send-btn").first.click()
    assert lab.wait_for_uploads(1)
    upload = lab.uploads[0]
    assert upload["file"]["data"].startswith(b"%PDF")
    assert upload["fields"]["dosyaEsasNo"] == "2025/412"
    assert upload["fields"]["evrakTuru"] == "Dilekçe"
    assert upload["fields"]["source"] == "uyap-avukat-eklentisi"
    page.close()


def test_row_with_view_and_download_links_uses_the_download_link(lab):
    lab.configure()
    page = lab.open("/dosya/evraklar")
    page.locator(".jurisai-send-btn").nth(2).click()
    assert lab.wait_for_uploads(1)
    assert lab.uploads[0]["file"]["data"] == _pdf("103")  # /evrak/indir?id=103, "goster" değil
    page.close()


def test_local_copy_is_off_by_default_and_on_when_enabled(lab):
    lab.configure(saveLocal=False)
    before = len(lab.downloads())
    page = lab.open("/dosya/evraklar")
    page.locator(".jurisai-send-btn").first.click()
    assert lab.wait_for_uploads(1)
    assert len(lab.downloads()) == before
    page.close()

    lab.configure(saveLocal=True)
    page = lab.open("/dosya/evraklar")
    page.locator(".jurisai-send-btn").first.click()
    assert lab.wait_for_uploads(1)
    time.sleep(1)
    assert len(lab.downloads()) == before + 1
    page.close()


def test_bulk_transfer_asks_for_confirmation(lab):
    lab.configure()
    page = lab.open("/dosya/evraklar")

    page.once("dialog", lambda dialog: dialog.dismiss())
    page.locator(".jurisai-send-all").click()
    page.wait_for_timeout(2500)
    assert lab.uploads == []

    page.once("dialog", lambda dialog: dialog.accept())
    page.locator(".jurisai-send-all").click()
    assert lab.wait_for_uploads(3, timeout=30)
    page.close()


def test_opening_a_case_does_not_upload_anything_when_auto_sync_is_off(lab):
    lab.configure(autoSync=False)
    page = lab.open("/dosya/pencere")
    page.click("#t2")  # avukat Evrak sekmesini kendisi açar
    page.wait_for_timeout(6000)
    assert lab.uploads == [], "otomatik aktarım kapalıyken kendiliğinden gönderim olmamalı"
    assert _buttons(page) == 3  # elle aktarım için düğmeler yine de çıkar
    page.close()


def test_auto_sync_uploads_documents_only_when_explicitly_enabled(lab):
    lab.configure(autoSync=True)
    page = lab.open("/dosya/pencere")
    assert lab.wait_for_uploads(3, timeout=30), "açık onaylı otomatik aktarım evrakları göndermeli"
    page.close()


def test_background_refuses_auto_ingest_when_setting_is_off(lab):
    lab.configure(autoSync=False)
    result = lab.worker.evaluate(
        "() => handleAutoIngest({ docUrls: ['https://avukat.uyap.gov.tr/evrak/indir?id=101'], dosyaEsasNo: '2025/412' })"
    )
    assert result["ok"] is False
    assert "kapalı" in result["error"]
    assert lab.uploads == []


def _wait_status(page, text: str, timeout: float = 10.0) -> str:
    """Eklenti sayfaları metin olarak JS çalıştırmayı (CSP) yasakladığından wait_for_function yerine yoklama."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = page.inner_text("#status")
        if text in current:
            return current
        time.sleep(0.2)
    raise AssertionError(f"durum satırında {text!r} görünmedi; şu an: {page.inner_text('#status')!r}")


def _popup(lab):
    extension_id = lab.worker.url.split("/")[2]
    page = lab.context.new_page()
    page.goto(f"chrome-extension://{extension_id}/popup.html")
    page.wait_for_timeout(500)
    return page


def test_popup_buttons_work_and_defaults_are_filled(lab):
    """popup.html bir dönem popup.js'i hiç yüklemiyordu: düğmeler tepkisizdi, alanlar boştu."""
    lab.configure(apiUrl="", apiKey=TOKEN)
    page = _popup(lab)
    assert page.input_value("#apiUrl").endswith("/api/public/v1/documents/upload")  # varsayılan dolduruldu
    assert page.input_value("#apiKey") == TOKEN

    page.fill("#apiUrl", f"http://127.0.0.1:{lab.api_port}/api/public/v1/documents/upload")
    page.click("#test")
    assert "✓" in _wait_status(page, "hazır")

    page.fill("#apiKey", "jsai_" + "z" * 44)
    page.click("#test")
    assert "Geçersiz bağlantı anahtarı" in _wait_status(page, "Ulaşılamadı")
    page.close()


def test_auto_sync_needs_consent_and_defaults_to_off(lab):
    lab.configure(autoSync=False, saveLocal=False)
    page = _popup(lab)
    assert page.is_checked("#autoSync") is False
    assert page.is_checked("#saveLocal") is False

    page.once("dialog", lambda dialog: dialog.dismiss())  # onay reddedilirse kutu geri kapanır
    page.click("#autoSync")
    assert page.is_checked("#autoSync") is False

    page.once("dialog", lambda dialog: dialog.accept())
    page.check("#autoSync")
    assert page.is_checked("#autoSync") is True
    page.click("#save")
    _wait_status(page, "kaydedildi")
    stored = lab.worker.evaluate("() => chrome.storage.sync.get(['autoSync', 'autoSyncConsentAt'])")
    assert stored["autoSync"] is True
    assert stored["autoSyncConsentAt"]
    page.close()


def test_page_diagnosis_reports_structure_only_never_content(lab):
    """Gerçek UYAP'ta seçiciler tutmazsa avukat "Sayfa tanısını kopyala" ile yapı özeti gönderir."""
    lab.configure()
    page = lab.open("/dosya/evraklar")
    assert _buttons(page) == 3

    reports = lab.worker.evaluate(
        """async () => {
            const [tab] = await chrome.tabs.query({ url: '*://*.uyap.gov.tr/dosya/*' });
            const frames = await chrome.scripting.executeScript({
                target: { tabId: tab.id, allFrames: true },
                func: () => (typeof window.__jurisaiDiagnose === 'function' ? window.__jurisaiDiagnose() : null),
            });
            return frames.map((frame) => frame.result).filter(Boolean);
        }"""
    )

    assert len(reports) == 1
    report = reports[0]
    assert report["caseContext"] is True
    assert report["rowsWithDocUrls"] == 3 and report["buttonsInjected"] == 3 and report["toolbar"] is True
    assert report["frame"] == "üst" and report["host"] == "avukat.uyap.gov.tr"
    assert report["extensionVersion"] == json.loads((EXTENSION_DIR / "manifest.json").read_text("utf-8"))["version"]
    shapes = {item["shape"] for item in report["docUrlShapes"]}
    assert "/evrak/indir?id" in shapes and "/evrak/indir?id,tip" in shapes
    serialized = json.dumps(report, ensure_ascii=False)
    # Hiçbir metin, taraf/dosya bilgisi, sayı ya da bağlantı değeri sızmaz.
    for leaked in ("Dilekçe", "Bilirkişi", "Tensip", "2025/412", "İstanbul", "id=101", "udf", "TOKEN"):
        assert leaked not in serialized
    assert not any(char.isdigit() for item in report["docUrlShapes"] for char in item["shape"])
    page.close()


def test_diagnose_button_explains_when_the_tab_is_not_a_uyap_page(lab):
    lab.configure()
    page = _popup(lab)  # etkin sekme eklentinin kendi sayfası: UYAP değil
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.click("#diagnose")
    assert "UYAP sayfası değil" in _wait_status(page, "UYAP sayfası")
    page.close()


def test_case_list_page_with_help_pdfs_uploads_nothing_even_with_auto_sync(lab):
    """Canlıda görülen hata: dava satırına tıklanınca sayfadaki kılavuz PDF'leri o davanın evrakı diye
    (dava satırının adıyla) defalarca gönderilmişti."""
    lab.configure(autoSync=True)
    page = lab.open("/vatandas/dosya-sorgulama")
    # Dava satırlarında "Dosyayı aç" düğmesi olabilir; ama hiçbir satır EVRAK satırı sayılmamalı.
    assert page.locator(".jurisai-send-btn:not(.jurisai-open-btn)").count() == 0
    page.locator("#r1 td").first.click()
    page.locator("#r2 td").nth(1).click()
    page.wait_for_timeout(9000)  # tıklama sonrası 0,9 / 2,5 / 6 sn'lik taramalar bitsin
    assert lab.uploads == [], [upload["file"]["name"] for upload in lab.uploads]
    page.close()


def test_diagnosis_on_the_case_list_page_finds_no_evrak_links(lab):
    lab.configure()
    page = lab.open("/vatandas/dosya-sorgulama")
    report = lab.worker.evaluate(
        """async () => {
            const [tab] = await chrome.tabs.query({ url: '*://*.uyap.gov.tr/vatandas/*' });
            const frames = await chrome.scripting.executeScript({
                target: { tabId: tab.id, allFrames: true },
                func: () => (typeof window.__jurisaiDiagnose === 'function' ? window.__jurisaiDiagnose() : null),
            });
            return frames.map((frame) => frame.result).filter(Boolean)[0];
        }"""
    )
    assert report["rowsWithDocUrls"] == 0  # kılavuz/yardım bağlantıları evrak sayılmaz
    assert report["docUrlShapes"] == []
    page.close()


def test_automatic_sync_sends_the_same_content_only_once_per_session(lab):
    lab.configure(autoSync=True)
    ingest = (
        "(name) => handleAutoIngest({ docUrls: ['https://avukat.uyap.gov.tr/evrak/indir?id=101'], "
        "dosyaEsasNo: '2025/412', mahkeme: name })"
    )
    first = lab.worker.evaluate(ingest, "Dava A")
    second = lab.worker.evaluate(ingest, "Dava B")  # aynı içerik başka bir ad/dava altında
    assert first["ok"] and first["files"] == 1
    assert second["ok"] and second["files"] == 0
    # Yinelenen evrak atlandığında dosya künyesi (taraf adı dahil) de yeniden gönderilmez.
    assert len(lab.uploads) == 1


def test_a_manual_send_is_never_blocked_by_the_duplicate_memory(lab):
    lab.configure(autoSync=False)
    send = (
        "() => handleUpload({ url: 'https://avukat.uyap.gov.tr/evrak/indir?id=101', "
        "evrakAdi: 'A', dosyaEsasNo: '2025/412' })"
    )
    assert lab.worker.evaluate(send)["ok"] and lab.worker.evaluate(send)["ok"]
    assert len(lab.uploads) == 2  # kullanıcı belgeyi sildikten sonra yeniden gönderebilir


def test_documents_are_never_fetched_from_outside_uyap(lab):
    lab.configure(autoSync=False)
    result = lab.worker.evaluate(
        "() => handleUpload({ url: 'https://cdn.e-devlet.gov.tr/downloads/portal/Kilavuz.pdf', evrakAdi: 'x' })"
    )
    assert result["ok"] is False and "UYAP dışı" in result["error"]
    assert lab.uploads == []


def test_diagnosis_describes_a_tree_based_evrak_list_without_leaking_its_content(lab):
    """Gerçek Vatandaş Portalı'nda evrak listesi klasör ağacı: tanı bu yapıyı ANLATIR, metni/adı sızdırmaz."""
    lab.configure()
    page = lab.open("/vatandas/evrak-agaci")
    report = lab.worker.evaluate(
        """async () => {
            const [tab] = await chrome.tabs.query({ url: '*://*.uyap.gov.tr/vatandas/*' });
            const frames = await chrome.scripting.executeScript({
                target: { tabId: tab.id, allFrames: true },
                func: () => (typeof window.__jurisaiDiagnose === 'function' ? window.__jurisaiDiagnose() : null),
            });
            return frames.map((frame) => frame.result).filter(Boolean)[0];
        }"""
    )
    assert report["scope"] == "açık pencere"
    assert report["tree"]["count"] >= 2 and any(item["isLeaf"] for item in report["tree"]["sample"])
    assert any(item["onclickFunction"].startswith("openNode(") for item in report["tree"]["sample"])
    assert "Ön İzlemeyi Aktifleştir" in report["buttonLabels"]
    assert "Evrak" in report["tabLabels"]
    assert any("jstree-anchor" in item["element"] for item in report["structure"])
    serialized = json.dumps(report, ensure_ascii=False)
    for leaked in ("SIRRI-EVRAK-ADI", "Gizli Klasör", "Ahmet", "Mehmet", "1234567", "99887", "Test Mahkemesi"):
        assert leaked not in serialized, leaked
    page.close()


def _saved_json_reports(lab) -> list[dict]:
    """Eklentinin yazdığı JSON raporları. Playwright indirmeleri GUID adlı dosyaya aldığından ad yerine
    MIME türü ve içerikle bulunur."""
    names = lab.worker.evaluate(
        "() => chrome.downloads.search({}).then((items) => items.filter((x) => x.mime === 'application/json').map((x) => x.filename))"
    )
    return [json.loads(Path(name).read_text("utf-8")) for name in names if Path(name).is_file()]


def test_click_recording_captures_what_a_tree_leaf_does_without_leaking_content(lab):
    """Gerçek UYAP'ta yaprağa tıklayınca ne olduğu tarif ettirilmeden kaydedilir; ad/metin/değer sızmaz."""
    lab.configure()
    page = lab.open("/vatandas/evrak-agaci-tikla")
    tab_id = lab.worker.evaluate(
        """async () => {
            const [tab] = await chrome.tabs.query({ url: '*://*.uyap.gov.tr/vatandas/*' });
            await chrome.tabs.sendMessage(tab.id, { type: 'JURISAI_RECORD_START', seconds: 30 });
            return tab.id;
        }"""
    )
    page.wait_for_timeout(600)
    page.locator("#yaprak").click()
    page.wait_for_timeout(1500)
    stopped = lab.worker.evaluate(
        "(id) => chrome.tabs.sendMessage(id, { type: 'JURISAI_RECORD_STOP' })", tab_id
    )
    assert stopped["ok"], stopped
    assert stopped["file"].startswith("NHR-Hukuk-UYAP/tani-kayit-")
    page.wait_for_timeout(1200)

    [report] = [item for item in _saved_json_reports(lab) if item.get("kind") == "tıklama kaydı"]
    events = report["events"]
    clicks = [event for event in events if event["kind"] == "click"]
    assert clicks and clicks[0]["target"]["chain"][0].startswith("a.jstree-anchor")
    assert "data-evrak-id" in clicks[0]["target"]["attributeNames"]
    resources = [event for event in events if event["kind"] == "resource"]
    assert any(
        event["initiator"] == "xmlhttprequest" and event["url"] == "/evrak/onizleme-verisi?evrakId" for event in resources
    ), resources
    added = [event for event in events if event["kind"] == "dom_added" and event["tag"] == "iframe"]
    assert added and added[0]["src"] == "/evrak/onizleme?id"
    assert report["diagnosisAtEnd"]["tree"]["count"] >= 1
    serialized = json.dumps(report, ensure_ascii=False)
    for leaked in ("SIRRI-YAPRAK-ADI", "Mehmet", "evrakId=55", "id=55", "2024/2000"):
        assert leaked not in serialized, leaked
    assert lab.uploads == []  # kayıt hiçbir şey göndermez
    page.close()


def test_diagnosis_is_also_saved_as_a_file(lab):
    lab.configure()
    page = lab.open("/vatandas/evrak-agaci")
    saved = lab.worker.evaluate("() => saveReportFile('tani', { reports: [{ ornek: true }] })")
    assert saved.startswith("NHR-Hukuk-UYAP/tani-")
    page.wait_for_timeout(1000)
    assert {"reports": [{"ornek": True}]} in _saved_json_reports(lab)
    page.close()


def test_network_recording_sees_the_request_made_inside_the_preview_iframe_without_leaking_values(lab):
    """Evrak iframe'in içinde gelir: ana sayfa kaydı bunu göremez, tarayıcı düzeyindeki ağ kaydı görür."""
    lab.configure()
    page = lab.open("/vatandas/onizleme-post")
    tab_id = lab.worker.evaluate(
        """async () => {
            const [tab] = await chrome.tabs.query({ url: '*://*.uyap.gov.tr/vatandas/*' });
            await chrome.tabs.sendMessage(tab.id, { type: 'JURISAI_RECORD_START', seconds: 30 }, { frameId: 0 });
            return tab.id;
        }"""
    )
    page.wait_for_timeout(600)
    page.locator("#yaprak2").click()
    page.wait_for_timeout(2000)
    stopped = lab.worker.evaluate(
        "(id) => chrome.tabs.sendMessage(id, { type: 'JURISAI_RECORD_STOP' }, { frameId: 0 })", tab_id
    )
    assert stopped["ok"], stopped
    page.wait_for_timeout(1200)

    # Aynı oturumda önceki testlerin kayıtları da var: bu testin kaydı ağ olayını içeren.
    [report] = [
        item
        for item in _saved_json_reports(lab)
        if any(e.get("url", "").endswith("/evrak/onizleme-gonder") for e in item.get("backgroundEvents", []))
    ]
    background = report["backgroundEvents"]
    requests = [e for e in background if e["kind"] == "request" and e["url"].endswith("/evrak/onizleme-gonder")]
    assert requests, background
    request = requests[0]
    assert request["method"] == "POST" and request["type"] == "sub_frame" and request["frameId"] != 0
    assert sorted(request["bodyFields"]) == ["evrakId", "gizliDeger"]
    responses = [e for e in background if e["kind"] == "response" and e["id"] == request["id"]]
    assert responses and responses[0]["contentType"] == "application/pdf"
    assert responses[0]["disposition"] == "inline" and responses[0]["status"] == 200
    serialized = json.dumps(report, ensure_ascii=False)
    for leaked in ("TOPSECRET", "SIRRI-ONIZLEME-ADI", "Mehmet", "gizli-ad", "evrakId=77"):
        assert leaked not in serialized, leaked
    assert lab.uploads == []
    page.close()


_PULL = (
    "async () => {"
    "  const [tab] = await chrome.tabs.query({ url: '*://*.uyap.gov.tr/vatandas/*' });"
    "  return chrome.tabs.sendMessage(tab.id, { type: 'JURISAI_PULL_DOSYA' }, { frameId: 0 });"
    "}"
)


def test_pulling_a_case_creates_one_upload_per_evrak_with_its_folder_path(lab):
    """Gerçek akış: ağaç açılır, ön izleme açılır, her yaprağa tıklanır, UYAP'ın ön izleme adresi yakalanıp belge
    ODT olarak indirilir; 'Son 20 Evrak' kısayolu çift saymaz; klasör yolu ve evrak türü gönderilir."""
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-agaci")
    page.on("dialog", lambda dialog: dialog.accept())

    result = lab.worker.evaluate(_PULL)

    assert result["ok"] and result["sent"] == 4 and result["failed"] == 0, result
    assert result["found"] == 4  # 101-104; "Son 20" kısayolundaki kopyalar (farklı kimlikli) hiç sayılmaz
    uploads = {upload["fields"]["evrakId"]: upload for upload in lab.uploads}
    assert sorted(uploads) == ["101", "102", "103", "104"]
    for upload in uploads.values():
        assert upload["file"]["data"].startswith(b"PK") and upload["file"]["name"].endswith(".odt")
        assert upload["fields"]["dosyaEsasNo"] == "2024/2000"
        assert upload["fields"]["birim"] == "Ankara Bölge Adliye Mahkemesi 19. Ceza Dairesi"
    assert uploads["101"]["fields"]["klasorYolu"] == "2024/2000 (Ceza Dava Dosyası) / Kesinleşme Şerhleri"
    assert uploads["101"]["fields"]["evrakTuru"] == "Kesinleşme Şerhleri"
    # Ek, bağlı olduğu evrakın altında durur.
    assert uploads["104"]["fields"]["klasorYolu"] == (
        "2024/2000 (Ceza Dava Dosyası) / Gerekçeli Karar / Gerekçeli Karar 30/06/2025"
    )
    # Aynı başlıklı iki evrak (101, 102) ayrı belge olarak gelir (içerikleri farklı).
    assert uploads["101"]["file"]["data"] != uploads["102"]["file"]["data"]
    page.close()


def test_pulling_asks_for_confirmation_and_sends_nothing_when_declined(lab):
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-agaci")
    page.on("dialog", lambda dialog: dialog.dismiss())

    result = lab.worker.evaluate(_PULL)

    assert result["ok"] and result["cancelled"] and result["found"] == 4
    assert lab.uploads == []
    page.close()


def test_preview_that_is_already_on_is_not_switched_off(lab):
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-agaci")
    page.click("#onizleme")  # kullanıcı ön izlemeyi zaten açmış
    page.on("dialog", lambda dialog: dialog.accept())

    result = lab.worker.evaluate(_PULL)

    assert result["ok"] and result["sent"] == 4, result
    assert page.inner_text("#onizleme") == "Ön İzlemeyi Kapat"  # eklenti düğmeye ikinci kez basmadı
    page.close()


def test_pulling_needs_the_connection_key_before_touching_the_portal(lab):
    lab.configure(apiKey="")
    page = lab.open("/vatandas/dosya-agaci")

    result = lab.worker.evaluate(_PULL)

    assert result["ok"] is False and "anahtar" in result["error"].lower()
    assert lab.uploads == []
    assert page.locator("iframe").count() == 0  # ağaç/önizleme'ye dokunulmadı
    page.close()


def test_pulling_without_an_open_case_window_explains_what_to_do(lab):
    lab.configure()
    page = lab.open("/vatandas/evrak-agaci-tikla")  # açık pencere var ama evrak ağacı/ön izleme düğmesi yok
    result = lab.worker.evaluate(
        "async () => { const [tab] = await chrome.tabs.query({ url: '*://*.uyap.gov.tr/vatandas/*' });"
        " return chrome.tabs.sendMessage(tab.id, { type: 'JURISAI_PULL_DOSYA' }, { frameId: 0 }); }"
    )
    assert result["ok"] is False and "Ön izleme" in result["error"]
    assert lab.uploads == []
    page.close()


def test_pull_errors_are_reported_with_their_reason(lab):
    """Önceki sürümde yalnız "8 hata" yazıyordu; neden görünmediği için gerçek portalda teşhis edilemedi."""
    lab.configure(throttleMs=500, apiKey="jsai_" + "z" * 44)  # geçersiz anahtar: sunucu 401 döner
    page = lab.open("/vatandas/dosya-agaci")
    page.on("dialog", lambda dialog: dialog.accept())

    result = lab.worker.evaluate(_PULL)

    assert result["ok"] and result["sent"] == 0 and result["failed"] >= 1
    assert any("anahtar" in error.lower() for error in result["errors"]), result["errors"]
    assert lab.uploads == []
    page.close()


def test_a_click_that_triggers_no_request_is_explained_in_the_error(lab):
    """Ön izleme açılmazsa (ya da UYAP tıklamaya yanıt vermezse) neden bildirimde yazar."""
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-agaci")
    # Eklenti ön izlemeyi açar; sahte sayfada açıkken yapraklar istek yapar. Burada düğmeyi önce açıp ardından
    # sayfanın tıklama işleyicisini kaldırarak "tıklama hiçbir şey yapmıyor" durumunu üretiriz.
    page.evaluate("() => { window.preview = true; document.getElementById('onizleme').textContent = 'Ön İzlemeyi Kapat'; }")
    page.evaluate("() => { document.addEventListener('click', (e) => e.stopImmediatePropagation(), true); }")
    page.on("dialog", lambda dialog: dialog.accept())

    result = lab.worker.evaluate(_PULL)

    assert result["ok"] and result["sent"] == 0 and result["failed"] >= 1
    assert any("hiç istek yapmadı" in error for error in result["errors"]), result["errors"]
    page.close()


_PULL_DISK = _PULL.replace("'JURISAI_PULL_DOSYA' }", "'JURISAI_PULL_DOSYA', mode: 'disk' }")


def test_download_path_keeps_the_uyap_folder_structure_and_is_filesystem_safe(lab):
    lab.configure()
    path = lab.worker.evaluate(
        """() => folderDownloadPath({
            dosyaEsasNo: '2024/2000', birim: 'Ankara Bölge Adliye Mahkemesi 19. Ceza Dairesi',
            klasorYolu: '2024/2000 (Ceza Dava Dosyası) / Gerekçeli Karar', evrakAdi: 'Gerekçeli Karar 30/06/2025',
        }, 'application/vnd.oasis.opendocument.text')"""
    )
    assert path == (
        "JurisAI-UYAP/2024 2000 Ankara Bölge Adliye Mahkemesi 19. Ceza Dairesi/"
        "2024 2000 (Ceza Dava Dosyası)/Gerekçeli Karar/Gerekçeli Karar 30 06 2025.odt"
    )
    hostile = lab.worker.evaluate(
        """() => folderDownloadPath({
            dosyaEsasNo: '..', birim: '', klasorYolu: '../.. / a:b*c? / "x" ', evrakAdi: 'ad<>|."', }, 'application/pdf')"""
    )
    assert ".." not in hostile.replace("JurisAI-UYAP", "").split("/")  # dizin geçişi yok
    assert not any(char in hostile for char in ['<', '>', ':', '"', '|', '?', '*', chr(92)])
    assert hostile.startswith("JurisAI-UYAP/") and hostile.endswith(".pdf")


def test_pulling_to_disk_needs_no_connection_key_and_sends_nothing_to_jurisai(lab):
    """"UYAP'tan klasör olarak indir": JurisAI'ya bağlanmaz (anahtar boş olabilir), her evrak diske yazılır."""
    lab.configure(throttleMs=500, apiKey="")
    page = lab.open("/vatandas/dosya-agaci")
    page.on("dialog", lambda dialog: dialog.accept())
    before = lab.worker.evaluate(
        "() => chrome.downloads.search({}).then((items) => items.filter((x) => x.mime === 'application/vnd.oasis.opendocument.text').length)"
    )

    result = lab.worker.evaluate(_PULL_DISK)

    assert result["ok"] and result["sent"] == 4 and result["failed"] == 0, result
    assert lab.uploads == []
    page.wait_for_timeout(1500)
    after = lab.worker.evaluate(
        "() => chrome.downloads.search({}).then((items) => items.filter((x) => x.mime === 'application/vnd.oasis.opendocument.text').length)"
    )
    assert after - before == 4
    page.close()
