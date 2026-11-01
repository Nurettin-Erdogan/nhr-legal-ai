from datetime import date

import pytest

from ingestion.yargitay.parser import (
    build_external_id,
    parse_chamber,
    parse_decision,
    parse_decision_date,
    parse_decision_no,
    parse_docket_no,
    tr_casefold,
)

HEADER_SUFFIX_FORM = "9. Hukuk Dairesi         2019/1234 E.  ,  2021/5678 K.  12.05.2021"

BODY_LABELED_FORM = """
YARGITAY
9. HUKUK DAİRESİ

ESAS NO : 2019/1234
KARAR NO : 2021/5678
KARAR TARİHİ : 12.05.2021

MAHKEMESİ : İş Mahkemesi

Davacı vekili dava dilekçesinde özetle kıdem tazminatı talep etmiştir.
"""


def test_tr_casefold_handles_dotted_capital_i():
    assert tr_casefold("KARAR TARİHİ") == "karar tarihi"
    assert tr_casefold("ISPAT") == "ıspat"


@pytest.mark.parametrize(
    "text",
    [
        HEADER_SUFFIX_FORM,
        BODY_LABELED_FORM,
        "Esas No: 2019/1234",
        "esas no 2019 / 1234",
    ],
)
def test_parse_docket_no_handles_common_forms(text):
    assert parse_docket_no(text) == "2019/1234"


@pytest.mark.parametrize(
    "text",
    [
        HEADER_SUFFIX_FORM,
        BODY_LABELED_FORM,
        "Karar No: 2021/5678",
        "2021/5678 K.",
    ],
)
def test_parse_decision_no_handles_common_forms(text):
    assert parse_decision_no(text) == "2021/5678"


def test_parse_docket_no_returns_none_without_case_number():
    assert parse_docket_no("Bu metinde numara yok.") is None


def test_case_numbers_are_normalized_without_padding():
    assert parse_docket_no("Esas No: 2019/0045") == "2019/45"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("KARAR TARİHİ : 12.05.2021", date(2021, 5, 12)),
        ("Karar Tarihi: 01/02/2020", date(2020, 2, 1)),
        ("2021/5678 K. 12-05-2021", date(2021, 5, 12)),
    ],
)
def test_parse_decision_date_reads_labeled_forms(text, expected):
    assert parse_decision_date(text) == expected


def test_parse_decision_date_ignores_unlabeled_dates_by_default():
    body = "Taraflar arasındaki sözleşme 03.04.2015 tarihinde imzalanmıştır."

    assert parse_decision_date(body) is None
    assert parse_decision_date(body, allow_unlabeled=True) == date(2015, 4, 3)


def test_parse_decision_date_rejects_impossible_date():
    assert parse_decision_date("Karar Tarihi: 32.13.2021") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("9. Hukuk Dairesi", "9. Hukuk Dairesi"),
        ("YARGITAY 9. HUKUK DAİRESİ", "9. Hukuk Dairesi"),
        ("9. HD", "9. Hukuk Dairesi"),
        ("12. Ceza Dairesi", "12. Ceza Dairesi"),
        ("Hukuk Genel Kurulu", "Hukuk Genel Kurulu"),
        ("Ceza Genel Kurulu", "Ceza Genel Kurulu"),
        (
            "Ceza Genel Kurulu 2004/8-130 E., 2004/206 K.\nYARGITAY DAİRESİ : 8. Ceza Dairesi",
            "Ceza Genel Kurulu",
        ),
        (
            "Hukuk Genel Kurulu 2005/9-235 E. , 2005/293 K.\n9. Hukuk Dairesi kararı temyiz edildi",
            "Hukuk Genel Kurulu",
        ),
    ],
)
def test_parse_chamber_normalizes_variants(text, expected):
    assert parse_chamber(text) == expected


def test_parse_chamber_returns_none_when_absent():
    assert parse_chamber("Bölge Adliye Mahkemesi") is None


def test_build_external_id_is_deterministic_and_slugified():
    external_id = build_external_id("Yargıtay", "9. Hukuk Dairesi", "2019/1234", "2021/5678")

    assert external_id == "yargitay/9-hukuk-dairesi/2019-1234/2021-5678"
    assert external_id == build_external_id(
        "Yargıtay", "9. Hukuk Dairesi", "2019/1234", "2021/5678"
    )


def test_parse_decision_builds_full_record():
    decision = parse_decision(
        header_text=HEADER_SUFFIX_FORM,
        body_text=BODY_LABELED_FORM,
        source_url="https://karararama.yargitay.gov.tr/",
    )

    assert decision is not None
    assert decision.court_name == "Yargıtay"
    assert decision.chamber == "9. Hukuk Dairesi"
    assert decision.docket_no == "2019/1234"
    assert decision.decision_no == "2021/5678"
    assert decision.decision_date == date(2021, 5, 12)
    assert decision.external_id == "yargitay/9-hukuk-dairesi/2019-1234/2021-5678"
    assert decision.title == (
        "Yargıtay 9. Hukuk Dairesi, E. 2019/1234, K. 2021/5678 (12.05.2021)"
    )
    assert "kıdem tazminatı" in decision.raw_text
    assert len(decision.content_hash) == 64


def test_parse_decision_returns_none_without_case_numbers():
    assert parse_decision(header_text="Bilinmeyen satır", body_text="Metin") is None


def test_parse_decision_hash_is_stable_across_whitespace_noise():
    first = parse_decision(header_text=HEADER_SUFFIX_FORM, body_text=BODY_LABELED_FORM)
    noisy_body = BODY_LABELED_FORM.replace("\n\n", "\n\n\n").replace(" : ", "  :  ")
    second = parse_decision(header_text=HEADER_SUFFIX_FORM, body_text=noisy_body)

    assert first is not None and second is not None
    assert first.content_hash == second.content_hash


def test_parse_decision_uses_fallback_chamber_when_missing():
    decision = parse_decision(
        header_text="2019/1234 E. 2021/5678 K.",
        body_text="Metin gövdesi",
        fallback_chamber="22. Hukuk Dairesi",
    )

    assert decision is not None
    assert decision.chamber == "22. Hukuk Dairesi"
