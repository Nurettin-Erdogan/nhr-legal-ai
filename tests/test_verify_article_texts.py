from scripts.verify_article_texts import pdf_url_for, without_leading_caption


def test_portal_page_url_maps_to_the_official_pdf_pattern():
    assert pdf_url_for("https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=633&MevzuatTur=4&MevzuatTertip=5") == (
        "4", "https://www.mevzuat.gov.tr/MevzuatMetin/4.5.633.pdf")
    assert pdf_url_for("https://www.mevzuat.gov.tr/MevzuatMetin/20.5.4876.pdf") == (
        "20", "https://www.mevzuat.gov.tr/MevzuatMetin/20.5.4876.pdf")


def test_unusable_or_foreign_urls_are_rejected():
    assert pdf_url_for("https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=abc&MevzuatTur=4&MevzuatTertip=5") is None
    assert pdf_url_for("https://www.mevzuat.gov.tr/baska") is None


def test_leading_article_caption_is_dropped_only_before_a_madde_line():
    assert without_leading_caption("İşletme müdürünün nitelikleri\n\nMADDE 33 – Metin.") == "MADDE 33 – Metin."
    assert without_leading_caption("MADDE 33 – Metin.\n\nİkinci paragraf.") == "MADDE 33 – Metin.\n\nİkinci paragraf."
    assert without_leading_caption("Amaç\n\nGEÇİCİ MADDE 1 – Metin.") == "GEÇİCİ MADDE 1 – Metin."


def test_difference_categories_never_grant_proof_for_near_but_not_exact_text():
    from scripts.verify_article_texts import classify_difference

    stored = "madde5kiracıdairesinitahliyeetmekzorundadırkiracı30günicindeödeyecektir" * 4
    assert classify_difference(stored, "sayfa12" + stored + "sonrakibaslik") == "stored_in_official"
    assert classify_difference("tabloekicerik" + stored + "tablo2", stored) == "official_in_stored"
    changed = stored.replace("30gün", "15gün", 1)  # tek rakam farkı: birebir değil, kanıt yazılmamalı
    assert classify_difference(changed, stored) in ("near_stored", "near_official")
    assert classify_difference(stored, "tamamenbaskametinvehukumyazisi" * 20) == "different"
