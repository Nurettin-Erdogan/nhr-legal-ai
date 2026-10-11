"""UYAP dosya bilgilerinin asistana kaynak olması: dava başına bir "UYAP dosya bilgileri" belgesi.

Dava sohbeti ("Belgelerle Sor") yalnız evrak metinlerini arıyordu; "borçlu kim", "bakiye borç ne", "en son ne işlem yapıldı",
"araç sorgusu ne çıktı" gibi soruların cevabı ise evrakta değil UYAP'ın dosya penceresindedir (taraflar, dosya hesabı, safahat).
Burada o bilgiler, asistanın atıf yapabileceği gerçek bir belgeye yazılır: `documents` + `document_chunks` (kişisel alan:
`project_id IS NULL`, yalnız sahibine görünür; RLS). Böylece cevap, öteki belgelerle aynı yoldan geçer: model yalnız satır
seçer, kod seçilen satırın bu belgede aynen bulunduğunu doğrular, atıf sohbet geçmişine kaydedilir.

Belgenin her satırı "Etiket: değer" biçimindedir ve UYAP'ın yazdığından türetilir (`api/execution_overview.py`); hiçbir satır
hesap ya da hukuki sonuç içermez. Kimlik numaraları satırlara alınmaz. UYAP bilgisi yeniden çekilip içerik değişince yeni
belge yazılır, eskisi silinmez, yalnız kapatılır (`deleted_at`): eski cevapların atıfları o günkü metni göstermeye devam eder.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from api.ai.rag import RAGContext
from api.execution_overview import build_overview, clean_text, history

logger = logging.getLogger(__name__)

RECORD_TITLE = "UYAP dosya bilgileri"
# Bu belgeden gelen kaynakların `authority` değeri; cevabın bu kayıttan geldiği bununla tanınır.
RECORD_AUTHORITY = "UYAP dosya bilgisi"
# Belgenin hangi davaya ait olduğu `metadata` içinde durur (evrak değildir; `office_case_documents` satırı yoktur).
CASE_KEY = "uyap_record_case_id"
RECENT_HISTORY = 25
MAX_SERVICE_LINES = 40

_IDENTITY_LABELS = {"Türü": "Takip türü", "Yolu": "Takip yolu", "Şekli": "Takip şekli", "Dosya Durumu": "Dosya durumu"}


def _day(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else "tarihi yazılmamış"


def _span(first: date | None, last: date | None, count: int) -> str:
    if count <= 1 or first == last:
        return _day(last or first)
    return f"ilk {_day(first)}, son {_day(last)}"


def _inline(text: str) -> str:
    """Kaydı tek satırlık birim yapar: içindeki cümle sonları "; " olur, sondaki nokta atılır.

    Kanıt birimleri cümle sonunda bölünür; "Araç Sahiplikten Sorgulandı. Sorgu Sonucu: YOK" kaydı ikiye bölünürse cevapta
    yarım satır görünür. Sözcükler ve sıraları değişmez, yalnız noktalama.
    """
    from api.ai.source_support import _sentences

    return "; ".join(piece.rstrip(".").strip() for piece in _sentences(text) if piece.strip(". "))


def _field(label: str, value: str, fallback: str) -> str:
    """"Etiket: değer" satırı. Kanıt birimi sayılması için etiket kısa olmalıdır (iki nokta ilk 40 karakterde); UYAP'ın
    uzun adı etiket olamıyorsa kısa bir etiketin değerine taşınır, yoksa satır bir öncekine yapışırdı."""
    label = label.replace(":", " ").strip()
    return f"{label}: {value}" if len(label) <= 38 else f"{fallback}: {label} — {value}"


def record_sections(tabs: Any, overview: dict[str, Any]) -> list[tuple[str, str]]:
    """(bölüm adı, metin) listesi; her satır "Etiket: değer". Boş bölüm yazılmaz."""
    sections: list[tuple[str, list[str]]] = []

    activity = overview["activity"]
    lines = [_field(_IDENTITY_LABELS.get(pair["label"], pair["label"]), pair["value"], "Dosya bilgisi") for pair in overview["identity"]]
    if activity["entries"]:
        lines.append(f"Safahat kayıt sayısı: {activity['entries']}")
        lines.append(f"İlk işlem tarihi: {_day(activity['first_date'])}")
        lines.append(f"Son işlem tarihi: {_day(activity['last_date'])}")
        if activity["last"]:
            last = " — ".join(_inline(part) for part in (activity["last"]["type"], activity["last"]["text"]) if part)
            lines.append(f"Son işlem: en son yapılan işlem {_day(activity['last_date'])} tarihli {last}")
    sections.append(("Künye", lines))

    lines = []
    for party in overview["parties"]:
        kind = f" ({party['type']})" if party["type"] else ""
        lawyer = f"; vekili {party['lawyer']}" if party["lawyer"] else "; vekil kaydı yok"
        lines.append(_field(party["role"] or "Taraf", f"{party['name']}{kind}{lawyer}", "Taraf"))
    sections.append(("Taraflar", lines))

    lines = [_field(pair["label"], f"{pair['value']} (UYAP dosya hesabı)", "Dosya hesabı") for pair in overview["account"]]
    lines += [_field(pair["label"], f"{pair['value']} (UYAP tahsilat/reddiyat özeti)", "Tahsilat özeti") for pair in overview["collections"]]
    sections.append(("Dosya hesabı", lines))

    lines = []
    for person in overview["asset_queries"]["people"]:
        who = person["name"] or "adı kayıtta okunamayan kişi"
        role = f" ({person['role']})" if person["role"] else ""
        for query in person["queries"]:
            times = f"; toplam {query['count']} sorgu" if query["count"] > 1 else ""
            if query["result"] is None:
                outcome = f"sorgu yapılmış, kayıtta sonuç yazılmamış, son sorgu {_day(query['last_date'])}"
            else:
                result = "aynı gün hem VAR hem YOK" if query["result"] == "VAR/YOK" else query["result"]
                outcome = f"yapılan sorguda UYAP kaydındaki son sonuç {result}, tarihi {_day(query['result_date'])}"
            lines.append(_field(f"{query['label']} sorgusu", f"{who}{role} için {outcome}{times}", "Sorgu"))
    # Başlıkta "borçlu" geçmez: yoksa "Borçlu kim?" sorusu bu bölümün bütün satırlarını konu içi sayardı.
    sections.append(("Sorgular", lines))

    lines = []
    for item in overview["milestones"]:
        # Kısa tutulur (kaydın metni "Son safahat kayıtları" bölümündedir): kısa olgu satırı tek soru sözcüğüyle bulunur.
        count = f"{item['count']} kayıt, " if item["count"] > 1 else ""
        lines.append(_field(item["label"], f"{count}{_span(item['first_date'], item['last_date'], item['count'])}", "İşlem"))
    for item in overview["other_actions"][:20]:
        lines.append(_field(_inline(item["name"]), f"{item['count']} kayıt, son {_day(item['last_date'])}", "Diğer işlem"))
    sections.append(("İşlemler", lines))

    lines = []
    for item in overview["services"][:MAX_SERVICE_LINES]:
        sent = f"{_day(item['sent_date'])} tarihinde çıkarıldı" if item["sent_date"] else "çıkış kaydı yok"
        method = f" ({item['method']})" if item["method"] else ""
        if item["result"]:
            outcome = f"sonuç {item['result']}, {_day(item['result_date'])}"
        elif item["result_date"]:
            outcome = f"sonuç kaydı {_day(item['result_date'])} tarihinde girilmiş, sonucun ne olduğu yazmıyor"
        else:
            outcome = "sonuç kaydı yok"
        lines.append(f"Tebligat: {item['recipient'] or 'muhatabı kayıtta okunamayan'} için {sent}{method}; {outcome}")
    sections.append(("Tebligatlar", lines))

    dated = [entry for entry in history(tabs) if entry["date"] is not None]
    lines = [
        f"Safahat {_day(entry['date'])}: " + " — ".join(_inline(part) for part in (entry["type"], clean_text(entry["text"])) if part)
        for entry in reversed(dated[-RECENT_HISTORY:])
        if entry["type"] or entry["text"]
    ]
    sections.append(("Son safahat kayıtları", lines))

    return [(name, f"UYAP DOSYA BİLGİLERİ — {name.upper()}\n" + "\n".join(body)) for name, body in sections if body]


def _digest(sections: list[tuple[str, str]]) -> str:
    return hashlib.sha256("\n\n".join(text for _name, text in sections).encode("utf-8")).hexdigest()


def ensure_record_document(connection: psycopg.Connection, *, user_id: UUID, case_id: UUID) -> UUID | None:
    """Davanın UYAP bilgisi belgesini güncel tutar; belge kimliğini döndürür (UYAP bilgisi çekilmemişse None).

    Bağlantı oturum sahibinin bağlantısıdır (RLS): başkasının davasının UYAP bilgisi okunamaz, başkası adına belge yazılamaz.
    """
    row = connection.execute(
        "SELECT tabs, complete, fetched_at FROM office_uyap_case_detail WHERE owner_id = %s AND case_id = %s",
        (user_id, case_id),
    ).fetchone()
    current = connection.execute(
        "SELECT id, metadata ->> 'digest' AS digest FROM documents "
        f"WHERE uploaded_by = %s AND project_id IS NULL AND deleted_at IS NULL AND metadata ->> '{CASE_KEY}' = %s",
        (user_id, str(case_id)),
    ).fetchall()
    sections: list[tuple[str, str]] = []
    if row is not None:
        # Gün sayısı gibi her gün değişen değer belgeye yazılmaz; yoksa belge her gün yeniden üretilirdi.
        overview = build_overview(row["tabs"], complete=row["complete"], fetched_at=row["fetched_at"], today=date.today())
        sections = record_sections(row["tabs"], overview)
    digest = _digest(sections) if sections else None
    keep = next((item["id"] for item in current if digest is not None and item["digest"] == digest), None)
    for item in current:
        if item["id"] != keep:
            connection.execute("UPDATE documents SET deleted_at = now(), deleted_by = %s WHERE id = %s", (user_id, item["id"]))
    if keep is not None or digest is None:
        return keep
    fetched: datetime | None = row["fetched_at"]
    document_id = uuid4()
    name = f"{RECORD_TITLE} ({fetched.strftime('%d.%m.%Y')} tarihinde çekildi)" if fetched else RECORD_TITLE
    connection.execute(
        "INSERT INTO documents (id, project_id, uploaded_by, file_name, mime_type, status, metadata, processed_at) "
        "VALUES (%s, NULL, %s, %s, 'text/plain', 'ready', %s, now())",
        (document_id, user_id, name, Jsonb({
            CASE_KEY: str(case_id), "digest": digest, "source": "uyap_case_detail",
            "fetched_at": fetched.isoformat() if fetched else None, "complete": bool(row["complete"]),
        })),
    )
    for index, (title, text) in enumerate(sections):
        connection.execute(
            "INSERT INTO document_chunks (id, document_id, chunk_index, content, section_title, content_hash, metadata) "
            "VALUES (%s, %s, %s, %s, %s, %s, '{}'::jsonb)",
            (uuid4(), document_id, index, text, title, hashlib.sha256(text.encode("utf-8")).hexdigest()),
        )
    return document_id


_CONTEXT_SQL = f"""
SELECT chunk.id AS chunk_id, document.id AS source_id, 'document'::text AS source_type, document.file_name AS title,
       NULL::text AS source_url, %(authority)s::text AS authority, NULL::text AS court_name, NULL::text AS chamber,
       NULL::text AS docket_no, NULL::text AS decision_no, NULL::date AS decision_date, NULL::text AS law_name,
       NULL::text AS law_no, NULL::text AS article_no, chunk.section_title AS article_title, NULL::date AS version_date,
       NULL::date AS effective_from, NULL::date AS effective_to, NULL::text AS source_version, NULL::integer AS revision,
       'user_document'::text AS verification, chunk.content, 0::real AS rank, chunk.page_number
FROM documents AS document
JOIN document_chunks AS chunk ON chunk.document_id = document.id
WHERE document.uploaded_by = %(user)s AND document.project_id IS NULL AND document.deleted_at IS NULL
  AND document.status = 'ready' AND document.metadata ->> '{CASE_KEY}' = %(case)s
ORDER BY chunk.chunk_index
"""


def record_contexts(connection: psycopg.Connection, *, user_id: UUID, case_id: UUID, question: str) -> list[RAGContext]:
    """Davanın UYAP bilgisi belgesinden, soruyla ilgili satır taşıyan bölümler (en ilgili önce); belge yoksa boş liste.

    Belge burada güncellenir; hata olursa sohbet evraklarla sürer (UYAP bilgisi olmadan), cevap uydurulmaz.
    """
    from api.ai.passages import sentence_score
    from api.ai.relevance import document_hint, passage_relevant
    from api.ai.source_support import source_sentences

    try:
        with connection.transaction():
            if ensure_record_document(connection, user_id=user_id, case_id=case_id) is None:
                return []
            rows = connection.execute(_CONTEXT_SQL, {"user": user_id, "case": str(case_id), "authority": RECORD_AUTHORITY}).fetchall()
    except psycopg.Error:
        logger.exception("UYAP dosya bilgisi belgesi hazırlanamadı")
        return []
    scored: list[tuple[float, RAGContext]] = []
    for row in rows:
        context = RAGContext(**row)
        hint = document_hint(context)
        units = [
            unit for unit in source_sentences(context)
            if passage_relevant(question, unit, source_type="document", document_hint=hint)
        ]
        if units:
            scored.append((max(sentence_score(unit, question) for unit in units), context))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [context for _score, context in scored]
