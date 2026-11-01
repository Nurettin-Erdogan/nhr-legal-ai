"""JurisAI MCP uç noktası (api/mcp_server.py): ChatGPT/Claude'a yalnız doğrulanmış kamu korpusunu araç olarak açar."""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi.testclient import TestClient

from api import mcp_server
from api.main import app
from api.mcp_public import app as public_mcp_app
from api.mcp_local_bridge import app as local_bridge_app

USER = uuid4()


def call(method, params=None, request_id=1):
    message = {"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})}
    if request_id is not None:
        message["id"] = request_id
    return mcp_server._handle(message, USER)


def test_initialize_announces_tools_and_the_usage_rules():
    result = call("initialize", {"protocolVersion": "2025-06-18"})["result"]
    assert result["capabilities"] == {"tools": {"listChanged": False}} and result["protocolVersion"] == "2025-06-18"
    assert "atif_dogrula" in result["instructions"]


def test_the_four_tools_are_read_only():
    tools = call("tools/list")["result"]["tools"]
    assert [t["name"] for t in tools] == ["search", "fetch", "madde_metni", "atif_dogrula"]
    assert all(t["annotations"]["readOnlyHint"] for t in tools)


def test_madde_metni_preserves_slash_in_article_number(monkeypatch):
    seen = {}

    def fake_query(where, params, *, limit):
        seen["where"], seen["params"] = where, params
        return [{"id": uuid4(), "law_name": "Hukuk Uyuşmazlıklarında Arabuluculuk Kanunu",
                 "law_no": "6325", "article_no": "18/B", "source_type": "legislation",
                 "source_url": "https://www.mevzuat.gov.tr/", "text": "MADDE 18/B"}]

    monkeypatch.setattr(mcp_server, "_query", fake_query)
    result = mcp_server._article({"kanun_no": "6325", "madde_no": "Madde 18 / B"})
    assert result["found"] is True
    assert seen["params"] == ("6325", "18/b")
    assert "l.article_no" in seen["where"]


def test_a_notification_gets_no_reply_and_unknown_methods_and_tools_are_errors():
    assert call("notifications/initialized", request_id=None) is None
    assert call("resources/list")["error"]["code"] == -32601
    assert call("tools/call", {"name": "sil", "arguments": {}})["error"]["code"] == -32602


def test_a_bad_argument_is_a_tool_error_the_assistant_can_read(monkeypatch):
    result = call("tools/call", {"name": "atif_dogrula", "arguments": {"atif": "Yargıtay kararı"}})["result"]
    assert result["isError"] and "esas numarası" in json.loads(result["content"][0]["text"])["error"]
    assert call("tools/call", {"name": "fetch", "arguments": {"id": "x"}})["result"]["isError"]


def test_a_tool_result_is_returned_as_text_and_structured_content(monkeypatch):
    monkeypatch.setitem(mcp_server._HANDLERS, "search", lambda args: {"results": [{"id": "1", "title": "T", "url": None}]})
    result = call("tools/call", {"name": "search", "arguments": {"query": "kıdem"}})["result"]
    assert result["structuredContent"]["results"][0]["title"] == "T" and not result["isError"]
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]


def test_citation_matching_requires_the_named_court_and_chamber(monkeypatch):
    rows = [{"id": uuid4(), "court_name": "Danıştay", "chamber": "5. Daire", "docket_no": "2023/9430", "decision_no": "2023/1",
             "decision_date": None, "text": "a", "source_type": "court_decision"},
            {"id": uuid4(), "court_name": "Yargıtay", "chamber": "9. Hukuk Dairesi", "docket_no": "2023/9430",
             "decision_no": "2023/8075", "decision_date": None, "text": "b", "source_type": "court_decision"}]
    monkeypatch.setattr(mcp_server, "_query", lambda *a, **k: rows)
    assert mcp_server._verify({"atif": "Yargıtay 9. HD 2023/9430 E."})["verified"] is True
    missing = mcp_server._verify({"atif": "Yargıtay 3. Hukuk Dairesi 2023/9430 E."})
    assert missing["verified"] is False and len(missing["ayni_esas_numarali_diger_kararlar"]) == 2


def test_the_endpoint_requires_a_signed_in_allowed_user():
    response = TestClient(app).post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 401


def test_public_mcp_surface_exposes_only_mcp_and_oauth_routes():
    client = TestClient(public_mcp_app)
    metadata = client.get("/.well-known/oauth-protected-resource",
                          headers={"x-forwarded-host": "example.trycloudflare.com", "x-forwarded-proto": "https"})
    assert metadata.status_code == 200
    assert metadata.json()["resource"] == "https://example.trycloudflare.com/mcp"
    # OAuth 2.1 is supported, but there is no OIDC ID token/userinfo service.
    assert client.get("/.well-known/openid-configuration").status_code == 404
    authorization = client.get("/.well-known/oauth-authorization-server").json()
    assert authorization["scopes_supported"] == ["legal:read"]
    assert client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 401
    for path in ("/docs", "/openapi.json", "/api/ai/answer", "/api/documents", "/api/auth/login"):
        assert client.get(path).status_code == 404


def test_public_transport_diagnostics_never_log_credentials_or_request_data(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="uvicorn.error")
    client = TestClient(public_mcp_app)
    response = client.post("/mcp?ticket=private-query", headers={"Authorization": "Bearer private-token"},
                           json={"private": "private-body"})
    assert response.status_code == 401
    client.get("/private-path")
    messages = "\n".join(record.getMessage() for record in caplog.records
                         if record.name == "uvicorn.error")
    assert "path=/mcp status=401" in messages
    assert "path=[other] status=404" in messages
    assert not any(value in messages for value in ("private-query", "private-token", "private-body", "private-path"))


def _oauth_client(monkeypatch):
    from types import SimpleNamespace

    from api import mcp_oauth

    user = uuid4()
    monkeypatch.setattr(mcp_oauth, "_session_state", lambda _u: (0, True))
    monkeypatch.setattr(mcp_oauth, "login", lambda *a, **k: SimpleNamespace(user=SimpleNamespace(id=user)))
    monkeypatch.setattr("api.auth.routes._auth_secret", lambda: "x" * 40)
    monkeypatch.setattr(mcp_oauth, "_auth_secret", lambda: "x" * 40)
    return TestClient(app), user


def _authorize(client, verifier="v" * 50, redirect="https://chatgpt.com/connector_platform_oauth_redirect"):
    import base64
    import hashlib
    from urllib.parse import parse_qs, urlparse

    client_id = client.post("/oauth/register", json={"redirect_uris": [redirect]}).json()["client_id"]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    form = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect, "code_challenge": challenge,
            "code_challenge_method": "S256", "state": "s", "email": "a@example.com", "password": "p"}
    location = client.post("/oauth/authorize", data=form, follow_redirects=False).headers["location"]
    return client_id, parse_qs(urlparse(location).query)["code"][0]


def test_the_connector_token_works_only_with_pkce_and_only_on_the_mcp_tools(monkeypatch):
    client, _user = _oauth_client(monkeypatch)
    client_id, code = _authorize(client)
    redirect = "https://chatgpt.com/connector_platform_oauth_redirect"
    wrong = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "code_verifier": "w" * 50,
                                              "redirect_uri": redirect, "client_id": client_id})
    assert wrong.status_code == 400
    tokens = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "code_verifier": "v" * 50,
                                               "redirect_uri": redirect, "client_id": client_id}).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 200
    from api.auth.routes import resolve_session
    from api.auth.security import TokenError
    import pytest

    with pytest.raises(TokenError):  # the app's own endpoints never accept a connector token
        resolve_session(tokens["access_token"])


def test_a_redirect_that_was_not_registered_or_is_not_https_is_refused(monkeypatch):
    client, _user = _oauth_client(monkeypatch)
    assert client.post("/oauth/register", json={"redirect_uris": ["http://evil.example/cb"]}).status_code == 400
    client_id = client.post("/oauth/register", json={"redirect_uris": ["https://chatgpt.com/cb"]}).json()["client_id"]
    page = client.get("/oauth/authorize", params={"response_type": "code", "client_id": client_id,
                                                  "redirect_uri": "https://evil.example/cb", "code_challenge": "c",
                                                  "code_challenge_method": "S256"})
    assert page.status_code == 400


def test_existing_google_session_bridge_keeps_app_cookie_on_loopback(monkeypatch):
    import base64
    import hashlib
    from urllib.parse import parse_qs, urlparse
    from api import mcp_local_bridge, mcp_oauth

    monkeypatch.setattr(mcp_oauth, "_auth_secret", lambda: "x" * 40)
    monkeypatch.setattr(mcp_local_bridge, "_user", lambda request: USER)
    monkeypatch.setattr(mcp_oauth, "_session_state", lambda user: (0, True))
    public = TestClient(public_mcp_app)
    bridge = TestClient(local_bridge_app)
    redirect = "https://chatgpt.com/connector/oauth/test"
    client_id = public.post("/oauth/register", json={"redirect_uris": [redirect]}).json()["client_id"]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(b"v" * 50).digest()).rstrip(b"=").decode()
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect,
              "code_challenge": challenge, "code_challenge_method": "S256", "state": "abc"}
    headers = {"x-forwarded-host": "example.trycloudflare.com", "x-forwarded-proto": "https"}
    start = public.get("/oauth/session/start", params=params, headers=headers, follow_redirects=False)
    assert start.status_code == 303
    flow = parse_qs(urlparse(start.headers["location"]).query)["flow"][0]
    assert bridge.get("/approve", params={"flow": flow}).status_code == 200
    approved = bridge.post("/approve", data={"flow": flow}, follow_redirects=False)
    assert approved.status_code == 303
    assert approved.headers["location"].startswith("https://example.trycloudflare.com/oauth/session/finish?")
    ticket = parse_qs(urlparse(approved.headers["location"]).query)["ticket"][0]
    finished = public.get("/oauth/session/finish", params={"ticket": ticket}, headers=headers,
                          follow_redirects=False)
    assert finished.status_code == 303
    assert finished.headers["location"].startswith(redirect + "?code=")
    assert public.get("/oauth/session/finish", params={"ticket": ticket}, headers=headers).status_code == 400
