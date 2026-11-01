"""Asistanın kendinden söz eden cümleleri ("elimde yok", "cevaplayabilirim") kaynakla kanıtlanamaz; cevaba girmez (ağ/DB gerektirmez).

Ölçüldü (2026-10-30): "Yalnızca kanun maddelerine ulaşabildiğinde hangi soruları cevaplayabilirsin? Bulamadığın kararları uydurmadan
kısmi bir yanıt oluştur" sorusunda iki Yargıtay kararına atıf yapan paragrafın hemen altında "bu kararlara ilişkin kaynaklar elimde
bulunmadığı için bilgi veremem" cümlesi denetimden geçti. Planlayıcının içtihat bölümü ham soruyu (talimatıyla birlikte) taşıyordu.
"""

import pytest

from api.ai.free_answer import _ABOUT_SOURCES


@pytest.mark.parametrize("sentence", [
    "Yalnızca kanun maddelerine ulaşabildiğimde, işe iade şartları hakkındaki soruları cevaplayabilirim.",
    "Ancak bu kararlara ilişkin kaynaklar elimde bulunmadığı için bilgi veremem.",
    "Bu nedenle, size yalnızca mevzuat kaynaklarıyla sınırlı, kısmi bir yanıt oluşturabiliyorum.",
    "Bu kararların içeriğini kanun metinlerinden çıkaramayız.",
    "Kararları uydurmadan yalnız kanunla cevap veriyorum.",
])
def test_sentences_about_the_assistant_itself_are_not_answers(sentence):
    assert _ABOUT_SOURCES.search(sentence)


@pytest.mark.parametrize("sentence", [
    "İşveren işçiyi bir ay içinde işe başlatmazsa tazminat ödemek zorundadır.",
    "İşçi bu süreyi kaçırırsa dava hakkını kaybeder ve işveren tazminat vermez.",
    "Bulunduğu yer mahkemesi yetkilidir.",
    "Hâkim delilleri serbestçe değerlendirir ve hüküm verir.",
    "Taraflar delil sunabilir.",
    "İşveren bu hakkı vermeyi reddedemez.",
])
def test_legal_sentences_with_similar_verbs_are_kept(sentence):
    assert not _ABOUT_SOURCES.search(sentence)


def test_the_added_case_law_part_is_a_plain_question_without_the_users_instructions(monkeypatch):
    from types import SimpleNamespace
    from api.ai import free_answer, pipeline
    from api.ai.verification import VerifiedAnswer
    from tests.factories import legislation_context
    question = ("Bir kullanıcı üç ayrı soru soruyor: İşe iade şartları, başvuru süresi ve iki Yargıtay kararı. Yalnızca kanun "
                "maddelerine ulaşabildiğinde hangi soruları cevaplayabilirsin?")
    local = legislation_context()
    seen = {}
    monkeypatch.setattr(pipeline, "get_settings", lambda: SimpleNamespace(legislation_embedding_model="", cloud_ai_provider=""))
    monkeypatch.setattr(free_answer, "plan_question", lambda *a: [("İşe iade şartları nelerdir?", ("işe iade şartları",))])

    def write(provider, **kwargs):
        seen["parts"] = [text for text, _ in kwargs["parts"]] if kwargs.get("parts") else None
        return VerifiedAnswer("Cevap.", (local,), ())

    monkeypatch.setattr(free_answer, "free_verified_answer", write)
    monkeypatch.setattr(pipeline, "_safe_retrieve", lambda retrieve, query: [local])
    pipeline._free_answer(object(), question, [local], [], pipeline.PipelineTimings(), object())
    assert seen["parts"] is not None
    assert "Bu konudaki Yargıtay kararları ne diyor?" in seen["parts"]
    assert not any("cevaplayabilirsin" in part for part in seen["parts"])


def test_a_repaired_answer_keeps_its_paragraphs():
    from hashlib import sha256
    from uuid import uuid4
    from api.ai.free_answer import _regroup, _remap_preserved
    assert _regroup([("a", 1), ("b", 1), ("c", 2), ("d", 1)]) == [["a", "b"], ["c"], ["d"]]
    chunk = str(uuid4())
    pool = [type("C", (), {"chunk_id": chunk})()]
    views = [{"units": ["birinci", "ikinci"]}]
    ref = lambda unit: [{"chunk_id": chunk, "unit": unit, "unit_hash": sha256(views[0]["units"][unit - 1].encode()).hexdigest()}]
    saved = [("Bir.", ref(1), 1), ("İki.", ref(2), 1), ("Üç.", ref(1), 2)]
    paragraphs = _remap_preserved(saved, pool, views)
    assert [[text for text, _ in p] for p in paragraphs] == [["Bir.", "İki."], ["Üç."]]
    # an older two-field record still works, one sentence per paragraph
    assert len(_remap_preserved([("Bir.", ref(1)), ("İki.", ref(2))], pool, views)) == 2
