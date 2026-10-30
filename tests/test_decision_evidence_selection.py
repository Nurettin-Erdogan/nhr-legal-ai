from dataclasses import replace
from uuid import UUID

from api.ai.discovery import select_answer_contexts
from api.ai.decision_attribution import requested_court_evidence
from api.ai.pipeline import _with_decisions
from api.ai.retrieval import merge_lexical_hits
from tests.factories import court_decision_context, legislation_context

QUESTION = 'Kira artışı hakkında Yargıtay kararları'


def test_employment_query_cannot_receive_criminal_jurisdiction_decisions_in_any_lane():
    question = 'İşe iade şartları ve 30 işçi hesabını iki Yargıtay kararıyla açıkla'
    criminal = decision(71, 'İşe iade davasından söz edilen dosyada ceza mahkemelerinin yetki uyuşmazlığı.',
                        chamber='5. Ceza Dairesi')
    unrelated = decision(72, 'Tapu iptal ve tescil talebi incelenmiştir.', chamber='1. Hukuk Dairesi')
    relevant = decision(73, 'İşe iade talebinde otuz işçi koşulu incelenmiştir.', chamber='9. Hukuk Dairesi')
    law = legislation_context()
    pool = [law, criminal, unrelated, relevant]
    assert select_answer_contexts(pool, 4, question=question) == [law, relevant]
    assert requested_court_evidence(question, pool) == [law, relevant]
    assert _with_decisions([law, criminal], pool, question=question) == [law, relevant]
    assert pool == [law, criminal, unrelated, relevant]


def test_mixed_employment_criminal_question_preserves_criminal_evidence():
    criminal = decision(74, 'İşverenin işçiye yönelik suç isnadı değerlendirilmiştir.', chamber='Ceza Genel Kurulu')
    assert requested_court_evidence('İşverenin suç teşkil eden eylemi için Yargıtay ceza kararları', [criminal]) == [criminal]


def decision(i, text, **kwargs):
    return replace(court_decision_context(content=text), source_id=UUID(int=i),
                   chunk_id=UUID(int=i+100), **kwargs)


def test_party_section_does_not_fill_decision_slots_before_reasoning():
    party = decision(1, 'DAVACININ İDDİALARI Kira artışı TÜFE ile sınırlıdır.')
    holding = decision(2, 'HUKUKİ DEĞERLENDİRME Kira artışı yönünden karar incelenmiştir.')
    assert select_answer_contexts([party, holding], 1, question=QUESTION) == [holding]
    assert _with_decisions([], [party, holding], question=QUESTION) == [holding, party]


def test_same_source_reasoning_survives_retrieval_diversification():
    party = decision(1, 'DAVACININ İDDİALARI Kira artışı TÜFE ile sınırlıdır.', rank=0.5)
    holding = replace(party, chunk_id=UUID(int=999),
                      content='HUKUKİ DEĞERLENDİRME Kira artışı TÜFE yönünden incelenmiştir.')
    assert merge_lexical_hits(QUESTION, [party, holding], [], 1) == [holding]


def test_auxiliary_decisions_are_unique_and_verified():
    a = decision(1, 'Kira artışı değerlendirilmiştir.')
    duplicate = replace(a, chunk_id=UUID(int=999))
    pending = decision(2, 'HUKUKİ DEĞERLENDİRME Kira artışı incelenmiştir.', verification='third_party')
    assert _with_decisions([], [a, duplicate, pending], question=QUESTION) == [a]


def test_no_source_is_deleted_or_relabelled_and_statute_stays_first():
    law = legislation_context()
    party = decision(1, 'DAVACININ İDDİALARI Kira artışı TÜFE ile sınırlıdır.')
    holding = decision(2, 'HUKUKİ DEĞERLENDİRME Kira artışı yönünden karar incelenmiştir.')
    original = [law, party, holding]
    selected = select_answer_contexts(original, 3, question=QUESTION)
    assert selected == [law, holding, party]
    assert original == [law, party, holding]


def test_statute_only_topic_keeps_verified_primary_basis():
    law = replace(legislation_context(), law_no='6098', article_no='344')
    party = decision(1, 'DAVACININ İDDİALARI Kira artışı TÜFE ile sınırlıdır.')
    assert select_answer_contexts([party, law], 3, question='kira zammı') == [law]


def test_explicit_court_request_does_not_substitute_another_official_court():
    yargitay = decision(1, 'Kira temerrüdü incelenmiştir.', court_name='Yargıtay')
    bam = decision(2, 'Kira temerrüdü incelenmiştir.', court_name='İstanbul Bölge Adliye Mahkemesi')
    law = legislation_context()

    result = requested_court_evidence('TBK 315 ve Yargıtay kararlarıyla açıkla', [law, bam, yargitay])

    assert result == [law, yargitay]


def test_explicit_multiple_courts_keep_only_named_courts():
    yargitay = decision(1, 'Kira temerrüdü incelenmiştir.', court_name='Yargıtay')
    danistay = decision(2, 'İdari işlem incelenmiştir.', court_name='Danıştay')
    bam = decision(3, 'Kira temerrüdü incelenmiştir.', court_name='İstanbul Bölge Adliye Mahkemesi')

    result = requested_court_evidence('Yargıtay ve Danıştay kararlarını karşılaştır', [yargitay, danistay, bam])

    assert result == [yargitay, danistay]


def test_relevant_unknown_section_precedes_unrelated_labelled_high_rank_holding():
    unrelated = decision(81, 'HUKUKİ DEĞERLENDİRME Tapu iptal ve tescil talebi incelenmiştir.', rank=9999)
    relevant = decision(82, 'Kira artışı TÜFE üst sınırı bakımından incelenmiştir.', rank=0.01)
    original = [unrelated, relevant]
    assert select_answer_contexts(original, 1, question=QUESTION) == [relevant]
    assert _with_decisions([], original, question=QUESTION) == [relevant, unrelated]
    assert original == [unrelated, relevant]
