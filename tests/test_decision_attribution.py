from dataclasses import replace

from api.ai.decision_attribution import court_holding_misattributed, decision_section_priority
from api.ai.synthesis import synthesize_answer
from tests.factories import court_decision_context
from tests.test_synthesis import Provider, approved, draft


def context(text):
    return replace(court_decision_context(content=text), court_name="Yargıtay")


def test_catalogue_court_cannot_own_lower_court_reasoning():
    quote = "Kiracı tarafından kira artış oranının kabul edildiği belirtilmiştir."
    source = context("İLK DERECE MAHKEMESİ KARARI " + quote)
    claim = "Yargıtay kira artış oranının kabul edildiğini belirtmiştir."
    assert court_holding_misattributed(claim, [(1, quote)], [source])
    writer, checker = Provider(draft(claim, (1, quote))), Provider(approved())
    diagnostics = {}
    assert synthesize_answer(writer, checker_provider=checker, question="Kira artışına dair karar?",
        contexts=[source], diagnostics=diagnostics, repair_attempts=0) is None
    assert not checker.calls  # even an always-approving checker cannot bypass it


def test_nested_text_does_not_become_holding_when_quoted_without_its_heading():
    quote = "Başvuru süresi tebliğden başlar."
    for heading in ("BÖLGE ADLİYE MAHKEMESİ KARARI", "DAVACININ İDDİASI", "DAVALININ SAVUNMASI"):
        assert court_holding_misattributed("Yargıtay başvuru süresinin tebliğden başladığına karar vermiştir.",
            [(1, quote)], [context(heading + " " + quote)])


def test_explicit_review_section_can_support_the_catalogue_court():
    old, holding = "İlk karar uygun bulunmuştur.", "Başvuru süresi tebliğden başlar."
    source = context("İLK DERECE MAHKEMESİ KARARI " + old + "\nTEMYİZ İNCELEMESİ\n" + holding)
    assert not court_holding_misattributed("Yargıtay başvuru süresinin tebliğden başladığına karar vermiştir.",
        [(1, holding)], [source])


def test_neutral_account_of_lower_court_is_not_an_upper_court_holding():
    quote = "Başvuru süresi tebliğden başlar."
    assert not court_holding_misattributed("İlk derece mahkemesi başvuru süresini değerlendirmiştir.",
        [(1, quote)], [context("İLK DERECE MAHKEMESİ KARARI " + quote)])


def test_multiline_evidence_is_resolved_to_its_actual_review_section():
    source = context("İLK DERECE MAHKEMESİ KARARI Önceki karar verilmiştir.\n"
                     "TEMYİZ İNCELEMESİ\nBaşvuru süresi tebliğden başlar.\nKarar bu nedenle bozulmuştur.")
    assert not court_holding_misattributed("Yargıtay kararın bozulmasına karar vermiştir.",
        [(1, "Başvuru süresi tebliğden başlar. Karar bu nedenle bozulmuştur.")], [source])


def test_observed_plural_party_heading_is_not_a_court_holding():
    quote = 'Kira artışının tüketici fiyat endeksini aşamayacağı ileri sürülmektedir.'
    source = context('DAVACININ İDDİALARI : ' + quote)
    assert decision_section_priority(source, 'kira zammı') == 3
    assert court_holding_misattributed('Yargıtay kira artışını değerlendirmiş ve belirtmiştir.',
                                      [(1, quote)], [source])


def test_priority_does_not_certify_unlabelled_text():
    assert decision_section_priority(context('Kira artışı değerlendirilmiştir.'), 'kira zammı') == 1


def test_mixed_chunk_uses_relevant_section_not_an_unrelated_holding():
    source = context('DAVACININ İDDİALARI Kira artışı TÜFE ile sınırlıdır.\n'
                     'HUKUKİ DEĞERLENDİRME Başvuru harcı yatırılmalıdır.')
    assert decision_section_priority(source, 'kira zammı') == 3
    source = context('DAVACININ İDDİALARI Kira artışı TÜFE ile sınırlıdır.\n'
                     'HUKUKİ DEĞERLENDİRME Kira artışı yönünden karar incelenmiştir.')
    assert decision_section_priority(source, 'kira zammı') == 0


def test_lower_court_section_is_not_catalogue_court_reasoning():
    assert decision_section_priority(context('İLK DERECE MAHKEMESİ KARARI Kira artışı incelenmiştir.'),
                                     'kira zammı') == 2


def test_plural_defence_is_nested():
    quote = 'Kira artışı sözleşmeye uygundur.'
    source = context('DAVALININ SAVUNMALARI ' + quote)
    assert decision_section_priority(source, 'kira zammı') == 3
    assert court_holding_misattributed('Yargıtay kira artışının sözleşmeye uygun olduğunu belirtmiştir.',
                                      [(1, quote)], [source])
