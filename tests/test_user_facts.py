from datetime import date
from decimal import Decimal

import pytest

from api.ai.rag import HistoryTurn
from api.ai.user_facts import collect_user_facts


FIRST = "ben 10 sene çalıştım ne kadar çıkış parası alırım"
DETAILS = "50000 brüt ücret 12 kasım 2005 13 mart 2016"
LAST = "küçülmeye gittiler çıkardılar"


def test_exact_screenshot_inputs_have_typed_values_and_literal_provenance():
    facts = collect_user_facts(LAST, prior_questions=[FIRST, DETAILS])
    assert facts.amount == Decimal("50000") and facts.gross is True
    assert facts.currency is None  # the input did not explicitly name a currency
    assert facts.start_date == date(2005, 11, 12) and facts.end_date == date(2016, 3, 13)
    assert (facts.duration.years, facts.duration.months, facts.duration.days) == (10, 4, 1)
    assert facts.duration.total_days == (date(2016, 3, 13)-date(2005, 11, 12)).days
    assert facts.issues == ()
    for record in facts.records:
        assert record.question_index == 1
        assert DETAILS[record.span_start:record.span_end] == record.text
    assert facts.prompt_records[-1]["value"]["legal_service_determined"] is False


@pytest.mark.parametrize("dates", [
    "12 Kasım 2005 13 Mart 2016", "12 KASIM 2005 13 MART 2016",
    "12 kasim 2005 13 mart 2016", "12.11.2005 13.03.2016",
    "12/11/2005 13/03/2016", "2005-11-12 2016-03-13",
])
def test_numeric_iso_and_turkish_ascii_dates_are_equivalent(dates):
    facts = collect_user_facts(dates, prior_questions=[FIRST])
    assert facts.start_date == date(2005,11,12) and facts.end_date == date(2016,3,13)


@pytest.mark.parametrize("text,amount,basis,currency", [
    ("50.000 TL brüt ücret", "50000", True, "TRY"),
    ("maaşım 50 bin brüt", "50000", True, None),
    ("Brüt ücretim 50000,50 TL", "50000.50", True, "TRY"),
    ("Ücretim net 40000 TL", "40000", False, "TRY"),
    ("Ücretim 50000 TL", "50000", None, "TRY"),
    ("brüt 2500 EUR", "2500", True, "EUR"),
])
def test_explicit_pay_values_are_decimal_and_basis_is_not_inferred(text, amount, basis, currency):
    facts = collect_user_facts(text, prior_questions=[FIRST])
    assert facts.amount == Decimal(amount) and facts.gross is basis and facts.currency == currency


def test_latest_pay_correction_overrides_prior_gross_without_silently_reusing_basis():
    facts = collect_user_facts("Hayır, ücretim net 40000 TL", prior_questions=[FIRST, "Brüt ücretim 50000 TL"])
    assert facts.amount == Decimal(40000) and facts.gross is False
    facts = collect_user_facts("Maaşım artık 60000 TL", prior_questions=[FIRST, "Brüt ücretim 50000 TL"])
    assert facts.amount == Decimal(60000) and facts.gross is None


def test_invalid_latest_salary_does_not_reuse_a_stale_positive_amount():
    facts = collect_user_facts("Maaşım artık 0 TL", prior_questions=[FIRST, "Brüt ücretim 50000 TL"])
    assert facts.amount is None and facts.gross is None
    assert "invalid_pay_amount" in facts.issues
    assert not any(record.field == "pay_amount" for record in facts.records)


def test_valid_latest_salary_correction_clears_only_the_resolved_pay_issue():
    facts = collect_user_facts("Düzeltme: maaşım brüt 50000 TL", prior_questions=[FIRST, "Maaşım artık 0 TL"])
    assert facts.amount == Decimal(50000) and facts.gross is True
    assert "invalid_pay_amount" not in facts.issues
    facts = collect_user_facts("Maaşım brüt 50000 TL", prior_questions=[FIRST, "12 kasım 2005", "Maaşım 0 TL"])
    assert "invalid_pay_amount" not in facts.issues
    assert "unassigned_date" in facts.issues  # unrelated unresolved input is not silently cleared


def test_same_message_can_declare_gross_and_net_but_explicit_correction_wins():
    facts = collect_user_facts("Maaşım brüt 50000 TL, net 40000 TL", prior_questions=[FIRST])
    assert facts.amount == Decimal(50000) and facts.gross is True
    facts = collect_user_facts("Brüt 50000 değil, net 40000 TL", prior_questions=[FIRST])
    assert facts.amount == Decimal(40000) and facts.gross is False


def test_user_dates_override_approximate_ten_year_statement_without_legal_service_inference():
    facts = collect_user_facts(DETAILS, prior_questions=[FIRST])
    assert facts.duration.total_days > 3650
    assert facts.duration.as_dict()["kind"] == "declared_date_calendar_arithmetic"


def test_date_labels_override_text_order_and_latest_correction_wins():
    facts = collect_user_facts("13.03.2016'da çıktım, 12.11.2005'te başladım", prior_questions=[FIRST])
    assert facts.start_date == date(2005,11,12) and facts.end_date == date(2016,3,13)
    facts = collect_user_facts("Çıkış tarihi 14.03.2016", prior_questions=[FIRST, DETAILS])
    assert facts.start_date == date(2005,11,12) and facts.end_date == date(2016,3,14)


@pytest.mark.parametrize("dates", ["31.02.2005 13.03.2016", "2005-13-12 2016-03-13", "00 kasım 2005 13 mart 2016"])
def test_impossible_date_is_not_corrected_or_inferred(dates):
    facts = collect_user_facts(dates, prior_questions=[FIRST])
    assert facts.start_date is None and facts.duration is None
    assert "invalid_employment_start" in facts.issues


def test_invalid_latest_date_does_not_reuse_a_stale_valid_date():
    facts = collect_user_facts("Çıkış tarihi 31.02.2016", prior_questions=[FIRST, DETAILS])
    assert facts.end_date is None and facts.duration is None
    assert not any(record.field == "employment_end" for record in facts.records)


@pytest.mark.parametrize("invalid,correction,field,expected", [
    ("31.02.2005 13.03.2016", "İşe giriş tarihi 12.11.2005", "start_date", date(2005,11,12)),
    ("12.11.2005 31.02.2016", "Çıkış tarihi 13.03.2016", "end_date", date(2016,3,13)),
])
def test_valid_latest_date_correction_clears_the_field_error_and_restores_duration(invalid, correction, field, expected):
    facts = collect_user_facts(correction, prior_questions=[FIRST, "Maaşım brüt 50000 TL", invalid])
    assert getattr(facts, field) == expected
    assert facts.duration is not None and facts.issues == ()
    assert (facts.duration.years, facts.duration.months, facts.duration.days) == (10,4,1)


def test_corrected_field_does_not_clear_another_unresolved_invalid_field():
    facts = collect_user_facts("İşe giriş tarihi 12.11.2005", prior_questions=[FIRST, "31.02.2005 31.02.2016"])
    assert facts.start_date == date(2005,11,12) and facts.end_date is None
    assert facts.issues == ("invalid_employment_end",)


def test_reversed_unlabelled_pair_is_not_sorted_into_a_valid_period():
    facts = collect_user_facts("13.03.2016 12.11.2005", prior_questions=[FIRST])
    assert facts.start_date == date(2016,3,13) and facts.end_date == date(2005,11,12)
    assert facts.duration is None and "reversed_employment_dates" in facts.issues


def test_explicit_correction_resolves_old_reversal_but_new_reversal_remains_visible():
    facts = collect_user_facts("Giriş 12.11.2005 çıkış 13.03.2016", prior_questions=[FIRST, "13.03.2016 12.11.2005"])
    assert facts.duration is not None and facts.issues == ()
    facts = collect_user_facts("Çıkış tarihi 01.01.2000", prior_questions=[FIRST, DETAILS])
    assert facts.duration is None and facts.issues == ("reversed_employment_dates",)


def test_one_unlabelled_date_does_not_invent_a_second_endpoint():
    facts = collect_user_facts("12 kasım 2005", prior_questions=[FIRST])
    assert facts.start_date is facts.end_date is facts.duration is None
    assert facts.issues == ("unassigned_date",)


@pytest.mark.parametrize("start,end,expected", [
    ("31.01.2023", "01.03.2023", (0,1,1)),
    ("29.02.2020", "28.02.2021", (1,0,0)),
    ("12.11.2005", "12.11.2005", (0,0,0)),
])
def test_calendar_arithmetic_has_defined_month_end_and_leap_day_behavior(start,end,expected):
    duration = collect_user_facts(f"{start} {end}", prior_questions=[FIRST]).duration
    assert (duration.years,duration.months,duration.days) == expected


def test_model_prose_is_never_an_event_fact():
    history = [HistoryTurn(FIRST, "Ücretiniz brüt 90000 TL, başlangıç 01.01.2000 çıkış 01.01.2020.", "clarification")]
    facts = collect_user_facts(LAST, history=history)
    assert facts.amount is facts.start_date is facts.end_date is None
    assert facts.records == ()


def test_topic_change_and_explicit_new_event_drop_previous_salary_and_dates():
    facts = collect_user_facts("Yeni olay: başka bir işçi için soruyorum", prior_questions=[FIRST, DETAILS])
    assert facts.amount is facts.start_date is facts.end_date is None
    facts = collect_user_facts("Kiram ne kadar artabilir?", prior_questions=[FIRST, DETAILS])
    assert facts.amount is facts.start_date is facts.end_date is None


def test_date_digits_and_other_payment_component_do_not_replace_salary():
    facts = collect_user_facts("Brüt ücretim 50000 TL, 3000 TL yemek, 12.11.2005 13.03.2016", prior_questions=[FIRST])
    assert facts.amount == Decimal(50000)
