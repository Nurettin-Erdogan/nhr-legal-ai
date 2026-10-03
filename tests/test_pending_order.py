"""Doğrulama kuyruğu: kurtarılamayan kayıtlar taze adayları (tebliğ/yönetmelik) tıkamaz."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone

import psycopg
import pytest
from psycopg.rows import dict_row

from ingestion.mevzuat.official_verify import _PENDING_LAWS_SQL, pending_laws

DATABASE_URL = os.getenv("NHR_TEST_DATABASE_URL")
requires_db = pytest.mark.skipif(not DATABASE_URL, reason="NHR_TEST_DATABASE_URL gerekir")
PREFIX = "99700"


def test_order_puts_the_attempt_tier_and_recency_before_the_type_priority():
    sql = _PENDING_LAWS_SQL
    tier = sql.index(">= 50 THEN 2")
    recent = sql.index("INTERVAL '20 minutes'")
    type_priority = sql.index("IN ('law', 'decree', 'constitution')")
    assert tier < recent < type_priority


@pytest.fixture
def connection():
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.transaction():
            yield conn
            raise psycopg.Rollback


def _law(conn, kind: str, number: int, *, attempts: int | None = None, recent: bool = False,
         gazette: bool = False, mbs: bool = False) -> str:
    metadata: dict = {"verified_against_gazette": gazette, "verified_against_mbs": mbs}
    if attempts is not None:
        metadata["verify_attempt_count"] = attempts
    if recent:
        metadata["verify_last_attempt_at"] = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    law_no = f"{PREFIX}{number}"
    source_id = conn.execute(
        """
        INSERT INTO legal_sources (
            source_type, title, external_id, authority, raw_text, ingest_status,
            canonical_source_name, ingestion_method, source_version, fetched_at, metadata
        )
        VALUES ('legislation', %s, %s, 'Mevzuat Bilgi Sistemi', 'metin', 'ready',
                'Mevzuat Bilgi Sistemi', 'test_fixture', '1', NOW(), %s::jsonb)
        RETURNING id
        """,
        (f"Test {kind} {law_no}", f"test/pending-order/{kind}/{law_no}", json.dumps(metadata)),
    ).fetchone()["id"]
    conn.execute(
        """
        INSERT INTO legislation_details (legal_source_id, legislation_type, law_name, law_no, article_no,
                                         official_gazette_date, official_gazette_no)
        VALUES (%s, %s, %s, %s, '1', %s, '30000')
        """,
        (source_id, kind, f"Test {kind} {law_no}", law_no, date(2020, 1, 1)),
    )
    return law_no


def _order(conn) -> list[str]:
    return [law["law_no"] for law in pending_laws(conn, limit=500) if law["law_no"].startswith(PREFIX)]


@requires_db
def test_hopeless_laws_never_outrank_fresh_communiques_even_when_not_recently_tried(connection):
    hopeless = [_law(connection, "decree", n, attempts=400) for n in range(1, 4)]
    communique = _law(connection, "communique", 10, attempts=5, mbs=True)
    fresh = _law(connection, "communique", 11)
    order = _order(connection)
    assert order.index(fresh) < order.index(communique) < min(order.index(h) for h in hopeless)


@requires_db
def test_a_recently_tried_exhausted_law_goes_behind_a_never_tried_communique(connection):
    # Eski sıralamada tür önceliği "yakın zamanda denendi" ölçütünün önündeydi: kanun hep öne dönerdi.
    tried = _law(connection, "law", 20, attempts=30, recent=True, gazette=True)
    waiting = _law(connection, "communique", 21, attempts=6, mbs=True)
    order = _order(connection)
    assert order.index(waiting) < order.index(tried)


@requires_db
def test_within_a_tier_law_types_still_come_first_and_fresh_candidates_before_exhausted(connection):
    exhausted_law = _law(connection, "law", 30, attempts=7)
    fresh_regulation = _law(connection, "regulation", 31)
    fresh_law = _law(connection, "law", 32)
    order = _order(connection)
    assert order.index(fresh_law) < order.index(fresh_regulation) < order.index(exhausted_law)
