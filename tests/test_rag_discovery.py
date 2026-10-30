"""Synthetic sources only; no database, portals, workers or legal advice."""

from dataclasses import replace
from uuid import UUID

import psycopg
import pytest

from api.ai import live_verify, retrieval
from api.ai.discovery import candidate_pool_size, select_answer_contexts, search_summary
from ingestion.yargitay.portal import CaptchaRequiredError
from tests.factories import court_decision_context

QUESTION = "Boşanmada ortak velayet hangi şartlarda verilir?"
TEXT = "Ortak velayet değerlendirilirken çocuğun yararı gözetilir."


def source(i, *, pending=False):
    return replace(
        court_decision_context(content=TEXT),
        source_id=UUID(int=i),
        chunk_id=UUID(int=1000 + i),
        verification="third_party" if pending else "official",
    )


def test_general_case_law_request_prioritizes_courts_over_administrative_keyword_hits():
    administrative = replace(
        source(1), source_type="other", authority="Sayıştay", rank=99
    )
    court = source(2)
    selected = select_answer_contexts(
        [administrative, court], 1, question="Kira artışıyla ilgili kararları araştır."
    )
    assert selected == [court]
    # Explicit institution scope remains authoritative; no source is deleted.
    assert select_answer_contexts(
        [administrative, court], 1, question="Sayıştay kira artışı kararlarını araştır."
    ) == [administrative]


def fake_database(monkeypatch, contexts):
    rows = [
        dict(
            id=c.source_id,
            external_id=f"yargitay:{c.source_id.int}",
            raw_text=c.content,
        )
        for c in contexts
        if c.verification == "third_party"
    ]

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=None):
            if params is not None:
                self.ids = params[0]
            return self

        def fetchall(self):
            return [row for row in reversed(rows) if row["id"] in self.ids]

    monkeypatch.setattr(live_verify, "database_connection", Connection)


def test_semantic_hit_never_suppresses_unembedded_text_hit(monkeypatch):
    calls = []
    semantic, unembedded = source(1), source(2, pending=True)

    def execute(conn, sql, params, **kwargs):
        calls.append((sql, params))
        if sql == retrieval.LEGISLATION_SEMANTIC_SQL:
            return []
        return [semantic] if sql == retrieval.SEMANTIC_RETRIEVAL_SQL else [unembedded]

    monkeypatch.setattr(retrieval, "_execute_retrieval", execute)
    stats = {}
    result = retrieval.retrieve_contexts(
        object(),
        question=QUESTION,
        top_k=48,
        query_embedding=[0.1] * 768,
        embedding_model="test-model",
        diagnostics=stats,
    )
    assert {c.source_id for c in result} == {semantic.source_id, unembedded.source_id}
    assert (
        len(calls) == 3 and calls[0][1]["candidate_limit"] <= 192
    )  # + legislation-only ANN (migration 060)
    assert stats["lexical_candidates"] == stats["semantic_candidates"] == 1
    assert stats["exhaustive"] is False


def test_m3_search_survives_a_failed_shared_query_embedding(monkeypatch):
    calls = []

    def execute(conn, sql, params, **kwargs):
        calls.append(sql)
        return []

    monkeypatch.setattr(retrieval, "_execute_retrieval", execute)
    stats = {}
    retrieval.retrieve_contexts(
        object(),
        question=QUESTION,
        top_k=4,
        query_embedding=None,
        embedding_model="test-model",
        legislation_embedding=[0.2] * 1024,
        diagnostics=stats,
    )
    assert retrieval.LEGISLATION_M3_SQL in calls
    assert retrieval.SEMANTIC_RETRIEVAL_SQL not in calls
    assert stats["legislation_m3_candidates"] == 0


def test_lexical_timeout_preserves_semantic_hits_and_reports_partial(monkeypatch):
    def execute(conn, sql, params, **kwargs):
        if sql == retrieval.SEMANTIC_RETRIEVAL_SQL:
            return [source(1)]
        raise psycopg.errors.QueryCanceled()

    monkeypatch.setattr(retrieval, "_execute_retrieval", execute)
    stats = {}
    assert retrieval.retrieve_contexts(
        object(),
        question=QUESTION,
        top_k=48,
        query_embedding=[0.1] * 768,
        embedding_model="test-model",
        diagnostics=stats,
    )
    assert stats["partial"] and stats["branches"][-1]["status"] == "timeout"


def test_candidate_pool_is_independent_of_model_context():
    assert candidate_pool_size(6) == 48
    assert candidate_pool_size(999) == 96
    official = [source(i) for i in range(1, 10)]
    duplicate = replace(official[0], chunk_id=UUID(int=9000))
    chosen = select_answer_contexts(
        [source(10, pending=True), official[0], duplicate, *official[1:]], 6
    )
    assert len(chosen) == len({c.source_id for c in chosen}) == 6
    assert all(c.verification == "official" for c in chosen)


def test_refills_past_first_four_failed_documents_without_retries(monkeypatch):
    contexts = [source(i, pending=True) for i in range(1, 11)]
    fake_database(monkeypatch, contexts)
    calls, promotions, stats = [], [], {}

    def fetch(kind, doc):
        calls.append(doc)
        return "Eşleşmeyen başka bir metin." if int(doc) <= 4 else TEXT

    result = live_verify.verify_third_party_contexts(
        contexts,
        fetcher=fetch,
        promoter=lambda *a: promotions.append(a[0]),
        max_docs=12,
        target_sources=3,
        diagnostics=stats,
    )
    assert calls == [str(i) for i in range(1, 8)]
    assert [c.source_id.int for c in result] == [5, 6, 7]
    assert len(promotions) == stats["promoted"] == 3
    assert stats["mismatched"] == 4 and stats["stop_reason"] == "target_reached"


@pytest.mark.parametrize(
    "error,reason",
    [
        (CaptchaRequiredError("blocked"), "captcha"),
        (live_verify._FetchTimeout(), "time_budget"),
    ],
)
def test_portal_block_does_not_trigger_refill_storm(monkeypatch, error, reason):
    contexts = [source(i, pending=True) for i in range(1, 10)] + [source(20)]
    fake_database(monkeypatch, contexts)
    calls, stats = [], {}

    def fetch(*args):
        calls.append(args)
        raise error

    result = live_verify.verify_third_party_contexts(
        contexts,
        fetcher=fetch,
        promoter=lambda *a: pytest.fail("must not promote"),
        max_docs=12,
        target_sources=6,
        diagnostics=stats,
    )
    assert len(calls) == 1 and result == [contexts[-1]]
    assert stats["stop_reason"] == reason


def test_request_budget_does_not_reset_between_candidates(monkeypatch):
    contexts = [source(i, pending=True) for i in range(1, 10)]
    fake_database(monkeypatch, contexts)
    clock, stats = [0.0], {}
    monkeypatch.setattr(live_verify, "monotonic", lambda: clock[0])

    def fetch(*args):
        clock[0] += 2
        return "eşleşmez"

    live_verify.verify_third_party_contexts(
        contexts, fetcher=fetch, max_docs=12, budget_seconds=3, diagnostics=stats
    )
    assert stats["attempted"] == 2 and stats["stop_reason"] == "time_budget"


def test_default_research_budget_remains_four(monkeypatch):
    contexts = [source(i, pending=True) for i in range(1, 10)]
    fake_database(monkeypatch, contexts)
    stats = {}
    live_verify.verify_third_party_contexts(
        contexts, fetcher=lambda *a: "eşleşmez", diagnostics=stats
    )
    assert stats["attempted"] == 4 and stats["stop_reason"] == "document_budget"


def test_repeated_chunks_do_not_consume_multiple_portal_requests(monkeypatch):
    c = source(1, pending=True)
    contexts = [c, replace(c, chunk_id=UUID(int=2000))]
    fake_database(monkeypatch, contexts)
    calls = []
    result = live_verify.verify_third_party_contexts(
        contexts, fetcher=lambda *a: calls.append(a) or TEXT, promoter=lambda *a: None
    )
    assert len(calls) == 1 and len(result) == 2


def test_only_attemptable_full_texts_are_loaded_from_database(monkeypatch):
    contexts = [source(i, pending=True) for i in range(1, 49)]
    seen = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            if params is not None:
                seen.extend(params[0])
            return self

        def fetchall(self):
            return []

    monkeypatch.setattr(live_verify, "database_connection", Connection)
    live_verify.verify_third_party_contexts(
        contexts, fetcher=lambda *a: TEXT, max_docs=12
    )
    assert seen == [c.source_id for c in contexts[:12]]


def test_summary_does_not_claim_total_or_expose_source_text():
    candidates = [source(1, pending=True), source(2), source(3)]
    stats = search_summary(
        candidates,
        candidates[1:],
        candidates[1:2],
        {"partial": True},
        {"attempted": 1, "stop_reason": "captcha"},
    )
    assert stats["candidate_documents"] == 3 and stats["selected_documents"] == 1
    assert stats["unverified_excluded"] == 1 and stats["retrieval_partial"]
    assert stats["exhaustive"] is False and "total" not in stats
    assert TEXT not in str(stats)


@pytest.mark.parametrize(
    "info,expected",
    [
        ({"partial": False, "branches": [{"name": "lexical", "status": "ok"}]}, "none"),
        # a bounded sample was delivered: the search answered, from a sample
        ({"partial": True, "branches": [{"name": "lexical", "status": "timeout_then_tiered"}]}, "sampled"),
        ({"partial": True, "branches": [{"name": "lexical", "status": "timeout_then_official"}]}, "sampled"),
        ({"partial": True, "branches": [{"name": "lexical", "status": "official_only"}]}, "sampled"),
        # a lane delivered nothing: the graver statement wins over a sampled sibling
        ({"partial": True, "branches": [{"name": "lexical", "status": "timeout_then_tiered"},
                                        {"name": "legislation_m3", "status": "timeout"}]}, "failed"),
        ({"partial": True, "branches": [{"name": "semantic", "status": "skipped_unindexed"}]}, "failed"),
        ({"partial": True, "branches": [{"name": "semantic", "status": "connection_error"}]}, "failed"),
        ({"partial": True, "decision_search": "timeout", "branches": []}, "failed"),
        # partial with no lane detail: the stronger statement is the safe one
        ({"partial": True}, "failed"),
        # a lane skipped on purpose is not a failure
        ({"partial": False, "branches": [{"name": "lexical", "status": "skipped_long_question"}]}, "none"),
        ({}, "none"),
    ],
)
def test_the_search_limit_separates_a_sample_from_a_failure(info, expected):
    from api.ai.discovery import retrieval_limit

    assert retrieval_limit(info) == expected


def test_the_graver_limit_wins_and_unknown_values_count_as_none():
    from api.ai.discovery import worse_limit

    assert worse_limit() == "none"
    assert worse_limit("none", "sampled") == "sampled"
    assert worse_limit("sampled", "failed", "none") == "failed"
    assert worse_limit(None, "bogus") == "none"


def test_summary_carries_the_search_limit_without_dropping_the_partial_flag():
    candidates = [source(1)]
    stats = search_summary(candidates, candidates, candidates,
                           {"partial": True, "branches": [{"name": "lexical", "status": "timeout_then_tiered"}]}, {})
    assert stats["retrieval_partial"] is True and stats["retrieval_limit"] == "sampled"
    clean = search_summary(candidates, candidates, candidates, {"partial": False, "branches": []}, {})
    assert clean["retrieval_partial"] is False and clean["retrieval_limit"] == "none"


def test_pipeline_keeps_large_pool_until_verification_then_limits_model(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from api.ai import pipeline
    from api.ai.cache import answer_cache
    from api.schemas import AIAnswerRequest

    answer_cache.clear()
    candidates = [source(i, pending=i <= 12) for i in range(1, 49)]
    events = []
    settings = SimpleNamespace(
        ai_provider="qwen",
        ai_model="synthetic",
        ollama_base_url="http://127.0.0.1:11434",
        ollama_timeout_seconds=1,
        ollama_max_output_tokens=256,
        ollama_num_ctx=4096,
        ollama_keep_alive="1m",
        rag_top_k=6,
        rag_context_chars=2400,
        rag_query_embedding=False,
        rag_explanations=False,
        embedding_model="test-model",
    )
    monkeypatch.setattr(pipeline, "get_settings", lambda: settings)
    monkeypatch.setattr(
        pipeline,
        "create_provider",
        lambda **kw: SimpleNamespace(name="qwen", model="synthetic"),
    )
    for name in (
        "pause_embeddings",
        "resume_embeddings",
        "unload_ollama_model",
        "verify_relevant_pending_statute",
    ):
        if hasattr(pipeline, name):
            monkeypatch.setattr(pipeline, name, lambda *a, **k: None)

    def retrieve(*a, **kwargs):
        assert kwargs["top_k"] == 48
        kwargs["diagnostics"].update(
            partial=True, lexical_candidates=40, semantic_candidates=20
        )
        return candidates

    def verify(contexts, **kwargs):
        assert (
            len(contexts) == 48
            and kwargs["target_sources"] == 6
            and kwargs["max_docs"] == 12
        )
        kwargs["diagnostics"].update(
            attempted=7, promoted=3, stop_reason="target_reached"
        )
        return [replace(c, verification="official") for c in contexts[4:7]] + contexts[
            12:
        ]

    def generate(*a, **kwargs):
        assert len(kwargs["contexts"]) == 6
        assert all(c.verification == "official" for c in kwargs["contexts"])
        return TEXT + " [K1]"

    monkeypatch.setattr(pipeline, "_retrieve", retrieve)
    monkeypatch.setattr(pipeline, "verify_third_party_contexts", verify)
    monkeypatch.setattr(pipeline, "generate_grounded_answer", generate)
    result, timings = asyncio.run(
        pipeline.execute_answer(
            AIAnswerRequest(question=QUESTION), None, on_stage=events.append
        )
    )
    assert result.grounded and len(result.citations) == 1
    assert result.search_summary["candidate_documents"] == 48
    assert result.search_summary["verified_documents"] == 39
    assert result.search_summary["unverified_excluded"] == 9
    assert result.search_summary["verification_promoted"] == 3
    assert result.search_summary["selected_documents"] == 6
    assert result.search_summary["retrieval_partial"]
    assert any(e["stage"] == "search_summary" for e in events)
