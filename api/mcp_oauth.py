"""ChatGPT / Claude bağlayıcıları için OAuth 2.1 (yetkilendirme kodu + PKCE, dinamik istemci kaydı) — yalnız MCP araçları için.

Tasarım (2026-10-26):
* Durumsuz: istemci kaydı, yetki kodu, erişim ve yenileme jetonu imzalı JWT'dir; yeni tablo yok. İmza anahtarı uygulamanın
  `JWT_SECRET`inden TÜRETİLEN ayrı bir anahtardır (`_mcp_secret`): bu jetonlar normal uç noktalarda (belgeler, davalar, UYAP)
  geçersizdir, normal oturum jetonu da burada bağlayıcı jetonu yerine geçmez. ChatGPT yalnız 4 okuma aracına erişir.
* Giriş, uygulamanın kendi `login` akışıyla yapılır: aynı parola denetimi, hatalı giriş kilidi, erişim listesi (AGENTS.md: yeni
  giriş yolu aynı denetimden geçer) ve denetim kaydı. Her MCP isteğinde erişim yeniden sorulur (`_session_state`): listeden
  çıkarılan ya da çıkış yapıp oturumlarını kapatan kullanıcının bağlayıcısı da düşer.
* Yönlendirme adresi kayıtta sabitlenir ve kod o adrese bağlıdır; PKCE (S256) zorunludur.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from urllib.parse import urlencode, urlparse
from uuid import UUID

import jwt
from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError

from api.auth.routes import _auth_secret, _session_state, login, resolve_session
from api.auth.schemas import LoginRequest
from api.auth.security import TokenError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["mcp-oauth"])

_ALGORITHM = "HS256"
_CODE_MINUTES = 5
_ACCESS_MINUTES = 60
_REFRESH_DAYS = 30
SCOPE = "legal:read"
_SESSION_BRIDGE_URL = "http://localhost:8878/approve"
_used_session_tickets: set[str] = set()


def _mcp_secret() -> str:
    """Normal oturum jetonlarından ayrı imza anahtarı (aynı sırdan HMAC ile türetilir)."""
    return hmac.new(_auth_secret().encode(), b"jurisai-mcp-oauth-v1", hashlib.sha256).hexdigest()


def _encode(claims: dict, ttl: timedelta) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({**claims, "iat": now, "exp": now + ttl}, _mcp_secret(), algorithm=_ALGORITHM)


def _decode(token: str, typ: str) -> dict:
    try:
        claims = jwt.decode(token, _mcp_secret(), algorithms=[_ALGORITHM])
    except jwt.InvalidTokenError as exc:
        raise TokenError("Geçersiz ya da süresi dolmuş jeton") from exc
    if claims.get("typ") != typ:
        raise TokenError("Yanlış jeton türü")
    return claims


def public_base(request: Request) -> str:
    """Dışarıdan görünen adres: MCP_PUBLIC_URL, yoksa vekil başlıkları, yoksa isteğin kendisi."""
    configured = os.getenv("MCP_PUBLIC_URL", "").strip().rstrip("/")
    if configured:
        return configured
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    return f"{scheme}://{host}".rstrip("/")


def mcp_user_id(request: Request, credentials: HTTPAuthorizationCredentials | None) -> UUID:
    """MCP isteğinin kullanıcısı: bağlayıcı erişim jetonu (ya da uygulamanın kendi oturumu, yerel deneme için)."""
    token = credentials.credentials if credentials else None
    if token:
        try:
            claims = _decode(token, "access")
            user_id = UUID(claims["sub"])
            valid_after, allowed = _session_state(user_id)
            if int(claims["iat"]) >= valid_after and allowed:
                return user_id
        except (TokenError, KeyError, ValueError):
            try:
                return resolve_session(token)
            except Exception:  # noqa: BLE001 - any failure is "not signed in"
                pass
    raise HTTPException(status_code=401, detail="Giriş gerekli",
                        headers={"WWW-Authenticate": f'Bearer resource_metadata="{public_base(request)}'
                                                     f'/.well-known/oauth-protected-resource"'})


# --- discovery -------------------------------------------------------------------------------------------------------

@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
def protected_resource(request: Request) -> dict:
    base = public_base(request)
    return {"resource": f"{base}/mcp", "authorization_servers": [base], "scopes_supported": [SCOPE],
            "bearer_methods_supported": ["header"], "resource_name": "JurisAI Türk hukuku kaynakları"}


@router.get("/.well-known/oauth-authorization-server")
def authorization_server(request: Request) -> dict:
    base = public_base(request)
    return {"issuer": base, "authorization_endpoint": f"{base}/oauth/authorize", "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register", "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"], "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"], "scopes_supported": [SCOPE]}


# --- client registration (RFC 7591) ---------------------------------------------------------------------------------

def _allowed_redirect(uri: str) -> bool:
    parsed = urlparse(uri)
    if parsed.fragment or not parsed.netloc:
        return False
    return parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"})


@router.post("/oauth/register", status_code=201)
async def register_client(request: Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        body = None
    uris = body.get("redirect_uris") if isinstance(body, dict) else None
    if not isinstance(uris, list) or not 1 <= len(uris) <= 5 or not all(isinstance(u, str) and _allowed_redirect(u) for u in uris):
        raise HTTPException(status_code=400, detail={"error": "invalid_redirect_uri"})
    name = str(body.get("client_name") or "MCP istemcisi")[:80]
    client_id = _encode({"typ": "client", "redirect_uris": uris, "name": name}, timedelta(days=3650))
    logger.info("mcp oauth client registered name=%s redirects=%s", name, uris)
    return {"client_id": client_id, "client_name": name, "redirect_uris": uris, "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"]}


def _client(client_id: str) -> dict:
    try:
        return _decode(client_id, "client")
    except TokenError as exc:
        raise HTTPException(status_code=400, detail="Bilinmeyen istemci") from exc


# --- authorization (login + consent) ---------------------------------------------------------------------------------

_FIELDS = ("response_type", "client_id", "redirect_uri", "code_challenge", "code_challenge_method", "state", "scope", "resource")


def _page(params: dict, client_name: str, error: str = "") -> HTMLResponse:
    hidden = "".join(f'<input type="hidden" name="{k}" value="{html.escape(str(params.get(k) or ""))}">' for k in _FIELDS)
    alert = f'<p class="e">{html.escape(error)}</p>' if error else ""
    body = f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JurisAI ile bağlan</title><style>
body{{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;display:grid;place-items:center;min-height:100vh;margin:0}}
form{{background:#1e293b;padding:28px;border-radius:14px;width:min(380px,92vw)}}h1{{font-size:20px;margin:0 0 6px}}
p{{font-size:14px;color:#94a3b8}}label{{display:block;font-size:13px;margin:14px 0 4px}}
input[type=email],input[type=password]{{width:100%;box-sizing:border-box;padding:10px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0}}
button{{margin-top:18px;width:100%;padding:11px;border:0;border-radius:8px;background:#3b82f6;color:#fff;font-weight:600;cursor:pointer}}
.e{{color:#fca5a5}}ul{{font-size:13px;color:#cbd5e1;padding-left:18px}}</style></head><body>
<form method="post" action="/oauth/authorize">{hidden}<h1>JurisAI ile bağlan</h1>
<p><b>{html.escape(client_name)}</b> JurisAI hesabınızla şu izni istiyor:</p>
<ul><li>Doğrulanmış mevzuat ve yargı kararlarında arama ve okuma</li><li>Karar atıflarını doğrulama</li></ul>
<p>Belgeleriniz, davalarınız ve UYAP kayıtlarınız paylaşılmaz.</p>{alert}
<label for="email">E-posta</label><input id="email" name="email" type="email" autocomplete="username" required>
<label for="password">Şifre</label><input id="password" name="password" type="password" autocomplete="current-password" required>
<button type="submit">Giriş yap ve izin ver</button></form></body></html>"""
    session_link = f'/oauth/session/start?{urlencode({k: str(params.get(k) or "") for k in _FIELDS})}'
    body = body.replace("</form>", f'<a href="{html.escape(session_link, quote=True)}" '
                        'style="display:block;margin-top:18px;color:#93c5fd">'
                        'Google ile açtığım mevcut JurisAI oturumuyla devam et</a></form>')
    return HTMLResponse(body, headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"})


def _check_request(params: dict) -> dict:
    if params.get("response_type") != "code" or params.get("code_challenge_method") != "S256" or not params.get("code_challenge"):
        raise HTTPException(status_code=400, detail="Yalnız PKCE (S256) ile yetkilendirme kodu desteklenir")
    client = _client(str(params.get("client_id") or ""))
    if params.get("redirect_uri") not in client["redirect_uris"]:
        raise HTTPException(status_code=400, detail="Yönlendirme adresi bu istemciye kayıtlı değil")
    return client


@router.get("/oauth/authorize")
def authorize_page(request: Request) -> HTMLResponse:
    params = {k: request.query_params.get(k) for k in _FIELDS}
    client = _check_request(params)
    return _page(params, client["name"])


@router.get("/oauth/session/start")
def session_start(request: Request) -> RedirectResponse:
    """Send a signed OAuth request to the user's loopback-only session bridge."""
    params = {k: request.query_params.get(k) for k in _FIELDS}
    _check_request(params)
    base = public_base(request)
    if not base.startswith("https://"):
        raise HTTPException(status_code=400, detail="HTTPS gerekli")
    flow = _encode({"typ": "session_flow", "params": params, "base": base}, timedelta(minutes=5))
    return RedirectResponse(f"{_SESSION_BRIDGE_URL}?{urlencode({'flow': flow})}", status_code=303)


@router.get("/oauth/session/finish")
def session_finish(request: Request, ticket: str) -> RedirectResponse:
    """Exchange a short-lived proof of an existing JurisAI session for an OAuth code."""
    try:
        claims = _decode(ticket, "session_ticket")
        params = claims["params"]
        user_id = UUID(claims["sub"])
        if claims["base"] != public_base(request) or ticket in _used_session_tickets:
            raise ValueError("Invalid origin or replayed ticket")
        _check_request(params)
        valid_after, allowed = _session_state(user_id)
        if not allowed or int(claims["iat"]) < valid_after:
            raise ValueError("Session revoked")
    except (TokenError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Oturum yetkisi geçersiz veya süresi dolmuş") from exc
    _used_session_tickets.add(ticket)
    if len(_used_session_tickets) > 10_000:
        _used_session_tickets.clear()
    code = _encode({"typ": "code", "sub": str(user_id), "client": params["client_id"][-32:],
                    "redirect_uri": params["redirect_uri"], "challenge": params["code_challenge"]},
                   timedelta(minutes=_CODE_MINUTES))
    query = urlencode({"code": code, **({"state": params["state"]} if params.get("state") else {})})
    redirect = params["redirect_uri"]
    return RedirectResponse(f"{redirect}{'&' if '?' in redirect else '?'}{query}", status_code=303,
                            headers={"Cache-Control": "no-store"})


@router.post("/oauth/authorize")
def authorize_submit(request: Request, email: Annotated[str, Form()], password: Annotated[str, Form()],
                     response_type: Annotated[str, Form()] = "", client_id: Annotated[str, Form()] = "",
                     redirect_uri: Annotated[str, Form()] = "", code_challenge: Annotated[str, Form()] = "",
                     code_challenge_method: Annotated[str, Form()] = "", state: Annotated[str, Form()] = "",
                     scope: Annotated[str, Form()] = "", resource: Annotated[str, Form()] = "") -> Response:
    params = {"response_type": response_type, "client_id": client_id, "redirect_uri": redirect_uri,
              "code_challenge": code_challenge, "code_challenge_method": code_challenge_method, "state": state,
              "scope": scope, "resource": resource}
    client = _check_request(params)
    try:
        signed_in = login(LoginRequest(email=email, password=password), Response(), request)
    except ValidationError:
        return _page(params, client["name"], "E-posta ya da şifre geçersiz.")
    except HTTPException as exc:
        return _page(params, client["name"], str(exc.detail))
    code = _encode({"typ": "code", "sub": str(signed_in.user.id), "client": client_id[-32:], "redirect_uri": redirect_uri,
                    "challenge": code_challenge}, timedelta(minutes=_CODE_MINUTES))
    logger.info("mcp oauth authorized user=%s client=%s", signed_in.user.id, client["name"])
    query = urlencode({"code": code, **({"state": state} if state else {})})
    return RedirectResponse(f"{redirect_uri}{'&' if '?' in redirect_uri else '?'}{query}", status_code=302)


# --- token ------------------------------------------------------------------------------------------------------------

def _tokens(user_id: str) -> dict:
    return {"access_token": _encode({"typ": "access", "sub": user_id, "scope": SCOPE}, timedelta(minutes=_ACCESS_MINUTES)),
            "token_type": "Bearer", "expires_in": _ACCESS_MINUTES * 60, "scope": SCOPE,
            "refresh_token": _encode({"typ": "refresh", "sub": user_id}, timedelta(days=_REFRESH_DAYS))}


def _token_error(code: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status_code, headers={"Cache-Control": "no-store"})


@router.post("/oauth/token")
async def token(request: Request) -> Response:
    form: dict[str, Any] = dict(await request.form())
    grant = form.get("grant_type")
    try:
        if grant == "authorization_code":
            claims = _decode(str(form.get("code") or ""), "code")
            verifier = str(form.get("code_verifier") or "")
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if (not verifier or not hmac.compare_digest(challenge, claims["challenge"])
                    or form.get("redirect_uri") != claims["redirect_uri"]
                    or str(form.get("client_id") or "")[-32:] != claims["client"]):
                return _token_error("invalid_grant")
        elif grant == "refresh_token":
            claims = _decode(str(form.get("refresh_token") or ""), "refresh")
        else:
            return _token_error("unsupported_grant_type")
        user_id = UUID(claims["sub"])
        valid_after, allowed = _session_state(user_id)
        if not allowed or int(claims["iat"]) < valid_after:
            return _token_error("invalid_grant")
    except (TokenError, KeyError, ValueError):
        return _token_error("invalid_grant")
    return JSONResponse(_tokens(str(user_id)), headers={"Cache-Control": "no-store"})
