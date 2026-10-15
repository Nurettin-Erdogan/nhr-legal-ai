"""KVKK erişim/taşınabilirlik hakkı: kullanıcının kendi verilerinin dışa aktarımı (JSON).

Yalnız çağıranın kendi satırları gelir (RLS, `authenticated_database_connection`). Dışa aktarma şunları ASLA içermez: parola özeti,
bağlantı anahtarları (UYAP eklenti anahtarı özeti), dosyaların sunucudaki iç yolları. Belge dosyalarının kendisi dahil değildir
(boyut): üst veriler ve metin özetleri gelir, dosyalar Dosyalar sayfasından indirilir. Satır sayısı tablo başına sınırlıdır ve sınır
aşılırsa bu `truncated` ile açıkça söylenir.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

MAX_ROWS = 20_000
EXCLUDED_TABLES = frozenset({"uyap_ingest_tokens"})  # anahtar özetleri dışa verilmez
EXCLUDED_COLUMNS = frozenset({"storage_path", "token", "token_hash", "token_prefix", "password_hash", "lease", "leased_until"})


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in EXCLUDED_COLUMNS}


def build_export(connection, user_id: UUID, tables: dict[str, str]) -> dict[str, Any]:
    """`tables`: arayüz adı -> gerçek tablo (api.office.TABLES). Tablo adları sabit listeden gelir, kullanıcı girdisi değildir."""
    user = connection.execute(
        "SELECT id, email, full_name, created_at, last_login_at FROM users WHERE id = %s", (user_id,)
    ).fetchone()
    office: dict[str, Any] = {}
    truncated: list[str] = []
    export_tables = {**tables, 'project_document_links':'office_project_documents'}
    for name, physical in sorted(export_tables.items()):
        if name in EXCLUDED_TABLES:
            continue
        rows = connection.execute(f'SELECT * FROM "{physical}" ORDER BY created_at LIMIT %s', (MAX_ROWS + 1,)).fetchall()
        if len(rows) > MAX_ROWS:
            truncated.append(name)
            rows = rows[:MAX_ROWS]
        office[name] = [_clean(dict(row)) for row in rows]

    conversations = connection.execute(
        "SELECT id, title, project_id, case_id, office_project_id, selected_document_ids, created_at FROM conversations WHERE created_by = %s AND deleted_at IS NULL ORDER BY created_at LIMIT %s",
        (user_id, MAX_ROWS + 1),
    ).fetchall()
    if len(conversations) > MAX_ROWS:
        truncated.append("conversations")
        conversations = conversations[:MAX_ROWS]
    messages: dict[UUID, list[dict[str, Any]]] = {}
    if conversations:
        for row in connection.execute(
            "SELECT conversation_id, role, content, model_name, created_at FROM messages "
            "WHERE conversation_id = ANY(%s) AND deleted_at IS NULL ORDER BY created_at",
            ([c["id"] for c in conversations],),
        ).fetchall():
            messages.setdefault(row["conversation_id"], []).append(
                {key: row[key] for key in ("role", "content", "model_name", "created_at")}
            )
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user": dict(user) if user else None,
        "office": office,
        "conversations": [{**dict(c), "messages": messages.get(c["id"], [])} for c in conversations],
        "truncated_tables": truncated,
        "notes": [
            "Belge dosyaları bu dışa aktarmaya dahil değildir; Dosyalar sayfasından tek tek indirilir.",
            "Parola, oturum ve eklenti bağlantı anahtarları güvenlik nedeniyle dışa aktarılmaz.",
        ],
    }
