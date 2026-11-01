from ingestion.mevzuat.text_verify import extract_article_text, strip_next_article_caption

PDF = (
    "Madde 18 - Otuz veya daha fazla işçi çalıştıran işyerlerinde fesih için geçerli bir sebep gerekir.\n"
    "a) Sendika üyeliği veya faaliyetlere katılmak.6\n"
    "İşverenin vekilleri hakkında bu madde uygulanmaz.\n"
    "\n"
    "Sözleşmenin feshinde usul\n"
    "Madde 19 - Fesih bildirimi yazılı yapılır ve sebebi açıkça belirtilir.\n"
)


def test_next_article_caption_is_not_part_of_the_previous_article():
    body = extract_article_text(PDF, "18")
    assert body.endswith("uygulanmaz.")
    assert "Sözleşmenin feshinde usul" not in body
    assert "katılmak.6" in body  # dipnot rakamına bu düzeltmede dokunulmaz


def test_last_article_keeps_its_ending_and_the_next_article_is_unaffected():
    assert extract_article_text(PDF, "19").endswith("açıkça belirtilir.")


def test_text_that_merely_lacks_a_final_period_is_never_cut():
    cut_off = "Madde 5 - Bu hüküm şu hallerde uygulanır\nve süresi iki yıldır\nsonuç olarak"
    assert strip_next_article_caption(cut_off) == cut_off


def test_multi_line_caption_is_removed_but_text_before_it_stays():
    body = "Madde 7 - Kurul kararları kesindir.\n\nKurulun görev ve\nyetkileri"
    assert strip_next_article_caption(body) == "Madde 7 - Kurul kararları kesindir."
