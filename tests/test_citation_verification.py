from __future__ import annotations

from api.ai.verification import verify_answer
from tests.factories import court_decision_context, legislation_context

FIRST = court_decision_context()
SECOND = legislation_context()


def test_valid_markers_survive_untouched():
    result = verify_answer("Kıdem tazminatı doğar. [K1]", [FIRST])

    assert result.text == "Kıdem tazminatı doğar. [K1]"
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
