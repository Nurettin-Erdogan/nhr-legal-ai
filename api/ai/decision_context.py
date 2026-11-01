"""Recover bounded full public decisions from their exact current revision.

The retrieval hit is often only a case's introductory paragraph. Restoration
does not certify a holding; existing role, relevance and claim checks still run.
"""
from dataclasses import replace
import hashlib

from api.ai.rag import RAGContext


def complete_decision(context: RAGContext, canonical: str, digest: str) -> RAGContext | None:
    if (context.source_type != 'court_decision' or context.verification != 'official'
            or not 200 <= len(canonical) <= 20000 or not context.content.strip()
            or context.content not in canonical
            or hashlib.sha256(canonical.encode('utf-8')).hexdigest() != digest):
        return None
    return replace(context, content=canonical)


def restore_decisions(contexts, connection):
    from api.ai.retrieval import _VERIFIED_SOURCE_FILTER
    result, cache = [], {}
    for context in contexts:
        if context.source_type != 'court_decision' or context.verification != 'official':
            result.append(context)
            continue
        key = context.source_id, context.source_version, context.revision
        if key not in cache:
            with connection.transaction():
                connection.execute("SET LOCAL statement_timeout='3s'")
                cache[key] = connection.execute(f'''SELECT ls.raw_text, ls.content_hash
                    FROM legal_sources ls JOIN legal_chunks chunk ON chunk.legal_source_id=ls.id
                    WHERE ls.id=%(source)s AND chunk.id=%(chunk)s
                      AND ls.source_type='court_decision' AND ls.is_current AND ls.deleted_at IS NULL
                      AND ls.source_version IS NOT DISTINCT FROM %(version)s
                      AND ls.revision IS NOT DISTINCT FROM %(revision)s
                      AND {_VERIFIED_SOURCE_FILTER} AND length(ls.raw_text)<=20000''',
                    dict(source=context.source_id, chunk=context.chunk_id,
                         version=context.source_version, revision=context.revision)).fetchone()
        row = cache[key]
        restored = complete_decision(context, row['raw_text'], row['content_hash']) if row else None
        result.append(restored or context)
    return result
