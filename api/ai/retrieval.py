from __future__ import annotations

import re
from datetime import date

import psycopg

from api.ai.embeddings import vector_literal
from api.ai.rag import RAGContext
from api.ai.search_plan import plan_search
from api.ai.passages import is_duration_question, sentence_score
from api.ai.relevance import question_intent, intent_tsquery, relevant_contexts

_LAW_NO_RE = re.compile(r"(?<!\d)(\d{3,5})(?!\d)")
_ARTICLE_RE = re.compile(
    r"madde\s+(\d{1,3}[a-zA-Z]?)|(\d{1,3})\.\s*madd",
    re.IGNORECASE,
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

# Bedesten articles are only citation-eligible after both independent official
# catalogue checks. This also protects older rows written as "ready" before
# ingestion began enforcing verification state.
_VERIFIED_SOURCE_FILTER = """
(
    (
        ls.ingest_status = 'ready'
        AND (
            ls.source_type <> 'legislation'
            OR (
                ls.metadata->>'verified_against_gazette' = 'true'
                AND ls.metadata->>'verified_against_mbs' = 'true'
            )
        )
    )
    OR (
        ls.ingestion_method = 'bulk_seed'
        AND ls.ingest_status = 'pending'
        AND ls.source_type = 'court_decision'
    )
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
ORDER BY ranked.score DESC, {_RECENCY_ORDER}
"""


def _document_lexical_sql(search_ctes: str) -> str:
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
  AND document.project_id = %(project_id)s
  AND search_query.value IS NOT NULL
  AND chunk.search_vector @@ search_query.value
ORDER BY rank DESC, document.created_at DESC
LIMIT %(top_k)s
"""


DOCUMENT_LEXICAL_RETRIEVAL_SQL = _document_lexical_sql(_SEARCH_QUERY_CTES)
DOCUMENT_LEXICAL_BROAD_SQL = _document_lexical_sql(_BROAD_SEARCH_QUERY_CTES)

DOCUMENT_HYBRID_RETRIEVAL_SQL = f"""
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
      AND document.project_id = %(project_id)s
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
      AND document.project_id = %(project_id)s
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


def question_law_numbers(question: str) -> tuple[str, ...]:
    return tuple(_LAW_NO_RE.findall(question))


def question_article_numbers(question: str) -> tuple[str, ...]:
    found: list[str] = []
    for match in _ARTICLE_RE.finditer(question):
        value = match.group(1) or match.group(2)
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
_FULL_RETRIEVAL_TIMEOUT = "10s"
_BOUNDED_RETRIEVAL_TIMEOUT = "15s"
_BOUNDED_MAX_CANDIDATES = 60000


def _bounded_variant(sql: str) -> str:
    """Sözcük araması çağrısını, eşleşmelerin ilk N tanesini sıralayan sürümle değiştirir."""
    return _LEXICAL_HITS_CALL_RE.sub(
        lambda match: (
            f"legal_rag_current_lexical_hits_bounded({match.group(1)}, {_BOUNDED_MAX_CANDIDATES})"
        ),
        sql,
    )


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

    def run(name, sql, params, budget):
        nonlocal completed
        tick = monotonic()
        try:
            rows = _execute_retrieval(connection, sql, params, timeout=budget)
            completed += 1
            status = 'ok'
            return rows
        except psycopg.errors.QueryCanceled as exc:
            errors.append(exc)
            info['partial'] = True
            status = 'timeout'
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
    lexical = run('lexical', sql, params, '4s')
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
    project_id: str,
    top_k: int,
    query_embedding: list[float] | None = None,
    embedding_model: str | None = None,
) -> list[RAGContext]:
    plan = plan_search(question)
    params = {
        "question": plan.text,
        "required_phrase": plan.phrase,
        "project_id": project_id,
        "top_k": top_k,
        "candidate_limit": max(top_k * 4, 20),
    }
    if query_embedding is not None and embedding_model:
        params.update(
            {
                "embedding": vector_literal(query_embedding),
                "embedding_model": embedding_model,
            }
        )
        return _execute_retrieval(connection, DOCUMENT_HYBRID_RETRIEVAL_SQL, params)

    contexts = _execute_retrieval(connection, DOCUMENT_LEXICAL_RETRIEVAL_SQL, params)
    if not lexical_hits_insufficient(question, contexts, top_k):
        return contexts
    broad_params = {
        **params,
        "top_k": max(top_k * 10, 40),
        "candidate_limit": max(top_k * 10, 40),
    }
    broad = _execute_retrieval(connection, DOCUMENT_LEXICAL_BROAD_SQL, broad_params)
    return merge_lexical_hits(question, contexts, broad, top_k)
