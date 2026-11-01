from api.ai.synthesis import _support_failures
from api.ai.term_support import terms_added

_QUESTION = "3 yıldır çalışıyorum, işveren beni çıkardı. Kıdem ve ihbar tazminatını aynı anda alabilir miyim?"
_UNIT_18_21 = ("İşverenin bildirim şartına uymaması veya bildirim süresine ait ücreti peşin ödeyerek sözleşmeyi feshetmesi, "
               "bu Kanunun 18, 19, 20 ve 21 inci maddesi hükümlerinin uygulanmasına engel olmaz.")
_UNIT_PAY = "Bildirim şartına uymayan taraf, bildirim süresine ait ücret tutarında tazminat ödemek zorundadır."
_UNIT_SEVERANCE = "İşçiye çalıştığı her tam yıl için otuz günlük ücreti tutarında kıdem tazminatı ödenir."
_HEADING = "İŞ KANUNU (4857) m. 17 — Süreli fesih"


def test_a_right_the_cited_unit_never_names_is_refused_even_when_the_question_names_it():
    # measured 2026-10-30: approved by the model checker, the cited unit speaks of Articles 18-21 only
    claim = "İşverenin bildirim şartına uymaması, kıdem tazminatı gibi diğer haklarınızın doğmasına engel olmaz."
    assert terms_added(claim, _UNIT_18_21 + "\n" + _HEADING) == ["kıdem"]
    assert "term_added" in _support_failures(claim, _UNIT_18_21, _HEADING, _QUESTION)


def test_the_statutes_own_words_for_a_right_are_accepted():
    # the statute never writes "ihbar": it speaks of the notice period and the pay for it
    claim = "İşveren bildirim şartına uymazsa ihbar tazminatı ödemek zorundadır."
    assert terms_added(claim, _UNIT_PAY) == []
    assert "term_added" not in _support_failures(claim, _UNIT_PAY, _HEADING, _QUESTION)
    assert terms_added("Kıdem tazminatı her tam yıl için otuz günlük ücrettir.", _UNIT_SEVERANCE) == []


def test_a_source_heading_counts_as_naming_the_right():
    assert terms_added("Yoksulluk nafakası süresizdir.", "Boşanma yüzünden yoksulluğa düşen taraf nafaka isteyebilir.",) == []
    assert terms_added("İştirak nafakası gücü oranındadır.", "Gücü oranında katılır.", ) == ["iştirak nafakası"]
    assert terms_added("İştirak nafakası gücü oranındadır.", "Gücü oranında katılır.\nTMK m. 182 — İştirak nafakası") == []


def test_the_opening_conclusion_is_judged_by_the_checker_not_by_this_gate():
    from api.ai.synthesis import _CONCLUSION_HARD
    assert "term_added" not in _CONCLUSION_HARD


def test_time_limit_words_must_come_from_the_source_too():
    assert terms_added("Dava zamanaşımı süresi içinde açılmalıdır.", "Dava bir yıl içinde açılır.") == ["zamanaşımı"]
    assert terms_added("Dava zamanaşımı süresi içinde açılmalıdır.", "Bu hak on yıllık zamanaşımına tabidir.") == []
    assert terms_added("Hak düşürücü süre bir aydır.", "Dava, bir ay içinde açılmazsa hak düşer.") == []
    assert terms_added("Bu alacağa faiz işler.", "Alacak ödenir.") == ["faiz"]
    assert terms_added("Kiracı depozitoyu geri alır.", "Kiracı güvence olarak üç aylık kirayı verir.") == []


def test_the_statutes_own_names_for_job_security_count_as_naming_the_reinstatement_right():
    assert terms_added("İşe iade davası için otuz işçi ve altı ay kıdem gerekir.",
                       "Otuz veya daha fazla işçi çalıştıran işyerlerinde iş güvencesi: en az altı aylık kıdem.") == []
    assert terms_added("İşe iade davası açabilirsiniz.", "Kıdem tazminatı ödenir.") == ["işe iade"]
