"""Offline replay of acronym retrieval failures; no model API or database."""
from dataclasses import replace
import json
import pytest

from api.ai.query_vocabulary import expand_search_terms, definition_evidence_score, standalone_definition
from api.ai.search_plan import plan_search
from api.ai.relevance import passage_relevant, semantic_search_text
from api.ai.passages import sentence_score
from api.ai import retrieval, free_answer
from tests.factories import legislation_context

REFERENCE_TEXT = (
    "Değişken faizli konut finansmanı sözleşmelerinde kullanılabilecek referans endeks "
    "Türkiye İstatistik Kurumu tarafından açıklanan Tüketici Fiyat Endeksi (TÜFE)' dir."
)


@pytest.mark.parametrize("query", ["TÜFE nedir?", "tüfe nedir", "tufe nedir?", "Tüfe ne demek?"])
def test_acronym_has_same_vocabulary_in_text_vector_and_passage_paths(query):
    assert "tüketici fiyat endeksi" in plan_search(query).text
    assert "tüketici fiyat endeksi" in semantic_search_text(query)
    assert passage_relevant(query, REFERENCE_TEXT)
    assert not passage_relevant(query, "Yivsiz tüfek ruhsatnamesi almak zorunludur.")
    assert not passage_relevant(query, "Tüfeklerin el değiştirmesi yönetmelikte belirtilir.")


@pytest.mark.parametrize("term,expected", [
    ("SGK", "sosyal güvenlik kurumu"), ("HMK", "hukuk muhakemeleri kanunu"),
    ("KVKK", "kişisel verilerin korunması"), ("KDV", "katma değer vergisi"),
])
def test_short_acronyms_are_not_lost_by_minimum_token_length(term, expected):
    assert expected in plan_search(term + " nedir?").text


def test_token_boundaries_and_source_text_are_preserved():
    assert expand_search_terms("Tüfek ruhsatı") == "tüfek ruhsatı"
    assert definition_evidence_score("TÜFE nedir?", REFERENCE_TEXT) > 0
    incidental = "Kira bedeli tüketici fiyat endeksi oranında artırılır."
    assert sentence_score(REFERENCE_TEXT, "TÜFE nedir?") > sentence_score(incidental, "TÜFE nedir?")


@pytest.mark.parametrize("question", ["TÜFE nedir?", "tufe nedir", "SGK nedir?", "KVKK ne demek?"])
def test_missing_acronym_sources_are_not_misreported_as_nonlegal(question):
    from api.ai.pipeline import _looks_non_legal
    assert not _looks_non_legal(question)


def test_lexical_query_uses_expansion_without_any_model(monkeypatch):
    calls = []
    source = legislation_context(content=REFERENCE_TEXT)

    def execute(connection, sql, params, *, timeout):
        calls.append(params)
        return [source]

    monkeypatch.setattr(retrieval, "_execute_retrieval", execute)
    result = retrieval.retrieve_contexts(None, question="TÜFE nedir?", top_k=4)
    assert result
    assert calls[0]["question"] == "tüketici fiyat endeksi"


def test_definition_replays_writer_and_checker_without_paid_api():
    from tests.test_free_answer import Provider, verdict
    source = replace(legislation_context(content=REFERENCE_TEXT), law_no="11297", article_no="3")
    writer = Provider("TÜFE, Tüketici Fiyat Endeksi'nin kısaltmasıdır. @@ 1.1")
    checker = Provider(verdict(1))
    info = {}
    answer = free_answer.free_verified_answer(writer, checker_provider=checker,
        question="TÜFE nedir?", contexts=[source], diagnostics=info)
    assert answer and answer.grounded
    assert answer.contexts == (source,)
    assert info["kept"] == 1
    payload = json.loads(writer.calls[0]["prompt"])
    assert payload["sources"][0]["evidence_units"][0]["text"] == REFERENCE_TEXT


@pytest.mark.parametrize("question,expected", [
    ("TÜFE nedir?", True), ("Haklı fesih ne demek?", True), ("KVKK nedir", True),
    ("Bu nedir?", False), ("Benim hakkım nedir?", False), ("Tazminatım nedir?", False),
    ("Sözleşmedeki TÜFE nedir?", False), ("Peki bunun anlamı nedir?", False),
])
def test_only_self_contained_definitions_can_ignore_previous_event_context(question, expected):
    assert standalone_definition(question) is expected
