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
    # Dosya listesi + gizli dosya penceresi (ağaçlı): satır düğmesi pencereyi açar.
    "/vatandas/dosya-listesi": "@@LISTE@@",
    # Gerçekçi evrak listesi.
    "/dosya/evraklar": f"<html><body><h2>{CASE_TITLE}</h2>{_EVRAK_ROWS}</body></html>",
    # Dosya penceresi: Evrak sekmesine basılınca liste AJAX ile gelir.
    "/dosya/pencere": f"""<html><body><div role="dialog" class="modal">
      <h4 class="modal-title">{CASE_TITLE}</h4>
      <ul class="nav"><li><a id="t1">Taraf Bilgileri</a></li><li><a id="t2">Evrak</a></li></ul>
      <div id="panel">Davacı: Ahmet Yılmaz Davalı: Örnek İnşaat A.Ş.</div></div>
      <script>
        // Bootstrap sekmesi bağlantıda dinlenir: onu saran li'ye tıklamak sekmeyi açmaz.
        document.querySelector('#t2').addEventListener('click', function (event) {{
          if (event.target.textContent.trim() !== 'Evrak') return;
          setTimeout(function () {{ document.getElementById('panel').innerHTML = `{_EVRAK_ROWS}`; }}, 150);
        }});
      </script></body></html>""",
}


PAGES["/vatandas/dosya-listesi"] = PAGES["/vatandas/dosya-agaci"].replace(
    '<div role="dialog" class="modal in" style="display:block">',
    '<div class="page-sidebar"><ul><li><a href="/main/jsp/vatandas/index.jsp?menuId=1#evrak">Evrak Sorgulama</a></li></ul></div>'
    '<table><tr><td>Katılan</td><td>Ankara Bölge Adliye Mahkemesi 19. Ceza Dairesi</td><td>2024/2000</td><td>'
    "<button type=\"button\" onclick=\"document.getElementById('dlg').style.display='block'\">Dosya Görüntüle</button>"
    '</td></tr></table><div id="dlg" role="dialog" class="modal in" style="display:none">',
)


BIRIM = "Ankara Bölge Adliye Mahkemesi 19. Ceza Dairesi"
EK_STABLE = f"ek:103:Ek 1@{BIRIM}"  # fikstürdeki ek (evrak_id="104", ana_evrak_id="103"): eklenti ekleri bu kalıcı kimlikle gönderir


def _legacy(evrak_id: str) -> str:
    """Eski testlerin ek için kullandığı "104" adını korur (UYAP şifreli evrak_id'yi her yüklemede değiştirir; eklenti kalıcı kimlik kullanır)."""
    return "104" if evrak_id == EK_STABLE else evrak_id


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
        if path == "/dosya/sorgu":  # Dosya Sorgulama: yargı türüne göre satırlar (JSON)
            tur = query.split("tur=")[-1].split("&")[0]
            return self._send(200, json.dumps(_real_rows(tur), ensure_ascii=False).encode(), "application/json; charset=utf-8")
        if path == "/dosya/mahkemeler":
            tur = query.split("tur=")[-1].split("&")[0]
            courts = sorted({row["birim"] for row in _real_rows(tur)})
            return self._send(200, json.dumps(courts, ensure_ascii=False).encode(), "application/json; charset=utf-8")
        if path == "/evrak/indir":
            doc_id = query.split("id=")[-1].split("&")[0]
            if "tip=udf" in query:
                return self._send(200, _udf(f"Bilirkişi raporu {doc_id}"), "application/zip")
            return self._send(200, _pdf(doc_id), "application/pdf")
        if path == "/main/jsp/viewer.jsp":
            # Gerçek portaldan öğrenilen davranışlar: (1) önizleme, ilk istekten ~2 sn sonra AYNI belgeyi bir kez daha ister
            # (gecikmiş ikinci aşama; sonraki yaprağın yakalamasına karışmamalı); (2) önizlenemeyen evrakta (TIFF) belge yerine
            # kısa bir mesaj döner ve gerçek dosya AYRI bir istekle (attachment) indirilir.
            page = (
                "<html><body><script>var q = location.search;"
                "fetch('/main/jsp/view_document_brd.uyap' + q, {credentials: 'include'});"
                "setTimeout(function () { fetch('/main/jsp/view_document_brd.uyap' + q, {credentials: 'include'}); }, 2200);"
                "if (q.indexOf('ENC104') >= 0) fetch('/main/jsp/evrak_indir.uyap' + q, {credentials: 'include'});"
                "</script></body></html>"
            )
            return self._send(200, page.encode(), "text/html; charset=utf-8")
        if path == "/main/jsp/view_document_brd.uyap":
            evrak_id = query.split("evrakId=")[-1].split("&")[0].removeprefix("ENC")
            if evrak_id == "109":
                message = "Görüntülemek istediğiniz evrakın boyutu çok büyük! Lütfen evrakı sisteminize kaydederek görüntüleyiniz."
                return self._send(200, message.encode(), "text/plain; charset=utf-8")
            if evrak_id in ("107", "108"):
                body = "<html><body>VEKALET PULU MAKBUZU T.C. ADALET BAKANLIĞI Makbuz No 123"
                if evrak_id == "108":
                    body += '<input type="password">'
                return self._send(200, (body + "</body></html>").encode(), "text/html; charset=utf-8")
            if evrak_id == "105":  # geçici: ilk istekte kısa mesaj, sonra belge
                _UyapHandler.seen_105 = getattr(_UyapHandler, "seen_105", 0) + 1
                if _UyapHandler.seen_105 == 1:
                    return self._send(200, "Sistem şu an yoğun 12345, lütfen tekrar deneyin.".encode(), "text/plain; charset=utf-8")
            if evrak_id == "106":  # kalıcı: hep kısa mesaj
                return self._send(200, "Bu evrağı görüntüleme yetkiniz yok (kod 777).".encode(), "text/plain; charset=utf-8")
            if evrak_id == "104":  # TIFF: belge yerine kısa mesaj
                message = "Bu evrak türü (Tiff) görüntülenemediğinden dolayı evrak indiriliyor.".encode()
                return self._send(200, message, "text/plain; charset=utf-8")
            data = _odt(f"Evrak {evrak_id} metni")
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.oasis.opendocument.text")
            self.send_header("Content-Disposition", "attachment; filename=evrak.odt")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/main/jsp/download_document_brd.uyap":
            # Gerçek portalda ölçüldü (2026-10-05): "Kaydet" (downloadDoc) ön izlemenin eşi olan bu adresi aynı evrakId/dosyaId/
            # yargiTuru ile, `mimeType` OLMADAN ister; ön izlemenin "boyutu çok büyük" dediği evrak buradan gerçek dosyasıyla gelir.
            evrak_id = query.split("evrakId=")[-1].split("&")[0].removeprefix("ENC")
            if evrak_id != "109" or "mimeType=" in query:
                return self._send(404, b"yok", "text/plain")
            data = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"fake-jpeg-109" * 40
            self.send_response(200)
            self.send_header("Content-Type", "application/download")
            self.send_header("Content-Disposition", 'attachment; filename="vekaletname_109.jpg"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/main/jsp/evrak_indir.uyap":
            data = b"II*\x00" + b"fake-tiff-104" * 20
            self.send_response(200)
            self.send_header("Content-Type", "image/tiff")
            self.send_header("Content-Disposition", 'attachment; filename="evrak_104.tif"')
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
    known_ids: list[str] = []  # JurisAI'da "zaten var" sayılan evrak kimlikleri

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
        elif self.path.endswith("/documents/known"):
            wanted = json.loads(body or b"{}").get("evrakIds", [])
            payload = {"ok": True, "known": [i for i in wanted if i in type(self).known_ids]}
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
        self.worker.evaluate(
            "(settings) => { const { apiKey, ...rest } = settings; return Promise.all([chrome.storage.sync.set(rest), chrome.storage.local.set({ apiKey }), chrome.storage.sync.remove('apiKey')]); }",
            settings,
        )
        self.worker.evaluate("() => sentHashes.clear()")  # testler birbirinin "gönderildi" kaydını görmesin
        self.worker.evaluate("() => chrome.storage.local.set({ autoUpdate: false })")  # eklenti test sırasında kendini yeniden yüklemesin
        _ApiHandler.uploads.clear()
        _ApiHandler.known_ids.clear()

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
    assert report["frame"] == "üst" and report["host"] == "(UYAP)"
    assert report["extensionVersion"] == json.loads((EXTENSION_DIR / "manifest.json").read_text("utf-8"))["version"]
    shapes = {item["shape"] for item in report["docUrlShapes"]}
    assert any("?param" in shape for shape in shapes)
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
            const tab = (await chrome.tabs.query({ url: '*://*.uyap.gov.tr/vatandas/*' })).sort((a, b) => b.id - a.id)[0];
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
    assert result["ok"] is False and "UYAP adresinden" in result["error"]
    assert lab.uploads == []


def test_only_recognized_uyap_receipt_html_is_accepted(lab):
    result = lab.worker.evaluate("""async () => {
      const meta = { evrakTuru: 'Vekalet Pulu Makbuzu', evrakAdi: 'Vekalet Pulu Makbuzu' };
      const receipt = new Blob(['<html><body>VEKALET PULU MAKBUZU T.C. ADALET BAKANLIĞI Makbuz No 123</body></html>'], {type: 'text/html'});
      const login = new Blob(['<html><body>VEKALET PULU MAKBUZU T.C. ADALET BAKANLIĞI Makbuz No 123 <input type="password"></body></html>'], {type: 'text/html'});
      return [await isUyapReceipt(receipt, meta), await isUyapReceipt(login, meta),
              await isUyapReceipt(receipt, { evrakTuru: 'Karar' }), fileNameFor(meta, 'text/html')];
    }""")
    assert result == [True, False, False, "Vekalet Pulu Makbuzu.html"]


def test_turkish_legacy_encoded_receipt_is_recognized(lab):
    accepted = lab.worker.evaluate("""async () => {
      // Windows-1254: ASCII text plus uppercase Ğ at byte 0xD0.
      const raw = new Uint8Array([
        ...new TextEncoder().encode('<html><body>VEKALET PULU MAKBUZU T.C. ADALET BAKANLI'),
        0xD0,
        ...new TextEncoder().encode('I Makbuz No 123</body></html>'),
      ]);
      return await isUyapReceipt(new Blob([raw], { type: 'text/html; charset=windows-1254' }), {evrakTuru:'Makbuz'});
    }""")
    assert accepted is True


def test_receipt_response_is_downloaded_but_login_page_is_not(lab):
    result = lab.worker.evaluate("""async () => {
      const meta = { evrakTuru: 'Vekalet Pulu Makbuzu', evrakAdi: 'Vekalet Pulu Makbuzu' };
      const receipt = await fetchDocument('https://vatandas.uyap.gov.tr/main/jsp/view_document_brd.uyap?evrakId=ENC107', 5000, meta);
      let rejected = false;
      try {
        await fetchDocument('https://vatandas.uyap.gov.tr/main/jsp/view_document_brd.uyap?evrakId=ENC108', 5000, meta);
      } catch (error) { rejected = /belge yerine sayfa/.test(error.message); }
      return [receipt.type, receipt.blob.size > 30, fileNameFor(meta, receipt.type), rejected];
    }""")
    assert result == ["text/html", True, "Vekalet Pulu Makbuzu.html", True]


def test_oversized_uyap_preview_is_not_mistaken_for_a_document(lab):
    error = lab.worker.evaluate("""async () => {
      try {
        await fetchDocument('https://vatandas.uyap.gov.tr/main/jsp/view_document_brd.uyap?evrakId=ENC109', 5000);
        return 'unexpected success';
      } catch (caught) { return { message: caught.message, retryable: !!caught.retryable }; }
    }""")
    assert "UYAP'taki Kaydet" in error["message"]
    assert error["retryable"] is False


def test_diagnosis_describes_a_tree_based_evrak_list_without_leaking_its_content(lab):
    """Gerçek Vatandaş Portalı'nda evrak listesi klasör ağacı: tanı bu yapıyı ANLATIR, metni/adı sızdırmaz."""
    lab.configure()
    page = lab.open("/vatandas/evrak-agaci")
    report = lab.worker.evaluate(
        """async () => {
            const tab = (await chrome.tabs.query({ url: '*://*.uyap.gov.tr/vatandas/*' })).sort((a, b) => b.id - a.id)[0];
            const frames = await chrome.scripting.executeScript({
                target: { tabId: tab.id, allFrames: true },
                func: () => (typeof window.__jurisaiDiagnose === 'function' ? window.__jurisaiDiagnose() : null),
            });
            return frames.map((frame) => frame.result).filter(Boolean)[0];
        }"""
    )
    assert report["scope"] == "açık pencere"
    assert report["tree"]["count"] >= 2 and any(item["isLeaf"] for item in report["tree"]["sample"])
    assert any(item["hasOnclick"] for item in report["tree"]["sample"])
    assert report["buttonCount"] > 0
    assert report["tabCount"] > 0
    assert report["structure"]
    serialized = json.dumps(report, ensure_ascii=False)
    for leaked in ("SIRRI-EVRAK-ADI", "Gizli Klasör", "Ahmet", "Mehmet", "1234567", "99887", "Test Mahkemesi"):
        assert leaked not in serialized, leaked
    page.close()


def _saved_json_reports(lab, expected=lambda _item: True) -> list[dict]:
    """Eklentinin yazdığı JSON raporları. Playwright indirmeleri GUID adlı dosyaya aldığından ad yerine
    MIME türü ve içerikle bulunur."""
    deadline = time.monotonic() + 10
    while True:
        names = lab.worker.evaluate(
            "() => chrome.downloads.search({}).then((items) => items.filter((x) => x.mime?.startsWith('application/json') || x.filename?.endsWith('.json')).map((x) => x.filename))"
        )
        reports = [json.loads(Path(name).read_text("utf-8")) for name in names if Path(name).is_file()]
        if any(expected(item) for item in reports) or time.monotonic() >= deadline:
            return reports
        time.sleep(0.25)


def test_click_recording_captures_what_a_tree_leaf_does_without_leaking_content(lab):
    """Gerçek UYAP'ta yaprağa tıklayınca ne olduğu tarif ettirilmeden kaydedilir; ad/metin/değer sızmaz."""
    lab.configure()
    page = lab.open("/vatandas/evrak-agaci-tikla")
    tab_id = lab.worker.evaluate(
        """async () => {
            const tab = (await chrome.tabs.query({ url: '*://*.uyap.gov.tr/vatandas/*' })).sort((a, b) => b.id - a.id)[0];
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

    [report] = [item for item in _saved_json_reports(lab, lambda item: item.get("kind") == "tıklama kaydı") if item.get("kind") == "tıklama kaydı"]
    events = report["events"]
    clicks = [event for event in events if event["kind"] == "click"]
    assert clicks and clicks[0]["target"]["chain"][0].startswith("a.")
    assert "data-evrak-id" in clicks[0]["target"]["attributeNames"]
    resources = [event for event in events if event["kind"] == "resource"]
    assert any(event["initiator"] == "xmlhttprequest" and "?param" in event["url"] for event in resources), resources
    added = [event for event in events if event["kind"] == "dom_added" and event["tag"] == "iframe"]
    assert added and "?param" in added[0]["src"]
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
    expected = {"reports": [{"ornek": True}]}
    assert expected in _saved_json_reports(lab, lambda item: item == expected)
    page.close()


def test_network_recording_sees_the_request_made_inside_the_preview_iframe_without_leaking_values(lab):
    """Evrak iframe'in içinde gelir: ana sayfa kaydı bunu göremez, tarayıcı düzeyindeki ağ kaydı görür."""
    lab.configure()
    page = lab.open("/vatandas/onizleme-post")
    tab_id = lab.worker.evaluate(
        """async () => {
            const tab = (await chrome.tabs.query({ url: '*://*.uyap.gov.tr/vatandas/*' })).sort((a, b) => b.id - a.id)[0];
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
        for item in _saved_json_reports(
            lab,
            lambda item: any(e.get("kind") == "request" and e.get("type") == "sub_frame" and e.get("method") == "POST" for e in item.get("backgroundEvents", [])),
        )
        if any(e.get("kind") == "request" and e.get("type") == "sub_frame" and e.get("method") == "POST" for e in item.get("backgroundEvents", []))
    ]
    background = report["backgroundEvents"]
    requests = [e for e in background if e["kind"] == "request" and e.get("type") == "sub_frame" and e.get("method") == "POST"]
    assert requests, background
    request = requests[0]
    assert request["method"] == "POST" and request["type"] == "sub_frame" and request["frameId"] != 0
    assert request["bodyFieldCount"] == 2
    responses = [e for e in background if e["kind"] == "response" and e["id"] == request["id"]]
    assert responses and responses[0]["contentType"] == "application/pdf"
    assert responses[0]["disposition"] == "inline" and responses[0]["status"] == 200
    serialized = json.dumps(report, ensure_ascii=False)
    for leaked in ("TOPSECRET", "SIRRI-ONIZLEME-ADI", "Mehmet", "gizli-ad", "evrakId=77"):
        assert leaked not in serialized, leaked
    assert lab.uploads == []
    page.close()


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




# --- Evrak seçimi ve çekme (gerçek Vatandaş Portalı ağacı + seçim penceresi) --------------------------------


def _start_pull(lab, mode: str = "upload") -> None:
    """Çekmeyi başlatır ama beklemez: seçim penceresi çıkar, test onu kullanır, sonra _finish_pull sonucu alır."""
    lab.worker.evaluate(
        """async (mode) => {
            const tab = (await chrome.tabs.query({ url: '*://*.uyap.gov.tr/vatandas/*' })).sort((a, b) => b.id - a.id)[0];
            self.__pull = chrome.tabs.sendMessage(tab.id, { type: 'JURISAI_PULL_DOSYA', mode }, { frameId: 0 });
        }""",
        mode,
    )


def _finish_pull(lab) -> dict:
    return lab.worker.evaluate("() => self.__pull")


def _choose(page, action: str, uncheck: tuple[int, ...] = ()) -> None:
    page.wait_for_selector(".jurisai-chooser", timeout=30000)
    for index in uncheck:
        page.locator(f'.jurisai-pick-item[data-index="{index}"]').uncheck()
    page.click(f"#jurisai-pick-{action}")


def _pull(lab, page, action: str = "upload", uncheck: tuple[int, ...] = ()) -> dict:
    _start_pull(lab, action)
    _choose(page, action, uncheck)
    return _finish_pull(lab)


def test_pulling_a_case_creates_one_upload_per_evrak_with_its_folder_path(lab):
    """Gerçek akış: ağaç açılır, ön izleme açılır, kullanıcı seçer, her yaprağa tıklanır, UYAP'ın ön izleme adresi
    yakalanıp belge ODT olarak indirilir; 'Son 20 Evrak' kısayolu (farklı kimlikli kopyalar) sayılmaz."""
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-agaci")

    result = _pull(lab, page)

    assert result["ok"] and result["sent"] == 4 and result["failed"] == 0, result
    assert result["found"] == 4 and result["chosen"] == 4
    uploads = {_legacy(upload["fields"]["evrakId"]): upload for upload in lab.uploads}
    assert sorted(uploads) == ["101", "102", "103", "104"]
    for evrak_id, upload in uploads.items():
        if evrak_id == "104":  # TIFF: belge yerine mesaj geldi, ayrı indirme adresinden alındı
            assert upload["file"]["data"].startswith(b"II*") and upload["file"]["name"].endswith(".tif")
        else:
            assert upload["file"]["data"].startswith(b"PK") and upload["file"]["name"].endswith(".odt")
        assert upload["fields"]["dosyaEsasNo"] == "2024/2000"
        assert upload["fields"]["birim"] == "Ankara Bölge Adliye Mahkemesi 19. Ceza Dairesi"
    assert uploads["101"]["fields"]["klasorYolu"] == "2024/2000 (Ceza Dava Dosyası) / Kesinleşme Şerhleri"
    assert uploads["101"]["fields"]["evrakTuru"] == "Kesinleşme Şerhleri"
    assert uploads["104"]["fields"]["klasorYolu"] == (
        "2024/2000 (Ceza Dava Dosyası) / Gerekçeli Karar / Gerekçeli Karar 30/06/2025"
    )
    assert uploads["101"]["file"]["data"] != uploads["102"]["file"]["data"]
    # Ekin türü "Ek" (bağlı olduğu evrakın başlığı değil); diğerlerinde en yakın klasörün adı.
    assert uploads["104"]["fields"]["evrakTuru"] == "Ek"
    assert uploads["103"]["fields"]["evrakTuru"] == "Gerekçeli Karar"
    # Hiçbir belge mesaj metni (text/plain) olarak kaydedilmedi; aynı içerik de atlanmadı.
    assert result["sameContent"] == 0 and not any(u["file"]["data"].startswith(b"Bu evrak t") for u in lab.uploads)
    page.close()


def test_only_the_evraks_the_user_ticks_are_pulled(lab):
    """"Biz hangisini seçersek o çekilir": işaretsiz bırakılan evrak hiç istenmez."""
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-agaci")
    _start_pull(lab)
    page.wait_for_selector(".jurisai-chooser", timeout=30000)
    labels = page.locator(".jurisai-chooser label").all_inner_texts()
    assert any("📁 2024/2000 (Ceza Dava Dosyası) / Kesinleşme Şerhleri" in label for label in labels)  # klasör başlıkları
    assert page.locator(".jurisai-pick-item").count() == 4
    assert "4 / 4 evrak seçili" in page.inner_text(".jurisai-chooser")

    # Önce hepsini kaldır: eylem düğmeleri kapanır. Sonra yalnız 103'ü (Gerekçeli Karar) işaretle.
    page.click("text=Tümünü seç / kaldır")
    assert page.is_disabled("#jurisai-pick-upload") and page.is_disabled("#jurisai-pick-disk")
    index_of_103 = page.evaluate(
        "() => [...document.querySelectorAll('.jurisai-pick-item')].findIndex((input) => input.parentElement.textContent.includes('Gerekçeli Karar 30/06/2025'))"
    )
    page.locator(".jurisai-pick-item").nth(index_of_103).check()
    assert "1 / 4 evrak seçili" in page.inner_text(".jurisai-chooser")
    page.click("#jurisai-pick-upload")
    result = _finish_pull(lab)

    assert result["ok"] and result["sent"] == 1 and result["chosen"] == 1 and result["found"] == 4, result
    assert [_legacy(upload["fields"]["evrakId"]) for upload in lab.uploads] == ["103"]
    page.close()


def test_cancelling_the_chooser_sends_nothing(lab):
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-agaci")
    _start_pull(lab)
    page.wait_for_selector(".jurisai-chooser", timeout=30000)
    page.click("#jurisai-pick-cancel")
    result = _finish_pull(lab)
    assert result["ok"] and result["cancelled"] and result["found"] == 4
    assert lab.uploads == []
    page.close()


def test_preview_that_is_already_on_is_not_switched_off(lab):
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-agaci")
    page.click("#onizleme")  # kullanıcı ön izlemeyi zaten açmış

    result = _pull(lab, page)

    assert result["ok"] and result["sent"] == 4, result
    assert page.inner_text("#onizleme") == "Ön İzlemeyi Kapat"  # eklenti düğmeye ikinci kez basmadı
    page.close()


def test_uploading_needs_the_connection_key_but_only_after_the_choice(lab):
    lab.configure(apiKey="")
    page = lab.open("/vatandas/dosya-agaci")

    result = _pull(lab, page, "upload")

    assert result["ok"] is False and "anahtar" in result["error"].lower()
    assert lab.uploads == []
    page.close()


def test_pulling_without_an_open_case_window_explains_what_to_do(lab):
    lab.configure()
    page = lab.open("/vatandas/evrak-agaci-tikla")  # açık pencere var ama evrak ağacı/ön izleme düğmesi yok
    result = lab.worker.evaluate(
        "async () => { const tab = (await chrome.tabs.query({ url: '*://*.uyap.gov.tr/vatandas/*' })).sort((a, b) => b.id - a.id)[0];"
        " return chrome.tabs.sendMessage(tab.id, { type: 'JURISAI_PULL_DOSYA' }, { frameId: 0 }); }"
    )
    assert result["ok"] is False and "Ön izleme" in result["error"]
    assert lab.uploads == []
    page.close()


def test_pull_errors_are_reported_with_their_reason(lab):
    """Önceki sürümde yalnız "8 hata" yazıyordu; neden görünmediği için gerçek portalda teşhis edilemedi."""
    lab.configure(throttleMs=500, apiKey="jsai_" + "z" * 44)  # geçersiz anahtar: sunucu 401 döner

    page = lab.open("/vatandas/dosya-agaci")
    result = _pull(lab, page, "upload")

    assert result["ok"] and result["sent"] == 0 and result["failed"] >= 1
    assert any("anahtar" in error.lower() for error in result["errors"]), result["errors"]
    assert lab.uploads == []
    page.close()


def test_a_click_that_triggers_no_request_is_explained_in_the_error(lab):
    """Ön izleme açılmazsa (ya da UYAP tıklamaya yanıt vermezse) neden bildirimde yazar."""
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-agaci")
    page.evaluate("() => { window.preview = true; document.getElementById('onizleme').textContent = 'Ön İzlemeyi Kapat'; }")
    page.evaluate(
        "() => { document.addEventListener('click', (e) => { if (e.target.closest('span.file')) e.stopImmediatePropagation(); }, true); }"
    )

    result = _pull(lab, page, "upload")

    assert result["ok"] and result["sent"] == 0 and result["failed"] >= 1
    assert any("hiç istek yapmadı" in error for error in result["errors"]), result["errors"]
    page.close()


def test_pulling_to_disk_needs_no_connection_key_and_sends_nothing_to_jurisai(lab):
    """"UYAP'tan klasör olarak indir": JurisAI'ya bağlanmaz (anahtar boş olabilir), her evrak diske yazılır."""
    lab.configure(throttleMs=500, apiKey="")
    page = lab.open("/vatandas/dosya-agaci")
    count = (
        "() => chrome.downloads.search({}).then((items) => "
        "items.filter((x) => x.mime === 'application/vnd.oasis.opendocument.text' || x.mime === 'image/tiff').length)"
    )
    before = lab.worker.evaluate(count)

    result = _pull(lab, page, "disk")

    assert result["ok"] and result["sent"] == 4 and result["failed"] == 0 and result["mode"] == "disk", result
    assert lab.uploads == []
    page.wait_for_timeout(1500)
    assert lab.worker.evaluate(count) - before == 4
    page.close()


def test_the_case_list_row_button_opens_the_case_and_shows_the_chooser(lab):
    """Dosya listesinde satırdaki düğme: dosyayı açar, evrak seçim penceresini getirir (eklenti penceresine gerek yok)."""
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-listesi")
    assert page.locator(".jurisai-open-btn").count() == 1
    assert "JurisAI: evrakları seç ve çek" in page.inner_text(".jurisai-open-btn")

    page.click(".jurisai-open-btn")
    page.wait_for_selector(".jurisai-chooser", timeout=30000)

    assert page.locator(".jurisai-pick-item").count() == 4
    assert "2024/2000" in page.inner_text(".jurisai-chooser")
    page.click("#jurisai-pick-cancel")
    assert lab.uploads == []
    page.close()


def test_menu_links_with_evrak_in_them_never_get_evidence_buttons(lab):
    """Gerçek portalda menü <nav>/<aside> değil sınıf adlarıyla kurulu ve "Evrak ..." bağlantıları var."""
    lab.configure()
    page = lab.open("/vatandas/dosya-listesi")
    assert page.locator(".jurisai-send-btn:not(.jurisai-open-btn)").count() == 0
    assert page.locator(".jurisai-toolbar:not(.jurisai-hint)").count() == 0
    page.close()


def test_launcher_is_always_present_and_lists_the_cases_to_choose_from(lab):
    """Satır düğmeleri sayfa yapısına bağlı: köşedeki sabit düğme her UYAP sayfasında çalışır."""
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-listesi")
    assert page.locator(".jurisai-launcher").count() == 1

    page.click(".jurisai-launcher")
    page.wait_for_selector(".jurisai-case-picker", timeout=10000)
    picker = page.inner_text(".jurisai-case-picker")
    assert "hangi dosyanın" in picker and "2024/2000" in picker and "Ankara Bölge Adliye Mahkemesi" in picker

    page.click(".jurisai-case-picker button >> nth=0")  # listedeki ilk (tek) dosya
    page.wait_for_selector(".jurisai-chooser", timeout=30000)
    assert page.locator(".jurisai-pick-item").count() == 4
    page.click("#jurisai-pick-cancel")
    assert lab.uploads == []
    page.close()


def test_launcher_goes_straight_to_the_chooser_when_a_case_is_already_open(lab):
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-agaci")

    page.click(".jurisai-launcher")
    page.wait_for_selector(".jurisai-chooser", timeout=30000)

    assert page.locator(".jurisai-pick-item").count() == 4
    page.click("#jurisai-pick-cancel")
    page.close()


def test_launcher_explains_what_to_do_when_there_is_no_case_on_the_page(lab):
    lab.configure()
    page = lab.open("/main")
    page.click(".jurisai-launcher")
    page.wait_for_selector(".jurisai-toast", timeout=5000)
    assert "Dosya Sorgulama" in page.inner_text(".jurisai-toasts")
    assert page.locator(".jurisai-case-picker, .jurisai-chooser").count() == 0
    page.close()


def test_diagnosis_reports_the_launcher_and_swallowed_refresh_errors(lab):
    lab.configure()
    page = lab.open("/vatandas/dosya-listesi")
    report = lab.worker.evaluate(
        """async () => {
            const tab = (await chrome.tabs.query({ url: '*://*.uyap.gov.tr/vatandas/*' })).sort((a, b) => b.id - a.id)[0];
            const frames = await chrome.scripting.executeScript({
                target: { tabId: tab.id, allFrames: true },
                func: () => (typeof window.__jurisaiDiagnose === 'function' ? window.__jurisaiDiagnose() : null),
            });
            return frames.map((frame) => frame.result).filter(Boolean)[0];
        }"""
    )
    assert report["launcher"] is True and report["caseOpenTargets"] == 1
    assert report["refreshFailed"] is False
    page.close()


# --- Evrak sayısı sınırı yok -----------------------------------------------------------------------------------

PAGES["/vatandas/dosya-buyuk"] = PAGES["/vatandas/dosya-agaci"].replace(
    "</script></body></html>",
    """
        // 41 evrak daha (toplam 45): eskiden en çok 40 evrak çekiliyordu.
        var folder = document.querySelectorAll('#tree ul ul ul')[1];
        for (var n = 0; n < 41; n++) {
          var li = document.createElement('li');
          li.innerHTML = '<span class="file" evrak_id="9' + n + '">Ek evrak ' + n + ' 01/07/2025</span>';
          folder.appendChild(li);
        }
      </script></body></html>""",
)


def test_there_is_no_cap_on_how_many_evidence_items_can_be_pulled(lab):
    """Kullanıcı istediği kadar evrak çekebilmeli: 45 evrak da seçilir ve hepsi kuyruğa alınır."""
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-buyuk")
    _start_pull(lab)
    page.wait_for_selector(".jurisai-chooser", timeout=60000)
    assert page.locator(".jurisai-pick-item").count() == 45
    assert "45 / 45 evrak seçili" in page.inner_text(".jurisai-chooser")
    assert "en fazla" not in page.inner_text(".jurisai-chooser")
    page.click("#jurisai-pick-upload")
    assert lab.wait_for_uploads(1, timeout=30)
    lab.worker.evaluate(
        """async () => {
            const tab = (await chrome.tabs.query({ url: '*://*.uyap.gov.tr/vatandas/*' })).sort((a, b) => b.id - a.id)[0];
            return chrome.tabs.sendMessage(tab.id, { type: 'JURISAI_PULL_STOP' }, { frameId: 0 });
        }"""
    )
    result = _finish_pull(lab)

    assert result["ok"] and result["found"] == 45 and result["chosen"] == 45, result  # kırpılmadı
    assert result["stopped"] is True and 1 <= result["sent"] < 45  # "Çekmeyi durdur" hâlâ çalışır
    page.close()


def test_a_late_second_request_from_a_previous_preview_never_replaces_the_next_evrak(lab):
    """Canlıda "12 aynı içerik atlandı": önceki önizlemenin gecikmiş isteği sonraki yaprağın adresi sanılıyor, doğru evrak
    hiç indirilmiyordu. Eşleştirme artık önizleme sayfasının kendi evrakId'siyle yapılır."""
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-agaci")

    result = _pull(lab, page)

    assert result["ok"] and result["sent"] == 4 and result["sameContent"] == 0 and result["failed"] == 0, result
    contents = {_legacy(upload["fields"]["evrakId"]): upload["file"]["data"] for upload in lab.uploads}
    assert len(set(contents.values())) == 4  # dört evrak, dört farklı içerik (hiçbiri bir öncekinin kopyası değil)
    page.close()


PAGES["/vatandas/dosya-sayi-tutmuyor"] = PAGES["/vatandas/dosya-agaci"].replace(
    "Kesinleşme Şerhleri (2)", "Kesinleşme Şerhleri (3)"  # UYAP 3 diyor, ağaçta yalnız 2 yaprak var
)


def test_chooser_compares_the_found_items_with_uyaps_own_folder_counts(lab):
    """"Gerçekten o kadar evrak var mı?": UYAP klasör adının yanına kendi sayısını yazar; eklenti bulduğuyla karşılaştırır."""
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-agaci")
    _start_pull(lab)
    page.wait_for_selector(".jurisai-chooser", timeout=30000)
    text = page.inner_text(".jurisai-chooser")
    assert "UYAP: 2, bulunan: 2" in text  # Kesinleşme Şerhleri (2): 2 yaprak
    assert "UYAP: 1, bulunan: 1" in text
    assert "UYAP klasör sayıları: 3 evrak · bulunan: 3" in text and "sayılar tutuyor" in text
    assert "ayrıca 1 ek" in text  # ek ayrıca sayılır
    page.click("#jurisai-pick-cancel")
    _finish_pull(lab)
    page.close()


def test_a_count_mismatch_is_flagged(lab):
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-sayi-tutmuyor")
    _start_pull(lab)
    page.wait_for_selector(".jurisai-chooser", timeout=90000)
    text = page.inner_text(".jurisai-chooser")
    assert "⚠ UYAP: 3, bulunan: 2" in text
    assert "UYAP klasör sayıları: 4 evrak · bulunan: 3" in text and "sayılar tutmuyor" in text
    assert "fark: Kesinleşme Şerhleri (UYAP 3, bulunan 2)" in text  # hangi klasörde fark olduğu yazılır
    page.click("#jurisai-pick-cancel")
    _finish_pull(lab)
    page.close()


def test_update_decision_reloads_only_when_newer_and_not_busy_and_detects_a_stale_install(lab):
    lab.configure()
    decide = "(args) => decideUpdate(args)"
    run = lambda **kwargs: lab.worker.evaluate(decide, kwargs)  # noqa: E731
    assert run(remote="2.16.1", current="2.16.0", tried="", busy=False) == "reload"
    assert run(remote="2.16.0", current="2.16.0", tried="", busy=False) == "none"  # güncel
    assert run(remote="2.15.9", current="2.16.0", tried="", busy=False) == "none"  # uzaktaki daha eski
    assert run(remote="2.10.0", current="2.9.5", tried="", busy=False) == "reload"  # 2.10 > 2.9 (metin değil sayı karşılaştırması)
    assert run(remote="", current="2.16.0", tried="", busy=False) == "none"
    assert run(remote="2.16.1", current="2.16.0", tried="", busy=True) == "wait"  # çekme/kayıt sürerken yeniden yüklenmez
    # Zaten bu sürüm için yeniden yüklendi ama sürüm değişmedi: eklenti güncel dosyalardan çalışmıyor.
    assert run(remote="2.16.1", current="2.16.0", tried="2.16.1", busy=False) == "stale"


def test_reinjecting_the_content_script_is_safe_and_clears_dead_ui(lab):
    """Yeniden yüklemeden sonra betik açık sekmeye yeniden yerleştirilir: çift çalışmaz, ölü düğme/panel temizlenir."""
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-agaci")
    assert page.locator(".jurisai-launcher").count() == 1
    # Eski (ölü) sürümden kalmış gibi bir arayüz parçası
    page.evaluate("() => { const dead = document.createElement('button'); dead.className = 'jurisai-launcher'; dead.id = 'olu'; document.body.append(dead); }")
    assert page.locator(".jurisai-launcher").count() == 2

    lab.worker.evaluate(
        """async () => {
            const tab = (await chrome.tabs.query({ url: '*://*.uyap.gov.tr/vatandas/*' })).sort((a, b) => b.id - a.id)[0];
            await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, files: ['content.js'] });
        }"""
    )
    page.wait_for_timeout(1500)
    # Aynı sürüm ikinci kez çalışmaz: sürüm koruması betiği atlar (ölü parçaya dokunmaz) — ama iki kez kurulum da olmaz.
    assert page.locator(".jurisai-chooser, .jurisai-case-picker").count() == 0
    assert page.locator(".jurisai-toolbar").count() <= 1

    # Gerçek yeniden yüklemede sürüm değişkeni sıfırdır; yeni dünya temiz arayüz kurar. Bunu taklit et.
    page.evaluate("() => { document.querySelectorAll('.jurisai-launcher').forEach((el) => el.remove()); }")
    lab.worker.evaluate(
        """async () => {
            const tab = (await chrome.tabs.query({ url: '*://*.uyap.gov.tr/vatandas/*' })).sort((a, b) => b.id - a.id)[0];
            await chrome.scripting.executeScript({
                target: { tabId: tab.id }, world: 'ISOLATED',
                func: () => { delete window.__jurisaiLoadedVersion; },
            });
            await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, files: ['content.js'] });
        }"""
    )
    page.wait_for_timeout(1500)
    assert page.locator(".jurisai-launcher").count() == 1 and page.locator("#olu").count() == 0
    page.click(".jurisai-launcher")  # yeni kurulan düğme çalışır: seçim penceresi gelir
    page.wait_for_selector(".jurisai-chooser", timeout=30000)
    page.click("#jurisai-pick-cancel")
    page.close()


def test_direct_download_probe_measures_without_storing_or_leaking(lab):
    """Yaprağa tıklamadan adres kurulabilir mi? Deneme ölçer, belge saklamaz/yüklemez, kimlik/ad sızdırmaz."""
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-agaci")
    result = lab.worker.evaluate(
        """async () => {
            const tab = (await chrome.tabs.query({ url: '*://*.uyap.gov.tr/vatandas/*' })).sort((a, b) => b.id - a.id)[0];
            return chrome.tabs.sendMessage(tab.id, { type: 'JURISAI_PULL_PROBE' }, { frameId: 0 });
        }"""
    )

    assert result["ok"], result
    report = result["report"]
    assert report["kind"] == "doğrudan indirme denemesi"
    assert report["paramCount"] == 4 and len(report["params"]) == 4
    # Sahte portalda sorgu yalnız evrakId'ye bağlı: kurulan adres gerçek ikinci evrakla aynı baytları verir.
    assert report["direct"]["sameBytesAsRealB"] is True and report["direct"]["status"] == 200
    assert any(param["equalsAttributeOfEvrakA"] is False for param in report["params"])
    assert any(param["sameInBothEvraks"] is True for param in report["params"])
    assert report["mimeTypeDiffersBetweenEvraks"] is False
    assert lab.uploads == []  # hiçbir şey yüklenmedi
    serialized = json.dumps(report, ensure_ascii=False)
    assert "ENC101" not in serialized and "ENC102" not in serialized and "Kesinleşme" not in serialized
    page.close()


def _one_leaf_page(leaf_id: str) -> str:
    """Ağaç sayfasındaki Kesinleşme Şerhleri klasörüne tek bir ek yaprak ekler."""
    return PAGES["/vatandas/dosya-agaci"].replace(
        '<li><span class="file" evrak_id="102">Kesinleşme Şerhleri 30/06/2025</span></li></ul></li>',
        f'<li><span class="file" evrak_id="102">Kesinleşme Şerhleri 30/06/2025</span></li>'
        f'<li><span class="file" evrak_id="{leaf_id}">Deneme evrakı {leaf_id}</span></li></ul></li>',
    )


PAGES["/vatandas/dosya-gecici"] = _one_leaf_page("105")
PAGES["/vatandas/dosya-kalici"] = _one_leaf_page("106")


def test_a_transient_short_message_is_retried_once_and_the_item_arrives(lab):
    lab.configure(throttleMs=500)
    _UyapHandler.seen_105 = 0
    page = lab.open("/vatandas/dosya-gecici")
    _start_pull(lab)
    page.wait_for_selector(".jurisai-chooser", timeout=30000)
    page.click("#jurisai-pick-upload")

    result = _finish_pull(lab)

    assert result["ok"] and result["failed"] == 0, result  # geçici mesaj yeniden denenince geçti
    assert "105" in [_legacy(upload["fields"]["evrakId"]) for upload in lab.uploads]
    page.close()


def test_a_permanent_short_message_is_reported_with_its_text_and_the_run_continues(lab):
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-kalici")
    _start_pull(lab)
    page.wait_for_selector(".jurisai-chooser", timeout=30000)
    page.click("#jurisai-pick-upload")

    result = _finish_pull(lab)

    assert result["ok"] and result["failed"] == 1 and result["sent"] >= 4, result  # diğer evraklar yine geldi
    reason = result["errors"][0]
    assert "yetkiniz yok" in reason and "kod #)" in reason and "777" not in reason  # UYAP'ın mesajı yazıldı, rakamlar maskeli
    assert "106" not in [_legacy(upload["fields"]["evrakId"]) for upload in lab.uploads]
    page.close()


PAGES["/vatandas/dosya-buyuk"] = _one_leaf_page("109")


def test_an_evrak_too_large_for_the_preview_is_fetched_from_uyaps_own_save_address(lab):
    """Canlıda 80 evraktan 4'ü "önizlemede vermiyor" diye düşüyordu: taranmış vekâletnameler ön izlemede yok, "Kaydet" adresinde var."""
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-buyuk")
    _start_pull(lab)
    page.wait_for_selector(".jurisai-chooser", timeout=30000)
    page.click("#jurisai-pick-upload")

    result = _finish_pull(lab)

    assert result["ok"] and result["failed"] == 0, result
    [upload] = [item for item in lab.uploads if _legacy(item["fields"]["evrakId"]) == "109"]
    assert upload["file"]["name"].endswith(".jpg") and upload["file"]["data"].startswith(b"\xff\xd8\xff")  # gerçek dosya, mesaj değil
    assert b"boyutu" not in upload["file"]["data"]
    page.close()


def test_the_save_address_is_derived_only_from_known_preview_addresses(lab):
    derived = lab.worker.evaluate("""() => [
      downloadUrlFor('https://vatandas.uyap.gov.tr/main/jsp/view_document_brd.uyap?mimeType=&evrakId=a%2Bb%40c&dosyaId=d%2Fe&yargiTuru=1'),
      downloadUrlFor('https://vatandas.uyap.gov.tr/main/jsp/view_document_danistay_brd.uyap?evrakId=x&mimeType=Udf&yargiTuru=2'),
      downloadUrlFor('https://vatandas.uyap.gov.tr/main/jsp/kvkEvrakViewDocument_brd.uyap?evrakId=x'),
      downloadUrlFor('https://vatandas.uyap.gov.tr/main/jsp/viewer.jsp?evrakId=x'),
      downloadUrlFor('https://vatandas.uyap.gov.tr/main/jsp/baska_brd.uyap?evrakId=x'),
      downloadUrlFor('bozuk adres'),
    ]""")
    assert derived == [
        # kodlama aynen korunur (şifreli kimlikte + / @ var), yalnız mimeType çıkarılır
        "https://vatandas.uyap.gov.tr/main/jsp/download_document_brd.uyap?evrakId=a%2Bb%40c&dosyaId=d%2Fe&yargiTuru=1",
        "https://vatandas.uyap.gov.tr/main/jsp/download_document_danistay_brd.uyap?evrakId=x&yargiTuru=2",
        "https://vatandas.uyap.gov.tr/main/jsp/kvkEvrakDownloadDocument_brd.uyap?evrakId=x",
        "",  # tanınmayan adresten tahminle istek yapılmaz
        "",
        "",
    ]


PAGES["/vatandas/dosya-tembel"] = PAGES["/vatandas/dosya-agaci"].replace(
    "</script></body></html>",
    """
        (function () {
          var original = toggle;
          toggle = function (li) {
            original(li);
            var ul = li.querySelector(':scope > ul');
            if (ul && !li.dataset.lazyDone && li.querySelector(':scope > .folder') && /Kesinleşme/.test(li.textContent.slice(0, 40))) {
              li.dataset.lazyDone = '1';
              var saved = ul.innerHTML;
              ul.innerHTML = '';
              setTimeout(function () { ul.innerHTML = saved; }, 1300);
            }
          };
        })();
      </script></body></html>""",
)
PAGES["/vatandas/dosya-kimliksiz"] = PAGES["/vatandas/dosya-agaci"].replace(
    '<span class="file" evrak_id="102">Kesinleşme Şerhleri 30/06/2025</span>',
    '<span class="file">KIMLIKSIZ</span>',
)


def test_the_tree_is_counted_only_after_lazy_loaded_nodes_have_arrived(lab):
    """Canlıda aynı dosya 464, sonra 447 evrak çıktı: ağaç tam yüklenmeden sayılıyordu."""
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-tembel")
    _start_pull(lab)
    page.wait_for_selector(".jurisai-chooser", timeout=60000)
    assert page.locator(".jurisai-pick-item").count() == 4  # geç gelen iki Kesinleşme Şerhi de sayıldı
    assert "UYAP: 2, bulunan: 2" in page.inner_text(".jurisai-chooser")
    page.click("#jurisai-pick-cancel")
    _finish_pull(lab)
    page.close()


def test_items_without_an_evidence_id_are_counted_and_reported(lab):
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-kimliksiz")
    _start_pull(lab)
    page.wait_for_selector(".jurisai-chooser", timeout=90000)
    text = page.inner_text(".jurisai-chooser")
    assert "kimliksiz öğe: 1 (çekilemez)" in text
    assert "⚠ UYAP: 2, bulunan: 1" in text  # UYAP 2 diyor, kimlikli yalnız 1 var
    page.click("#jurisai-pick-cancel")
    _finish_pull(lab)
    page.close()


# Aynı evrak iki klasörde: "Kopya (2)" klasöründe 102 (Kesinleşme Şerhleri'nde de var) ve yeni bir evrak (120) bulunur.
PAGES["/vatandas/dosya-kopyali"] = PAGES["/vatandas/dosya-agaci"].replace(
    '<li class="expandable"><div class="hitarea"></div><span class="folder">Gerekçeli Karar (1)',
    '<li class="expandable"><div class="hitarea"></div><span class="folder">Kopya (2)</span><ul style="display:none">'
    '<li><span class="file" evrak_id="102">Kesinleşme Şerhleri 30/06/2025</span></li>'
    '<li><span class="file" evrak_id="120">Başka evrak 01/07/2025</span></li></ul></li>\n'
    '              <li class="expandable"><div class="hitarea"></div><span class="folder">Gerekçeli Karar (1)',
)


def test_a_count_difference_caused_by_the_same_evrak_in_two_folders_is_explained(lab):
    """Canlıda iki klasörde UYAP bir fazla diyordu: aynı evrak_id iki klasörde görünüyor, tek kez çekilir ve fark bununla açıklanır."""
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-kopyali")
    _start_pull(lab)
    page.wait_for_selector(".jurisai-chooser", timeout=30000)
    text = page.inner_text(".jurisai-chooser")
    assert page.locator(".jurisai-pick-item").count() == 5  # 101, 102, 103, 104 (ek), 120: 102 tek kez
    assert "⚠ UYAP: 2, bulunan: 1" in text  # Kopya klasörü: 2 diyor, 102 başka klasörde sayıldı
    assert "UYAP klasör sayıları: 5 evrak · bulunan: 4" in text
    assert "fark 1 evrağın iki klasörde birden görünmesinden" in text and "sayılar tutmuyor" not in text
    page.click("#jurisai-pick-cancel")
    _finish_pull(lab)
    page.close()


# Klasör ilk açılışta eksik yükleniyor (Kesinleşme Şerhleri (2): 1 yaprak); kapatıp yeniden açınca tamamı geliyor.
PAGES["/vatandas/dosya-yarim"] = PAGES["/vatandas/dosya-agaci"].replace(
    "</script></body></html>",
    """
        (function () {
          var original = toggle; var held = null; var opens = 0;
          toggle = function (li) {
            original(li);
            var label = li.querySelector(':scope > .folder');
            if (!label || label.textContent.indexOf('Kesinleşme Şerhleri (2)') !== 0) return;
            if (!li.classList.contains('collapsable')) return;
            opens += 1;
            var ul = li.querySelector(':scope > ul');
            if (opens === 1) { held = ul.lastElementChild; ul.removeChild(held); }
            else if (held) { ul.appendChild(held); held = null; }
          };
        })();
      </script></body></html>""",
)
# Klasör hiç yüklenmiyor: fark kalır ve açıkça gösterilir.
PAGES["/vatandas/dosya-bos"] = PAGES["/vatandas/dosya-agaci"].replace(
    "</script></body></html>",
    """
        (function () {
          var original = toggle;
          toggle = function (li) {
            original(li);
            var label = li.querySelector(':scope > .folder');
            if (!label || label.textContent.indexOf('Kesinleşme Şerhleri (2)') !== 0) return;
            if (li.classList.contains('collapsable')) li.querySelector(':scope > ul').innerHTML = '';
          };
        })();
      </script></body></html>""",
)


def test_a_folder_that_loaded_only_partly_is_reopened_until_it_matches_uyaps_count(lab):
    """Canlıda aynı dosya 463, sonra 456 evrak çıktı: eksik yüklenen klasör artık kapatılıp yeniden açılır."""
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-yarim")
    _start_pull(lab)
    page.wait_for_selector(".jurisai-chooser", timeout=90000)
    text = page.inner_text(".jurisai-chooser")
    assert "UYAP: 2, bulunan: 2" in text, text
    assert "UYAP klasör sayıları: 3 evrak · bulunan: 3" in text and "sayılar tutuyor" in text
    assert page.locator("#jurisai-pick-rescan").count() == 0  # fark yok: yeniden tara düğmesi çıkmaz
    page.click("#jurisai-pick-cancel")
    _finish_pull(lab)
    page.close()


def test_a_folder_that_never_loads_is_counted_flagged_and_can_be_rescanned(lab):
    """Hiç evrak bulunamayan klasör UYAP toplamından düşmez; fark adıyla yazılır ve ağaç yeniden taranabilir."""
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-bos")
    _start_pull(lab)
    page.wait_for_selector(".jurisai-chooser", timeout=90000)
    text = page.inner_text(".jurisai-chooser")
    assert "UYAP klasör sayıları: 3 evrak · bulunan: 1" in text, text  # boş klasörün 2'si de UYAP toplamında
    assert "fark: Kesinleşme Şerhleri (UYAP 2, bulunan 0)" in text
    page.click("#jurisai-pick-rescan")
    page.wait_for_selector(".jurisai-chooser", timeout=90000)  # yeniden tarandı, seçim penceresi yeniden açıldı
    assert "fark: Kesinleşme Şerhleri (UYAP 2, bulunan 0)" in page.inner_text(".jurisai-chooser")
    page.click("#jurisai-pick-cancel")
    _finish_pull(lab)
    page.close()


# Aynı evrak iki klasörde (102) ve aynı ek iki yerde (104): "copies" 2 olur ama eksik klasör yoktur, fark 1'dir.
PAGES["/vatandas/dosya-kopyali-ek"] = PAGES["/vatandas/dosya-kopyali"].replace(
    '<li><span class="file" evrak_id="120">Başka evrak 01/07/2025</span></li>',
    '<li class="expandable"><div class="hitarea"></div><span class="file" evrak_id="120">Başka evrak 01/07/2025</span>'
    '<ul style="display:none"><li><span class="file" evrak_id="104" ana_evrak_id="120">Ek 1</span></li></ul></li>',
)


def test_a_difference_is_explained_when_no_folder_is_missing_even_if_attachments_repeat(lab):
    """Canlıda hiçbir klasör eksik değildi ama kopya sayısı tutmadığı için boş "fark:" ile kırmızı uyarı çıkıyordu."""
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-kopyali-ek")
    _start_pull(lab)
    page.wait_for_selector(".jurisai-chooser", timeout=90000)
    text = page.inner_text(".jurisai-chooser")
    assert "UYAP klasör sayıları: 5 evrak · bulunan: 4" in text, text
    assert "✓ fark 1 evrağın iki klasörde birden görünmesinden" in text
    assert "sayılar tutmuyor" not in text and "fark:" not in text
    assert page.locator("#jurisai-pick-rescan").count() == 0
    page.click("#jurisai-pick-cancel")
    _finish_pull(lab)
    page.close()


def test_evraks_already_in_jurisai_are_not_clicked_or_downloaded_again(lab):
    """Yarıda kalan çekmeyi sürdürmek: JurisAI'da olan evrak (101) hiç tıklanmaz, yalnız kalanlar çekilir."""
    lab.configure(throttleMs=500)
    _ApiHandler.known_ids.append("101")
    page = lab.open("/vatandas/dosya-agaci")
    _start_pull(lab)
    page.wait_for_selector(".jurisai-chooser", timeout=30000)
    page.click("#jurisai-pick-upload")

    result = _finish_pull(lab)

    assert result["ok"] and result["known"] == 1 and result["failed"] == 0, result
    sent = sorted(_legacy(upload["fields"]["evrakId"]) for upload in lab.uploads)
    assert "101" not in sent and len(sent) == 3, sent  # 4 evraktan 3'ü çekildi
    assert result["chosen"] == 3
    page.close()


def test_main_evraks_only_button_unchecks_the_attachments(lab):
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-agaci")
    _start_pull(lab)
    page.wait_for_selector(".jurisai-chooser", timeout=30000)
    assert "4 / 4 evrak seçili" in page.inner_text(".jurisai-chooser")
    page.click("#jurisai-pick-main")
    assert "3 / 4 evrak seçili" in page.inner_text(".jurisai-chooser")
    page.click("#jurisai-pick-upload")

    result = _finish_pull(lab)

    assert result["ok"] and result["sent"] == 3 and result["chosen"] == 3, result
    assert "104" not in [_legacy(upload["fields"]["evrakId"]) for upload in lab.uploads]  # 104 ek
    page.close()


def test_the_summary_reports_where_the_time_goes(lab):
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-agaci")
    _start_pull(lab)
    page.wait_for_selector(".jurisai-chooser", timeout=30000)
    page.click("#jurisai-pick-upload")

    result = _finish_pull(lab)

    timing = result["timing"]
    assert timing["items"] == 4 and timing["pause"] >= 1500, timing  # her evrak için en az 1,5 sn bekleme
    assert timing["capture"] > 0 and timing["download"] >= 0 and timing["upload"] >= 0
    assert "evrak başına ort.: yakalama" in result["summary"]
    page.close()


# Evrak 103'ün ek listesi ilk açılışta boş geliyor (UYAP ek listesini yükleyemedi); kapatıp yeniden açınca ek (104) geliyor.
PAGES["/vatandas/dosya-ek-bos"] = PAGES["/vatandas/dosya-agaci"].replace(
    "</script></body></html>",
    """
        (function () {
          var original = toggle; var held = null; var opens = 0;
          toggle = function (li) {
            original(li);
            var label = li.querySelector(':scope > .file');
            if (!label || label.getAttribute('evrak_id') !== '103') return;
            if (!li.classList.contains('collapsable')) return;
            opens += 1;
            var ul = li.querySelector(':scope > ul');
            if (opens === 1) { held = ul.innerHTML; ul.innerHTML = ''; }
            else if (held) { ul.innerHTML = held; held = null; }
          };
        })();
      </script></body></html>""",
)


def test_an_opened_evrak_with_an_empty_attachment_list_is_reopened_until_the_attachment_arrives(lab):
    """Canlıda ek sayısı 367 → 350 diye azalıyordu: ek listesi yüklenemeyen evrak artık kapatılıp yeniden açılır."""
    lab.configure(throttleMs=500)
    page = lab.open("/vatandas/dosya-ek-bos")
    _start_pull(lab)
    page.wait_for_selector(".jurisai-chooser", timeout=90000)
    text = page.inner_text(".jurisai-chooser")
    assert page.locator(".jurisai-pick-item").count() == 4, text  # 101, 102, 103 ve eki 104
    assert "ayrıca 1 ek" in text
    assert "yüklenemeyen açık düğüm" not in text  # onarıldı
    assert "4 benzersiz evrak/ek" in text
    page.click("#jurisai-pick-cancel")
    _finish_pull(lab)
    page.close()


# --- JurisAI web sayfası ↔ eklenti köprüsü (bridge.js) -----------------------------------------------------
# Sahte JurisAI sayfası localhost:3000'de sunulur (eklentinin köprü betiği yalnız oraya yerleşir); sayfa gerçek uygulamanın
# yaptığı gibi window.postMessage ile komut gönderir.
JURISAI_PAGE = """<html><body><h1>JurisAI</h1><script>
window.ask = (type, payload, wait) => new Promise((resolve) => {
  const id = 'q' + Math.random();
  const on = (event) => {
    const d = event.data;
    if (event.source === window && d && d.source === 'jurisai-extension' && d.id === id) { window.removeEventListener('message', on); resolve(d); }
  };
  window.addEventListener('message', on);
  window.postMessage({ source: 'jurisai-web', id: id, type: type, payload: payload || {} }, location.origin);
  setTimeout(() => { window.removeEventListener('message', on); resolve({ timeout: true }); }, wait || 8000);
});
</script></body></html>"""


def _jurisai_page(lab):
    page = lab.context.new_page()
    page.route(
        "http://localhost:3000/**",
        lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=JURISAI_PAGE),
    )
    page.goto("http://localhost:3000/dashboard/uyap")
    page.wait_for_timeout(500)
    return page


def _close_uyap_tabs(lab):
    for page in list(lab.context.pages):
        if "uyap.gov.tr" in page.url:
            page.close()


def test_the_jurisai_page_can_ping_the_extension(lab):
    lab.configure(throttleMs=500)
    web = _jurisai_page(lab)
    reply = web.evaluate("() => window.ask('PING')")
    version = json.loads((EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8"))["version"]
    assert reply["ok"] and reply["version"] == version and reply["connected"] is True, reply
    web.close()


def test_the_jurisai_page_lists_the_dosyalar_of_the_open_uyap_tab(lab):
    lab.configure(throttleMs=500)
    uyap = lab.open("/vatandas/dosya-listesi")
    web = _jurisai_page(lab)
    reply = web.evaluate("() => window.ask('LIST_DOSYALAR')")
    assert reply["ok"], reply
    assert len(reply["items"]) == 1
    item = reply["items"][0]
    assert item["esas"] == "2024/2000" and "Ankara Bölge Adliye Mahkemesi 19. Ceza Dairesi" in item["birim"], item
    assert item["key"] and "button" not in item  # satır düğmesi (DOM öğesi) sayfaya gitmez
    web.close()
    uyap.close()


def test_the_bridge_says_what_is_missing_when_there_is_no_uyap_tab_or_no_list(lab):
    lab.configure(throttleMs=500)
    _close_uyap_tabs(lab)
    web = _jurisai_page(lab)
    assert web.evaluate("() => window.ask('LIST_DOSYALAR')")["code"] == "no_uyap_tab"
    other = lab.open("/vatandas/onizleme-post")  # UYAP sekmesi var ama dosya listesi yok
    reply = web.evaluate("() => window.ask('LIST_DOSYALAR')")
    assert reply["ok"] is False and reply["code"] == "no_list", reply
    other.close()
    web.close()


def test_the_jurisai_page_can_open_a_dosya_and_the_evrak_chooser_appears_in_the_uyap_tab(lab):
    lab.configure(throttleMs=500)
    uyap = lab.open("/vatandas/dosya-listesi")
    web = _jurisai_page(lab)
    key = web.evaluate("() => window.ask('LIST_DOSYALAR')")["items"][0]["key"]
    reply = web.evaluate("(key) => window.ask('OPEN_DOSYA', { key })", key)
    assert reply["ok"], reply
    uyap.wait_for_selector(".jurisai-chooser", timeout=60000)
    uyap.click("#jurisai-pick-cancel")
    uyap.wait_for_timeout(500)
    stale = web.evaluate("() => window.ask('OPEN_DOSYA', { key: 'olmayan#1' })")
    assert stale["ok"] is False and stale["code"] == "stale", stale
    web.close()
    uyap.close()


def test_the_bridge_ignores_commands_that_are_not_on_its_list(lab):
    lab.configure(throttleMs=500)
    web = _jurisai_page(lab)
    assert web.evaluate("() => window.ask('EVIL', {}, 800)") == {"timeout": True}
    assert web.evaluate("() => window.ask('PING')")["ok"]  # köprü çalışmaya devam eder
    web.close()


def test_reinjecting_the_bridge_into_an_open_jurisai_tab_gives_exactly_one_reply(lab):
    """Eklenti güncellenince açık JurisAI sekmesine köprü yeniden yerleştirilir; eski kopya susmalı, yanıt çift gelmemeli."""
    lab.configure(throttleMs=500)
    web = _jurisai_page(lab)
    lab.worker.evaluate("() => reinjectIntoOpenTabs()")
    web.wait_for_timeout(700)
    replies = web.evaluate(
        """() => new Promise((resolve) => {
          let count = 0;
          window.addEventListener('message', (event) => {
            if (event.data && event.data.id === 'cift-yanit' && event.data.source === 'jurisai-extension') count += 1;
          });
          window.postMessage({ source: 'jurisai-web', id: 'cift-yanit', type: 'PING', payload: {} }, location.origin);
          setTimeout(() => resolve(count), 1000);
        })"""
    )
    assert replies == 1
    web.close()


def test_the_jurisai_page_can_write_the_connection_key_into_the_extension(lab):
    lab.configure(throttleMs=500, apiKey="")
    web = _jurisai_page(lab)
    assert web.evaluate("() => window.ask('PING')")["connected"] is False
    key = "jsai_" + "a1b2c3d4" * 5
    with lab.context.expect_page() as opened:
        web.evaluate("(key) => { window.pairing = window.ask('SET_KEY', { key }); }", key)
    approval = opened.value
    approval.locator("#approve").click()
    assert web.evaluate("() => window.pairing")["ok"] is True
    stored = lab.worker.evaluate("() => chrome.storage.local.get('apiKey')")
    assert stored["apiKey"] == key
    assert "apiKey" not in lab.worker.evaluate("() => chrome.storage.sync.get('apiKey')")
    assert web.evaluate("() => window.ask('PING')")["connected"] is True
    web.close()
    lab.configure(throttleMs=500)  # testin anahtarını geri koy


def test_the_extension_refuses_a_malformed_connection_key(lab):
    lab.configure(throttleMs=500)
    web = _jurisai_page(lab)
    for bad in ("", "kisa", "jsai_kisa", "jsai_" + "x" * 20 + " ; DROP", "baska_" + "a" * 40, "jsai_" + "a" * 300):
        reply = web.evaluate("(key) => window.ask('SET_KEY', { key })", bad)
        assert reply["ok"] is False, bad
    assert lab.worker.evaluate("() => chrome.storage.local.get('apiKey')")["apiKey"] == TOKEN  # değişmedi
    web.close()


# --- JurisAI sayfasından evrak ağacı + aktarım (TREE / PULL_IDS / JOB_STATUS / STOP_JOB) -----------------------


def _poll_job(web, tab_id, job_id, with_tree=False, timeout=120):
    """İş bitene kadar (done/error) JurisAI sayfası gibi yoklar."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        reply = web.evaluate(
            "(p) => window.ask('JOB_STATUS', p)", {"tabId": tab_id, "jobId": job_id, "withTree": with_tree}
        )
        assert reply.get("ok"), reply
        if reply["job"]["state"] != "running":
            return reply
        time.sleep(0.4)
    raise AssertionError("iş bitmedi")


def _read_tree(lab):
    """Sahte dosya listesini açar, ilk dosyanın ağacını JurisAI sayfasından okur. (uyap, web, tab_id, tree) döner."""
    uyap = lab.open("/vatandas/dosya-listesi")
    web = _jurisai_page(lab)
    key = web.evaluate("() => window.ask('LIST_DOSYALAR')")["items"][0]["key"]
    started = web.evaluate("(key) => window.ask('TREE', { key })", key)
    assert started["ok"] and isinstance(started["tabId"], int), started
    done = _poll_job(web, started["tabId"], started["jobId"], with_tree=True)
    assert done["job"]["state"] == "done", done
    return uyap, web, started["tabId"], done["tree"]


def test_the_jurisai_page_reads_the_evrak_tree_and_knows_what_is_already_in_jurisai(lab):
    lab.configure(throttleMs=500)
    _ApiHandler.known_ids.append("101")
    uyap, web, _tab, tree = _read_tree(lab)
    assert sorted(_legacy(item["id"]) for item in tree["items"]) == ["101", "102", "103", "104"]
    assert all(set(item) == {"id", "title", "folders", "typeName", "isEk", "declared"} for item in tree["items"])  # DOM öğesi yok
    assert [_legacy(item["id"]) for item in tree["items"] if item["isEk"]] == ["104"]
    assert tree["known"] == ["101"] and tree["knownChecked"] is True
    counts = tree["counts"]
    assert counts["declaredTotal"] == 3 and counts["foundTotal"] == 3 and counts["matches"] is True and counts["eks"] == 1
    assert tree["who"]["esas"] == "2024/2000"
    web.close()
    uyap.close()


def test_the_jurisai_page_starts_an_aktarim_and_follows_its_progress(lab):
    lab.configure(throttleMs=500)
    uyap, web, tab_id, _tree = _read_tree(lab)
    pull = web.evaluate("(p) => window.ask('PULL_IDS', p)", {"tabId": tab_id, "ids": ["101", "102", "103"], "mode": "upload"})
    assert pull["ok"] and pull["total"] == 3, pull
    done = _poll_job(web, tab_id, pull["jobId"])
    assert done["job"]["state"] == "done", done
    run = done["run"]
    assert run["total"] == 3 and run["done"] == 3 and run["stats"]["sent"] == 3 and run["stats"]["failed"] == 0, run
    assert run["result"]["summary"].startswith("3 evrak aktarıldı")
    assert sorted(_legacy(upload["fields"]["evrakId"]) for upload in lab.uploads) == ["101", "102", "103"]
    assert all(upload["fields"]["klasorYolu"] for upload in lab.uploads)  # klasör yolu da gider
    web.close()
    uyap.close()


def test_evraks_already_in_jurisai_are_skipped_when_the_jurisai_page_starts_an_aktarim(lab):
    lab.configure(throttleMs=500)
    _ApiHandler.known_ids.append("101")
    uyap, web, tab_id, _tree = _read_tree(lab)
    pull = web.evaluate("(p) => window.ask('PULL_IDS', p)", {"tabId": tab_id, "ids": ["101", "102"], "mode": "upload"})
    assert pull["ok"], pull
    done = _poll_job(web, tab_id, pull["jobId"])
    assert done["run"]["stats"]["known"] == 1 and done["run"]["stats"]["sent"] == 1, done["run"]
    assert [_legacy(upload["fields"]["evrakId"]) for upload in lab.uploads] == ["102"]
    web.close()
    uyap.close()


def test_a_running_aktarim_can_be_stopped_from_the_jurisai_page(lab):
    lab.configure(throttleMs=4000)  # evrak başına ~4 sn: durdurmak için zaman var
    uyap, web, tab_id, _tree = _read_tree(lab)
    pull = web.evaluate("(p) => window.ask('PULL_IDS', p)", {"tabId": tab_id, "ids": ["101", "102", "103", EK_STABLE], "mode": "upload"})
    assert pull["ok"], pull
    assert lab.wait_for_uploads(1, timeout=30)
    assert web.evaluate("(p) => window.ask('STOP_JOB', p)", {"tabId": tab_id, "jobId": pull["jobId"]})["ok"]
    done = _poll_job(web, tab_id, pull["jobId"])
    assert done["run"]["result"]["stopped"] is True and len(lab.uploads) < 4, done["run"]
    web.close()
    uyap.close()


def test_bridge_job_commands_refuse_bad_input_and_non_uyap_tabs(lab):
    lab.configure(throttleMs=500)
    uyap, web, tab_id, _tree = _read_tree(lab)
    # seçili evrak yok / bilinmeyen evrak
    assert web.evaluate("(p) => window.ask('PULL_IDS', p)", {"tabId": tab_id, "ids": []})["code"] == "empty"
    assert web.evaluate("(p) => window.ask('PULL_IDS', p)", {"tabId": tab_id, "ids": ["yok-boyle-evrak"]})["code"] == "empty"
    # bilinmeyen iş
    assert web.evaluate("(p) => window.ask('JOB_STATUS', p)", {"tabId": tab_id, "jobId": "x"})["code"] == "unknown_job"
    assert web.evaluate("(p) => window.ask('STOP_JOB', p)", {"tabId": tab_id, "jobId": "x"})["ok"] is False
    # UYAP olmayan sekmeye iş komutu gitmez (JurisAI sayfasının kendi sekmesi dahil)
    own = lab.worker.evaluate("async () => (await chrome.tabs.query({ url: 'http://localhost:3000/*' }))[0].id")
    assert web.evaluate("(p) => window.ask('JOB_STATUS', p)", {"tabId": own, "jobId": "x"})["code"] == "no_uyap_tab"
    assert web.evaluate("(p) => window.ask('JOB_STATUS', p)", {"tabId": "1", "jobId": "x"})["code"] == "bad_tab"
    # liste değişmişse
    stale = web.evaluate("() => window.ask('TREE', { key: 'olmayan#1' })")
    assert stale["ok"] is True  # iş başlar; dosyanın yokluğu asenkron iş durumunda bildirilir
    failed = _poll_job(web, stale["tabId"], stale["jobId"])
    assert failed["job"]["state"] == "error" and failed["job"]["code"] == "stale", failed
    web.close()
    uyap.close()


def test_the_extension_sleeps_for_a_content_script_so_hidden_tabs_are_not_throttled(lab):
    lab.configure(throttleMs=500)
    extension_id = lab.worker.url.split("/")[2]
    page = lab.context.new_page()
    page.goto(f"chrome-extension://{extension_id}/popup.html")
    took = page.evaluate(
        """async () => {
          const started = Date.now();
          const reply = await chrome.runtime.sendMessage({ type: 'JURISAI_SLEEP', ms: 400 });
          return { ok: reply && reply.ok, ms: Date.now() - started };
        }"""
    )
    assert took["ok"] and 380 <= took["ms"] < 3000, took
    page.close()


# --- Gerçek Vatandaş Portalı yapısı (canlıda ölçüldü, 2026-10-04) --------------------------------------------------
# - Dosya Sorgulama: "Yargı Türü" seçilip "Dosya Sorgula"ya basılır (DataTables: 15 kayıt/sayfa, sayfalama, "Tümü" seçeneği);
# - evrak_id her sayfa yüklemesinde yeniden şifrelenir; kalıcı bilgi: balondaki "Birim Evrak No" ve eklerin düz ana_evrak_id'si;
# - aynı ekler iki farklı evrakın altında görünebilir; "Son 20 Evrak" kısayol kopyaları farklı şifreli kimlik taşır;
# - bootstrap modalı kapanırken (animasyon) gelen "aç" tıklamasını yutar.

_REAL_TYPES = [("0", "Ceza"), ("1", "Hukuk"), ("2", "İcra"), ("5", "Adli Tıp")]


def _real_rows(tur: str) -> list[dict]:
    if tur == "0":
        return [
            {"role": "Katılan", "birim": "Ankara Bölge Adliye Mahkemesi 19. Ceza Dairesi", "esas": "2024/2000", "tur": "Ceza Dava Dosyası", "acilis": "19.11.2024 15:01:22", "durum": "Kapalı ( 27.06.2025 15:55:46 )"},
            {"role": "Katılan", "birim": "Ankara 33. Ağır Ceza Mahkemesi", "esas": "2024/124", "tur": "Ceza Dava Dosyası", "acilis": "06.03.2024 09:25:46", "durum": "Kapalı ( 27.06.2025 11:43:11 )"},
        ]
    if tur == "1":
        return [{"role": "Davacı", "birim": "Ankara 5. Asliye Hukuk Mahkemesi", "esas": "2023/77", "tur": "Hukuk Dava Dosyası", "acilis": "02.02.2023 10:00:00", "durum": "Açık"}]
    if tur == "2":
        return [
            {"role": "Alacaklı", "birim": "Ankara 12. İcra Dairesi", "esas": f"2022/{100 + number}", "tur": "İcra Dosyası", "acilis": f"{number + 1:02d}.03.2022 09:00:00", "durum": "Açık"}
            for number in range(20)
        ]
    return []


_REAL_LIST_HTML = """<html><body>
<div><a href="javascript:void(0)">Güvenli Çıkış</a></div>
<h3>DOSYA SORGULAMA</h3>
<select id="yargiTuru">@@OPTIONS@@</select>
<select id="mahkeme"><option value="">Tümü</option></select>
<button id="btnQueryDoc" class="btn btn-success" type="button">Dosya Sorgula</button>
<div id="dosya_listesi_table_wrapper" class="dataTables_wrapper">
  <select name="dosya_listesi_table_length">@@LENGTHS@@</select>
  <table id="dosya_listesi_table" class="table table-striped table-bordered dataTable">
    <thead><tr><th>Taraf Rolü</th><th>Mahkeme Adı</th><th>Esas No</th><th>Dosya Türü</th><th>Dosya Açılış Tarihi</th><th>Dosya Durumu</th><th>Dosya Görüntüle</th></tr></thead>
    <tbody></tbody>
  </table>
  <div class="dataTables_info"></div>
  <div class="dataTables_paginate"><ul>
    <li class="paginate_button previous disabled"><a href="#">Önceki</a></li>
    <li class="paginate_button next disabled"><a href="#">Sonraki</a></li>
  </ul></div>
</div>
<div id="dosya_goruntule_modal" class="modal fade in" role="dialog" style="display:none">
  <h4 class="modal-title"></h4>
  <button type="button" id="kapat">Kapat</button>
  <button type="button" id="onizleme">Ön İzlemeyi Aktifleştir</button>
  <ul id="tree" class="treeview"></ul>
  <div id="viewer"></div>
</div>
<script>
  var state = { rows: [], size: 15, page: 0 };
  var lockedUntil = 0; // bootstrap modalı kapanırken gelen "aç" tıklamasını yutar
  function rnd() { var c = 'abcdefghijklmnopqrstuvwxyz0123456789+/'; var s = ''; for (var i = 0; i < 44; i++) s += c[Math.floor(Math.random() * c.length)]; return s; }
  function ev(no, title, inner) {
    var span = '<span class="file" ce="e" data-placement="top" data-html="true" evrak_id="&quot;' + rnd() + '&quot;" data-original-title="<b>Birim Evrak No: ' + no + '</b><br>Türü: Deneme">' + title + '</span>';
    if (!inner) return '<li>' + span + '</li>';
    return '<li class="expandable"><div class="hitarea"></div>' + span + '<ul style="display:none">' + inner + '</ul></li>';
  }
  function eks(ana) {
    var out = '';
    for (var n = 1; n <= 3; n++) out += '<li><span class="file" ana_evrak_id="' + ana + '" evrak_id="&quot;' + rnd() + '&quot;" data-original-title="" title="">Ek ' + n + '</span></li>';
    return out;
  }
  function folder(name, children, open) {
    return '<li class="' + (open ? 'collapsable' : 'expandable') + '"><div class="hitarea"></div><span class="folder">' + name + '</span><ul' + (open ? '' : ' style="display:none"') + '>' + children + '</ul></li>';
  }
  function buildTree(label) {
    var recent = folder('Dosyaya Eklenen Son 20 Evrak', ev(5001, 'Kesinleşme Şerhleri 01/07/2025') + ev(5003, 'Gerekçeli Karar 30/06/2025', eks('7000000001')), false);
    var all = folder('Tüm Evraklar', folder('2024 (Dava Dosyası)',
      folder('Kesinleşme Şerhleri (2)', ev(5001, 'Kesinleşme Şerhleri 01/07/2025') + ev(5002, 'Kesinleşme Şerhleri 02/07/2025'), false) +
      folder('Gerekçeli Karar (1)', ev(5003, 'Gerekçeli Karar 30/06/2025', eks('7000000001')), false) +
      folder('Talimat Yazısı (2)', ev(5002, 'Kesinleşme Şerhleri 02/07/2025') + ev(5004, 'Talimat Yazısı 03/07/2025', eks('7000000001')), false),
      false), true);
    return '<li class="collapsable"><span class="folder">' + label + '</span><ul>' + recent + all + '</ul></li>';
  }
  var preview = false;
  function toggle(li) {
    var ul = li.querySelector(':scope > ul'); if (!ul) return;
    var closed = li.classList.contains('expandable');
    li.classList.toggle('expandable', !closed); li.classList.toggle('collapsable', closed);
    ul.style.display = closed ? 'block' : 'none';
  }
  document.addEventListener('click', function (event) {
    var t = event.target;
    if (t.classList.contains('hitarea') || t.classList.contains('folder')) toggle(t.closest('li'));
    else if (t.classList.contains('file') && preview) {
      var frame = document.createElement('iframe');
      frame.src = '/main/jsp/viewer.jsp?mimeType=odt&evrakId=ENC' + encodeURIComponent(t.getAttribute('evrak_id')) + '&dosyaId=9&yargiTuru=Ceza';
      document.getElementById('viewer').replaceChildren(frame);
    }
  });
  document.getElementById('onizleme').addEventListener('click', function () {
    preview = !preview; this.textContent = preview ? 'Ön İzlemeyi Kapat' : 'Ön İzlemeyi Aktifleştir';
  });
  document.getElementById('kapat').addEventListener('click', function () {
    lockedUntil = Date.now() + @@LOCK@@;
    setTimeout(function () { document.getElementById('dosya_goruntule_modal').style.display = 'none'; }, 350);
  });
  function openModal(row) {
    if (Date.now() < lockedUntil) return;
    var modal = document.getElementById('dosya_goruntule_modal');
    modal.querySelector('.modal-title').textContent = row.esas + ' - ' + row.birim + ' - ' + row.tur;
    document.getElementById('tree').innerHTML = buildTree(row.birim + ' ' + row.esas);
    preview = false; document.getElementById('onizleme').textContent = 'Ön İzlemeyi Aktifleştir';
    modal.style.display = 'block';
  }
  function render() {
    var tb = document.querySelector('#dosya_listesi_table tbody'); tb.innerHTML = '';
    var size = state.size === -1 ? Math.max(1, state.rows.length) : state.size;
    var from = state.page * size, slice = state.rows.slice(from, from + size);
    if (!state.rows.length) tb.innerHTML = '<tr><td class="dataTables_empty" colspan="7">Tabloda herhangi bir veri mevcut değil</td></tr>';
    slice.forEach(function (r) {
      var tr = document.createElement('tr');
      [r.role, r.birim, r.esas, r.tur, r.acilis, r.durum].forEach(function (v) { var td = document.createElement('td'); td.textContent = v; tr.appendChild(td); });
      var td = document.createElement('td'); var b = document.createElement('button'); b.type = 'button'; b.className = 'btn'; b.textContent = 'Dosya Görüntüle';
      b.addEventListener('click', function () { openModal(r); }); td.appendChild(b); tr.appendChild(td); tb.appendChild(tr);
    });
    document.querySelector('.dataTables_info').textContent = state.rows.length ? state.rows.length + ' Kayıttan ' + (from + 1) + ' - ' + (from + slice.length) + ' Arası Kayıtlar' : 'Kayıt Yok';
    document.querySelector('.paginate_button.next').classList.toggle('disabled', from + size >= state.rows.length);
  }
  document.getElementById('yargiTuru').addEventListener('change', function () {
    fetch('/dosya/mahkemeler?tur=' + this.value).then(function (r) { return r.json(); }).then(function (list) {
      document.getElementById('mahkeme').innerHTML = '<option value="">Tümü</option>' + list.map(function (c) { return '<option>' + c + '</option>'; }).join('');
    });
  });
  document.getElementById('btnQueryDoc').addEventListener('click', function () {
    fetch('/dosya/sorgu?tur=' + document.getElementById('yargiTuru').value).then(function (r) { return r.json(); }).then(function (rows) {
      state.rows = rows; state.page = 0; render();
    });
  });
  document.querySelector('select[name=dosya_listesi_table_length]').addEventListener('change', function () { state.size = parseInt(this.value, 10); state.page = 0; render(); });
  document.querySelector('.paginate_button.next a').addEventListener('click', function (event) {
    event.preventDefault();
    if (!this.parentElement.classList.contains('disabled')) { state.page += 1; render(); }
  });
  render();
</script></body></html>"""


def _real_list_page(all_option: bool = True, lock_ms: int = 300) -> str:
    options = "".join(f'<option value="{value}">{label}</option>' for value, label in _REAL_TYPES)
    lengths = '<option value="10">10</option><option value="15" selected>15</option>'
    if all_option:
        lengths += '<option value="50">50</option><option value="-1">Tümü</option>'
    return _REAL_LIST_HTML.replace("@@OPTIONS@@", options).replace("@@LENGTHS@@", lengths).replace("@@LOCK@@", str(lock_ms))


PAGES["/vatandas/dosya-sorgulama-gercek"] = _real_list_page()
PAGES["/vatandas/dosya-sorgulama-sayfali"] = _real_list_page(all_option=False)  # "Tümü" yok: "Sonraki" ile gezilmeli
PAGES["/vatandas/dosya-sorgulama-kilitli"] = _real_list_page(lock_ms=1500)  # modal kapanırken "aç" tıklaması 1,5 sn yutulur
PAGES["/vatandas/anasayfa-gercek"] = """<html><body>
<ul class="menu"><li><a id="ust" href="javascript:void(0)">Sorgulama İşlemleri</a>
  <ul id="alt" style="display:none"><li><a href="javascript:menuButtonClick('12573')">Dosya Sorgulama</a></li><li><a href="javascript:void(0)">Danıştay Dosya Sorgulama</a></li></ul></li></ul>
<a href="javascript:void(0)">Güvenli Çıkış</a>
<script>
  document.getElementById('ust').addEventListener('click', function () { document.getElementById('alt').style.display = 'block'; });
  function menuButtonClick(id) { location.href = '/vatandas/dosya-sorgulama-gercek'; }
</script></body></html>"""
PAGES["/vatandas/giris-gercek"] = "<html><body><h1>UYAP Bilişim Sistemi</h1><button>Giriş Seçenekleri</button><a href='#'>Giriş Yapınız</a></body></html>"


def _ask(web, type_, payload=None, wait=60000):
    return web.evaluate("([t, p, w]) => window.ask(t, p, w)", [type_, payload or {}, wait])


def _real_list(web):
    reply = _ask(web, "LIST_DOSYALAR")
    assert reply.get("ok"), reply
    return reply


def _real_tree(web, item):
    started = _ask(web, "TREE", {"key": item["key"], "yargiTuru": item["yargiTuru"]})
    assert started.get("ok"), started
    done = _poll_job(web, started["tabId"], started["jobId"], with_tree=True)
    assert done["job"]["state"] == "done", done
    return started["tabId"], done["tree"]


def _by_esas(listing, esas):
    return next(item for item in listing["items"] if item["esas"] == esas)


@pytest.mark.parametrize("path", ["/vatandas/dosya-sorgulama-gercek", "/vatandas/dosya-sorgulama-sayfali"])
def test_the_real_list_queries_every_yargi_turu_and_reads_every_page(lab, path):
    """Canlıda liste kendiliğinden gelmiyordu: eklenti her yargı türünü sorgular, sayfa boyutunu "Tümü" yapar (yoksa sayfaları gezer)."""
    lab.configure(throttleMs=500)
    uyap = lab.open(path)
    web = _jurisai_page(lab)
    listing = _real_list(web)
    assert listing["complete"] is True and listing["errors"] == []
    assert [(entry["label"], entry["count"]) for entry in listing["types"]] == [("Ceza", 2), ("Hukuk", 1), ("İcra", 20), ("Adli Tıp", 0)]
    assert len(listing["items"]) == 23 and len({item["key"] for item in listing["items"]}) == 23
    ceza = _by_esas(listing, "2024/124")
    assert ceza["yargiTuru"] == "Ceza" and ceza["birim"] == "Ankara 33. Ağır Ceza Mahkemesi" and ceza["role"] == "Katılan"
    assert ceza["tur"] == "Ceza Dava Dosyası" and ceza["durum"].startswith("Kapalı") and ceza["acilis"].startswith("06.03.2024")
    assert {item["yargiTuru"] for item in listing["items"]} == {"Ceza", "Hukuk", "İcra"}
    web.close()
    uyap.close()


def test_a_stuck_next_page_is_reported_as_partial_not_as_a_complete_list(lab):
    lab.configure(throttleMs=500)
    uyap = lab.open("/vatandas/dosya-sorgulama-sayfali")
    web = _jurisai_page(lab)
    try:
        uyap.evaluate("""() => document.querySelector('.paginate_button.next').addEventListener(
            'click', event => { event.preventDefault(); event.stopImmediatePropagation(); }, true)""")
        listing = _real_list(web)
        assert listing["complete"] is False
        assert any("sonraki sayfa" in error for error in listing["errors"]), listing
        assert len(listing["items"]) == 18  # Ceza 2 + Hukuk 1 + ilk İcra sayfası 15
    finally:
        web.close()
        uyap.close()


def test_two_concurrent_list_requests_do_not_mutate_the_uyap_form_together(lab):
    lab.configure(throttleMs=500)
    uyap = lab.open("/vatandas/dosya-sorgulama-gercek")
    web = _jurisai_page(lab)
    try:
        replies = web.evaluate("() => Promise.all([window.ask('LIST_DOSYALAR', {}, 60000), window.ask('LIST_DOSYALAR', {}, 60000)])")
        assert sum(reply.get("ok") is True for reply in replies) == 1, replies
        assert any(reply.get("code") == "busy" for reply in replies), replies
    finally:
        web.close()
        uyap.close()


def test_a_case_on_a_later_page_can_be_opened_from_jurisai(lab):
    lab.configure(throttleMs=500)
    uyap = lab.open("/vatandas/dosya-sorgulama-sayfali")
    web = _jurisai_page(lab)
    try:
        listing = _real_list(web)
        _, tree = _real_tree(web, _by_esas(listing, "2022/119"))
        assert tree["who"]["esas"] == "2022/119"
    finally:
        web.close()
        uyap.close()


def test_the_extension_opens_dosya_sorgulama_from_the_menu_when_it_is_not_open(lab):
    lab.configure(throttleMs=500)
    uyap = lab.open("/vatandas/anasayfa-gercek")
    web = _jurisai_page(lab)
    first = _ask(web, "LIST_DOSYALAR")
    assert first["ok"] is False and first["code"] == "navigating", first
    uyap.wait_for_url("**/dosya-sorgulama-gercek", timeout=15000)
    uyap.wait_for_timeout(1500)  # yeni sayfaya içerik betiği yerleşsin
    assert len(_real_list(web)["items"]) == 23
    web.close()
    uyap.close()


def test_a_logged_out_uyap_page_is_reported_as_login_required(lab):
    lab.configure(throttleMs=500)
    uyap = lab.open("/vatandas/giris-gercek")
    web = _jurisai_page(lab)
    reply = _ask(web, "LIST_DOSYALAR")
    assert reply["ok"] is False and reply["code"] == "login_required", reply
    web.close()
    uyap.close()


def test_the_tree_identity_is_stable_even_though_uyap_reencrypts_evrak_ids_on_every_load(lab):
    """Canlıda aynı dosya her yüklemede 445-467 evrak çıkıyordu: şifreli evrak_id değişiyor. Kalıcı kimlik: balondaki Birim Evrak No
    ve eklerin düz ana_evrak_id'si; aynı evrak iki klasörde, aynı ekler iki evrakta görününce tek sayılır."""
    lab.configure(throttleMs=500)
    uyap = lab.open("/vatandas/dosya-sorgulama-gercek")
    web = _jurisai_page(lab)
    _tab, first = _real_tree(web, _by_esas(_real_list(web), "2024/2000"))
    ids = sorted(item["id"] for item in first["items"])
    assert ids == sorted(
        [f"ev:{no}@{BIRIM}" for no in (5001, 5002, 5003, 5004)] + [f"ek:7000000001:Ek {n}@{BIRIM}" for n in (1, 2, 3)]
    ), ids
    counts = first["counts"]
    assert counts["declaredTotal"] == 5 and counts["foundTotal"] == 4 and counts["eks"] == 3
    assert counts["matches"] is False and counts["explained"] is True  # fark: 5002 iki klasörde
    assert first["who"]["esas"] == "2024/2000"

    uyap.reload()  # UYAP tüm şifreli kimlikleri yeniden üretir
    uyap.wait_for_timeout(1800)
    _tab, second = _real_tree(web, _by_esas(_real_list(web), "2024/2000"))
    assert sorted(item["id"] for item in second["items"]) == ids
    web.close()
    uyap.close()


def test_already_imported_evraks_are_recognised_across_page_loads(lab):
    """Önce şifreli kimlikle eşleşme hiç tutmazdı (her yüklemede yeni kimlik): aynı dosya her çekilişte yeniden yükleniyordu."""
    lab.configure(throttleMs=500)
    uyap = lab.open("/vatandas/dosya-sorgulama-gercek")
    web = _jurisai_page(lab)
    tab_id, tree = _real_tree(web, _by_esas(_real_list(web), "2024/2000"))
    pull = _ask(web, "PULL_IDS", {"tabId": tab_id, "ids": [item["id"] for item in tree["items"]], "mode": "upload"})
    assert pull["ok"] and pull["total"] == 7, pull
    done = _poll_job(web, tab_id, pull["jobId"], timeout=180)
    assert done["run"]["stats"]["sent"] == 7 and done["run"]["stats"]["failed"] == 0, done["run"]
    sent = sorted(upload["fields"]["evrakId"] for upload in lab.uploads)
    assert sent == sorted(item["id"] for item in tree["items"])  # JurisAI'ya giden kimlik = kalıcı kimlik

    _ApiHandler.known_ids.extend(sent)  # sunucu bunları artık biliyor
    uyap.reload()
    uyap.wait_for_timeout(1800)
    tab_id, again = _real_tree(web, _by_esas(_real_list(web), "2024/2000"))
    assert sorted(again["known"]) == sent and again["knownChecked"] is True
    count = len(lab.uploads)
    pull = _ask(web, "PULL_IDS", {"tabId": tab_id, "ids": [item["id"] for item in again["items"]], "mode": "upload"})
    done = _poll_job(web, tab_id, pull["jobId"], timeout=60)
    assert done["run"]["stats"]["known"] == 7 and done["run"]["stats"]["sent"] == 0, done["run"]
    assert len(lab.uploads) == count  # hiç evraka tıklanmadı, hiçbir şey yeniden yüklenmedi
    web.close()
    uyap.close()


def test_a_dosya_of_another_yargi_turu_than_the_displayed_one_is_found_by_requerying(lab):
    lab.configure(throttleMs=500)
    uyap = lab.open("/vatandas/dosya-sorgulama-gercek")
    web = _jurisai_page(lab)
    listing = _real_list(web)  # liste bitince tabloda son tür (Adli Tıp, boş) görünür
    _tab, tree = _real_tree(web, _by_esas(listing, "2023/77"))
    assert tree["who"]["esas"] == "2023/77" and len(tree["items"]) == 7
    web.close()
    uyap.close()


def test_opening_the_next_dosya_retries_when_the_closing_modal_swallows_the_click(lab):
    """Canlıda: modal kapanırken (animasyon) gelen "Dosya Görüntüle" tıklaması yutuluyordu ve "dosya penceresi açılamadı" çıkıyordu."""
    lab.configure(throttleMs=500)
    uyap = lab.open("/vatandas/dosya-sorgulama-kilitli")
    web = _jurisai_page(lab)
    listing = _real_list(web)
    _real_tree(web, _by_esas(listing, "2024/2000"))
    _tab, second = _real_tree(web, _by_esas(listing, "2024/124"))  # önce 2024/2000 penceresi kapanır, ilk tıklama yutulur
    assert second["who"]["esas"] == "2024/124"
    web.close()
    uyap.close()
