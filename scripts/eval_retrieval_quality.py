"""Compare old OR, 2-token AND, and AND→OR fallback retrieval quality.

Latency is recorded but the report is recall/precision oriented.

  .\\.venv\\Scripts\\python.exe -m scripts.eval_retrieval_quality
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any

from api.ai.eval_questions import REGRESSION_QUESTIONS
from api.ai.rag import RAGContext
from api.ai.retrieval import retrieve_contexts
from api.config import get_settings
from api.db import database_connection

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "logs"

_TOKEN_SQL = """
SELECT ARRAY(
    SELECT token
    FROM (
        SELECT unnest(lexemes) AS token,
               row_number() OVER () AS ord
        FROM ts_debug('turkish', %(question)s)
        WHERE lexemes IS NOT NULL
    ) parsed
    WHERE char_length(token) >= 4
      AND token NOT IN (
        'sayıl', 'kanun', 'madde', 'maddes', 'neler', 'nasıl', 'hangi',
        'kadar', 'neyi', 'düzen', 'koşul', 'nedir', 'olan', 'olarak', 'üzere'
      )
    ORDER BY ord
    LIMIT 2
) AS tokens
"""

MODES = ("legacy_or", "narrow", "auto")


def _fold(text: str) -> str:
    return text.casefold()


def _hit_blob(context: RAGContext) -> str:
    return _fold(
        " ".join(
            part
            for part in (
                context.reference_line,
                context.content,
                context.title,
                context.law_name or "",
                context.law_no or "",
                context.article_no or "",
                context.article_title or "",
                context.authority or "",
                context.court_name or "",
            )
            if part
        )
    )


def _term_hits(blob: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if _fold(term) in blob]


def _article_ok(context: RAGContext, article: str | None) -> bool:
    if not article:
        return False
    wanted = article.casefold()
    if context.article_no and context.article_no.casefold() == wanted:
        return True
    blob = _hit_blob(context)
    return (
        f"m. {wanted}" in blob
        or f"m.{wanted}" in blob
        or f"madde {wanted}" in blob
    )


def score_contexts(item: dict[str, Any], contexts: list[RAGContext]) -> dict[str, Any]:
    expected_types = set(item["expect_source_types"])
    must_terms = tuple(item["must_terms"])
    expect_law_no = item.get("expect_law_no")
    expect_article_no = item.get("expect_article_no")
    hits: list[dict[str, Any]] = []
    for index, context in enumerate(contexts, start=1):
        blob = _hit_blob(context)
        matched_terms = _term_hits(blob, must_terms)
        law_ok = bool(expect_law_no) and (
            expect_law_no in (context.law_no or "")
            or expect_law_no in blob
        )
        article_ok = _article_ok(context, expect_article_no)
        supports = len(matched_terms) >= min(2, len(must_terms))
        hits.append(
            {
                "k": f"K{index}",
                "source_type": context.source_type,
                "reference": context.reference_line,
                "law_no": context.law_no,
                "article_no": context.article_no,
                "matched_terms": matched_terms,
                "law_ok": law_ok,
                "article_ok": article_ok,
                "supports": supports,
                "excerpt": context.content.replace("\n", " ").strip()[:280],
            }
        )

    type_ok = bool(expected_types & {hit["source_type"] for hit in hits})
    law_found = any(hit["law_ok"] for hit in hits) if expect_law_no else None
    article_found = (
        any(hit["article_ok"] for hit in hits) if expect_article_no else None
    )
    citation_supports = any(hit["supports"] for hit in hits)
    correct = citation_supports and type_ok
    if expect_law_no:
        correct = bool(law_found)
        if expect_article_no:
            correct = bool(law_found and article_found)
    elif expect_article_no:
        correct = bool(article_found and citation_supports)

    return {
        "no_hit": len(contexts) == 0,
        "expected_types": list(item["expect_source_types"]),
        "type_ok": type_ok,
        "correct_law_or_decision": correct,
        "citation_supports": citation_supports,
        "law_found": law_found,
        "article_found": article_found,
        "hits": hits,
    }


def _and_wrong(and_tokens: list[str], scored: dict[str, Any]) -> bool:
    if not and_tokens:
        return scored["no_hit"]
    return (
        scored["no_hit"]
        or not scored["citation_supports"]
        or not scored["type_ok"]
    )


def main() -> int:
    settings = get_settings()
    top_k = settings.rag_top_k
    rows: list[dict[str, Any]] = []
    with database_connection() as connection:
        for item in REGRESSION_QUESTIONS:
            tokens_row = connection.execute(
                _TOKEN_SQL, {"question": item["question"]}
            ).fetchone()
            and_tokens = list(tokens_row["tokens"] or []) if tokens_row else []
            mode_results: dict[str, Any] = {}
            for mode in MODES:
                started = monotonic()
                contexts = retrieve_contexts(
                    connection,
                    question=item["question"],
                    top_k=top_k,
                    as_of=None,
                    lexical_mode=mode,
                )
                elapsed_ms = round((monotonic() - started) * 1000, 1)
                scored = score_contexts(item, contexts)
                scored["retrieval_ms"] = elapsed_ms
                scored["hit_count"] = len(contexts)
                mode_results[mode] = scored
            rows.append(
                {
                    "id": item["id"],
                    "topic": item["topic"],
                    "question": item["question"],
                    "and_tokens": and_tokens,
                    "and_query": " & ".join(and_tokens),
                    "expected_types": list(item["expect_source_types"]),
                    "expect_law_no": item.get("expect_law_no"),
                    "expect_article_no": item.get("expect_article_no"),
                    "must_terms": list(item["must_terms"]),
                    "legacy_or": mode_results["legacy_or"],
                    "new_and": mode_results["narrow"],
                    "fallback": mode_results["auto"],
                    "and_wrong_or_nohit": _and_wrong(
                        and_tokens, mode_results["narrow"]
                    ),
                    "fallback_used": (
                        [hit["reference"] for hit in mode_results["narrow"]["hits"]]
                        != [hit["reference"] for hit in mode_results["auto"]["hits"]]
                    ),
                }
            )

    def _count(mode_key: str, field: str) -> int:
        return sum(1 for row in rows if row[mode_key][field])

    summary = {
        "n": len(rows),
        "top_k": top_k,
        "legacy_or": {
            "no_hit": _count("legacy_or", "no_hit"),
            "type_ok": _count("legacy_or", "type_ok"),
            "correct": _count("legacy_or", "correct_law_or_decision"),
            "supports": _count("legacy_or", "citation_supports"),
        },
        "new_and": {
            "no_hit": _count("new_and", "no_hit"),
            "type_ok": _count("new_and", "type_ok"),
            "correct": _count("new_and", "correct_law_or_decision"),
            "supports": _count("new_and", "citation_supports"),
        },
        "fallback": {
            "no_hit": _count("fallback", "no_hit"),
            "type_ok": _count("fallback", "type_ok"),
            "correct": _count("fallback", "correct_law_or_decision"),
            "supports": _count("fallback", "citation_supports"),
        },
        "and_wrong_or_nohit": [
            row["id"] for row in rows if row["and_wrong_or_nohit"]
        ],
        "fallback_changed": [row["id"] for row in rows if row["fallback_used"]],
    }

    payload = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "rows": rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "retrieval_quality.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("id | AND tokens | eski doğru | AND doğru | fallback doğru | AND hata")
    for row in rows:
        print(
            f"{row['id']:16} | {row['and_query']:24} | "
            f"{int(row['legacy_or']['correct_law_or_decision'])} "
            f"sup={int(row['legacy_or']['citation_supports'])} "
            f"type={int(row['legacy_or']['type_ok'])} | "
            f"{int(row['new_and']['correct_law_or_decision'])} "
            f"sup={int(row['new_and']['citation_supports'])} "
            f"type={int(row['new_and']['type_ok'])} nohit={int(row['new_and']['no_hit'])} | "
            f"{int(row['fallback']['correct_law_or_decision'])} "
            f"sup={int(row['fallback']['citation_supports'])} "
            f"type={int(row['fallback']['type_ok'])} | "
            f"{'YES' if row['and_wrong_or_nohit'] else 'no'}"
        )
        for mode_name, key in (
            ("eski", "legacy_or"),
            ("AND", "new_and"),
            ("fb", "fallback"),
        ):
            for hit in row[key]["hits"]:
                print(
                    f"  {mode_name} {hit['k']} {hit['source_type']:16} "
                    f"law={hit['law_no'] or '-'} m.{hit['article_no'] or '-'} "
                    f"sup={int(hit['supports'])} {hit['reference'][:90]}"
                )
    print("\nÖzet:", json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"yazıldı: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
