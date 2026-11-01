import pytest

from scripts.audit_legislation_integrity import HEADING, heading_identity, stored_identity


@pytest.mark.parametrize("text,expected", [
    ("MADDE 80[1] (1) Açıklama\n\nEK MADDE 1- Diğer hüküm", "80"),
    ("Başlık\n\nMADDE 18/A- (1) Metin", "18/A"),
    ("Geçici Madde 1- (1) Metin", "GEÇİCİ 1"),
    ("EK MADDE 2 – (1) Metin", "EK 2"),
    ("MADDE 25A – Metin", "25A"),
])
def test_corpus_audit_recognizes_distinct_article_identities(text, expected):
    match = HEADING.search(text)
    assert match is not None
    assert heading_identity(*match.groups()) == expected


def test_embedded_cross_reference_is_not_a_heading():
    assert not HEADING.search("Bu Kanunun 18/B maddesinin hükümleri uygulanır.")
    assert stored_identity("Geçici Madde 1") == "GEÇİCİ 1"
    assert stored_identity("18 / A") == "18/A"
