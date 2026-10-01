"""Hukuk araştırması API'sinin karar ve mevzuatı birlikte sunma testleri."""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date

import pytest

psycopg = pytest.importorskip("psycopg")

from api import legal

DATABASE_URL = os.getenv("NHR_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="NHR_TEST_DATABASE_URL tanımlı değil; veritabanı testleri atlandı.",
)

TOKEN = "pytest987654"
TEST_LAW_NO = "999992"


@pytest.fixture
def connection():
    with psycopg.connect(DATABASE_URL, row_factory=psycopg.rows.dict_row) as conn:
        with conn.transaction():
            yield conn
            raise psycopg.Rollback


def _seed_legislation(connection):
    source_id = connection.execute(
        """
        INSERT INTO legal_sources (
            source_type, title, external_id, authority, raw_text, ingest_status, metadata,
            canonical_source_name, ingestion_method, source_version,
            fetched_at, last_verified_at
        )
        VALUES (
            'legislation', %s, %s, 'Mevzuat Bilgi Sistemi', %s, 'ready',
            '{"verified_against_gazette":true,"verified_against_mbs":true}',
            'Mevzuat Bilgi Sistemi', 'bedesten_public_json_http', '1',
            NOW(), NOW()
        )
        RETURNING id
        """,
        (
            "İş Kanunu m. 25 — Haklı fesih",
            f"test/{TOKEN}/law/{TEST_LAW_NO}/25",
            f"{TOKEN} işveren haklı nedenle derhal feshedebilir.",
        ),
    ).fetchone()["id"]
    connection.execute(
        """
        INSERT INTO legislation_details (
            legal_source_id, legislation_type, law_name, law_no, article_no,
            article_title, official_gazette_no
        )
        VALUES (%s, 'law', 'İş Kanunu', %s, '25', 'Haklı fesih', '25134')
        """,
        (source_id, TEST_LAW_NO),
    )
    connection.execute(
        """
        INSERT INTO legal_chunks (legal_source_id, chunk_index, content)
        VALUES (%s, 0, %s)
        """,
        (source_id, f"{TOKEN} işveren haklı nedenle derhal feshedebilir."),
    )
    return source_id


@pytest.fixture(autouse=True)
def _clear_search_cache():
    legal._search_cache.clear()
    yield
    legal._search_cache.clear()


def _use_connection(monkeypatch, connection) -> None:
    @contextmanager
    def database_connection():
        yield connection

    monkeypatch.setattr(legal, "database_connection", database_connection)


def test_search_returns_legislation_metadata(connection, monkeypatch):
    source_id = _seed_legislation(connection)
    # VEYA yedeği yalnız resmî katmanı (embedding'li parçalar) tarar.
    connection.execute(
        "UPDATE legal_chunks SET embedding = '[0.1,0.2,0.3]'::vector WHERE legal_source_id = %s",
        (source_id,),
    )
    _use_connection(monkeypatch, connection)

    response = legal.search_legal_sources(
        q=f"{TOKEN} eşleşmeyenifade",
        limit=10,
        offset=0,
    )

    result = next(item for item in response.results if item.id == source_id)
    assert result.source_type == "legislation"
    assert result.law_name == "İş Kanunu"
    assert result.law_no == TEST_LAW_NO
    assert result.article_no == "25"
    assert result.chamber is None


def test_unverified_legislation_is_not_public(connection, monkeypatch):
    source_id = _seed_legislation(connection)
    connection.execute(
        "UPDATE legal_sources SET metadata = '{}'::jsonb WHERE id = %s",
        (source_id,),
    )
    _use_connection(monkeypatch, connection)

    response = legal.search_legal_sources(q=TOKEN, limit=10, offset=0)
    assert all(item.id != source_id for item in response.results)
    with pytest.raises(legal.HTTPException) as exc:
        legal.legal_source_detail(source_id)
    assert exc.value.status_code == 404


def test_source_detail_returns_legislation_and_chunks(connection, monkeypatch):
    source_id = _seed_legislation(connection)
    _use_connection(monkeypatch, connection)

    source = legal.legal_source_detail(source_id)

    assert source.source_type == "legislation"
    assert source.law_name == "İş Kanunu"
    assert source.official_gazette_no == "25134"
    assert len(source.chunks) == 1
    assert TOKEN in source.raw_text


def _seed_court(connection, *, court_name: str, authority: str, suffix: str) -> None:
    source_id = connection.execute(
        """
        INSERT INTO legal_sources (
            source_type, title, external_id, authority, raw_text, ingest_status,
            canonical_source_name, ingestion_method, source_version,
            fetched_at, last_verified_at
        )
        VALUES (
            'court_decision', %s, %s, %s, %s, 'ready',
            %s, 'test_fixture', '1', NOW(), NOW()
        )
        RETURNING id
        """,
        (
            f"{court_name} test kararı",
            f"test/{TOKEN}/court/{suffix}",
            authority,
            f"{TOKEN} {suffix} karar metni",
            court_name,
        ),
    ).fetchone()["id"]
    connection.execute(
        """
        INSERT INTO court_decision_details (
            legal_source_id, court_name, chamber, docket_no, decision_no, decision_date
        )
        VALUES (%s, %s, 'Test Dairesi', %s, %s, %s)
        """,
        (source_id, court_name, f"{TOKEN}/{suffix}", f"{TOKEN}/{suffix}", date(2026, 3, 1)),
    )
    connection.execute(
        "INSERT INTO legal_chunks (legal_source_id, chunk_index, content) VALUES (%s, 0, %s)",
        (source_id, f"{TOKEN} {suffix} karar metni"),
    )


def test_corpus_stats_break_down_courts_verification_and_embeddings(connection, monkeypatch):
    _seed_legislation(connection)
    for article_no, metadata in (
        ("1", "{}"),
        ("2", '{"verified_against_gazette":true}'),
        ("3", '{"verified_against_mbs":true}'),
    ):
        pending_id = connection.execute(
            """
            INSERT INTO legal_sources (
                source_type, title, external_id, authority, raw_text, ingest_status, metadata,
                canonical_source_name, ingestion_method, source_version,
                fetched_at, last_verified_at
            )
            VALUES (
                'legislation', %s, %s, 'Mevzuat Bilgi Sistemi', %s, 'pending',
                %s::jsonb, 'Mevzuat Bilgi Sistemi', 'bedesten_public_json_http', '1',
                NOW(), NOW()
            )
            RETURNING id
            """,
            (
                f"Bekleyen kanun m. {article_no}",
                f"test/{TOKEN}/law/{TEST_LAW_NO}/{article_no}",
                f"{TOKEN} henüz doğrulanmamış madde {article_no}.",
                metadata,
            ),
        ).fetchone()["id"]
        connection.execute(
            """
            INSERT INTO legislation_details (
                legal_source_id, legislation_type, law_name, law_no, article_no
            )
            VALUES (%s, 'law', 'İş Kanunu', %s, %s)
            """,
            (pending_id, TEST_LAW_NO, article_no),
        )
    _seed_court(connection, court_name="Yargıtay", authority="Yargıtay", suffix="yarg")
    _seed_court(connection, court_name="Danıştay", authority="Danıştay", suffix="dan")
    _seed_court(
        connection,
        court_name="Anayasa Mahkemesi",
        authority="Anayasa Mahkemesi",
        suffix="aym",
    )
    kdk_id = connection.execute(
        """
        INSERT INTO legal_sources (
            source_type, title, external_id, authority, raw_text, ingest_status,
            canonical_source_name, ingestion_method, source_version,
            fetched_at, last_verified_at
        )
        VALUES (
            'other', %s, %s, 'Kamu Denetçiliği Kurumu', %s, 'ready',
            'KDK Kararlar Bilgi Bankası', 'kdk_public_datatables_pdf', '1',
            NOW(), NOW()
        )
        RETURNING id
        """,
        (
            "KDK test kararı",
            f"test/{TOKEN}/kdk/1",
            f"{TOKEN} idari karar metni",
        ),
    ).fetchone()["id"]
    connection.execute(
        "INSERT INTO legal_chunks (legal_source_id, chunk_index, content) VALUES (%s, 0, %s)",
        (kdk_id, f"{TOKEN} idari karar metni"),
    )
    _use_connection(monkeypatch, connection)
    # Production uses an approximate pg_stat counter. Transactional fixture
    # rows are invisible to it, so supply this test's exact in-transaction count.
    monkeypatch.setattr(
        legal,
        "_live_chunk_estimate",
        lambda: connection.execute("SELECT count(*) AS n FROM legal_chunks").fetchone()["n"],
    )
    # Some deployments have live progress readers; the committed baseline does
    # not. Stub them only when present, without making them a test prerequisite.
    for reader in ("_live_embedded_count", "_read_embed_progress_ready"):
        if hasattr(legal, reader):
            monkeypatch.setattr(legal, reader, lambda: None)

    stats = legal.corpus_stats()

    assert stats.court_decisions.yargitay >= 1
    assert stats.court_decisions.danistay >= 1
    assert stats.court_decisions.anayasa_mahkemesi >= 1
    assert stats.administrative.kamu_denetciligi_kurumu >= 1
    assert stats.legislation_count >= 1
    verification = stats.legislation_verification
    assert verification.bedesten >= 4
    assert verification.both_verified >= 1
    assert verification.gazette_only >= 1
    assert verification.mbs_only >= 1
    assert verification.neither >= 1
    assert verification.bedesten == (
        verification.both_verified
        + verification.gazette_only
        + verification.mbs_only
        + verification.neither
    )
    assert stats.embeddings.pending >= 1
    assert stats.chunk_count == stats.embeddings.ready + stats.embeddings.pending
    assert stats.decision_count >= (
        stats.court_decisions.yargitay
        + stats.court_decisions.danistay
        + stats.court_decisions.anayasa_mahkemesi
    )
