from __future__ import annotations

import asyncio
import threading
from datetime import date
from types import SimpleNamespace

import pytest

from api.ai.on_demand_verify import (
    clear_on_demand_verification_cache,
    explicit_statute_reference,
    verify_pending_statute,
    verify_relevant_pending_statute,
)
from api.ai import pipeline as ai_pipeline
from api.ai.cache import answer_cache
from api.schemas import AIAnswerRequest
from tests.factories import legislation_context


@pytest.fixture(autouse=True)
def _clear_attempt_cache():
    clear_on_demand_verification_cache()
    yield
    clear_on_demand_verification_cache()


def _candidate() -> dict:
    return {
        "legislation_type": 1,
        "law_no": "2577",
        "law_name": "İdari Yargılama Usulü Kanunu",
        "official_gazette_date": None,
        "official_gazette_no": None,
        "metadata": {},
    }


def test_explicit_statute_reference_ignores_unlabelled_year():
    assert explicit_statute_reference(
        "2024 yilinda 2577 sayili Kanun m. 7 nasil uygulanir?"
    ) == ("2577", "7")
    assert explicit_statute_reference("İptal davası süresi nedir?") is None


def test_historical_or_non_exact_question_does_not_touch_portals():
    def unexpected_loader(*_args):
        raise AssertionError("aday sorgulanmamalı")

    assert (
        verify_pending_statute(
            "İptal davası süresi nedir?",
            candidate_loader=unexpected_loader,
        )
        == "not_applicable"
    )
    assert (
        verify_pending_statute(
            "2577 sayili Kanun madde 7 nedir?",
            as_of=date(2020, 1, 1),
            candidate_loader=unexpected_loader,
        )
        == "not_applicable"
    )


def test_verified_candidate_is_applied_before_retrieval():
    applied: list[tuple[dict, dict, dict]] = []

    status = verify_pending_statute(
        "2577 sayili Kanun m. 7 nedir?",
        candidate_loader=lambda law_no, article_no: (
            _candidate() if (law_no, article_no) == ("2577", "7") else None
        ),
        verifier=lambda _law: (
            {
                "verified_against_gazette": True,
                "verified_against_mbs": True,
            },
            {"verify_last_attempt_at": "2026-09-23T00:00:00+00:00"},
            5,
        ),
        applier=lambda law, flags, results: applied.append((law, flags, results)),
    )

    assert status == "verified"
    assert len(applied) == 1
    assert applied[0][1]["verified_against_gazette"] is True
    assert applied[0][1]["verified_against_mbs"] is True


def test_one_official_catalog_is_enough_to_verify():
    # Kullanıcı kararı 2026-10-15: Resmî Gazete ya da MBS'den biriyle eşleşen madde resmîdir.
    applied: list[tuple[dict, dict, dict]] = []

    status = verify_pending_statute(
        "2577 sayili Kanun madde 7 nedir?",
        candidate_loader=lambda *_args: _candidate(),
        verifier=lambda _law: (
            {
                "verified_against_gazette": True,
                "verified_against_mbs": False,
            },
            {"mbs_verification": {"verified": False}},
            5,
        ),
        applier=lambda law, flags, results: applied.append((law, flags, results)),
    )

    assert status == "verified"
    assert len(applied) == 1
    assert applied[0][1]["verified_against_mbs"] is False


def test_matching_neither_catalog_stays_pending_and_records_result():
    applied: list[tuple[dict, dict, dict]] = []

    status = verify_pending_statute(
        "2577 sayili Kanun madde 7 nedir?",
        candidate_loader=lambda *_args: _candidate(),
        verifier=lambda _law: (
            {
                "verified_against_gazette": False,
                "verified_against_mbs": False,
            },
            {"mbs_verification": {"verified": False}},
            5,
        ),
        applier=lambda law, flags, results: applied.append((law, flags, results)),
    )

    assert status == "pending"
    assert len(applied) == 1
    assert applied[0][1]["verified_against_gazette"] is False


def test_slow_portal_is_bounded_by_request_budget():
    release = threading.Event()

    def slow_verifier(_law):
        release.wait(1)
        return (
            {
                "verified_against_gazette": False,
                "verified_against_mbs": False,
            },
            {},
            0,
        )

    try:
        status = verify_pending_statute(
            "2577 sayili Kanun m. 7 nedir?",
            budget_seconds=0.01,
            candidate_loader=lambda *_args: _candidate(),
            verifier=slow_verifier,
            applier=lambda *_args: None,
        )
        assert status == "timeout"
    finally:
        release.set()


def test_pipeline_verifies_exact_pending_statute_before_retrieval(monkeypatch):
    answer_cache.clear()
    verified: list[str] = []

    monkeypatch.setattr(
        ai_pipeline,
        "get_settings",
        lambda: SimpleNamespace(
            ai_provider="deepseek",
            ai_model="test-model",
            ollama_base_url="http://127.0.0.1:11434",
            ollama_timeout_seconds=10,
            ollama_max_output_tokens=256,
            ollama_num_ctx=2048,
            ollama_keep_alive="1m",
            rag_query_embedding=False,
            rag_top_k=2,
            embedding_model="test-embedding",
            rag_context_chars=800,
        ),
    )
    monkeypatch.setattr(
        ai_pipeline,
        "create_provider",
        lambda **_kwargs: SimpleNamespace(name="deepseek", model="test-model"),
    )
    monkeypatch.setattr(
        ai_pipeline,
        "unload_ollama_model",
        lambda *_args: None,
        raising=False,
    )
    monkeypatch.setattr(
        ai_pipeline,
        "verify_pending_statute",
        lambda question, **_kwargs: verified.append(question) or "verified",
    )
    monkeypatch.setattr(
        ai_pipeline,
        "verify_relevant_pending_statute",
        lambda question, **_kwargs: "not_pending",
    )

    def retrieve(*_args, **_kwargs):
        assert verified, "resmî doğrulama retrieval'dan önce çalışmalı"
        return [legislation_context()]

    monkeypatch.setattr(ai_pipeline, "_retrieve", retrieve)
    monkeypatch.setattr(
        ai_pipeline,
        "generate_grounded_answer",
        lambda *_args, **_kwargs: f"{legislation_context().content} [K1]",
    )

    response, timings = asyncio.run(
        ai_pipeline.execute_answer(
            AIAnswerRequest(question="4857 sayili Kanun madde 25 nedir?"),
            None,
        )
    )

    assert response.grounded is True
    assert timings.extra["on_demand_legislation"] == "verified"


def test_relevant_pending_statute_promotes_only_matching_official_text():
    candidate = {
        **_candidate(),
        "source_id": "00000000-0000-0000-0000-000000000099",
        "article_no": "14",
        "raw_text": "uzun madde metni",
        "metadata": {
            "verified_against_mbs": True,
            "mbs_pdf_url": "https://www.mevzuat.gov.tr/MevzuatMetin/1.5.1475.pdf",
        },
    }
    promoted: list[tuple[dict, float, str]] = []

    status = verify_relevant_pending_statute(
        "Kıdem tazminatına hak kazanma şartları nelerdir?",
        candidate_loader=lambda _question: [candidate],
        text_verifier=lambda _law: (
            True,
            0.947,
            "https://www.mevzuat.gov.tr/MevzuatMetin/1.5.1475.pdf",
        ),
        promoter=lambda law, ratio, url: promoted.append((law, ratio, url)),
    )

    assert status == "verified"
    assert promoted == [
        (
            candidate,
            0.947,
            "https://www.mevzuat.gov.tr/MevzuatMetin/1.5.1475.pdf",
        )
    ]


def test_relevant_pending_statute_does_not_promote_text_mismatch():
    promoted: list[object] = []

    status = verify_relevant_pending_statute(
        "Kıdem tazminatına hak kazanma şartları nelerdir?",
        candidate_loader=lambda _question: [{"source_id": "x"}],
        text_verifier=lambda _law: (
            False,
            0.51,
            "https://www.mevzuat.gov.tr/MevzuatMetin/1.5.1475.pdf",
        ),
        promoter=lambda *args: promoted.append(args),
    )

    assert status == "pending"
    assert promoted == []
