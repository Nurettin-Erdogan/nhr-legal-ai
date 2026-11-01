"""İncelenen kaynaklar: "ihtiyaç" gibi yaygın bir kelimeyle gelen alakasız kararlar elenir."""

from __future__ import annotations

from dataclasses import replace

from api.ai.consulted_relevance import relevant_chunk_ids
from api.ai.pipeline import consulted_sources
from api.ai.verification import VerifiedAnswer
from tests.factories import court_decision_context

QUESTION = "Kiracının tahliyesi için ihtiyaç nedeniyle açılan davada hangi şartlar aranır?"


def decision(n: int, content: str):
    return replace(
        court_decision_context(
            chunk_id=f"00000000-0000-0000-0000-{n:012d}",
            source_id=f"00000000-0000-0000-0001-{n:012d}",
            content=content,
        ),
        verification="official",
    )


RELEVANT = [
    "Kiracının tahliyesi ihtiyaç nedeniyle istenmiş, ihtiyacın samimi olması aranmıştır.",
    "Konutun kiracısı ihtiyaç sebebiyle tahliye edilmek istenmiş, tahliye davası açılmıştır.",
    "İşyeri kiracısının tahliyesi talebinde ihtiyaç gerçek ve samimi olmalıdır.",
]
NOISE = [
    "İhtiyati haciz koşulları oluşmadığından davanın reddine karar verilmiştir.",
    "Maddi hasarlı trafik kazası nedeniyle açılan davada kusur oranı belirlenmiştir.",
    "Gemi donatanı aleyhine açılan davada yangın zararının tahsiline karar verilmiştir.",
    "İhtiyati tedbir isteyen şirketin talebi yerinde görülmemiştir ve dava reddedilmiştir.",
    "Bacanın yasal şartlara uygunluğu bilirkişi raporuyla tespit edilmiştir davada.",
]


def pool_of(*texts):
    return [decision(i + 1, text) for i, text in enumerate(texts)]


def test_unrelated_decisions_matched_by_a_common_word_are_dropped():
    pool = pool_of(*RELEVANT, *NOISE)
    keep = relevant_chunk_ids(QUESTION, pool)
    kept_texts = {c.content for c in pool if c.chunk_id in keep}
    assert kept_texts == set(RELEVANT)


def test_a_homogeneous_pool_loses_nothing():
    kidem = [
        f"Kıdem tazminatı hesabında işçinin çalışma süresi {n} yıl olarak esas alınmıştır."
        for n in range(6)
    ]
    pool = pool_of(*kidem)
    keep = relevant_chunk_ids("İşçinin kıdem tazminatına hak kazanması için hangi şartlar gerekir?", pool)
    assert keep == {c.chunk_id for c in pool}


def test_a_small_pool_or_a_vague_question_is_never_filtered():
    pool = pool_of(*RELEVANT[:2], NOISE[0])
    assert relevant_chunk_ids(QUESTION, pool) == {c.chunk_id for c in pool}
    big = pool_of(*RELEVANT, *NOISE)
    assert relevant_chunk_ids("peki süresi?", big) == {c.chunk_id for c in big}


def test_the_cited_source_is_part_of_the_pool_so_a_weak_pool_cannot_promote_noise():
    # Gerçek akışta havuza cevapta alıntılanan karar da girer; o güçlü eşleştiği için
    # yalnız zayıf eşleşen ("ihtiyati") kararlar onun yanında elenir.
    pool = pool_of(RELEVANT[0], *NOISE)
    keep = relevant_chunk_ids(QUESTION, pool)
    assert {c.content for c in pool if c.chunk_id in keep} == {RELEVANT[0]}


def test_consulted_list_uses_the_filter_but_the_answer_basis_is_untouched():
    pool = pool_of(*RELEVANT, *NOISE)
    answer = VerifiedAnswer(text="Cevap [K1].", contexts=(pool[0],), unverified_markers=())
    listed = consulted_sources(answer, pool, QUESTION)
    assert {c.excerpt for c in listed} == set(RELEVANT[1:])
    assert all(c.verification == "official" for c in listed)
    # Soru verilmezse süzgeç uygulanmaz (eski davranış).
    assert len(consulted_sources(answer, pool)) == len(pool) - 1
