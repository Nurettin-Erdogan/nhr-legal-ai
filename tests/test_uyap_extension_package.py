"""Kullanıcıya özel UYAP eklenti paketi: anahtar zipe gömülür, veritabanına yalnız bu istekte oluşur, eskileri iptal eder."""

from __future__ import annotations

import contextlib
import io
import json
import re
import zipfile
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import uyap_extension_package as package
from api.auth.routes import current_user_id

KEY_FORMAT = re.compile(r"^jsai_[A-Za-z0-9]{20,200}$")  # background.js BRIDGE_SET_KEY ve applyBundledKey ile aynı


def _general_zip() -> bytes:
    return package.PACKAGE.read_bytes()


def test_generated_keys_have_the_format_the_extension_accepts_and_never_repeat():
    keys = {package.new_key() for _ in range(50)}
    assert len(keys) == 50
    assert all(KEY_FORMAT.match(key) for key in keys)


def test_personalising_adds_only_the_config_file_and_keeps_every_other_byte():
    original = _general_zip()
    key = package.new_key()
    personal = zipfile.ZipFile(io.BytesIO(package.personalise(original, key)))
    general = zipfile.ZipFile(io.BytesIO(original))
    assert set(personal.namelist()) - set(general.namelist()) == {package.CONFIG_NAME}
    assert set(general.namelist()) <= set(personal.namelist())
    for name in general.namelist():
        assert personal.read(name) == general.read(name), name
    assert json.loads(personal.read(package.CONFIG_NAME)) == {"apiKey": key}


def test_the_general_package_never_contains_a_key_and_is_refused_if_it_does():
    original = _general_zip()
    assert package.CONFIG_NAME not in zipfile.ZipFile(io.BytesIO(original)).namelist()
    once = package.personalise(original, package.new_key())
    with pytest.raises(ValueError):
        package.personalise(once, package.new_key())


def test_the_extension_reads_the_bundled_key_and_does_not_overwrite_a_newer_one():
    source = (package.PACKAGE.parents[0] / "jurisai-avukat" / "background.js").read_text(encoding="utf-8")
    assert 'chrome.runtime.getURL("jurisai-config.json")' in source
    assert "bundledKeyApplied" in source  # aynı anahtar yeniden uygulanmaz
    assert source.count("applyBundledKey()") >= 3  # açılışta, kurulumda ve tarayıcı başlangıcında


class _Connection:
    def __init__(self, log):
        self.log = log

    def execute(self, sql, params=()):
        self.log.append((" ".join(sql.split()), params))


def _client(monkeypatch, log, *, audit=None):
    user = uuid4()

    @contextlib.contextmanager
    def connection(user_id):
        assert user_id == str(user)
        yield _Connection(log)

    monkeypatch.setattr(package, "authenticated_database_connection", connection)
    monkeypatch.setattr(package, "record_event", lambda conn, **kw: (audit if audit is not None else []).append(kw))
    app = FastAPI()
    app.include_router(package.router)
    app.dependency_overrides[current_user_id] = lambda: user
    return TestClient(app), user


def test_download_embeds_the_same_key_it_stores_revokes_old_keys_and_audits_without_the_key(monkeypatch):
    log: list = []
    audit: list = []
    client, user = _client(monkeypatch, log, audit=audit)
    response = client.post("/api/uyap-extension/package")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    key = json.loads(zipfile.ZipFile(io.BytesIO(response.content)).read(package.CONFIG_NAME))["apiKey"]
    assert KEY_FORMAT.match(key)

    revoke, insert = log
    assert "SET revoked = true" in revoke[0] and revoke[1] == (user,)
    assert "INSERT INTO office_uyap_ingest_tokens" in insert[0] and insert[1][1:3] == (user, key)
    assert len(audit) == 1 and audit[0]["action"] == "uyap.extension_package_download"
    assert key not in str(audit)  # denetim kaydına düz anahtar yazılmaz
    assert audit[0]["metadata"] == {"key_prefix": key[:9]}


def test_every_download_gets_a_fresh_key(monkeypatch):
    client, _ = _client(monkeypatch, [])
    keys = {
        json.loads(zipfile.ZipFile(io.BytesIO(client.post("/api/uyap-extension/package").content)).read(package.CONFIG_NAME))["apiKey"]
        for _ in range(3)
    }
    assert len(keys) == 3


def test_without_a_session_nothing_is_created_or_served(monkeypatch):
    log: list = []
    monkeypatch.setattr(package, "authenticated_database_connection", lambda user_id: pytest.fail("oturumsuz DB erişimi"))
    app = FastAPI()
    app.include_router(package.router)
    response = TestClient(app).post("/api/uyap-extension/package")
    assert response.status_code == 401
    assert log == []


def test_a_missing_general_package_is_a_clear_503_and_creates_no_key(monkeypatch, tmp_path):
    log: list = []
    client, _ = _client(monkeypatch, log)
    monkeypatch.setattr(package, "PACKAGE", tmp_path / "yok.zip")
    assert client.post("/api/uyap-extension/package").status_code == 503
    assert log == []
