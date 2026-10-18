"""UYAP dosya penceresinin evrak dışı bilgileri (dosya bilgileri, dosya hesabı, taraflar, safahat, tahsilat/reddiyat).

Tarayıcı eklentisi sekmeleri salt okunur okur ve sonucu buraya yollar. Değerler UYAP'ın yazdığı metindir; sunucu bunları yorumlamaz,
hesaplamaz, hukuki sonuç üretmez. Sunucu UYAP'ı göremez; bu yüzden istemcinin "eksiksiz" iddiasına körü körüne güvenmez: her tablonun
okunan satır sayısını UYAP'ın söylediği sayıyla kendisi karşılaştırır ve kaydı yalnız hepsi tutuyorsa `complete` yazar.

Dava, evrak aktarımıyla aynı kimlikle bulunur (esas no + dosya penceresinin yazdığı birim). Dosyanın hiç evrakı yoksa (UYAP "evrak
bilgisi bulunamadı" diyen eski icra dosyası) dava kaydı burada, evrak aktarımıyla aynı kuralla ("bekleyen", müvekkil ilişkisi yok)
açılır: dosya bilgileri evraksız dosyada da kaybolmaz. Aynı kimlikte birden çok dava varsa hiçbirine yazılmaz.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from api.audit import AuditContext, record_event
from api.auth.routes import current_user_id
from api.db import authenticated_database_connection
from api.uyap_cases import ensure_case

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/office/uyap", tags=["office"])

# Satır/sekme sayısı sınırsızdır; yalnız bozuk istemciye karşı hücre uzunluğu ve sütun sayısı sınırlanır.
MAX_CELL_CHARS = 4000
MAX_COLUMNS = 60
ALLOWED_TAB_KEYS = frozenset({"bilgiler", "hesap", "taraflar", "safahat", "tahsilat"})


class DetailPair(BaseModel):
    label: str = Field(max_length=160)
    value: str = Field(default="", max_length=MAX_CELL_CHARS)


class DetailTable(BaseModel):
    title: str = Field(default="", max_length=120)
    headers: list[str] = Field(default_factory=list, max_length=MAX_COLUMNS)
    rows: list[list[str]] = Field(default_factory=list)
    declared: int | None = Field(default=None, ge=0, le=100_000_000)
    complete: bool = False
    empty_evidence: Literal["uyap_static_reddiyat_detail"] | None = None

    @field_validator("headers")
    @classmethod
    def _short_headers(cls, value: list[str]) -> list[str]:
        return [text[:160] for text in value]

    @field_validator("rows")
    @classmethod
    def _bounded_rows(cls, value: list[list[str]]) -> list[list[str]]:
        # Satır sayısı sınırsızdır; yalnız sütun sayısı ve hücre uzunluğu sınırlanır (bozuk istemciye karşı).
        return [[cell[:MAX_CELL_CHARS] for cell in row[:MAX_COLUMNS]] for row in value]


class DetailTab(BaseModel):
    key: str = Field(max_length=40)
    label: str = Field(default="", max_length=80)
    pairs: list[DetailPair] = Field(default_factory=list, max_length=500)
    tables: list[DetailTable] = Field(default_factory=list, max_length=24)
    complete: bool = False


class CaseDetail(BaseModel):
    esas: str = Field(max_length=60)
    birim: str = Field(max_length=160)
    tabs: list[DetailTab] = Field(min_length=1, max_length=24)
    problems: list[str] = Field(default_factory=list, max_length=20)
    complete: bool = False


def _static_reddiyat_schema(headers: list[str]) -> bool:
    """UYAP'ın tahsilat satırıyla birlikte gizli ürettiği reddiyat detay tablosu. Canlıda iki düzen ölçüldü: 12 sütunlu
    ("… Ödenecek Tutar") ve Ceza dosyalarında 9 sütunlu ("Makbuz No, Durum, Reddiyat Tarihi, Reddiyat Nedeni, …, Net Ödenecek
    Miktar"; 2026-10-16). Eklentideki kuralla aynıdır (content.js `reddiyatSchema`)."""
    names = [header.casefold() for header in headers]
    return (8 <= len(names) <= 14 and names[0] == "makbuz no" and "reddiyat tarihi" in names
            and "reddiyat nedeni" in names and "ödenecek" in names[-1])


def verified_tabs(tabs: list[DetailTab]) -> tuple[list[dict[str, Any]], bool, list[str]]:
    """Sekmeleri saklanacak biçime çevirir ve eksiksizliği SUNUCUDA yeniden hesaplar: her tabloda okunan satır sayısı UYAP'ın
    söylediğine eşit olmalı (UYAP sayı söylemiyorsa kabul). Bilinmeyen sekme anahtarı atılır (yalnız okunan sekmeler saklanır)."""
    stored: list[dict[str, Any]] = []
    problems: list[str] = []
    for tab in tabs:
        if tab.key not in ALLOWED_TAB_KEYS:
            continue
        tables = []
        tab_complete = tab.complete and bool(tab.pairs or tab.tables)
        if tab.complete and not tab_complete:
            problems.append(f"{tab.label or tab.key}: içerik veya doğrulanmış boş sonuç yok.")
        for table in tab.tables:
            matches = table.declared is None or len(table.rows) == table.declared
            has_result = bool(table.rows) or table.declared == 0
            if table.empty_evidence:
                # Sadece ölçülmüş, statik reddiyat detay şeması; diğer belirsiz boş
                # tablolar bu istisna ile eksiksiz ilan edilemez.
                valid_evidence = (tab.key == "tahsilat" and table.title == "Reddiyat detayı"
                                  and not table.rows and table.declared == 0 and _static_reddiyat_schema(table.headers))
                has_result = has_result and valid_evidence
            if not matches:
                problems.append(f"{tab.label or tab.key}{' / ' + table.title if table.title else ''}: "
                                f"UYAP {table.declared} kayıt yazıyor, {len(table.rows)} kayıt alındı.")
            if not has_result:
                problems.append(f"{tab.label or tab.key}: boş tablonun sıfır kayıt olduğu doğrulanamadı.")
            tab_complete = tab_complete and matches and has_result and table.complete
            tables.append({"title": table.title, "headers": table.headers, "rows": table.rows,
                           "declared": table.declared, "complete": matches and has_result and table.complete,
                           **({"empty_evidence": table.empty_evidence} if table.empty_evidence else {})})
        stored.append({"key": tab.key, "label": tab.label, "pairs": [pair.model_dump() for pair in tab.pairs],
                       "tables": tables, "complete": tab_complete})
    return stored, bool(stored) and all(tab["complete"] for tab in stored), problems


@router.post("/case-detail")
def save_case_detail(
    body: CaseDetail, user_id: Annotated[UUID, Depends(current_user_id)], request: Request
) -> dict[str, Any]:
    tabs, complete, computed_problems = verified_tabs(body.tabs)
    if not tabs:
        raise HTTPException(status_code=422, detail="Kaydedilecek dosya bilgisi yok")
    problems = [" ".join(text.split())[:300] for text in [*body.problems, *computed_problems] if text.strip()][:12]
    audit = AuditContext.from_request(request)
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            case_id, status = ensure_case(
                connection, user_id, file_no=body.esas, birim=body.birim, audit=audit,
                note="UYAP dosya bilgisinden oluşturuldu (dosyada aktarılacak evrak yok ya da henüz aktarılmadı). "
                     "Dosya durumu ve müvekkil ilişkisi henüz doğrulanmadı.",
            )
            if case_id is None:
                return {"status": status}
            connection.execute(
                "INSERT INTO office_uyap_case_detail (case_id, owner_id, tabs, complete, problems, fetched_at) "
                "VALUES (%s, %s, %s, %s, %s, now()) "
                "ON CONFLICT (case_id) DO UPDATE SET tabs = EXCLUDED.tabs, complete = EXCLUDED.complete, "
                "problems = EXCLUDED.problems, fetched_at = now()",
                (case_id, user_id, Jsonb(tabs), complete and body.complete, Jsonb(problems)),
            )
            record_event(
                connection, action="office.uyap_case_detail", actor_user_id=user_id, context=audit,
                entity_type="cases", entity_id=case_id,
                metadata={"tabs": len(tabs), "complete": complete and body.complete, "case_created": status == "created"},
            )
    except psycopg.Error as exc:
        logger.exception("UYAP dosya bilgileri kaydedilemedi")
        raise HTTPException(status_code=503, detail="Dosya bilgileri kaydedilemedi") from exc
    return {"status": "saved", "case_id": case_id, "complete": complete and body.complete, "case_created": status == "created",
            "tabs": [tab["key"] for tab in tabs], "problems": problems}


@router.get("/case-detail/{case_id}")
def read_case_detail(case_id: UUID, user_id: Annotated[UUID, Depends(current_user_id)]) -> dict[str, Any]:
    """Davanın saklanan UYAP dosya bilgileri (yalnız sahibi; RLS). Kayıt yoksa 404."""
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            row = connection.execute(
                "SELECT case_id, tabs, complete, problems, fetched_at FROM office_uyap_case_detail "
                "WHERE case_id = %s AND owner_id = %s", (case_id, user_id),
            ).fetchone()
    except psycopg.Error as exc:
        logger.exception("UYAP dosya bilgileri okunamadı")
        raise HTTPException(status_code=503, detail="Dosya bilgileri okunamadı") from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Bu dava için UYAP dosya bilgisi çekilmemiş")
    return dict(row)
