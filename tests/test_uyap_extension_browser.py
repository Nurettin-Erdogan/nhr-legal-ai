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

    def do_GET(self):  # noqa: N802
        path, _, query = self.path.partition("?")
        if path in PAGES:
            return self._send(200, PAGES[path].encode(), "text/html; charset=utf-8")
        if path == "/evrak/indir":
            doc_id = query.split("id=")[-1].split("&")[0]
            if "tip=udf" in query:
                return self._send(200, _udf(f"Bilirkişi raporu {doc_id}"), "application/zip")
            return self._send(200, _pdf(doc_id), "application/pdf")
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
