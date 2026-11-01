import pytest

from scripts.audit_official_legislation_text import classify


def test_whitespace_only_match_is_explicit_not_a_similarity_threshold():
    assert classify('MADDE 1- Süre otuz gündür.', 'MADDE 1-\nSüre  otuz gündür.') == 'exact_ignoring_whitespace'


@pytest.mark.parametrize('official', [
    'MADDE 1- Süre 31 gündür.',
    'MADDE 1- Ödeme yapılmaz.',
    'MADDE 1- Şart aranmaksızın ödeme yapılır.',
])
def test_changes_in_number_negation_or_condition_cannot_be_marked_exact(official):
    assert classify('MADDE 1- Süre 30 gündür. Ödeme yapılır.', official) == 'text_difference_requires_review'


def test_missing_official_heading_is_not_claimed_to_be_absent_from_the_law():
    assert classify('MADDE 222- Metin.', '') == 'official_heading_absent'


def test_boundary_heading_difference_is_review_not_automatic_false_law():
    assert classify('Amaç\nMADDE 1- Kural uygulanır.', 'MADDE 1- Kural uygulanır.\nTanımlar') == 'text_difference_requires_review'
