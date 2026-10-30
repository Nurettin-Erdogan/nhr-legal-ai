"""`/api/legal/semantic`: olayı anlatan sorgu için benzer karar listesi (sohbet hattının hibrit getirmesi), gerçek veritabanında."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import contextmanager
from datetime import date

import psycopg
import pytest
from fastapi import HTTPException

from api import legal
from tests.test_ai_persistence import TOKEN, connection as _connection_fixture

connection = _connection_fixture

pytestmark = pytest.mark.skipif(not os.getenv("NHR_TEST_DATABASE_URL"), reason="Isolated test DB not configured")

_numbers = iter(range(9000, 100000))  # (mahkeme, daire, esas, karar) benzersiz olmalı


def _decision(connection, label: str, text: str, *, status="ready", method="yargitay_public_json_http", current=True, deleted=False):
    source_id = connection.execute(
        """
        INSERT INTO legal_sources (
            source_type, title, external_id, authority, raw_text, published_at, ingest_status,
            canonical_source_name, ingestion_method, source_version, fetched_at, last_verified_at, is_current, deleted_at
        )
        VALUES ('court_decision', %s, %s, 'Yargıtay', %s, %s, %s, 'Yargıtay Karar Arama', %s, '1', NOW(), NOW(), %s,
                CASE WHEN %s THEN NOW() END)
        RETURNING id
        """,
        (f"Yargıtay {label}", f"test/{TOKEN}/semantic/{label}", text, date(2026, 1, 2), status, method, current, deleted),
    ).fetchone()["id"]
    number = next(_numbers)
    connection.execute(
        "INSERT INTO court_decision_details (legal_source_id, court_name, chamber, docket_no, decision_no, decision_date) "
        "VALUES (%s, 'Yargıtay', '9. Hukuk Dairesi', %s, %s, %s)",
        (source_id, f"2026/{number}", f"2026/{number + 100000}", date(2026, 1, 2)),
    )
    connection.execute("INSERT INTO legal_chunks (legal_source_id, chunk_index, content) VALUES (%s, 0, %s)", (source_id, text))
    return source_id


@pytest.fixture
def semantic(connection, monkeypatch):
    @contextmanager
    def database_connection():
        yield connection

    monkeypatch.setattr(legal, "database_connection", database_connection)
    legal._semantic_cache.clear()
    state = {"embedding": None, "calls": 0}

    async def embed(question):
        state["calls"] += 1
        return state["embedding"]

    monkeypatch.setattr("api.ai.pipeline._embed_question", embed)
    yield state
    legal._semantic_cache.clear()


def _search(query: str, **kwargs):
    return asyncio.run(legal.semantic_search_sources(q=query, limit=kwargs.get("limit", 10), offset=kwargs.get("offset", 0)))


def test_a_case_description_returns_matching_decisions_with_their_fields_and_verification(connection, semantic):
    official = _decision(connection, "resmi", f"{TOKEN} işçi haklı nedenle feshetti, kıdem tazminatına hak kazanır.")
    response = _search(f"{TOKEN} müvekkil işçi haklı nedenle iş akdini feshetti, kıdem tazminatı alabilir mi")
    hit = next(hit for hit in response.results if hit.id == official)
    assert hit.verification == "official" and hit.source_type == "court_decision"
    assert hit.court_name == "Yargıtay" and hit.chamber == "9. Hukuk Dairesi" and hit.docket_no.startswith("2026/")
    assert hit.decision_date == date(2026, 1, 2) and hit.excerpt.startswith(TOKEN) and len(hit.excerpt) <= 700
    assert response.partial is True  # en iyi ~60 kaynakla sınırlı: korpusun tamamı değil


def test_unverified_bulk_records_are_not_listed(connection, semantic):
    """Doğrulanmamış toplu kayıt aramada çıkmaz (kullanıcı kararı 2026-10-18)."""
    third = _decision(connection, "ucuncu", f"{TOKEN} işçi kıdem tazminatı kararı.", status="pending", method="bulk_seed")
    assert third not in [hit.id for hit in _search(f"{TOKEN} işçi kıdem tazminatı kararı arıyorum").results]


@pytest.mark.parametrize("change", [{"current": False}, {"deleted": True}])
def test_ineligible_sources_are_not_returned(connection, semantic, change):
    hidden = _decision(connection, "gizli", f"{TOKEN} tazminat kararı hakkında.", **change)
    assert hidden not in [hit.id for hit in _search(f"{TOKEN} tazminat kararı hakkında arıyorum").results]


def test_pagination_walks_the_pool_without_repeats(connection, semantic):
    created = [_decision(connection, f"s{number}", f"{TOKEN} tazminat davası {number}.") for number in range(5)]
    first = _search(f"{TOKEN} tazminat davası", limit=3, offset=0)
    second = _search(f"{TOKEN} tazminat davası", limit=3, offset=3)
    seen = [hit.id for hit in first.results] + [hit.id for hit in second.results]
    assert len(seen) == len(set(seen)) and set(created) <= set(seen)
    assert first.total == second.total >= 5


def test_without_the_embedding_service_the_lexical_search_still_answers(connection, semantic):
    """Gömme servisi kapalıyken 503 yerine yalnız sözcük araması yapılır; sonuç zaten "kısmi" işaretlidir."""
    semantic["embedding"] = None
    source = _decision(connection, "sozcuk", f"{TOKEN} zeytinyağı ihracatı gecikmesi.")
    response = _search(f"{TOKEN} zeytinyağı ihracatı gecikmesi")
    assert source in [hit.id for hit in response.results] and response.partial is True


def test_results_are_cached_per_query(connection, semantic):
    _decision(connection, "onbellek", f"{TOKEN} zeytinyağı ihracatı önbellek.")
    first = _search(f"{TOKEN} zeytinyağı ihracatı önbellek")
    second = _search(f"{TOKEN} zeytinyağı ihracatı önbellek")
    assert first is second and semantic["calls"] == 1  # ikinci istek ne gömme ne veritabanı


def test_a_timeout_is_a_504_never_an_empty_list(connection, semantic, monkeypatch):
    def always_timeout(*args, **kwargs):
        raise psycopg.errors.QueryCanceled("zaman aşımı")

    monkeypatch.setattr("api.ai.retrieval.retrieve_contexts", always_timeout)
    with pytest.raises(HTTPException) as error:
        _search(f"{TOKEN} kıdem tazminatı zaman aşımı kararı")
    assert error.value.status_code == 504


def test_a_cold_first_attempt_is_retried_once(connection, semantic, monkeypatch):
    attempts = []
    from api.ai import retrieval

    original = retrieval.retrieve_contexts

    def flaky(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise psycopg.errors.QueryCanceled("soğuk önbellek")
        return original(*args, **kwargs)

    monkeypatch.setattr("api.ai.retrieval.retrieve_contexts", flaky)
    source = _decision(connection, "yeniden", f"{TOKEN} zeytinyağı ihracatı sevkiyatı.")
    response = _search(f"{TOKEN} zeytinyağı ihracatı sevkiyatı")
    assert len(attempts) == 2 and source in [hit.id for hit in response.results]


def test_the_query_text_is_never_logged(connection, semantic, caplog):
    with caplog.at_level(logging.DEBUG):
        _search(f"{TOKEN} müvekkil adı gizli bilgi içeren olay anlatımı")
    assert "gizli bilgi" not in caplog.text


def test_a_partial_thin_first_attempt_is_retried_and_the_fuller_answer_is_kept(connection, semantic, monkeypatch):
    """Bir kol zaman aşımına düşüp yalnız 1 kaynak kalırsa (yalnız kanun maddesi gibi) bir kez daha denenir."""
    from api.ai import retrieval

    original = retrieval.retrieve_contexts
    attempts = []

    def thin_then_full(*args, **kwargs):
        attempts.append(1)
        contexts = original(*args, **kwargs)
        if len(attempts) == 1:
            kwargs["diagnostics"]["partial"] = True
            return contexts[:1]
        return contexts

    monkeypatch.setattr("api.ai.retrieval.retrieve_contexts", thin_then_full)
    created = [_decision(connection, f"kismi{number}", f"{TOKEN} zeytinyağı ihracatı gecikmesi {number}.") for number in range(3)]
    response = _search(f"{TOKEN} zeytinyağı ihracatı gecikmesi")
    assert len(attempts) == 2 and set(created) <= {hit.id for hit in response.results}


def test_a_complete_first_attempt_is_not_retried(connection, semantic, monkeypatch):
    from api.ai import retrieval

    original = retrieval.retrieve_contexts
    attempts = []

    def counting(*args, **kwargs):
        attempts.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr("api.ai.retrieval.retrieve_contexts", counting)
    _decision(connection, "tam", f"{TOKEN} zeytinyağı ihracatı sevkiyatı kararı.")
    _search(f"{TOKEN} zeytinyağı ihracatı sevkiyatı kararı")
    assert len(attempts) == 1
