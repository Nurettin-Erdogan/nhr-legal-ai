"""The identity rules of the official-article importers: a repeated heading is still one article only when it is unambiguous."""

import importlib.util
from pathlib import Path

from ingestion.mevzuat.identity import article_headings

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("import_missing", ROOT / "scripts" / "import_missing_official_articles.py")
imp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(imp)

REAL = (
    "Madde 17 – (Değişik: 1/1/2000-4444/1 md.)\nBirinci madde metni burada tamamlanır.\n"
    "Madde 18 – (Değişik: 1/1/2000-4444/2 md.)\nİkinci madde metni burada tamamlanır.\n"
    "Madde 19 – Üçüncü madde metni burada tamamlanır.\n"
    "\nYÜRÜRLÜK TABLOSU\nMadde 18 | 1/1/1981 tarihinden geçerli olmak üzere 5/5/1981\nMadde 19 5/5/1981\n"
)


def test_a_heading_repeated_only_in_an_appendix_table_is_still_one_article():
    headings = article_headings(REAL)
    assert imp._unambiguous_repeat(REAL, headings, "18") is True


def test_two_dashed_headings_for_one_identity_stay_ambiguous():
    text = REAL + "Madde 18 – Başka bir madde metni burada yer alır.\nMadde 20 – Son madde.\n"
    assert imp._unambiguous_repeat(text, article_headings(text), "18") is False


def test_an_article_whose_ending_heading_is_not_dashed_is_not_taken():
    # the heading that ends article 19's text is an appendix line, so where its text stops is not certain
    headings = article_headings(REAL)
    assert imp._unambiguous_repeat(REAL, headings, "19") is False


def test_an_identity_that_only_occurs_undashed_is_not_taken():
    text = "Madde 5 | tablo satırı\nMadde 6 – Gerçek madde metni burada.\nMadde 5 | ikinci tablo satırı\n"
    assert imp._unambiguous_repeat(text, article_headings(text), "5") is False
