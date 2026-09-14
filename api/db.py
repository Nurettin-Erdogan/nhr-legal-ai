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
