"""Kaynak başına PostgreSQL advisory lock.

Aynı source iki worker'da paralel çalışmaz; farklı source'lar bağımsızdır.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

LOCK_NAMESPACE = 872001


class JobLockedError(RuntimeError):
    """Aynı kaynak için başka bir sync zaten çalışıyor."""


@contextmanager
def source_job_lock(
    connection: psycopg.Connection,
    source_name: str,
) -> Iterator[None]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_lock(%s, hashtext(%s))",
            (LOCK_NAMESPACE, source_name),
        )
        locked = bool(cursor.fetchone()[0])
    if not locked:
        raise JobLockedError(f"{source_name} sync zaten çalışıyor")
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_unlock(%s, hashtext(%s))",
                (LOCK_NAMESPACE, source_name),
            )
