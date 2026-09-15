from __future__ import annotations

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
    chunk.content
"""

_DETAIL_JOINS = """
LEFT JOIN court_decision_details decision ON decision.legal_source_id = ls.id
LEFT JOIN legislation_details legislation ON legislation.legal_source_id = ls.id
"""

_RECENCY_ORDER = "COALESCE(decision.decision_date, ls.published_at) DESC NULLS LAST"

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
    CROSS JOIN search_query
    WHERE ls.deleted_at IS NULL
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
    WHERE ls.deleted_at IS NULL
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


def retrieve_contexts(
    connection: psycopg.Connection,
    *,
    question: str,
    top_k: int,
    query_embedding: list[float] | None = None,
    embedding_model: str | None = None,
) -> list[RAGContext]:
    if query_embedding is not None and embedding_model:
        rows = connection.execute(
            HYBRID_RETRIEVAL_SQL,
            {
                "question": question,
                "top_k": top_k,
                "candidate_limit": max(top_k * 4, 20),
                "embedding": vector_literal(query_embedding),
                "embedding_model": embedding_model,
            },
        ).fetchall()
    else:
        rows = connection.execute(
            LEXICAL_RETRIEVAL_SQL,
            {"question": question, "top_k": top_k},
        ).fetchall()
    return [RAGContext(**row) for row in rows]
