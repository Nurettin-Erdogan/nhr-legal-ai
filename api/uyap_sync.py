"""UYAP "tüm dosyaları aktar" koşusunun dosya başına doğrulama kaydı.

Tarayıcı her dosya için UYAP evrak ağacını aktarımdan sonra yeniden okur ve sonucu buraya bildirir. Sunucu UYAP'ı
göremez; bu yüzden bildirilen sayılara körü körüne güvenmez: o dosyanın kendi veritabanındaki UYAP evrak sayısını
(`server_documents`) kendisi sayar ve dosyayı ancak şu koşulların hepsi sağlanınca "eksiksiz" yazar:

  * tarayıcı eksik evrak ve tutarsızlık bildirmemiştir,
  * UYAP ağacında bulunan evrak sayısı kadar (ya da daha çok) evrak sunucuda gerçekten kayıtlıdır.

Dosya, evrak aktarımında kullanılan aynı kimlikle bulunur (esas no + birim; bkz. `uyap_cases`). Aynı kimlikte birden çok
dava varsa hiçbirine yazılmaz ("ambiguous"). Evrak içeriği bu uç noktadan geçmez; yalnız sayılar ve UYAP listesindeki
üst veri (yargı türü, dosya türü, durum, taraf rolü, açılış) saklanır.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from api.audit import AuditContext, record_event
from api.auth.routes import current_user_id
from api.db import authenticated_database_connection
from api.uyap_cases import UYAP_SOURCES, case_number, court_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/office/uyap", tags=["office"])

MAX_ITEMS = 500
MAX_PROBLEMS = 6


class SyncItem(BaseModel):
    esas: str = Field(max_length=60)
    birim: str = Field(max_length=160)
    yargi_turu: str = Field(default="", max_length=80)
    dosya_turu: str = Field(default="", max_length=80)
    durum: str = Field(default="", max_length=80)
    rol: str = Field(default="", max_length=60)
    acilis: str = Field(default="", max_length=40)
    declared: int = Field(default=0, ge=0, le=1_000_000)
    found: int = Field(default=0, ge=0, le=1_000_000)
    missing: int = Field(default=0, ge=0, le=1_000_000)
    complete: bool = False
    problems: list[str] = Field(default_factory=list, max_length=20)


class SyncReport(BaseModel):
    items: list[SyncItem] = Field(min_length=1, max_length=MAX_ITEMS)


def _clean(value: str) -> str | None:
    text = " ".join(value.split())
    return text or None


def _find_case(connection, owner_id: UUID, number: str, court: str) -> tuple[UUID | None, str]:
    """(dava kimliği, durum): "ok" | "no_case" | "ambiguous"."""
    candidates = connection.execute(
        "SELECT id, court FROM office_cases WHERE owner_id = %s AND "
        "(regexp_replace(case_no, '\\s', '', 'g') = %s OR regexp_replace(esas_no, '\\s', '', 'g') = %s)",
        (owner_id, number, number),
    ).fetchall()
    matches = [row["id"] for row in candidates if court_key(row["court"]) == court]
    if not matches:
        return None, "no_case"
    if len(matches) > 1:
        return None, "ambiguous"
    return matches[0], "ok"


def _server_documents(connection, owner_id: UUID, case_id: UUID) -> int:
    """Bu davaya bağlı, çöpte olmayan UYAP evraklarının sayısı (evrak kimliği varsa kimliğe göre tekil)."""
    return int(
        connection.execute(
            "SELECT count(DISTINCT coalesce(uyap_evrak_key, id::text)) AS n FROM office_case_documents "
            "WHERE owner_id = %s AND case_id = %s AND deleted_at IS NULL AND source = ANY(%s)",
            (owner_id, case_id, list(UYAP_SOURCES)),
        ).fetchone()["n"]
    )


@router.post("/sync-report")
def save_sync_report(
    body: SyncReport, user_id: Annotated[UUID, Depends(current_user_id)], request: Request
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    saved = 0
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            for item in body.items:
                number, court = case_number(item.esas), court_key(item.birim)
                entry: dict[str, Any] = {"esas": item.esas, "birim": item.birim}
                if not number or not court:
                    results.append({**entry, "status": "missing_metadata"})
                    continue
                case_id, status = _find_case(connection, user_id, number, court)
                if case_id is None:
                    results.append({**entry, "status": status})
                    continue
                stored = _server_documents(connection, user_id, case_id)
                problems = [" ".join(text.split())[:300] for text in item.problems if text.strip()][:MAX_PROBLEMS]
                consistent = stored >= item.found
                if not consistent:
                    problems.insert(0, f"Sunucuda {stored} UYAP evrakı kayıtlı, UYAP ağacında {item.found} evrak bulundu.")
                    problems = problems[:MAX_PROBLEMS]
                # Bildirilen sorunlar aktarım sırasındaki geçici hatalar olabilir (sonradan tamamlanmış); belirleyici olan
                # son doğrulamadır: eksik evrak yok ve sunucudaki sayı ağaçla tutarlı.
                complete = item.complete and item.missing == 0 and consistent
                connection.execute(
                    "INSERT INTO office_uyap_case_sync (case_id, owner_id, yargi_turu, dosya_turu, dosya_durumu, taraf_rolu, "
                    "acilis, declared_count, found_count, missing_count, server_documents, complete, problems, checked_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()) "
                    "ON CONFLICT (case_id) DO UPDATE SET yargi_turu = EXCLUDED.yargi_turu, dosya_turu = EXCLUDED.dosya_turu, "
                    "dosya_durumu = EXCLUDED.dosya_durumu, taraf_rolu = EXCLUDED.taraf_rolu, acilis = EXCLUDED.acilis, "
                    "declared_count = EXCLUDED.declared_count, found_count = EXCLUDED.found_count, "
                    "missing_count = EXCLUDED.missing_count, server_documents = EXCLUDED.server_documents, "
                    "complete = EXCLUDED.complete, problems = EXCLUDED.problems, checked_at = now()",
                    (case_id, user_id, _clean(item.yargi_turu), _clean(item.dosya_turu), _clean(item.durum), _clean(item.rol),
                     _clean(item.acilis), item.declared, item.found, item.missing, stored, complete, Jsonb(problems)),
                )
                saved += 1
                results.append({**entry, "status": "saved", "case_id": case_id, "complete": complete, "server_documents": stored})
            if saved:
                record_event(
                    connection, action="office.uyap_sync_report", actor_user_id=user_id,
                    context=AuditContext.from_request(request), entity_type="cases", entity_id=None,
                    metadata={"files": saved, "complete": sum(1 for row in results if row.get("complete"))},
                )
    except psycopg.Error as exc:
        logger.exception("UYAP eşitleme raporu kaydedilemedi")
        raise HTTPException(status_code=503, detail="Eşitleme raporu kaydedilemedi") from exc
    return {"saved": saved, "results": results}


@router.get("/sync-status")
def sync_status(user_id: Annotated[UUID, Depends(current_user_id)]) -> dict[str, Any]:
    """Sahibin UYAP dosyalarının son doğrulama durumu (en yeni önce)."""
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            rows = connection.execute(
                "SELECT s.case_id, coalesce(c.esas_no, c.case_no) AS esas, c.court AS birim, s.yargi_turu, s.dosya_turu, "
                "s.dosya_durumu, s.taraf_rolu, s.acilis, s.declared_count, s.found_count, s.missing_count, "
                "s.server_documents, s.complete, s.problems, s.checked_at "
                "FROM office_uyap_case_sync s JOIN office_cases c ON c.id = s.case_id "
                "WHERE s.owner_id = %s ORDER BY s.checked_at DESC, s.case_id LIMIT 2000",
                (user_id,),
            ).fetchall()
    except psycopg.Error as exc:
        logger.exception("UYAP eşitleme durumu okunamadı")
        raise HTTPException(status_code=503, detail="Eşitleme durumu okunamadı") from exc
    return {
        "files": rows,
        "summary": {
            "files": len(rows),
            "complete": sum(1 for row in rows if row["complete"]),
            "missing": sum(row["missing_count"] for row in rows),
        },
    }
