"""Vatandaş başvuru formu: KVKK aydınlatma metni onayı olmadan kişisel veri alınmaz; onay kaydı tutulur."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from api import office_public
from tests.test_ai_persistence import connection as _connection_fixture

connection = _connection_fixture

pytestmark = pytest.mark.skipif(not os.getenv("NHR_TEST_DATABASE_URL"), reason="Isolated test DB not configured")


@pytest.fixture
def api(connection, monkeypatch):  # noqa: F811
    @contextmanager
    def database_connection():
        yield connection

    monkeypatch.setattr("api.db.database_connection", database_connection)
    office_public._application_hits.clear()
    return connection


def _send(**overrides):
    values = dict(ad_soyad="Ayşe Test", telefon="05320000000", eposta=None, hukuk_alani="İş Hukuku", konu="PYTESTBASVURU işten çıkarıldım", sohbet_ozeti=None)
    values.update(overrides)
    request = SimpleNamespace(client=SimpleNamespace(host="203.0.113.7"))
    response = office_public.create_application(office_public.ApplicationRequest(**values), request)
    return response.status_code, json.loads(response.body)


def _rows(connection):
    return connection.execute("SELECT kvkk_aydinlatma_at, kvkk_aydinlatma_surum FROM office_basvurular WHERE konu LIKE 'PYTESTBASVURU%'").fetchall()


def test_an_application_without_the_privacy_notice_is_refused_and_nothing_is_stored(api):
    status, body = _send()
    assert status == 400 and "aydınlatma" in body["error"]
    assert _rows(api) == []
    assert _send(aydinlatma_okundu=False)[0] == 400 and _rows(api) == []


def test_the_acknowledgement_and_the_notice_version_are_recorded(api):
    status, body = _send(aydinlatma_okundu=True, aydinlatma_surum="2026-10-taslak")
    assert status == 200 and body == {"ok": True}
    [row] = _rows(api)
    assert row["kvkk_aydinlatma_at"] is not None and row["kvkk_aydinlatma_surum"] == "2026-10-taslak"


def test_a_missing_version_is_stored_as_null_and_an_oversized_one_is_rejected(api):
    assert _send(aydinlatma_okundu=True)[0] == 200
    assert _rows(api)[0]["kvkk_aydinlatma_surum"] is None
    with pytest.raises(Exception):
        office_public.ApplicationRequest(ad_soyad="Ayşe", telefon="1", konu="konu", aydinlatma_okundu=True, aydinlatma_surum="x" * 41)
