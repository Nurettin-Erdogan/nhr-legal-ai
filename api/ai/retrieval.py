from __future__ import annotations

import re
from datetime import date

import psycopg

from api.ai.embeddings import vector_literal
from api.ai.rag import RAGContext
from api.ai.search_plan import plan_search
from api.ai.passages import is_duration_question, sentence_score
from api.ai.relevance import question_intent, intent_tsquery, focused_intent_tsquery, relevant_contexts
from api.ai.seed_tier import seed_tier
from api.ai.workspace_scope import project_document_predicate

_LAW_NO_RE = re.compile(r"(?<!\d)(\d{3,5})(?!\d)")
_ARTICLE_RE = re.compile(
    # "madde 18", "18. madde", ve avukatların kısa yazımı "m. 18" / "m.18" / "md. 18".
    r"madde\s+(\d{1,3}[a-zA-Z]?)|(\d{1,3})\.\s*madd|(?<![0-9A-Za-zÇĞİÖŞÜçğıöşü])md?\.\s*(\d{1,3})(?!\d)",
    re.IGNORECASE,
)

# Numarası yazılmadan ADIYLA anılan temel kanunlar ("Anayasanın 36. maddesi", "TBK m. 344", "İİK m. 67"). Bu tablo hukuki
# içerik değildir; yalnız hangi kanunun maddesinin getirileceğini söyler, madde metni yine korpustaki resmî kayıttan okunur.
# Her numara 2026-10-08'de korpustaki resmî mevzuat kaydının adıyla karşılaştırılarak doğrulandı (ör. 2709 = TÜRKİYE
# CUMHURİYETİ ANAYASASI, 4857 = İŞ KANUNU). Belirsiz kısaltmalar bilerek yoktur ("TMK": Medeni Kanun da Terörle Mücadele
# Kanunu da olabilir). Desenler `normalize` edilmiş (küçük harf) metne uygulanır.
_NAMED_LAWS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), law_no)
    for pattern, law_no in (
        (r"\banayasa(?!\s+mahkeme)", "2709"),
        (r"(?<!deniz )(?<!basın )(?<!basin )\biş kanunu", "4857"),
        (r"\bborçlar kanunu|\btbk\b", "6098"),
        (r"\bmedeni kanun", "4721"),
        (r"\btürk ceza kanunu|\btck\b", "5237"),
        (r"\bceza muhakemesi kanunu|\bcmk\b", "5271"),
        (r"\bhukuk muhakemeleri kanunu|\bhmk\b", "6100"),
        (r"\bicra (?:ve )?iflas kanunu|\biik\b", "2004"),
        (r"\bidari yargılama usulü kanunu|\biyuk\b", "2577"),
        (r"\btürk ticaret kanunu|\bttk\b", "6102"),
        (r"\btüketicinin korunması hakkında kanun|\btkhk\b", "6502"),
        (r"\bkişisel verilerin korunması kanunu|\bkvkk\b", "6698"),
        (r"\bkat mülkiyeti kanunu", "634"),
        (r"\bkarayolları trafik kanunu", "2918"),
        (r"\biş mahkemeleri kanunu", "7036"),
        (r"\bkamu denetçiliği kurumu kanunu", "6328"),
    )
)
_KDK_INTENT_RE = re.compile(r"kamu denetçi|\bkdk\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[0-9A-Za-zÇĞİÖŞÜçğıöşüâîûÂÎÛ]+")
_SKIP_LEXEMES = (
    "sayıl",
    "kanun",
    "madde",
    "maddes",
    "neler",
    "nasıl",
    "hangi",
    "kadar",
    "neyi",
    "düzen",
    "koşul",
    "nedir",
    "olan",
    "olarak",
    "üzere",
)
_SKIP_SQL = ", ".join("'" + token.replace("'", "''") + "'" for token in _SKIP_LEXEMES)
_BOILERPLATE_WORDS = frozenset(
    {
        *_SKIP_LEXEMES,
        "nelerdir",
        "nasildir",
        "hangisi",
        "kimdir",
        "kimde",
        "kimdedir",
        "hakkında",
        "karşı",
        "göre",
        "şekilde",
    }
)


# Both legal source subtypes are joined optionally so legislation and court
# decisions compete in the same ranking; a source carries exactly one of them.
_SELECT_COLUMNS = """
    chunk.id AS chunk_id,
    ls.id AS source_id,
    ls.source_type,
    ls.title,
    ls.source_url,
    ls.authority,
    COALESCE(decision.court_name, CASE WHEN ls.source_type = 'other' THEN ls.authority END) AS court_name,
    decision.chamber,
    decision.docket_no,
    COALESCE(
        decision.decision_no,
        CASE WHEN ls.source_type = 'other' THEN ls.metadata->>'decision_no' END
    ) AS decision_no,
    COALESCE(
        decision.decision_date,
        CASE WHEN ls.source_type = 'other'
             THEN NULLIF(ls.metadata->>'decision_date', '')::date END
    ) AS decision_date,
    legislation.law_name,
    legislation.law_no,
    legislation.article_no,
    legislation.article_title,
    legislation.version_date,
    ls.effective_from,
    ls.effective_to,
    ls.source_version,
    ls.revision,
    CASE
        WHEN ls.ingestion_method = 'bulk_seed' AND ls.ingest_status = 'pending'
            THEN 'third_party'
        ELSE 'official'
    END AS verification,
    chunk.chunk_index,
    chunk.content
"""

_DETAIL_JOINS = """
LEFT JOIN court_decision_details decision ON decision.legal_source_id = ls.id
LEFT JOIN legislation_details legislation ON legislation.legal_source_id = ls.id
"""

_RECENCY_ORDER = "COALESCE(decision.decision_date, ls.published_at) DESC NULLS LAST"

# Preserve all content terms after removing question boilerplate. Known compound
# concepts are mandatory phrases; their words must not be confused with unrelated
# occurrences (e.g. ortak cocuk ... velayet).
_TOKEN_CTES = f"""
tokens AS (
    SELECT token, ord
    FROM (
        SELECT unnest(lexemes) AS token,
               row_number() OVER () AS ord
        FROM ts_debug('turkish', %(question)s)
        WHERE lexemes IS NOT NULL
    ) parsed
    WHERE char_length(token) >= 4
      AND token NOT IN ({_SKIP_SQL})
),
numbers AS (
    SELECT DISTINCT match[1] AS token
    FROM regexp_matches(%(question)s, '\\m[0-9]{{3,5}}\\M', 'g') AS match
)
"""


def _search_query_ctes(*, joiner: str, token_limit: int | None) -> str:
    if token_limit is None:
        token_select = "SELECT token FROM tokens"
    else:
        token_select = (
            "SELECT token FROM ("
            "SELECT token FROM tokens ORDER BY ord "
            f"LIMIT {int(token_limit)}"
            ") limited"
        )
    return f"""
{_TOKEN_CTES},
search_query AS (
    SELECT CASE
        WHEN EXISTS (SELECT 1 FROM tokens)
          OR EXISTS (SELECT 1 FROM numbers)
        THEN to_tsquery(
            'turkish',
            NULLIF(
                array_to_string(
                    ARRAY(
                        SELECT token FROM (
                            {token_select}
                            UNION
                            SELECT token FROM numbers
                        ) parts
                    ),
                    '{joiner}'
                ),
                ''
            )
        )
        ELSE NULL
    END AS value
)
"""


_ALL_TERMS_CTES = _search_query_ctes(joiner=" & ", token_limit=None)
_SEARCH_QUERY_CTES = _ALL_TERMS_CTES.replace("search_query AS (", "base_query AS (") + """,
search_query AS (
    SELECT CASE WHEN %(required_phrase)s = '' THEN value
                ELSE value && phraseto_tsquery('turkish', %(required_phrase)s)
           END AS value
    FROM base_query
)
"""
_BROAD_SEARCH_QUERY_CTES = _search_query_ctes(joiner=" | ", token_limit=None)
_LEGACY_OR_SEARCH_QUERY_CTES = """
search_query AS (
    SELECT to_tsquery(
        'turkish',
        NULLIF(
            array_to_string(
                tsvector_to_array(to_tsvector('turkish', %(question)s)),
                ' | '
            ),
            ''
        )
    ) AS value
)
"""

# Bedesten maddeleri resmî kataloglardan biriyle (Resmî Gazete ya da MBS) eşleşince atıf alabilir (kullanıcı kararı 2026-10-15).
# Doğrulanmamış toplu kararlar şimdilik aranmaz (kullanıcı kararı 2026-10-18); doğrulandıkça `ready` olarak girer.
_VERIFIED_SOURCE_FILTER = """
(
    (
        ls.ingest_status = 'ready'
        AND (
            ls.source_type <> 'legislation'
            OR (
                (
                    ls.metadata->>'verified_against_gazette' = 'true'
                    OR ls.metadata->>'verified_against_mbs' = 'true'
                )
                OR ls.metadata->>'verified_text_against_mbs' = 'true'
            )
        )
    )
    -- Doğrulanmamış toplu kayıtlar (`bulk_seed` + `pending`) şimdilik modele verilmez (kullanıcı kararı 2026-10-18).
)
"""

# Historical legislation is returned only when the official validity interval is
# known. `version_date` is useful audit metadata but is not treated as a legal
# effective date. Court decisions are bounded by their own decision date.
_TEMPORAL_FILTER = """
(
    (CAST(%(as_of)s AS date) IS NULL AND ls.is_current)
    OR
    (
        CAST(%(as_of)s AS date) IS NOT NULL
        AND (
            (
                ls.source_type = 'legislation'
                AND ls.effective_from IS NOT NULL
                AND ls.effective_from <= CAST(%(as_of)s AS date)
                AND (
                    ls.effective_to IS NULL
                    OR ls.effective_to >= CAST(%(as_of)s AS date)
                )
            )
            OR
            (
                ls.source_type = 'court_decision'
                AND ls.is_current
                AND decision.decision_date IS NOT NULL
                AND decision.decision_date <= CAST(%(as_of)s AS date)
            )
            OR
            (
                ls.source_type = 'other'
                AND ls.is_current
                AND ls.published_at IS NOT NULL
                AND ls.published_at <= CAST(%(as_of)s AS date)
            )
        )
    )
)
"""

_LEXICAL_HIT_FILTER = f"""
ls.deleted_at IS NULL
  AND {_VERIFIED_SOURCE_FILTER}
  AND search_query.value IS NOT NULL
  AND chunk.search_vector @@ search_query.value
"""

def _current_lexical_sql(search_ctes: str) -> str:
    return f"""
WITH {search_ctes},
ranked AS (
    SELECT hits.chunk_id AS id, hits.rank
    FROM search_query
    CROSS JOIN LATERAL legal_rag_current_lexical_hits(
        search_query.value,
        %(candidate_limit)s
    ) AS hits
    WHERE search_query.value IS NOT NULL
)
SELECT
{_SELECT_COLUMNS},
    ranked.rank
FROM ranked
JOIN legal_chunks chunk ON chunk.id = ranked.id
JOIN legal_sources ls ON ls.id = chunk.legal_source_id
{_DETAIL_JOINS}
WHERE {_VERIFIED_SOURCE_FILTER}
ORDER BY ranked.rank DESC, {_RECENCY_ORDER}
LIMIT %(top_k)s
"""


def _historical_lexical_sql(search_ctes: str) -> str:
    return f"""
WITH {search_ctes},
ranked AS (
    SELECT chunk.id,
           ts_rank_cd(chunk.search_vector, search_query.value) AS rank
    FROM legal_chunks chunk
    JOIN legal_sources ls ON ls.id = chunk.legal_source_id
    {_DETAIL_JOINS}
    CROSS JOIN search_query
    WHERE {_LEXICAL_HIT_FILTER}
      AND {_TEMPORAL_FILTER}
    ORDER BY rank DESC
    LIMIT %(candidate_limit)s
)
SELECT
{_SELECT_COLUMNS},
    ranked.rank
FROM ranked
JOIN legal_chunks chunk ON chunk.id = ranked.id
JOIN legal_sources ls ON ls.id = chunk.legal_source_id
{_DETAIL_JOINS}
ORDER BY ranked.rank DESC, {_RECENCY_ORDER}
LIMIT %(top_k)s
"""


LEXICAL_RETRIEVAL_SQL = _current_lexical_sql(_SEARCH_QUERY_CTES)
LEXICAL_BROAD_RETRIEVAL_SQL = _current_lexical_sql(_BROAD_SEARCH_QUERY_CTES)
LEXICAL_LEGACY_OR_SQL = _current_lexical_sql(_LEGACY_OR_SEARCH_QUERY_CTES)
LEXICAL_HISTORICAL_SQL = _historical_lexical_sql(_SEARCH_QUERY_CTES)
LEXICAL_HISTORICAL_BROAD_SQL = _historical_lexical_sql(_BROAD_SEARCH_QUERY_CTES)
LEXICAL_HISTORICAL_LEGACY_OR_SQL = _historical_lexical_sql(_LEGACY_OR_SEARCH_QUERY_CTES)

STATUTE_RETRIEVAL_SQL = f"""
SELECT
{_SELECT_COLUMNS},
    10.0::real AS rank
FROM legal_chunks chunk
JOIN legal_sources ls ON ls.id = chunk.legal_source_id
{_DETAIL_JOINS}
WHERE ls.deleted_at IS NULL
  AND {_VERIFIED_SOURCE_FILTER}
  AND ls.source_type = 'legislation'
  AND legislation.law_no = %(law_no)s
  AND legislation.article_no = %(article_no)s
  AND {_TEMPORAL_FILTER}
ORDER BY chunk.chunk_index
LIMIT %(top_k)s
"""

HYBRID_RETRIEVAL_SQL = f"""
WITH {_SEARCH_QUERY_CTES},
lexical AS (
    SELECT hits.chunk_id AS id,
           row_number() OVER (ORDER BY hits.rank DESC) AS position
    FROM search_query
    CROSS JOIN LATERAL legal_rag_current_lexical_hits(
        search_query.value,
        %(candidate_limit)s
    ) AS hits
    WHERE search_query.value IS NOT NULL
),
semantic AS (
    SELECT chunk.id,
           row_number() OVER (ORDER BY chunk.embedding <=> %(embedding)s::vector) AS position
    FROM legal_chunks chunk
    JOIN legal_sources ls ON ls.id = chunk.legal_source_id
    WHERE ls.deleted_at IS NULL
      AND {_VERIFIED_SOURCE_FILTER}
      AND ls.is_current
      AND chunk.embedding IS NOT NULL
      AND chunk.embedding_model = %(embedding_model)s
    ORDER BY position
    LIMIT %(candidate_limit)s
),
scores AS (
    SELECT id, 0.55 / (60 + position) AS score FROM lexical
    UNION ALL
    SELECT id, 0.45 / (60 + position) AS score FROM semantic
),
ranked AS (
    SELECT id, sum(score) AS score
    FROM scores
    GROUP BY id
    ORDER BY score DESC
    LIMIT %(top_k)s
)
SELECT
{_SELECT_COLUMNS},
    ranked.score AS rank
FROM ranked
JOIN legal_chunks chunk ON chunk.id = ranked.id
JOIN legal_sources ls ON ls.id = chunk.legal_source_id
{_DETAIL_JOINS}
WHERE {_VERIFIED_SOURCE_FILTER}
ORDER BY ranked.score DESC, {_RECENCY_ORDER}
"""

HYBRID_HISTORICAL_SQL = f"""
WITH {_SEARCH_QUERY_CTES},
lexical AS (
    SELECT chunk.id,
           row_number() OVER (
               ORDER BY ts_rank_cd(chunk.search_vector, search_query.value) DESC
           ) AS position
    FROM legal_chunks chunk
    JOIN legal_sources ls ON ls.id = chunk.legal_source_id
    {_DETAIL_JOINS}
    CROSS JOIN search_query
    WHERE {_LEXICAL_HIT_FILTER}
      AND {_TEMPORAL_FILTER}
    ORDER BY position
    LIMIT %(candidate_limit)s
),
semantic AS (
    SELECT chunk.id,
           row_number() OVER (ORDER BY chunk.embedding <=> %(embedding)s::vector) AS position
    FROM legal_chunks chunk
    JOIN legal_sources ls ON ls.id = chunk.legal_source_id
    {_DETAIL_JOINS}
    WHERE ls.deleted_at IS NULL
      AND {_VERIFIED_SOURCE_FILTER}
      AND {_TEMPORAL_FILTER}
      AND chunk.embedding IS NOT NULL
      AND chunk.embedding_model = %(embedding_model)s
    ORDER BY position
    LIMIT %(candidate_limit)s
),
scores AS (
    SELECT id, 0.55 / (60 + position) AS score FROM lexical
    UNION ALL
    SELECT id, 0.45 / (60 + position) AS score FROM semantic
),
ranked AS (
    SELECT id, sum(score) AS score
    FROM scores
    GROUP BY id
    ORDER BY score DESC
    LIMIT %(top_k)s
)
SELECT
{_SELECT_COLUMNS},
    ranked.score AS rank
FROM ranked
JOIN legal_chunks chunk ON chunk.id = ranked.id
JOIN legal_sources ls ON ls.id = chunk.legal_source_id
{_DETAIL_JOINS}
WHERE {_VERIFIED_SOURCE_FILTER}
ORDER BY ranked.score DESC, {_RECENCY_ORDER}
"""


# Belge aramasının kapsamı: bir proje, bir büro davası veya açık belge seçimi. Dava kapsamı, UYAP/büro belgelerinin
# türetilmiş kayıtlarını `office_case_documents.case_id` üzerinden bulur; belge başka davaya
# bağlanırsa kapsam kendiliğinden güncel kalır. RLS her iki durumda da yalnız erişilebilir
# belgeleri döndürür. Açık seçim varsa yalnız seçilen office_case_documents aranır;
# case_id ayrıca verildiyse seçimin bu davaya ait alt kümesiyle sınırlanır.
_DOCUMENT_SCOPE_PROJECT = "document.project_id = %(project_id)s"
_DOCUMENT_SCOPE_CASE = (
    "document.office_case_document_id IN "
    "(SELECT office_doc.id FROM office_case_documents AS office_doc "
    "WHERE office_doc.case_id = %(case_id)s AND office_doc.deleted_at IS NULL)"  # çöpteki belge aranmaz
)
_DOCUMENT_SCOPE_SELECTED = (
    "document.office_case_document_id IN "
    "(SELECT office_doc.id FROM office_case_documents AS office_doc "
    "WHERE office_doc.id = ANY(%(document_ids)s::uuid[]) AND office_doc.deleted_at IS NULL "
    "AND (%(case_id)s::uuid IS NULL OR office_doc.case_id = %(case_id)s) "
    "AND (%(office_project_id)s::uuid IS NULL OR " + project_document_predicate('office_doc') + "))"
)
_DOCUMENT_SCOPE_OFFICE_PROJECT = (
    "document.office_case_document_id IN (SELECT office_doc.id FROM office_case_documents office_doc "
    "WHERE office_doc.deleted_at IS NULL AND " + project_document_predicate('office_doc') + ")"
)


def _document_lexical_sql(search_ctes: str, scope: str = _DOCUMENT_SCOPE_PROJECT) -> str:
    return f"""
WITH {search_ctes}
SELECT
    chunk.id AS chunk_id,
    document.id AS source_id,
    'document'::text AS source_type,
    document.file_name AS title,
    NULL::text AS source_url,
    'Kullanıcı belgesi'::text AS authority,
    NULL::text AS court_name,
    NULL::text AS chamber,
    NULL::text AS docket_no,
    NULL::text AS decision_no,
    NULL::date AS decision_date,
    NULL::text AS law_name,
    NULL::text AS law_no,
    NULL::text AS article_no,
    chunk.section_title AS article_title,
    NULL::date AS version_date,
    NULL::date AS effective_from,
    NULL::date AS effective_to,
    NULL::text AS source_version,
    NULL::integer AS revision,
    'user_document'::text AS verification,
    chunk.content,
    ts_rank_cd(chunk.search_vector, search_query.value) AS rank,
    chunk.page_number
FROM document_chunks AS chunk
JOIN documents AS document ON document.id = chunk.document_id
CROSS JOIN search_query
WHERE document.deleted_at IS NULL
  AND document.status = 'ready'
  AND {scope}
  AND search_query.value IS NOT NULL
  AND chunk.search_vector @@ search_query.value
ORDER BY rank DESC, document.created_at DESC
LIMIT %(top_k)s
"""


DOCUMENT_LEXICAL_RETRIEVAL_SQL = _document_lexical_sql(_SEARCH_QUERY_CTES)
DOCUMENT_LEXICAL_BROAD_SQL = _document_lexical_sql(_BROAD_SEARCH_QUERY_CTES)
DOCUMENT_CASE_LEXICAL_RETRIEVAL_SQL = _document_lexical_sql(_SEARCH_QUERY_CTES, _DOCUMENT_SCOPE_CASE)
DOCUMENT_CASE_LEXICAL_BROAD_SQL = _document_lexical_sql(_BROAD_SEARCH_QUERY_CTES, _DOCUMENT_SCOPE_CASE)
DOCUMENT_SELECTED_LEXICAL_RETRIEVAL_SQL = _document_lexical_sql(_SEARCH_QUERY_CTES, _DOCUMENT_SCOPE_SELECTED)
DOCUMENT_SELECTED_LEXICAL_BROAD_SQL = _document_lexical_sql(_BROAD_SEARCH_QUERY_CTES, _DOCUMENT_SCOPE_SELECTED)
DOCUMENT_OFFICE_PROJECT_LEXICAL_SQL = _document_lexical_sql(_SEARCH_QUERY_CTES, _DOCUMENT_SCOPE_OFFICE_PROJECT)
DOCUMENT_OFFICE_PROJECT_BROAD_SQL = _document_lexical_sql(_BROAD_SEARCH_QUERY_CTES, _DOCUMENT_SCOPE_OFFICE_PROJECT)

def _document_hybrid_sql(scope: str = _DOCUMENT_SCOPE_PROJECT) -> str:
    return f"""
WITH {_SEARCH_QUERY_CTES},
lexical AS (
    SELECT chunk.id,
           row_number() OVER (
               ORDER BY ts_rank_cd(chunk.search_vector, search_query.value) DESC
           ) AS position
    FROM document_chunks AS chunk
    JOIN documents AS document ON document.id = chunk.document_id
    CROSS JOIN search_query
    WHERE document.deleted_at IS NULL
      AND document.status = 'ready'
      AND {scope}
      AND search_query.value IS NOT NULL
      AND chunk.search_vector @@ search_query.value
    ORDER BY position
    LIMIT %(candidate_limit)s
),
semantic AS (
    SELECT chunk.id,
           row_number() OVER (ORDER BY chunk.embedding <=> %(embedding)s::vector) AS position
    FROM document_chunks AS chunk
    JOIN documents AS document ON document.id = chunk.document_id
    WHERE document.deleted_at IS NULL
      AND document.status = 'ready'
      AND {scope}
      AND chunk.embedding IS NOT NULL
      AND chunk.embedding_model = %(embedding_model)s
    ORDER BY position
    LIMIT %(candidate_limit)s
),
scores AS (
    SELECT id, 0.55 / (60 + position) AS score FROM lexical
    UNION ALL
    SELECT id, 0.45 / (60 + position) AS score FROM semantic
),
ranked AS (
    SELECT id, sum(score) AS score
    FROM scores
    GROUP BY id
    ORDER BY score DESC
    LIMIT %(top_k)s
)
SELECT
    chunk.id AS chunk_id,
    document.id AS source_id,
    'document'::text AS source_type,
    document.file_name AS title,
    NULL::text AS source_url,
    'Kullanıcı belgesi'::text AS authority,
    NULL::text AS court_name,
    NULL::text AS chamber,
    NULL::text AS docket_no,
    NULL::text AS decision_no,
    NULL::date AS decision_date,
    NULL::text AS law_name,
    NULL::text AS law_no,
    NULL::text AS article_no,
    chunk.section_title AS article_title,
    NULL::date AS version_date,
    NULL::date AS effective_from,
    NULL::date AS effective_to,
    NULL::text AS source_version,
    NULL::integer AS revision,
    'user_document'::text AS verification,
    chunk.content,
    ranked.score AS rank,
    chunk.page_number
FROM ranked
JOIN document_chunks AS chunk ON chunk.id = ranked.id
JOIN documents AS document ON document.id = chunk.document_id
ORDER BY ranked.score DESC, document.created_at DESC
"""


DOCUMENT_HYBRID_RETRIEVAL_SQL = _document_hybrid_sql()
DOCUMENT_CASE_HYBRID_RETRIEVAL_SQL = _document_hybrid_sql(_DOCUMENT_SCOPE_CASE)
DOCUMENT_SELECTED_HYBRID_RETRIEVAL_SQL = _document_hybrid_sql(_DOCUMENT_SCOPE_SELECTED)
DOCUMENT_OFFICE_PROJECT_HYBRID_SQL = _document_hybrid_sql(_DOCUMENT_SCOPE_OFFICE_PROJECT)


def named_law_numbers(question: str) -> tuple[str, ...]:
    """Soruda adıyla geçen temel kanunların numaraları (yazım sırasına göre, yinelenmeden)."""
    from api.ai.search_plan import normalize

    value = normalize(question)
    hits = sorted(
        (match.start(), law_no) for pattern, law_no in _NAMED_LAWS for match in [pattern.search(value)] if match
    )
    found: list[str] = []
    for _, law_no in hits:
        if law_no not in found:
            found.append(law_no)
    return tuple(found)


def question_law_numbers(question: str) -> tuple[str, ...]:
    """Sorudaki kanun numaraları.

    Kanun numarası açıkça yazılmışsa ("4857 sayılı Kanun madde 18") yalnız o kullanılır. Yazılmamışsa ve soru bir MADDE
    numarası veriyorsa kanun adından çıkarılır: "Anayasanın 36. maddesi" → 2709, "TBK m. 344" → 6098. Madde numarası olmayan
    soruda ad eşlemesi yapılmaz (konu sorusunu "açık madde sorusu"na çevirmesin). Üç haneli madde numarası tek başına kanun
    numarası sanılmaz: "TBK 344. madde"de 344 kanun değil maddedir.
    """
    numbers = tuple(_LAW_NO_RE.findall(question))
    articles = question_article_numbers(question)
    if not articles:
        return numbers
    from api.ai.search_plan import normalize

    value = normalize(question)

    def is_explicit(number: str) -> bool:
        # Madde numarası kanun numarası değildir; yıl gibi görünen sayı ("2023 yılında …") ancak "sayılı" ile yazılmışsa kanundur
        # (2004 sayılı İcra ve İflas Kanunu gibi).
        if number in articles:
            return False
        year_like = len(number) == 4 and number[:2] in ("19", "20")
        return not year_like or re.search(rf"(?<!\d){number}\s*sayılı", value) is not None

    if any(is_explicit(number) for number in numbers):
        return numbers
    return named_law_numbers(question) or numbers


def question_article_numbers(question: str) -> tuple[str, ...]:
    found: list[str] = []
    for match in _ARTICLE_RE.finditer(question):
        value = match.group(1) or match.group(2) or match.group(3)
        if value:
            found.append(value.lower())
    return tuple(found)


def distinctive_question_words(question: str) -> tuple[str, ...]:
    words = [word for word in _WORD_RE.findall(question.casefold()) if len(word) >= 4]
    return tuple(word for word in words if word not in _BOILERPLATE_WORDS)


def _word_in_blob(word: str, blob: str) -> bool:
    if word in blob:
        return True
    stem = word[: max(4, len(word) - 2)]
    return len(stem) >= 4 and stem in blob


def _context_blob(context: RAGContext) -> str:
    parts = [
        context.reference_line,
        context.content,
        context.title,
        context.law_name or "",
        context.law_no or "",
        context.article_no or "",
        context.article_title or "",
        context.authority or "",
        context.court_name or "",
    ]
    return " ".join(parts).casefold()


def _article_in_context(context: RAGContext, article: str) -> bool:
    wanted = article.casefold()
    if context.article_no and context.article_no.casefold() == wanted:
        return True
    blob = _context_blob(context)
    return (
        f"m. {wanted}" in blob
        or f"m.{wanted}" in blob
        or f"madde {wanted}" in blob
    )


def lexical_hits_insufficient(
    question: str,
    contexts: list[RAGContext],
    top_k: int,
) -> bool:
    """True when lexical hits are insufficient (mandatory phrases never relax)."""
    if len(contexts) < max(1, top_k):
        return True
    blob = " ".join(_context_blob(context) for context in contexts)
    law_nos = question_law_numbers(question)
    articles = question_article_numbers(question)
    law_match = bool(law_nos) and any(number in blob for number in law_nos)
    article_match = bool(articles) and any(
        _article_in_context(context, article)
        for context in contexts
        for article in articles
    )
    if law_nos and not law_match:
        return True
    if law_nos and articles and not article_match:
        return True
    if law_match and (not articles or article_match):
        return False
    kdk_intent = bool(_KDK_INTENT_RE.search(question))
    if not kdk_intent and all(context.source_type == "other" for context in contexts):
        return True
    distinctive = distinctive_question_words(question)
    if distinctive:
        overlap = sum(1 for word in distinctive if _word_in_blob(word, blob))
        if overlap < min(2, len(distinctive)):
            return True
    return False


def _hit_quality_score(question: str, context: RAGContext) -> float:
    blob = _context_blob(context)
    law_match = any(number in blob for number in question_law_numbers(question))
    article_match = any(
        _article_in_context(context, article)
        for article in question_article_numbers(question)
    )
    overlap = sum(
        1 for word in distinctive_question_words(question) if _word_in_blob(word, blob)
    )
    score = float(context.rank or 0) * 0.05 + overlap * 2.0
    from api.ai.source_support import _sentences
    score += max((sentence_score(s, question) for s in _sentences(context.content, include_tail=False)), default=0)
    if law_match:
        score += 8.0
    if article_match:
        score += 6.0
    if overlap == 0 and not law_match:
        return score
    kdk_intent = bool(_KDK_INTENT_RE.search(question))
    if context.source_type == "legislation":
        score += 3.0
    elif context.source_type == "court_decision":
        score += 2.0
    elif context.source_type == "other":
        score += 2.0 if kdk_intent else 0.0
    return score


def _diversify_by_source(contexts: list[RAGContext], top_k: int) -> list[RAGContext]:
    """Keep extra chunks only for the same legislation article; otherwise one hit per source."""
    selected: list[RAGContext] = []
    seen: set = set()
    overflow: list[RAGContext] = []
    for context in contexts:
        duplicate = context.source_id in seen
        if duplicate and context.source_type != "legislation":
            overflow.append(context)
            continue
        selected.append(context)
        seen.add(context.source_id)
        if len(selected) >= top_k:
            return selected[:top_k]
    for context in overflow:
        selected.append(context)
        if len(selected) >= top_k:
            break
    return selected[:top_k]


def merge_lexical_hits(
    question: str,
    narrow: list[RAGContext],
    broad: list[RAGContext],
    top_k: int,
) -> list[RAGContext]:
    combined: dict = {}
    for context in (*narrow, *broad):
        combined.setdefault(context.chunk_id, context)
    ranked = sorted(
        combined.values(),
        key=lambda context: _hit_quality_score(question, context),
        reverse=True,
    )
    return _diversify_by_source(ranked, top_k)


_LEXICAL_HITS_CALL_RE = re.compile(
    r"legal_rag_current_lexical_hits\(((?:[^()]|%\(\w+\))*)\)"
)
# Tam sıralı sözcük araması soğuk diskte zaman aşımına uğrarsa katmanlı sürüme düşülür: resmî
# katman yine tam puanlanır, doğrulanmamış toplu katmanda yalnız ilk _TIERED_SEED_CAP eşleşme
# puanlanır (docs/legal-search-performance.md). Sonuç "partial" işaretlenir.
_TIERED_RETRY_TIMEOUT = "4s"
_TIERED_SEED_CAP = 3000
# Katmanlı sürüm de yetişmezse yalnız resmî katman (toplu katman atlanır). Ölçüldü (2026-10-10): arkada yoğun veri işi
# çalışırken toplu katmanın 31 GB'lık dizini bellekte kalamıyor; tek bir aramada dizin taraması 5,6 sn, satır okuması 4,9 sn
# sürüp 8 sn'lik süreyi aşıyordu, oysa resmî katman aynı sorguda 0,26 sn'de bitiyordu. Cevap yalnız doğrulanmış kaynağa
# dayandığı için resmî katmanla dönmek, 10 sn bekleyip hiç sonuç alamamaktan iyidir; sonuç "partial" işaretlenir.
_OFFICIAL_ONLY_TIMEOUT = "4s"
# Yalnız resmî katmana düşüldüğünde puanlanan en çok eşleşme: yük altında 5 000 parçanın puanlanması da 4 sn'yi aşabiliyor
# (ölçüldü: 2026-10-10), 1 500 parça ~1,5 sn sürer. Olağan soruda resmî eşleşme bunun altındadır (ölçülen: 222, 636).
_OFFICIAL_ONLY_CAP = 1500
# Tam sıralı aramaya verilen ilk süre. Yetişen sorgular 0,2-1,1 sn'de bitiyor; yetişmeyenler 8 sn'lik bütçenin
# tamamını boşa harcayıp sonra katmanlı sürümden <1 sn'de cevap alıyordu (altı olağan sorunun üçünde ölçüldü:
# 2026-10-08). Katmanlı sürümde resmî katman yine tam puanlandığı için (5 000 eşleşmeye kadar) erken geçiş cevabın
# dayandığı doğrulanmış kaynakları değiştirmez; yalnız doğrulanmamış toplu katman örneklenir ve sonuç "partial" olur.
_FULL_RANKING_FIRST_BUDGET_MS = 2500


def _tiered_variant(sql: str, seed_cap: int = _TIERED_SEED_CAP, official_cap: int | None = None) -> str:
    """Tam sıralı sözcük araması çağrısını katmanlı sürümle değiştirir (`official_cap` verilmezse fonksiyonun varsayılanı)."""
    tail = "" if official_cap is None else f", {int(official_cap)}"
    return _LEXICAL_HITS_CALL_RE.sub(
        lambda match: f"legal_rag_current_lexical_hits_tiered({match.group(1)}, {int(seed_cap)}{tail})",
        sql,
    )


def _capped_budget(budget: str, limit_ms: int) -> str:
    """Süre bütçesini ("8s", "5200ms") verilen üst sınırla kırpar."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(ms|s)\s*", budget)
    if not match:
        return budget
    milliseconds = float(match.group(1)) * (1000 if match.group(2) == "s" else 1)
    return f"{int(min(milliseconds, limit_ms))}ms"


def _run_retrieval(connection: psycopg.Connection, sql: str, params: dict, timeout: str):
    # Savepoint: zaman aşımı yalnız bu sorguyu geri alır, çağıranın işlemini bozmaz.
    with connection.transaction():
        connection.execute(f"SET LOCAL statement_timeout = '{timeout}'")
        return connection.execute(sql, params).fetchall()


def _execute_retrieval(
    connection: psycopg.Connection,
    sql: str,
    params: dict,
    *,
    timeout: str = "15s",
) -> list[RAGContext]:
    try:
        connection.execute("SET jit TO off")
        # Varsayılan 4 MB work_mem ile yüz binlerce eşleşen parçanın sıralanması diske taşar;
        # 64 MB bunu belirgin biçimde azaltır.
        connection.execute("SET work_mem TO '64MB'")
    except psycopg.Error:
        pass
    # Rank against the full searchable corpus, not an arbitrary first 6,000 rows.
    # A timeout is an explicit failure, never a silently incomplete result set.
    rows = _run_retrieval(connection, sql, params, timeout)
    return [RAGContext(**row) for row in rows]


def _lexical_sql(*, historical: bool, mode: str) -> str:
    if mode == "broad":
        return LEXICAL_HISTORICAL_BROAD_SQL if historical else LEXICAL_BROAD_RETRIEVAL_SQL
    if mode == "legacy_or":
        return LEXICAL_HISTORICAL_LEGACY_OR_SQL if historical else LEXICAL_LEGACY_OR_SQL
    return LEXICAL_HISTORICAL_SQL if historical else LEXICAL_RETRIEVAL_SQL


def _retrieve_statute_contexts(
    connection: psycopg.Connection,
    *,
    question: str,
    top_k: int,
    as_of: date | None,
) -> list[RAGContext]:
    law_nos = question_law_numbers(question)
    articles = question_article_numbers(question)
    if not law_nos or not articles:
        return []
    return _execute_retrieval(
        connection,
        STATUTE_RETRIEVAL_SQL,
        {
            "law_no": law_nos[0],
            "article_no": articles[0],
            "top_k": top_k,
            "as_of": as_of,
        },
    )


def _retrieve_legacy_contexts(
    connection: psycopg.Connection,
    *,
    question: str,
    top_k: int,
    query_embedding: list[float] | None = None,
    embedding_model: str | None = None,
    as_of: date | None = None,
    lexical_mode: str = "auto",
) -> list[RAGContext]:
    plan = plan_search(question)
    pool_size = max(top_k * 4, 24)
    params = {
        "question": plan.text,
        "required_phrase": plan.phrase,
        "top_k": pool_size,
        "candidate_limit": pool_size,
        "as_of": as_of,
    }
    historical = as_of is not None
    if query_embedding is not None and embedding_model:
        params.update(
            {
                "embedding": vector_literal(query_embedding),
                "embedding_model": embedding_model,
            }
        )
        sql = HYBRID_HISTORICAL_SQL if historical else HYBRID_RETRIEVAL_SQL
        return merge_lexical_hits(question, _execute_retrieval(connection, sql, params), [], top_k)

    mode = lexical_mode if lexical_mode != "auto" else "narrow"
    contexts = _execute_retrieval(
        connection,
        _lexical_sql(historical=historical, mode=mode),
        params,
    )
    if lexical_mode != "auto":
        return contexts[:top_k]

    if plan.phrase and is_duration_question(question):
        # A duration may be written as 'bir sene' rather than the question's
        # 'süresi'. Search that intent too, but NEVER drop the legal compound.
        duration_ctes = _SEARCH_QUERY_CTES.replace(
            "END AS value\n    FROM base_query",
            "END && to_tsquery('turkish', 'gün | ay | yıl | sene | hafta') AS value\n    FROM base_query",
        )
        duration_sql = _lexical_sql(historical=historical, mode="narrow").replace(
            _SEARCH_QUERY_CTES, duration_ctes
        )
        try:
            extra = _execute_retrieval(connection, duration_sql, params, timeout="4s")
        except psycopg.errors.QueryCanceled:
            # Optional intent expansion must not discard successful primary hits.
            extra = []
        contexts = merge_lexical_hits(question, contexts, extra, pool_size)

    contexts = merge_lexical_hits(question, contexts, [], top_k)
    statute = _retrieve_statute_contexts(
        connection, question=question, top_k=top_k, as_of=as_of
    )
    if statute:
        contexts = merge_lexical_hits(question, statute, contexts, top_k)
    elif question_law_numbers(question) and question_article_numbers(question):
        # An explicit statute/article question must be answered from that exact,
        # verified provision.  Court decisions mentioning the same numbers are
        # not a safe substitute for the text of the provision itself.
        return []
    if plan.phrase or not lexical_hits_insufficient(question, contexts, top_k):
        return contexts

    broad_params = {
        **params,
        "top_k": max(top_k * 10, 40),
        "candidate_limit": max(top_k * 10, 40),
    }
    broad = _execute_retrieval(
        connection,
        _lexical_sql(historical=historical, mode="broad"),
        broad_params,
    )
    return merge_lexical_hits(question, contexts, broad, top_k)


# ANN candidate retrieval must order directly by the distance operator before
# ranking. A row_number over every embedding prevents a bounded nearest-neighbor
# plan. RLS, model identity, source status and temporal rules are preserved.
SEMANTIC_RETRIEVAL_SQL = f"""
WITH nearest AS MATERIALIZED (
    SELECT chunk.id, chunk.embedding <=> %(embedding)s::vector AS distance
    FROM legal_chunks chunk
    JOIN legal_sources ls ON ls.id = chunk.legal_source_id
    {_DETAIL_JOINS}
    WHERE chunk.embedding IS NOT NULL
      AND chunk.embedding_model = %(embedding_model)s
      AND ls.deleted_at IS NULL
      AND {_VERIFIED_SOURCE_FILTER}
      AND {_TEMPORAL_FILTER}
    ORDER BY chunk.embedding <=> %(embedding)s::vector
    LIMIT %(candidate_limit)s
)
SELECT {_SELECT_COLUMNS}, (1.0 - nearest.distance)::real AS rank
FROM nearest
JOIN legal_chunks chunk ON chunk.id = nearest.id
JOIN legal_sources ls ON ls.id = chunk.legal_source_id
{_DETAIL_JOINS}
ORDER BY nearest.distance, chunk.id
"""


def retrieve_contexts(
    connection: psycopg.Connection, *, question: str, top_k: int,
    query_embedding: list[float] | None = None, embedding_model: str | None = None,
    as_of: date | None = None, lexical_mode: str = "auto", diagnostics: dict | None = None,
) -> list[RAGContext]:
    """Selective full-corpus lexical + optional ANN search; never unbounded OR.

    Hints are NOT legal evidence. A mapped statute must exist and pass the same
    official/current/version filters as an explicit reference. Failed optional
    branches don't discard successful results. If every branch times out, expose
    the failure rather than pretend the corpus contains no relevant sources.
    """
    if lexical_mode != "auto":
        return _retrieve_legacy_contexts(
            connection, question=question, top_k=top_k, as_of=as_of,
            query_embedding=query_embedding, embedding_model=embedding_model,
            lexical_mode=lexical_mode,
        )
    from time import monotonic
    info = diagnostics if diagnostics is not None else {}
    info.update(branches=[], partial=False, semantic_requested=query_embedding is not None)
    started = monotonic()
    errors = []
    completed = 0

    def run(name, sql, params, budget, first_budget_ms=None):
        nonlocal completed
        tick = monotonic()
        tiered = _tiered_variant(sql)
        has_tiers = tiered != sql
        if first_budget_ms is not None and has_tiers:
            budget = _capped_budget(budget, first_budget_ms)
        # Sıra: tam sıralı sürüm; yetişmezse katmanlı sürüm (toplu katman örneklenir); o da yetişmezse yalnız resmî katman.
        # Hepsi düşerse hata sayılır ("kaynak yok" denmez). Her deneme: (sql, süre, durum adı, toplu katmanı sınırlı tarar mı).
        attempts = [(sql, budget, 'ok', False)]
        if has_tiers:
            official_only = _tiered_variant(sql, seed_cap=0, official_cap=_OFFICIAL_ONLY_CAP)
            if seed_tier.allow():
                attempts += [(tiered, _TIERED_RETRY_TIMEOUT, 'timeout_then_tiered', True),
                             (official_only, _OFFICIAL_ONLY_TIMEOUT, 'timeout_then_official', False)]
            else:
                # Toplu katman az önce art arda zaman aşımına uğradı (bkz. api.ai.seed_tier): bir süre hiç denenmez.
                attempts = [(official_only, _OFFICIAL_ONLY_TIMEOUT, 'official_only', False)]
        failure = None
        try:
            for attempt_sql, timeout, label, samples_seed_tier in attempts:
                try:
                    rows = _execute_retrieval(connection, attempt_sql, params, timeout=timeout)
                except psycopg.errors.QueryCanceled as exc:
                    failure = exc
                    info['partial'] = True
                    if samples_seed_tier:
                        seed_tier.record(False)
                    continue
                completed += 1
                status = label
                if label != 'ok':
                    info['partial'] = True
                if samples_seed_tier:
                    seed_tier.record(True)
                return rows
            status = 'timeout'
            errors.append(failure)
            return []
        finally:
            info['branches'].append(dict(name=name, status=locals().get('status', 'error'),
                                         seconds=round(monotonic()-tick, 3)))

    law_nos, articles = question_law_numbers(question), question_article_numbers(question)
    explicit = bool(law_nos and articles)
    intent = question_intent(question)
    reference = (law_nos[0], articles[0]) if explicit else (intent.statute if intent else None)
    statute = []
    if reference:
        statute = run('statute', STATUTE_RETRIEVAL_SQL, dict(law_no=reference[0],
                      article_no=reference[1], as_of=as_of, top_k=max(top_k, 8)), '3s')
        if explicit:
            info['seconds'] = round(monotonic()-started, 3)
            if errors and not completed:
                raise errors[0]
            return statute[:top_k]

    plan = plan_search(question)
    params = dict(question=plan.text, required_phrase=plan.phrase, as_of=as_of,
                  top_k=max(24, top_k*4), candidate_limit=max(24, top_k*4))
    if intent:
        params['intent_query'] = intent_tsquery(intent)
        ctes = "search_query AS (SELECT to_tsquery('turkish', %(intent_query)s) AS value)"
        sql = _historical_lexical_sql(ctes) if as_of else _current_lexical_sql(ctes)
    else:
        sql = _lexical_sql(historical=as_of is not None, mode='narrow')
    semantic = []
    if query_embedding is not None and embedding_model:
        semantic = run('semantic', SEMANTIC_RETRIEVAL_SQL,
                       dict(params, embedding=vector_literal(query_embedding),
                            embedding_model=embedding_model,
                            candidate_limit=min(192, max(96, top_k * 12))), '3s')
    # Embedding coverage is incomplete. Always query the text index as well:
    # finding a few ANN hits is not evidence that the remaining corpus is empty.
    # Each branch retains a deadline; a failed branch cannot erase other hits.
    focused_query = focused_intent_tsquery(question, intent) if intent else None
    lexical = []
    if focused_query:
        # Share one deadline across focused + broad search. Don't double the
        # worst-case latency and don't change source trust or temporal filters.
        lexical_started = monotonic()
        lexical = run('lexical_focused', sql, dict(params, intent_query=focused_query), '8s')
        eligible = relevant_contexts(question, lexical)
        sufficient = len({c.source_id for c in eligible}) >= top_k
        remaining_ms = int((8 - (monotonic() - lexical_started)) * 1000)
        info['lexical_strategy'] = 'statute_linked'
        if not sufficient and remaining_ms > 0 and info['branches'][-1]['status'] == 'ok':
            lexical += run('lexical', sql, params, f'{remaining_ms}ms')
            lexical = list({c.chunk_id: c for c in lexical}.values())
            info['lexical_strategy'] = 'statute_linked_then_broad'
        elif not sufficient:
            info['partial'] = True
    else:
        # Geniş arama: tam sıralı sürüme kısa ilk süre, yetişmezse katmanlı sürüm (bkz. _FULL_RANKING_FIRST_BUDGET_MS).
        # Maddeye bağlı odaklı aramanın (yukarıda) ölçülmüş ortak süresi değişmez.
        lexical = run('lexical', sql, params, '8s', _FULL_RANKING_FIRST_BUDGET_MS)
        info['lexical_strategy'] = 'broad'
    candidates = relevant_contexts(question, lexical + semantic)
    unique_candidates = {c.chunk_id: c for c in statute + lexical + semantic}
    relevant_ids = {c.chunk_id for c in relevant_contexts(question, list(unique_candidates.values()))}
    info.update(
        lexical_candidates=len(lexical), semantic_candidates=len(semantic),
        candidate_chunks=len(unique_candidates),
        candidate_documents=len({c.source_id for c in unique_candidates.values()}),
        irrelevant_chunks=len(unique_candidates) - len(relevant_ids),
        exhaustive=False,
    )
    # Reciprocal rank fusion avoids comparing arbitrary ts_rank and cosine units.
    if semantic:
        from dataclasses import replace
        ranks = {}
        for branch in (lexical, semantic):
            for position, context in enumerate(branch, 1):
                ranks[context.chunk_id] = ranks.get(context.chunk_id, 0) + 1 / (60 + position)
        candidates = [replace(c, rank=ranks[c.chunk_id]) for c in candidates]
    ranked = merge_lexical_hits(question, relevant_contexts(question, statute), candidates, top_k)
    # Preserve a matching verified provision even if high-frequency cases outrank it.
    if statute:
        provisions = relevant_contexts(question, statute)
        preferred = sorted(provisions, key=lambda c: _hit_quality_score(question, c), reverse=True)[:2]
        ids = {c.chunk_id for c in preferred}
        ranked = (preferred + [c for c in ranked if c.chunk_id not in ids])[:top_k]
    info['seconds'] = round(monotonic()-started, 3)
    info['returned'] = len(ranked)
    if not ranked and errors:
        raise errors[0]
    return ranked


def retrieve_document_contexts(
    connection: psycopg.Connection,
    *,
    question: str,
    project_id: str | None = None,
    case_id: str | None = None,
    document_ids: list[str] | None = None,
    office_project_id: str | None = None,
    top_k: int,
    query_embedding: list[float] | None = None,
    embedding_model: str | None = None,
) -> list[RAGContext]:
    """RLS altında proje, dava veya açık belge seçimi. Seçim dava kapsamını daraltabilir."""
    selected = bool(document_ids)
    scopes = sum(value is not None for value in (project_id, case_id, office_project_id))
    if (selected and (project_id is not None or scopes > 1)) or (not selected and scopes != 1):
        raise ValueError("Belge araması için project_id veya case_id'den tam biri verilmelidir")
    by_case = case_id is not None
    hybrid_sql = DOCUMENT_CASE_HYBRID_RETRIEVAL_SQL if by_case else DOCUMENT_HYBRID_RETRIEVAL_SQL
    lexical_sql = DOCUMENT_CASE_LEXICAL_RETRIEVAL_SQL if by_case else DOCUMENT_LEXICAL_RETRIEVAL_SQL
    broad_sql = DOCUMENT_CASE_LEXICAL_BROAD_SQL if by_case else DOCUMENT_LEXICAL_BROAD_SQL
    if office_project_id:
        hybrid_sql, lexical_sql, broad_sql = DOCUMENT_OFFICE_PROJECT_HYBRID_SQL, DOCUMENT_OFFICE_PROJECT_LEXICAL_SQL, DOCUMENT_OFFICE_PROJECT_BROAD_SQL
    if selected:
        hybrid_sql = DOCUMENT_SELECTED_HYBRID_RETRIEVAL_SQL
        lexical_sql = DOCUMENT_SELECTED_LEXICAL_RETRIEVAL_SQL
        broad_sql = DOCUMENT_SELECTED_LEXICAL_BROAD_SQL

    plan = plan_search(question)
    params = {
        "question": plan.text,
        "required_phrase": plan.phrase,
        "top_k": top_k,
        "candidate_limit": max(top_k * 4, 20),
    }
    params["case_id" if by_case else "project_id"] = case_id if by_case else project_id
    params['office_project_id'] = office_project_id
    if selected:
        params.update(document_ids=document_ids, case_id=case_id)
    if query_embedding is not None and embedding_model:
        params.update(
            {
                "embedding": vector_literal(query_embedding),
                "embedding_model": embedding_model,
            }
        )
        contexts = _execute_retrieval(connection, hybrid_sql, params)
    else:
        contexts = _execute_retrieval(connection, lexical_sql, params)
    # Hibrit yolun sözcük kolu sıkı (VE) eşleşir: "ne yazıyor?" gibi dolgu sözcüklü bir soruda
    # embedding'i henüz üretilmemiş parçalar hiç bulunamazdı. Kapsam kullanıcının kendi belgeleriyle
    # sınırlı olduğundan geniş (VEYA) yedek ucuzdur; her iki yolda da uygulanır.
    if not lexical_hits_insufficient(question, contexts, top_k):
        return contexts
    broad_params = {
        **params,
        "top_k": max(top_k * 10, 40),
        "candidate_limit": max(top_k * 10, 40),
    }
    broad = _execute_retrieval(connection, broad_sql, broad_params)
    return merge_lexical_hits(question, contexts, broad, top_k)
