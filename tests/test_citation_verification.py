from __future__ import annotations

from api.ai.verification import verify_answer
from tests.factories import court_decision_context, legislation_context

FIRST = court_decision_context()
SECOND = legislation_context()


def test_valid_markers_survive_untouched():
    result = verify_answer(f"{FIRST.content} [K1]", [FIRST])

    assert result.text == f"{FIRST.content} [K1]"
    assert result.contexts == (FIRST,)
    assert result.unverified_markers == ()
    assert result.grounded


def test_marker_beyond_retrieved_sources_is_removed():
    result = verify_answer("İlk dayanak [K1] ikinci dayanak [K7].", [FIRST])

    assert "[K7]" not in result.text
    assert result.text == "İlk dayanak [K1] ikinci dayanak."
    assert result.unverified_markers == ("K7",)
    assert result.contexts == (FIRST,)


def test_uncited_sources_are_not_reported_as_citations():
    result = verify_answer("Yalnızca ikinci kaynağa dayanıyorum. [K2]", [FIRST, SECOND])

    assert result.contexts == (SECOND,)
    assert result.text.endswith("[K1]"), "cited source should be renumbered to K1"


def test_markers_are_renumbered_in_order_of_first_appearance():
    result = verify_answer("Önce [K2], sonra [K1], tekrar [K2].", [FIRST, SECOND])

    assert result.text == "Önce [K1], sonra [K2], tekrar [K1]."
    assert result.contexts == (SECOND, FIRST)


def test_answer_without_any_marker_is_not_grounded():
    result = verify_answer("Kaynaklarda bu konuda yeterli bilgi bulunmuyor.", [FIRST])

    assert not result.grounded
    assert result.contexts == ()
    assert result.unverified_markers == ()


def test_answer_citing_only_invalid_markers_is_not_grounded():
    result = verify_answer("Karar şöyledir [K4].", [FIRST])

    assert not result.grounded
    assert result.contexts == ()
    assert result.unverified_markers == ("K4",)


def test_lowercase_and_spaced_markers_are_accepted():
    result = verify_answer(f"{FIRST.content} [k1]\n{SECOND.content} [ K2 ]", [FIRST, SECOND])

    assert result.grounded
    assert result.text == f"{FIRST.content} [K1]\n{SECOND.content} [K2]"
    assert result.contexts == (FIRST, SECOND)


def test_insufficient_source_reply_is_detected():
    from api.ai.verification import is_insufficient_source_reply

    assert is_insufficient_source_reply("Kaynaklarda bu konuda yeterli bilgi bulunmuyor.")
    assert not is_insufficient_source_reply("Kıdem tazminatı bir yıl sonra doğar.")
    assert not is_insufficient_source_reply("Kaynak yetersiz. [K1]")


def test_explicit_source_insufficiency_explanation_is_detected():
    from api.ai.verification import is_insufficient_source_reply

    answer = (
        "Kıdem tazminatına hak kazanmanın şartları hukuki bir konudur. "
        "Ancak, verilen kaynaklarla doğrudan ilişkilendirilebilecek bir hüküm "
        "bulunmamaktadır. Bilgilerin eksikliği nedeniyle daha kapsamlı bir cevap "
        "vermek mümkün değildir."
    )

    assert is_insufficient_source_reply(answer)


def test_answer_with_an_uncited_claim_is_not_grounded():
    result = verify_answer(
        f"{FIRST.content} [K1] İşveren ödeme yapar.",
        [FIRST],
    )

    assert not result.grounded
    assert result.contexts == (FIRST,)
    assert result.unsupported_claims == ("İşveren ödeme yapar.",)


def test_answer_with_cjk_text_is_not_grounded():
    result = verify_answer("Kıdem koşulu uygulanır. 相关规定 [K1]", [FIRST])

    assert not result.grounded
    assert result.foreign_script_detected
    assert result.contexts == (FIRST,)


def test_numeric_claim_missing_from_cited_source_is_not_grounded():
    result = verify_answer(
        "Kıdem tazminatı 30 gün içinde talep edilmelidir. [K1]",
        [FIRST],
    )

    assert not result.grounded
    assert len(result.unsupported_claims) == 1
    assert "30 gün" in result.unsupported_claims[0]


def test_numeric_claim_present_in_source_remains_grounded():
    source = court_decision_context(content="Başvuru süresi 30 gündür.")

    result = verify_answer("Başvuru süresi 30 gündür. [K1]", [source])

    assert result.grounded
