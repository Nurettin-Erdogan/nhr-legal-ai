"""Offline regressions from the saved assistant evaluation, plus unsafe variants."""
import pytest

from api.ai.numeric_support import numeric_claims_supported
from api.ai.synthesis import _support_failures


@pytest.mark.parametrize("word,number", [("dörder", 4), ("ikişer", 2), ("üçer", 3)])
def test_distributive_duration(word, number):
    source = f"İzin süreleri {word} gün artırılır."
    assert numeric_claims_supported(f"İzin süresi {number} gün artırılır.", source)
    assert not numeric_claims_supported(f"İzin süresi {number + 1} gün artırılır.", source)
    assert not numeric_claims_supported(f"İzin süresi {number} ay artırılır.", source)


def test_equivalent_minimum_not_added():
    failures = _support_failures("En az 14 gün izin verilir.", "İzin süresi ondört günden az olamaz.", "")
    assert "minimum_added" not in failures
    assert "number_or_unit" not in failures
    assert "minimum_added" in _support_failures("En az 14 gün izin verilir.", "İzin süresi ondört gündür.", "")


def test_locative_coordinated_duration_unit():
    source = "İdare mahkemelerinde altmış ve vergi mahkemelerinde otuz gündür."
    assert numeric_claims_supported("Süre 60 gündür.", source)
    assert not numeric_claims_supported("Süre 60 aydır.", source)
    assert not numeric_claims_supported("Süre 61 gündür.", source)
    assert not numeric_claims_supported("60 gün", "60 TL ve vergi mahkemelerinde 30 gündür.")
    assert not numeric_claims_supported("60 gün", "60. Vergi mahkemelerinde 30 gündür.")


def test_quantified_pdf_split_year_unit_preserves_original_numbers():
    source = "İtirazın tebliği tarihinden itibaren bir sen e içinde mahkemeye başvurabilir."
    assert numeric_claims_supported("Bir yıl içinde başvurabilir.", source)
    assert numeric_claims_supported("Bir yıllık süre", source)
    assert not numeric_claims_supported("İki yıl içinde", source)
    assert not numeric_claims_supported("Bir ay içinde", source)
    assert not numeric_claims_supported("Bir yıl içinde", "Bir senet içinde borç ikrarı bulunur.")


def test_age_boundary_cannot_drop_the_included_birthday():
    from api.ai.numeric_support import boundaries_supported
    inclusive = 'Onsekiz ve daha küçük yaştaki işçilere izin verilir.'
    exclusive = '18 yaşını doldurmamış işçilere izin verilir.'
    assert not boundaries_supported(exclusive, inclusive)
    assert not boundaries_supported(inclusive, exclusive)
    assert boundaries_supported('18 yaş ve altındaki işçilere izin verilir.', inclusive)
    assert 'boundary_changed' in _support_failures(exclusive, inclusive, '')


_NOTICE_TIERS = ("Bildirim süreleri: altı aya kadar sürmüş işçi için iki hafta; altı aydan birbuçuk yıla kadar sürmüş işçi için dört hafta; "
                 "birbuçuk yıldan üç yıla kadar sürmüş işçi için altı hafta; üç yıldan fazla sürmüş işçi için sekiz hafta sonra feshedilmiş sayılır.")
_USER_THREE_YEARS = "3 yıldır aynı işyerinde çalışıyorum. İşveren beni işten çıkardı. İhbar tazminatı alabilir miyim?"


def test_tier_above_the_users_own_threshold_is_not_applied_to_them():
    claim = "İşveren size kanuni sekiz haftalık bildirim süresine uyarak haber verirse ihbar tazminatı doğmaz."
    assert 'boundary_changed' in _support_failures(claim, _NOTICE_TIERS, '', _USER_THREE_YEARS)


def test_general_statement_naming_the_threshold_and_the_lower_tier_stay_allowed():
    assert 'boundary_changed' not in _support_failures(
        "Üç yıldan fazla çalışan işçiler için bildirim süresi sekiz haftadır.", _NOTICE_TIERS, '', _USER_THREE_YEARS)
    assert 'boundary_changed' not in _support_failures(
        "Üç yıla kadar çalışmış işçi için bildirim süresi altı haftadır.", _NOTICE_TIERS, '', _USER_THREE_YEARS)


def test_deictic_two_is_not_a_numeric_claim_but_a_unit_after_it_is():
    source = "Kıdem tazminatı ve ihbar tazminatı farklı sebeplerle doğar ve birbirinin alınmasına engel değildir."
    assert 'number_or_unit' not in _support_failures(
        "Bu iki tazminat farklı sebeplerle doğar ve birbirinin alınmasına engel değildir.", source, '')
    assert 'number_or_unit' in _support_failures("Her iki yıl sonunda ödeme yapılır.", source, '')


def test_users_own_number_inside_the_sentence_does_not_excuse_the_tier_above_it():
    # measured 2026-10-30: "Üç yıldır çalıştığınız için ... sekiz haftadır" passed because the sentence itself said "üç"
    source = _NOTICE_TIERS.replace("; ", ", ")
    assert 'boundary_changed' in _support_failures(
        "Üç yıldır çalıştığınız için, size yapılması gereken bildirim süresi sekiz haftadır.", source, '', _USER_THREE_YEARS)
    assert 'boundary_changed' not in _support_failures(
        "Üç yıldır çalıştığınız için bildirim süreniz altı haftadır.", source, '', _USER_THREE_YEARS)
    assert 'boundary_changed' not in _support_failures(
        "Altı aydan az çalışan işçi için bildirim süresi iki haftadır.", source, '', _USER_THREE_YEARS)


def test_writer_is_warned_when_the_users_number_sits_on_a_source_threshold():
    from api.ai.numeric_support import user_threshold_notes
    notes = user_threshold_notes([_NOTICE_TIERS], _USER_THREE_YEARS)
    assert len(notes) == 1 and "3 yıldan fazla" in notes[0]
    assert user_threshold_notes([_NOTICE_TIERS], "5 yıldır çalışıyorum") == []
    assert user_threshold_notes([_NOTICE_TIERS], "") == []


def test_iş_günü_is_one_unit_whether_the_statute_writes_it_in_one_word_or_two():
    from api.ai.numeric_support import numeric_claims_supported
    assert numeric_claims_supported("On iş günü içinde işverene başvurmalısınız.", "On işgünü içinde işverene başvurur.")
    assert numeric_claims_supported("On işgünü içinde başvurur.", "On iş günü içinde başvurur.")
    # a plain "gün" is still not an "iş günü"
    assert not numeric_claims_supported("On iş günü içinde başvurur.", "On gün içinde başvurur.")
