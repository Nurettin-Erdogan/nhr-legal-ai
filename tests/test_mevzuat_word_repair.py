from collections import Counter

from ingestion.mevzuat.word_repair import build_vocabulary, only_spaces_removed, rejoin_split_words

CORPUS = [
    "kanunun maddesi tarafından belirlenen ödenen vergi " * 3,
    "Kanunun 62 nci maddesi tarafından ödenen vergi hükümleri ve numarası " * 3,
    "dolayısıyla bu hüküm uygulanır ve olan numarası belirtilir " * 6,
]
VOCAB = build_vocabulary(CORPUS)


def test_obvious_splits_are_rejoined_and_only_a_space_goes():
    text = "7072 sayılı Kanu nun 62 nci maddesi tarafı ndan ödene n vergi, dolayısı yla bu hüküm"
    fixed, joins = rejoin_split_words(text, VOCAB)
    assert fixed == "7072 sayılı Kanunun 62 nci maddesi tarafından ödenen vergi, dolayısıyla bu hüküm"
    assert [(j.left, j.fragment) for j in joins if j.kind == "suffix"] == [("Kanu", "nun"), ("tarafı", "ndan"), ("ödene", "n"), ("dolayısı", "yla")]
    assert only_spaces_removed(text, fixed)


def test_unknown_result_word_is_not_guessed():
    text = "kadarı dır ve ulaşımı nın güvenliği"
    assert rejoin_split_words(text, VOCAB)[0] == text


def test_fragment_that_belongs_to_the_next_word_is_left_alone():
    text = "fıkranın olan n umarası belirtilir"
    assert rejoin_split_words(text, Counter({"olann": 99, "umarası": 0}))[0] == text


def test_acronyms_and_real_words_are_untouched():
    text = "su ürünleri ve PTT nin işletme tür ve nitelik"
    assert rejoin_split_words(text, VOCAB)[0] == text


def test_text_without_splits_is_returned_unchanged():
    text = "Bu Kanun yayımı tarihinde yürürlüğe girer."
    assert rejoin_split_words(text, VOCAB) == (text, [])


def test_fragment_that_belongs_to_the_right_hand_word_joins_right():
    vocab = build_vocabulary(["sırasına alfabe sırasına nerede her nerede olursa selam dur komutu " * 6])
    text = "alfabe sı rasına göre, her n erede olursa; selam dur komutu"
    fixed, joins = rejoin_split_words(text, vocab)
    assert fixed == "alfabe sırasına göre, her nerede olursa; selam dur komutu"
    assert [j.kind for j in joins] == ["prefix", "prefix"]
    assert only_spaces_removed(text, fixed)
