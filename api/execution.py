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
from pydantic import BaseModel, Field

from api.auth.routes import current_user_id
from api.db import authenticated_database_connection
from api.execution_ask import MAX_QUESTION, answer as answer_question
from api.execution_overview import build_overview, list_overview
from api.turkish_text import TR_FOLD as _TR, fold, fold_keep_length

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/office/execution", tags=["office"])

# --- Birim ve evrak türü tanıma --------------------------------------------------------------------------------------------

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


def receipt_amounts(text: str) -> list[str]:
    """Makbuz metninde geçen farklı TL tutarları, metindeki yazılışlarıyla ve ilk geçiş sırasıyla (toplanmaz, seçilmez)."""
    seen: dict[Decimal, str] = {}
    for match in _AMOUNT.finditer(text or ""):
        value = _to_decimal(f"{match.group(1)},{match.group(2)}")
        if value is not None and value not in seen:
            seen[value] = f"{match.group(1)},{match.group(2)} TL"
    return list(seen.values())


# --- Haciz ihbarnamesi cevapları -------------------------------------------------------------------------------------------
#
# UYAP'taki "89/1 Haciz İhbarnamesi Cevabı" evrakının kendisi yalnız KEP iletisi zarfıdır; bankanın yazısı o evrakın EKİNDE
# durur (gerçek veride 76 cevap evrakı, 168 ek; ölçüldü: 2026-10-09). Ek, UYAP yolundan tanınır:
#     "<dosya> / 89/1 Haciz İhbarnamesi Cevabı / 89/1 Haciz İhbarnamesi Cevabı 12/03/2025"
#
# Burada cevabın SONUCU söylenmez. Banka yazıları kalıp ve koşullu cümlelerle doludur: 168 ekin 146'sında "bloke / haciz
# şerhi / haciz işlendi" türü bir ifade geçiyor, oysa yalnız 24'ünde tutar var (ölçüldü: 2026-10-09); anahtar sözcükle
# "olumlu/olumsuz" demek güvenilir değildir. Bu yüzden yalnız metinde NE GEÇTİĞİ gösterilir (tutar, "bloke",
# "bulunmamaktadır" türü ifade), cümle aynen alıntılanır ve liste buna göre sıralanır; avukat içinde tutar geçen cevabı
# önce görür ve kendisi okur.

_REPLY_PARENT = re.compile(r"haciz\s+ihbarnamesi\s+cevab")
_PATH_DATE = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s*$")
def _folded_pattern(pattern: str) -> re.Pattern[str]:
    """Kalıp, aranan metinle aynı biçimde katlanır ("ı" → "i"); yoksa "bulunmadığı" katlanmış metinde hiç eşleşmez."""
    return re.compile(pattern.translate(_TR))


_NEGATIVE = _folded_pattern(
    r"bulunmamakta|bulunmadığı|bulunmamıştır|rastlan\w*mamış|mevcut değil|mevcut olmadığı|tespit edilememiş|"
    r"müşterimiz değil|(?:hesabı|kaydı|alacağı|bakiyesi) yoktur"
)
_BLOCK = _folded_pattern(r"\bbloke")
# Gönderen kurumun adı yazının başlığından okunur (en iyi çaba; bulunamazsa "okunamadı" denir). İki yazılış: "Türkiye X
# Bankası A.Ş." ve bitişik "Xbank T.A.Ş.". Yalın "Banka/Bankası/Bankamız" sözcüğü ("Banka Alacakları İcra Dairesi") ad değildir.
_COMPANY_SUFFIX = r"(?:\s+(?:T\.?\s?A\.?\s?Ş\.?|A\.?\s?Ş\.?|A\.?\s?O\.?))?"
_SENDER = re.compile(
    r"((?:[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü&.]*\s+){1,5}(?:BANKASI|Bankası)\b" + _COMPANY_SUFFIX + r"|"
    r"\b[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü]{1,14}(?:BANKA|banka|BANK|bank)\b" + _COMPANY_SUFFIX + r"|"
    r"\b[A-Z]{2,6}\s+(?:BANK|Bank)\b" + _COMPANY_SUFFIX + r")"
)
# Başlıktaki adın önüne yapışan kısa büyük harfli sözcükler (şube/evrak kodu: "DVK Türkiye Vakıflar Bankası") ada dahil değildir.
_SENDER_PREFIX_NOISE = re.compile(r"^(?:(?!T\.?C\.?\s)[A-ZÇĞİÖŞÜ]{1,5}\s+)+(?=[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü.]+\s+\S)")
_ABBREVIATION_END = re.compile(r"(?:\b[A-Za-zÇĞİÖŞÜçğıöşü]|\bNo|\bmd|\bSk|\bCad|\bMah|\bŞti|\bLtd|\bTic|\bSan|\bAv|\bDr|\d)\.$")
_QUOTE_LIMIT = 420
REPLY_GROUP_LABELS = {
    "amount": "Tutar geçiyor",
    "block": "“Bloke” ifadesi geçiyor",
    "negative": "“Bulunmamaktadır” türü ifade geçiyor",
    "unclear": "Belirleyici ifade bulunamadı",
}


def _clean_sender(name: str) -> str:
    value = " ".join(name.split())
    return value if re.match(r"^[A-Z]{2,6}\s+(?:BANK|Bank)\b", value) else _SENDER_PREFIX_NOISE.sub("", value)


def is_reply_attachment(doc_type: str | None, uyap_path: str | None) -> bool:
    """Evrak, bir haciz ihbarnamesi cevabının eki mi (89/1, 89/2, 89/3)."""
    if fold(doc_type) != "ek":
        return False
    parts = [part.strip() for part in (uyap_path or "").split(" / ")]
    return len(parts) >= 3 and bool(_REPLY_PARENT.search(fold(parts[-2])))


def path_date(uyap_path: str | None) -> date | None:
    """UYAP yolunun sonundaki evrak tarihi ("… Cevabı 12/03/2025")."""
    match = _PATH_DATE.search(uyap_path or "")
    if not match:
        return None
    try:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None


def _sentence_around(text: str, start: int, end: int) -> str:
    """Bulunan ifadeyi içeren cümle, özgün metinden aynen; çok uzunsa iki yandan kırpılıp "…" ile işaretlenir."""
    left = start
    while left > 0:
        cut = text.rfind(". ", 0, left)
        if cut < 0:
            left = 0
            break
        if not _ABBREVIATION_END.search(text[max(0, cut - 6):cut + 1]):
            left = cut + 2
            break
        left = cut
    right = end
    while True:
        cut = text.find(". ", right)
        if cut < 0:
            right = len(text)
            break
        if not _ABBREVIATION_END.search(text[max(0, cut - 6):cut + 1]):
            right = cut + 1
            break
        right = cut + 2
    sentence = text[left:right].strip()
    if len(sentence) <= _QUOTE_LIMIT:
        return sentence
    half = _QUOTE_LIMIT // 2
    middle = (start + end) // 2
    begin, finish = max(left, middle - half), min(right, middle + half)
    return ("…" if begin > left else "") + text[begin:finish].strip() + ("…" if finish < right else "")


def reply_summary(text: str) -> dict[str, Any]:
    """Cevap yazısında geçenler: tutarlar (yazıldığı gibi), belirleyici ifadeyi taşıyan cümleler (aynen) ve sıralama grubu.

    Grup bir hukuki sonuç değildir; yalnız metinde ne geçtiğini söyler ("amount" > "block" > "negative" > "unclear").
    """
    original = " ".join((text or "").split())
    folded = fold_keep_length(original)
    amounts = receipt_amounts(original)
    quotes: list[str] = []
    spans = [m.span() for m in _AMOUNT.finditer(original)][:2]
    spans += [m.span() for m in _BLOCK.finditer(folded)][:1]
    spans += [m.span() for m in _NEGATIVE.finditer(folded)][:1]
    for start, end in spans:
        sentence = _sentence_around(original, start, end)
        if sentence and all(sentence not in other and other not in sentence for other in quotes):
            quotes.append(sentence)
    has_block, has_negative = bool(_BLOCK.search(folded)), bool(_NEGATIVE.search(folded))
    group = "amount" if amounts else "block" if has_block else "negative" if has_negative else "unclear"
    sender = _SENDER.search(original)
    return {
        "group": group,
        "amounts": amounts,
        "quotes": quotes[:3],
        "mentions_block": has_block,
        "mentions_negative": has_negative,
        "sender": _clean_sender(sender.group(1)) if sender else None,
    }


# --- Liste -----------------------------------------------------------------------------------------------------------------

# Yalnız tutarı güvenle okunan makbuz türleri toplanır; reddiyat makbuzu yalnız sayılır.
_SUMMED = ("tahsilat", "masraf")

_FILES_SQL = f"""
SELECT c.id AS case_id, c.case_no, c.esas_no, c.court, c.status, c.title,
       d.id AS document_id, d.doc_type, d.doc_date,
       s.dosya_durumu, s.dosya_turu, s.taraf_rolu, s.acilis, s.complete AS sync_complete,
       s.missing_count AS sync_missing, s.checked_at AS sync_checked_at, s.server_documents AS sync_documents,
       dt.complete AS detail_complete, dt.fetched_at AS detail_fetched_at,
       (SELECT t -> 'pairs' FROM jsonb_array_elements(dt.tabs) AS t WHERE t ->> 'key' = 'hesap' LIMIT 1) AS account_pairs
FROM office_cases c
LEFT JOIN office_case_documents d ON d.case_id = c.id AND d.owner_id = c.owner_id AND d.deleted_at IS NULL
LEFT JOIN office_uyap_case_sync s ON s.case_id = c.id AND s.owner_id = c.owner_id
LEFT JOIN office_uyap_case_detail dt ON dt.case_id = c.id AND dt.owner_id = c.owner_id
WHERE c.owner_id = %(owner)s AND {COURT_SQL}
  -- Evrakı olmayan dosya da listelenir, yeter ki UYAP'tan bilgisi gelmiş olsun (evraksız eski takip dosyası, evrakları
  -- henüz aktarılmamış dosya). Hiçbir UYAP kaydı ve evrakı olmayan kayıt listeye girmez.
  AND (d.id IS NOT NULL OR s.case_id IS NOT NULL OR dt.case_id IS NOT NULL)
ORDER BY c.id
"""

_OVERVIEW_SQL = """
SELECT case_id, tabs, complete, fetched_at
FROM office_uyap_case_detail
WHERE owner_id = %(owner)s AND case_id = ANY(%(ids)s)
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
        # O doğrulamada JurisAI'da kayıtlı evrak sayısı; sonradan evrak silindiyse `build_files` bunu fark eder.
        "recorded_documents": row.get("sync_documents"),
        "removed_since": 0,
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


def load_overviews(connection: Any, owner: UUID, case_ids: list[UUID], today: date) -> dict[UUID, dict[str, Any]]:
    """Dosya kimliğinden UYAP bilgisi özetine; UYAP bilgisi çekilmemiş dosya sözlükte yer almaz."""
    if not case_ids:
        return {}
    rows = connection.execute(_OVERVIEW_SQL, {"owner": owner, "ids": case_ids}).fetchall()
    return {
        row["case_id"]: build_overview(row["tabs"], complete=row["complete"], fetched_at=row["fetched_at"], today=today)
        for row in rows
    }


def build_files(
    rows: list[dict[str, Any]], texts: dict[UUID, str], overviews: dict[UUID, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Satırları dosya başına toplar. `texts`: makbuz evrakının kimliğinden metnine; `overviews`: UYAP bilgisi özetleri."""
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
                # Takip türü/durumu, taraf adları, son işlem ve son sonucu "VAR" yazan sorgular (UYAP bilgisinden); yoksa None.
                "overview": list_overview(overviews[case_id]) if overviews and case_id in overviews else None,
                "counts": Counter(),
                "_receipts": {kind: {"count": 0, "read": 0, "total": Decimal(0)} for kind in _SUMMED},
            }
        if row.get("document_id") is None:
            continue  # evrakı olmayan dosya: yalnız UYAP bilgisiyle listelenir
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
        uyap = entry["uyap"]
        if uyap and uyap["recorded_documents"] is not None and entry["documents"] < uyap["recorded_documents"]:
            # Doğrulamadan sonra evrak silinmiş: eski "eksiksiz" kaydı artık doğru değildir.
            uyap["removed_since"] = uyap["recorded_documents"] - entry["documents"]
            uyap["complete"] = False
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


# --- Tek dosyanın dökümü: makbuzlar ve haciz ihbarnamesi cevapları ---------------------------------------------------------

_RECEIPT_KINDS = ("tahsilat", "masraf", "reddiyat")
# Cevaplar bu sırayla gösterilir: içinde tutar geçen önce; "belirleyici ifade bulunamadı" olumsuz ifadeli olandan önce gelir
# (okunmadan geçilmesin diye).
REPLY_DISPLAY_ORDER = ("amount", "block", "unclear", "negative")

_DETAIL_SQL = f"""
SELECT c.id AS case_id, c.case_no, c.esas_no, c.court,
       d.id AS document_id, d.doc_type, d.doc_date, d.uyap_path, d.file_name, d.storage_path
FROM office_cases c
LEFT JOIN office_case_documents d ON d.case_id = c.id AND d.owner_id = c.owner_id AND d.deleted_at IS NULL
WHERE c.owner_id = %(owner)s AND c.id = %(case_id)s AND {COURT_SQL}
ORDER BY d.doc_date DESC NULLS LAST, d.created_at DESC
"""


def is_reply_envelope(doc_type: str | None) -> bool:
    """"89/1 Haciz İhbarnamesi Cevabı" evrakının kendisi (KEP zarfı)."""
    return bool(_REPLY_PARENT.search(fold(doc_type)))


def detail_text_ids(rows: list[dict[str, Any]]) -> list[UUID]:
    """Dökümde metni okunacak evraklar: makbuzlar ve haciz cevabı ekleri."""
    return [
        row["document_id"] for row in rows
        if row.get("document_id") is not None
        and (classify_document(row["doc_type"]) in _RECEIPT_KINDS or is_reply_attachment(row["doc_type"], row["uyap_path"]))
    ]


def _file_ref(row: dict[str, Any]) -> dict[str, Any]:
    """Belgeyi açmak için gerekenler; depolama anahtarı zaten sahibine özeldir ve indirme ucu sahipliği yeniden denetler."""
    return {"id": row["document_id"], "file_name": row.get("file_name"), "storage_path": row.get("storage_path")}


def _reply_signature(day: date | None, summary: dict[str, Any], text: str) -> tuple:
    """Aynı yazının iki kopyasını (KEP paketi + PDF) tek satırda birleştirmek için imza."""
    if summary["quotes"] or summary["amounts"]:
        return (day, summary["sender"], tuple(fold(quote) for quote in summary["quotes"]), tuple(summary["amounts"]))
    return (day, summary["sender"], re.sub(r"\W+", "", fold(text))[:600])


def build_detail(rows: list[dict[str, Any]], texts: dict[UUID, str]) -> dict[str, Any] | None:
    """Tek icra dosyasının dökümü; dosya bulunamadıysa None. Hiçbir tutar toplanmaz, hiçbir cevap yorumlanmaz."""
    if not rows:
        return None
    head = rows[0]
    receipts: list[dict[str, Any]] = []
    replies: dict[tuple, dict[str, Any]] = {}
    envelopes = attachments = unread = 0
    for row in rows:
        document_id = row.get("document_id")
        if document_id is None:
            continue
        kind = classify_document(row["doc_type"])
        text = texts.get(document_id, "")
        if kind in _RECEIPT_KINDS:
            amounts = receipt_amounts(text)
            receipts.append({
                "document": _file_ref(row),
                "kind": kind,
                "label": _DOC_LABELS[kind],
                "doc_type": row["doc_type"],
                "date": row["doc_date"],
                "readable": bool(text.strip()),
                # Tek tutar varsa makbuz tutarıdır; birden çok farklı tutar varsa hangisi olduğu bilinemez (liste gösterilir).
                "amount": amounts[0] if len(amounts) == 1 else None,
                "amounts": amounts,
            })
        elif is_reply_envelope(row["doc_type"]):
            envelopes += 1
        elif is_reply_attachment(row["doc_type"], row["uyap_path"]):
            attachments += 1
            day = path_date(row["uyap_path"]) or row["doc_date"]
            if not text.strip():
                unread += 1
            summary = reply_summary(text)
            signature = _reply_signature(day, summary, text) if text.strip() else (day, document_id)
            entry = replies.get(signature)
            if entry is None:
                replies[signature] = {
                    "date": day, "readable": bool(text.strip()), "documents": [_file_ref(row)],
                    "group": summary["group"], "sender": summary["sender"], "amounts": summary["amounts"],
                    "quotes": summary["quotes"],
                }
            else:
                entry["documents"].append(_file_ref(row))
    items = sorted(
        replies.values(),
        key=lambda item: (REPLY_DISPLAY_ORDER.index(item["group"]), -(item["date"] or date.min).toordinal()),
    )
    groups = Counter(item["group"] for item in items)
    return {
        "case_id": head["case_id"],
        "file_no": head["esas_no"] or head["case_no"],
        "court": " ".join((head["court"] or "").split()),
        "kind": execution_kind(head["court"]) or "takip",
        "receipts": receipts,
        "replies": {
            "envelopes": envelopes,
            "attachments": attachments,
            "unread": unread,
            "items": items,
            "groups": {group: groups[group] for group in REPLY_DISPLAY_ORDER if groups.get(group)},
        },
        "labels": {"receipts": {kind: _DOC_LABELS[kind] for kind in _RECEIPT_KINDS}, "reply_groups": REPLY_GROUP_LABELS},
    }


@router.get("/files/{case_id}")
def execution_file_detail(case_id: UUID, user_id: Annotated[UUID, Depends(current_user_id)]) -> dict[str, Any]:
    """Oturum sahibinin tek icra dosyasının dökümü: makbuzlar (tutarlar metinden okunur) ve haciz ihbarnamesi cevapları."""
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            rows = connection.execute(_DETAIL_SQL, {"owner": user_id, "case_id": case_id}).fetchall()
            ids = detail_text_ids(rows)
            texts = {
                item["document_id"]: item["text"]
                for item in (connection.execute(_TEXT_SQL, {"owner": user_id, "ids": ids}).fetchall() if ids else [])
            }
            overviews = load_overviews(connection, user_id, [case_id], date.today()) if rows else {}
    except psycopg.Error:
        logger.exception("İcra dosyası dökümü okunamadı")
        raise HTTPException(status_code=503, detail="İcra dosyası dökümü şu an yüklenemiyor") from None
    detail = build_detail(rows, texts)
    if detail is None:
        # Başkasının dosyası, icra dairesi olmayan dava ve olmayan kayıt aynı yanıtı alır.
        raise HTTPException(status_code=404, detail="İcra dosyası bulunamadı")
    # UYAP'tan çekilen dosya bilgisinden künye, taraflar, önemli işlemler ve sorgular; çekilmemişse None.
    detail["overview"] = overviews.get(case_id)
    return detail


_ASK_SQL = f"""
SELECT c.id AS case_id, coalesce(c.esas_no, c.case_no) AS file_no, c.court, s.dosya_durumu AS uyap_status
FROM office_cases c
LEFT JOIN office_uyap_case_sync s ON s.case_id = c.id AND s.owner_id = c.owner_id
WHERE c.owner_id = %(owner)s AND {COURT_SQL}
ORDER BY c.created_at DESC
"""


class AskBody(BaseModel):
    question: str = Field(min_length=2, max_length=MAX_QUESTION)


@router.post("/ask")
def execution_ask(body: AskBody, user_id: Annotated[UUID, Depends(current_user_id)]) -> dict[str, Any]:
    """Dosyalar arası soru: bilinen kalıplar süzgece çevrilir ve oturum sahibinin icra dosyalarına uygulanır (dil modeli yok).

    Soru metni kaydedilmez; yanıtta yalnız sahibin kendi dosyaları yer alır.
    """
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            cases = connection.execute(_ASK_SQL, {"owner": user_id}).fetchall()
            overviews = load_overviews(connection, user_id, [row["case_id"] for row in cases], date.today())
    except psycopg.Error:
        logger.exception("Dosyalar arası soru yanıtlanamadı")
        raise HTTPException(status_code=503, detail="Dosyalar şu an sorgulanamıyor") from None
    files = [
        {
            "case_id": row["case_id"], "file_no": row["file_no"], "court": " ".join((row["court"] or "").split()),
            "kind": execution_kind(row["court"]) or "takip", "uyap_status": row["uyap_status"],
            "overview": overviews.get(row["case_id"]),
        }
        for row in cases
    ]
    return answer_question(files, body.question)


@router.get("/files")
def execution_files(user_id: Annotated[UUID, Depends(current_user_id)]) -> dict[str, Any]:
    """Oturum sahibinin icra dosyaları (icra daireleri ve icra mahkemeleri) ve makbuz özetleri."""
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            rows = connection.execute(_FILES_SQL, {"owner": user_id}).fetchall()
            ids = [
                row["document_id"] for row in rows
                if row["document_id"] is not None and classify_document(row["doc_type"]) in _SUMMED
            ]
            texts = {
                item["document_id"]: item["text"]
                for item in (connection.execute(_TEXT_SQL, {"owner": user_id, "ids": ids}).fetchall() if ids else [])
            }
            overviews = load_overviews(connection, user_id, list({row["case_id"] for row in rows}), date.today())
    except psycopg.Error:
        logger.exception("İcra dosyaları okunamadı")
        raise HTTPException(status_code=503, detail="İcra dosyaları şu an yüklenemiyor") from None
    files = build_files(rows, texts, overviews)
    return {"files": files, "summary": summarize(files), "labels": _DOC_LABELS}
