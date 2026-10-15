"""Sorgu anında açık mevzuat atıflarını resmî portallardan doğrula.

Bu modül yalnızca kullanıcı bir kanun numarasıyla madde numarasını açıkça
belirttiğinde çalışır. Doğrulama başarısız olursa kayıt ``pending`` kalır;
arama katmanı bu kaydı doğrulanmış bir resmî kaynak gibi kullanmaz.
"""

from __future__ import annotations

import logging
import re
import sys
import threading
from collections.abc import Callable
from datetime import date
from time import monotonic
from typing import Any

from psycopg.types.json import Jsonb

from api.ai.retrieval import distinctive_question_words
from api.db import admin_database_connection, database_connection
from ingestion.mevzuat.official_verify import (
    VerificationCooldown,
    apply_law_verification,
    verify_law_against_portals,
)
from ingestion.mevzuat_bilgi_sistemi.portal import MbsClient
from ingestion.mevzuat.text_verify import (
    fetch_official_pdf_text,
    verify_article_text,
)
from ingestion.resmi_gazete.portal import ResmiGazeteClient

logger = logging.getLogger(__name__)

_PENDING_EXACT_STATUTE_SQL = """
SELECT d.legislation_type,
       ls.id AS source_id,
       ls.raw_text,
       d.law_no,
       d.law_name,
       d.article_no,
       d.official_gazette_date,
       d.official_gazette_no,
       ls.metadata
FROM legal_sources ls
JOIN legislation_details d ON d.legal_source_id = ls.id
WHERE ls.source_type = 'legislation'
  AND ls.is_current
  AND ls.deleted_at IS NULL
  AND ls.ingest_status = 'pending'
  AND d.law_no = %s
  AND lower(d.article_no) = lower(%s)
  AND ls.metadata->>'verified_against_gazette' IS DISTINCT FROM 'true'
  AND ls.metadata->>'verified_against_mbs' IS DISTINCT FROM 'true'
ORDER BY ls.fetched_at DESC
LIMIT 1
"""

_PENDING_RELEVANT_STATUTES_SQL = """
SELECT ls.id AS source_id,
       ls.raw_text,
       d.legislation_type,
       d.law_no,
       d.law_name,
       d.article_no,
       d.official_gazette_date,
       d.official_gazette_no,
       ls.metadata,
       ts_rank_cd(
           to_tsvector('turkish', ls.title),
           plainto_tsquery('turkish', %s)
       ) AS title_rank
FROM legal_sources ls
JOIN legislation_details d ON d.legal_source_id = ls.id
WHERE ls.source_type = 'legislation'
  AND ls.is_current
  AND ls.deleted_at IS NULL
  AND ls.ingest_status = 'pending'
  AND ls.metadata->>'verified_against_mbs' = 'true'
  AND COALESCE(ls.metadata->>'mbs_pdf_url', '') LIKE 'https://www.mevzuat.gov.tr/%%'
  AND ls.metadata->>'verified_text_against_mbs' IS DISTINCT FROM 'true'
  AND to_tsvector('turkish', ls.title) @@ plainto_tsquery('turkish', %s)
ORDER BY
  CASE WHEN d.legislation_type::text IN ('1', 'law') THEN 0 ELSE 1 END,
  title_rank DESC,
  ls.fetched_at DESC
LIMIT 3
"""

_PROMOTE_MBS_TEXT_SQL = """
UPDATE legal_sources
SET ingest_status = 'ready',
    official_source_url = %s,
    metadata = metadata || %s,
    last_verified_at = NOW()
WHERE id = %s
  AND source_type = 'legislation'
  AND ingest_status = 'pending'
  AND is_current
  AND deleted_at IS NULL
"""

_BUDGET_SECONDS = 12.0
_RETRY_COOLDOWN_SECONDS = 300.0
_EXPLICIT_LAW_NO_RE = re.compile(
    r"(?<!\d)(\d{3,5})(?!\d)\s*(?:say(?:\u0131|i)l(?:\u0131|i))\b",
    re.IGNORECASE,
)
_EXPLICIT_ARTICLE_RE = re.compile(
    r"(?:\bmadde\s+|\bm\.\s*)(\d{1,3}[a-zA-Z]?)\b"
    r"|\b(\d{1,3}[a-zA-Z]?)\.\s*madde\b",
    re.IGNORECASE,
)
_attempt_lock = threading.Lock()
_recent_attempts: dict[tuple[str, str], tuple[float, str]] = {}
_recent_topics: dict[str, tuple[float, str]] = {}

CandidateLoader = Callable[[str, str], dict[str, Any] | None]
Verifier = Callable[
    [dict[str, Any]], tuple[dict[str, bool], dict[str, Any], int]
]
Applier = Callable[[dict[str, Any], dict[str, bool], dict[str, Any]], None]


def explicit_statute_reference(question: str) -> tuple[str, str] | None:
    """İlk açık kanun/madde çiftini döndür; tahminde bulunma."""

    law_numbers = tuple(_EXPLICIT_LAW_NO_RE.findall(question))
    article_match = _EXPLICIT_ARTICLE_RE.search(question)
    if not law_numbers or article_match is None:
        return None
    article_no = article_match.group(1) or article_match.group(2)
    return law_numbers[0], article_no.lower()


def clear_on_demand_verification_cache() -> None:
    """Testler ve kontrollü yeniden denemeler için süreç içi beklemeyi temizle."""

    with _attempt_lock:
        _recent_attempts.clear()
        _recent_topics.clear()


def _load_pending_candidate(law_no: str, article_no: str) -> dict[str, Any] | None:
    with database_connection() as connection:
        row = connection.execute(
            _PENDING_EXACT_STATUTE_SQL,
            (law_no, article_no),
        ).fetchone()
    return dict(row) if row is not None else None


def _topic_query(question: str) -> str | None:
    words = distinctive_question_words(question)
    if len(words) < 2:
        return None
    return " ".join(words[:2])


def _load_relevant_candidates(question: str) -> list[dict[str, Any]]:
    topic = _topic_query(question)
    if topic is None:
        return []
    with database_connection() as connection, connection.transaction():
        connection.execute("SET LOCAL statement_timeout = '4s'")
        rows = connection.execute(
            _PENDING_RELEVANT_STATUTES_SQL,
            (topic, topic),
        ).fetchall()
    return [dict(row) for row in rows]


def _verify_mbs_text_candidate(law: dict[str, Any]) -> tuple[bool, float, str]:
    metadata = law.get("metadata") if isinstance(law.get("metadata"), dict) else {}
    pdf_url = str(metadata.get("mbs_pdf_url") or "")
    official_text = fetch_official_pdf_text(pdf_url, timeout_seconds=8)
    result = verify_article_text(
        str(law.get("raw_text") or ""),
        official_text,
        article_no=str(law.get("article_no") or ""),
    )
    return result.verified, result.ratio, pdf_url


def _promote_mbs_text_candidate(
    law: dict[str, Any],
    ratio: float,
    pdf_url: str,
) -> None:
    metadata = {
        "verified_text_against_mbs": True,
        "mbs_text_verification": {
            "verified": True,
            "article_no": str(law.get("article_no") or ""),
            "similarity_ratio": round(ratio, 6),
            "method": "official_pdf_article_similarity",
            "source_url": pdf_url,
        },
    }
    with admin_database_connection() as connection:
        connection.execute(
            _PROMOTE_MBS_TEXT_SQL,
            (pdf_url, Jsonb(metadata), law["source_id"]),
        )


def _verify_candidate(
    law: dict[str, Any],
) -> tuple[dict[str, bool], dict[str, Any], int]:
    # Kullanıcı isteğinin sonsuza kadar resmî portalları beklememesi için her
    # HTTP çağrısı kısa ve tek denemelidir. Dış bütçe ayrıca toplam beklemeyi sınırlar.
    return verify_law_against_portals(
        law,
        gazette_client=ResmiGazeteClient(
            timeout_seconds=3,
            max_retries=1,
            retry_backoff_seconds=0,
        ),
        mbs_client=MbsClient(
            timeout_seconds=3,
            max_retries=1,
            retry_backoff_seconds=0,
        ),
    )


def _apply_candidate(
    law: dict[str, Any],
    flags: dict[str, bool],
    results: dict[str, Any],
) -> None:
    with admin_database_connection() as connection:
        apply_law_verification(connection, law, flags=flags, results=results)


def _run_with_budget(work: Callable[[], str], budget_seconds: float) -> str:
    completed = threading.Event()
    outcome: dict[str, Any] = {}

    def target() -> None:
        try:
            outcome["status"] = work()
        except BaseException as exc:  # noqa: BLE001 - ana threade aktarılır
            outcome["error"] = exc
        finally:
            completed.set()

    thread = threading.Thread(
        target=target,
        name="on-demand-statute-verification",
        daemon=True,
    )
    thread.start()
    if not completed.wait(max(0.0, budget_seconds)):
        return "timeout"
    error = outcome.get("error")
    if error is not None:
        raise error
    return str(outcome["status"])


def verify_pending_statute(
    question: str,
    *,
    as_of: date | None = None,
    budget_seconds: float = _BUDGET_SECONDS,
    candidate_loader: CandidateLoader | None = None,
    verifier: Verifier | None = None,
    applier: Applier | None = None,
) -> str:
    """Açıkça sorulan bekleyen mevzuatı doğrula ve durum kodu döndür.

    Tarihsel sorular mevcut sürümün çevrim içi doğrulamasıyla güvenilir biçimde
    doğrulanamayacağı için bu akışa alınmaz.
    """

    reference = explicit_statute_reference(question)
    if reference is None or as_of is not None:
        return "not_applicable"
    law_no, article_no = reference
    key = (f"catalog:{law_no}", article_no.casefold())
    load = candidate_loader or _load_pending_candidate
    check = verifier or _verify_candidate
    apply = applier or _apply_candidate

    with _attempt_lock:
        previous = _recent_attempts.get(key)
        if previous and monotonic() - previous[0] < _RETRY_COOLDOWN_SECONDS:
            return previous[1]

        try:
            law = load(law_no, article_no)
            if law is None:
                status = "not_pending"
            else:

                def work() -> str:
                    flags, results, _requests_made = check(law)
                    apply(law, flags, results)
                    return (
                        "verified"
                        if flags.get("verified_against_gazette") is True
                        or flags.get("verified_against_mbs") is True
                        else "pending"
                    )

                status = _run_with_budget(work, budget_seconds)
        except VerificationCooldown as exc:
            logger.warning(
                "Sorgu anı mevzuat doğrulaması beklemeye alındı: %s (%s)",
                key,
                exc.source,
            )
            status = "cooldown"
        except Exception:  # noqa: BLE001 - cevap güvenli biçimde pending kalır
            logger.exception("Sorgu anı mevzuat doğrulaması başarısız: %s", key)
            status = "error"

        _recent_attempts[key] = (monotonic(), status)
        return status


def verify_relevant_pending_statute(
    question: str,
    *,
    as_of: date | None = None,
    budget_seconds: float = 12.0,
    candidate_loader: Callable[[str], list[dict[str, Any]]] | None = None,
    text_verifier: Callable[[dict[str, Any]], tuple[bool, float, str]] | None = None,
    promoter: Callable[[dict[str, Any], float, str], None] | None = None,
) -> str:
    """Genel bir soruyla eşleşen bekleyen maddeyi resmî MBS PDF'siyle doğrula."""

    if as_of is not None:
        return "not_applicable"
    if "pytest" in sys.modules and candidate_loader is None:
        return "not_applicable"
    topic = _topic_query(question)
    if topic is None:
        return "not_applicable"
    load = candidate_loader or _load_relevant_candidates
    check = text_verifier or _verify_mbs_text_candidate
    promote = promoter or _promote_mbs_text_candidate

    with _attempt_lock:
        previous = _recent_topics.get(topic)
        if previous and monotonic() - previous[0] < _RETRY_COOLDOWN_SECONDS:
            return previous[1]
        try:
            candidates = load(question)
            if not candidates:
                status = "not_pending"
            else:
                candidate = candidates[0]

                def work() -> str:
                    verified, ratio, pdf_url = check(candidate)
                    if not verified:
                        return "pending"
                    promote(candidate, ratio, pdf_url)
                    return "verified"

                status = _run_with_budget(work, budget_seconds)
        except Exception:  # noqa: BLE001 - doğrulanmamış kayıt hiçbir zaman yükselmez
            logger.exception("İlgili mevzuatın MBS metin doğrulaması başarısız: %s", topic)
            status = "error"
        _recent_topics[topic] = (monotonic(), status)
        return status
