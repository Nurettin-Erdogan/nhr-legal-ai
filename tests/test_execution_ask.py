"""Dosyalar arası soru: bilinen kalıplar süzgece çevrilir, UYAP kayıtlarına uygulanır (dil modeli yok; örnekler uydurmadır)."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from api import execution
from api.execution_ask import answer, parse
from api.execution_overview import build_overview
from api.main import app
from tests.test_case_document_rag import db, needs_db  # noqa: F401  (fixture)
from tests.test_execution import _world

TODAY = date(2026, 10, 13)
HEADS = ["İşlem Yapan Birim", "Tarih", "İşlem Türü", "Açıklama", "İşlem Durumu"]


def _query(day, kind, name, result):
    text = f"Avukat DENEME VEKİL tarafından, {name} adlı kişi {kind}" + (f" Sorgu Sonucu: {result}" if result else "")
    return ["x", day, kind, text, ""]


def _tabs(status, debtor, rows, *, kind="İlamsız Takip", path="Genel Haciz Yoluyla Takip"):
    return [
        {"key": "bilgiler", "pairs": [{"label": "Türü", "value": kind}, {"label": "Yolu", "value": path}, {"label": "Dosya Durumu", "value": status}], "tables": []},
        {"key": "taraflar", "pairs": [], "tables": [{"headers": ["Rol", "Tipi", "Adı", "Vekil", "İşlem"], "rows": [
            ["Alacaklı", "Kurum", "DENEME ALACAK A.Ş.", "", ""], ["Borçlu", "Kişi", debtor, "", ""]]}]},
        {"key": "safahat", "pairs": [], "tables": [{"headers": HEADS, "rows": rows}]},
    ]


def _file(no, court, tabs):
    overview = None if tabs is None else build_overview(tabs, complete=True, fetched_at=None, today=TODAY)
    return {"case_id": uuid4(), "file_no": no, "court": court, "kind": "takip", "uyap_status": None, "overview": overview}


CAR, DEED = "Araç Sahiplikten Sorgulandı.", "TAKBIS Bilgisi Sorgulandı."
FILES = [
    _file("2025/1", "Ankara 7. Genel İcra Dairesi", _tabs("Açık", "AYŞE ÖRNEK", [
        ["x", "01.02.2025", "Dosyanın Açılması", "", ""],
        ["x", "20.02.2025", "Dosya Kesinleşme Bilgi Girişi.", "AYŞE ÖRNEK kesinlesme bilgisi kaydedildi.", ""],
        _query("05.10.2026", CAR, "AYŞE ÖRNEK", "VAR"), _query("05.10.2026", DEED, "AYŞE ÖRNEK", "YOK"),
        _query("06.10.2026", CAR, "DENEME ALACAK A.Ş.", "VAR")])),
    _file("2024/2", "Kahramankazan İcra Dairesi", _tabs("Açık", "ISMAIL DENEMECI", [
        ["x", "01.02.2024", "Dosyanın Açılması", "", ""], _query("01.03.2024", CAR, "ISMAIL DENEMECI", "YOK")])),
    _file("2019/3", "(Kapatılan)Ankara 2. İcra Dairesi", _tabs("Takipsizlik", "ESKİ BORÇLU", [
        ["x", "01.07.2019", "Dosyanın Açılması", "", ""], ["x", "01.07.2021", "Dosya Kapatıldı", "x", ""]],
        kind="İlamlı Takip")),
    _file("2025/4", "Ankara 9. İcra Dairesi", None),  # UYAP bilgisi çekilmemiş
]


def _ask(question, files=FILES):
    return answer(files, question)


def test_requires_a_session():
    assert TestClient(app).post("/api/office/execution/ask", json={"question": "açık dosyalar"}).status_code == 401


def test_open_files_are_listed_with_the_uyap_status_as_evidence():
    out = _ask("Açık dosyalarım hangileri?")

    assert out["ok"] and out["understood"] == ["UYAP durumu: Açık"]
    assert [row["file_no"] for row in out["rows"]] == ["2025/1", "2024/2"]
    assert out["rows"][0]["facts"] == ["UYAP durumu: Açık"] and out["rows"][0]["debtors"] == ["AYŞE ÖRNEK"]
    assert [row["file_no"] for row in _ask("kapalı dosyalar")["rows"]] == ["2019/3"]
    assert [row["file_no"] for row in _ask("takipsizlik durumundaki dosyalar")["rows"]] == ["2019/3"]


def test_a_query_result_question_quotes_the_record_and_ignores_queries_about_the_creditor():
    out = _ask("Hangi dosyalarımda araç sorgusu VAR yazıyor?")

    assert out["understood"] == ["Araç sorgusu: VAR"]
    assert [row["file_no"] for row in out["rows"]] == ["2025/1"]
    assert out["rows"][0]["facts"] == ["Araç sorgusu: VAR · 05.10.2026 (AYŞE ÖRNEK)"]  # alacaklı hakkındaki "VAR" sayılmaz
    assert [row["file_no"] for row in _ask("araç sorgusu yok çıkan dosyalar")["rows"]] == ["2024/2"]
    assert [row["file_no"] for row in _ask("tapu sorgusu YOK olan dosyalar")["rows"]] == ["2025/1"]
    assert _ask("sgk sorgusu var çıkan dosyalar")["matched"] == 0


def test_idle_questions_filter_by_days_and_sort_without_promoting_unknown_dates():
    longest = _ask("En uzun süredir işlem yapılmayan dosyalar")
    assert longest["understood"] == ["Sıra: en uzun süredir işlem görmeyen önce"]
    assert [row["file_no"] for row in longest["rows"]] == ["2019/3", "2024/2", "2025/1"]
    assert longest["rows"][0]["facts"] == [f"Son işlem 01.07.2021 · {(TODAY - date(2021, 7, 1)).days} gün önce"]
    assert longest["not_evaluated"] == 1 and "UYAP bilgisi çekilmediği" in longest["note"]

    six_months = _ask("6 aydır işlem görmeyen açık dosyalar")
    assert six_months["understood"] == ["En az 180 gündür işlem yok", "UYAP durumu: Açık"]
    assert [row["file_no"] for row in six_months["rows"]] == ["2024/2"]
    assert [row["file_no"] for row in _ask("en son işlem yapılan dosyalar")["rows"]] == ["2025/1", "2024/2", "2019/3"]


def test_milestone_questions_work_for_present_and_absent_records():
    assert [row["file_no"] for row in _ask("kesinleşme bilgisi girilmiş dosyalar")["rows"]] == ["2025/1"]
    missing = _ask("Kesinleşme bilgisi girilmemiş dosyalar")
    assert missing["understood"] == ["Kesinleşme bilgisi: kayıt yok"]
    assert [row["file_no"] for row in missing["rows"]] == ["2024/2", "2019/3"]
    assert missing["rows"][0]["facts"] == ["Kesinleşme bilgisi: safahatta kayıt yok"]


def test_names_courts_and_follow_up_types_are_matched_without_turkish_letter_surprises():
    assert [row["file_no"] for row in _ask("ismail denemeci")["rows"]] == ["2024/2"]
    assert [row["file_no"] for row in _ask("kahramankazan dosyaları")["rows"]] == ["2024/2"]
    assert [row["file_no"] for row in _ask("AYSE ORNEK hangi dosyada")["rows"]] == ["2025/1"]
    assert [row["file_no"] for row in _ask("ilamlı takipler")["rows"]] == ["2019/3"]
    assert [row["file_no"] for row in _ask("ilamsız takiplerim")["rows"]] == ["2025/1", "2024/2"]


def test_counting_lists_everything_and_a_status_only_question_includes_files_without_uyap_details():
    everything = _ask("kaç dosyam var")
    assert everything["understood"] == ["Bütün icra dosyaları"] and everything["matched"] == 4 and everything["not_evaluated"] == 0


@pytest.mark.parametrize("question", ["hangi dosyalar", "??", "ve ile mi"])
def test_a_question_that_is_not_understood_is_refused_with_examples_instead_of_guessed(question):
    out = _ask(question)

    assert out["ok"] is False and out["rows"] == [] and out["matched"] == 0
    assert "tahminle cevap vermiyorum" in out["note"] and len(out["examples"]) >= 4


def test_an_unknown_word_is_searched_as_a_name_and_says_so():
    out = _ask("bugün hava nasıl")

    assert out["ok"] and out["matched"] == 0
    assert out["understood"] == ["Ad / birim / dosya no içinde: bugun hava nasil"]  # nasıl anlaşıldığı gösterilir


def test_parse_reports_how_the_question_was_understood():
    parsed, labels = parse("2 yıldır işlem yapılmayan kapalı dosyalarda tapu sorgusu var mı")
    assert labels == ["En az 730 gündür işlem yok", "UYAP durumu: Açık olmayan", "Tapu (TAKBİS) sorgusu: VAR"]
    assert parsed.names == []


# --- Veritabanı ile -------------------------------------------------------------------------------------------------------


@needs_db
def test_the_question_is_answered_only_from_the_callers_own_execution_files(db, monkeypatch):  # noqa: F811
    world = _world(db, monkeypatch)

    def add(owner, number, court, tabs):
        case_id = uuid4()
        world.become(None)
        world.connection.execute(
            "INSERT INTO office_cases (id, owner_id, case_no, esas_no, court, title) VALUES (%s, %s, %s, %s, %s, 'x')",
            (case_id, owner, number, number, court),
        )
        if tabs is not None:
            world.connection.execute(
                "INSERT INTO office_uyap_case_detail (case_id, owner_id, tabs, complete) VALUES (%s, %s, %s, true)", (case_id, owner, Jsonb(tabs)),
            )
        return case_id

    mine = add(world.alice, "2025/1", "Ankara 7. Genel İcra Dairesi", _tabs("Açık", "AYŞE ÖRNEK", [_query("05.10.2026", CAR, "AYŞE ÖRNEK", "VAR")]))
    add(world.alice, "2025/9", "Ankara 5. Sulh Hukuk Mahkemesi", _tabs("Açık", "AYŞE ÖRNEK", [_query("05.10.2026", CAR, "AYŞE ÖRNEK", "VAR")]))  # icra değil
    add(world.bob, "2025/2", "İstanbul İcra Dairesi", _tabs("Açık", "BAŞKA BORÇLU", [_query("05.10.2026", CAR, "BAŞKA BORÇLU", "VAR")]))

    out = execution.execution_ask(execution.AskBody(question="araç sorgusu var çıkan dosyalar"), world.alice)

    assert [row["case_id"] for row in out["rows"]] == [mine] and out["total_files"] == 1
    assert "BAŞKA BORÇLU" not in str(out)
    assert execution.execution_ask(execution.AskBody(question="ayşe örnek"), world.bob)["matched"] == 0
