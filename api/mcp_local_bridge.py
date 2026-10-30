"""Loopback-only approval bridge for a user already signed in to JurisAI.

This app is deliberately separate from the public MCP/OAuth app. It reads the
normal localhost session cookie, then returns only a short-lived signed proof
to the public OAuth endpoint; the app session itself never leaves localhost.
"""

from datetime import timedelta
from html import escape
from urllib.parse import urlencode, urlparse

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from api.auth.routes import COOKIE_NAME, resolve_session
from api.auth.security import TokenError
from api.mcp_oauth import _check_request, _decode, _encode

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def _flow(flow: str) -> dict:
    try:
        claims = _decode(flow, "session_flow")
        base = claims["base"]
        parsed = urlparse(base)
        if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".trycloudflare.com"):
            raise ValueError("Unexpected public host")
        _check_request(claims["params"])
        return claims
    except (TokenError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Bağlantı isteği geçersiz veya süresi dolmuş") from exc


def _user(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Önce localhost:3000 üzerindeki JurisAI uygulamasına Google ile giriş yapın")
    try:
        return resolve_session(token)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail="JurisAI oturumu geçersiz; yeniden Google ile giriş yapın") from exc


@app.get("/approve")
def approval_page(request: Request, flow: str) -> HTMLResponse:
    claims = _flow(flow)
    _user(request)
    client = _check_request(claims["params"])
    body = ("<!doctype html><html lang='tr'><meta charset='utf-8'><title>JurisAI MCP izni</title>"
            "<body style='font-family:system-ui;max-width:520px;margin:12vh auto'>"
            "<h1>JurisAI MCP bağlantısı</h1><p>Bu bilgisayardaki mevcut JurisAI oturumunuzla "
            f"{escape(client['name'])} için doğrulanmış kamu hukuku kaynaklarına okuma izni verilecek. "
            "Özel belgeler, davalar ve UYAP verileri açılmaz.</p>"
            "<form method='post' action='/approve'>"
            f"<input type='hidden' name='flow' value='{escape(flow, quote=True)}'>"
            "<button type='submit'>ChatGPT bağlantısına izin ver</button></form></body></html>")
    return HTMLResponse(body, headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"})


@app.post("/approve")
def approve(request: Request, flow: str = Form()) -> RedirectResponse:
    claims = _flow(flow)
    user_id = _user(request)
    ticket = _encode({"typ": "session_ticket", "sub": str(user_id), "params": claims["params"],
                      "base": claims["base"]}, timedelta(seconds=60))
    return RedirectResponse(f"{claims['base']}/oauth/session/finish?{urlencode({'ticket': ticket})}",
                            status_code=303, headers={"Cache-Control": "no-store"})
