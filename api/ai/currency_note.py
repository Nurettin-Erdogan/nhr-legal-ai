"""How current the cited legislation is: a statement the code makes from stored verification dates, never the model.

Measured 2026-10-30: "30 Ekim 2026 itibarıyla 4857 m. 18 ve 20'yi resmî kaynaklardan kontrol et; ulaşamıyorsan hangi tarihe kadar
doğrulayabildiğini açıkça belirt" got a correct, sourced summary of both articles but not a word about the date: the texts had last
been compared with mevzuat.gov.tr on 27 October and nothing carried that date to the answer. The note below is built only from
`legal_sources.last_verified_at` and the verification flags; it adds no legal claim and is shown apart from the proven answer text.
"""

import re
from datetime import date, datetime

from api.ai.rag import RAGContext
from api.ai.search_plan import normalize

_MONTHS = ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık")
_MONTH_NUMBERS = {normalize(name): number for number, name in enumerate(_MONTHS, start=1)}

# The user asks whether the text is the one in force today, or asks for a check against the official source.
_CURRENCY_ASKED = re.compile(
    r"yürürlük|güncel|itibar[ıi]y?la|son hal|hala geçerli|hâlâ geçerli|halen geçerli|değiş(?:ti|miş|tirildi|iklik)"
    r"|doğrula|kontrol et|teyit|resm[iî] (?:kaynak|metin|site)|mevzuat\.gov\.tr|resmi gazete")
_TEXT_DATE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(_MONTH_NUMBERS) + r")\s+(\d{4})\b")
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")

VERIFICATION_RECORDS_SQL = """
SELECT ls.id, ls.last_verified_at,
       ls.metadata->>'verified_against_mbs' = 'true' OR ls.metadata->>'verified_text_against_mbs' = 'true' AS mbs,
       ls.metadata->>'verified_against_gazette' = 'true' AS gazette
FROM legal_sources ls
WHERE ls.id = ANY(%(ids)s::uuid[]) AND ls.deleted_at IS NULL
"""


def asks_currency(question: str) -> bool:
    return bool(_CURRENCY_ASKED.search(normalize(question)))


def question_date(question: str) -> date | None:
    """The date the question names ("30 Ekim 2026", "30.10.2026"); None if none or invalid."""
    q = normalize(question)
    match = _TEXT_DATE.search(q)
    parts = (match[1], _MONTH_NUMBERS[match[2]], match[3]) if match else None
    if parts is None and (match := _NUMERIC_DATE.search(q)):
        parts = (match[1], match[2], match[3])
    if parts is None:
        return None
    try:
        return date(int(parts[2]), int(parts[1]), int(parts[0]))
    except ValueError:
        return None


def turkish_date(value: date) -> str:
    return f"{value.day} {_MONTHS[value.month - 1]} {value.year}"


def fetch_verification_records(source_ids) -> dict:
    """{source_id: row} for the given sources; read only, public corpus rows."""
    ids = [str(value) for value in dict.fromkeys(source_ids)]
    if not ids:
        return {}
    from api.db import database_connection
    with database_connection() as connection:
        rows = connection.execute(VERIFICATION_RECORDS_SQL, dict(ids=ids)).fetchall()
    return {str(row["id"]): row for row in rows}


RECHECK_SOURCES_SQL = """
SELECT ls.id, ls.raw_text, d.law_no, d.article_no
FROM legal_sources ls
JOIN legislation_details d ON d.legal_source_id = ls.id
WHERE ls.id = ANY(%(ids)s::uuid[]) AND ls.is_current AND ls.deleted_at IS NULL AND ls.source_type = 'legislation'
"""
_RECORD_RECHECK_SQL = """
UPDATE legal_sources SET last_verified_at = NOW(), metadata = metadata || %(proof)s
WHERE id = %(id)s AND is_current AND deleted_at IS NULL AND source_type = 'legislation'
"""
SAME, DIFFERENT, UNREACHABLE = "same", "different", "unreachable"


def recheck_official(source_ids, *, fetch_law=None, extract=None, max_laws: int = 2) -> dict[str, str]:
    """Compare the stored current text of each cited article with the official MBS text, now.

    Only law numbers leave the machine (the existing paced, pinned MBS client). A match refreshes ``last_verified_at``; a
    mismatch never changes the stored text (AGENTS.md: a differing current text is not replaced from a chat) and is reported.
    """
    import json

    from api.ai.official_research import extract_article, fetch_law_cached
    from api.db import admin_database_connection, database_connection
    from ingestion.mevzuat.text_verify import _comparison_key
    fetch_law, extract = fetch_law or fetch_law_cached, extract or extract_article
    ids = [str(value) for value in dict.fromkeys(source_ids)]
    if not ids:
        return {}
    with database_connection() as connection:
        rows = connection.execute(RECHECK_SOURCES_SQL, dict(ids=ids)).fetchall()
    statuses: dict[str, str] = {}
    documents: dict[str, object] = {}
    for row in rows:
        law, source = row["law_no"], str(row["id"])
        if not (law and row["article_no"] and str(law).isdigit()):
            continue
        if law not in documents:
            if len(documents) >= max_laws:
                continue
            try:
                documents[law] = fetch_law(law)
            except Exception:  # noqa: BLE001 - portal down, CAPTCHA, identity mismatch: all mean "not reached"
                documents[law] = None
        document = documents[law]
        if document is None:
            statuses[source] = UNREACHABLE
            continue
        try:
            body = extract(document[1], row["article_no"])
        except Exception:  # noqa: BLE001 - article absent/ambiguous in the official text: not a match
            statuses[source] = DIFFERENT
            continue
        statuses[source] = SAME if _comparison_key(body) == _comparison_key(row["raw_text"] or "") else DIFFERENT
    same = [source for source, status in statuses.items() if status == SAME]
    if same:
        checked = datetime.now().astimezone().isoformat()
        try:
            with admin_database_connection() as connection:
                connection.execute("SET LOCAL lock_timeout='2s'")
                for source in same:
                    law = next(r["law_no"] for r in rows if str(r["id"]) == source)
                    url = getattr(documents[law][0], "pdf_url", None)
                    proof = json.dumps({"mbs_recheck": {"checked_at": checked, "url": url, "method": "chat_recheck_comparison_key"}})
                    connection.execute(_RECORD_RECHECK_SQL, dict(id=source, proof=proof))
        except Exception:  # noqa: BLE001 - the comparison stands; only the stored date stays older
            pass
    return statuses


def _references(contexts: list[RAGContext]) -> str:
    by_law: dict[str, list[str]] = {}
    for context in contexts:
        law = f"{context.law_no} sayılı Kanun" if context.law_no else (context.law_name or context.title)
        article = f"m. {context.article_no}" if context.article_no else ""
        articles = by_law.setdefault(law, [])
        if article and article not in articles:
            articles.append(article)
    return "; ".join(f"{law} {', '.join(articles)}".strip() for law, articles in by_law.items())


def verification_note(question: str, as_of: date | None, contexts, records: dict, today: date,
                      live: dict | None = None) -> str | None:
    """The currency statement for the cited legislation, or None when the question does not ask about it.

    Historical questions (``as_of`` before today) are answered from the version in force then; this note is about today's text.
    ``live`` holds today's comparison with the official text (see `recheck_official`): a match counts as verified today.
    """
    live = live or {}
    if as_of is not None and as_of < today:
        return None
    if as_of is None and not asks_currency(question):
        return None
    legislation = list({c.source_id: c for c in contexts if c.source_type == "legislation"}.values())
    if not legislation:
        return None
    references = _references(legislation)
    target = as_of or question_date(question) or today
    dated = []
    for context in legislation:
        row = records.get(str(context.source_id)) or {}
        if live.get(str(context.source_id)) == SAME:
            row = {**row, "last_verified_at": today, "mbs": True}
        verified = row.get("last_verified_at")
        if isinstance(verified, datetime):
            verified = verified.date()
        if isinstance(verified, date):
            dated.append((verified, bool(row.get("mbs")), bool(row.get("gazette"))))
    different = [c for c in legislation if live.get(str(c.source_id)) == DIFFERENT]
    unreachable = [c for c in legislation if live.get(str(c.source_id)) == UNREACHABLE]
    live_sentences = ""
    if different:
        live_sentences += (f" Bugün yapılan karşılaştırmada {_references(different)} için kayıtlı metin Mevzuat Bilgi Sistemi'ndeki "
                           "metinle eşleşmedi; kayıt değiştirilmedi, maddenin değişmiş olabileceğini resmî kaynaktan kontrol edin.")
    if unreachable:
        live_sentences += (f" Bugün Mevzuat Bilgi Sistemi'ne ulaşılamadığı için {_references(unreachable)} yeniden "
                           "karşılaştırılamadı.")
    if len(dated) < len(legislation):
        return (f"Doğrulama bilgisi: Atıf yapılan mevzuat metinlerinden ({references}) en az birinin resmî kaynakla son "
                f"karşılaştırma tarihi kayıtlarda yok; bu metinlerin {turkish_date(target)} itibarıyla güncel olduğu "
                "doğrulanamadı." + live_sentences)
    oldest, newest = min(d for d, _, _ in dated), max(d for d, _, _ in dated)
    mbs, gazette = any(m for _, m, _ in dated), any(g for _, _, g in dated)
    portal = ("Mevzuat Bilgi Sistemi (mevzuat.gov.tr) ve Resmî Gazete" if mbs and gazette
              else "Mevzuat Bilgi Sistemi (mevzuat.gov.tr)" if mbs else "Resmî Gazete" if gazette else "resmî kaynak")
    when = (f"en son {turkish_date(oldest)} tarihinde" if oldest == newest
            else f"{turkish_date(oldest)} ile {turkish_date(newest)} tarihleri arasında")
    note = f"Doğrulama bilgisi: Atıf yapılan mevzuat metinleri ({references}) {portal} ile {when} karşılaştırıldı."
    if oldest < target:
        note += (f" {turkish_date(oldest)} sonrasında yapılmış bir değişiklik bu karşılaştırmaya yansımamış olabilir; "
                 f"metinlerin {turkish_date(target)} itibarıyla güncelliği bu tarihten sonrası için doğrulanmadı.")
    return note + live_sentences
