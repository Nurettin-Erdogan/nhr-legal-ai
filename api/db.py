from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from api.config import get_settings


@contextmanager
def database_connection() -> Iterator[psycopg.Connection]:
    with psycopg.connect(
        get_settings().database_url,
        row_factory=dict_row,
        connect_timeout=5,
    ) as connection:
        yield connection


@contextmanager
def admin_database_connection() -> Iterator[psycopg.Connection]:
    database_url = get_settings().admin_database_url
    if not database_url:
        raise RuntimeError("DATABASE_ADMIN_URL tanımlı değil")
    with psycopg.connect(
        database_url,
        row_factory=dict_row,
        connect_timeout=5,
    ) as connection:
        yield connection


@contextmanager
def authenticated_database_connection(user_id: str) -> Iterator[psycopg.Connection]:
    """Open an RLS-aware runtime connection scoped to one authenticated user."""
    with database_connection() as connection, connection.transaction():
        connection.execute("SELECT set_config('app.user_id', %s, true)", (user_id,))
        yield connection
