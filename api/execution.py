"""İcra dosyaları: UYAP'tan gelen icra dairesi dosyalarının listesi ve makbuzlardan okunan tutarlar.

Ayrı bir tablo yoktur: icra dosyası, UYAP aktarımında oluşan dava kaydıdır (`office_cases`) ve mahkemesi/birimi bir icra
dairesidir. Burada yalnız kaydın üst verisi ve evrak türleri okunur; hiçbir hukuki sonuç üretilmez.

Tutarlar belgenin metninden OKUNUR, hesaplanmaz ya da tahmin edilmez. Makbuz biçimleri farklıdır; bir makbuzdan tek ve
belirsizlik bırakmayan bir tutar okunamıyorsa o makbuz toplama katılmaz ve bu açıkça sayılır ("5 makbuzdan 4'ü okundu").
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from api.auth.routes import current_user_id
from api.db import authenticated_database_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/office/execution", tags=["office"])

# --- Birim ve evrak türü tanıma --------------------------------------------------------------------------------------------

_TR = str.maketrans("İIıŞÇĞÖÜ", "iiişçğöü")


def fold(text: str | None) -> str:
    """Türkçe harf çiftlerini tek biçime indirip küçük harfe çevirir."""
    return " ".join((text or "").translate(_TR).lower().split())


# Aynı kuralın SQL karşılığı: büyük "İ/I" harfleri veritabanı yerelinden bağımsız olarak katlanır.
COURT_SQL = (
    "lower(translate(coalesce(c.court, ''), 'İIıŞÇĞÖÜ', 'iiişçğöü')) "
    "~ 'icra\\s+(dairesi|müdürlüğü|hukuk\\s+mahkemesi|ceza\\s+mahkemesi)'"
)


def execution_kind(court: str | None) -> str | None:
    """"takip": icra dairesi dosyası; "mahkeme": icra hukuk/ceza mahkemesi (şikayet, itiraz); icra değilse None."""
    value = fold(court)
    if re.search(r"icra\s+(dairesi|müdürlüğü)", value):
        return "takip"
    if re.search(r"icra\s+(hukuk|ceza)\s+mahkemesi", value):
        return "mahkeme"
    return None


# Sıra önemlidir: ilk eşleşen kazanır ("tahsil harcı makbuzu", "tahsilat makbuzu"ndan önce gelmelidir).
_DOC_RULES: tuple[tuple[str, str], ...] = (
    ("harc", r"tahsil\s+harc|harc\s+makbuz|vekalet\s+pulu|sayman\s+mutemet"),
    ("reddiyat", r"^reddiyat\s+makbuzu"),
    ("reddiyat_diger", r"reddiyat"),
    ("tahsilat", r"^tahsilat\s+makbuzu|haricen\s+tahsil"),
    ("masraf", r"masraf\s+makbuzu"),
    ("takip_talebi", r"takip\s+talebi"),
    ("odeme_emri", r"odeme\s+icra\s+emri|odeme\s+emri|icra\s+emri|bakiye\s+borc\s+muhtira"),
    ("itiraz", r"borca\s+itiraz|itiraz"),
    ("haciz", r"haciz|89/?\s*[123]"),
    ("teblig", r"teblig|mazbata|tebligat"),
    ("hesap", r"hesab\w*\s+rapor|hesap\s+rapor"),
    ("dayanak", r"takibin\s+dayanag|ilam"),
)
_DOC_LABELS = {
    "haciz": "Haciz", "tahsilat": "Tahsilat", "reddiyat": "Reddiyat", "masraf": "Masraf", "harc": "Harç",
    "teblig": "Tebligat", "takip_talebi": "Takip talebi", "odeme_emri": "Ödeme emri", "itiraz": "İtiraz",
    "hesap": "Dosya hesabı", "dayanak": "Takip dayanağı", "reddiyat_diger": "Reddiyat (fiş/dekont)", "diger": "Diğer",
}


def classify_document(doc_type: str | None) -> str:
    # Dosya adındaki ASCII temizleme artıkları ve aksanlar sonucu bozmasın.
    value = fold(doc_type).translate(str.maketrans("çğıöşü", "cgiosu"))
    for kind, pattern in _DOC_RULES:
        if re.search(pattern, value):
            return kind
    return "diger"


# --- Makbuzdan tutar okuma -------------------------------------------------------------------------------------------------

_AMOUNT = re.compile(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})\s*(?:TL|₺|TRY)\b", re.IGNORECASE)


def _to_decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def receipt_amount(text: str, kind: str) -> Decimal | None:
    """Makbuz metninden tek bir tutar; belirsizse None.

    Metindeki bütün TL tutarları aynı değerse o değer makbuz tutarıdır. Farklı tutarlar varsa (harç/faiz/vekalet ücreti
    kırılımı, brüt/net) hangisinin makbuz tutarı olduğu bilinemez; None. Reddiyat makbuzları bu yüzden toplanmaz: gerçek
    makbuzlarda 10 tutardan 2–7'si farklıdır (ölçüldü: 2026-10-06), onlar için bu işlev çağrılmaz.
    """
    if not text:
        return None
    values = {_to_decimal(f"{m.group(1)},{m.group(2)}") for m in _AMOUNT.finditer(text)}
    values.discard(None)
    return values.pop() if len(values) == 1 else None


# --- Liste -----------------------------------------------------------------------------------------------------------------

# Yalnız tutarı güvenle okunan makbuz türleri toplanır; reddiyat makbuzu yalnız sayılır.
_SUMMED = ("tahsilat", "masraf")

_FILES_SQL = f"""
SELECT c.id AS case_id, c.case_no, c.esas_no, c.court, c.status, c.title,
       d.id AS document_id, d.doc_type, d.doc_date,
       s.dosya_durumu, s.dosya_turu, s.taraf_rolu, s.acilis, s.complete AS sync_complete,
       s.missing_count AS sync_missing, s.checked_at AS sync_checked_at,
       dt.complete AS detail_complete, dt.fetched_at AS detail_fetched_at,
       (SELECT t -> 'pairs' FROM jsonb_array_elements(dt.tabs) AS t WHERE t ->> 'key' = 'hesap' LIMIT 1) AS account_pairs
FROM office_cases c
JOIN office_case_documents d ON d.case_id = c.id AND d.owner_id = c.owner_id AND d.deleted_at IS NULL
LEFT JOIN office_uyap_case_sync s ON s.case_id = c.id AND s.owner_id = c.owner_id
LEFT JOIN office_uyap_case_detail dt ON dt.case_id = c.id AND dt.owner_id = c.owner_id
WHERE c.owner_id = %(owner)s AND {COURT_SQL}
ORDER BY c.id
"""

_TEXT_SQL = """
SELECT od.id AS document_id, string_agg(chunk.content, E'\\n' ORDER BY chunk.chunk_index) AS text
FROM office_case_documents od
JOIN documents doc ON doc.office_case_document_id = od.id AND doc.status = 'ready'
JOIN document_chunks chunk ON chunk.document_id = doc.id
WHERE od.owner_id = %(owner)s AND od.deleted_at IS NULL AND od.id = ANY(%(ids)s)
GROUP BY od.id
"""


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _uyap_info(row: dict[str, Any]) -> dict[str, Any] | None:
    """UYAP'ın gösterdiği durum/tür/rol metni (yorumlanmaz) ve son doğrulama; kayıt yoksa None."""
    if row.get("sync_checked_at") is None:
        return None
    return {
        "durum": row.get("dosya_durumu"),
        "tur": row.get("dosya_turu"),
        "rol": row.get("taraf_rolu"),
        "acilis": row.get("acilis"),
        "complete": bool(row.get("sync_complete")),
        "missing": int(row.get("sync_missing") or 0),
        "checked_at": row["sync_checked_at"],
    }


def _detail_info(row: dict[str, Any]) -> dict[str, Any] | None:
    """UYAP'tan çekilmiş dosya bilgisinin özeti: tamamlık, çekilme zamanı ve UYAP'ın "Dosya Hesabı" alanları (UYAP'ın yazdığı metin;
    hiçbir tutar burada hesaplanmaz). Çekilmemişse None."""
    if row.get("detail_fetched_at") is None:
        return None
    pairs = row.get("account_pairs") or []
    account = [
        {"label": str(pair.get("label", ""))[:160], "value": str(pair.get("value", ""))[:200]}
        for pair in pairs if isinstance(pair, dict) and pair.get("label")
    ]
    return {"complete": bool(row.get("detail_complete")), "fetched_at": row["detail_fetched_at"], "account": account}


def build_files(rows: list[dict[str, Any]], texts: dict[UUID, str]) -> list[dict[str, Any]]:
    """Satırları dosya başına toplar. `texts`: makbuz evrakının kimliğinden metnine."""
    files: dict[UUID, dict[str, Any]] = {}
    for row in rows:
        case_id = row["case_id"]
        entry = files.get(case_id)
        if entry is None:
            entry = files[case_id] = {
                "case_id": case_id,
                "file_no": row["esas_no"] or row["case_no"],
                "court": " ".join((row["court"] or "").split()),
                "kind": execution_kind(row["court"]) or "takip",
                "documents": 0, "first_date": None, "last_date": None,
                # UYAP dosya listesindeki üst veri ve son eşitleme doğrulaması (yoksa None: hiç doğrulanmamış).
                "uyap": _uyap_info(row),
                # UYAP'tan çekilen dosya bilgisi (taraflar, safahat, dosya hesabı…): yoksa None.
                "detail": _detail_info(row),
                "counts": Counter(),
                "_receipts": {kind: {"count": 0, "read": 0, "total": Decimal(0)} for kind in _SUMMED},
            }
        entry["documents"] += 1
        stamp: date | None = row["doc_date"]
        if stamp:
            entry["first_date"] = min(entry["first_date"] or stamp, stamp)
            entry["last_date"] = max(entry["last_date"] or stamp, stamp)
        kind = classify_document(row["doc_type"])
        entry["counts"][kind] += 1
        if kind in _SUMMED:
            receipt = entry["_receipts"][kind]
            receipt["count"] += 1
            amount = receipt_amount(texts.get(row["document_id"], ""), kind)
            if amount is not None:
                receipt["read"] += 1
                receipt["total"] += amount
    result = []
    for entry in files.values():
        receipts = entry.pop("_receipts")
        entry["counts"] = {kind: entry["counts"][kind] for kind in _DOC_LABELS if entry["counts"].get(kind)}
        entry["receipts"] = {
            kind: {"count": data["count"], "read": data["read"], "total": _money(data["total"]) if data["read"] else None}
            for kind, data in receipts.items() if data["count"]
        }
        result.append(entry)
    result.sort(key=lambda item: (item["last_date"] or date.min, item["documents"]), reverse=True)
    return result


def summarize(files: list[dict[str, Any]]) -> dict[str, Any]:
    """Üst kartlar: dosya sayısı ve okunabilen makbuz toplamları (okunamayanlar sayıyla belirtilir)."""
    summary: dict[str, Any] = {
        "files": len(files),
        "documents": sum(item["documents"] for item in files),
        # UYAP'tan eksiksiz aktarıldığı doğrulanan / hiç doğrulanmamış dosya sayısı.
        "verified_complete": sum(1 for item in files if (item.get("uyap") or {}).get("complete")),
        "never_verified": sum(1 for item in files if item.get("uyap") is None),
    }
    for kind in _SUMMED:
        count = sum(item["receipts"].get(kind, {}).get("count", 0) for item in files)
        read = sum(item["receipts"].get(kind, {}).get("read", 0) for item in files)
        total = sum((Decimal(item["receipts"][kind]["total"]) for item in files if item["receipts"].get(kind, {}).get("total")), Decimal(0))
        summary[kind] = {"count": count, "read": read, "total": _money(total) if read else None}
    return summary


@router.get("/files")
def execution_files(user_id: Annotated[UUID, Depends(current_user_id)]) -> dict[str, Any]:
    """Oturum sahibinin icra dosyaları (icra daireleri ve icra mahkemeleri) ve makbuz özetleri."""
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            rows = connection.execute(_FILES_SQL, {"owner": user_id}).fetchall()
            ids = [row["document_id"] for row in rows if classify_document(row["doc_type"]) in _SUMMED]
            texts = {
                item["document_id"]: item["text"]
                for item in (connection.execute(_TEXT_SQL, {"owner": user_id, "ids": ids}).fetchall() if ids else [])
            }
    except psycopg.Error:
        logger.exception("İcra dosyaları okunamadı")
        raise HTTPException(status_code=503, detail="İcra dosyaları şu an yüklenemiyor") from None
    files = build_files(rows, texts)
    return {"files": files, "summary": summarize(files), "labels": _DOC_LABELS}
