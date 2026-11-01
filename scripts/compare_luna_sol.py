"""Two-question fixed-evidence writer comparison, explicit budget, no app changes."""
import argparse
from decimal import Decimal
import json
import logging
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.assistant_eval import Budget, EvaluationStop, CASES, write_report

MODELS = ("openai/gpt-6-luna", "openai/gpt-6-sol")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--budget-usd", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--case", choices=("enforcement", "reinstatement"))
    args = p.parse_args()
    if args.output.exists():
        p.error("Output must be new")
    budget = Budget(args.budget_usd)
    import httpx
    from api.config import get_settings
    from api.db import database_connection
    from api.ai.cloud_provider import OpenRouterDeepSeekProvider, _CloudBase
    from api.ai.free_answer import _free_verified_answer
    from api.ai.provision_context import restore_provisions
    from api.ai.retrieval import STATUTE_RETRIEVAL_SQL, _execute_retrieval
    from api.ai.trust import verified_contexts

    settings = get_settings()
    if settings.cloud_ai_provider != "openrouter":
        raise EvaluationStop("provider_not_openrouter")
    logging.disable(logging.CRITICAL)
    with httpx.Client(timeout=15, trust_env=False) as c:
        response = c.get("https://openrouter.ai/api/v1/models")
        response.raise_for_status()
        prices = {m["id"]: m["pricing"] for m in response.json()["data"] if m["id"] in MODELS}
    if set(prices) != set(MODELS):
        raise EvaluationStop("model_missing")
    calls, rows = [], []
    original_post = _CloudBase._post

    class PilotProvider(OpenRouterDeepSeekProvider):
        # Only this script: the legacy provider validates DeepSeek efforts,
        # while both explicitly selected OpenAI models support medium.
        def __post_init__(self):
            if self.model not in MODELS or self.reasoning_effort not in {"none", "medium"}:
                raise ValueError("Unexpected comparison configuration")

    def metered(provider, url, headers, payload):
        model = payload.get("model")
        if url != "https://openrouter.ai/api/v1/chat/completions" or model not in MODELS:
            raise EvaluationStop("unexpected_endpoint")
        if any(payload.get(k) for k in ("tools", "plugins", "web_search_options")):
            raise EvaluationStop("tools_forbidden")
        price = prices[model]
        if any(Decimal(str(price.get(k, 0))) != 0 for k in ("request", "internal_reasoning")):
            raise EvaluationStop("unsupported_fee")
        bound = len(json.dumps(payload["messages"], ensure_ascii=False).encode()) + 1024
        if bound > 200000:
            raise EvaluationStop("context_too_large")
        rate = max(Decimal(price["prompt"]), Decimal(price.get("input_cache_write", "0")))
        cap = 4096
        # Byte-count input bound, worst input/cache-write rate + 20% margin.
        reservation = budget.reserve(Decimal("1.2") * (bound * rate + cap * Decimal(price["completion"])))
        body_payload = dict(payload, max_tokens=cap, usage={"include": True})
        body_payload.pop("max_completion_tokens", None)
        started = time.monotonic()
        try:
            body = original_post(provider, url, headers, body_payload)
        except Exception as error:
            budget.settle(reservation)
            report.setdefault("failed_calls", []).append({"model": model,
                "error_class": type(error).__name__, "status": getattr(error, "status_code", None),
                "charged_reservation_usd": str(reservation)})
            raise EvaluationStop("provider_error_reserved_stop") from None
        usage = body.get("usage") or {}
        if usage.get("cost") is None:
            budget.settle(reservation)
            raise EvaluationStop("missing_cost")
        budget.settle(reservation, usage["cost"])
        calls.append({"model": model, "reasoning": body_payload.get("reasoning"), "usage": usage,
                      "seconds": round(time.monotonic()-started, 3),
                      "finish_reason": body.get("choices", [{}])[0].get("finish_reason")})
        return body

    report = {"scope": "fixed_evidence_single_writer_attempt_and_common_luna_checker_not_full_pipeline",
              "budget_usd": str(budget.limit), "pricing": prices, "rows": rows, "calls": calls,
              "writer_effort": "medium", "checker": "openai/gpt-6-luna:none", "output_cap": 4096}
    write_report(args.output, report)
    _CloudBase._post = metered
    try:
        for case_id, refs in (("enforcement", [("2004", a) for a in ("42", "58", "62", "67", "68")]),
                              ("reinstatement", [("4857", "18"), ("4857", "20")])):
            if args.case and case_id != args.case:
                continue
            case = next(c for c in CASES if c["id"] == case_id)
            with database_connection() as db:
                db.execute("SET TRANSACTION READ ONLY")
                contexts = []
                for law, article in refs:
                    hits = _execute_retrieval(db, STATUTE_RETRIEVAL_SQL,
                        {"law_no": law, "article_no": article, "as_of": None, "top_k": 5}, timeout="5s")
                    contexts.extend(hits)
                contexts = verified_contexts(restore_provisions(contexts, db))
            # Identical ordered evidence and question for both models. No web,
            # planner, re-search, stored conversation, or cache between trials.
            for model in MODELS:
                diag, raw = {}, []
                start, cost_before, first_call = time.monotonic(), budget.spent, len(calls)
                writer = PilotProvider(model=model, api_key=settings.cloud_ai_api_key,
                    reasoning_effort="medium", max_output_tokens=4096, timeout_seconds=120)
                checker = PilotProvider(model=MODELS[0], api_key=settings.cloud_ai_api_key,
                    reasoning_effort="none", max_output_tokens=4096, timeout_seconds=120)
                result = _free_verified_answer(writer, question=case["question"], contexts=contexts,
                    checker_provider=checker, diagnostics=diag, on_draft=raw.append)
                rows.append({"case": case_id, "question": case["question"], "model": model,
                    "seconds": round(time.monotonic()-start, 3), "cost_usd": str(budget.spent-cost_before),
                    "calls": len(calls)-first_call, "raw_draft": raw,
                    "verified_answer": result.text if result else None, "diagnostics": diag,
                    "evidence_ids": [str(c.chunk_id) for c in contexts]})
                report["spent_usd"] = str(budget.spent)
                write_report(args.output, report)
                print(json.dumps({k: rows[-1][k] for k in ("case", "model", "seconds", "cost_usd", "calls")}), flush=True)
    except EvaluationStop as stop:
        report["stopped"] = str(stop)
    except Exception as error:
        report["error_class"] = type(error).__name__
    finally:
        _CloudBase._post = original_post
        report.update(spent_usd=str(budget.spent), held_usd=str(budget.held))
        write_report(args.output, report)
    return 2 if report.get("stopped") or report.get("error_class") else 0


if __name__ == "__main__":
    raise SystemExit(main())
