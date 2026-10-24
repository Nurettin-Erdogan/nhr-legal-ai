from dataclasses import replace
from datetime import date

from api.ai.dialogue import outcome_search_query
from api.ai.event_context import build_event_context, compose_event_answer, source_covers_date
from api.ai.retrieval import question_law_numbers
from tests.factories import legislation_context


FIRST = "ben 10 sene çalıştım ne kadar çıkış parası alırım"
DETAILS = "50000 brüt ücret 12 kasım 2005 13 mart 2016"
LAST = "küçülmeye gittiler çıkardılar"


def modern_source():
    return replace(legislation_context(content="İşçi kıdem tazminatı bakımından bu kurallara tabidir."),
                   law_no="1475", article_no="14", version_date=date(2024,7,10),
                   effective_from=None, effective_to=None)


def context(sources=(), **kwargs):
    return build_event_context(LAST, sources, prior_questions=[FIRST, DETAILS], **kwargs)


def test_exact_three_turn_problem_keeps_facts_but_not_salary_as_a_law_number():
    query = outcome_search_query(LAST, prior_questions=[FIRST, DETAILS])
    assert "kıdem" in query and "ihbar" in query
    assert question_law_numbers(query) == ()
    event = context([modern_source()])
    text = compose_event_answer("", event, generation_failed=True)
    assert "12.11.2005–13.03.2016" in text and "10 yıl 4 ay 1 gün" in text
    assert "brüt ücret 50.000" in text and "50.000 TL" not in text
    assert "13.03.2016 için" in text and "mevzuat sürümü" in text
    assert "İlgili kaynaklar bulundu ancak" not in text
    assert "500.000" not in text and "hak kazandınız" not in text


def test_explicit_reference_is_not_erased_to_normalise_a_salary_word_problem():
    assert outcome_search_query("1475 sayılı kanun madde 14'e göre hesapla", prior_questions=[FIRST,DETAILS]) is None


def test_version_date_is_not_effectiveness_and_interval_is_required():
    source = modern_source()
    assert not source_covers_date(source, date(2016,3,13))
    assert context([source]).historical_basis_missing
    source = replace(source, version_date=date(2010,1,1))
    assert not source_covers_date(source, date(2016,3,13))
    source = replace(source, effective_from=date(2010,1,1), effective_to=date(2018,1,1))
    assert source_covers_date(source,date(2016,3,13))
    assert not context([source]).historical_basis_missing
    assert not source_covers_date(source,date(2019,1,1))


def test_explicit_as_of_is_preserved_not_overwritten_by_collected_event_date():
    event = context([modern_source()], as_of=date(2015,1,1))
    assert event.applicable_on == date(2015,1,1)
    assert event.facts.end_date == date(2016,3,13)
    text = compose_event_answer("", event, generation_failed=True)
    assert "İstenen değerlendirme tarihi 01.01.2015" in text
    assert "12.11.2005–13.03.2016" in text


def test_future_or_unknown_temporal_metadata_is_not_labelled_verified():
    event = context([modern_source()], as_of=date(2030,1,1))
    assert event.historical_basis_missing and not event.payload["historical_applicability_verified"]


def test_a_future_decision_cannot_share_a_verified_historical_interval():
    from tests.factories import court_decision_context
    statute = replace(modern_source(),effective_from=date(2010,1,1),effective_to=date(2018,1,1))
    future_case = replace(court_decision_context(),decision_date=date(2026,1,1))
    assert context([statute,future_case]).historical_basis_missing


def test_current_reference_never_gets_presented_as_the_historical_outcome():
    event = context([modern_source()])
    text = compose_event_answer("Mevcut metindeki genel kural. [K1]", event, legal_reference=True)
    assert "mevcut madde sürümleri" in text and "kesin bir hak veya tutar tespiti değildir" in text
    assert text.endswith("Mevcut metindeki genel kural. [K1]")


def test_reversed_or_missing_dates_cannot_become_a_valid_event_summary():
    assert build_event_context(LAST,[modern_source()],prior_questions=[FIRST,"50000 brüt 13.03.2016 12.11.2005"]) is None


def test_private_document_reader_is_not_replaced_with_generic_event_arithmetic():
    from tests.factories import document_context
    assert context([document_context()]) is None


def test_unknown_historical_context_without_sources_still_has_a_useful_data_status():
    event = context()
    assert event.historical_basis_missing
    text = compose_event_answer("Modelin belirsiz kaynak yok mesajı", event)
    assert "Modelin" not in text and "10 yıl 4 ay 1 gün" in text
