"""JurisAI'yi ChatGPT / Claude gibi asistanlara araç olarak bağlayan MCP uç noktası (kullanıcı kararı 2026-10-26).

Kullanıcı kendi asistanına JurisAI'yi bir kez bağlar; asistan Türk hukuku sorusunda buradaki araçları çağırır. Cevabı kullanıcının
asistanı yazar, biz yalnız DOĞRULANMIŞ resmî kaynağı (`api.legal._VERIFIED_SOURCE_FILTER`) ve atıf denetimini veririz; bu kanalda
"her cümle kanıtlı" denetimimiz çalışmaz, araç açıklamaları bunu asistana açıkça söyler. Yalnız kamuya açık hukuk korpusu döner:
kullanıcının belgeleri, davaları ve UYAP kayıtları bu araçlara hiç bağlanmaz.

Protokol: MCP "streamable HTTP" uç noktası, JSON-RPC 2.0 (`initialize`, `tools/list`, `tools/call`, `ping`); yalnız tek seferlik
JSON yanıt verilir (akış yok). Giriş, bağlayıcının OAuth jetonuyla (`api.mcp_oauth`) ya da yerel denemede uygulama oturumuyla; ikisi de erişim listesinden geçer.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Annotated, Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import JSONResponse, Response

from api.mcp_oauth import mcp_user_id
from api.db import database_connection
from api.legal import _VERIFIED_SOURCE_FILTER, search_legal_sources
from ingestion.mevzuat.identity import canonical_article

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mcp"])
_bearer = HTTPBearer(auto_error=False)

PROTOCOL_VERSION = "2025-06-18"
_MAX_TEXT_CHARS = 20_000
_INSTRUCTIONS = (
    "JurisAI, Türk mevzuatının ve Yargıtay/Danıştay/AYM kararlarının resmî portallardan doğrulanmış kopyalarını sunar. Türk "
    "hukuku sorusunda önce `search` ile kaynak bul, `fetch` ile metnini oku; kanun maddesi için `madde_metni` kullan. Cevabında "
    "bir karar künyesi ya da madde numarası anacaksan önce `atif_dogrula` ile denetle; bulunamayan atfı kullanma. Kaynakta "
    "yazmayan hukuki sonucu kaynak gösterme."
)

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "search",
        "title": "İçtihat ve mevzuat ara",
        "description": "Doğrulanmış Türk mevzuatı ve yargı kararlarında sözcük araması. Sonuçlar kimlik, künye ve resmî bağlantı "
                       "içerir; metni okumak için `fetch` kullanın.",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Arama ifadesi, ör. \"ihbar tazminatı bildirim süresi\""},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8}},
            "required": ["query"], "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "fetch",
        "title": "Kaynak metnini getir",
        "description": "`search` sonucundaki kimlikle doğrulanmış kaynağın tam metnini ve künyesini getirir.",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string", "description": "Kaynak kimliği (UUID)"}},
                        "required": ["id"], "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "madde_metni",
        "title": "Kanun maddesi metni",
        "description": "Kanun numarası ve madde numarasıyla güncel, resmî kaynakla doğrulanmış madde metnini getirir "
                       "(ör. kanun_no=4857, madde_no=17).",
        "inputSchema": {"type": "object", "properties": {
            "kanun_no": {"type": "string", "description": "Kanun numarası, ör. 4857"},
            "madde_no": {"type": "string", "description": "Madde numarası, ör. 17 ya da 25"}},
            "required": ["kanun_no", "madde_no"], "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "atif_dogrula",
        "title": "Karar atfını doğrula",
        "description": "Bir karar künyesinin (ör. \"Yargıtay 9. Hukuk Dairesi 2023/9430 E., 2024/123 K.\") doğrulanmış "
                       "korpusta bulunup bulunmadığını denetler ve bulunursa karar metninin başını döndürür. Bulunamayan "
                       "künyeyi cevapta kullanmayın.",
        "inputSchema": {"type": "object", "properties": {
            "atif": {"type": "string", "description": "Karar künyesi; esas numarası (2023/9430 E.) zorunlu"}},
            "required": ["atif"], "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]

_SOURCE_SQL = f"""
SELECT ls.id, ls.title, ls.source_url, ls.source_type,
       d.court_name, d.chamber, d.docket_no, d.decision_no, d.decision_date,
       l.law_name, l.law_no, l.article_no,
       (SELECT string_agg(c.content, E'\\n' ORDER BY c.chunk_index) FROM legal_chunks c WHERE c.legal_source_id = ls.id) AS text
FROM legal_sources ls
LEFT JOIN court_decision_details d ON d.legal_source_id = ls.id
LEFT JOIN legislation_details l ON l.legal_source_id = ls.id
WHERE ls.deleted_at IS NULL AND {_VERIFIED_SOURCE_FILTER} AND %s
"""


class _ToolError(ValueError):
    """A problem with the caller's arguments; reported to the assistant as a tool error, not a protocol error."""


def _reference(row: dict) -> str:
    if row.get("court_name"):
        parts = [row["court_name"], row.get("chamber") or ""]
        if row.get("docket_no"):
            parts.append(f"E. {row['docket_no']}")
        if row.get("decision_no"):
            parts.append(f"K. {row['decision_no']}")
        if row.get("decision_date"):
            parts.append(f"T. {row['decision_date']:%d.%m.%Y}")
        return ", ".join(p for p in parts if p)
    if row.get("law_name"):
        return f"{row['law_name']} ({row.get('law_no') or '-'}) m. {row.get('article_no') or '-'}"
    return row.get("title") or ""


def _source(row: dict, *, limit: int = _MAX_TEXT_CHARS) -> dict:
    text = row.get("text") or ""
    return {"id": str(row["id"]), "title": _reference(row), "url": row.get("source_url"),
            "text": text[:limit], "truncated": len(text) > limit,
            "metadata": {"tur": row.get("source_type"), "dogrulanmis_resmi_kaynak": True}}


def _query(where: str, params: tuple, *, limit: int = 5) -> list[dict]:
    with database_connection() as connection:
        connection.execute("SET LOCAL statement_timeout = '15s'")
        return connection.execute(_SOURCE_SQL.replace("%s", where, 1) + f" LIMIT {int(limit)}", params).fetchall()


def _search(arguments: dict) -> dict:
    query = " ".join(str(arguments.get("query") or "").split())
    if not 2 <= len(query) <= 300:
        raise _ToolError("query 2-300 karakter olmalı")
    limit = min(max(int(arguments.get("limit") or 8), 1), 20)
    found = search_legal_sources(q=query, limit=limit, offset=0, as_of=None)
    results = [{"id": str(hit.id), "title": _reference(hit.model_dump()) or hit.title, "url": hit.source_url}
               for hit in found.results]
    return {"results": results}


def _fetch(arguments: dict) -> dict:
    try:
        source_id = UUID(str(arguments.get("id")))
    except ValueError as exc:
        raise _ToolError("id geçerli bir kaynak kimliği değil") from exc
    rows = _query("ls.id = %s", (source_id,), limit=1)
    if not rows:
        raise _ToolError("Bu kimlikle doğrulanmış bir kaynak yok")
    return _source(rows[0])


def _article(arguments: dict) -> dict:
    law_no = re.sub(r"\D", "", str(arguments.get("kanun_no") or ""))
    article_no = canonical_article(str(arguments.get("madde_no") or "")).lower()
    if not law_no or not article_no:
        raise _ToolError("kanun_no ve madde_no gerekli")
    if not re.fullmatch(r"(?:ek geçici|geçici|ek)?\s*\d+(?:/[a-zçğıöşü])?", article_no):
        raise _ToolError("madde_no geçerli bir madde numarası değil")
    rows = _query("ls.source_type = 'legislation' AND ls.is_current AND l.law_no = %s AND lower(l.article_no) = %s",
                  (law_no, article_no), limit=1)
    if not rows:
        return {"found": False, "message": f"{law_no} sayılı Kanunun {article_no}. maddesi doğrulanmış kaynaklarımızda yok; "
                                           "madde numarasını kontrol edin. Bu madde hakkında hukuki iddiada bulunmayın."}
    return {"found": True, **_source(rows[0])}


_DOCKET = re.compile(r"(\d{4})\s*/\s*(\d{1,6})\s*(?:E\b|E\.|esas)", re.IGNORECASE)
_DECISION = re.compile(r"(\d{4})\s*/\s*(\d{1,6})\s*(?:K\b|K\.|karar)", re.IGNORECASE)
_CHAMBER = re.compile(r"(\d{1,2})\s*\.?\s*(hukuk|ceza|h\.?\s*d|c\.?\s*d|daire)", re.IGNORECASE)
_COURTS = ("yargıtay", "danıştay", "anayasa mahkemesi")


def _verify(arguments: dict) -> dict:
    citation = " ".join(str(arguments.get("atif") or "").split())[:300]
    docket = _DOCKET.search(citation)
    if not docket:
        raise _ToolError("Künyede esas numarası bulunamadı (ör. 2023/9430 E.)")
    decision = _DECISION.search(citation)
    rows = _query("ls.source_type = 'court_decision' AND d.is_current AND d.docket_no = %s"
                  + (" AND d.decision_no = %s" if decision else ""),
                  (f"{docket[1]}/{docket[2]}", *((f"{decision[1]}/{decision[2]}",) if decision else ())), limit=20)
    lowered = citation.replace("İ", "i").lower()
    court = next((name for name in _COURTS if name in lowered), None)
    chamber = _CHAMBER.search(citation)
    kind = None if not chamber else ("ceza" if chamber[2].lower().startswith("c") else
                                     "hukuk" if chamber[2].lower().startswith("h") else None)

    def matches(row: dict) -> bool:
        name = (row.get("court_name") or "").replace("İ", "i").lower()
        room = (row.get("chamber") or "").replace("İ", "i").lower()
        return ((court is None or court in name)
                and (chamber is None or room.startswith(f"{chamber[1]}."))
                and (kind is None or kind in room))

    exact = [row for row in rows if matches(row)]
    if not exact:
        others = [_reference(row) for row in rows[:5]]
        return {"verified": False, "message": "Bu künyeyle eşleşen doğrulanmış bir karar bulunamadı; cevapta kullanmayın.",
                "ayni_esas_numarali_diger_kararlar": others}
    if len(exact) > 1:
        return {"verified": False, "message": "Künye birden çok kararla eşleşiyor; mahkeme, daire ve karar numarasını ekleyin.",
                "adaylar": [_reference(row) for row in exact[:5]]}
    return {"verified": True, **_source(exact[0], limit=3000)}


_HANDLERS = {"search": _search, "fetch": _fetch, "madde_metni": _article, "atif_dogrula": _verify}


def _result(request_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _handle(message: Any, user_id: UUID) -> dict | None:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return _error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid Request")
    request_id, method = message.get("id"), message["method"]
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if "id" not in message:  # a notification (e.g. notifications/initialized) gets no response
        return None
    if method == "initialize":
        return _result(request_id, {"protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
                                    "capabilities": {"tools": {"listChanged": False}},
                                    "serverInfo": {"name": "JurisAI", "version": "0.1.0"}, "instructions": _INSTRUCTIONS})
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": _TOOLS})
    if method == "tools/call":
        handler = _HANDLERS.get(params.get("name"))
        if handler is None:
            return _error(request_id, -32602, "Bilinmeyen araç")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        try:
            payload = handler(arguments)
            is_error = False
        except _ToolError as exc:
            payload, is_error = {"error": str(exc)}, True
        except psycopg.Error:
            logger.exception("MCP aracı veritabanı hatası (%s)", params.get("name"))
            payload, is_error = {"error": "Kaynak veritabanına şu an ulaşılamıyor; biraz sonra yeniden deneyin."}, True
        logging.getLogger("uvicorn.error").info("MCP tool=%s error=%s", params.get("name"), is_error)
        return _result(request_id, {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, default=str)}],
                                    "structuredContent": json.loads(json.dumps(payload, default=str)), "isError": is_error})
    return _error(request_id, -32601, "Method not found")


@router.post("/mcp")
async def mcp_endpoint(request: Request,
                       credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> Response:
    # The connector's own access token (api/mcp_oauth.py), never the app session: it reaches only these read-only tools.
    from starlette.concurrency import run_in_threadpool as _thread

    user_id = await _thread(mcp_user_id, request, credentials)
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(_error(None, -32700, "Parse error"), status_code=400)
    from starlette.concurrency import run_in_threadpool

    if isinstance(body, list):
        replies = [reply for reply in [await run_in_threadpool(_handle, item, user_id) for item in body[:20]] if reply]
        return JSONResponse(replies) if replies else Response(status_code=202)
    reply = await run_in_threadpool(_handle, body, user_id)
    return JSONResponse(reply) if reply is not None else Response(status_code=202)


@router.get("/mcp")
def mcp_stream_not_supported() -> Response:
    return Response(status_code=405, headers={"Allow": "POST"})
