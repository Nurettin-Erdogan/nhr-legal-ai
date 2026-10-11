"""UYAP dosya bilgilerinin asistana kaynak olması: dava başına "UYAP dosya bilgileri" belgesi (örnekler uydurmadır)."""

from __future__ import annotations

import contextlib
from datetime import date
from uuid import UUID, uuid4

import pytest
from psycopg.types.json import Jsonb

from api import uyap_record_document as record
from api.ai import pipeline
from api.ai.case_questions import is_case_file_question
from api.ai.evidence_selection import evidence_candidates
from api.ai.rag import RAGContext
from api.ai.relevance import document_hint, passage_relevant
from api.ai.source_support import source_sentences, unsupported_source_claims
from api.execution_overview import build_overview
from api.schemas import AIAnswerRequest
from tests.test_case_document_rag import _case, _indexed_document, db, needs_db  # noqa: F401  (fixture)

TODAY = date(2026, 10, 10)
HEADS = ["İşlem Yapan Birim", "Tarih", "İşlem Türü", "Açıklama", "İşlem Durumu"]
U = "Ankara 7. Genel İcra Dairesi"


def _q(day: str, kind: str, name: str, result: str | None) -> list[str]:
    text = f"[TC: 12345678901] Avukat DENEME VEKİL tarafından, {name} adlı kişi {kind}" + (f" Sorgu Sonucu: {result}" if result else "")
    return [U, day, kind, text, ""]


TABS = [
    {"key": "bilgiler", "pairs": [
        {"label": "Türü", "value": "İlamsız Takip"}, {"label": "Yolu", "value": "Genel Haciz Yoluyla Takip"},
        {"label": "Dosya Durumu", "value": "Açık"}], "tables": []},
    {"key": "hesap", "pairs": [
        {"label": "Toplam Alacak", "value": "₺13.783,00"}, {"label": "Yatan Para", "value": "₺0,00"},
        {"label": "Bakiye Borç Miktari", "value": "₺13.783,00"}, {"label": "Seç", "value": "Seçim Yapınız"}], "tables": []},
    {"key": "taraflar", "pairs": [], "tables": [{"headers": ["Rol", "Tipi", "Adı", "Vekil", "İşlem"], "rows": [
        ["Alacaklı", "Kurum", "DENEME ALACAK ANONİM ŞİRKETİ", "[Av. DENEME VEKİL]", ""],
        ["Borçlu", "Kişi", "AYŞE ÖRNEK", "", ""]]}]},
    {"key": "safahat", "pairs": [], "tables": [{"headers": HEADS, "rows": [
        [U, "01.02.2025", "Dosyanın Açılması", "", ""],
        [U, "02.02.2025", "Ödeme İcra Emri Evrağı Hazırlandı.", "Örnek 7 (Eski No 49) İlamsız Takiplerde Ödeme Emri (49) Hazirlandi.", ""],
        [U, "03.02.2025", "Tebligat Bilgileri Kaydedildi", "2700000000001 - Tebligat Bilgileri Kaydedildi [BORÇLU VE MÜFLİS AYŞE ÖRNEK ] tarafına - Kapalı Tebligat", ""],
        [U, "10.02.2025", "Tebligat Sonuç Bilgileri Kaydedildi", "Tebligat Sonuç Bilgileri Kaydedildi [BORÇLU VE MÜFLİS AYŞE ÖRNEK ] - 2700000000001 - Tebliğ Edildi", ""],
        [U, "21.02.2025", "Dosya Kesinleşme Bilgi Girişi.", "AYŞE ÖRNEK kesinlesme bilgisi kaydedildi.", ""],
        [U, "22.02.2025", "Tensip Zaptı Bilgi Girişi", "Tensip Zaptı Bilgi Girişi (Avukat Portal Haciz Talebi)", ""],
        _q("23.02.2025", "Araç Sahiplikten Sorgulandı.", "AYŞE ÖRNEK", "YOK"),
        _q("23.02.2025", "TAKBIS Bilgisi Sorgulandı.", "AYŞE ÖRNEK", "VAR"),
        _q("23.02.2025", "Taraf icin getSGKAktif4ASorgu laması yapıldı.", "AYŞE ÖRNEK", None),
        [U, "24.02.2025", "Bankaya Hesap Haciz İhbarnamesinin Hazırlanması(Tebligatlı).", "Bankaya Hesap Haciz İhbarnamesinin Hazırlanması(Tebligatlı).", ""],
        [U, "30.09.2026", "Gelen Evrak Kaydedilmesi", "89/1 Haciz İhbarnamesi Cevabı", ""]]}]},
    {"key": "tahsilat", "pairs": [], "tables": [{"headers": ["Tahsilat", "Reddiyat", "Tahsilat Kalanı"], "rows": [["162,5 TL", "162,5 TL", "0 TL"]]}]},
]


# --- Belge metni ----------------------------------------------------------------------------------------------------------


def _sections():
    return record.record_sections(TABS, build_overview(TABS, complete=True, fetched_at=None, today=TODAY))


def _contexts():
    return [
        RAGContext(chunk_id=uuid4(), source_id=uuid4(), source_type="document", title="UYAP dosya bilgileri", source_url=None,
                   authority="UYAP dosya bilgisi", court_name=None, chamber=None, docket_no=None, decision_no=None, decision_date=None,
                   law_name=None, law_no=None, article_no=None, article_title=name, content=text, rank=1.0, verification="user_document")
        for name, text in _sections()
    ]


def _relevant(question):
    return [
        context for context in _contexts()
        if any(passage_relevant(question, unit, source_type="document", document_hint=document_hint(context)) for unit in source_sentences(context))
    ]


def test_the_record_is_written_as_label_value_lines_without_identity_numbers_or_daily_values():
    sections = dict(_sections())

    assert list(sections) == ["Künye", "Taraflar", "Dosya hesabı", "Sorgular", "İşlemler", "Tebligatlar", "Son safahat kayıtları"]
    assert "Borçlu: AYŞE ÖRNEK (Kişi); vekil kaydı yok" in sections["Taraflar"].splitlines()
    assert "Alacaklı: DENEME ALACAK ANONİM ŞİRKETİ (Kurum); vekili Av. DENEME VEKİL" in sections["Taraflar"].splitlines()
    assert "Bakiye Borç Miktari: ₺13.783,00 (UYAP dosya hesabı)" in sections["Dosya hesabı"].splitlines()
    assert not any(line.startswith("Seç") for line in sections["Dosya hesabı"].splitlines())
    assert "Tapu (TAKBİS) sorgusu: AYŞE ÖRNEK (Borçlu) için yapılan sorguda UYAP kaydındaki son sonuç VAR, tarihi 23.02.2025" in sections["Sorgular"]
    assert "SGK aktif 4A sorgusu: AYŞE ÖRNEK (Borçlu) için sorgu yapılmış, kayıtta sonuç yazılmamış, son sorgu 23.02.2025" in sections["Sorgular"]
    assert "Kesinleşme bilgisi girildi: 21.02.2025" in sections["İşlemler"].splitlines()
    assert "sonuç Tebliğ Edildi, 10.02.2025" in sections["Tebligatlar"]
    everything = "\n".join(sections.values())
    assert "12345678901" not in everything and "[TC" not in everything
    assert "gün önce" not in everything  # her gün değişen değer belgeye yazılmaz (belge her gün yeniden üretilmesin)
    # Bir safahat kaydı tek birimdir: "… Sorgulandı. Sorgu Sonucu: YOK" ikiye bölünmez.
    history_units = source_sentences(_contexts()[-1])
    assert any(unit.startswith("Safahat 23.02.2025: Araç Sahiplikten Sorgulandı —") and unit.endswith("Sorgu Sonucu: YOK") for unit in history_units)


def test_an_empty_uyap_record_produces_no_sections():
    assert record.record_sections([], build_overview([], complete=False, fetched_at=None, today=TODAY)) == []


@pytest.mark.parametrize("question, section, expected", [
    ("Borçlu kim?", "Taraflar", "Borçlu: AYŞE ÖRNEK (Kişi); vekil kaydı yok"),
    ("Bu dosyada alacaklı kimdir?", "Taraflar", "Alacaklı: DENEME ALACAK ANONİM ŞİRKETİ (Kurum); vekili Av. DENEME VEKİL"),
    ("Bakiye borç ne kadar?", "Dosya hesabı", "Bakiye Borç Miktari: ₺13.783,00 (UYAP dosya hesabı)"),
    ("Araç sorgusunun sonucu ne?", "Sorgular", "Araç sorgusu: AYŞE ÖRNEK (Borçlu) için yapılan sorguda UYAP kaydındaki son sonuç YOK, tarihi 23.02.2025"),
    ("SGK sorgusu yapıldı mı?", "Sorgular", "SGK aktif 4A sorgusu: AYŞE ÖRNEK (Borçlu) için sorgu yapılmış, kayıtta sonuç yazılmamış, son sorgu 23.02.2025"),
    ("En son hangi işlem yapıldı?", "Künye", "Son işlem: en son yapılan işlem 30.09.2026 tarihli Gelen Evrak Kaydedilmesi — 89/1 Haciz İhbarnamesi Cevabı"),
    ("Takip kesinleşti mi?", "İşlemler", "Kesinleşme bilgisi girildi: 21.02.2025"),
    ("Dosya ne zaman açıldı?", "İşlemler", "Dosyanın açılması: 01.02.2025"),
    ("Dosya durumu nedir?", "Künye", "Dosya durumu: Açık"),
])
def test_typical_questions_find_their_line_and_the_line_passes_the_source_check(question, section, expected):
    contexts = _relevant(question)
    assert section in [context.article_title for context in contexts]

    chosen = next(item for item in evidence_candidates(question, contexts) if item.text == expected)

    # Model yalnız satır kimliği seçer; seçilen satır kaynak denetiminden aynen geçer, değiştirilmiş hâli geçmez.
    assert unsupported_source_claims(f"{chosen.text} [K{chosen.marker}]", contexts) == ()
    altered = chosen.text.replace("AYŞE", "FATMA").replace("DENEME", "BAŞKA").replace("2025", "2024").replace("2026", "2027").replace("Açık", "Kapalı").replace("13.783", "99.999")
    assert altered != chosen.text and unsupported_source_claims(f"{altered} [K{chosen.marker}]", contexts)


def test_a_question_about_something_else_takes_nothing_from_the_record():
    assert _relevant("Kira sözleşmesinin süresi ne kadar?") == []


def test_record_questions_stay_inside_the_file_but_legal_questions_do_not():
    for question in ("Safahatta en son ne var?", "UYAP'ta dosya durumu nedir?", "Bakiye borç ne kadar?", "Araç sorgusunun sonucu ne?"):
        assert is_case_file_question(question), question
    for question in ("Borçlu temerrüde düşerse ne olur?", "Haciz için hangi şartlar gerekir?"):
        assert not is_case_file_question(question), question


# --- Veritabanı ile -------------------------------------------------------------------------------------------------------


def _detail(world, owner, case_id, tabs):
    world.become(None)
    world.connection.execute(
        "INSERT INTO office_uyap_case_detail (case_id, owner_id, tabs, complete) VALUES (%s, %s, %s, true) "
        "ON CONFLICT (case_id) DO UPDATE SET tabs = EXCLUDED.tabs, fetched_at = now()", (case_id, owner, Jsonb(tabs)),
    )


def _records(world, case_id):
    world.become(None)
    return world.connection.execute(
        "SELECT id, deleted_at, file_name, (SELECT count(*) FROM document_chunks c WHERE c.document_id = d.id) AS chunks "
        "FROM documents d WHERE metadata ->> 'uyap_record_case_id' = %s", (str(case_id),),
    ).fetchall()


@needs_db
def test_the_record_document_is_written_once_and_replaced_only_when_uyap_data_changes(db):  # noqa: F811
    case_id = _case(db, db.alice)
    db.become(db.alice)
    assert record.ensure_record_document(db.connection, user_id=db.alice, case_id=case_id) is None  # UYAP bilgisi çekilmemiş
    _detail(db, db.alice, case_id, TABS)

    db.become(db.alice)
    first = record.ensure_record_document(db.connection, user_id=db.alice, case_id=case_id)
    again = record.ensure_record_document(db.connection, user_id=db.alice, case_id=case_id)

    assert first is not None and again == first  # içerik aynıysa yeniden yazılmaz
    rows = _records(db, case_id)
    assert [(row["deleted_at"] is None, row["chunks"]) for row in rows] == [(True, 7)]
    assert rows[0]["file_name"].startswith("UYAP dosya bilgileri (")

    changed = [{**TABS[0], "pairs": [{"label": "Dosya Durumu", "value": "Haricen Tahsil"}]}, *TABS[1:]]
    _detail(db, db.alice, case_id, changed)
    db.become(db.alice)
    second = record.ensure_record_document(db.connection, user_id=db.alice, case_id=case_id)

    assert second not in (None, first)
    states = {row["id"]: row["deleted_at"] is None for row in _records(db, case_id)}
    assert states == {first: False, second: True}  # eski belge silinmez, kapatılır: eski atıflar o günkü metni gösterir


@needs_db
def test_record_sections_reach_the_case_chat_only_for_the_owner_and_only_when_relevant(db, monkeypatch):  # noqa: F811
    @contextlib.contextmanager
    def as_user(user_id: str):
        db.become(UUID(user_id))
        yield db.connection

    monkeypatch.setattr(pipeline, "authenticated_database_connection", as_user)
    monkeypatch.setattr(pipeline, "sweep_unindexed", lambda *a, **k: 0)
    monkeypatch.setattr(pipeline, "case_document_coverage", lambda owner, case_id: {"case_id": str(case_id)})
    mine, theirs = _case(db, db.alice), _case(db, db.bob)
    _indexed_document(db, db.alice, mine, "Takip talebi: bakiye borç için borçlu aleyhine ilamsız takip başlatılması talep edilir.", name="takip-talebi.udf")
    _detail(db, db.alice, mine, TABS)
    _detail(db, db.bob, theirs, TABS)

    def ask(user, case_id, question):
        diagnostics: dict = {}
        contexts = pipeline._retrieve(AIAnswerRequest(question=question, case_id=case_id), user_id=user, query_embedding=None,
                                      top_k=6, embedding_model="m", diagnostics=diagnostics)
        return contexts, diagnostics

    contexts, diagnostics = ask(db.alice, mine, "Bakiye borç ne kadar?")
    assert contexts[0].article_title == "Dosya hesabı" and contexts[0].verification == "user_document"
    assert [context.title for context in contexts[1:]] == ["takip-talebi.udf"]  # evrak da aday kalır, UYAP kaydı önde
    assert diagnostics["uyap_record_sections"] == 1 and diagnostics["case_file_only"] is True
    assert "Bakiye Borç Miktari: ₺13.783,00 (UYAP dosya hesabı)" in contexts[0].content

    # Başkası, davanın kimliğini bilse de o davanın UYAP bilgisine ulaşamaz ve onun adına belge yazılmaz.
    db.become(db.bob)
    assert record.record_contexts(db.connection, user_id=db.bob, case_id=mine, question="Bakiye borç ne kadar?") == []
    db.become(db.alice)
    assert record.record_contexts(db.connection, user_id=db.alice, case_id=theirs, question="Bakiye borç ne kadar?") == []
    assert _records(db, theirs) == []

    # Kaydı dosyada duran soru başka davaların kararlarına gitmez (hukuki değerlendirme isteyen soru gider).
    searched: list[str] = []
    monkeypatch.setattr(pipeline, "retrieve_contexts", lambda *a, **k: searched.append(k["question"]) or [])
    monkeypatch.setattr(pipeline, "_case_statute_contexts", lambda *a, **k: [])
    contexts, diagnostics = ask(db.alice, mine, "Takip kesinleşti mi?")
    assert diagnostics["case_file_only"] is True and searched == []
    assert "Kesinleşme bilgisi girildi: 21.02.2025" in contexts[0].content
    _unused, diagnostics = ask(db.alice, mine, "Takibin kesinleşmesi için hangi şartlar gerekir?")
    assert diagnostics["case_file_only"] is False and len(searched) == 1

    # UYAP kaydıyla ilgisi olmayan soruda kayıt araya girmez.
    _unused, diagnostics = ask(db.alice, mine, "Kira sözleşmesinin süresi ne kadar?")
    assert diagnostics["uyap_record_sections"] == 0


def test_lines_from_the_uyap_record_are_never_rewritten_by_the_explanation_step():
    from api.ai.explanation import explain_verified_answer
    from api.ai.verification import verify_answer

    class Rewriter:
        calls = 0

        def generate(self, **kwargs):
            Rewriter.calls += 1
            return '{"claims":[{"text":"Alacaklı Deneme Alak Anonim Şirketidir.","sources":[1]}]}'

    context = next(c for c in _contexts() if c.article_title == "Taraflar")
    context = RAGContext(**{**{name: getattr(context, name) for name in context.__dataclass_fields__}, "authority": record.RECORD_AUTHORITY})
    line = "Alacaklı: DENEME ALACAK ANONİM ŞİRKETİ (Kurum); vekili Av. DENEME VEKİL"
    answer = verify_answer(f"{line} [K1]", [context], question="Alacaklı kimdir?")
    assert answer.grounded

    explained = explain_verified_answer(Rewriter(), question="Alacaklı kimdir?", answer=answer)

    assert explained.text == answer.text and Rewriter.calls == 0  # ad ve tutar aynen kalır; model hiç çağrılmaz
