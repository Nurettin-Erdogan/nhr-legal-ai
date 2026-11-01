"""Önceden hazırlanmış cevaplar (api/ai/warm_cache.py): yalnız kaynaklar değişmemişse ve yalnız genel sorular için kullanılır."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import psycopg
import pytest

from api.ai import warm_cache
from api.ai.verification import VerifiedAnswer
from tests.factories import court_decision_context, legislation_context

LAW = legislation_context(content="İşveren bildirim süresine uymazsa tazminat öder.")
DECISION = court_decision_context(chunk_id="00000000-0000-0000-0000-000000000051", source_id="00000000-0000-0000-0000-000000000052",
                                  content="Mahkeme ihbar tazminatına hükmetmiştir.")


class FakeConnection:
    """execute() -> object with fetchone(); records every statement."""

    def __init__(self, row=None, error=None):
        self.row, self.error, self.statements = row, error, []

    def execute(self, sql, params=()):
        if self.error:
            raise self.error
        self.statements.append((sql, params))
        return SimpleNamespace(fetchone=lambda: self.row)


def _row(answer, current, kind="legal"):
    return {"answer_text": answer.text, "answer_kind": kind,
            "contexts": json.dumps([warm_cache.context_to_json(c) for c in answer.contexts]),
            "source_fingerprint": warm_cache.state_fingerprint(current)}


def test_the_question_key_ignores_case_punctuation_and_spacing_but_not_words():
    assert warm_cache.question_key("Kıdem  Tazminatı nedir, kimler alabilir?") == warm_cache.question_key("kıdem tazminatı nedir kimler alabilir")
    assert warm_cache.question_key("İhbar tazminatı nedir?") == warm_cache.question_key("ihbar tazminatı nedir")
    assert warm_cache.question_key("Kıdem tazminatı nedir?") != warm_cache.question_key("İhbar tazminatı nedir?")
    assert warm_cache.question_key("Süre 30 gün mü?") != warm_cache.question_key("Süre 60 gün mü?")


def test_a_context_survives_the_json_round_trip_exactly():
    for context in (LAW, DECISION):
        assert warm_cache.context_from_json(warm_cache.context_to_json(context)) == context
    assert isinstance(warm_cache.context_from_json(warm_cache.context_to_json(LAW)).chunk_id, UUID)


def test_the_state_fingerprint_changes_with_content_version_and_revision():
    base = warm_cache.state_fingerprint([LAW, DECISION])
    assert warm_cache.state_fingerprint([DECISION, LAW]) == base  # order does not matter
    assert warm_cache.state_fingerprint([replace(LAW, content=LAW.content + " Yeni."), DECISION]) != base
    assert warm_cache.state_fingerprint([replace(LAW, source_version="v2"), DECISION]) != base
    assert warm_cache.state_fingerprint([replace(LAW, revision=9), DECISION]) != base


def test_a_stored_answer_is_served_only_while_every_cited_chunk_is_unchanged(monkeypatch):
    answer = VerifiedAnswer(text="Kaynaklı cevap.", contexts=(LAW, DECISION), unverified_markers=())
    row = _row(answer, [LAW, DECISION])
    monkeypatch.setattr(warm_cache, "_current_chunks", lambda connection, ids: [LAW, DECISION])
    served = warm_cache.lookup(FakeConnection(row), "Soru?")
    assert served is not None and served.text == "Kaynaklı cevap." and served.contexts == (LAW, DECISION) and served.grounded

    # the statute was amended since: nothing is served
    monkeypatch.setattr(warm_cache, "_current_chunks", lambda connection, ids: [replace(LAW, content="Değişti."), DECISION])
    assert warm_cache.lookup(FakeConnection(row), "Soru?") is None
    # a cited chunk is no longer verified/current (the trust filters return fewer rows)
    monkeypatch.setattr(warm_cache, "_current_chunks", lambda connection, ids: [LAW])
    assert warm_cache.lookup(FakeConnection(row), "Soru?") is None


def test_no_stored_answer_database_error_or_non_legal_kind_means_the_normal_pipeline(monkeypatch):
    answer = VerifiedAnswer(text="Cevap.", contexts=(LAW,), unverified_markers=())
    monkeypatch.setattr(warm_cache, "_current_chunks", lambda connection, ids: [LAW])
    assert warm_cache.lookup(FakeConnection(None), "Soru?") is None
    assert warm_cache.lookup(FakeConnection(error=psycopg.OperationalError("down")), "Soru?") is None
    assert warm_cache.lookup(FakeConnection(_row(answer, [LAW], kind="conversation")), "Soru?") is None
    bad = _row(answer, [LAW])
    bad["contexts"] = "not json"
    assert warm_cache.lookup(FakeConnection(bad), "Soru?") is None


def test_only_a_grounded_legal_answer_with_readable_sources_is_stored(monkeypatch):
    monkeypatch.setattr(warm_cache, "_current_chunks", lambda connection, ids: [LAW])
    good = VerifiedAnswer(text="Cevap.", contexts=(LAW,), unverified_markers=())
    connection = FakeConnection()
    assert warm_cache.store(connection, "  Soru nedir?  ", good, "model-x") is True
    sql, params = connection.statements[0]
    assert "INSERT INTO verified_answer_cache" in sql
    assert params[0] == warm_cache.question_key("Soru nedir?") and params[1] == warm_cache.ANSWER_PIPELINE_VERSION
    assert params[2] == "Soru nedir?" and params[6] == warm_cache.state_fingerprint([LAW]) and params[7] == "model-x"

    empty = VerifiedAnswer(text="Kaynaksız.", contexts=(), unverified_markers=())
    assert warm_cache.store(FakeConnection(), "Soru?", empty, "m") is False
    conversation = VerifiedAnswer(text="Merhaba.", contexts=(LAW,), unverified_markers=(), answer_kind="conversation")
    assert warm_cache.store(FakeConnection(), "Soru?", conversation, "m") is False
    # a cited chunk that cannot be read back unchanged is never stored
    monkeypatch.setattr(warm_cache, "_current_chunks", lambda connection, ids: [])
    assert warm_cache.store(FakeConnection(), "Soru?", good, "m") is False


@pytest.mark.parametrize("change,expected", [
    ({}, True),
    ({"as_of": "2020-01-01"}, False),
    ({"conversation_id": "00000000-0000-0000-0000-0000000000aa"}, False),
    ({"project_id": "00000000-0000-0000-0000-0000000000bb"}, False),
    ({"case_id": "00000000-0000-0000-0000-0000000000cc"}, False),
    ({"selected_document_ids": ["00000000-0000-0000-0000-0000000000dd"]}, False),
])
def test_only_a_plain_general_question_may_use_the_stored_answers(change, expected):
    from api.ai.pipeline import _warm_cache_eligible
    from api.schemas import AIAnswerRequest
    values = {"question": "Kıdem tazminatı nedir?", **change}
    if "as_of" in values:
        from datetime import date
        values["as_of"] = date.fromisoformat(values["as_of"])
    request = AIAnswerRequest(**values)
    settings = SimpleNamespace(rag_natural_answers=True, free_answer_enabled=True, warm_answer_cache_enabled=True)
    cloud, local = object(), object()
    assert _warm_cache_eligible(request, settings, cloud, local, (), "default") is expected
    # never on the local model, with earlier turns, or when switched off
    assert _warm_cache_eligible(request, settings, local, local, (), "default") is False
    assert _warm_cache_eligible(request, settings, cloud, local, ("önceki tur",), "default") is False
    assert _warm_cache_eligible(request, SimpleNamespace(**{**vars(settings), "warm_answer_cache_enabled": False}),
                                cloud, local, (), "default") is False
    assert _warm_cache_eligible(request, settings, cloud, local, (), "deep_research") is False


def test_the_warmup_list_parses_aliases_and_drops_repeats(tmp_path):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("warm_script", Path(__file__).resolve().parents[1] / "scripts" / "warm_answer_cache.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    listing = tmp_path / "q.txt"
    listing.write_text(
        "# yorum\n\nKıdem tazminatı nedir? || Kıdem tazminatı nedir || kıdem tazminatı kimlere ödenir\n"
        "İhbar tazminatı nedir?\nkıdem tazminatı NEDİR\nİhbar süresi nedir? || İhbar tazminatı nedir\n", encoding="utf-8")
    questions = script.read_questions(listing)
    assert questions == [("Kıdem tazminatı nedir?", ["kıdem tazminatı kimlere ödenir"]),
                         ("İhbar tazminatı nedir?", []), ("İhbar süresi nedir?", [])]


def test_the_shipped_warmup_list_has_no_personal_facts_and_no_duplicate_keys():
    import importlib.util
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("warm_script2", root / "scripts" / "warm_answer_cache.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    questions = script.read_questions(root / "docs" / "warmup-questions.txt")
    assert len(questions) >= 100
    keys = [warm_cache.question_key(text) for main, aliases in questions for text in (main, *aliases)]
    assert len(keys) == len(set(keys))
    for main, aliases in questions:
        for text in (main, *aliases):
            assert not re.search(r"\d", text), text  # a number is a user fact: never in a shared, stored question
            assert len(text) <= 160
