"""UYAP eklentisi uç noktaları ve üst veri ayrıştırma. Veritabanı sahtelenir."""

from __future__ import annotations

import base64
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

    assert response.json() == {"ok": True, "found": 2, "inserted": 1, "skipped": 1}
    assert stored[0]["owner_id"] == OWNER
    assert "/" not in stored[0]["file_name"] and stored[0]["file_name"].endswith(".pdf")


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
