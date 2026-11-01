from api.ai.synthesis import _support_failures


def test_active_and_passive_party_demand_are_the_same_allegation():
    # Kaynak: "talep edilmektedir" (edilgen); cümle: "talep etmiştir" (etken). Taraf talebi eklenmiş sayılmamalı.
    failures = _support_failures("Davacı 160.000 TL kıdem tazminatı talep etmiştir.",
                                 "Kıdem tazminatı 160.000 TL talep edilmektedir.", "")
    assert "allegation_added" not in failures
    assert "allegation_omitted" not in failures


def test_a_demand_the_source_does_not_state_is_still_an_added_allegation():
    failures = _support_failures("Davacı 160.000 TL kıdem tazminatı talep etmiştir.",
                                 "Kıdem tazminatı 160.000 TL tutarındadır.", "")
    assert "allegation_added" in failures
