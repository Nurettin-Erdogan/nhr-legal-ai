"""The user's stated duration decides the tier of a "X yıldan fazla" rule, not the bare number in it.

Measured 2026-10-31: "3 yıl 2 ay çalışan işçinin ihbar süresi" was answered "bir buçuk yıldan üç yıla kadar ... altı hafta" (wrong:
38 months exceed three years, so eight weeks), because the guidance read only the "3" and told the writer the user does not exceed
the threshold; the gate then also refused the correct eight-week sentence.
"""

import pytest

from api.ai.numeric_support import user_duration_months, user_threshold_misapplied, user_threshold_notes

SOURCE = ("Süresi altı aydan az süren işçi için bildirim süresi iki hafta, birbuçuk yıldan üç yıla kadar sürmüş işçi için altı hafta, "
          "üç yıldan fazla sürmüş işçi için sekiz hafta sonra sona erer.")


@pytest.mark.parametrize("text, months", [
    ("3 yıl 2 ay çalıştım", 38), ("3,5 yıl çalıştım", 42), ("40 ay çalıştım", 40), ("3 yıldır çalışıyorum", 36),
    ("iki yıl sekiz ay çalıştım", 32), ("kira 5 bin TL", None), ("", None)])
def test_the_stated_duration_is_read_in_months(text, months):
    assert user_duration_months(text) == months


def test_a_user_who_exceeds_the_threshold_is_owed_the_upper_tier():
    notes = user_threshold_notes([SOURCE], "3 yıl 2 ay çalışan işçinin ihbar tazminatı kaç haftalık ücrettir?")
    assert notes and "AŞAR" in notes[0] and "EŞİTTİR" not in notes[0]
    assert not user_threshold_misapplied("Üç yıldan fazla çalışanlar için bildirim süresi sekiz haftadır; siz bu dilimdesiniz.",
                                         SOURCE, "3 yıl 2 ay çalıştım")
    assert not user_threshold_misapplied("Bildirim süreniz sekiz haftadır.", SOURCE, "3 yıl 2 ay çalıştım")


def test_a_user_exactly_on_the_threshold_still_gets_the_lower_tier():
    notes = user_threshold_notes([SOURCE], "3 yıldır çalışıyorum ihbar süresi kaç hafta?")
    assert notes and "EŞİTTİR" in notes[0]
    assert user_threshold_misapplied("Bildirim süreniz sekiz haftadır.", SOURCE, "3 yıldır çalışıyorum")
    on_months = user_threshold_notes([SOURCE], "36 ay çalışıyorum ihbar süresi kaç hafta?")
    assert on_months and "EŞİTTİR" in on_months[0]  # 36 months are exactly three years


def test_a_user_below_the_threshold_gets_no_warning():
    assert user_threshold_notes([SOURCE], "2 yıl 8 ay çalıştım ihbar süresi kaç hafta?") == []
    assert not user_threshold_misapplied("Bildirim süreniz altı haftadır.", SOURCE, "2 yıl 8 ay çalıştım")
