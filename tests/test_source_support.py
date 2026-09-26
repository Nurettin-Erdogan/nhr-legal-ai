from dataclasses import replace

import pytest

from api.ai.verification import verify_answer
from tests.factories import court_decision_context


@pytest.mark.parametrize("claim", [
    "Bu olayda talep kabul edilmelidir.",
    "Bu olayda talep reddedilmemelidir.",
    "Talep reddedilmelidir.",  # condition/scope removed
    "Bu olayda talep reddedilmelidir. Ücret ödenmelidir.",
])
def test_citation_cannot_launder_contradiction_or_added_claim(claim):
    source = court_decision_context(content="Bu olayda talep reddedilmelidir.")
    assert not verify_answer(f"{claim} [K1]", [source]).grounded


def test_exact_sentence_survives_whitespace_and_quotes():
    source = court_decision_context(content="Bu olayda\n talep reddedilmelidir.")
    assert verify_answer('“Bu olayda talep reddedilmelidir.” [K1]', [source]).grounded


def test_all_cited_sources_must_support_sentence():
    sources = [
        court_decision_context(content="Bu olayda talep reddedilmelidir."),
        court_decision_context(content="İşveren ücret ödemelidir."),
    ]
    assert not verify_answer("Bu olayda talep reddedilmelidir. [K1] [K2]", sources).grounded
    assert verify_answer("Bu olayda talep reddedilmelidir. [K1]\nİşveren ücret ödemelidir. [K2]", sources).grounded


def test_uninvented_number_is_not_enough_and_metadata_is_not_evidence():
    source = court_decision_context(content="Başvuru süresi 30 gündür.")
    assert not verify_answer("Başvuru 30 yıl sonra yapılabilir. [K1]", [source]).grounded
    source = replace(source, title="Talep kabul edilmelidir.")
    assert not verify_answer("Talep kabul edilmelidir. [K1]", [source]).grounded


def test_abbreviation_does_not_drop_condition():
    source = court_decision_context(content="Kanun m. 25 uygulanırsa talep reddedilmelidir.")
    assert verify_answer(f"{source.content} [K1]", [source]).grounded
    assert not verify_answer("25 uygulanırsa talep reddedilmelidir. [K1]", [source]).grounded


def test_truncated_source_tail_cannot_support_completed_claim():
    source = court_decision_context(content="Talep kabul edilebilir, ancak")
    assert not verify_answer("Talep kabul edilebilir. [K1]", [source]).grounded
    assert not verify_answer("Talep kabul edilebilir, ancak [K1]", [source]).grounded


def test_invalid_marker_is_not_silently_approved():
    source = court_decision_context()
    result = verify_answer(f"{source.content} [K1] [K99]", [source])
    assert not result.grounded
    assert result.unverified_markers == ("K99",)


def test_source_matching_does_not_promote_third_party():
    source = replace(court_decision_context(), verification="third_party")
    result = verify_answer(f"{source.content} [K1]", [source])
    assert result.grounded
    assert result.contexts[0].verification == "third_party"
