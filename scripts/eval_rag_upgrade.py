"""Read-only public-corpus lexical/hybrid comparison. Never controls workers.

Run as python -m scripts.eval_rag_upgrade --output data/benchmarks/rag-upgrade.json
Labels reflect topic matching, NOT a human-labelled legal correctness score.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from time import perf_counter

from api.ai.embeddings import create_embedding_provider
from api.ai.evidence_selection import evidence_candidates
from api.ai.retrieval import retrieve_contexts
from api.ai.trust import verified_contexts
from api.ai.relevance import semantic_search_text
from api.config import get_settings
from api.db import database_connection
from scripts.compare_local_rag import QUESTIONS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--hybrid', action='store_true')
    parser.add_argument('--case', choices=['rent', *[key for key, _ in QUESTIONS]], action='append')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Refusing to overwrite an existing report')
    settings = get_settings()
    provider = create_embedding_provider(provider_name=settings.embedding_provider,
        model=settings.embedding_model, dimensions=settings.embedding_dimensions,
        ollama_base_url=settings.ollama_base_url, ollama_timeout_seconds=15)
    cases = [('rent', 'Kira sözleşmesinde TÜFE üzerinde artış istenirse ne yapılır?'), *QUESTIONS]
    report = []
    for case_id, question in cases:
        if args.case and case_id not in args.case:
            continue
        start = perf_counter()
        row = dict(id=case_id, question=question, hybrid=args.hybrid)
        diagnostics = {}
        try:
            vector = provider.embed_query(semantic_search_text(question)) if args.hybrid else None
            row['embedding_seconds'] = round(perf_counter()-start, 3) if vector else 0
            with database_connection() as connection:
                connection.execute('SET TRANSACTION READ ONLY')
                candidates = retrieve_contexts(connection, question=question, top_k=6,
                    query_embedding=vector, embedding_model=settings.embedding_model,
                    diagnostics=diagnostics)
            contexts = verified_contexts(candidates)
            evidence = evidence_candidates(question, contexts, per_source_chars=2000)
            row.update(contexts=[asdict(c) for c in contexts], pending_excluded=len(candidates)-len(contexts),
                       evidence=[asdict(e) for e in evidence], count=len(contexts))
        except Exception as exc:
            row['error'] = type(exc).__name__
        row.update(seconds=round(perf_counter()-start,3), diagnostics=diagnostics)
        report.append(row)
        print(json.dumps({k:v for k,v in row.items() if k not in ('contexts','evidence')},ensure_ascii=False),flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),encoding='utf8')


if __name__ == '__main__':
    main()
