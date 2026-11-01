"""İcra dosyası incelemesi: UYAP dosya bilgilerinden künye, taraflar, önemli işlemler, tebligatlar ve kişi başına sorgular.

Örnek kayıtlar uydurmadır; kalıpları gerçek hesapta ölçülen UYAP safahat biçimleriyle aynıdır (2026-10-10). Özetin kuralı:
UYAP'ın yazdığı seçilir, sayılır ve sıralanır; hiçbir sonuç çıkarılmaz.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from api import execution
from api import execution_overview as overview
from tests.test_case_document_rag import db, needs_db  # noqa: F401  (fixture)
from tests.test_execution import _case_with_document, _row, _world

TODAY = date(2026, 10, 10)
HEADS = ["İşlem Yapan Birim", "Tarih", "İşlem Türü", "Açıklama", "İşlem Durumu"]
UNIT = "Ankara 7. Genel İcra Dairesi"


def _safahat(*rows: tuple[str, str, str]) -> dict:
    return {"key": "safahat", "pairs": [], "tables": [{"headers": HEADS, "rows": [[UNIT, day, kind, text, ""] for day, kind, text in rows]}]}


def _taraflar(*rows: tuple[str, str, str, str]) -> dict:
    return {"key": "taraflar", "pairs": [], "tables": [{"headers": ["Rol", "Tipi", "Adı", "Vekil", "İşlem"], "rows": [[*row, ""] for row in rows]}]}


PARTIES = _taraflar(
    ("Borçlu", "Kişi", "AYŞE ÖRNEK", ""),
    ("Alacaklı", "Kurum", "DENEME ALACAK A.Ş.", "[Av. DENEME VEKİL]"),
    ("Borçlu", "Kişi", "ISMAIL DENEMECI", ""),
)


# --- Sekmeleri okuma -----------------------------------------------------------------------------------------------------


def test_identity_account_and_collection_fields_are_passed_through_as_uyap_wrote_them():
    tabs = [
        {"key": "bilgiler", "pairs": [{"label": "Türü", "value": "İlamsız Takip"}, {"label": "Dosya Durumu", "value": "Açık"}, {"label": "Boş", "value": ""}]},
        {"key": "hesap", "pairs": [{"label": "Toplam Alacak", "value": "₺13.783,00"}, {"label": "Seç", "value": "Seçim Yapınız"}, "bozuk"]},
        {"key": "tahsilat", "tables": [
            {"headers": ["Makbuz No", "Reddiyat Tarihi"], "rows": [["1", "01/02/2025"]]},
            {"headers": ["Tahsilat", "Reddiyat", "Tahsilat Kalanı"], "rows": [["162,5 TL", "162,5 TL", "0 TL"]]},
        ]},
    ]

    assert overview.identity(tabs) == [{"label": "Türü", "value": "İlamsız Takip"}, {"label": "Dosya Durumu", "value": "Açık"}]
    assert overview.account(tabs) == [{"label": "Toplam Alacak", "value": "₺13.783,00"}]  # "Seç" bir hesap alanı değil
    assert overview.collections(tabs) == [
        {"label": "Tahsilat", "value": "162,5 TL"}, {"label": "Reddiyat", "value": "162,5 TL"}, {"label": "Tahsilat Kalanı", "value": "0 TL"},
    ]


def test_parties_keep_uyaps_wording_with_creditors_first():
    assert overview.parties([PARTIES]) == [
        {"role": "Alacaklı", "type": "Kurum", "name": "DENEME ALACAK A.Ş.", "lawyer": "Av. DENEME VEKİL"},
        {"role": "Borçlu", "type": "Kişi", "name": "AYŞE ÖRNEK", "lawyer": ""},
        {"role": "Borçlu", "type": "Kişi", "name": "ISMAIL DENEMECI", "lawyer": ""},
    ]


@pytest.mark.parametrize("value, expected", [
    ("12.03.2025", date(2025, 3, 12)), ("12/03/2025 14:05", date(2025, 3, 12)), ("31.02.2025", None), ("", None), (None, None),
])
def test_dates_are_read_in_both_uyap_spellings(value, expected):
    assert overview.parse_date(value) == expected


def test_summary_text_drops_identity_numbers_but_keeps_the_service_barcode():
    text = "[TC: 12345678901] Avukat X tarafından 12345678901 TC No ile 2700123456789 barkodlu, TR120006200000000123456789 hesabına"

    cleaned = overview.clean_text(text)

    assert "12345678901" not in cleaned and "[TC" not in cleaned and "0006200000000123456789" not in cleaned
    assert "2700123456789" in cleaned  # 13 haneli tebligat barkodu kimlik numarası değildir
    assert overview.clean_text("a" * 300).endswith("…") and len(overview.clean_text("a" * 300)) == 240


def test_malformed_or_missing_tabs_give_empty_sections_instead_of_failing():
    for tabs in (None, [], "bozuk", [None, 3, {"key": "safahat", "tables": [{"headers": None, "rows": "x"}, "y"]}], [{"key": "taraflar"}]):
        view = overview.build_overview(tabs, complete=False, fetched_at=None, today=TODAY)
        assert view["parties"] == [] and view["milestones"] == [] and view["services"] == []
        assert view["activity"]["entries"] == 0 and view["activity"]["days_since_last"] is None
        assert view["asset_queries"] == {"kinds": [], "people": []}


# --- Sorgular ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind, text, expected", [
    ("Araç Sahiplikten Sorgulandı.", "", ("arac", "Araç")),
    ("TC No ile Takbis Sorgulaması Yapıldı", "", ("tapu", "Tapu (TAKBİS)")),
    ("TAKBIS Bilgisi Sorgulandı.", "", ("tapu", "Tapu (TAKBİS)")),
    ("Taraf icin getSGKAktif4ASorgu laması yapıldı.", "", ("sgk_aktif_4a", "SGK aktif 4A")),
    ("Taraf icin getSGKPasif4CSorgu laması yapıldı.", "", ("sgk_pasif_4c", "SGK pasif 4C")),
    ("Taraf icin getSGKIsyeriTescilByTcNo laması yapıldı.", "", ("sgk_isyeri", "SGK işyeri tescil")),
    ("SGK Haciz Sorgulandı", "", ("sgk_haciz", "SGK haciz")),
    ("PTT Posta Çeki için Rapor Alındı.", "", ("posta", "Posta çeki")),
    ("", "Avukat X tarafından, Y adlı kişi adres sorgulaması yapıldı. Sorgu Sonucu: VAR", ("adres", "Adres")),
    ("", "başka bir açıklama", None),  # türü yazılmamış ve tanınmayan kayıt sorgu sayılmaz
    ("Tebligat Bilgileri Kaydedildi", "adres sorgulaması", None),
    ("Mahrumiyet Bilgisi Sorgulandı.", "", None),
])
def test_query_records_are_recognised_by_uyaps_own_action_names(kind, text, expected):
    assert overview.query_kind(kind, text) == expected


@pytest.mark.parametrize("text, expected", [
    ("… Araç Sahiplikten Sorgulandı. Sorgu Sonucu: YOK", "YOK"),
    ("… Araç Sahiplikten Sorgulandı.Sorgu Sonucu YOK", "YOK"),  # UYAP'ın eski yazımı: boşluksuz, iki noktasız
    ("… SGK Haciz Sorgulandı Sorgu Sonucu: VAR", "VAR"),
    ("… TAKBIS Bilgisi Sorgulandı.", None),  # sonuç yazmıyorsa tahmin edilmez
    ("Sorgu Sonucu: BELİRSİZ", None),
])
def test_the_result_is_only_what_the_record_says(text, expected):
    assert overview.query_result(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Avukat DENEME VEKİL tarafından, AYŞE ÖRNEK adlı kişi Araç Sahiplikten Sorgulandı.Sorgu Sonucu YOK", "AYŞE ÖRNEK"),
    ("[TC: 12345678901] Avukat DENEME VEKİL tarafından, ISMAIL DENEMECI adlı kişi TAKBIS Bilgisi Sorgulandı. Sorgu Sonucu: YOK", "ISMAIL DENEMECI"),
    ("12345678901 TC Kimlik No'lu Avukat DENEME VEKİL Tarafından 10987654321 AYŞE ÖRNEK Adlı Kişi İçin TC No ile Takbis Sorgulaması Yapıldı", "AYŞE ÖRNEK"),
    ("Avukat DENEME VEKİL tarafından, DENEME TİCARET LTD. ŞTİ. adlı kurum Araç Sahiplikten Sorgulandı.", "DENEME TİCARET LTD. ŞTİ."),
    ("12345678901 TC No ile Takbis Sorgulaması Yapıldı", None),
    ("", None),
])
def test_the_queried_person_is_read_from_the_record_without_identity_numbers(text, expected):
    assert overview.queried_person(text) == expected


def _query(day: str, kind: str, name: str, result: str | None) -> tuple[str, str, str]:
    return (day, kind, f"Avukat DENEME VEKİL tarafından, {name} adlı kişi {kind}" + (f" Sorgu Sonucu: {result}" if result else ""))


def test_queries_are_grouped_per_person_with_the_latest_written_result():
    car, deed = "Araç Sahiplikten Sorgulandı.", "TAKBIS Bilgisi Sorgulandı."
    tabs = [PARTIES, _safahat(
        _query("05.06.2025", car, "AYŞE ÖRNEK", "YOK"),
        _query("01.02.2024", car, "AYŞE ÖRNEK", "VAR"),      # eski kayıt: sonraki sonuç onun yerini alır
        _query("07.07.2025", car, "AYŞE ÖRNEK", None),       # sonuç yazmayan kayıt son sonucu silmez, yalnız son sorgu tarihini ilerletir
        _query("03.03.2025", deed, "ISMAIL DENEMECI", "VAR"),
        _query("03.03.2025", deed, "ISMAIL DENEMECI", "YOK"),  # aynı gün iki farklı sonuç: ikisi de gösterilir
        _query("04.04.2025", car, "DENEME ALACAK A.Ş.", "YOK"),
        ("09.09.2025", deed, "12345678901 TC No ile Takbis Sorgulaması Yapıldı"),
        ("10.09.2025", "", "Avukat DENEME VEKİL tarafından, AYŞE ÖRNEK adlı kişi adres sorgulaması yapıldı. Sorgu Sonucu: VAR"),
    )]

    result = overview.build_overview(tabs, complete=True, fetched_at=None, today=TODAY)["asset_queries"]

    assert result["kinds"] == [{"key": "arac", "label": "Araç"}, {"key": "tapu", "label": "Tapu (TAKBİS)"}, {"key": "adres", "label": "Adres"}]
    # Borçlular önce, sonra alacaklı; adı okunamayan kayıt en sonda.
    assert [(row["name"], row["role"]) for row in result["people"]] == [
        ("AYŞE ÖRNEK", "Borçlu"), ("ISMAIL DENEMECI", "Borçlu"), ("DENEME ALACAK A.Ş.", "Alacaklı"), (None, None),
    ]
    ayse = {cell["key"]: cell for cell in result["people"][0]["queries"]}
    assert (ayse["arac"]["count"], ayse["arac"]["last_date"], ayse["arac"]["result"], ayse["arac"]["result_date"]) == (
        3, date(2025, 7, 7), "YOK", date(2025, 6, 5),
    )
    assert ayse["arac"]["results"] == {"VAR": 1, "YOK": 1, "unstated": 1}
    assert ayse["adres"]["result"] == "VAR"
    assert result["people"][1]["queries"][0]["result"] == "VAR/YOK"
    assert result["people"][3]["queries"][0]["result"] is None and result["people"][3]["queries"][0]["count"] == 1


def test_a_name_that_matches_two_different_roles_gets_no_role():
    tabs = [_taraflar(("Alacaklı", "Kişi", "ALİ DENEME", ""), ("Borçlu", "Kişi", "ALİ DENEME", "")),
            _safahat(_query("01.01.2025", "Araç Sahiplikten Sorgulandı.", "ALİ DENEME", "YOK"))]

    people = overview.build_overview(tabs, complete=True, fetched_at=None, today=TODAY)["asset_queries"]["people"]

    assert [(row["name"], row["role"]) for row in people] == [("ALİ DENEME", None)]


# --- Önemli işlemler ------------------------------------------------------------------------------------------------------


def test_milestones_follow_the_usual_course_and_unknown_actions_stay_under_their_uyap_name():
    tabs = [_safahat(
        ("20.03.2025", "Dosya Kesinleşme Bilgi Girişi.", "AYŞE ÖRNEK kesinlesme bilgisi kaydedildi."),
        ("01.02.2025", "Dosyanın Açılması", ""),
        ("02.02.2025", "Ödeme İcra Emri Evrağı Hazırlandı.", "Örnek 7 (Eski No 49) İlamsız Takiplerde Ödeme Emri (49) Hazirlandi."),
        ("21.03.2025", "Tensip Zaptı Bilgi Girişi", "Tensip Zaptı Bilgi Girişi (Avukat Portal Haciz Talebi)"),
        ("22.03.2025", "Tensip Zaptı Bilgi Girişi", "Tensip Zaptı Bilgi Girişi (Kabul)"),
        ("23.03.2025", "Bankaya Hesap Haciz İhbarnamesinin Hazırlanması(Tebligatlı).", "Bankaya Hesap Haciz İhbarnamesinin Hazırlanması(Tebligatlı)."),
        ("24.03.2025", "Gelen Evrak Kaydedilmesi", "89/1 Haciz İhbarnamesi Cevabı"),
        ("25.03.2025", "Gelen Evrak Kaydedilmesi", "89/1 Haciz İhbarnamesi Cevabı"),
        ("26.03.2025", "Yanlışlıkla Kapatılan Dosyanın Açılması", "x"),
        ("27.03.2025", "Vekaletname İle Vekil Kaydedildi", "AYŞE ÖRNEK tarafının vekili olarak 12345678901 T.C. Kimlik No.lu Vekil X Kaydedildi."),
        ("28.03.2025", "Hiç Görülmemiş Bir İşlem", "y"),
        ("29.03.2025", "", "türü yazılmamış kayıt"),
        ("30.03.2025", "Araç Sahiplikten Sorgulandı.", "Avukat X tarafından, AYŞE ÖRNEK adlı kişi Araç Sahiplikten Sorgulandı. Sorgu Sonucu: YOK"),
    )]

    view = overview.build_overview(tabs, complete=True, fetched_at=None, today=TODAY)

    assert [(item["key"], item["count"]) for item in view["milestones"]] == [
        ("acilis", 1), ("odeme_emri", 1), ("kesinlesme", 1), ("haciz_talebi", 1), ("talep", 1), ("banka_haciz", 1), ("gelen_evrak", 2),
        ("yeniden_acilis", 1),
    ]
    incoming = next(item for item in view["milestones"] if item["key"] == "gelen_evrak")
    assert (incoming["first_date"], incoming["last_date"]) == (date(2025, 3, 24), date(2025, 3, 25))
    assert incoming["uyap_types"] == ["Gelen Evrak Kaydedilmesi"]
    assert incoming["recent"][0] == {"date": date(2025, 3, 25), "text": "89/1 Haciz İhbarnamesi Cevabı"}  # en yeni önce
    # Tanınmayan işlem hiçbir gruba zorla sokulmaz; sorgu kaydı burada da sayılmaz.
    assert {item["name"]: item["count"] for item in view["other_actions"]} == {
        "Vekaletname İle Vekil Kaydedildi": 1, "Hiç Görülmemiş Bir İşlem": 1, "(işlem türü yazılmamış)": 1,
    }
    assert sum(item["count"] for item in view["milestones"]) + sum(item["count"] for item in view["other_actions"]) == 12


def test_activity_counts_days_since_the_last_record_without_drawing_a_conclusion():
    tabs = [_safahat(("01.02.2025", "Dosyanın Açılması", ""), ("30.09.2026", "Gelen Evrak Kaydedilmesi", "[TC: 12345678901] yazı"), ("bozuk", "Dosya Kapatıldı", "x"))]

    activity = overview.build_overview(tabs, complete=True, fetched_at=None, today=TODAY)["activity"]

    assert activity == {
        "entries": 3, "undated": 1, "first_date": date(2025, 2, 1), "last_date": date(2026, 9, 30), "days_since_last": 10,
        "last": {"type": "Gelen Evrak Kaydedilmesi", "text": "yazı"},
    }
    future = overview.build_overview([_safahat(("01.01.2030", "Dosyanın Açılması", ""))], complete=True, fetched_at=None, today=TODAY)
    assert future["activity"]["days_since_last"] is None  # ileri tarihli kayıt: "eksi gün" yazılmaz


# --- Tebligatlar ----------------------------------------------------------------------------------------------------------


def test_service_records_are_paired_with_their_result_by_barcode():
    tabs = [_safahat(
        ("03.02.2025", "Tebligat Bilgileri Kaydedildi", "2700000000001 - Tebligat Bilgileri Kaydedildi [BORÇLU VE MÜFLİS AYŞE ÖRNEK ] tarafına - Kapalı Tebligat"),
        ("10.02.2025", "Tebligat Sonuç Bilgileri Kaydedildi", "Tebligat Sonuç Bilgileri Kaydedildi [BORÇLU VE MÜFLİS AYŞE ÖRNEK ] - 2700000000001 - Tebliğ Edildi"),
        ("05.03.2025", "Tebligat Bilgileri Kaydedildi", "2700000000002 - Tebligat Bilgileri Kaydedildi [Tebligat Yapılacak 3. Taraf DENEME BANKASI ANONİM ŞİRKETİ] tarafına - Kapalı Tebligat"),
        ("12.03.2025", "Tebligat Sonuç Bilgileri Kaydedildi", "Barkod No:2700000000002"),
        ("06.03.2025", "Tebligat Bilgileri Kaydedildi", "2700000000003 - Tebligat Bilgileri Kaydedildi [Vekil DENEME VEKİL ] tarafına - Kapalı Tebligat"),
        ("07.03.2025", "Tebligat Sonuç Bilgileri Kaydedildi", "Barkod No:2700000000009"),  # çıkış kaydı olmayan sonuç
    )]

    services = overview.build_overview(tabs, complete=True, fetched_at=None, today=TODAY)["services"]

    by_code = {item["barcode"]: item for item in services}
    assert [item["barcode"] for item in services] == ["2700000000009", "2700000000003", "2700000000002", "2700000000001"]  # en yeni önce
    assert by_code["2700000000001"] == {
        "barcode": "2700000000001", "recipient": "BORÇLU VE MÜFLİS AYŞE ÖRNEK", "method": "Kapalı Tebligat",
        "sent_date": date(2025, 2, 3), "result": "Tebliğ Edildi", "result_date": date(2025, 2, 10),
    }
    # "Barkod No:…" kaydı yalnız sonucun girildiğini söyler; sonucun ne olduğu yazmıyorsa uydurulmaz.
    assert (by_code["2700000000002"]["result"], by_code["2700000000002"]["result_date"]) == (None, date(2025, 3, 12))
    assert (by_code["2700000000003"]["result"], by_code["2700000000003"]["result_date"]) == (None, None)
    assert (by_code["2700000000009"]["sent_date"], by_code["2700000000009"]["recipient"]) == (None, None)


# --- Liste satırı ---------------------------------------------------------------------------------------------------------


def test_the_list_summary_names_parties_and_only_repeats_positive_results_about_debtors():
    car, deed = "Araç Sahiplikten Sorgulandı.", "TAKBIS Bilgisi Sorgulandı."
    tabs = [
        {"key": "bilgiler", "pairs": [{"label": "Türü", "value": "İlamsız Takip"}, {"label": "Yolu", "value": "Genel Haciz Yoluyla Takip"},
                                      {"label": "Dosya Durumu", "value": "Takipsizlik"}]},
        PARTIES,
        _safahat(
            _query("01.02.2025", car, "AYŞE ÖRNEK", "VAR"),
            _query("02.02.2025", deed, "AYŞE ÖRNEK", "YOK"),
            _query("03.02.2025", deed, "DENEME ALACAK A.Ş.", "VAR"),  # alacaklı hakkındaki sorgu listede anılmaz
            ("04.02.2025", "", "Avukat X tarafından, AYŞE ÖRNEK adlı kişi adres sorgulaması yapıldı. Sorgu Sonucu: VAR"),
        ),
    ]

    row = overview.list_overview(overview.build_overview(tabs, complete=True, fetched_at=None, today=TODAY))

    assert row == {
        "type": "İlamsız Takip", "path": "Genel Haciz Yoluyla Takip", "status": "Takipsizlik",
        "creditors": ["DENEME ALACAK A.Ş."], "debtors": ["AYŞE ÖRNEK", "ISMAIL DENEMECI"], "party_count": 3,
        "last_activity": date(2025, 2, 4), "days_since_last": (TODAY - date(2025, 2, 4)).days, "history_entries": 4,
        "positive_queries": ["Araç"],
    }


def test_a_file_without_documents_is_listed_and_a_stale_completeness_record_is_not_trusted():
    checked = datetime(2026, 10, 9, tzinfo=timezone.utc)
    emptied, kept = uuid4(), uuid4()
    base = {"dosya_durumu": "Açık", "sync_complete": True, "sync_missing": 0, "sync_checked_at": checked}
    rows = [
        {**_row(emptied, None), "document_id": None, **base, "sync_documents": 110},  # doğrulamadan sonra evrakları silinmiş
        {**_row(kept, "Takip Talebi", date(2025, 1, 2), no="2025/2"), **base, "sync_documents": 1},
    ]
    views = {emptied: overview.build_overview([PARTIES], complete=True, fetched_at=checked, today=TODAY)}

    files = {item["case_id"]: item for item in execution.build_files(rows, {}, views)}

    assert files[emptied]["documents"] == 0 and files[emptied]["counts"] == {} and files[emptied]["last_date"] is None
    assert (files[emptied]["uyap"]["complete"], files[emptied]["uyap"]["removed_since"]) == (False, 110)
    assert files[emptied]["overview"]["debtors"] == ["AYŞE ÖRNEK", "ISMAIL DENEMECI"]
    assert (files[kept]["uyap"]["complete"], files[kept]["uyap"]["removed_since"]) == (True, 0) and files[kept]["overview"] is None
    assert execution.summarize(list(files.values()))["verified_complete"] == 1


# --- Veritabanı ile -------------------------------------------------------------------------------------------------------

_TABS = (
    '[{"key": "bilgiler", "pairs": [{"label": "Türü", "value": "İlamsız Takip"}, {"label": "Dosya Durumu", "value": "Açık"}], "tables": []},'
    ' {"key": "taraflar", "pairs": [], "tables": [{"headers": ["Rol", "Tipi", "Adı", "Vekil", "İşlem"],'
    ' "rows": [["Borçlu", "Kişi", "AYŞE ÖRNEK", "", ""]]}]},'
    ' {"key": "safahat", "pairs": [], "tables": [{"headers": ["İşlem Yapan Birim", "Tarih", "İşlem Türü", "Açıklama", "İşlem Durumu"],'
    ' "rows": [["x", "01.02.2025", "Dosyanın Açılması", "", ""]]}]}]'
)


def _bare_file(world, owner, number, court="Ankara 7. Genel İcra Dairesi"):
    case_id = uuid4()
    world.become(None)
    world.connection.execute(
        "INSERT INTO office_cases (id, owner_id, case_no, esas_no, court, title) VALUES (%s, %s, %s, %s, %s, 'x')",
        (case_id, owner, number, number, court),
    )
    return case_id


@needs_db
def test_a_documentless_file_with_uyap_details_is_listed_and_reviewed_only_for_its_owner(db, monkeypatch):  # noqa: F811
    from fastapi import HTTPException

    world = _world(db, monkeypatch)
    with_details, without_anything = _bare_file(world, world.alice, "2012/7"), _bare_file(world, world.alice, "2012/8")
    world.connection.execute(
        "INSERT INTO office_uyap_case_detail (case_id, owner_id, tabs, complete) VALUES (%s, %s, %s::jsonb, true)", (with_details, world.alice, _TABS),
    )
    _case_with_document(world, world.bob, "İstanbul İcra Dairesi", "Takip Talebi")

    files = execution.execution_files(world.alice)["files"]

    assert [item["case_id"] for item in files] == [with_details]  # UYAP kaydı da evrakı da olmayan dosya listede yok
    assert files[0]["documents"] == 0 and files[0]["overview"]["status"] == "Açık" and files[0]["overview"]["debtors"] == ["AYŞE ÖRNEK"]
    assert execution.execution_files(world.bob)["files"][0]["overview"] is None  # başkasının UYAP bilgisi sızmaz

    detail = execution.execution_file_detail(with_details, world.alice)
    assert detail["receipts"] == [] and detail["overview"]["complete"] is True
    assert [item["key"] for item in detail["overview"]["milestones"]] == ["acilis"]
    assert execution.execution_file_detail(without_anything, world.alice)["overview"] is None  # UYAP bilgisi çekilmemiş
    with pytest.raises(HTTPException) as denied:
        execution.execution_file_detail(with_details, world.bob)
    assert denied.value.status_code == 404
