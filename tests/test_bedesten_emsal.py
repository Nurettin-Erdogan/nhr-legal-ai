"""Bedesten emsal-karar istemcisi ve toplayıcı yardımcıları. Ağ ve veritabanı gerekmez."""

from __future__ import annotations

import base64
import io
import json
import urllib.error
from datetime import date

import pytest

from ingestion import bedesten_emsal
from ingestion.bedesten_emsal import BedestenClient, BedestenError, BedestenRateLimited, day_window


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Opener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(json.loads(request.data))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return _Response(json.dumps(item).encode("utf-8"))


@pytest.fixture(autouse=True)
def _isolated_cooldown(tmp_path, monkeypatch):
    monkeypatch.setattr(bedesten_emsal, "COOLDOWN_FILE", tmp_path / "cooldown.json")
    monkeypatch.setattr(bedesten_emsal.time, "sleep", lambda _seconds: None)


def _client(*responses):
    opener = _Opener(*responses)
    return BedestenClient(min_interval=5.0, opener=opener), opener


def test_day_window_uses_turkey_local_day():
    assert day_window(date(2026, 9, 17)) == ("2026-09-16T21:00:00.000Z", "2026-09-17T20:59:59.000Z")


def test_search_parses_items_and_total():
    payload = {
        "data": {
            "total": 2,
            "emsalKararList": [
                {"documentId": "1227640000", "birimAdi": "1. Hukuk Dairesi", "esasNo": "2026/6584",
                 "kararNo": "2026/6111", "kararTarihiStr": "17.09.2026"},
                {"documentId": None, "birimAdi": "x"},
            ],
        },
        "metadata": {"FMTY": "SUCCESS"},
    }
    client, opener = _client(payload)

    page = client.search("yargitay", date(2026, 9, 17), date(2026, 9, 17), page_size=500)

    assert page.total == 2 and len(page.items) == 1
    item = page.items[0]
    assert (item.document_id, item.chamber, item.docket_no, item.decision_date) == (
        "1227640000", "1. Hukuk Dairesi", "2026/6584", date(2026, 9, 17))
    sent = opener.requests[0]["data"]
    assert sent["itemTypeList"] == ["YARGITAYKARARI"] and sent["pageSize"] == 100
    assert sent["kararTarihiStart"] == "2026-09-16T21:00:00.000Z"


def test_content_is_decoded_from_base64():
    html = "<html><body>Karar metni</body></html>"
    client, _ = _client({"data": {"content": base64.b64encode(html.encode()).decode()}, "metadata": {}})

    assert client.content_html("1") == html


def test_rate_limit_writes_shared_cooldown_and_raises():
    error = urllib.error.HTTPError("u", 429, "Too Many", {}, None)
    client, _ = _client(error)

    with pytest.raises(BedestenRateLimited) as raised:
        client.content_html("1")

    assert "429" in str(raised.value)
    assert bedesten_emsal.read_cooldown() > 0


def test_service_error_metadata_is_reported():
    client, _ = _client({"data": None, "metadata": {"FMTY": "ERROR", "FMTE": "Lütfen Arama Kriterlerini Kontrol Ediniz!"}})

    with pytest.raises(BedestenError, match="Arama Kriterlerini"):
        client.search("danistay", date(2026, 1, 1), date(2026, 1, 1))


def test_slots_are_shared_between_clients():
    first = bedesten_emsal.reserve_slot(5.0)
    second = bedesten_emsal.reserve_slot(5.0)

    assert first == 0.0 and 4.0 < second <= 5.0
