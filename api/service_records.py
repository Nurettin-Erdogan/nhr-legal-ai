"""Tebliğ kayıtları: davanın e-tebliğ mazbatalarından OKUNAN tarih damgaları ve tebligatın yapılmış sayıldığı gün.

Süre hesabının başlangıcı çoğu zaman tebliğ tarihidir; UYAP'tan gelen e-tebliğ mazbatası bu tarihi satır satır yazar:

    03/09/2026 10:14 Muhatap hesabına teslim edilmek üzere UETS tarafından teslim alındı.
    03/09/2026 10:15 Tebligat alıcı için ayrılmış tebligat alanına (hesabına) başarılı bir şekilde konuldu.
    04/09/2026 09:02 Tebligat, alıcısı tarafından açıldı.
    2026-09-08 Tebligat, alıcının hesabına iletilmesine müteakip mevzuat gereği belirlenen süre sonunda otomatik olarak …

Burada hiçbir süre BAŞLATILMAZ ve hiçbir hukuki sonuç söylenmez: yalnız mazbatada yazan damgalar okunur. Tebligatın yapılmış
sayıldığı gün iki yoldan gelir ve ikisi yan yana gösterilir: (1) mazbatanın kendi satırı, (2) hesaba ulaşma gününden
hesaplanan gün. Hesap kuralı (Tebligat Kanunu: "Elektronik yolla tebligat, muhatabın elektronik adresine ulaştığı tarihi
izleyen beşinci günün sonunda yapılmış sayılır") bu dosyada sabit bir iddia olarak durmaz: korpustaki resmî doğrulanmış
madde metninde aynen bulunuyorsa uygulanır, bulunmuyorsa (madde değişmiş, korpusta yok) hesap yapılmaz. Hangi tarihin
sürenin başlangıcı olacağına avukat karar verir (Süreler sekmesinde aday olarak sunulur).

Kâğıt mazbatalar taranmış belgedir; OCR metninden tarih güvenle okunamaz ve "okunamadı" diye sayılır (ölçüldü: 2026-10-09).
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from api import statute_hints
from api.auth.routes import current_user_id
from api.db import authenticated_database_connection, database_connection
from api.execution import _TEXT_SQL, _file_ref, _folded_pattern, classify_document
from api.turkish_text import fold_keep_length

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/office/cases", tags=["office"])

# "2026-09-03 10:15:07", "2026-09-08" ya da "03/09/2026 10:15", "03.09.2026".
_STAMP = re.compile(
    r"(?<!\d)(?:(?P<y1>\d{4})-(?P<m1>\d{2})-(?P<d1>\d{2})|(?P<d2>\d{2})[./](?P<m2>\d{2})[./](?P<y2>\d{4}))"
    r"(?:[ T](?P<h>\d{2}):(?P<min>\d{2})(?::(?P<s>\d{2}))?)?(?!\d)"
)
# Sıra önemli değildir; her damganın ardından gelen metin bu kalıplardan biriyle eşleşirse olay sayılır.
_EVENT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("received", _folded_pattern(r"uets tarafından teslim alındı")),
    ("delivered", _folded_pattern(r"\(hesabına\)[^.]{0,40}konuldu|tebligat alanına[^.]{0,60}konuldu")),
    ("opened", _folded_pattern(r"alıcısı tarafından açıldı")),
    ("deemed", _folded_pattern(r"mevzuat gereği belirlenen süre sonunda")),
)
EVENT_LABELS = {
    "received": "UETS teslim aldı",
    "delivered": "Muhatabın hesabına ulaştı",
    "opened": "Alıcı açtı",
    "deemed": "Mazbataya göre süre sonunda yapılmış sayıldı",
}
_EVENT_TEXT_LIMIT = 220
_ENVELOPE = re.compile(r"BU\s+ZARFTA\s+(?P<content>.{1,400}?)\s+VARDIR", re.DOTALL)

# Hesap kuralı: madde numarası ve aranacak cümle. Cümle korpustaki resmî metinde aynen yoksa hesap yapılmaz.
E_SERVICE_RULE = statute_hints.Hint("7201", "7", ("beşinci günün sonunda yapılmış sayılır",))
E_SERVICE_RULE_SENTENCE = (
    "Elektronik yolla tebligat, muhatabın elektronik adresine ulaştığı tarihi izleyen beşinci günün sonunda yapılmış sayılır."
)
E_SERVICE_DAYS = 5


def _stamp_value(match: re.Match[str]) -> tuple[date, str] | None:
    """Damganın tarihi ve yazılacak ISO biçimi (saat varsa saatle); olmayan tarih (31/02) atılır."""
    year = match.group("y1") or match.group("y2")
    month = match.group("m1") or match.group("m2")
    day = match.group("d1") or match.group("d2")
    try:
        if match.group("h") is not None:
            moment = datetime(int(year), int(month), int(day), int(match.group("h")), int(match.group("min")), int(match.group("s") or 0))
            return moment.date(), moment.isoformat(timespec="seconds")
        only = date(int(year), int(month), int(day))
        return only, only.isoformat()
    except ValueError:
        return None


def parse_service_events(text: str) -> list[dict[str, Any]]:
    """Mazbata metnindeki olay satırları: tür, damga ve satırın metni (aynen). Tanınmayan damgalar (evrak tarihleri) atlanır."""
    original = " ".join((text or "").split())
    folded = fold_keep_length(original)
    stamps = list(_STAMP.finditer(original))
    events: list[dict[str, Any]] = []
    for index, match in enumerate(stamps):
        value = _stamp_value(match)
        if value is None:
            continue
        end = stamps[index + 1].start() if index + 1 < len(stamps) else len(original)
        end = min(end, match.end() + _EVENT_TEXT_LIMIT)
        segment = folded[match.end():end]
        for kind, pattern in _EVENT_RULES:
            if pattern.search(segment):
                events.append({"kind": kind, "on": value[0], "at": value[1], "text": original[match.end():end].strip()})
                break
    return events


def served_documents(text: str) -> str | None:
    """Zarfın içindekiler, mazbatada yazdığı gibi ("BU ZARFTA … VARDIR" arası); yoksa None."""
    match = _ENVELOPE.search(" ".join((text or "").split()))
    return match.group("content").strip(" .,;") if match else None


def summarize_record(text: str, *, rule_verified: bool) -> dict[str, Any]:
    """Tek mazbatanın özeti: olaylar, hesaba ulaşma günü, mazbatanın yazdığı ve hesaplanan "yapılmış sayılma" günü."""
    events = parse_service_events(text)
    delivered = next((event["on"] for event in events if event["kind"] == "delivered"), None)
    stated = next((event["on"] for event in events if event["kind"] == "deemed"), None)
    computed = delivered + timedelta(days=E_SERVICE_DAYS) if delivered and rule_verified else None
    return {
        "electronic": bool(events),
        "served": served_documents(text),
        "events": [{"kind": e["kind"], "label": EVENT_LABELS[e["kind"]], "at": e["at"], "text": e["text"]} for e in events],
        "delivered_on": delivered,
        "stated_deemed_on": stated,
        "computed_deemed_on": computed,
        # İkisi de varsa ve tutuyorsa True; biri eksikse karşılaştırılamaz (None).
        "agrees": (stated == computed) if stated and computed else None,
    }


def build_service_records(rows: list[dict[str, Any]], texts: dict[UUID, str], *, rule: dict[str, Any] | None) -> dict[str, Any] | None:
    """Davanın tebliğ kayıtları; dava bulunamadıysa None. Tarih okunamayan tebliğ evrakı sayılır, uydurulmaz."""
    if not rows:
        return None
    records: list[dict[str, Any]] = []
    unreadable = 0
    for row in rows:
        document_id = row.get("document_id")
        if document_id is None or classify_document(row["doc_type"]) != "teblig":
            continue
        summary = summarize_record(texts.get(document_id, ""), rule_verified=rule is not None)
        if not summary["electronic"]:
            unreadable += 1
            continue
        records.append({"document": _file_ref(row), "doc_type": row["doc_type"], "date": row["doc_date"], **summary})
    records.sort(key=lambda item: (item["delivered_on"] or item["stated_deemed_on"] or date.min), reverse=True)
    return {
        "case_id": rows[0]["case_id"],
        "records": records,
        # Tebliğ evrakı olup da olay satırı okunamayanlar (kâğıt mazbata, zarf, metni olmayan belge).
        "unreadable": unreadable,
        "rule": None if rule is None else {**rule, "sentence": E_SERVICE_RULE_SENTENCE, "days": E_SERVICE_DAYS},
    }


_RECORDS_SQL = """
SELECT c.id AS case_id, d.id AS document_id, d.doc_type, d.doc_date, d.file_name, d.storage_path
FROM office_cases c
LEFT JOIN office_case_documents d ON d.case_id = c.id AND d.owner_id = c.owner_id AND d.deleted_at IS NULL
WHERE c.owner_id = %(owner)s AND c.id = %(case_id)s
ORDER BY d.doc_date DESC NULLS LAST, d.created_at DESC
"""


_ARTICLE_HEADING = re.compile(r"(?i)\bmadde\s+(\d+(?:/[a-zçğıöşü])?)\s*[–-]")


def article_label_for(article_text: str, sentence_part: str, fallback: str) -> str:
    """Cümlenin, madde metninde hangi "Madde N" başlığının altında durduğu.

    Korpusta 7201 m. 7 kaydı m. 7 ile m. 7/a'yı birlikte taşır (ölçüldü: 2026-10-09); kural m. 7/a'dadır. Atıf, kaydın madde
    numarasından değil metindeki en yakın önceki başlıktan okunur; başlık bulunamazsa kaydın numarası kullanılır.
    """
    flat = " ".join((article_text or "").split())
    at = flat.find(sentence_part)
    if at < 0:
        return fallback
    headings = [match for match in _ARTICLE_HEADING.finditer(flat) if match.start() < at]
    return headings[-1].group(1) if headings else fallback


def verified_e_service_rule() -> dict[str, Any] | None:
    """Kuralın dayandığı madde korpusta resmî doğrulanmış ve cümleyi taşıyorsa atıf bilgisi; değilse None (hesap yapılmaz)."""
    try:
        with database_connection() as connection:
            row = connection.execute(
                statute_hints._SQL, {"law_no": E_SERVICE_RULE.law_no, "article_no": E_SERVICE_RULE.article_no}
            ).fetchone()
    except psycopg.Error:
        logger.warning("E-tebligat kuralı korpustan doğrulanamadı", exc_info=True)
        return None
    if row is None or not statute_hints.text_matches(E_SERVICE_RULE, row["content"] or ""):
        return None
    label = article_label_for(row["content"], E_SERVICE_RULE.expect[0], row["article_no"])
    return {
        "reference": f"{' '.join(row['law_name'].split())} ({row['law_no']}) m. {label}",
        "source_url": row["source_url"],
        "source_id": str(row["id"]),
        "law_no": row["law_no"],
        "article_no": label,
        "verification": "official",
    }


@router.get("/{case_id}/service-records")
def case_service_records(case_id: UUID, user_id: Annotated[UUID, Depends(current_user_id)]) -> dict[str, Any]:
    """Oturum sahibinin davasındaki e-tebliğ mazbatalarından okunan tebliğ kayıtları (süre başlangıcı için aday tarihler)."""
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            rows = connection.execute(_RECORDS_SQL, {"owner": user_id, "case_id": case_id}).fetchall()
            ids = [row["document_id"] for row in rows if row["document_id"] is not None and classify_document(row["doc_type"]) == "teblig"]
            texts = {
                item["document_id"]: item["text"]
                for item in (connection.execute(_TEXT_SQL, {"owner": user_id, "ids": ids}).fetchall() if ids else [])
            }
    except psycopg.Error:
        logger.exception("Tebliğ kayıtları okunamadı")
        raise HTTPException(status_code=503, detail="Tebliğ kayıtları şu an yüklenemiyor") from None
    result = build_service_records(rows, texts, rule=verified_e_service_rule() if rows else None)
    if result is None:
        raise HTTPException(status_code=404, detail="Dava bulunamadı")
    return result
