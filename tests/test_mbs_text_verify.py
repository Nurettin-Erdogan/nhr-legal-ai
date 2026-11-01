from __future__ import annotations

from ingestion.mevzuat.text_verify import (
    extract_article_text,
    verify_article_text,
)


def test_extract_article_stops_at_next_heading():
    text = "Başlık\nMadde 14 - " + ("kıdem tazminatı şartı " * 20) + "\nMadde 15 - Sonraki"

    article = extract_article_text(text, "14")

    assert article.startswith("Madde 14")
    assert "Madde 15" not in article


def test_article_verification_tolerates_footnotes_and_layout_only():
    body = "İşçinin kıdem tazminatına hak kazanması için kanuni koşullar uygulanır. " * 8
    seed = f"Kıdem tazminatı:\nMadde 14 - {body}[2]"
    official = f"KANUN\nMadde 14 -\n{body}\n2 22/5/2003 tarihli dipnot\nMadde 15 - Başka hüküm"

    result = verify_article_text(seed, official, article_no="14")

    assert result.verified
    assert result.ratio >= 0.93


def test_article_verification_rejects_different_or_short_text():
    official = "Madde 14 - " + ("resmî ve tamamen farklı hüküm " * 15) + "\nMadde 15 - x"

    different = verify_article_text(
        "Madde 14 - " + ("uyuşmayan başka içerik " * 15),
        official,
        article_no="14",
    )
    short = verify_article_text("Madde 14 - kısa", official, article_no="14")

    assert not different.verified
    assert not short.verified


def test_extract_article_returns_empty_for_missing_article():
    assert extract_article_text("Madde 2 - Metin", "14") == ""
