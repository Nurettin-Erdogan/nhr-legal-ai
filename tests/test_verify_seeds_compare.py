"""Üçüncü taraf karar metninin resmî metinle karşılaştırılması: tek harf ya da rakam farkı doğrulanmaz.

Kural gerçek portal ölçümüne dayanır (2026-10-07): "uyuşmayan" 24 kararın 23'ünde fark yalnız derlemede düşmüş birkaç işaretti,
1'inde derleme resmî metnin kesintisiz parçasıydı; hiçbirinde farklı sözcük/rakam yoktu.
"""

from __future__ import annotations

from scripts import verify_seeds
from scripts.verify_seeds import compare_texts

OFFICIAL = (
    "T.C. YARGITAY 9. Hukuk Dairesi Esas No: 2024/1234 Karar No: 2025/5678\n"
    "Davacı vekili, müvekkilinin iş sözleşmesinin \"haklı neden\" olmadan feshedildiğini; 12.345,67 TL kıdem tazminatı talep etmiştir. "
    "Mahkemece davanın KABULÜNE karar verilmiştir. " * 12
)


def check(seed, official=OFFICIAL):
    return compare_texts(seed, official, official)


def test_whitespace_only_difference_is_verified_as_before():
    seed = OFFICIAL.replace("\n", "  ").replace(". ", ".\n")
    assert check(seed) == ("verified", "text_equal_ignoring_whitespace")


def test_dropped_punctuation_is_verified_but_labelled():
    seed = OFFICIAL.replace('"', "").replace(";", "")
    assert check(seed) == ("verified", "text_equal_ignoring_punctuation")


def test_a_single_different_digit_or_letter_is_never_verified():
    assert check(OFFICIAL.replace("2025/5678", "2025/5679")) == ("mismatch", "")  # karar numarası
    assert check(OFFICIAL.replace("12.345,67", "12.345,68")) == ("mismatch", "")  # tutar
    assert check(OFFICIAL.replace("KABULÜNE", "REDDİNE")) == ("mismatch", "")  # hüküm
    assert check(OFFICIAL.replace("haklı neden", "geçerli neden")) == ("mismatch", "")
    # Noktalama yok sayılsa da rakamların SIRASI korunmalı: ondalık ayırıcıyı kaydırmak rakamları değiştirmez ama
    # eksik/fazla rakam yakalanır.
    assert check(OFFICIAL.replace("12.345,67", "12.345,6")) == ("mismatch", "")


def test_a_contiguous_part_of_the_official_text_is_verified_as_part_and_short_fragments_are_not():
    part = OFFICIAL[: len(OFFICIAL) // 2]
    assert check(part) == ("verified", "seed_is_part_of_official_text")  # eksik metin: resmî TAM metin yazılır
    short = "Mahkemece davanın KABULÜNE karar verilmiştir."
    assert len(verify_seeds._alnum(short)) < verify_seeds.MIN_PART_CHARS
    assert check(short) == ("mismatch", "")  # kısa ortak kalıp eşleşme sayılmaz
    # Parça içinde tek harf farkı varsa parça sayılmaz.
    assert check(part.replace("KABULÜNE", "REDDİNE", 1)) == ("mismatch", "")


def test_seed_with_extra_text_or_an_empty_seed_is_a_mismatch():
    assert check(OFFICIAL + " Ek açıklama: bu karar bozulmuştur.") == ("mismatch", "")
    assert check("") == ("mismatch", "")
    assert check("...,,,;;;") == ("mismatch", "")  # harf/rakam içermeyen metin hiçbir şeyle eşleşmez


def test_third_party_cleaned_official_variant_is_also_compared():
    stripped = OFFICIAL.replace("T.C. YARGITAY ", "")
    assert compare_texts(stripped, OFFICIAL, stripped) == ("verified", "text_equal_ignoring_whitespace")
