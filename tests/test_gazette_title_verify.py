"""Tebliğ/yönetmelik: Resmî Gazete'de numara yok; kimlik yayın günü + başlıkla doğrulanır."""

from __future__ import annotations

import json
from datetime import date

import pytest

from ingestion.mevzuat import official_verify
from ingestion.resmi_gazete.portal import (
    ResmiGazeteClient,
    ResmiGazeteError,
    match_title_entries,
    title_base_key,
    title_ident_tokens,
)

DAY = date(2023, 4, 8)


def entry(title, issue=32157, day="2023-04-08", url="/fihrist?tarih=2023-04-08"):
    return {"konu": title, "resmiGazeteSayisi": issue, "resmiGazeteTarihi": f"{day}T00:00:00", "url": url,
            "kanunKararNo": ""}


def test_parenthetical_suffix_spelling_does_not_change_the_base_key():
    ours = "İTHALATTA HAKSIZ REKABETİN ÖNLENMESİNE İLİŞKİN TEBLİĞ\r (TEBLİĞ NO: 2023/14)"
    theirs = "İthalatta Haksız Rekabetin Önlenmesine İlişkin Tebliğ (No: 2023/14)"
    assert title_base_key(ours) == title_base_key(theirs)
    assert title_ident_tokens(ours) == title_ident_tokens(theirs) == ("2023/14",)


def test_identifier_tokens_cover_codes_and_plain_numbers():
    assert title_ident_tokens("MECBURİ STANDARD TEBLİĞİ (TEBLİĞ NO: ÖSG-2009/07)") == ("ösg-2009/07",)
    assert title_ident_tokens("GÜMRÜK GENEL TEBLİĞİ (SERİ NO:55)") == ("55",)
    assert title_ident_tokens("SU KİRLİLİĞİ KONTROLÜ YÖNETMELİĞİ İDARİ USULLER TEBLİĞİ") == ()


def test_unique_title_and_date_matches():
    entries = [entry("Başka Bir Tebliğ"), entry("Su Kirliliği Kontrolü Yönetmeliği İdari Usuller Tebliği")]
    chosen = match_title_entries(
        entries, title="SU KİRLİLİĞİ KONTROLÜ YÖNETMELİĞİ İDARİ USULLER TEBLİĞİ", publication_date=DAY, issue_no="32157"
    )
    assert chosen["konu"].startswith("Su Kirliliği")


def test_sibling_communiques_with_the_same_title_are_told_apart_by_their_number():
    entries = [
        entry("İthalatta Haksız Rekabetin Önlenmesine İlişkin Tebliğ (No: 2023/13)"),
        entry("İthalatta Haksız Rekabetin Önlenmesine İlişkin Tebliğ (No: 2023/14)"),
    ]
    title = "İTHALATTA HAKSIZ REKABETİN ÖNLENMESİNE İLİŞKİN TEBLİĞ (TEBLİĞ NO: 2023/14)"
    chosen = match_title_entries(entries, title=title, publication_date=DAY, issue_no="32157")
    assert chosen["konu"].endswith("2023/14)")


def test_siblings_without_a_number_in_our_title_are_ambiguous_and_refused():
    entries = [
        entry("İthalatta Haksız Rekabetin Önlenmesine İlişkin Tebliğ (No: 2023/13)"),
        entry("İthalatta Haksız Rekabetin Önlenmesine İlişkin Tebliğ (No: 2023/14)"),
    ]
    with pytest.raises(ResmiGazeteError, match="2 aday"):
        match_title_entries(
            entries, title="İTHALATTA HAKSIZ REKABETİN ÖNLENMESİNE İLİŞKİN TEBLİĞ", publication_date=DAY, issue_no=None
        )


def test_other_date_or_other_title_is_never_accepted():
    entries = [entry("Mecburi Standard Tebliği", day="2023-04-09")]
    with pytest.raises(ResmiGazeteError, match="0 aday"):
        match_title_entries(entries, title="MECBURİ STANDARD TEBLİĞİ", publication_date=DAY, issue_no=None)
    with pytest.raises(ResmiGazeteError, match="0 aday"):
        match_title_entries(
            [entry("Mecburi Standard Tebliği")], title="MECBURİ STANDARD TEBLİĞİ (SIRA NO: 1) EK", publication_date=DAY,
            issue_no=None,
        )


def test_recorded_issue_number_that_contradicts_the_gazette_is_refused():
    with pytest.raises(ResmiGazeteError, match="çelişiyor"):
        match_title_entries(
            [entry("Mecburi Standard Tebliği", issue=32157)], title="MECBURİ STANDARD TEBLİĞİ",
            publication_date=DAY, issue_no="99999",
        )


def test_a_conflicting_identifier_on_a_unique_title_is_refused():
    with pytest.raises(ResmiGazeteError, match="numara/kod çelişiyor"):
        match_title_entries(
            [entry("Mecburi Standard Tebliği (No: 2010/5)")],
            title="MECBURİ STANDARD TEBLİĞİ (TEBLİĞ NO: 2010/6)", publication_date=DAY, issue_no=None,
        )


def test_a_duplicated_index_row_is_one_document_not_an_ambiguity():
    row = entry("Mecburi Standard Tebliği")
    chosen = match_title_entries([row, dict(row)], title="MECBURİ STANDARD TEBLİĞİ", publication_date=DAY, issue_no=None)
    assert chosen["konu"] == "Mecburi Standard Tebliği"


class _Response:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw

    def read(self) -> bytes:
        return self.raw

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _Opener:
    """Ana sayfa isteğine boş, aramaya sayfalı yanıt verir."""

    def __init__(self, pages: list[list[dict]], total: int) -> None:
        self.pages = pages
        self.total = total
        self.searches = 0

    def open(self, request, timeout):
        if request.data is None:
            return _Response(b"<html></html>")
        body = json.loads(request.data.decode("utf-8"))
        start = body["start"]
        index = start // 100
        self.searches += 1
        return _Response(json.dumps({"data": self.pages[index], "recordsTotal": self.total,
                                     "recordsFiltered": self.total}).encode("utf-8"))


def test_every_page_of_a_busy_day_is_read_and_the_day_is_cached():
    first = [entry(f"Tebliğ {i}") for i in range(100)]
    second = [entry("Mecburi Standard Tebliği (No: ÖSG-2009/07)")]
    opener = _Opener([first, second], total=101)
    client = ResmiGazeteClient(opener=opener)

    result = client.verify_by_title(publication_date=DAY, issue_no="32157",
                                    title="MECBURİ STANDARD TEBLİĞİ (TEBLİĞ NO: ÖSG-2009/07)")
    assert result.verified and result.observed_issue_no == "32157" and not result.law_no_present
    assert opener.searches == 2
    client.verify_by_title(publication_date=DAY, issue_no="32157",
                           title="MECBURİ STANDARD TEBLİĞİ (TEBLİĞ NO: ÖSG-2009/07)")
    assert opener.searches == 2  # aynı gün yeniden istenmez


def test_missing_publication_date_cannot_be_verified_by_title():
    with pytest.raises(ResmiGazeteError, match="yayın tarihi yok"):
        ResmiGazeteClient(opener=_Opener([[]], 0)).verify_by_title(publication_date=None, issue_no=None, title="X")


class _FakeGazette:
    def __init__(self, *, by_title=None, by_number=None):
        self.by_title, self.by_number = by_title, by_number
        self.calls: list[str] = []

    def verify_by_title(self, **kwargs):
        self.calls.append("title")
        if isinstance(self.by_title, Exception):
            raise self.by_title
        return self.by_title

    def verify_legislation(self, **kwargs):
        self.calls.append("number")
        if isinstance(self.by_number, Exception):
            raise self.by_number
        return self.by_number


class _Verified:
    def __init__(self, verified=True):
        self.verified = verified

    def to_json(self):
        return {"verified": self.verified, "detail": "ok"}


def _law(kind, law_no):
    return {"legislation_type": kind, "law_no": law_no, "law_name": "MECBURİ STANDARD TEBLİĞİ",
            "official_gazette_date": DAY, "official_gazette_no": "32157"}


@pytest.fixture(autouse=True)
def _clear_cache():
    official_verify._GAZETTE_OK.clear()
    yield
    official_verify._GAZETTE_OK.clear()


def test_communique_is_verified_by_title_and_marked_with_its_method():
    client = _FakeGazette(by_title=_Verified())
    verified, result, _ = official_verify._check_gazette(
        _law("communique", "41115"), gazette_client=client, gazette_key=("communique", "41115", "32157")
    )
    assert verified is True and result["method"] == "title_date" and client.calls == ["title"]


def test_long_communique_number_is_not_searched_as_a_gazette_number_after_a_title_miss():
    client = _FakeGazette(by_title=ResmiGazeteError("başlık + tarih ile tekil Resmî Gazete kaydı bulunamadı (0 aday)"))
    verified, result, _ = official_verify._check_gazette(
        _law("communique", "41115"), gazette_client=client, gazette_key=("communique", "41115", "32157")
    )
    assert verified is False and client.calls == ["title"] and "0 aday" in result["detail"]


def test_short_communique_number_falls_back_to_the_number_search_and_keeps_both_reasons():
    client = _FakeGazette(
        by_title=ResmiGazeteError("başlık yok (0 aday)"),
        by_number=ResmiGazeteError("1234 numaralı mevzuat için tekil Resmî Gazete kaydı bulunamadı"),
    )
    verified, result, _ = official_verify._check_gazette(
        _law("communique", "1234"), gazette_client=client, gazette_key=("communique", "1234", "32157")
    )
    assert verified is False and client.calls == ["title", "number"]
    assert "başlıkla: başlık yok" in result["detail"] and "1234 numaralı" in result["detail"]


def test_laws_never_use_the_title_path():
    client = _FakeGazette(by_number=_Verified())
    verified, _, _ = official_verify._check_gazette(
        _law("law", "4857"), gazette_client=client, gazette_key=("law", "4857", "32157")
    )
    assert verified is True and client.calls == ["number"]


def test_pending_query_no_longer_excludes_long_regulation_numbers_or_demotes_communiques():
    sql = official_verify._PENDING_LAWS_SQL
    assert "length(d.law_no) > 6" not in sql
    assert "length(pending.law_no) > 4" not in sql
