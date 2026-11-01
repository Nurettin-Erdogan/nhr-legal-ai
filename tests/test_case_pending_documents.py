"""Belgeler henüz işlenirken (ör. OCR sürerken) sorulan soru yanıltıcı "kaynak yok" hatası vermemeli."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from api.ai import pipeline as ai_pipeline
from api.ai.cache import answer_cache
from api.ai.pipeline import iter_answer_events
from api.schemas import AIAnswerRequest
from tests.test_ai_pipeline import _settings


def _run(monkeypatch, *, case_id, document_scope):
    answer_cache.clear()
    monkeypatch.setattr(ai_pipeline, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        ai_pipeline,
        "create_provider",
        lambda **kwargs: SimpleNamespace(name="deepseek", model="deepseek-r1:8b"),
    )

    def retrieve(*args, **kwargs):
        if document_scope is not None and kwargs.get("diagnostics") is not None:
            kwargs["diagnostics"]["document_scope"] = document_scope
        return []

    monkeypatch.setattr(ai_pipeline, "_retrieve", retrieve)

    async def collect():
        return [
            event
            async for event in iter_answer_events(
                AIAnswerRequest(question="Bilirkişi raporunda hangi tutar hesaplanmış?", case_id=case_id),
                None,
            )
        ]

    return asyncio.run(collect())[-1]


def test_pending_case_documents_are_explained_instead_of_reporting_no_source(monkeypatch):
    scope = {"total": 3, "ready": 1, "pending": 2, "failed": [], "ocr": 0}
    event = _run(monkeypatch, case_id=uuid4(), document_scope=scope)

    assert event["stage"] == "error" and event["status"] == 422
    assert "2 belge henüz işleniyor" in event["detail"]
    assert "OCR" in event["detail"]
    assert "resmî doğrulanmış kaynak" not in event["detail"]


def test_without_pending_documents_the_usual_no_source_message_remains(monkeypatch):
    scope = {"total": 1, "ready": 1, "pending": 0, "failed": [], "ocr": 0}
    event = _run(monkeypatch, case_id=uuid4(), document_scope=scope)

    assert event["status"] == 422
    assert "resmî doğrulanmış kaynak bulunamadı" in event["detail"]


def test_questions_without_a_case_never_mention_documents(monkeypatch):
    event = _run(monkeypatch, case_id=None, document_scope={"pending": 5})

    assert "belge henüz işleniyor" not in event["detail"]
    assert "resmî doğrulanmış kaynak bulunamadı" in event["detail"]
