"""UYAP dosya bilgisinden dava listesinin boş kalan alanları: dava türü ve karşı taraf.

UYAP aktarımı dava kaydını yalnız esas no ve birimle açar; "Tür" ve "Karşı taraf" sütunları boş kalıyordu. Burada yalnız UYAP'ın kendi
yazdığı değerler okunur, hukuki yorum yapılmaz:

- Dava türü: "Dosya Bilgileri" sekmesindeki "Türü" satırı (ör. "İlamsız Takip").
- Karşı taraf: "Taraf Bilgileri" tablosunda hesabın kendi kişisi (bağlı UYAP kimliğinin adı) bir tarafsa, ters roldeki taraflar
  (Alacaklı ↔ Borçlu, Davacı ↔ Davalı, Sanık ↔ Katılan/Mağdur/Müşteki/İhbar Eden). Hesap sahibi tarafta yoksa ya da rol çiftlenemiyorsa
  karşı taraf yazılmaz (tahmin edilmez).

Mevcut dolu alanlar ezilmez; yalnız boş (NULL) alan doldurulur.
"""

from __future__ import annotations

from typing import Any

_FOLD = str.maketrans({"İ": "i", "I": "i", "ı": "i", "Ç": "c", "ç": "c", "Ğ": "g", "ğ": "g", "Ö": "o", "ö": "o", "Ş": "s", "ş": "s", "Ü": "u", "ü": "u"})

# Rol → karşısındaki roller (UYAP'ın "Rol" sütunundaki yazımlar; katlanmış, küçük harf).
_OPPOSITES: dict[str, frozenset[str]] = {
    "alacakli": frozenset({"borclu"}),
    "borclu": frozenset({"alacakli"}),
    "davaci": frozenset({"davali"}),
    "davali": frozenset({"davaci"}),
    "sanik": frozenset({"katilan", "magdur", "musteki", "ihbar eden"}),
    "suca suruklenen cocuk": frozenset({"katilan", "magdur", "musteki", "ihbar eden"}),
    "katilan": frozenset({"sanik"}),
    "magdur": frozenset({"sanik"}),
    "musteki": frozenset({"sanik"}),
    "ihbar eden": frozenset({"sanik"}),
}
MAX_NAMES = 3
MAX_LENGTH = 300


def fold(text: str) -> str:
    return " ".join(str(text).translate(_FOLD).lower().split())


def _tab(tabs: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    return next((tab for tab in tabs if tab.get("key") == key), None)


def case_type(tabs: list[dict[str, Any]]) -> str | None:
    """"Dosya Bilgileri" sekmesindeki "Türü" değeri; yoksa None."""
    tab = _tab(tabs, "bilgiler")
    for pair in (tab or {}).get("pairs", []):
        if fold(pair.get("label", "")) == "turu" and str(pair.get("value", "")).strip():
            return " ".join(str(pair["value"]).split())[:100]
    return None


# UYAP "Dosya Durumu" → uygulama durumu. Yalnız anlamı açık olanlar eşlenir: "Açık" → aktif; "Kapalı" ve UYAP'ın kapanış nedeni olarak
# yazdığı takipsizlik/haricen tahsil/feragat/takibin iptali → kapalı. Diğer değerler ("İnfaz", "Karara Çıkmış", "Borcun Tamamının
# Ödenmemesi" gibi) dosyanın açık mı kapalı mı olduğunu söylemediği için eşlenmez (beklemede kalır).
_OPEN_STATES = {"acik"}
_CLOSED_STATES = ("kapali", "takipsizlik", "haricen tahsil", "feragat", "takibin iptali")
AUTO_NOTE_PREFIX = "UYAP "


def file_status(tabs: list[dict[str, Any]]) -> str | None:
    """"Dosya Bilgileri" > "Dosya Durumu" değerinden "active" | "closed"; eşlenemezse None."""
    tab = _tab(tabs, "bilgiler")
    for pair in (tab or {}).get("pairs", []):
        if fold(pair.get("label", "")) != "dosya durumu":
            continue
        value = fold(pair.get("value", ""))
        if value in _OPEN_STATES:
            return "active"
        if any(marker in value for marker in _CLOSED_STATES):
            return "closed"
    return None


def opponent(tabs: list[dict[str, Any]], own_names: list[str]) -> str | None:
    """Hesap sahibinin tarafına ters roldeki tarafların adları ("A, B ve 2 kişi daha"); belirlenemezse None."""
    tab = _tab(tabs, "taraflar")
    if not tab or not own_names:
        return None
    own = {fold(name) for name in own_names if name.strip()}
    rows: list[tuple[str, str]] = []  # (rol, ad)
    for table in tab.get("tables", []):
        headers = [fold(header) for header in table.get("headers", [])]
        if "rol" not in headers or "adi" not in headers:
            continue
        role_at, name_at = headers.index("rol"), headers.index("adi")
        for row in table.get("rows", []):
            if len(row) > max(role_at, name_at):
                rows.append((fold(row[role_at]), " ".join(str(row[name_at]).split())))
    mine = {role for role, name in rows if fold(name) in own}
    if not mine:
        return None
    wanted = set().union(*(_OPPOSITES.get(role, frozenset()) for role in mine))
    if not wanted:
        return None
    names: list[str] = []
    for role, name in rows:
        if role in wanted and name and fold(name) not in own and name not in names:
            names.append(name)
    if not names:
        return None
    text = ", ".join(names[:MAX_NAMES])
    if len(names) > MAX_NAMES:
        text += f" ve {len(names) - MAX_NAMES} kişi daha"
    return text[:MAX_LENGTH]


def own_party(tabs: list[dict[str, Any]], own_names: list[str]) -> str | None:
    """Taraflar tablosunda hesap sahibinin kendi kişisinin (bağlı UYAP kimliği) yazılışı; tarafta değilse None."""
    tab = _tab(tabs, "taraflar")
    own = {fold(name) for name in own_names if name.strip()}
    if not tab or not own:
        return None
    for table in tab.get("tables", []):
        headers = [fold(header) for header in table.get("headers", [])]
        if "adi" not in headers:
            continue
        at = headers.index("adi")
        for row in table.get("rows", []):
            if len(row) > at and fold(row[at]) in own:
                return " ".join(str(row[at]).split())[:200]
    return None


def readable_title(own: str | None, other: str | None, court: str) -> str | None:
    """"Taraf – Karşı taraf · Birim" (her iki taraf da biliniyorsa); yoksa None (başlık değişmez)."""
    if not own or not other:
        return None
    return f"{own} – {other.split(',')[0].split(' ve ')[0]} · {court}"[:300]


def apply_fields(connection: Any, owner_id: Any, case_id: Any, tabs: list[dict[str, Any]], own_names: list[str]) -> dict[str, bool]:
    """Dava kaydındaki boş alanları doldurur: tür, karşı taraf, müvekkil (hesap sahibinin kendi kişisi) ve otomatik başlığı okunur başlıkla değiştirir.

    Dolu alan ezilmez. Başlık yalnız UYAP'ın otomatik yazdığı "esas · birim" biçimindeyse (kullanıcı değiştirmediyse) yenilenir. Müvekkil
    kaydı yoksa hesap sahibinin adıyla açılır (not düşülür); aynı ad varsa o kullanılır.
    """
    case = connection.execute(
        "SELECT title, case_no, court, client_id, case_type, opponent, status, notes FROM office_cases WHERE id = %s", (case_id,)
    ).fetchone()
    if case is None:
        return {}
    kind = None if case["case_type"] else case_type(tabs)
    other = case["opponent"] or opponent(tabs, own_names)
    new_opponent = None if case["opponent"] else other
    mine = own_party(tabs, own_names)
    client_id = case["client_id"]
    created_client = False
    if client_id is None and mine:
        existing = connection.execute("SELECT id, full_name FROM office_clients WHERE owner_id = %s", (owner_id,)).fetchall()
        match = next((row["id"] for row in existing if fold(row["full_name"]) == fold(mine)), None)
        if match is None:
            from uuid import uuid4

            match = uuid4()
            connection.execute(
                "INSERT INTO office_clients (id, owner_id, full_name, client_type, notes) VALUES (%s, %s, %s, 'individual', %s)",
                (match, owner_id, mine, "UYAP kimliğinizden otomatik oluşturuldu; müvekkil ilişkisini kontrol edin."),
            )
            created_client = True
        client_id = match
    title = None
    auto = f"{case['case_no']} · {case['court']}"
    if case["title"] == auto:
        title = readable_title(mine, other, case["court"] or "")
    # Durum: yalnız UYAP'ın kendi açtığı ve hiç değiştirilmemiş ("beklemede" + otomatik not) dava UYAP'ın söylediği durumla güncellenir.
    status = None
    if case["status"] == "pending" and str(case["notes"] or "").startswith(AUTO_NOTE_PREFIX):
        status = file_status(tabs)
    changed = {"type": bool(kind), "opponent": bool(new_opponent), "client": client_id != case["client_id"], "title": bool(title),
               "status": bool(status), "client_created": created_client}
    if any(changed[key] for key in ("type", "opponent", "client", "title", "status")):
        connection.execute(
            "UPDATE office_cases SET case_type = COALESCE(case_type, %s), opponent = COALESCE(opponent, %s), "
            "client_id = COALESCE(client_id, %s), title = COALESCE(%s, title), status = COALESCE(%s, status) WHERE id = %s",
            (kind, new_opponent, client_id, title, status, case_id),
        )
    return changed
