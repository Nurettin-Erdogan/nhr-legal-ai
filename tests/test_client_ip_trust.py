"""Giriş deneme sınırı ve denetim kaydı istemci IP'sine dayanır; bu IP'nin nereden geldiği burada sabitlenir.

Ölçüldü (2026-10-08): uvicorn varsayılan ayarıyla `127.0.0.1`'den gelen isteklerde `X-Forwarded-For` başlığını okur
(`proxy_headers=True`, güvenilen adres `127.0.0.1`). Yani aynı makinedeki ters vekilin arkasında gerçek istemci adresi
kendiliğinden gelir; başka adresten bağlanan istemcinin yazdığı başlık ise yok sayılır. Bu varsayım değişirse (uvicorn
güncellemesi, farklı başlatma) testler düşer: sınır herkes için tek adrese çökmesin ya da istemci adres uydurabilmesin.
"""

from __future__ import annotations

import asyncio

from uvicorn.config import Config
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from api.audit import AuditContext
from api.main import app


def _seen_client(peer: str, forwarded: str | None, trusted: str = "127.0.0.1") -> str:
    """Vekil başlığı katmanından sonra uygulamanın gördüğü istemci adresi."""
    seen: dict = {}

    async def inner(scope, receive, send):
        seen["client"] = scope["client"]

    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    scope = {"type": "http", "client": (peer, 50000), "headers": headers, "scheme": "http"}
    asyncio.run(ProxyHeadersMiddleware(inner, trusted_hosts=trusted)(scope, None, None))
    return seen["client"][0]


def test_the_server_reads_forwarded_headers_only_from_the_local_proxy_by_default(monkeypatch):
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    config = Config(app)

    assert config.proxy_headers is True
    trusted = {item.strip() for item in str(config.forwarded_allow_ips).split(",")}
    assert "127.0.0.1" in trusted and trusted <= {"127.0.0.1", "::1"}  # yalnız bu makine; sürüme göre ::1 de olabilir


def test_behind_the_local_proxy_the_real_client_address_is_used():
    assert _seen_client("127.0.0.1", "203.0.113.9") == "203.0.113.9"


def test_an_address_the_client_wrote_itself_is_ignored_when_the_proxy_appends_the_real_one():
    # nginx `$proxy_add_x_forwarded_for`: istemcinin yazdığı değer solda kalır, vekil gerçek adresi sağa ekler.
    assert _seen_client("127.0.0.1", "10.9.9.9, 203.0.113.9") == "203.0.113.9"


def test_a_client_connecting_directly_cannot_choose_its_address():
    assert _seen_client("203.0.113.50", "10.9.9.9") == "203.0.113.50"


def test_a_proxy_on_another_host_is_trusted_only_when_configured():
    assert _seen_client("10.0.0.5", "203.0.113.9") == "10.0.0.5"
    assert _seen_client("10.0.0.5", "203.0.113.9", trusted="10.0.0.5") == "203.0.113.9"


def test_the_audit_record_takes_the_address_the_server_resolved():
    class _Request:
        headers = {"x-forwarded-for": "10.9.9.9", "user-agent": "test"}

        class client:  # noqa: N801 - Starlette istek nesnesindeki ad
            host = "203.0.113.50"

    # Uygulama başlığı kendisi yorumlamaz: güven kararı tek yerde (sunucu katmanında) verilir.
    assert AuditContext.from_request(_Request()).ip_address == "203.0.113.50"
