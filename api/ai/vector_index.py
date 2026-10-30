"""Cheap, read-only readiness checks for shared legal ANN indexes."""
from time import monotonic
import psycopg

_TTL_SECONDS = 15
_cache = {}

INDEX_READY_SQL = """
SELECT EXISTS (
    -- İkili nicemlenmiş HNSW (anlam sorgusu bunu kullanır; bkz. retrieval.SEMANTIC_RETRIEVAL_SQL)
    SELECT 1 FROM pg_index ix
    JOIN pg_class idx ON idx.oid = ix.indexrelid
    WHERE ix.indrelid = to_regclass('public.legal_chunks') AND idx.relname = 'idx_legal_chunks_embedding_bq'
      AND ix.indisvalid AND ix.indisready
) OR EXISTS (
    SELECT 1 FROM pg_index ix
    JOIN pg_class idx ON idx.oid = ix.indexrelid
    JOIN pg_am am ON am.oid = idx.relam
    JOIN pg_attribute col ON col.attrelid = ix.indrelid AND col.attname = 'embedding'
    JOIN pg_opclass op ON op.oid = ix.indclass[0]
    WHERE ix.indrelid = to_regclass('public.legal_chunks')
      AND ix.indisvalid AND ix.indisready
      AND am.amname IN ('hnsw', 'ivfflat') AND op.opcname = 'vector_cosine_ops'
      AND ix.indkey[0] = col.attnum
      AND (ix.indpred IS NULL OR pg_get_expr(ix.indpred, ix.indrelid) IN
           ('(embedding IS NOT NULL)', 'embedding IS NOT NULL'))
) AS ready
"""


# The live query orders by a binary Hamming expression, not cosine distance.
# A valid cosine index alone must not enable that query: PostgreSQL would scan
# and sort the whole corpus. Keep INDEX_READY_SQL for the cosine maintenance
# tool, but require the matching expression/operator for live retrieval.
SEMANTIC_INDEX_READY_SQL = """
SELECT EXISTS (
    SELECT 1 FROM pg_index ix
    JOIN pg_class idx ON idx.oid = ix.indexrelid
    JOIN pg_am am ON am.oid = idx.relam
    JOIN pg_opclass op ON op.oid = ix.indclass[0]
    WHERE ix.indrelid = to_regclass('public.legal_chunks')
      AND ix.indisvalid AND ix.indisready AND ix.indnkeyatts = 1
      AND am.amname = 'hnsw' AND op.opcname = 'bit_hamming_ops'
      AND ix.indkey[0] = 0
      AND pg_get_indexdef(ix.indexrelid, 1, true)
          IN ('(binary_quantize(embedding)::bit(768))',
              '(binary_quantize(embedding))::bit(768)',
              'binary_quantize(embedding)::bit(768)')
      AND (ix.indpred IS NULL OR pg_get_expr(ix.indpred, ix.indrelid) IN
           ('(embedding IS NOT NULL)', 'embedding IS NOT NULL'))
) AS ready
"""


def shared_vector_index_ready(connection) -> bool | None:
    """False means known absent/unusable; unknown retains the bounded old query.

    Cache only actual connection identities, not a global result shared across
    databases/roles. Recheck soon so a concurrent index build needs no API restart.
    No index is built, dropped or enabled here, and no trust/RLS filter changes.
    """
    if not callable(getattr(connection, "execute", None)):
        return None
    info = getattr(connection, "info", None)
    key = tuple(getattr(info, part, None) for part in ("host", "port", "dbname", "user")) if info else None
    now = monotonic()
    if key and key in _cache and now - _cache[key][0] < _TTL_SECONDS:
        return _cache[key][1]
    try:
        with connection.transaction():
            previous = connection.execute("SHOW statement_timeout").fetchone()
            previous = previous["statement_timeout"] if isinstance(previous, dict) else previous[0]
            connection.execute("SET LOCAL statement_timeout = '300ms'")
            row = connection.execute(SEMANTIC_INDEX_READY_SQL).fetchone()
            ready = row["ready"] if isinstance(row, dict) else row[0]
            connection.execute("SELECT set_config('statement_timeout', %s, true)", (previous,))
    except psycopg.Error:
        return None  # savepoint rollback keeps the rest of retrieval usable
    if type(ready) is not bool:
        return None
    if key:
        if len(_cache) >= 32:
            _cache.clear()
        _cache[key] = (now, ready)
    return ready
