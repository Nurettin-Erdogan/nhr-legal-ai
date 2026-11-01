"""UYAP sayfası tanınmadığında eklentinin ürettiği yapı özetini sahibin hesabına kaydeder (2026-10-18).

Amaç: Avukat Portalı gibi canlıda hiç görülmemiş sayfalar ilk gerçek kullanımda düzeltilebilsin. Özet içerik taşımaz
(eklenti maskeler); bu uç ayrıca savunma katmanıdır: 6+ rakamlık dizi (kimlik/telefon/dosya numarası), e-posta benzeri metin,
çok uzun metin ya da bilinmeyen biçim içeren rapor reddedilir. Sahip başına en çok 50 kayıt, saatte en çok 20 kayıt.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Annotated, Any
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from api.audit import AuditContext, record_event
from api.auth.routes import current_user_id
from api.db import authenticated_database_connection

logger = logging.getLogger(__name__)

MAX_PER_OWNER = 50
MAX_PER_HOUR = 20
MAX_STRING = 200
_LEAK = re.compile(r"\d{6,}|[^\s@]+@[^\s@]+\.[a-z]{2,}", re.IGNORECASE)


class Diagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^[a-z_]{2,40}$")
    context: dict[str, Any] = Field(default_factory=dict)
    reports: list[dict[str, Any]] = Field(default_factory=list, max_length=8)


def _clean(value: Any, depth: int = 0) -> Any:
    """Yalnız sayı, mantıksal, kısa metin, liste ve sözlük; metin sızıntı kalıbı taşırsa reddeder."""
    if depth > 6:
        raise ValueError("rapor çok derin")
    if value is None or isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        if len(value) > MAX_STRING or _LEAK.search(value):
            raise ValueError("rapor içerik ya da kimlik benzeri metin taşıyor")
        return value
    if isinstance(value, list):
        return [_clean(item, depth + 1) for item in value[:60]]
    if isinstance(value, dict):
        return {str(key)[:60]: _clean(item, depth + 1) for key, item in list(value.items())[:80]}
    raise ValueError("bilinmeyen değer")


router = APIRouter(prefix="/api/office/uyap/diagnostics", tags=["office"])


@router.post("")
def save_diagnostic(body: Diagnostic, user_id: Annotated[UUID, Depends(current_user_id)], request: Request) -> dict[str, Any]:
    try:
        context = _clean(body.context)
        reports = _clean(body.reports)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Tanı raporu kabul edilmedi: {exc}") from exc
    if len(json.dumps(context, ensure_ascii=False).encode()) > 4096 or len(json.dumps(reports, ensure_ascii=False).encode()) > 65536:
        raise HTTPException(status_code=413, detail="Tanı raporu çok büyük")
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            recent = connection.execute(
                "SELECT count(*) AS n FROM office_uyap_diagnostics WHERE owner_id = %s AND created_at > now() - interval '1 hour'",
                (user_id,),
            ).fetchone()["n"]
            if recent >= MAX_PER_HOUR:
                return {"ok": True, "saved": False, "reason": "rate_limited"}
            diagnostic_id = uuid4()
            connection.execute(
                "INSERT INTO office_uyap_diagnostics (id, owner_id, code, context, reports) VALUES (%s, %s, %s, %s, %s)",
                (diagnostic_id, user_id, body.code, Jsonb(context), Jsonb(reports)),
            )
            connection.execute(
                "DELETE FROM office_uyap_diagnostics WHERE owner_id = %s AND id NOT IN ("
                "SELECT id FROM office_uyap_diagnostics WHERE owner_id = %s ORDER BY created_at DESC LIMIT %s)",
                (user_id, user_id, MAX_PER_OWNER),
            )
            record_event(connection, action="office.uyap_diagnostic", actor_user_id=user_id,
                         context=AuditContext.from_request(request), entity_type="uyap_diagnostic", entity_id=diagnostic_id,
                         metadata={"code": body.code, "reports": len(reports)})
    except psycopg.Error as exc:
        logger.exception("UYAP tanı raporu kaydedilemedi")
        raise HTTPException(status_code=503, detail="Tanı raporu kaydedilemedi") from exc
    return {"ok": True, "saved": True, "id": str(diagnostic_id)}
