"""Sorgu anında açık mevzuat atıflarını resmî portallardan doğrula.

Bu modül yalnızca kullanıcı bir kanun numarasıyla madde numarasını açıkça
belirttiğinde çalışır. Doğrulama başarısız olursa kayıt ``pending`` kalır;
arama katmanı bu kaydı doğrulanmış bir resmî kaynak gibi kullanmaz.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from datetime import date
from time import monotonic
from typing import Any

from api.db import admin_database_connection, database_connection
from ingestion.mevzuat.official_verify import (
    VerificationCooldown,
    apply_law_verification,
    verify_law_against_portals,
)
from ingestion.mevzuat_bilgi_sistemi.portal import MbsClient
from ingestion.resmi_gazete.portal import ResmiGazeteClient

logger = logging.getLogger(__name__)

_PENDING_EXACT_STATUTE_SQL = """
SELECT d.legislation_type,
       d.law_no,
       d.law_name,
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
  AND (ls.metadata->>'verified_against_gazette' IS DISTINCT FROM 'true'
       OR ls.metadata->>'verified_against_mbs' IS DISTINCT FROM 'true')
ORDER BY ls.fetched_at DESC
LIMIT 1
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


def _load_pending_candidate(law_no: str, article_no: str) -> dict[str, Any] | None:
    with database_connection() as connection:
        row = connection.execute(
            _PENDING_EXACT_STATUTE_SQL,
            (law_no, article_no),
        ).fetchone()
    return dict(row) if row is not None else None


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
    key = (law_no, article_no.casefold())
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
                        and flags.get("verified_against_mbs") is True
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
