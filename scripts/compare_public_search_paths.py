"""Read-only keyword-list vs assistant lexical retrieval comparison.

No generation, embedding or provider call; this isolates lexical discovery and
selection, not the complete assistant/model verification pipeline.
"""
import argparse
import json
from pathlib import Path
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api import legal
from api.ai import retrieval
from api.ai.discovery import select_answer_contexts
from api.ai.pipeline import _with_decisions
from api.ai.relevance import question_intent, relevant_contexts
from api.ai.search_plan import plan_search
from api.config import get_settings
from api.db import database_connection


def describe(c):
    return dict(source=str(c.source_id), chunk=str(c.chunk_id), type=c.source_type,
                reference=c.reference_line, characters=len(c.content),
                law=c.law_no, article=c.article_no)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--query', required=True)
    args = parser.parse_args()
    question = args.query
    capture = []
    execute = retrieval._execute_retrieval

    def traced(connection, sql, params, **kwargs):
        tick = monotonic()
        try:
            result = execute(connection, sql, params, **kwargs)
        except Exception as exc:
            capture.append(dict(status=type(exc).__name__, timeout=kwargs.get('timeout'),
                                seconds=round(monotonic()-tick, 3)))
            raise
        eligible = {c.chunk_id for c in relevant_contexts(question, result)}
        capture.append(dict(status='ok', timeout=kwargs.get('timeout'),
            seconds=round(monotonic()-tick, 3), rows=len(result),
            contexts=[dict(**describe(c), relevance_pass=c.chunk_id in eligible) for c in result]))
        return result

    started = monotonic()
    listing = legal.search_legal_sources(q=question, limit=10, offset=0, as_of=None)
    print(json.dumps(dict(stage='list', seconds=round(monotonic()-started, 2),
        total=listing.total, partial=listing.partial,
        results=[dict(source=str(c.id), title=c.title) for c in listing.results]), ensure_ascii=False), flush=True)
    retrieval._execute_retrieval = traced
    try:
        info = {}
        with database_connection() as db:
            db.execute('SET TRANSACTION READ ONLY')
            contexts = retrieval.retrieve_contexts(db, question=question, top_k=48,
                                                   diagnostics=info)
        selected = select_answer_contexts(contexts, get_settings().rag_top_k + 2, question=question)
        pool = _with_decisions(selected, contexts, question=question)
        intent = question_intent(question)
        print(json.dumps(dict(stage='assistant_lexical_only',
            plan=str(plan_search(question)), intent=intent.name if intent else None,
            diagnostics=info, branches=[{**{k:v for k,v in b.items() if k != 'contexts'},
                'relevance_pass': sum(c['relevance_pass'] for c in b.get('contexts', []))} for b in capture],
            returned_count=len(contexts),
            list_overlap=[str(c.source_id) for c in contexts if str(c.source_id) in {str(r.id) for r in listing.results}],
            selected=[describe(c) for c in selected], model_pool=[describe(c) for c in pool]),
            ensure_ascii=False, default=str), flush=True)
    finally:
        retrieval._execute_retrieval = execute


if __name__ == '__main__':
    main()
