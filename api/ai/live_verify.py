"""Kullanıcı sorduğunda getirilen tohum kaynakları resmî portaldan doğrular.

CAPTCHA aşılmaz; eşleşmeyen veya doğrulanamayan kaynak cevapta gösterilmez.
"""

from __future__ import annotations

import logging
import sys
import threading
from dataclasses import replace
from time import monotonic
from typing import Callable
from uuid import UUID

import psycopg

from api.ai.rag import RAGContext
from api.ai.trust import verified_contexts
from api.db import admin_database_connection, database_connection
from ingestion.seed_verify import (
    document_id_from_external_id,
    fetch_official_text,
    promote_verified_seed,
    seed_matches_official,
    source_kind_from_external_id,
    official_document_url,
    _nospace,
)
from ingestion.source_errors import is_rate_limited
from ingestion.yargitay.portal import CaptchaRequiredError

logger = logging.getLogger(__name__)

_PENDING_SQL = """
SELECT ls.id, ls.external_id, ls.raw_text
FROM legal_sources ls
WHERE ls.id = ANY(%s)
  AND ls.ingestion_method = 'bulk_seed'
  AND ls.ingest_status = 'pending'
  AND ls.is_current
  AND ls.deleted_at IS NULL
"""

_BUDGET_SECONDS = 12.0
_MAX_DOCS = 4


class _FetchTimeout(TimeoutError):
    """Portal isteği toplam doğrulama bütçesinde tamamlanmadı."""


def _fetch_with_deadline(
    fetcher: Callable[[str, str], str], kind: str, document_id: str, timeout: float
) -> str:
    """Portal isteğini en fazla `timeout` sn bekler.

    Bütçe eskiden yalnız belgeler arasında kontrol ediliyordu; tek bir istek portalın zaman aşımı
    ve geri çekilme beklemeleriyle 30 sn'yi bulabiliyordu. İstek burada ayrı bir iş parçacığında
    çalışır: süre dolarsa çağıran devam eder, iş parçacığı istemcinin kendi zaman aşımıyla
    sessizce biter (ingestion istemcisine dokunulmaz).
    """
    outcome: dict[str, object] = {}
    finished = threading.Event()

    def run() -> None:
        try:
            outcome["value"] = fetcher(kind, document_id)
        except BaseException as exc:  # noqa: BLE001 - çağıranın iş parçacığında yeniden fırlatılır
            outcome["error"] = exc
        finally:
            finished.set()

    threading.Thread(target=run, name="live-verify-fetch", daemon=True).start()
    if not finished.wait(timeout):
        raise _FetchTimeout(f"{kind}:{document_id}")
    if "error" in outcome:
        raise outcome["error"]  # type: ignore[misc]
    return outcome["value"]  # type: ignore[return-value]


def verify_third_party_contexts(
    contexts: list[RAGContext],
    *,
    fetcher=fetch_official_text,
    promoter=None,
    budget_seconds: float = _BUDGET_SECONDS,
) -> list[RAGContext]:
    """Resmî metinle eşleşenleri döndürür; hata/bütçe aşımında kapalı kalır."""
    if "pytest" in sys.modules and fetcher is fetch_official_text:
        return verified_contexts(contexts)
    pending_ids = [
        context.source_id
        for context in contexts
        if context.verification == "third_party"
    ]
    if not pending_ids:
        return verified_contexts(contexts)
    started = monotonic()
    try:
        with database_connection() as connection:
            # Reading candidates also counts against the request budget.
            connection.execute("SET LOCAL statement_timeout = '3s'")
            rows = connection.execute(_PENDING_SQL, (pending_ids,)).fetchall()
    except psycopg.Error:
        logger.warning("Canlı doğrulama için tohum kayıtları okunamadı", exc_info=True)
        return verified_contexts(contexts)

    verified: dict[UUID, str] = {}
    # Preserve relevance order; a DB ANY query has no ordering guarantee.
    by_id = {row['id']: row for row in rows}
    rows = [by_id[source_id] for source_id in dict.fromkeys(pending_ids) if source_id in by_id]
    for row in rows[:_MAX_DOCS]:
        remaining = budget_seconds - (monotonic() - started)
        if remaining <= 0:
            break
        external_id = str(row["external_id"] or "")
        kind = source_kind_from_external_id(external_id)
        if kind is None:
            continue
        document_id = document_id_from_external_id(external_id)
        try:
            official = _fetch_with_deadline(fetcher, kind, document_id, remaining)
        except _FetchTimeout:
            # Portal yanıt vermedi: yeni istek başlatılmaz (portala yük bindirmemek için).
            logger.info("Canlı doğrulama bütçesi doldu; kaynak doğrulanmadı olarak kalır")
            break
        except CaptchaRequiredError:
            logger.info("Canlı doğrulama CAPTCHA istedi; kaynak doğrulanmadı olarak kalır")
            break
        except Exception as exc:
            if is_rate_limited(exc):
                logger.info("Canlı doğrulama hız sınırına takıldı")
                break
            logger.info("Canlı doğrulama atlandı: %s", exc)
            continue
        if not official.strip() or not seed_matches_official(row["raw_text"] or "", official):
            continue
        # Metadata/full-text equality alone must not bless a stale/corrupt chunk.
        if any(not _nospace(c.content) or _nospace(c.content) not in _nospace(official)
               for c in contexts if c.source_id == row['id']):
            continue
        try:
            if promoter is not None:
                promoter(row["id"], kind, document_id, official)
            else:
                with admin_database_connection() as admin:
                    promote_verified_seed(
                        admin,
                        source_id=row["id"],
                        kind=kind,
                        document_id=document_id,
                        official_text=official,
                    )
            verified[row["id"]] = official_document_url(kind, document_id)
        except (psycopg.Error, RuntimeError):
            logger.warning("Doğrulanan tohum yazılamadı", exc_info=True)

    return verified_contexts([
        replace(context, verification="official", source_url=verified[context.source_id])
        if context.source_id in verified
        else context
        for context in contexts
    ])
