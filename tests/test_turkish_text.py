"""Türkçe karakter geri getirme: ASCII yazılmış sorular ("davaci kac yil") arama için düzeltilir."""

from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from api.ai import research, turkish_text
from api.ai import pipeline as ai_pipeline
from api.ai.cache import answer_cache
from api.ai.turkish_text import restore_turkish
from api.schemas import AIAnswerRequest
from tests.test_ai_pipeline import _settings


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("davaci kac yil calismis", "davacı kaç yıl çalışmış"),
        ("kidem tazminati", "kıdem tazminatı"),
        ("haksiz fesih halinde isci", "haksız fesih halinde işçi"),
        ("isten cikarma", "işten çıkarma"),
        ("bosanma davasi ve nafaka", "boşanma davası ve nafaka"),
        ("tuketici hakem heyeti basvuru siniri", "tüketici hakem heyeti başvuru sınırı"),
        ("kira artis orani", "kira artış oranı"),
        ("mahkeme karari ile icra takibi", "mahkeme kararı ile icra takibi"),
        ("ihbar suresi kac hafta", "ihbar süresi kaç hafta"),
    ],
)
def test_ascii_typed_legal_questions_get_their_turkish_letters_back(typed, expected):
    assert restore_turkish(typed) == expected


def test_ambiguous_words_are_decided_by_their_neighbours():
    assert restore_turkish("ise iade davasi") == "işe iade davası"  # "işe iade"
    assert restore_turkish("ise baslama tarihi") == "işe başlama tarihi"  # "işe başlama"
    assert restore_turkish("isyeri ise iade") == "işyeri işe iade"
    # Bağlaç olan "ise" korunur ("davalı ise ..."): belirsizlikte zarar verecek değişiklik yapılmaz.
    assert restore_turkish("davali ise haksiz fesih") == "davalı ise haksız fesih"


def test_text_that_already_has_a_turkish_letter_is_left_alone():
    for text in ("davacı kaç yıl çalışmış", "Kidem tazminatı nedir", "boşanma davasında nafaka", "İş Kanunu madde 17"):
        assert restore_turkish(text) == text


def test_idempotent():
    once = restore_turkish("davaci kac yil calismis")
    assert restore_turkish(once) == once


def test_valid_ascii_words_acronyms_numbers_and_punctuation_are_untouched():
    assert restore_turkish("idare mahkemesi istanbul") == "idare mahkemesi istanbul"
    assert restore_turkish("TBK 344. madde, HMK m. 107") == "TBK 344. madde, HMK m. 107"
    assert restore_turkish("kidem tazminati (8 yil, 340.000 TL)?") == "kıdem tazminatı (8 yıl, 340.000 TL)?"


def test_capitalisation_is_preserved():
    assert restore_turkish("Kidem Tazminati nedir") == "Kıdem Tazminatı nedir"
    assert restore_turkish("KIDEM TAZMINATI sartlari") == "KIDEM TAZMİNATI şartları"


def test_suffixes_after_an_apostrophe_or_digit_are_not_treated_as_words():
    assert restore_turkish("Yargitay'in kidem tazminati karari") == "Yargıtay'in kıdem tazminatı kararı"
    assert restore_turkish("30'uncu madde") == "30'uncu madde"


def test_missing_vocabulary_never_breaks_search(monkeypatch):
    turkish_text._vocabulary.cache_clear()
    monkeypatch.setattr(turkish_text, "RESOURCE", turkish_text.RESOURCE.with_name("yok.json.gz"))
    try:
        assert restore_turkish("davaci kac yil") == "davaci kac yil"
        assert restore_turkish("") == ""
    finally:
        turkish_text._vocabulary.cache_clear()


def test_restoring_is_fast_enough_to_run_on_every_question():
    restore_turkish("isinma")  # sözlüğü yükle
    started = time.perf_counter()
    for _ in range(2000):
        restore_turkish("davaci kac yil calismis ve bilirkisi kidem tazminatini ne kadar hesaplamis")
    assert time.perf_counter() - started < 2.0


# --- arama yollarına bağlantı ------------------------------------------------------------------


def test_answer_pipeline_searches_with_restored_letters_but_keeps_the_typed_question(monkeypatch):
    answer_cache.clear()
    monkeypatch.setattr(ai_pipeline, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        ai_pipeline, "create_provider", lambda **kwargs: SimpleNamespace(name="deepseek", model="deepseek-r1:8b")
    )
    searched: list[str] = []

    def retrieve(*args, **kwargs):
        searched.append(kwargs["question"])
        return []

    monkeypatch.setattr(ai_pipeline, "_retrieve", retrieve)
    typed = "davaci kac yil calismis ve kidem tazminati nedir"
    request = AIAnswerRequest(question=typed)

    async def collect():
        return [event async for event in ai_pipeline.iter_answer_events(request, None)]

    asyncio.run(collect())

    assert searched and searched[0] == "davacı kaç yıl çalışmış ve kıdem tazminatı nedir"
    assert request.question == typed  # kullanıcının yazdığı soru değişmedi


def test_research_page_searches_restored_text_and_echoes_the_typed_query(monkeypatch):
    seen: list[str] = []

    def load(q, limit, offset):
        seen.append(q)
        return SimpleNamespace(text=q, phrase=None), [], False, 0, False

    monkeypatch.setattr(research, "load_candidate_page", load)
    monkeypatch.setattr(research, "verify_third_party_contexts", lambda candidates: candidates)

    response = research.research_sources(q="kidem tazminati sartlari", limit=10, offset=0)

    assert seen == ["kıdem tazminatı şartları"]
    assert response["query"] == "kidem tazminati sartlari"


def test_legal_search_uses_restored_text_and_echoes_the_typed_query(monkeypatch):
    from api import legal

    legal._search_cache.clear()
    captured: list[dict] = []

    class _Result:
        def fetchall(self):
            return []

    class _Connection:
        def execute(self, statement, params=None):
            if isinstance(params, dict) and "query" in params:
                captured.append(params)
            return _Result()

    @contextmanager
    def connection():
        yield _Connection()

    monkeypatch.setattr(legal, "database_connection", connection)

    response = legal.search_legal_sources(q="kidem tazminati sartlari", limit=5, offset=0, as_of=None)

    assert captured and captured[0]["query"] == "kıdem tazminatı şartları"
    assert response.query == "kidem tazminati sartlari"


def test_answer_generation_also_gets_the_restored_question(monkeypatch):
    """Kanıt cümlelerini seçen alaka filtresi aksanlara duyarlıdır: üretime ASCII soru gitseydi tüm
    cümleler elenir ve model hiç çağrılmadan "yeterli bilgi yok" denirdi."""
    from tests.test_document_relevance import FACT, _context

    answer_cache.clear()
    monkeypatch.setattr(ai_pipeline, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        ai_pipeline, "create_provider", lambda **kwargs: SimpleNamespace(name="deepseek", model="deepseek-r1:8b")
    )
    document = _context("document", "BİLİRKİŞİ RAPORU\n\n" + FACT, "user_document")
    monkeypatch.setattr(ai_pipeline, "_retrieve", lambda *args, **kwargs: [document])
    generated: list[str] = []

    def generate(provider, *, question, contexts, **kwargs):
        generated.append(question)
        return f"{FACT} [K1]"

    monkeypatch.setattr(ai_pipeline, "generate_grounded_answer", generate)

    async def collect():
        return [
            event
            async for event in ai_pipeline.iter_answer_events(
                AIAnswerRequest(question="bilirkisi kidem tazminatini ne kadar hesaplamis"), None
            )
        ]

    asyncio.run(collect())

    assert generated == ["bilirkişi kıdem tazminatını ne kadar hesaplamış"]
