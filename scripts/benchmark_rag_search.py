"""Read-only public-corpus retrieval benchmark; never verifies/promotes or generates answers."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from statistics import median
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.ai.discovery import candidate_pool_size
from api.ai.embeddings import create_embedding_provider
from api.ai.relevance import semantic_search_text
from api.ai.retrieval import retrieve_contexts
from api.config import get_settings
from api.db import database_connection

QUESTIONS = [
    "Kira sözleşmesinde TÜFE üzerinde artış istenirse ne yapılır?",
    "Boşanmada ortak velayet hangi şartlarda verilir?",
    "İşçinin haksız feshinde kıdem tazminatı şartları nelerdir?",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--question', action='append')
    parser.add_argument('--concurrency', type=int, choices=(1,2), default=1)
    parser.add_argument('--repeats', type=int, choices=range(1,6), default=1)
    args = parser.parse_args()
    settings = get_settings()
    questions = args.question or QUESTIONS
    vectors = {}
    if settings.rag_query_embedding:
        provider = create_embedding_provider(provider_name=settings.embedding_provider,
            model=settings.embedding_model, dimensions=settings.embedding_dimensions,
            ollama_base_url=settings.ollama_base_url, ollama_timeout_seconds=8)
        for question in questions:
            vectors[question] = provider.embed_query(semantic_search_text(question))

    def run(question):
        info = {}
        start = monotonic()
        try:
            with database_connection() as connection:
                connection.execute('SET TRANSACTION READ ONLY')
                contexts = retrieve_contexts(connection, question=question,
                    top_k=candidate_pool_size(settings.rag_top_k),
                    query_embedding=vectors.get(question), embedding_model=settings.embedding_model,
                    diagnostics=info)
            return dict(question=question, seconds=round(monotonic()-start,3),
                returned_documents=len({c.source_id for c in contexts}), diagnostics=info)
        except Exception as exc:
            return dict(question=question, seconds=round(monotonic()-start,3),
                        error=type(exc).__name__, diagnostics=info)

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(run, questions * args.repeats))
    for result in results:
        print(json.dumps(result, ensure_ascii=False))
    failed = sum(bool(r.get('error') or r['diagnostics'].get('partial')) for r in results)
    print(json.dumps(dict(runs=len(results), failed_or_partial=failed,
        median_seconds=round(median(r['seconds'] for r in results),3),
        max_seconds=max(r['seconds'] for r in results), concurrency=args.concurrency)))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
