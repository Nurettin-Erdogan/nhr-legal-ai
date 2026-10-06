"""UYAP eklentisi uç noktaları ve üst veri ayrıştırma. Veritabanı sahtelenir."""

from __future__ import annotations

import base64
import hashlib
import io
import zipfile
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import office_public
from api.office_public import router
from api.uyap_meta import extract_text_sample, is_allowed_file, parse_uyap_meta, safe_file_name

TOKEN = "t" * 32
OWNER = uuid4()


def _client(monkeypatch, *, owner=(uuid4(), OWNER), outcome=("inserted", uuid4())):
    stored: list[dict] = []

    def fake_owner(token):
        return owner if token == TOKEN else None

    def fake_store(owner_id, **kwargs):
        stored.append({"owner_id": owner_id, **kwargs})
        return outcome

    monkeypatch.setattr(office_public, "_owner_for_token", fake_owner)
    monkeypatch.setattr(office_public, "_store", fake_store)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), stored


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_ingest_rejects_unknown_token(monkeypatch):
    client, stored = _client(monkeypatch)

    response = client.post(
        "/api/public/uyap-ingest",
        json={"token": "x" * 32, "files": [{"name": "a.pdf", "contentBase64": _b64(b"abc")}]},
    )

    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == "*"
    assert not stored


def test_ingest_stores_allowed_files_for_the_token_owner(monkeypatch):
    client, stored = _client(monkeypatch)

    response = client.post(
        "/api/public/uyap-ingest",
        json={
            "token": TOKEN,
            "files": [
                {"name": "../../etc/karar 2024-123.pdf", "contentBase64": _b64(b"%PDF")},
                {"name": "virus.exe", "contentBase64": _b64(b"MZ")},
            ],
        },
    )

    assert response.json() == {"ok": True, "found": 2, "inserted": 1, "duplicates": 0, "skipped": 1}
    assert stored[0]["owner_id"] == OWNER
    assert "/" not in stored[0]["file_name"] and stored[0]["file_name"].endswith(".pdf")


def test_ingest_reports_duplicates_separately_from_rejected_files(monkeypatch):
    client, _ = _client(monkeypatch, outcome=("duplicate", uuid4()))

    response = client.post(
        "/api/public/uyap-ingest",
        json={
            "token": TOKEN,
            "files": [
                {"name": "dilekce.pdf", "contentBase64": _b64(b"%PDF")},
                {"name": "virus.exe", "contentBase64": _b64(b"MZ")},
            ],
        },
    )

    body = response.json()
    assert body["duplicates"] == 1
    assert body["inserted"] == 0
    assert body["skipped"] == 2  # eski istemciler: yinelenen + geçersiz


def test_ingest_body_is_capped_before_the_token_is_looked_up(monkeypatch):
    client, stored = _client(monkeypatch)
    looked_up: list[str] = []
    monkeypatch.setattr(office_public, "_owner_for_token", lambda token: looked_up.append(token))
    monkeypatch.setattr(office_public, "MAX_INGEST_REQUEST_BYTES", 1024)

    response = client.post(
        "/api/public/uyap-ingest",
        json={"token": TOKEN, "files": [{"name": "a.pdf", "contentBase64": _b64(b"x" * 4096)}]},
    )

    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == "*"
    assert not looked_up and not stored


def test_ingest_rejects_malformed_json_without_a_token_lookup(monkeypatch):
    client, stored = _client(monkeypatch)

    response = client.post(
        "/api/public/uyap-ingest", content=b"{not json", headers={"content-type": "application/json"}
    )

    assert response.status_code == 422
    assert not stored


def test_extension_connection_check_gets_400_with_a_file_message(monkeypatch):
    """Eklentinin "Bağlantıyı dene" düğmesi: geçerli anahtar + dosyasız istek → 400 ve "dosya" mesajı."""
    client, stored = _client(monkeypatch)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    empty_form = client.post("/api/public/v1/documents/upload", data={"evrakId": "1"}, headers=headers)
    empty_multipart = client.post(
        "/api/public/v1/documents/upload",
        content=b"--nhrtest--\r\n",
        headers={**headers, "content-type": "multipart/form-data; boundary=nhrtest"},
    )
    bad_token = client.post(
        "/api/public/v1/documents/upload", data={"evrakId": "1"}, headers={"Authorization": "Bearer " + "z" * 32}
    )

    for response in (empty_form, empty_multipart):
        assert response.status_code == 400
        assert "dosya" in response.json()["error"].lower()
    assert bad_token.status_code == 401
    assert not stored


def test_upload_checks_token_before_parsing_the_multipart_body(monkeypatch):
    client, stored = _client(monkeypatch)
    monkeypatch.setattr(office_public, "MAX_FILE_BYTES", 10)
    monkeypatch.setattr(office_public, "MULTIPART_OVERHEAD_BYTES", 10)
    big = {"file": ("evrak.pdf", b"x" * 5000, "application/pdf")}

    no_token = client.post("/api/public/v1/documents/upload", files=big)
    wrong = client.post(
        "/api/public/v1/documents/upload", files=big, headers={"Authorization": "Bearer " + "z" * 32}
    )
    too_big = client.post(
        "/api/public/v1/documents/upload", files=big, headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert (no_token.status_code, wrong.status_code, too_big.status_code) == (401, 401, 413)
    assert not stored


def test_upload_requires_bearer_token_and_known_extension(monkeypatch):
    client, stored = _client(monkeypatch)
    files = {"file": ("evrak.pdf", b"%PDF-1.4", "application/pdf")}

    assert client.post("/api/public/v1/documents/upload", files=files).status_code == 401
    bad_type = client.post(
        "/api/public/v1/documents/upload",
        files={"file": ("x.exe", b"MZ", "application/octet-stream")},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    ok = client.post(
        "/api/public/v1/documents/upload",
        files=files,
        data={"evrakId": "77", "dosyaEsasNo": "2024/55"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert bad_type.status_code == 415
    assert ok.status_code == 200 and ok.json()["ok"] is True
    assert stored[0]["file_name"] == "77-evrak.pdf"
    assert stored[0]["overrides"]["uyap_file_no"] == "2024/55"


def test_duplicate_upload_is_reported_not_repeated(monkeypatch):
    existing = uuid4()
    client, _ = _client(monkeypatch, outcome=("duplicate", existing))

    response = client.post(
        "/api/public/v1/documents/upload",
        files={"file": ("evrak.pdf", b"%PDF", "application/pdf")},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.json() == {"ok": True, "duplicate": True, "id": str(existing)}


def test_changed_evidence_is_not_silently_discarded_or_duplicated(monkeypatch):
    client, _ = _client(monkeypatch, outcome=("changed", None))
    response = client.post(
        "/api/public/v1/documents/upload",
        files={"file": ("evrak.odt", b"different content", "application/vnd.oasis.opendocument.text")},
        data={"evrakId": "stable-1", "dosyaEsasNo": "2024/1"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 409
    assert "içeriği değişmiş" in response.json()["error"]


def test_meta_parsing_reads_file_no_date_court_and_type():
    meta = parse_uyap_meta(
        "gerekceli_karar.pdf", "İstanbul 3. Asliye Hukuk Mahkemesi 2024/123 Esas 15.03.2025 tarihli"
    )

    assert meta["uyap_file_no"] == "2024/123"
    assert meta["doc_date"] == "2025-03-15"
    assert meta["doc_type"] == "Karar"  # liste sırasındaki ilk eşleşme (web/src/lib/uyap.ts ile aynı)
    assert "Asliye Hukuk" in (meta["uyap_birim"] or "")


def test_meta_parsing_ignores_impossible_dates():
    assert parse_uyap_meta("x.pdf", "31.02.2025")["doc_date"] is None


def test_file_name_and_extension_rules():
    assert safe_file_name(r"..\..\gizli/dosya adı.pdf") == "dosya_ad_.pdf"
    assert is_allowed_file("a.UDF") and not is_allowed_file("a.exe")


def test_udf_text_is_read_from_content_xml():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("content.xml", "<doc><p>Merhaba dilekçe</p></doc>")

    assert "Merhaba dilekçe" in extract_text_sample("belge.udf", buffer.getvalue())
    assert extract_text_sample("bozuk.udf", b"not a zip") == ""


def test_upload_accepts_odt_and_keeps_the_uyap_folder_path(monkeypatch):
    """Eklenti evrakı UYAP ağacındaki klasör yoluyla yollar; ODT (ön izleme biçimi) kabul edilir."""
    client, stored = _client(monkeypatch)

    response = client.post(
        "/api/public/v1/documents/upload",
        files={"file": ("Gerekceli Karar.odt", b"PK\x03\x04odt", "application/vnd.oasis.opendocument.text")},
        data={
            "evrakId": "123",
            "evrakTuru": "Gerekçeli Karar",
            "dosyaEsasNo": "2024/2000",
            "klasorYolu": "2024/2000 (Ceza Dava Dosyası)  /  Gerekçeli Karar  /\n Ek 1",
        },
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert stored[0]["file_name"] == "123-Gerekceli_Karar.odt"
    overrides = stored[0]["overrides"]
    assert overrides["uyap_path"] == "2024/2000 (Ceza Dava Dosyası) / Gerekçeli Karar / Ek 1"  # boşluklar sadeleşir
    assert overrides["doc_type"] == "Gerekçeli Karar"


def test_upload_accepts_html_receipt_and_extracts_text(monkeypatch):
    client, stored = _client(monkeypatch)
    html = '<html><head><meta charset="windows-1254"></head><body>VEKALET PULU MAKBUZU T.C. ADALET BAKANLIĞI Makbuz No 123</body></html>'.encode("cp1254")
    response = client.post(
        "/api/public/v1/documents/upload",
        files={"file": ("Vekalet Pulu Makbuzu.html", html, "text/html")},
        data={"evrakId": "receipt-1", "evrakTuru": "Makbuz", "dosyaEsasNo": "2024/55"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    assert stored[0]["file_name"].endswith(".html")
    assert stored[0]["data"] == html
    assert "BAKANLIĞI" in extract_text_sample(stored[0]["file_name"], stored[0]["data"])


def test_folder_path_is_capped_and_optional(monkeypatch):
    client, stored = _client(monkeypatch)

    client.post(
        "/api/public/v1/documents/upload",
        files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")},
        data={"klasorYolu": "k" * 900},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    client.post(
        "/api/public/v1/documents/upload",
        files={"file": ("b.pdf", b"%PDF-1.4", "application/pdf")},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert len(stored[0]["overrides"]["uyap_path"]) == 400
    assert stored[1]["overrides"]["uyap_path"] is None


def test_encrypted_uyap_evrak_ids_never_end_up_in_the_file_name(monkeypatch):
    """Gerçek portalda evrak_id şifreli bir değerdir (tırnak, '/', '+'); dosya adına ham hâliyle girerse
    Windows yazamaz ("Kayıt hatası"). Kararlı bir özet kullanılır; kısa/düz kimlik olduğu gibi kalır."""
    client, stored = _client(monkeypatch)
    weird = '"hfHeLsx0lKef/FTtsb+ab==\\x"'

    for evrak_id, title in ((weird, "A.odt"), (weird, "A.odt"), (weird + "2", "A.odt"), ("123", "A.odt")):
        response = client.post(
            "/api/public/v1/documents/upload",
            files={"file": (title, b"PK\x03\x04", "application/vnd.oasis.opendocument.text")},
            data={"evrakId": evrak_id},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert response.status_code == 200

    names = [item["file_name"] for item in stored]
    assert all(set(name) <= set("abcdef0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz._") for name in names)
    assert not any(char in name for name in names for char in '"/\\+=*?<>|:')
    assert names[0] == names[1]  # aynı kimlik, aynı ön ek (yinelenen denetimi çalışabilsin)
    assert names[0] != names[2]  # farklı evrak, farklı ön ek
    assert names[3] == "123-A.odt"  # düz kimlik olduğu gibi


def test_evrak_id_prefix_rules():
    assert office_public.evrak_id_prefix(None) == "" and office_public.evrak_id_prefix("  ") == ""
    assert office_public.evrak_id_prefix("77") == "77"
    assert office_public.evrak_id_prefix("a.b-c_9") == "a.b-c_9"
    hashed = office_public.evrak_id_prefix('"x/y')
    assert len(hashed) == 12 and hashed == office_public.evrak_id_prefix('"x/y')
    assert office_public.evrak_id_prefix("k" * 80) != "k" * 80  # çok uzun kimlik de özetlenir


def test_known_documents_lists_only_the_evraks_already_stored_for_the_token_owner(monkeypatch):
    client, _ = _client(monkeypatch)
    seen = []

    def fake_keys(owner_id, esas_no, birim):
        seen.append((owner_id, esas_no, birim))
        return ["101", office_public.evrak_id_prefix("A+/b==")]

    monkeypatch.setattr(office_public, "_stored_keys", fake_keys)

    response = client.post(
        "/api/public/v1/documents/known",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"evrakIds": ["101", "A+/b==", "999", "", "bozuk"], "dosyaEsasNo": "2024/124", "birim": "Ankara 1. İcra Dairesi"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "known": ["101", "A+/b=="]}
    assert seen == [(OWNER, "2024/124", "Ankara 1. İcra Dairesi")]  # owner + case + court
    assert response.headers["access-control-allow-origin"] == "*"


def test_known_documents_requires_a_valid_token_and_a_sane_body(monkeypatch):
    client, _ = _client(monkeypatch)
    monkeypatch.setattr(office_public, "_stored_keys", lambda *args: [])

    assert client.post("/api/public/v1/documents/known", json={"evrakIds": []}).status_code == 401
    bad = client.post("/api/public/v1/documents/known", headers={"Authorization": "Bearer " + "x" * 32}, json={"evrakIds": []})
    assert bad.status_code == 401
    headers = {"Authorization": f"Bearer {TOKEN}"}
    assert client.post("/api/public/v1/documents/known", headers=headers, content=b"not json").status_code == 422
    too_many = {"evrakIds": [str(number) for number in range(office_public.MAX_KNOWN_IDS + 1)]}
    assert client.post("/api/public/v1/documents/known", headers=headers, json=too_many).status_code == 422
    monkeypatch.setattr(office_public, "MAX_KNOWN_REQUEST_BYTES", 50)
    assert client.post("/api/public/v1/documents/known", headers=headers, json={"evrakIds": ["1" * 100]}).status_code == 413


def test_known_evrak_ids_uses_explicit_keys_and_ignores_oversized_ids():
    keys = ["ENC-12", "7"]
    assert office_public.known_evrak_ids(["ENC-12", "7", "8", "x" * 601], keys) == ["ENC-12", "7"]
    assert office_public.known_evrak_ids(["bozuk"], ["bozuk-ad-yok.pdf"]) == []


def test_known_documents_without_case_and_court_never_skip_evidence(monkeypatch):
    client, _ = _client(monkeypatch)
    monkeypatch.setattr(office_public, "_stored_keys", lambda *args: (_ for _ in ()).throw(AssertionError("Ambiguous query")))
    headers = {"Authorization": f"Bearer {TOKEN}"}
    for payload in ({"evrakIds": ["1"]}, {"evrakIds": ["1"], "dosyaEsasNo": "2024/1"},
                    {"evrakIds": ["1"], "dosyaEsasNo": "invalid", "birim": "Court"}):
        response = client.post("/api/public/v1/documents/known", json=payload, headers=headers)
        assert response.json() == {"ok": True, "known": []}


def test_same_named_same_sized_legacy_document_needs_matching_bytes(monkeypatch, tmp_path):
    old_file = tmp_path / "old.pdf"
    old_file.write_bytes(b"old!")
    old_id = uuid4()

    class Rows:
        def fetchall(self):
            return [{"id": old_id, "owner_id": OWNER, "storage_path": "legacy.pdf", "checksum_sha256": None}]

    class Connection:
        def execute(self, query, params):
            assert "file_name = %s" in query and params[:2] == ["same.pdf", 4]
            return Rows()

    monkeypatch.setattr(office_public, "_storage_path", lambda *_: old_file)
    args = {"file_name": "same.pdf", "size_bytes": 4, "uyap_file_no": "2024/1", "source": None}
    assert office_public.find_duplicate(Connection(), **args, checksum_sha256=hashlib.sha256(b"new!").hexdigest()) is None
    assert office_public.find_duplicate(Connection(), **args, checksum_sha256=hashlib.sha256(b"old!").hexdigest()) == old_id


def test_same_uyap_evrak_with_repacked_odt_is_not_imported_twice(monkeypatch, tmp_path):
    def odt(extra: str) -> bytes:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr(
                "content.xml",
                '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body>'
                '<office:text><text:p>Aynı hukuki metin</text:p></office:text></office:body></office:document-content>',
            )
            archive.writestr("meta.xml", extra)
        return stream.getvalue()

    old_data, new_data = odt("eski"), odt("yeni paket metadata")
    stored_file = tmp_path / "old.odt"
    stored_file.write_bytes(old_data)
    old_id = uuid4()

    class Rows:
        def fetchall(self):
            return [{"id": old_id, "owner_id": OWNER, "storage_path": "old.odt", "checksum_sha256": None}]

    class Connection:
        def execute(self, query, params):
            assert "size_bytes = %s" not in query
            return Rows()

    monkeypatch.setattr(office_public, "_storage_path", lambda *_: stored_file)
    assert len(old_data) != len(new_data)
    assert office_public.find_duplicate(
        Connection(), file_name="abc-Ek_1.odt", size_bytes=len(new_data),
        uyap_file_no="2024/1", source="uyap-avukat-eklentisi",
        evrak_key="abc", checksum_sha256=hashlib.sha256(new_data).hexdigest(),
        content_text=" ".join(extract_text_sample("abc-Ek_1.odt", new_data).split()),
    ) == old_id
