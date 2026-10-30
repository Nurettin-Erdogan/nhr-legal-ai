import pytest
from scripts.quarantine_legislation_identity_errors import mismatch


@pytest.mark.parametrize('article,text,expected', [
    ('18', 'MADDE 18/A- Metin.', True),
    ('18/A', 'MADDE 18/A- Metin.', False),
    ('3', 'GEÇİCİ MADDE 1- Metin.', True),
    ('3', 'Bu Kanunun 18/A maddesine göre işlem yapılır.', False),
    ('3', 'x'*301 + '\nMADDE 18/A- Uzak alıntı.', False),
])
def test_only_recognized_near_start_identity_conflicts_are_quarantined(article,text,expected):
    assert mismatch(article,text) is expected
