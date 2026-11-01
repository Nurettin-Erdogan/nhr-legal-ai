"""Atıf yapılan üçüncü taraf kaynakları öncelikli doğrulama kuyruğuna alır.

Cevap üretildikten sonra çağrılır. Portala istek atmaz; yalnız `seed_verification_queue`
tablosuna satır ekler. Kuyruğu `scripts/verify_seeds.py` (portala tek elden giden süreç)
tarih taramasının önünde tüketir, böylece eşzamanlı istek ve ek CAPTCHA riski doğmaz.
"""

from __future__ import annotations

import logging
import threading
from uuid import UUID

import psycopg

from api.db import database_connection

logger = logging.getLogger(__name__)

# Bir cevapta en çok bu kadar kaynak kuyruğa alınır; kalanı sonraki sorularda sıraya girer.
MAX_PER_ANSWER = 6

_ENQUEUE_SQL = """
INSERT INTO seed_verification_queue (legal_source_id)
SELECT ls.id
FROM legal_sources ls
WHERE ls.id = ANY(%s)
  AND ls.ingestion_method = 'bulk_seed'
  AND ls.ingest_status = 'pending'
  AND ls.is_current
  AND ls.deleted_at IS NULL
ON CONFLICT (legal_source_id) DO UPDATE
SET request_count = seed_verification_queue.request_count + 1,
    requested_at = now()
"""


def enqueue(source_ids: list[UUID]) -> int:
    """Kuyruğa alınan/talebi artırılan kayıt sayısını döndürür."""
    if not source_ids:
        return 0
    with database_connection() as connection:
        connection.execute("SET LOCAL statement_timeout = '5s'")
        return connection.execute(_ENQUEUE_SQL, (source_ids[:MAX_PER_ANSWER],)).rowcount or 0


def enqueue_in_background(source_ids: list[UUID]) -> None:
    """Cevabı geciktirmeden kuyruğa alır; hata cevabı etkilemez."""
    if not source_ids:
        return

    def run() -> None:
        try:
            enqueue(source_ids)
        except psycopg.Error:
            logger.warning("Atıf doğrulama kuyruğuna eklenemedi", exc_info=True)

    threading.Thread(target=run, name="citation-verify-enqueue", daemon=True).start()
