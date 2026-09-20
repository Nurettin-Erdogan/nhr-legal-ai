from ingestion.danistay.parser import parse_chamber


def test_parse_chamber_numbered_header():
    assert parse_chamber("Danıştay 6. Daire Başkanlığı 2022/4009 E. , 2025/57 K.") == "6. Daire"


def test_parse_chamber_ordinal_body():
    assert parse_chamber("T.C. DANIŞTAY ALTINCI DAİRE Esas No : 2022/4009") == "6. Daire"


def test_parse_chamber_iddk():
    assert (
        parse_chamber("Danıştay İdari Dava Daireleri Kurulu 2021/1 E., 2021/2 K.")
        == "İdari Dava Daireleri Kurulu"
    )


def test_parse_chamber_vddk():
    assert parse_chamber("Vergi Dava Daireleri Kurulu") == "Vergi Dava Daireleri Kurulu"


def test_parse_chamber_missing():
    assert parse_chamber("İdare mahkemesi kararı") is None
