from __future__ import annotations

from datetime import date

import psycopg

from api.ai.embeddings import vector_literal
from api.ai.rag import RAGContext


# Both legal source subtypes are joined optionally so legislation and court
# decisions compete in the same ranking; a source carries exactly one of them.
_SELECT_COLUMNS = """
    chunk.id AS chunk_id,
    ls.id AS source_id,
    ls.source_type,
    ls.title,
    ls.source_url,
    ls.authority,
    decision.court_name,
    decision.chamber,
    decision.docket_no,
    decision.decision_no,
    decision.decision_date,
    legislation.law_name,
    legislation.law_no,
    legislation.article_no,
    legislation.article_title,
    legislation.version_date,
    ls.effective_from,
    ls.effective_to,
    ls.source_version,
    ls.revision,
    chunk.content
"""

_DETAIL_JOINS = """
LEFT JOIN court_decision_details decision ON decision.legal_source_id = ls.id
LEFT JOIN legislation_details legislation ON legislation.legal_source_id = ls.id
"""

_RECENCY_ORDER = "COALESCE(decision.decision_date, ls.published_at) DESC NULLS LAST"

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
        )
    )
)
"""

LEXICAL_RETRIEVAL_SQL = f"""
WITH search_query AS (
    SELECT to_tsquery(
        'turkish',
        array_to_string(
            tsvector_to_array(to_tsvector('turkish', %(question)s)),
            ' | '
        )
    ) AS value
)
SELECT
{_SELECT_COLUMNS},
    ts_rank_cd(chunk.search_vector, search_query.value) AS rank
FROM legal_chunks chunk
JOIN legal_sources ls ON ls.id = chunk.legal_source_id
{_DETAIL_JOINS}
CROSS JOIN search_query
WHERE ls.deleted_at IS NULL
  AND {_TEMPORAL_FILTER}
  AND search_query.value IS NOT NULL
  AND chunk.search_vector @@ search_query.value
ORDER BY rank DESC, {_RECENCY_ORDER}
LIMIT %(top_k)s
"""

HYBRID_RETRIEVAL_SQL = f"""
WITH search_query AS (
    SELECT to_tsquery(
        'turkish',
        array_to_string(
            tsvector_to_array(to_tsvector('turkish', %(question)s)),
            ' | '
        )
    ) AS value
),
lexical AS (
    SELECT chunk.id,
           row_number() OVER (
               ORDER BY ts_rank_cd(chunk.search_vector, search_query.value) DESC
           ) AS position
    FROM legal_chunks chunk
    JOIN legal_sources ls ON ls.id = chunk.legal_source_id
    {_DETAIL_JOINS}
    CROSS JOIN search_query
    WHERE ls.deleted_at IS NULL
      AND {_TEMPORAL_FILTER}
      AND search_query.value IS NOT NULL
      AND chunk.search_vector @@ search_query.value
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

DOCUMENT_LEXICAL_RETRIEVAL_SQL = """
WITH search_query AS (
    SELECT to_tsquery(
        'turkish',
        array_to_string(
            tsvector_to_array(to_tsvector('turkish', %(question)s)),
            ' | '
        )
    ) AS value
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

DOCUMENT_HYBRID_RETRIEVAL_SQL = """
WITH search_query AS (
    SELECT to_tsquery(
        'turkish',
        array_to_string(
            tsvector_to_array(to_tsvector('turkish', %(question)s)),
            ' | '
        )
    ) AS value
),
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
    chunk.content,
    ranked.score AS rank,
    chunk.page_number
FROM ranked
JOIN document_chunks AS chunk ON chunk.id = ranked.id
JOIN documents AS document ON document.id = chunk.document_id
ORDER BY ranked.score DESC, document.created_at DESC
"""


def retrieve_contexts(
    connection: psycopg.Connection,
    *,
    question: str,
    top_k: int,
    query_embedding: list[float] | None = None,
    embedding_model: str | None = None,
    as_of: date | None = None,
) -> list[RAGContext]:
    params = {
        "question": question,
        "top_k": top_k,
        "candidate_limit": max(top_k * 4, 20),
        "as_of": as_of,
    }
    if query_embedding is not None and embedding_model:
        params.update(
            {
                "embedding": vector_literal(query_embedding),
                "embedding_model": embedding_model,
            }
        )
        rows = connection.execute(HYBRID_RETRIEVAL_SQL, params).fetchall()
    else:
        rows = connection.execute(LEXICAL_RETRIEVAL_SQL, params).fetchall()
    return [RAGContext(**row) for row in rows]


def retrieve_document_contexts(
    connection: psycopg.Connection,
    *,
    question: str,
    project_id: str,
    top_k: int,
    query_embedding: list[float] | None = None,
    embedding_model: str | None = None,
) -> list[RAGContext]:
    params = {
        "question": question,
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
        rows = connection.execute(DOCUMENT_HYBRID_RETRIEVAL_SQL, params).fetchall()
    else:
        rows = connection.execute(DOCUMENT_LEXICAL_RETRIEVAL_SQL, params).fetchall()
    return [RAGContext(**row) for row in rows]
