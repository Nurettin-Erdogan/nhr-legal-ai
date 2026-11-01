"""UYAP dosya bilgisinden dava türü ve karşı taraf (api.uyap_case_fields)."""

from __future__ import annotations

from api.uyap_case_fields import case_type, opponent

HEADERS = ["Rol", "Tipi", "Adı", "Vekil", "İşlem"]


def _tabs(rows, pairs=None):
    return [
        {"key": "bilgiler", "pairs": pairs or [{"label": "Türü", "value": "İlamsız Takip"}], "tables": []},
        {"key": "taraflar", "pairs": [], "tables": [{"headers": HEADERS, "rows": rows}]},
    ]


ROWS = [
    ["Alacaklı", "Kurum", "SEVETA TİC", "[ADEM DOĞRUER]", ""],
    ["Aracı Kişi Kurum", "Kurum", "DORUK LTD", "", ""],
    ["Borçlu", "Kişi", "ATİLLA POYRAZ", "", ""],
    ["Borçlu", "Kişi", "DOĞAN POYRAZ", "", ""],
]


def test_case_type_comes_from_the_file_information_tab():
    assert case_type(_tabs(ROWS)) == "İlamsız Takip"
    assert case_type(_tabs(ROWS, pairs=[{"label": "Yolu", "value": "x"}])) is None
    assert case_type([]) is None


def test_opponent_is_the_opposite_role_of_the_account_holders_own_party():
    assert opponent(_tabs(ROWS), ["Atilla Poyraz"]) == "SEVETA TİC"
    assert opponent(_tabs(ROWS), ["ATİLLA POYRAZ"]) == "SEVETA TİC"


def test_opponent_is_not_guessed_when_the_account_holder_is_not_a_party():
    assert opponent(_tabs(ROWS), ["BAŞKA KİŞİ"]) is None
    assert opponent(_tabs(ROWS), []) is None


def test_long_opponent_lists_are_summarised_and_neutral_roles_are_ignored():
    rows = [["Davacı", "Kişi", "AYŞE", "", ""]] + [["Davalı", "Kişi", f"KİŞİ {i}", "", ""] for i in range(5)] + [["Üçüncü Şahıs", "Kişi", "X", "", ""]]
    assert opponent(_tabs(rows), ["Ayşe"]) == "KİŞİ 0, KİŞİ 1, KİŞİ 2 ve 2 kişi daha"
    assert opponent(_tabs([["Üçüncü Şahıs", "Kişi", "AYŞE", "", ""]]), ["Ayşe"]) is None


def test_own_party_and_readable_title():
    from api.uyap_case_fields import own_party, readable_title

    assert own_party(_tabs(ROWS), ["atilla poyraz"]) == "ATİLLA POYRAZ"
    assert own_party(_tabs(ROWS), ["Başka"]) is None
    assert readable_title("ATİLLA POYRAZ", "SEVETA TİC, ABC ve 2 kişi daha", "İstanbul 20. İcra Dairesi") == (
        "ATİLLA POYRAZ – SEVETA TİC · İstanbul 20. İcra Dairesi"
    )
    assert readable_title(None, "X", "Y") is None
    assert readable_title("A", None, "Y") is None


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, case, clients):
        self.case, self.clients, self.writes = case, clients, []

    def execute(self, sql, params=()):
        if sql.startswith("SELECT title"):
            return _Cursor([self.case])
        if sql.startswith("SELECT id, full_name"):
            return _Cursor(self.clients)
        self.writes.append((sql.split()[0], params))
        return _Cursor([])


def test_apply_fields_fills_only_empty_fields_and_creates_the_own_client_once():
    from api.uyap_case_fields import apply_fields

    case = {"title": "2023/1 · İstanbul 20. İcra Dairesi", "case_no": "2023/1", "court": "İstanbul 20. İcra Dairesi", "client_id": None,
            "case_type": None, "opponent": None, "status": "pending", "notes": "UYAP evrak aktarımından oluşturuldu."}
    connection = _Connection(case, [])
    changed = apply_fields(connection, "owner", "case", _tabs(ROWS), ["ATİLLA POYRAZ"])
    assert changed == {"type": True, "opponent": True, "client": True, "title": True, "status": False, "client_created": True}
    assert [kind for kind, _ in connection.writes] == ["INSERT", "UPDATE"]

    filled = dict(case, client_id="c1", case_type="Kendi türüm", opponent="Kendi karşı tarafım", title="Elle yazdığım başlık")
    connection = _Connection(filled, [])
    changed = apply_fields(connection, "owner", "case", _tabs(ROWS), ["ATİLLA POYRAZ"])
    assert not any(changed.values()) and connection.writes == []


def test_file_status_maps_only_unambiguous_uyap_states():
    from api.uyap_case_fields import file_status

    def tabs(value):
        return [{"key": "bilgiler", "pairs": [{"label": "Dosya Durumu", "value": value}], "tables": []}]

    assert file_status(tabs("Açık")) == "active"
    assert file_status(tabs("Kapalı")) == "closed"
    assert file_status(tabs("Takipsizlik")) == "closed"
    assert file_status(tabs("Haricen Tahsil Nedeniyle")) == "closed"
    assert file_status(tabs("7420 Sayılı Kanunun Geçici 2.Maddesi Kapsamında Feragat")) == "closed"
    for unclear in ("İnfaz", "Karara Çıkmış", "Borcun Tamamının Ödenmemesi", ""):
        assert file_status(tabs(unclear)) is None


def test_apply_fields_updates_status_only_for_untouched_uyap_cases():
    from api.uyap_case_fields import apply_fields

    tabs = _tabs(ROWS) + []
    tabs[0]["pairs"] = [{"label": "Dosya Durumu", "value": "Kapalı"}]
    base = {"title": "x", "case_no": "1", "court": "c", "client_id": "c1", "case_type": "t", "opponent": "o"}
    untouched = _Connection(dict(base, status="pending", notes="UYAP evrak aktarımından oluşturuldu."), [])
    assert apply_fields(untouched, "owner", "case", tabs, [])["status"] is True
    edited = _Connection(dict(base, status="pending", notes="Müvekkille görüşüldü."), [])
    assert apply_fields(edited, "owner", "case", tabs, [])["status"] is False
    chosen = _Connection(dict(base, status="active", notes="UYAP evrak aktarımından oluşturuldu."), [])
    assert apply_fields(chosen, "owner", "case", tabs, [])["status"] is False
