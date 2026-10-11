"""Literal text search in owner-scoped, ready office document chunks (not an AI answer)."""

import re

from api.office_search import fold, like_pattern


def normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def content_pattern(query: str) -> str:
    return like_pattern(normalized_text(query))


def match_excerpt(content: str, query: str, *, page_number=None, section_title=None) -> dict | None:
    """Return bounded plain-text pieces, never HTML or an invented page number."""
    text = normalized_text(content)
    term = normalized_text(query)
    start = fold(text).find(fold(term)) if term else -1
    if start < 0:
        return None
    end = start + len(term)
    left, right = max(0, start - 110), min(len(text), end + 160)
    return {
        "before": ("…" if left else "") + text[left:start],
        "match": text[start:end],
        "after": text[end:right] + ("…" if right < len(text) else ""),
        "page_number": page_number,
        "section_title": section_title,
    }


# The source and derived document must belong to the same owner, in addition to RLS.
# Match all chunks, not only content_excerpt (which may contain just the opening text).
MATCH_JOIN = """
JOIN LATERAL (
    SELECT chunk.content, chunk.page_number, chunk.section_title
    FROM documents indexed
    JOIN document_chunks chunk ON chunk.document_id = indexed.id
    WHERE indexed.office_case_document_id = office_case_documents.id
      AND indexed.uploaded_by = office_case_documents.owner_id
      AND indexed.deleted_at IS NULL AND indexed.status = 'ready'
      AND lower(translate(regexp_replace(chunk.content, '\\s+', ' ', 'g'),
          'İIıŞÇĞÖÜ', 'iiişçğöü')) LIKE %s ESCAPE '\\'
    ORDER BY chunk.chunk_index, chunk.id
    LIMIT 1
) hit ON TRUE
"""


def search_coverage(connection, owner, *, source, category, selected_folder, category_sql) -> dict:
    """Coverage is for the selected archive filters, before the content query."""
    predicate = "TRUE"
    params = [owner]
    if source != "all":
        predicate += " AND origin = %s"
        params.append(source)
    if category:
        predicate += " AND category = %s"
        params.append(category)
    if selected_folder:
        predicate += " AND origin = %s AND folder_no IS NOT DISTINCT FROM %s AND folder_birim IS NOT DISTINCT FROM %s"
        params.extend(selected_folder)
    rows = connection.execute("""
        WITH scoped AS (
            SELECT od.id, indexed.status,
                CASE WHEN od.source IN ('uyap', 'uyap-avukat-eklentisi', 'uyap-extension') THEN 'uyap' ELSE 'manual' END AS origin,
                NULLIF(btrim(od.uyap_file_no), '') AS folder_no,
                NULLIF(btrim(od.uyap_birim), '') AS folder_birim,
                regexp_replace(translate(lower(COALESCE(NULLIF(btrim(od.doc_type), ''),
                    regexp_replace(regexp_replace(od.file_name, '^[0-9a-f]{12,64}[-_]', '', 'i'), '[.][^.]+$', ''))),
                    'çğıöşüİ', 'cgiosui'), '[^a-z0-9.]', '', 'g') AS kind,
                EXISTS (SELECT 1 FROM document_chunks chunk WHERE chunk.document_id = indexed.id) AS has_chunks
            FROM office_case_documents od
            LEFT JOIN documents indexed ON indexed.office_case_document_id = od.id
                AND indexed.uploaded_by = od.owner_id AND indexed.deleted_at IS NULL
            WHERE od.owner_id = %s AND od.deleted_at IS NULL
        ), categorized AS (SELECT *, """ + category_sql + """ AS category FROM scoped)
        SELECT status, has_chunks, count(*) AS n FROM categorized WHERE """ + predicate +
        " GROUP BY status, has_chunks", tuple(params)).fetchall()
    result = dict(total=0, ready=0, pending=0, failed=0)
    for row in rows:
        count = row["n"]
        result["total"] += count
        status = row["status"]
        key = "ready" if status == "ready" and row["has_chunks"] else (
            "failed" if status == "failed" else "pending"
        )
        result[key] += count
    return result
