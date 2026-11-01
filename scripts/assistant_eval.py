"""Offline-first evaluation of synthetic public questions. Never persists chats.

Default: print the fixed matrix, no model/DB/network access.
--replay REPORT: re-score saved answers for free, not a new model generation.
--sources --output NEW_FILE: read-only local statute-lane evidence snapshot.
--live --budget-usd AMOUNT --output NEW_FILE: explicitly paid, bounded pilot.
Live mode uses the application's pipeline, not a simpler replacement prompt.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, replace
from decimal import Decimal, InvalidOperation
import hashlib
import json
import logging
from pathlib import Path
import statistics
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MODEL = "openai/gpt-6-luna"
EFFORTS = ("low", "medium", "high")
# These are evaluation targets, not an assertion of an expert-approved answer.
# Each named facet requires independent reviewer confirmation after the run.
CASES = (
    {"id": "rent", "question": "Konut kirasında artış sınırı nedir? Beş yıldan sonra ne değişir?",
     "refs": [("6098", "344")], "facets": ["artış sınırı", "beş yıl istisnası"]},
    {"id": "eviction", "question": "Kiracı kirayı ödemezse hangi şartlarla sözleşmeyi feshedebilirim? Yazılı ihtarın içeriği ve süreyi açıkla.",
     "refs": [("6098", "315")], "facets": ["ihtar içeriği", "ödeme süresi", "fesih koşulu"]},
    {"id": "reinstatement", "question": "İşe iade şartları nelerdir? Otuz işçi nasıl hesaplanır ve hangi sürede başvurmalıyım?",
     "refs": [("4857", "18"), ("4857", "20")], "facets": ["şartlar", "işçi hesabı", "başvuru süreleri"]},
    {"id": "notice", "question": "İhbar tazminatı hangi koşullarda doğar? Bildirim süresine uyulursa yine ödenir mi?",
     "refs": [("4857", "17")], "facets": ["hak kazanma", "bildirim süresi"]},
    {"id": "enforcement", "question": "Banka havalesiyle borç verdim, senet yok. İlamsız takip yapabilir miyim? Borçlu itiraz ederse yollar ve süreler nelerdir?",
     "refs": [("2004", "67"), ("2004", "68")], "facets": ["takip", "itirazın iptali", "itirazın kaldırılması", "ispat"]},
    {"id": "property", "question": "Evlilik sırasında krediyle alınan ev yalnız eşimin adına. Boşanmada kalan kredi ve mal paylaşımı nasıl değerlendirilir?",
     "refs": [("4721", "219"), ("4721", "231")], "facets": ["malın niteliği", "kredi borcu", "katılma alacağı"]},
    {"id": "administrative", "question": "Belediye ruhsat başvurumu reddetti. İptal davasında görevli mahkeme ve genel dava açma süresi nedir?",
     "refs": [("2577", "7")], "facets": ["görev", "süre", "başlangıç"]},
    {"id": "leave", "question": "Yıllık ücretli izne ne zaman hak kazanılır? Asgari izin süreleri ve yaş istisnalarını açıkla.",
     "refs": [("4857", "53")], "facets": ["hak kazanma", "süreler", "yaş istisnası"]},
    {"id": "consumer", "question": "İnternetten aldığım ürün için cayma hakkı var mı? Süre ve temel istisnalar nedir?",
     "refs": [("6502", "48")], "facets": ["cayma hakkı", "süre", "istisnalar"]},
    {"id": "injury", "question": "İş kazası nedeniyle işverenden maddi ve manevi tazminat isteyebilir miyim? Görevli mahkeme ve zamanaşımını değerlendir.",
     "refs": [("6098", "417")], "facets": ["sorumluluk", "tazminat", "görev", "zamanaşımı"]},
    {"id": "reinstatement_decisions", "question": "2026 yılında işe iade davası açmanın şartları nelerdir? 30 işçi şartı nasıl hesaplanır? Konuyla doğrudan ilgili iki gerçek Yargıtay kararını resmi bağlantılarıyla göster.",
     "refs": [("4857", "18"), ("4857", "20")],
     "facets": ["şartlar", "işçi hesabı", "iki ayrı ilgili karar", "resmi bağlantılar"]},
)


class EvaluationStop(BaseException):
    """Must not become a provider fallback, retry, or a paid repair loop."""


def selected_matrix(args):
    wanted = getattr(args, "case", None)
    cases = [c for c in CASES if not wanted or c["id"] in wanted][:args.limit]
    efforts = tuple(dict.fromkeys(getattr(args, "effort", None) or EFFORTS))
    return cases, efforts


def positive_decimal(value):
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid budget") from None
    if not number.is_finite() or number <= 0:
        raise ValueError("Budget must be positive and finite")
    return number


class Budget:
    def __init__(self, limit):
        self.limit = positive_decimal(limit)
        self.spent = Decimal(0)
        self.held = Decimal(0)
        self.lock = threading.Lock()

    def reserve(self, amount):
        amount = positive_decimal(amount)
        with self.lock:
            if self.spent + self.held + amount > self.limit:
                raise EvaluationStop("budget_before_call")
            self.held += amount
        return amount

    def settle(self, reservation, actual=None):
        # Unknown/failed call: keep its complete reservation charged; fail closed.
        debit = reservation if actual is None else Decimal(str(actual))
        if not debit.is_finite() or debit < 0 or debit > reservation:
            raise EvaluationStop("invalid_or_over_reservation_cost")
        with self.lock:
            self.held -= reservation
            self.spent += debit


def score(case, answer):
    citations = answer.get("citations") or []
    refs = {(str(c.get("law_no")), str(c.get("article_no"))) for c in citations}
    missing = [list(ref) for ref in case["refs"] if tuple(ref) not in refs]
    unsafe = [c for c in citations if c.get("verification") != "official"]
    text = answer.get("answer") or ""
    return {
        "grounded": answer.get("grounded") is True,
        "missing_expected_refs": missing,
        "unsafe_citation_count": len(unsafe),
        "unverified_marker_count": len(answer.get("unverified_markers") or []),
        "answer_nonempty": bool(text.strip()),
        "characters": len(text),
        "automatic_source_checks_pass": bool(text.strip()) and answer.get("grounded") is True
            and not missing and not unsafe and not answer.get("unverified_markers"),
        "expert_review": {facet: "pending" for facet in case["facets"]},
        "legal_correctness": "not_established_by_automatic_checks",
    }


def summarize(rows):
    groups = {}
    for effort in EFFORTS:
        entries = [r for r in rows if r["effort"] == effort]
        if not entries:
            continue
        groups[effort] = {
            "answers": len(entries),
            "automatic_source_passes": sum(r.get("score", {}).get("automatic_source_checks_pass", False) for r in entries),
            "median_seconds": statistics.median(r["seconds"] for r in entries),
            "cost_usd": str(sum((Decimal(r["cost_usd"]) for r in entries), Decimal(0))),
            "expert_review": "pending",
            # A citation match is NOT a complete answer. Preserve pipeline's
            # own partial/coverage signals separately, even for grounded text.
            "partial_answers": sum(bool(r.get("timings", {}).get("extra", {}).get("free_answer", {}).get("partial_answer")) for r in entries),
            "checker_coverage_false": sum(r.get("timings", {}).get("extra", {}).get("free_answer", {}).get("coverage_preserved") is False for r in entries),
            "refusals": sum(r.get("answer", {}).get("answer_kind") == "insufficient_sources" for r in entries),
        }
    return groups


def write_report(path, report):
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def capture_sources(args):
    from contextlib import contextmanager
    from api.ai import pipeline
    from api.ai.trust import verified_contexts
    from api.ai.provision_context import restore_provisions
    from api.ai.retrieval import STATUTE_RETRIEVAL_SQL, _execute_retrieval
    from api.schemas import AIAnswerRequest
    original = pipeline.database_connection

    @contextmanager
    def read_only_connection():
        with original() as db:
            db.execute("SET TRANSACTION READ ONLY")
            yield db

    pipeline.database_connection = read_only_connection
    rows = []
    try:
        for case in CASES[:args.limit]:
            started = time.monotonic()
            contexts = pipeline._planned_statutes(AIAnswerRequest(question=case["question"]), case["question"])
            with read_only_connection() as db:
                contexts = verified_contexts(restore_provisions(contexts, db))
            refs = {(c.law_no, c.article_no) for c in contexts}
            direct = []
            for law, article in case["refs"]:
                with read_only_connection() as db:
                    hits = _execute_retrieval(db, STATUTE_RETRIEVAL_SQL,
                        {"law_no": law, "article_no": article, "as_of": None, "top_k": 3}, timeout="5s")
                    hits = verified_contexts(restore_provisions(hits, db))
                direct.append({"law": law, "article": article, "verified_hits": len(hits),
                               "present_in_hint_lane": (law, article) in refs})
            rows.append({"case": case["id"], "question": case["question"],
                         "seconds": round(time.monotonic() - started, 3),
                         "missing_in_this_lane": [ref for ref in case["refs"] if ref not in refs],
                         "direct_reference_control": direct,
                         "sources": [asdict(c) for c in contexts]})
    finally:
        pipeline.database_connection = original
    write_report(args.output, {"paid_calls": 0, "read_only": True,
        "scope": "exact_local_statute_lane_not_full_assistant_retrieval", "rows": rows})
    print(json.dumps({"paid_calls": 0, "cases": len(rows), "all_expected_refs_found":
                      sum(not r["missing_in_this_lane"] for r in rows)}))
    return 0


async def live(args):
    # Imports/settings/secret access only after explicit live opt-in.
    import httpx
    from api.ai import pipeline
    from api.ai.cache import answer_cache
    from api.ai.cloud_provider import _CloudBase, FallbackProvider
    from api.config import get_settings
    from api.schemas import AIAnswerRequest

    settings = get_settings()
    if settings.cloud_ai_provider != "openrouter" or settings.cloud_ai_model != MODEL:
        raise EvaluationStop("configured_model_is_not_luna_openrouter")
    # No production conversation writes and no web-ingestion writes in this pilot.
    # DB retrieval uses the actual current corpus; this is not full HTTP/UI timing.
    settings = replace(settings, official_web_research_enabled=False)
    budget = Budget(args.budget_usd)
    records, calls = [], []
    with httpx.Client(timeout=15, trust_env=False) as client:
        response = client.get("https://openrouter.ai/api/v1/models")
        response.raise_for_status()
        model = next(m for m in response.json()["data"] if m["id"] == MODEL)
    pricing = model["pricing"]
    input_rate = max(positive_decimal(pricing["prompt"]),
                     Decimal(str(pricing.get("input_cache_write", 0))))
    output_rate = positive_decimal(pricing["completion"])
    # Catalog web_search is an optional tool fee, not a text-request fee.
    # This pilot never enables model tools/plugins; enforce that at dispatch too.
    if any(Decimal(str(pricing.get(k, 0))) != 0 for k in ("request", "internal_reasoning")):
        raise EvaluationStop("unsupported_additional_pricing")
    output_limit = getattr(args, "max_output_tokens", 16384)
    original_post = _CloudBase._post
    original_local = FallbackProvider._generate_local
    original_settings = pipeline.get_settings

    def no_local(*a, **kw):
        raise EvaluationStop("cloud_failed_no_local_fallback_in_comparison")

    def metered(provider, url, headers, payload):
        if url != "https://openrouter.ai/api/v1/chat/completions" or payload.get("model") != MODEL:
            raise EvaluationStop("unexpected_paid_endpoint_or_model")
        if payload.get("tools") or payload.get("plugins") or payload.get("web_search_options"):
            raise EvaluationStop("paid_tools_not_allowed_in_comparison")
        # A UTF-8 byte bound plus framing margin is deliberately conservative;
        # restrict to short-context pricing, reserve 2x and stop BEFORE dispatch.
        prompt_bound = len(json.dumps(payload["messages"], ensure_ascii=False).encode()) + 1024
        if prompt_bound > 200000:
            raise EvaluationStop("prompt_outside_short_context_budget")
        reserve = budget.reserve(2 * (prompt_bound * input_rate + output_limit * output_rate))
        payload = dict(payload, max_tokens=output_limit, usage={"include": True})
        payload.pop("max_completion_tokens", None)
        tick = time.monotonic()
        try:
            body = original_post(provider, url, headers, payload)
        except Exception:
            budget.settle(reserve)
            raise EvaluationStop("provider_error_cost_reserved_no_retry") from None
        usage = body.get("usage") or {}
        if usage.get("cost") is None:
            budget.settle(reserve)
            raise EvaluationStop("provider_cost_missing")
        budget.settle(reserve, usage["cost"])
        calls.append({"model": MODEL, "reasoning": payload.get("reasoning"),
                      "seconds": round(time.monotonic() - tick, 3), "usage": usage,
                      "prompt_sha256": hashlib.sha256(json.dumps(payload["messages"], sort_keys=True).encode()).hexdigest()})
        return body

    _CloudBase._post = metered
    FallbackProvider._generate_local = no_local
    pipeline.get_settings = lambda: settings
    report = {"model": MODEL, "budget_usd": str(budget.limit), "pricing": pricing,
              "web_research": False, "production_settings_changed": False,
              "output_token_cap_for_eval_only": output_limit, "rows": records, "calls": calls}
    write_report(args.output, report)
    try:
        cases, efforts = selected_matrix(args)
        for case_index, case in enumerate(cases):
            # Fresh per-effort context, no saved conversation/history bias.
            # Rotate order so every case does not give low the cold-host penalty.
            offset = case_index % len(efforts)
            for effort in efforts[offset:] + efforts[:offset]:
                answer_cache.clear()
                tick, start_cost, start_call = time.monotonic(), budget.spent, len(calls)
                try:
                    answer, timing = await pipeline.execute_answer(
                        AIAnswerRequest(question=case["question"], reasoning_effort=effort), None)
                    body = answer.model_dump(mode="json")
                    row = {"case": case["id"], "effort": effort, "answer": body,
                           "score": score(case, body), "timings": asdict(timing)}
                except EvaluationStop:
                    raise
                except Exception as error:
                    row = {"case": case["id"], "effort": effort, "error_class": type(error).__name__}
                row.update(seconds=round(time.monotonic() - tick, 3),
                           cost_usd=str(budget.spent - start_cost), calls=len(calls) - start_call)
                records.append(row)
                report.update(spent_usd=str(budget.spent), summary=summarize(records))
                write_report(args.output, report)
                print(json.dumps({k: row[k] for k in ("case", "effort", "seconds", "cost_usd", "calls")}), flush=True)
    except EvaluationStop as stop:
        report["stopped"] = str(stop)
    finally:
        _CloudBase._post, FallbackProvider._generate_local = original_post, original_local
        pipeline.get_settings = original_settings
        report.update(spent_usd=str(budget.spent), held_usd=str(budget.held), summary=summarize(records))
        write_report(args.output, report)
    return 2 if report.get("stopped") else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--replay", type=Path)
    mode.add_argument("--sources", action="store_true")
    parser.add_argument("--budget-usd")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int, default=10, choices=range(1, 11))
    parser.add_argument("--case", action="append", choices=[c["id"] for c in CASES])
    parser.add_argument("--effort", action="append", choices=EFFORTS)
    parser.add_argument("--max-output-tokens", type=int, default=16384, choices=(4096, 8192, 16384))
    args = parser.parse_args()
    if args.sources:
        if not args.output or args.output.exists():
            parser.error("Source snapshot requires a new output path")
        return capture_sources(args)
    if not args.live:
        if args.replay:
            report = json.loads(args.replay.read_text(encoding="utf-8"))
            by_id = {c["id"]: c for c in CASES}
            for row in report["rows"]:
                if "answer" in row:
                    row["score"] = score(by_id[row["case"]], row["answer"])
            print(json.dumps(summarize(report["rows"]), ensure_ascii=False, indent=2))
        else:
            cases, efforts = selected_matrix(args)
            print(json.dumps({"paid_calls": 0, "cases": cases, "efforts": efforts}, ensure_ascii=False, indent=2))
        return 0
    if not args.budget_usd or not args.output or args.output.exists():
        parser.error("Live requires explicit budget and a new output path")
    positive_decimal(args.budget_usd)
    logging.disable(logging.CRITICAL)
    try:
        return asyncio.run(live(args))
    except (EvaluationStop, Exception) as error:
        # Never print exception strings: SDKs can include authorization/payloads.
        print(json.dumps({"stopped": type(error).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
