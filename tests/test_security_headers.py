"""API yanıtlarında tarayıcı güvenlik başlıkları."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from api import main


def test_every_response_carries_the_browser_security_headers_even_errors():
    client = TestClient(main.app)
    for path in ("/api/auth/session", "/yok-boyle-bir-yol", "/api/office/execution/files"):
        headers = client.get(path).headers
        assert headers["x-content-type-options"] == "nosniff", path
        assert headers["x-frame-options"] == "DENY", path
        assert headers["referrer-policy"] == "no-referrer", path
        assert headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'", path


def test_interactive_docs_are_not_broken_by_the_content_policy():
    headers = TestClient(main.app).get("/docs").headers
    assert "content-security-policy" not in headers and headers["x-frame-options"] == "DENY"


def test_every_api_method_passes_the_browser_cors_preflight():
    # Yönetici panelinin PUT/PATCH uçları sunucu testlerini geçti ama tarayıcıda CORS ön kontrolüne takıldı (2026-10-24).
    # Yollar OpenAPI şemasından okunur: bu FastAPI sürümünde dahil edilen yönlendiricilerin uçları `app.routes`ta görünmüyor.
    cors = next(entry for entry in main.app.user_middleware if entry.cls is CORSMiddleware)
    allowed = {method.lower() for method in cors.kwargs["allow_methods"]} | {"head"}
    http_methods = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
    paths = main.app.openapi()["paths"]
    blocked = sorted(
        f"{method.upper()} {path}"
        for path, operations in paths.items()
        for method in operations
        if method in http_methods and method not in allowed
    )
    assert blocked == []
    assert len(paths) > 50 and "/api/admin/registration" in paths  # tarama boş geçmesin


def test_hsts_is_sent_only_when_the_deployment_uses_secure_cookies(monkeypatch):
    client = TestClient(main.app)
    assert "strict-transport-security" not in client.get("/yok").headers  # yerel HTTP
    monkeypatch.setattr(main, "settings", SimpleNamespace(auth_cookie_secure=True))
    assert client.get("/yok").headers["strict-transport-security"].startswith("max-age=31536000")
