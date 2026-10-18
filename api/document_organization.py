"""Belge listesinde üst veriye dayalı, yeniden aktarım gerektirmeyen düzenleme.

Kategoriler içerik analizi veya hukuki değerlendirme değildir. UYAP evrak türü
önceliklidir; bulunmuyorsa dosya adı kullanılır. Aynı esas numarasını taşıyan
farklı birimler ayrı klasörlerdir; çalışma alanındaki dava ilişkisi değişmez.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from api.document_content_search import MATCH_JOIN, content_pattern, match_excerpt, search_coverage

CATEGORIES = {
    "financial": "Makbuz ve mali belgeler",
    "representation": "Vekâlet ve yetki belgeleri",
    "expert": "Bilirkişi ve raporlar",
    "notice": "Tebligatlar",
    "petition": "Dilekçeler ve başvurular",
    "decision": "Kararlar ve kesinleşme",
    "minutes": "Tutanak ve duruşma belgeleri",
    "enforcement": "İcra ve takip belgeleri",
    "correspondence": "Yazışmalar ve müzekkereler",
    "attachment": "Ekler",
    "other": "Diğer / türü belirsiz",
}

# Sabit düzenli ifadeler; kullanıcı girdisi SQL'e eklenmez. Dosya adındaki
# ASCII temizleme artıkları (O_deme, I_cra gibi) boşlukları kaldırarak eşleşir.
_RULES = (
    ("financial", "makbuz|harc|dekont|masraf|tahsilat|reddiyat"),
    ("representation", "vekalet|yetkibelgesi"),
    ("expert", "bilirkisi|rapor"),
    ("notice", "teblig|mazbata"),
    ("decision", "karar|ilam|kesinlesme"),
    ("petition", "dilekce|basvuru|itiraz|istinaf|temyiz|layiha"),
    ("minutes", "tutanak|durusma|tensip"),
    ("enforcement", "haciz|odemeemri|odemeicraemri|icraemri|takip|satis"),
    ("petition", "cevap|talep|beyan"),
    ("correspondence", "muzekkere|yazisma|dosyagonderme|talimat|yazi"),
    ("attachment", "^ek[0-9]*$|^ek[0-9]+[.]"),
)
_CATEGORY_SQL = "CASE " + " ".join(
    f"WHEN kind ~ '{pattern}' THEN '{category}'" for category, pattern in _RULES
) + " ELSE 'other' END"


def folder_key(origin: str, file_no: str | None, birim: str | None) -> str:
    return json.dumps([origin, file_no, birim], ensure_ascii=False, separators=(",", ":"))


def parse_folder(value: str) -> tuple[str, str | None, str | None]:
    try:
        parts = json.loads(value)
    except (ValueError, TypeError):
        parts = None
    if (
        not isinstance(parts, list)
        or len(parts) != 3
        or parts[0] not in ("uyap", "manual")
        or any(part is not None and not isinstance(part, str) for part in parts[1:])
        or any(isinstance(part, str) and len(part) > 200 for part in parts[1:])
    ):
        raise HTTPException(status_code=422, detail="Geçersiz belge klasörü")
    return tuple(parts)


UNKNOWN_ACCOUNT = "unknown"


def parse_account(value: str) -> UUID | str | None:
    """UYAP hesabı süzgeci: boş (hepsi), "unknown" (kimden geldiği bilinmeyen UYAP evrakı) ya da UYAP kişisinin kimliği."""
    if not value:
        return None
    if value == UNKNOWN_ACCOUNT:
        return UNKNOWN_ACCOUNT
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(status_code=422, detail="Geçersiz UYAP hesabı") from None


def organized_documents(
    connection: Any, owner: UUID, *, q: str, source: str, category: str,
    folder: str, order: str, offset: int, limit: int, summary_only: bool = False,
    search_in: str = "metadata", account: str = "",
) -> dict[str, Any]:
    if category and category not in CATEGORIES:
        raise HTTPException(status_code=422, detail="Geçersiz belge kategorisi")
    selected_account = parse_account(account)
    selected_folder = parse_folder(folder) if folder else None
    if search_in not in ("metadata", "content"):
        raise HTTPException(status_code=422, detail="Geçersiz arama kapsamı")
    content_search = search_in == "content"
    if content_search and q.strip() and len(q.strip()) < 2:
        raise HTTPException(status_code=422, detail="İçerik araması için en az 2 karakter yazın")
    term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{term}%"
    # RLS'e ek açık sahiplik ve aktif-belge filtresi: sayımlar da yalnız sahibinindir.
    join = MATCH_JOIN if content_search and q.strip() else ""
    hit_columns = "hit.content AS match_content, hit.page_number, hit.section_title," if join else ""
    match_where = "TRUE" if content_search else """(
        file_name ILIKE %s ESCAPE '\\' OR uyap_file_no ILIKE %s ESCAPE '\\'
        OR uyap_birim ILIKE %s ESCAPE '\\' OR doc_type ILIKE %s ESCAPE '\\')"""
    cte = """WITH matched AS (
        SELECT id, file_name, storage_path, size_bytes, source, uyap_file_no, uyap_birim,
               doc_type, doc_date, case_id, created_at, uyap_account_id, """ + hit_columns + """
               NULLIF(btrim(uyap_file_no), '') AS folder_no,
               NULLIF(btrim(uyap_birim), '') AS folder_birim,
               CASE WHEN source IN ('uyap', 'uyap-avukat-eklentisi', 'uyap-extension') THEN 'uyap' ELSE 'manual' END AS origin,
               regexp_replace(translate(lower(COALESCE(NULLIF(btrim(doc_type), ''),
                   regexp_replace(regexp_replace(file_name, '^[0-9a-f]{12,64}[-_]', '', 'i'), '[.][^.]+$', ''))),
                   'çğıöşüİ', 'cgiosui'), '[^a-z0-9.]', '', 'g') AS kind
        FROM office_case_documents """ + join + """
        WHERE owner_id = %s AND deleted_at IS NULL AND """ + match_where + """
    ), categorized AS (SELECT *, """ + _CATEGORY_SQL + " AS category FROM matched) "
    params: list[Any] = ([content_pattern(q), owner] if join else [owner]) if content_search else [owner, pattern, pattern, pattern, pattern]
    base_where = "TRUE"
    if source != "all":
        base_where += " AND origin = %s"
        params.append(source)
    # Dosyalar kimin UYAP'ından geldiyse onun altında (kullanıcı kararı 2026-10-16). Kişi sayımları bu süzgeçten önce alınır.
    account_facets = connection.execute(
        cte + "SELECT c.uyap_account_id, a.display_name, count(*) AS n, count(DISTINCT (c.folder_no, c.folder_birim)) AS files "
        "FROM categorized c LEFT JOIN office_uyap_accounts a ON a.id = c.uyap_account_id "
        "WHERE " + base_where.replace("origin", "c.origin") + " AND c.origin = 'uyap' "
        "GROUP BY c.uyap_account_id, a.display_name ORDER BY a.display_name NULLS LAST",
        tuple(params),
    ).fetchall()
    if selected_account == UNKNOWN_ACCOUNT:
        base_where += " AND origin = 'uyap' AND uyap_account_id IS NULL"
    elif selected_account is not None:
        base_where += " AND uyap_account_id = %s"
        params.append(selected_account)
    # Facet sayımları sayfalama öncesinde; ilk 50 belge bütün arşiv gibi sunulmaz.
    facets = connection.execute(
        cte + "SELECT origin, folder_no, folder_birim, category, uyap_account_id, count(*) AS n "
        "FROM categorized WHERE " + base_where +
        " GROUP BY origin, folder_no, folder_birim, category, uyap_account_id "
        "ORDER BY origin DESC, folder_birim NULLS LAST, folder_no NULLS LAST, category",
        tuple(params),
    ).fetchall()
    folders: dict[str, dict] = {}
    counts: dict[str, int] = {}
    total = 0
    for item in facets:
        key = folder_key(item["origin"], item["folder_no"], item["folder_birim"])
        group = folders.setdefault(key, {
            "key": key, "source": item["origin"], "file_no": item["folder_no"],
            "birim": item["folder_birim"], "count": 0,
            "matching_count": 0, "accounts": {},
        })
        group["count"] += item["n"]
        if item["origin"] == "uyap":
            account_key = str(item["uyap_account_id"]) if item["uyap_account_id"] else UNKNOWN_ACCOUNT
            group["accounts"][account_key] = group["accounts"].get(account_key, 0) + item["n"]
        counts[item["category"]] = counts.get(item["category"], 0) + item["n"]
        if (not category or item["category"] == category) and (not folder or key == folder_key(*selected_folder)):
            total += item["n"]
            group["matching_count"] += item["n"]
    where = base_where
    if category:
        where += " AND category = %s"
        params.append(category)
    if selected_folder:
        where += " AND origin = %s AND folder_no IS NOT DISTINCT FROM %s AND folder_birim IS NOT DISTINCT FROM %s"
        params.extend(selected_folder)
    sorting = {
        "recent": "created_at DESC, id DESC",
        "date_desc": "doc_date DESC NULLS LAST, created_at DESC, id DESC",
        "date_asc": "doc_date ASC NULLS LAST, created_at ASC, id ASC",
    }[order]
    rows = [] if summary_only else connection.execute(
        cte + "SELECT id, file_name, storage_path, size_bytes, source, uyap_file_no, uyap_birim, "
        "doc_type, doc_date, case_id, created_at, category, origin, folder_no, folder_birim " +
        (", match_content, page_number, section_title " if join else "") +
        "FROM categorized WHERE " + where + " ORDER BY " + sorting + " LIMIT %s OFFSET %s",
        (*params, limit, offset),
    ).fetchall()
    for row in rows:
        row["folder_key"] = folder_key(row.pop("origin"), row.pop("folder_no"), row.pop("folder_birim"))
        if join:
            row["content_match"] = match_excerpt(
                row.pop("match_content"), q, page_number=row.pop("page_number"),
                section_title=row.pop("section_title"),
            )
    names = {str(item["uyap_account_id"]): item["display_name"] for item in account_facets if item["uyap_account_id"]}
    for group in folders.values():
        # Dosyanın sahibi: evraklarının çoğunun geldiği UYAP kişisi (aynı dosya iki kişinin UYAP'ında da olabilir).
        counted = group.pop("accounts")
        owner_key = max(counted, key=counted.get) if counted else None
        group["account_id"] = owner_key
        group["account_name"] = names.get(owner_key) if owner_key and owner_key != UNKNOWN_ACCOUNT else None
    return {
        "rows": rows, "total": total, "folders": list(folders.values()),
        "accounts": [{"id": str(item["uyap_account_id"]) if item["uyap_account_id"] else UNKNOWN_ACCOUNT,
                      "name": item["display_name"], "count": item["n"], "files": item["files"]} for item in account_facets],
        "categories": [{"id": key, "label": label, "count": counts[key]}
                       for key, label in CATEGORIES.items() if counts.get(key)],
        "matched_total": sum(counts.values()),
        **({"content_coverage": search_coverage(
            connection, owner, source=source, category=category,
            selected_folder=selected_folder, category_sql=_CATEGORY_SQL,
        )} if content_search else {}),
    }
