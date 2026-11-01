"""Read-only public corpus concept/admission replay, no model or web calls."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.ai.search_plan import research_queries
from api.ai.retrieval import retrieve_contexts
from api.ai.free_answer import _usable
from api.ai.synthesis import _source_views
from api.ai.evidence_pool import balanced_evidence
from api.db import database_connection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--question', required=True)
    args = parser.parse_args()
    lanes = []
    for query in research_queries(args.question):
        info = {}
        with database_connection() as db:
            db.execute('SET TRANSACTION READ ONLY')
            found = retrieve_contexts(db, question=query, top_k=6, diagnostics=info)
        lanes.append(found)
        print(json.dumps(dict(query=query, returned=len(found), partial=info.get('partial'),
                              sources=[c.reference_line for c in found]), ensure_ascii=False), flush=True)
    selected = balanced_evidence(lanes, 8)
    from api.ai.decision_context import restore_decisions
    with database_connection() as db:
        db.execute('SET TRANSACTION READ ONLY')
        selected = restore_decisions(selected, db)
    for context in selected:
        usable = _usable(context, 36000)
        views = _source_views([usable], 36000) if usable else []
        units = [unit for view in views for unit in view['units']]
        evidence = [unit for unit in units if any(word in unit.lower()
            for word in ('delil', 'ispat', 'tanık', 'bedel', 'mal kaçır', 'mirasç'))]
        print(json.dumps(dict(source=str(context.source_id), reference=context.reference_line,
            admitted=bool(usable), units=len(units), relevant_units=len(evidence),
            public_excerpt=evidence[:2]), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
