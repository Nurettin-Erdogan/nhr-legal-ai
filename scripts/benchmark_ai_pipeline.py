"""Measure the grounded-answer pipeline against the 20-question regression set.

Examples:
  .\\.venv\\Scripts\\python.exe -m scripts.benchmark_ai_pipeline --mode retrieval --label before
  .\\.venv\\Scripts\\python.exe -m scripts.benchmark_ai_pipeline --mode full --label before
  .\\.venv\\Scripts\\python.exe -m scripts.benchmark_ai_pipeline --mode hybrid
  .\\.venv\\Scripts\\python.exe -m scripts.benchmark_ai_pipeline --mode explain
  .\\.venv\\Scripts\\python.exe -m scripts.benchmark_ai_pipeline --mode concurrent
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any

from api.ai.eval_questions import REGRESSION_QUESTIONS
from api.ai.providers import AIProviderError, create_provider
from api.ai.rag import SYSTEM_INSTRUCTION, build_grounded_prompt, generate_grounded_answer
from api.ai.retrieval import LEXICAL_RETRIEVAL_SQL, retrieve_contexts
from api.ai.verification import verify_answer
from api.config import get_settings
from api.db import database_connection

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "logs"


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((pct / 100) * (len(ordered) - 1))))
    return ordered[index]


def _summarize(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, Any]:
    summary: dict[str, Any] = {"n": len(rows)}
    for key in keys:
        values = [float(row[key]) for row in rows if row.get(key) is not None]
        if not values:
            continue
        summary[key] = {
            "mean": round(statistics.fmean(values), 1),
            "p50": round(_percentile(values, 50) or 0, 1),
            "p95": round(_percentile(values, 95) or 0, 1),
            "min": round(min(values), 1),
            "max": round(max(values), 1),
        }
    return summary


def _write(label: str, payload: dict[str, Any]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"ai_pipeline_{label}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _print_summary(title: str, summary: dict[str, Any]) -> None:
    print(f"\n== {title} ==")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def cmd_retrieval(label: str) -> None:
    settings = get_settings()
    rows: list[dict[str, Any]] = []
    with database_connection() as connection:
        for item in REGRESSION_QUESTIONS:
            started = monotonic()
            contexts = retrieve_contexts(
                connection,
                question=item["question"],
                top_k=settings.rag_top_k,
                as_of=None,
            )
            elapsed = (monotonic() - started) * 1000
            rows.append(
                {
                    "id": item["id"],
                    "topic": item["topic"],
                    "retrieval_ms": round(elapsed, 1),
                    "hit_count": len(contexts),
                    "source_types": [context.source_type for context in contexts],
                    "references": [context.reference_line for context in contexts],
                    "expected_overlap": bool(
                        set(item["expect_source_types"])
                        & {context.source_type for context in contexts}
                    ),
                }
            )
    summary = _summarize(rows, ("retrieval_ms",))
    summary["empty_hits"] = sum(1 for row in rows if row["hit_count"] == 0)
    summary["expected_type_hits"] = sum(1 for row in rows if row["expected_overlap"])
    path = _write(
        f"{label}_retrieval",
        {
            "measured_at": datetime.now(timezone.utc).isoformat(),
            "top_k": settings.rag_top_k,
            "query_embedding": settings.rag_query_embedding,
            "summary": summary,
            "rows": rows,
        },
    )
    _print_summary("retrieval", summary)
    print(f"yazıldı: {path}")


def cmd_hybrid() -> None:
    settings = get_settings()
    from api.ai.embeddings import create_embedding_provider

    embedder = create_embedding_provider(
        provider_name=settings.embedding_provider,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        ollama_base_url=settings.ollama_base_url,
        ollama_timeout_seconds=settings.ollama_timeout_seconds,
    )
    rows: list[dict[str, Any]] = []
    with database_connection() as connection:
        embedding_ready = connection.execute(
            "SELECT count(*) AS n FROM legal_chunks WHERE embedding IS NOT NULL"
        ).fetchone()["n"]
        for item in REGRESSION_QUESTIONS:
            lexical_started = monotonic()
            lexical = retrieve_contexts(
                connection, question=item["question"], top_k=settings.rag_top_k
            )
            lexical_ms = (monotonic() - lexical_started) * 1000
            embed_started = monotonic()
            try:
                vector = embedder.embed_query(item["question"])
                embed_error = None
            except Exception as exc:  # noqa: BLE001 — benchmark must continue
                vector = None
                embed_error = str(exc)
            embed_ms = (monotonic() - embed_started) * 1000
            hybrid_ms = None
            overlap = 0
            hybrid_types: list[str] = []
            if vector is not None:
                hybrid_started = monotonic()
                hybrid = retrieve_contexts(
                    connection,
                    question=item["question"],
                    top_k=settings.rag_top_k,
                    query_embedding=vector,
                    embedding_model=settings.embedding_model,
                )
                hybrid_ms = (monotonic() - hybrid_started) * 1000
                lexical_ids = {str(context.chunk_id) for context in lexical}
                hybrid_ids = {str(context.chunk_id) for context in hybrid}
                overlap = len(lexical_ids & hybrid_ids)
                hybrid_types = [context.source_type for context in hybrid]
            rows.append(
                {
                    "id": item["id"],
                    "lexical_ms": round(lexical_ms, 1),
                    "embedding_ms": round(embed_ms, 1),
                    "hybrid_ms": None if hybrid_ms is None else round(hybrid_ms, 1),
                    "overlap": overlap,
                    "lexical_types": [context.source_type for context in lexical],
                    "hybrid_types": hybrid_types,
                    "embed_error": embed_error,
                }
            )
    summary = _summarize(rows, ("lexical_ms", "embedding_ms", "hybrid_ms"))
    summary["embedding_ready_chunks"] = embedding_ready
    summary["mean_overlap"] = round(statistics.fmean(row["overlap"] for row in rows), 2)
    path = _write(
        "hybrid_compare",
        {
            "measured_at": datetime.now(timezone.utc).isoformat(),
            "top_k": settings.rag_top_k,
            "summary": summary,
            "rows": rows,
        },
    )
    _print_summary("hybrid vs lexical", summary)
    print(f"yazıldı: {path}")


def cmd_explain() -> None:
    settings = get_settings()
    question = REGRESSION_QUESTIONS[0]["question"]
    params = {
        "question": question,
        "top_k": settings.rag_top_k,
        "candidate_limit": max(settings.rag_top_k * 4, 20),
        "as_of": None,
    }
    sql = "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) " + LEXICAL_RETRIEVAL_SQL
    with database_connection() as connection:
        indexes = connection.execute(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename IN ('legal_chunks', 'legal_sources', 'legislation_details',
                                'court_decision_details')
            ORDER BY tablename, indexname
            """
        ).fetchall()
        plan = [
            next(iter(row.values()))
            for row in connection.execute(sql, params).fetchall()
        ]
        counts = connection.execute(
            """
            SELECT
              (SELECT count(*) FROM legal_chunks) AS chunks,
              (SELECT count(*) FROM legal_chunks WHERE embedding IS NOT NULL) AS embedded,
              (SELECT count(*) FROM legal_sources
                WHERE deleted_at IS NULL AND ingest_status = 'ready' AND is_current) AS ready_sources
            """
        ).fetchone()
    payload = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "counts": dict(counts),
        "plan": plan,
        "indexes": [dict(row) for row in indexes],
    }
    path = _write("explain_lexical", payload)
    print("\n".join(plan))
    print(f"yazıldı: {path}")


def cmd_full(label: str, *, max_output_tokens: int | None, num_ctx: int | None) -> None:
    settings = get_settings()
    provider = create_provider(
        provider_name=settings.ai_provider,
        model=settings.ai_model,
        ollama_base_url=settings.ollama_base_url,
        ollama_timeout_seconds=settings.ollama_timeout_seconds,
        ollama_max_output_tokens=max_output_tokens or settings.ollama_max_output_tokens,
        ollama_num_ctx=num_ctx or settings.ollama_num_ctx,
        ollama_keep_alive=settings.ollama_keep_alive,
    )
    rows: list[dict[str, Any]] = []
    for item in REGRESSION_QUESTIONS:
        row: dict[str, Any] = {
            "id": item["id"],
            "topic": item["topic"],
            "error": None,
            "token_limit_error": False,
            "grounded": False,
            "citation_ok": False,
        }
        total_started = monotonic()
        try:
            retrieval_started = monotonic()
            with database_connection() as connection:
                contexts = retrieve_contexts(
                    connection,
                    question=item["question"],
                    top_k=settings.rag_top_k,
                )
            row["retrieval_ms"] = round((monotonic() - retrieval_started) * 1000, 1)
            row["embedding_ms"] = 0.0
            row["hit_count"] = len(contexts)
            if not contexts:
                row["error"] = "empty_retrieval"
                row["total_ms"] = round((monotonic() - total_started) * 1000, 1)
                rows.append(row)
                print(f"{item['id']}: empty retrieval", flush=True)
                continue
            prompt_started = monotonic()
            prompt = build_grounded_prompt(
                item["question"],
                contexts,
                max_context_chars=settings.rag_context_chars,
            )
            row["prompt_build_ms"] = round((monotonic() - prompt_started) * 1000, 1)
            row["prompt_chars"] = len(SYSTEM_INSTRUCTION) + len(prompt)
            llm_started = monotonic()
            raw = generate_grounded_answer(
                provider,
                question=item["question"],
                contexts=contexts,
                max_context_chars=settings.rag_context_chars,
            )
            row["llm_ms"] = round((monotonic() - llm_started) * 1000, 1)
            usage = getattr(provider, "last_usage", None)
            if usage is not None:
                row["prompt_eval_count"] = usage.prompt_eval_count
                row["eval_count"] = usage.eval_count
                row["done_reason"] = usage.done_reason
            verify_started = monotonic()
            verified = verify_answer(raw, contexts)
            row["verification_ms"] = round((monotonic() - verify_started) * 1000, 1)
            persist_started = monotonic()
            row["persist_ms"] = round((monotonic() - persist_started) * 1000, 1)
            row["grounded"] = verified.grounded
            row["citation_ok"] = verified.grounded and bool(verified.contexts)
            row["unverified_markers"] = list(verified.unverified_markers)
            row["answer_chars"] = len(verified.text)
            row["cited_types"] = [context.source_type for context in verified.contexts]
            row["expected_type_cited"] = bool(
                set(item["expect_source_types"])
                & {context.source_type for context in verified.contexts}
            )
        except AIProviderError as exc:
            row["error"] = str(exc)
            row["token_limit_error"] = "token sınırında kesildi" in str(exc)
        except Exception as exc:  # noqa: BLE001 — keep the rest of the set
            row["error"] = f"{type(exc).__name__}: {exc}"
        row["total_ms"] = round((monotonic() - total_started) * 1000, 1)
        rows.append(row)
        status = "ok" if row["citation_ok"] else (row["error"] or "ungrounded")
        print(
            f"{item['id']}: {status} total={row.get('total_ms')} llm={row.get('llm_ms')}",
            flush=True,
        )
    numeric = (
        "retrieval_ms",
        "embedding_ms",
        "prompt_build_ms",
        "llm_ms",
        "verification_ms",
        "persist_ms",
        "total_ms",
        "prompt_eval_count",
        "eval_count",
    )
    summary = _summarize(rows, numeric)
    n = len(rows)
    summary["error_rate"] = round(sum(1 for row in rows if row.get("error")) / n, 3)
    summary["token_limit_error_rate"] = round(
        sum(1 for row in rows if row.get("token_limit_error")) / n, 3
    )
    summary["citation_success_rate"] = round(
        sum(1 for row in rows if row.get("citation_ok")) / n, 3
    )
    summary["grounded_rate"] = round(sum(1 for row in rows if row.get("grounded")) / n, 3)
    path = _write(
        f"{label}_full",
        {
            "measured_at": datetime.now(timezone.utc).isoformat(),
            "label": label,
            "model": settings.ai_model,
            "max_output_tokens": max_output_tokens or settings.ollama_max_output_tokens,
            "num_ctx": num_ctx or settings.ollama_num_ctx,
            "top_k": settings.rag_top_k,
            "summary": summary,
            "rows": rows,
        },
    )
    _print_summary(f"full {label}", summary)
    print(f"yazıldı: {path}")


def cmd_concurrent() -> None:
    import threading

    settings = get_settings()
    question = REGRESSION_QUESTIONS[0]["question"]
    with database_connection() as connection:
        contexts = retrieve_contexts(
            connection, question=question, top_k=settings.rag_top_k
        )
    if not contexts:
        raise SystemExit("eşzamanlı test için kaynak bulunamadı")

    def one(name: str, bucket: dict[str, Any]) -> None:
        provider = create_provider(
            provider_name=settings.ai_provider,
            model=settings.ai_model,
            ollama_base_url=settings.ollama_base_url,
            ollama_timeout_seconds=settings.ollama_timeout_seconds,
            ollama_max_output_tokens=settings.ollama_max_output_tokens,
            ollama_num_ctx=settings.ollama_num_ctx,
            ollama_keep_alive=settings.ollama_keep_alive,
        )
        started = monotonic()
        try:
            generate_grounded_answer(
                provider,
                question=question,
                contexts=contexts,
                max_context_chars=settings.rag_context_chars,
            )
            bucket[name] = {"ok": True, "ms": round((monotonic() - started) * 1000, 1)}
        except Exception as exc:  # noqa: BLE001
            bucket[name] = {
                "ok": False,
                "ms": round((monotonic() - started) * 1000, 1),
                "error": str(exc),
            }

    results: dict[str, Any] = {}
    wall_started = monotonic()
    workers = [
        threading.Thread(target=one, args=("a", results)),
        threading.Thread(target=one, args=("b", results)),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    payload = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "wall_ms": round((monotonic() - wall_started) * 1000, 1),
        "results": results,
    }
    path = _write("concurrent", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"yazıldı: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("retrieval", "hybrid", "explain", "full", "concurrent"),
        default="retrieval",
    )
    parser.add_argument("--label", default="run")
    parser.add_argument("--max-output-tokens", type=int, default=None)
    parser.add_argument("--num-ctx", type=int, default=None)
    args = parser.parse_args()
    if args.mode == "retrieval":
        cmd_retrieval(args.label)
    elif args.mode == "hybrid":
        cmd_hybrid()
    elif args.mode == "explain":
        cmd_explain()
    elif args.mode == "full":
        cmd_full(
            args.label,
            max_output_tokens=args.max_output_tokens,
            num_ctx=args.num_ctx,
        )
    else:
        cmd_concurrent()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
