"""Shared grounded-answer pipeline: retrieve, cache, generate, verify, persist."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import AsyncIterator, Callable, Coroutine, Sequence
from dataclasses import dataclass, field, replace
from time import monotonic
from typing import Any, Literal
from uuid import UUID

import psycopg
from fastapi import HTTPException
from psycopg.errors import InsufficientPrivilege

from api.audit import AI_ANSWER, AuditContext, record_event
from api.ai.case_questions import asks_for_legal_assessment, is_case_file_question
from api.ai.answer_kind import AnswerKind
from api.ai.conversation_intent import NON_LEGAL_REPLY as _NON_LEGAL_REPLY
from api.ai.document_selection import selected_document_coverage
from api.ai.cache import (
    answer_cache,
    answer_cache_key,
    history_fingerprint,
    source_fingerprint,
    restore_verified_natural_answer,
)
from api.ai.conversation_history import (
    ConversationNotFound,
    load_conversation_context,
    needs_standalone_rewrite,
    retrieval_question,
    standalone_question,
)
from api.ai.embeddings import EmbeddingProviderError, create_embedding_provider
from api.embed_pause import pause_embeddings, resume_embeddings, unload_ollama_model
from api.ai.history import ConversationScopeMismatch, record_exchange
from api.ai.workspace_scope import office_project_case, project_document_coverage
from api.document_indexing import case_document_coverage, sweep_unindexed
from api.ai.live_verify import verify_third_party_contexts
from api.ai.consulted_relevance import relevant_chunk_ids
from api.ai.discovery import (LIMIT_FAILED, LIMIT_NONE, candidate_pool_size, retrieval_limit, search_summary,
                              select_answer_contexts, worse_limit)
from api.ai.fast_statute import try_fast_statute
from api.ai.event_lookup import lookup_event_basis, load_current_event_reference
from api.ai.relevance import case_law_requested, documents_answer, documents_named_in, missing_document_references
from api.ai.trust import usable_as_evidence, verified_contexts
from api.ai.turkish_text import restore_turkish
from api.ai.on_demand_verify import (
    explicit_statute_reference,
    verify_pending_statute,
    verify_relevant_pending_statute,
)
from api.ai.providers import AIProvider, AIProviderError, create_provider
from api.ai.cloud_provider import AuxiliaryProvider, DeepSeekCloudProvider, FallbackProvider, create_cloud_provider
from api.ai.rag import HistoryTurn, RAGContext, generate_grounded_answer
from api.ai.retrieval import retrieve_contexts, retrieve_document_contexts
from api.ai.verification import (
    VerifiedAnswer,
    has_insufficient_source_signal,
    is_insufficient_source_reply,
    prune_rejected_lines,
    verify_answer,
)
from api.config import get_settings
from api.db import authenticated_database_connection, database_connection
from api.ai import verification_queue
from api.schemas import AIAnswerRequest, AIAnswerResponse, AICitation
from api.uyap_record_document import record_contexts

logger = logging.getLogger(__name__)

StageCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None] | None]
_generation_lock = asyncio.Lock()
_cloud_generation_slots = {}


def _generation_slot(provider, local_provider):
    """Local GPU stays serialized; independent cloud requests need not queue
    behind an entire unrelated writer/checker/repair sequence. The fan-out is
    still bounded, not unlimited paid-provider concurrency.
    """
    if ((provider is local_provider and getattr(provider, "name", "") != "bedrock")
            or (isinstance(provider, FallbackProvider) and provider.fell_back)):
        return _generation_lock
    loop = asyncio.get_running_loop()
    for old_loop in list(_cloud_generation_slots):
        if old_loop.is_closed():
            _cloud_generation_slots.pop(old_loop, None)
    if loop not in _cloud_generation_slots:
        _cloud_generation_slots[loop] = asyncio.BoundedSemaphore(4)
    return _cloud_generation_slots[loop]


GenerationProfile = Literal["default", "deep_research"]


@dataclass(frozen=True, slots=True)
class _ServerReplyProvider:
    """Do not label server-owned social/status text as a model generation."""
    name: str = "application"
    model: str = "conversation-router-v1"

    def generate(self, *, system_instruction: str, prompt: str) -> str:
        raise AIProviderError("Uygulama yanıtı model çağrısı yapmaz")


# Synthesis failures where no checker judged the meaning: the draft quoted inexactly, had the wrong shape, mismatched a
# number, or a source chunk could not be shown whole. Only these fall back to the verified-quote route.
_MECHANICAL_SYNTHESIS_REJECTIONS = frozenset({"evidence", "draft_shape", "numeric_polarity", "source_shape", "budget", "answer_focus",
                                              # claims WE left out made an otherwise fully supported answer incomplete
                                              "dropped_coverage",
                                              # the writer claimed a source gap the checker rejected (sources cover it)
                                              "unconfirmed_source_gap"})


_DIGEST_REASONS = frozenset({"numeric_polarity", "research_coverage", "dropped_coverage", "budget", "source_shape", "draft_shape", "answer_focus"})


def _wants_source_text(question: str) -> bool:
    return bool(re.search(r"\baynen\b|\bolduğu gibi\b|\btam met\w*|\bmadde metn\w*", question, re.I))


def cloud_allowed(request: AIAnswerRequest) -> bool:
    """Bulut modeline yalnız genel hukuk sorusu gider: dava, proje ya da seçili belge kapsamı varsa hep yerel model."""
    return not (request.project_id or request.case_id or request.office_project_id or request.selected_document_ids)


def answer_provider(
    settings, request: AIAnswerRequest, local: AIProvider, *, profile: GenerationProfile = "default",
) -> AIProvider:
    """Sunucu tarafından seçilen profil; özel kapsamlar her profilde yerelde kalır."""
    if profile not in {"default", "deep_research"}:
        raise ValueError("Bilinmeyen üretim profili")
    if not cloud_allowed(request):
        return local
    if getattr(settings, "ai_provider", "") == "bedrock":
        # Both public and scoped primary providers are Bedrock, but retain
        # distinct identities so public-only retrieval/cache guards stay intact.
        # A private request still uses its scoped primary, never public caches/web.
        from copy import copy
        return copy(local)
    if profile == "deep_research":
        # Genel sohbetin sağlayıcısını/anahtarını miras alma; ayrı açık onay gerekir.
        if not getattr(settings, "deep_research_cloud_enabled", False):
            return local
        options = dict(
            provider_name=getattr(settings, "deep_research_ai_provider", "deepseek"), model=settings.deep_research_ai_model,
            api_key=settings.deep_research_ai_api_key,
            timeout_seconds=settings.deep_research_ai_timeout_seconds,
            max_output_tokens=settings.deep_research_ai_max_output_tokens,
            reasoning_effort=settings.deep_research_ai_reasoning_effort,
        )
    else:
        if not getattr(settings, "cloud_ai_provider", ""):
            return local
        options = dict(
            provider_name=settings.cloud_ai_provider, model=settings.cloud_ai_model, api_key=settings.cloud_ai_api_key,
            timeout_seconds=settings.cloud_ai_timeout_seconds, max_output_tokens=settings.cloud_ai_max_output_tokens,
            reasoning_effort=getattr(settings, "cloud_ai_reasoning_effort", "low"),
        )
    # Per-request Luna choice; never changes global settings or private routing.
    if (profile == "default" and request.reasoning_effort is not None
            and options["provider_name"] == "openrouter"
            and options["model"] == "openai/gpt-6-luna"):
        options["reasoning_effort"] = request.reasoning_effort
    try:
        cloud = create_cloud_provider(**options)
    except AIProviderError as exc:
        logger.warning("Bulut modeli kurulamadı (%s); yerel model kullanılıyor", exc)
        return local
    return FallbackProvider(primary=cloud, fallback=local)


def provider_cache_model(provider: AIProvider, profile: GenerationProfile) -> str:
    """Aynı modelin farklı düşünme/token profilleri birbirinin cevabını kullanmasın."""
    if isinstance(provider, FallbackProvider) and not provider.fell_back:
        cloud = provider.primary
        auxiliary_policy = ":aux-none-uncapped-v2" if (
            profile == "deep_research" or isinstance(cloud, DeepSeekCloudProvider)
        ) else ""
        return f"{profile}:{cloud.name}:{cloud.model}:{getattr(cloud, 'reasoning_effort', '')}:{cloud.max_output_tokens}{auxiliary_policy}"
    return provider.model


_FREE_ANSWER_SOURCES_PER_SENTENCE = 4
_FREE_ANSWER_SOURCES_PER_PART = 6
_PERIOD_FACET = re.compile(r"zamanaşımı|hak düşürücü|(?:dava|başvuru|itiraz|temyiz|istinaf|şikayet|şikâyet)\w*\s+(?:açma\s+)?(?:süre|müddet)|hangi süre|ne kadar süre|kaç (?:gün|ay|yıl|hafta)|süresi", re.IGNORECASE)


def _free_answer(provider: AIProvider, question: str, contexts: list[RAGContext], history, timings: "PipelineTimings",
                 checker: AIProvider, on_draft=None, *, public_web_scope=False, prepared_plan=None,
                 on_partial=None) -> "VerifiedAnswer | None":
    from api.ai.free_answer import free_verified_answer
    from api.ai.evidence_pool import balanced_evidence, query_scoped_evidence
    from api.ai.request_memo import memoize_request

    settings = get_settings()
    from api.ai.llm_meter import LLMMeter, metered
    meter = LLMMeter()
    stage_started = monotonic()
    stage_ms = timings.extra.setdefault('natural_stages_ms', {})
    from api.ai.relevance import case_law_requested
    if case_law_requested(question) and sum(1 for context in contexts if context.source_type == "court_decision") < _FREE_ANSWER_EXTRA_DECISIONS:
        # Bilinen konularda arama "hızlı kanun yolu"na girip havuza hiç karar koymuyor (kira sorusunda yalnız TBK m. 315 vardı);
        # yargı uygulaması cevaptan eksik kalıyordu. Sorunun kendi karar araması ayrıca çalışır, en çok 3 karar eklenir.
        try:
            with database_connection() as connection:
                found = verified_contexts(retrieve_contexts(connection, question=question, top_k=8))
            contexts = _with_decisions(contexts, found, question=question)
        except Exception:  # noqa: BLE001 - decisions are an enrichment; the statutes alone still answer
            logger.exception("Serbest cevap için karar araması başarısız")

    def vector(sentence: str) -> list[float] | None:
        model = getattr(settings, "legislation_embedding_model", "")
        if not model:
            return None
        try:
            from api.ai.relevance import semantic_search_text
            embedder = create_embedding_provider(
                provider_name="ollama", model=model, dimensions=1024, ollama_base_url=settings.ollama_base_url,
                ollama_timeout_seconds=min(8.0, settings.ollama_timeout_seconds))
            return embedder.embed_query(semantic_search_text(sentence))
        except EmbeddingProviderError:
            return None

    def decision_vector(sentence: str) -> list[float] | None:
        # The shared (decision) vector of this part. Without it a part searched decisions only by words, and a common legal term
        # ("nafaka", "itirazın iptali") matches hundreds of thousands of chunks, so the lexical lane fell back to an unranked sample;
        # the semantic lane over the 21.9 M embedded chunks ran once, for the whole question only (measured 2026-10-30).
        model = getattr(settings, "embedding_model", "")
        if not model or not getattr(settings, "rag_query_embedding", False):
            return None
        try:
            from api.ai.relevance import semantic_search_text
            embedder = create_embedding_provider(
                provider_name=settings.embedding_provider, model=model, dimensions=settings.embedding_dimensions,
                ollama_base_url=settings.ollama_base_url, ollama_timeout_seconds=min(8.0, settings.ollama_timeout_seconds))
            return embedder.embed_query(semantic_search_text(sentence))
        except EmbeddingProviderError:
            return None

    @memoize_request
    def concept_lookup(query: str) -> list[RAGContext]:
        # Different subquestions often share the same legal concept. Own
        # transaction + request-local single-flight: no repeated corpus sort,
        # no failed transaction leaking into successful sibling searches.
        with database_connection() as connection:
            return retrieve_contexts(connection, question=query,
                                     top_k=_FREE_ANSWER_SOURCES_PER_SENTENCE)

    @memoize_request
    def retrieve(sentence: str) -> list[RAGContext]:
        # A planner's numeric reference is an exact lookup, not a semantic
        # query. Do not embed/search the whole corpus before reading that
        # very provision. Only this entire canonical query shape qualifies;
        # a fact pattern mentioning the same article keeps broad discovery.
        reference = re.fullmatch(r'([0-9]{1,5}) sayılı Kanun m\. ([0-9]{1,3}(?:/[A-Za-z])?)', sentence)
        if reference and public_web_scope:
            from api.ai.retrieval import STATUTE_RETRIEVAL_SQL, _execute_retrieval
            with database_connection() as connection:
                return verified_contexts(_execute_retrieval(connection, STATUTE_RETRIEVAL_SQL,
                    dict(law_no=reference[1], article_no=reference[2], as_of=None,
                         top_k=_FREE_ANSWER_SOURCES_PER_SENTENCE), timeout='5s'))
        # Kanun maddeleri önce (konu tablosu + bge-m3 anlam araması), sonra aynı cümlenin karar aramaları: karar parçaları
        # çoğu zaman cümle sınırında temiz bölünmediğinden kanıt olarak yalnız resmî madde sık kullanılabilir.
        legislation_vector = vector(sentence)
        part_vector = decision_vector(sentence)
        search_info: dict = {}
        from concurrent.futures import ThreadPoolExecutor

        from api.ai.search_plan import research_queries
        concept = research_queries(sentence)[1:]
        # The concept lookups do not depend on the main search, so they run beside it: two heavy lexical lanes queued one behind
        # the other took 15 s for a part (measured 2026-10-30). Each opens its own connection; a failed optional lookup cannot
        # touch the main search's transaction.
        concept_pool = ThreadPoolExecutor(max_workers=len(concept)) if concept else None
        concept_futures = [concept_pool.submit(concept_lookup, query) for query in concept] if concept_pool else []
        statutes: list[RAGContext] = []
        found: list[RAGContext] = []
        try:
            try:
                with database_connection() as connection:
                    statutes = _case_statute_contexts(connection, sentence, [])
                    found = retrieve_contexts(connection, question=sentence, top_k=_FREE_ANSWER_SOURCES_PER_SENTENCE,
                                              legislation_embedding=legislation_vector, expand_legislation=True,
                                              query_embedding=part_vector,
                                              embedding_model=settings.embedding_model if part_vector is not None else None,
                                              parallel_public_vectors=part_vector is not None,
                                              diagnostics=search_info)
            except psycopg.Error:
                # The database refused this part's search (overload, timeout): the part keeps what it already found (the topic
                # statutes), the user is told the research may be incomplete, and the part without any source is named in the
                # answer by the existing "no proven source for this part" note instead of the whole request failing with a 500.
                logger.warning("Bölüm araması veritabanı hatasıyla yarım kaldı", exc_info=True)
                search_info["partial"] = True
                search_info["decision_search"] = "timeout"
            # A lane of this part's search ran out of time or was sampled: the user is told the research may be incomplete (the
            # outer search used to be the only source of that warning).
            # (not inside "free_answer": the attempt loop clears that dictionary)
            searches = timings.extra.setdefault("part_searches", [])
            searches.append({"query": sentence[:60], "partial": bool(search_info.get("partial")),
                             "limit": retrieval_limit(search_info),
                             "branches": [(b.get("name"), b.get("status"), b.get("seconds"))
                                          for b in search_info.get("branches", [])]})
            concept_hits = []
            for future in concept_futures:
                try:
                    concept_hits.extend(future.result())
                except psycopg.Error:
                    logger.warning('Hukuk kavramı arama kolu tamamlanamadı')
        finally:
            if concept_pool is not None:
                concept_pool.shutdown(wait=False)
        # Hints and semantic/lexical discovery are independent evidence lanes.
        # Two broad hints must not hide the directly relevant semantic statute.
        return balanced_evidence([query_scoped_evidence(sentence, lane) for lane in [
            statutes,
            [c for c in found if c.source_type == "legislation"],
            [c for c in found if c.source_type != "legislation"],
            concept_hits,
        ]], _FREE_ANSWER_SOURCES_PER_PART)

    # Plan → search per part: a question with several subjects ("nafaka, velayet, mal paylaşımı süresi") got sources only for the
    # dominant one and the rest was skipped silently (2026-10-25). Each part now brings its own statutes and decisions.
    from concurrent.futures import ThreadPoolExecutor

    from api.ai.free_answer import plan_question

    planner_started = monotonic()
    if prepared_plan:
        # The outer pipeline already paid for and validated a research plan.
        # Reuse it instead of asking another planner the same question.
        plan = list(prepared_plan)
    else:
        planner = _planner(settings)
        if planner is not None:
            plan = plan_question(metered(planner, meter), question, history)
        else:
            # No "short question needs no planner" shortcut: it sent every question under 15 words without "ve" straight to a raw
            # word search (measured 2026-10-30: "Aldığım telefon iki ayda bozuldu..." was never turned into "ayıplı mal", and
            # "telefon" brought prison-administration rules). `plan_question` itself skips the model for a recognised one-topic
            # question, so only questions the system does not know pay for the planning call.
            from api.ai.free_answer import simple_search_plan
            plan = simple_search_plan(question, history) or plan_question(metered(checker, meter), question, history)
    if not plan:
        timings.extra.setdefault("free_answer", {}).update(reason="not_legal", status="fallback")
        return None
    # The planner may treat requested precedents as output decoration and omit
    # them from its legal aspects. Preserve that explicit research requirement.
    from api.ai.relevance import case_law_requested
    if case_law_requested(question) and not any(case_law_requested(text) for text, _ in plan):
        from api.ai.search_plan import research_queries
        # The part's own text is a plain case-law question: the raw question also carried instructions to the assistant ("what
        # could you answer with statutes only?"), and the writer answered those with sentences about itself (2026-10-30).
        plan = [*plan, ("Bu konudaki Yargıtay kararları ne diyor?", research_queries(question))]
    queries = [query for _, part_queries in plan for query in part_queries]
    stage_ms['planning'] = round((monotonic() - stage_started) * 1000, 1)
    stage_ms['planner_call'] = round((monotonic() - planner_started) * 1000, 1)
    stage_started = monotonic()
    from api.ai.free_answer import simple_search_plan, _usable
    # Progressive retrieval: validate exact local provisions for EVERY planned
    # facet before running the expensive semantic/precedent fan-out. This is
    # structural source readiness, never a completeness or truth verdict.
    # Explicit case-law, historical and private scopes keep full discovery.
    local_plan_lanes = []
    if public_web_scope and not case_law_requested(question):
        from api.ai.relevance import context_relevant
        for text, part_queries in plan:
            if _PERIOD_FACET.search(text):
                # A limitation/filing period is where statute text alone is least reliable: the article may be wrong, silent
                # or read differently by the courts (TMK m. 178's one year vs. the Hukuk Genel Kurulu's ten years for the
                # participation claim, 2026-10-30). Such a facet always gets the full statute + precedent discovery.
                local_plan_lanes.append([])
                continue
            reference_queries = [q for q in part_queries if re.fullmatch(
                r'[0-9]{1,5} sayılı Kanun m\. [0-9]{1,3}(?:/[A-Za-z])?', q)]
            # A planner may name only one provision for a multi-path facet.
            # Supplement its references with the existing deterministic topic
            # catalogue BEFORE treating an exact local lane as ready. These
            # numbers are search hints, never generated law or proof of support.
            from api import statute_hints
            reference_queries.extend(f'{hint.law_no} sayılı Kanun m. {hint.article_no}'
                                     for hint in statute_hints.suggest(text))
            reference_queries = list(dict.fromkeys(reference_queries))
            rows = list({c.chunk_id: c for q in reference_queries for c in _safe_retrieve(retrieve, q)}.values())
            if rows:
                from api.ai.provision_context import restore_provisions
                try:
                    with database_connection() as connection:
                        rows = restore_provisions(rows, connection)
                except psycopg.Error:
                    rows = []
            rows = [c for c in rows if _usable(c, 36000) is not None and context_relevant(text, c)]
            local_plan_lanes.append(rows)
    local_plan_reused = bool(local_plan_lanes) and all(local_plan_lanes)
    reuse_initial = (len(plan) == 1 and plan[0][0] == question
                     and simple_search_plan(question, history) is not None)
    initial_usable = [c for c in contexts if _usable(c, 36000) is not None] if reuse_initial else []
    # one worker per query: with two, a three-part question searched in two rounds (measured 2026-10-30: 10 s for 2 parts)
    with ThreadPoolExecutor(max_workers=len(queries)) as pool_executor:
        if local_plan_reused:
            found_per_query = [rows for rows, (_, part_queries) in zip(local_plan_lanes, plan) for _ in part_queries]
            contexts = list({c.chunk_id: c for rows in local_plan_lanes for c in rows}.values())
        elif initial_usable:
            found_per_query = [initial_usable for _ in queries]
        else:
            # Duplicate queued queries must not occupy a worker waiting on
            # single-flight work while a different query waits behind them.
            unique_queries = list(dict.fromkeys(queries))
            found_by_query = dict(zip(unique_queries,
                pool_executor.map(lambda q: _safe_retrieve(retrieve, q), unique_queries)))
            found_per_query = [found_by_query[q] for q in queries]
    timings.extra['initial_evidence_reused'] = bool(initial_usable)
    timings.extra['local_plan_evidence_reused'] = local_plan_reused
    stage_ms['part_search'] = round((monotonic() - stage_started) * 1000, 1)
    stage_started = monotonic()
    # Resolve canonical local statute tails BEFORE deciding that an official
    # PDF must be downloaded. A recoverable local chunk is not missing data.
    from api.ai.provision_context import restore_provisions
    local_pool = list({c.chunk_id: c for c in [*contexts, *(c for lane in found_per_query for c in lane)]}.values())
    try:
        with database_connection() as connection:
            restored_local = restore_provisions(local_pool, connection)
        restored_by_id = {c.chunk_id: c for c in restored_local}
        contexts = [restored_by_id[c.chunk_id] for c in contexts]
        found_per_query = [[restored_by_id[c.chunk_id] for c in lane] for lane in found_per_query]
    except psycopg.Error:
        logger.warning('Web öncesi yerel madde bağlamı okunamadı; kaynak politikası korunuyor')
    stage_ms['preweb_local_restore'] = round((monotonic() - stage_started) * 1000, 1)
    stage_started = monotonic()
    # Fetch only after the local research plan. The web lane gets no history,
    # names, uploads or raw outbound query: adapters reduce plans to numeric
    # references / fixed legal vocabulary. Persisted corpus IDs are required.
    web_contexts = []
    if public_web_scope and getattr(settings, 'official_web_research_enabled', False):
        from api.ai.official_research import research_official
        from api.ai.chat_research_policy import official_research_reasons
        from api.ai.relevance import context_relevant
        research_pool = [*contexts, *(c for lane in found_per_query for c in lane)]
        reasons = official_research_reasons(question, plan, research_pool,
            usable=lambda c: _usable(c, 16000) is not None, relevant=context_relevant)
        timings.extra['official_web_routing'] = list(reasons) or ['local_sources_ready']
        if reasons:
            result = research_official(queries, research_pool, public_scope=public_web_scope)
            web_contexts = list(result.contexts)
            timings.extra['official_web'] = list(result.statuses)
    stage_ms['official_web'] = round((monotonic() - stage_started) * 1000, 1)
    stage_started = monotonic()
    per_part: list[list[RAGContext]] = []
    cursor = 0
    for _, part_queries in plan:
        lanes = found_per_query[cursor:cursor + len(part_queries)]
        cursor += len(part_queries)
        if web_contexts:
            from api.ai.retrieval import _hit_quality_score
            relevant = sorted(web_contexts, key=lambda c: -_hit_quality_score(' '.join(part_queries), c))
            lanes.append([c for c in relevant if _hit_quality_score(' '.join(part_queries), c) > 0])
        per_part.append(balanced_evidence(
            [query_scoped_evidence(' '.join(part_queries), lane) for lane in lanes],
            _FREE_ANSWER_SOURCES_PER_PART))
    # Interleave the parts so the character budget never drops a whole part; then the question's own sources.
    ordered: list[RAGContext] = []
    for rank in range(max((len(p) for p in per_part), default=0)):
        ordered.extend(p[rank] for p in per_part if rank < len(p))
    contexts = list({c.chunk_id: c for c in [*ordered, *contexts, *web_contexts]}.values())
    # Recover full canonical provisions when fixed-size ingestion cut a rule in
    # mid-sentence. Same source/revision/trust predicates; no chunk-tail guesses.
    from api.ai.provision_context import restore_provisions
    try:
        with database_connection() as connection:
            contexts = restore_provisions(contexts, connection)
    except psycopg.Error:
        logger.warning("Tam mevzuat bağlamı okunamadı; mevcut doğrulanmış parçalar korunuyor")
    from api.ai.decision_context import restore_decisions
    try:
        with database_connection() as connection:
            contexts = restore_decisions(contexts, connection)
    except psycopg.Error:
        logger.warning('Tam karar bağlamı okunamadı; mevcut doğrulanmış parçalar korunuyor')
    # A request naming a court is narrower than generic "case-law" research.
    # Don't let an official lower-court/BAM source stand in for requested Yargıtay.
    from api.ai.decision_attribution import requested_court_evidence
    contexts = requested_court_evidence(question, contexts)
    parts = [(text, frozenset(c.chunk_id for c in found)) for (text, _), found in zip(plan, per_part)]
    stage_ms['restore_and_select'] = round((monotonic() - stage_started) * 1000, 1)
    stage_started = monotonic()
    from api.ai.evidence_readiness import prepare_parts, requested_decisions_ready
    from api.ai.free_answer import _usable

    def normalize_repair(rows):
        with database_connection() as connection:
            rows = restore_provisions(rows, connection)
            rows = restore_decisions(rows, connection)
        return requested_court_evidence(question, rows)

    contexts, parts, readiness = prepare_parts(parts, contexts, retrieve,
        usable=lambda c: _usable(c, 36000) is not None, normalize=normalize_repair,
        ready=requested_decisions_ready)
    timings.extra['evidence_readiness'] = readiness
    stage_ms['prewrite_readiness'] = round((monotonic() - stage_started) * 1000, 1)
    stage_started = monotonic()
    timings.extra.setdefault("free_answer", {})["plan"] = [text for text, _ in plan]
    answer = free_verified_answer(metered(provider, meter), question=question, contexts=contexts, retrieve=retrieve, history=history,
                                checker_provider=metered(_checker_for(settings, provider, checker), meter),
                                diagnostics=timings.extra.setdefault("free_answer", {}),
                                on_draft=on_draft, parts=parts, deferred_research=local_plan_reused,
                                parallel_parts=getattr(settings, 'free_answer_parallel_parts', True),
                                triage_sources=getattr(settings, 'free_answer_source_triage', True),
                                on_partial=on_partial,
                                explain_in_background=getattr(settings, 'free_answer_defer_reasons', True))
    stage_ms['write_and_check'] = round((monotonic() - stage_started) * 1000, 1)
    answer_info = timings.extra.get('free_answer') or {}
    selected_attempt = {key: answer_info[key] for key in ('write_seconds', 'check_seconds', 'attempts')
                        if isinstance(answer_info.get(key), (int, float))}
    timings.extra['llm_meter'] = meter.summary()
    logger.warning('Assistant stage durations ms=%s readiness=%s selected_attempt=%s llm=%s attempts=%s',
                   stage_ms, readiness, selected_attempt, timings.extra['llm_meter'], answer_info.get('attempts'))
    return answer



def _checker_for(settings, provider: AIProvider, checker: AIProvider) -> AIProvider:
    """The independent check on its own model (`CLOUD_AI_CHECK_MODEL`): a writer that also judges its own sentences lets its
    blind spots through (2026-10-30: a senseless sentence about the worker's own justified termination passed). Same cloud
    provider and key, same local fallback; an unset model, a local run or an already fallen-back request keep `checker`."""
    model = getattr(settings, "cloud_ai_check_model", "")
    if not model or not isinstance(provider, FallbackProvider) or provider.fell_back:
        return checker
    try:
        from dataclasses import replace

        return FallbackProvider(primary=replace(provider.primary, model=model), fallback=provider.fallback)
    except (TypeError, AIProviderError):
        return checker


def _planner(settings) -> AIProvider | None:
    """Splitting the question is an easy job: on Gemini it runs on the light model, whose free quota is separate, so the main
    model's daily quota is left for writing and checking (2026-10-25: the free quota ran out after a few test questions). A busy
    light model is not waited for; the caller then plans with the main model."""
    if getattr(settings, "ai_provider", "") == "bedrock":
        return None  # all generation uses the single configured primary model
    model = getattr(settings, "cloud_ai_plan_model", "")
    provider_name = getattr(settings, "cloud_ai_provider", "")
    if provider_name not in {"gemini", "bedrock"} or not model:
        return None
    try:
        from dataclasses import replace

        planner = create_cloud_provider(provider_name=provider_name, model=model, api_key=settings.cloud_ai_api_key,
                                        timeout_seconds=20.0, reasoning_effort="low")
        return replace(planner, busy_waits=())
    except AIProviderError:
        return None


def _safe_retrieve(retrieve, query: str) -> list[RAGContext]:
    try:
        return retrieve(query)
    except Exception:  # noqa: BLE001 - one failed part search must not sink the answer; that part is reported as not found
        logger.exception("Parça araması başarısız")
        return []



_FREE_ANSWER_EXTRA_DECISIONS = 3


# Yalnız cevap ZATEN çıkmadığında VE hiç kaynak bulunamadığında mesajı seçer ("TÜFE nedir" hukuk sözcüğü taşımaz ama kira
# artışının ölçütüdür; kaynak bulunduysa soru hukukidir, 2026-10-25); soruyu reddetmek için kullanılmaz ("komşum ağacımı kesti" hukuk sözcüğü taşımasa
# da hukuki sorudur ve normal yoldan geçer). "Hava nasıl, pizza tarifi" sorusuna "kaynaklar bulundu ama doğrulayamadım" demek
# yanıltıcıydı (2026-10-25).
_LEGAL_WORD = re.compile(
    r"hukuk|kanun|yasa|madde|mevzuat|yönetmelik|dava|mahkeme|yargıtay|danıştay|anayasa|avukat|hâkim|hakim|savcı|"
    r"tazminat|sözleşme|işçi|işveren|işten|kıdem|ihbar|maaş|ücret|kira|ev sahibi|boşan|nafaka|velayet|miras|tapu|"
    r"ceza|suç|şikayet|icra|haciz|borç|alacak|faiz|zamanaşımı|süre|hak|yasal|vergi|şirket|ortak|sigorta|kaza|"
    r"tebligat|itiraz|başvuru|izin|fesih|feshet|arabulucu|noter|vekalet|vasiyet|mülk|komşu|evlilik|eş|çocuk|polis",
    re.IGNORECASE)
# The model service itself failed (quota / overload): saying "doğrulayamadım" blamed the sources (2026-10-25, Gemini free quota).
_BUSY_REPLY = ("Yapay zekâ hizmeti şu anda yoğun olduğu için cevabı hazırlayamadım. Lütfen birkaç dakika sonra yeniden deneyin.")


def _looks_non_legal(question: str) -> bool:
    from api.ai.query_vocabulary import has_search_abbreviation
    return not has_search_abbreviation(question) and not _LEGAL_WORD.search(question.replace("İ", "i"))


def _missing_requested_article(question: str, contexts: Sequence[RAGContext]) -> tuple[str, str] | None:
    """Soru tek bir kanunun tek bir maddesini açıkça soruyorsa ve o madde getirilen kaynaklarda yoksa (kanun no, madde no)."""
    from api.ai.retrieval import question_article_numbers, question_law_numbers

    articles = set(question_article_numbers(question))
    laws = set(question_law_numbers(question)) - articles  # "madde 999" is also read as a law number
    if len(laws) != 1 or len(articles) != 1:
        return None
    law_no, article_no = next(iter(laws)), next(iter(articles))
    found = any(c.source_type == "legislation" and c.law_no == law_no and (c.article_no or "").lower() == article_no
                for c in contexts)
    return None if found else (law_no, article_no)


def _missing_article_text(law_no: str, article_no: str, official_statuses) -> str:
    """What the user is told about an article that is not in the verified corpus. Only an official text that was read and
    identified, and that has no such article, allows "there is no such article"; otherwise only our own records are spoken for."""
    from datetime import date as _date
    absent = any(status.get('status') == 'article_absent' and status.get('law_no') == law_no and status.get('article_no') == article_no
                 for status in official_statuses or ())
    if absent:
        from api.ai.currency_note import turkish_date
        return (f"{law_no} sayılı Kanunun resmî metninde {article_no}. madde bulunmuyor: Mevzuat Bilgi Sistemi'ndeki (mevzuat.gov.tr) "
                f"güncel metin {turkish_date(_date.today())} tarihinde okundu ve bu numarada bir madde yok. Madde numarasını kontrol "
                "edip yeniden sorabilir ya da konuyu madde numarası vermeden anlatabilirsiniz.")
    return (f"{law_no} sayılı Kanunun {article_no}. maddesini doğrulanmış mevzuat kaynaklarımızda bulamadım. Madde numarası "
            "yanlış yazılmış olabilir ya da bu madde henüz kaynaklarımıza eklenmemiş olabilir; numarayı kontrol edip yeniden "
            "sorabilir ya da konuyu madde numarası vermeden anlatabilirsiniz.")


def _with_decisions(selected: list[RAGContext], pool: Sequence[RAGContext], *, question: str = '') -> list[RAGContext]:
    """Seçilen kaynaklara, havuzdaki en alakalı karar parçalarını ekler (en çok 3 karar toplam): "kiracı kirayı ödemezse" gibi
    sorularda seçici yalnız kanun maddesini bırakıyor ve cevap yargı uygulamasından hiç söz etmiyordu (ölçüldü: 2026-10-25)."""
    from api.ai.decision_attribution import decision_selection_key, decision_matches_question
    selected = [c for c in selected if decision_matches_question(question, c)]
    have = sum(1 for context in selected if context.source_type == "court_decision")
    known = {context.chunk_id for context in selected}
    sources = {context.source_id for context in selected if context.source_type == 'court_decision'}
    extra = [context for context in pool if context.source_type == "court_decision"
             and context.verification == 'official' and context.chunk_id not in known
             and decision_matches_question(question, context)]
    if question:
        extra.sort(key=lambda c: decision_selection_key(c, question))
    added = []
    for context in extra:
        if len(added) >= max(0, _FREE_ANSWER_EXTRA_DECISIONS - have):
            break
        if context.source_id in sources:
            continue
        added.append(context)
        sources.add(context.source_id)
    return [*selected, *added]


def _already_verified(answer: "VerifiedAnswer"):
    """`synthesize_answer` yerine geçer: cevap zaten cümle cümle kanıtlandı, yeniden sentez yapılmaz."""
    def synthesize(*_args, **_kwargs):
        return answer
    return synthesize


def auxiliary_provider(provider: AIProvider, profile: GenerationProfile) -> AIProvider:
    deepseek_cloud = isinstance(provider, FallbackProvider) and isinstance(provider.primary, DeepSeekCloudProvider)
    return AuxiliaryProvider(provider) if profile == "deep_research" or deepseek_cloud else provider


def holds_private_documents(contexts: list[RAGContext]) -> bool:
    return any(context.verification == "user_document" or context.source_type == "document" for context in contexts)
_PROGRESS_HEARTBEAT_SECONDS = 8.0
# Canlı portal doğrulaması LLM üretimiyle paralel çalışır. Önbellek isabetinde gizleyecek bir
# LLM süresi olmadığından yalnız kısa beklenir; LLM sonrasında ise doğrulamanın kendi bütçesi
# (`live_verify`) zaten sınırlı olduğundan bu değer yalnız emniyet payıdır.
_CACHE_HIT_VERIFY_WAIT_SECONDS = 2.0
_VERIFY_GRACE_SECONDS = 5.0
_PRE_GENERATION_VERIFY_WAIT_SECONDS = 15.0


@dataclass(slots=True)
class PipelineTimings:
    retrieval_ms: float = 0.0
    embedding_ms: float = 0.0
    prompt_build_ms: float = 0.0
    llm_ms: float = 0.0
    verification_ms: float = 0.0
    persist_ms: float = 0.0
    total_ms: float = 0.0
    from_cache: bool = False
    prompt_eval_count: int | None = None
    eval_count: int | None = None
    done_reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def as_citation(position: int, context: RAGContext) -> AICitation:
    return AICitation(
        marker=f"K{position}",
        source_id=context.source_id,
        chunk_id=context.chunk_id,
        source_type=context.source_type,
        title=context.title,
        reference=context.reference_line,
        source_url=context.source_url,
        court_name=context.court_name,
        chamber=context.chamber,
        docket_no=context.docket_no,
        decision_no=context.decision_no,
        decision_date=context.decision_date,
        law_name=context.law_name,
        law_no=context.law_no,
        article_no=context.article_no,
        page_number=context.page_number,
        version_date=context.version_date,
        effective_from=context.effective_from,
        effective_to=context.effective_to,
        source_version=context.source_version,
        revision=context.revision,
        excerpt=context.content[:500],
        rank=context.rank,
        verification=context.verification,
    )


CONSULTED_SOURCE_LIMIT = 8


def consulted_sources(
    answer: VerifiedAnswer, contexts: Sequence[RAGContext], question: str = ""
) -> list[AICitation]:
    """Cevaba girmeyen ama incelenen doğrulanmış kaynaklar: kaynak başına bir pasaj, I1, I2, ...

    Yalnız `usable_as_evidence` olanlar listelenir (resmî kaynak ya da kullanıcının kendi belgesi);
    doğrulanmamış üçüncü taraf kayıtlar buraya hiçbir koşulda girmez.
    """
    if not answer.grounded or not answer.contexts:
        # Cevap kaynaklardan çıkarılamadıysa aranan kaynaklar büyük olasılıkla soruyla ilgisizdir;
        # onları "incelendi" diye göstermek yanıltıcı olur.
        return []
    cited_chunks = {context.chunk_id for context in answer.contexts}
    seen_sources = {context.source_id for context in answer.contexts}
    # Sözcük eşleşmesi alakasız kararları da getirir; havuzda az kararda geçen soru kelimelerine göre
    # süzülür (bkz. consulted_relevance). Süzgeç yalnız gösterimi etkiler, cevabı değil.
    keep = relevant_chunk_ids(question, contexts) if question else None
    listed: list[AICitation] = []
    for context in contexts:
        if context.chunk_id in cited_chunks or context.source_id in seen_sources:
            continue
        if keep is not None and context.chunk_id not in keep:
            continue
        if not usable_as_evidence(context):
            continue
        seen_sources.add(context.source_id)
        position = len(listed) + 1
        listed.append(as_citation(position, context).model_copy(update={"marker": f"I{position}"}))
        if len(listed) >= CONSULTED_SOURCE_LIMIT:
            break
    return listed


def _queue_cited_third_party(answer: VerifiedAnswer) -> None:
    """Atıf yapılan doğrulanmamış kaynakları öncelikli doğrulama sırasına alır."""
    pending = [
        context.source_id
        for context in answer.contexts
        if context.verification == "third_party"
    ]
    verification_queue.enqueue_in_background(pending)


def _response_from_verified(
    request: AIAnswerRequest,
    answer: VerifiedAnswer,
    *,
    provider: AIProvider,
    conversation_id: UUID | None,
    message_id: UUID | None,
    from_cache: bool,
    timings: PipelineTimings | None = None,
    consulted: Sequence[RAGContext] = (),
) -> AIAnswerResponse:
    if any(not usable_as_evidence(context) for context in answer.contexts):
        raise HTTPException(503, "Kaynak doğrulaması tamamlanamadı; doğrulanmamış atıflar gösterilmiyor.")
    if not from_cache:
        _queue_cited_third_party(answer)
    coverage_info = {} if timings is None else (
        timings.extra.get("free_answer") or timings.extra.get("synthesis") or {})
    coverage_complete = None
    if coverage_info:
        if (coverage_info.get("partial_answer") or coverage_info.get("uncovered_parts")
                or coverage_info.get("coverage_preserved") is False):
            coverage_complete = False
        elif coverage_info.get("coverage_preserved") is True:
            coverage_complete = True
    return AIAnswerResponse(
        question=request.question,
        as_of=request.as_of,
        answer=answer.text,
        provider=provider.name,
        model=provider.model,
        citations=[
            as_citation(position, context)
            for position, context in enumerate(answer.contexts, start=1)
        ],
        consulted_sources=consulted_sources(answer, consulted, request.question),
        grounded=answer.grounded,
        answer_kind=answer.answer_kind,
        coverage_complete=coverage_complete,
        unverified_markers=list(answer.unverified_markers),
        conversation_id=conversation_id,
        message_id=message_id,
        from_cache=from_cache,
        prompt_eval_count=None if timings is None else timings.prompt_eval_count,
        eval_count=None if timings is None else timings.eval_count,
        done_reason=None if timings is None else timings.done_reason,
        search_summary=None if timings is None else timings.extra.get('search_summary'),
        interpreted_question=None if timings is None else timings.extra.get('interpreted_question'),
        summary=list(answer.summary),
        verification_note=answer.verification_note,
        document_scope=(
            None if timings is None else (timings.extra.get('retrieval') or {}).get('document_scope')
        ),
    )


def _with_verification_note(request: AIAnswerRequest, answer: VerifiedAnswer) -> VerifiedAnswer:
    """Attach the code-built currency note (when the question asks about it and legislation is cited); a cached note is rebuilt."""
    from dataclasses import replace as _replace
    from datetime import date as _date

    from api.ai import currency_note
    legislation = [c.source_id for c in answer.contexts if c.source_type == "legislation"]
    if (not answer.grounded or not legislation
            or (request.as_of is None and not (currency_note.asks_currency(request.question)
                                               or currency_note.asks_identity(request.question)))):
        return _replace(answer, verification_note=None)
    today = _date.today()
    try:
        records = currency_note.fetch_verification_records(legislation)
    except psycopg.Error:
        logger.warning("Mevzuat doğrulama tarihleri okunamadı")
        records = {}
    live: dict = {}
    if _live_recheck_allowed(request, answer):
        # The user asked about the text in force: articles not compared with the official text today are compared now. Only the
        # law number leaves the machine (approved public adapter); private scopes and historical questions never reach here.
        stale = [source for source in legislation
                 if not _verified_on(records.get(str(source), {}).get("last_verified_at"), today)]
        if stale:
            try:
                live = currency_note.recheck_official(stale)
            except Exception:  # noqa: BLE001 - a failed check is reported as "not reached", never as verified
                logger.warning("Resmî metinle yeniden karşılaştırma yapılamadı")
                live = {str(source): currency_note.UNREACHABLE for source in stale}
    identities: dict = {}
    if currency_note.asks_identity(request.question) and _live_recheck_allowed(request, answer):
        # The law's own header (acceptance date, Gazette date/number) comes from the official text, never from the model.
        identities = currency_note.fetch_law_identities(
            c.law_no for c in answer.contexts if c.source_type == "legislation")
    note = currency_note.verification_note(request.question, request.as_of, answer.contexts, records, today, live, identities)
    if identities and currency_note.identity_sentence(identities):
        trimmed = currency_note.drop_cannot_reach_sentences(answer.text)
        if trimmed.strip():
            answer = _replace(answer, text=trimmed)
    return _replace(answer, verification_note=note)


def _verified_on(value, day) -> bool:
    from datetime import datetime as _datetime
    if isinstance(value, _datetime):
        value = value.astimezone().date()
    return value == day


def _live_recheck_allowed(request: AIAnswerRequest, answer: VerifiedAnswer) -> bool:
    settings = get_settings()
    return (bool(getattr(settings, "official_web_research_enabled", False)) and cloud_allowed(request)
            and request.as_of is None and not holds_private_documents(list(answer.contexts))
            and os.getenv("NHR_OFFLINE_AUDIT") != "1")


def _payload_from_response(response: AIAnswerResponse) -> dict[str, Any]:
    return response.model_dump(
        mode="json",
        exclude={
            "conversation_id",
            "message_id",
            "from_cache",
            "prompt_eval_count",
            "eval_count",
            "done_reason",
            "document_scope",  # her istekte yeniden hesaplanır; önbellekte bayatlar
            "interpreted_question",
        },
    )


async def _finish_without_evidence(
    request: AIAnswerRequest, user_id: UUID | None, *, text: str,
    kind: AnswerKind, timings: PipelineTimings, started: float, emit: StageCallback,
    audit: AuditContext | None = None,
    model_name: str = "conversation-router-v1",
    generated_provider: AIProvider | None = None,
) -> tuple[AIAnswerResponse, PipelineTimings]:
    """Conversation/status is not a legal finding and must never be marked grounded."""
    answer = VerifiedAnswer(text=text, contexts=(), unverified_markers=(), answer_kind=kind)
    provider = generated_provider or _ServerReplyProvider(model=model_name)
    conversation_id = message_id = None
    persist_started = monotonic()
    if user_id is not None:
        conversation_id, message_id = await asyncio.to_thread(
            persist_answer, request, answer, user_id=user_id, model_name=provider.model,
            audit=audit, document_scope=(timings.extra.get("retrieval") or {}).get("document_scope"),
        )
    timings.persist_ms = (monotonic() - persist_started) * 1000
    response = _response_from_verified(
        request, answer, provider=provider, conversation_id=conversation_id,
        message_id=message_id, from_cache=False, timings=timings,
    )
    timings.total_ms = (monotonic() - started) * 1000
    await emit("done", result=response.model_dump(mode="json"))
    return response, timings


async def _general_definition_fallback(request, user_id, *, provider, local_provider,
                                       generation_profile, timings, started, emit, audit):
    from api.ai.general_information import eligible_definition, generate_definition
    if (generation_profile != "default" or not cloud_allowed(request)
            or provider is local_provider or not eligible_definition(request.question)):
        return None
    await emit("generating")
    tick = monotonic()
    async with _generation_slot(provider, local_provider):
        text = await asyncio.to_thread(generate_definition, provider, request.question)
    timings.llm_ms += (monotonic() - tick) * 1000
    if text is None:
        return None
    timings.extra["answer_mode"] = "general_information"
    return await _finish_without_evidence(
        request, user_id, text=text, kind="general_information", timings=timings,
        started=started, emit=emit, audit=audit, generated_provider=provider,
    )


async def _embed_question(question: str) -> list[float] | None:
    settings = get_settings()
    try:
        provider = create_embedding_provider(
            provider_name=settings.embedding_provider,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            ollama_base_url=settings.ollama_base_url,
            ollama_timeout_seconds=min(8.0, settings.ollama_timeout_seconds),
        )
        from api.ai.relevance import semantic_search_text
        return await asyncio.to_thread(provider.embed_query, semantic_search_text(question))
    except EmbeddingProviderError as exc:
        logger.warning("Soru embedding'i üretilemedi (%s); lexical RAG kullanılacak", exc)
        return None


async def _embed_legislation_question(question: str) -> list[float] | None:
    """Second query vector for the legislation-only search (bge-m3, migration 061); ``None`` when off or failing."""
    settings = get_settings()
    model = getattr(settings, "legislation_embedding_model", "")
    if not model:
        return None
    try:
        provider = create_embedding_provider(
            provider_name="ollama", model=model, dimensions=1024, ollama_base_url=settings.ollama_base_url,
            ollama_timeout_seconds=min(8.0, settings.ollama_timeout_seconds),
        )
        from api.ai.relevance import semantic_search_text
        return await asyncio.to_thread(provider.embed_query, semantic_search_text(question))
    except EmbeddingProviderError as exc:
        logger.warning("Mevzuat sorgu vektörü üretilemedi (%s); yalnız ortak anlam araması kullanılacak", exc)
        return None


def _consume_task_result(task: "asyncio.Future[Any]") -> None:
    """Beklenmeyen bir görevin istisnası "never retrieved" uyarısına dönmesin."""
    if not task.cancelled() and task.exception() is not None:
        logger.warning("Canlı doğrulama görevi başarısız", exc_info=task.exception())


def _start_live_verification(
    contexts: list[RAGContext],
    *, target_sources: int = 6, diagnostics: dict | None = None,
) -> "asyncio.Future[list[RAGContext]] | None":
    """Doğrulanmamış kaynak varsa portal doğrulamasını arka planda başlatır."""
    if not any(context.verification == "third_party" for context in contexts):
        return None
    task = asyncio.ensure_future(asyncio.to_thread(
        verify_third_party_contexts, contexts, max_docs=12,
        target_sources=target_sources, diagnostics=diagnostics,
    ))
    task.add_done_callback(_consume_task_result)
    return task


async def _resolve_verification(
    task: "asyncio.Future[list[RAGContext]] | None",
    contexts: list[RAGContext],
    *,
    wait: float,
    timings: PipelineTimings,
) -> list[RAGContext]:
    """Paralel doğrulamanın sonucunu alır.

    Bitmediyse ya da hata verdiyse rozetler olduğu gibi kalır: kaynak "doğrulanmadı" görünmeye
    devam eder, yani yavaş bir portal cevabı yanlış biçimde "resmî" gösteremez. Görev iptal
    edilmez (kalıcı terfi kendi başına tamamlanır); yalnız bu cevap onu beklemez.
    """
    if task is None:
        return contexts
    started = monotonic()
    try:
        result = await asyncio.wait_for(asyncio.shield(task), timeout=wait)
        timings.extra["live_verify"] = "done"
        return result
    except asyncio.TimeoutError:
        logger.info("Canlı doğrulama %.1f sn içinde bitmedi; kaynaklar doğrulanmadı kalıyor", wait)
        timings.extra["live_verify"] = "timeout"
        return contexts
    except Exception:
        logger.warning("Canlı doğrulama sonucu alınamadı", exc_info=True)
        timings.extra["live_verify"] = "error"
        return contexts
    finally:
        timings.extra["live_verify_wait_ms"] = round((monotonic() - started) * 1000, 1)


def _source_preview(contexts: list[RAGContext]) -> list[dict[str, Any]]:
    """Cevap hazır olmadan gösterilecek kaynak özeti. İddia içermez: yalnız künye ve durum."""
    return [
        {
            "marker": f"K{position}",
            "source_id": str(context.source_id),
            "source_type": context.source_type,
            "reference": context.reference_line,
            "verification": context.verification,
        }
        for position, context in enumerate(contexts, start=1)
    ]


async def _load_history(
    request: AIAnswerRequest, user_id: UUID | None
) -> tuple[tuple[HistoryTurn, ...], tuple[str, ...]]:
    """Devam eden sohbetin önceki turlarını ve son sorularını RLS altında okur."""
    if request.conversation_id is None:
        return (), ()
    if user_id is None:
        raise HTTPException(
            status_code=401, detail="Sohbeti sürdürmek için oturum açmalısınız"
        )

    def load():
        with authenticated_database_connection(str(user_id)) as connection:
            return load_conversation_context(connection, request.conversation_id)

    try:
        context = await asyncio.to_thread(load)
    except ConversationNotFound as exc:
        raise HTTPException(status_code=404, detail="Sohbet bulunamadı") from exc
    except psycopg.Error as exc:
        logger.exception("Sohbet geçmişi okunamadı")
        raise HTTPException(
            status_code=503, detail="Sohbet geçmişi okunamadı"
        ) from exc
    if request.project_id != context.project_id:
        raise HTTPException(
            status_code=409, detail="Bu sohbet farklı bir projeye ait"
        )
    if (request.case_id, request.office_project_id, set(request.selected_document_ids)) != (
        context.case_id, context.office_project_id, set(context.selected_document_ids),
    ):
        raise HTTPException(409, "Bu sohbet farklı bir dava, proje veya belge seçimine ait. Kendi kapsamıyla açın veya yeni sohbet başlatın.")
    questions = getattr(context, "questions", ()) or tuple(turn.question for turn in context.turns)
    return context.turns, questions


def persist_answer(
    request: AIAnswerRequest,
    answer: VerifiedAnswer,
    *,
    user_id: UUID,
    model_name: str,
    audit: AuditContext | None = None,
    from_cache: bool = False,
    document_scope: dict | None = None,
) -> tuple[UUID | None, UUID | None]:
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            conversation_id, message_id = record_exchange(
                connection,
                user_id=user_id,
                conversation_id=request.conversation_id,
                project_id=request.project_id,
                question=request.question,
                answer=answer,
                model_name=model_name,
                as_of=request.as_of,
                case_id=request.case_id,
                office_project_id=request.office_project_id,
                selected_document_ids=request.selected_document_ids,
                document_scope=document_scope,
            )
            # Soru ve cevap metni denetim günlüğüne yazılmaz; yalnız olayın özeti.
            record_event(
                connection,
                action=AI_ANSWER,
                actor_user_id=user_id,
                context=audit,
                entity_type="conversation",
                entity_id=conversation_id,
                project_id=request.project_id,
                metadata={
                    "message_id": str(message_id),
                    "model": model_name,
                    "grounded": answer.grounded,
                    "answer_kind": answer.answer_kind,
                    "from_cache": from_cache,
                    "citation_count": len(answer.contexts),
                    "third_party_citations": sum(
                        1 for context in answer.contexts if context.verification == "third_party"
                    ),
                    "document_citations": sum(
                        1 for context in answer.contexts if context.source_type == "document"
                    ),
                    "case_id": str(request.case_id) if request.case_id else None,
                    "office_project_id": str(request.office_project_id) if request.office_project_id else None,
                    "selected_document_count": len(request.selected_document_ids),
                },
                strict=False,
            )
            return conversation_id, message_id
    except ConversationScopeMismatch as exc:
        raise HTTPException(409, str(exc)) from exc
    except InsufficientPrivilege as exc:
        raise HTTPException(
            status_code=403,
            detail="Bu konuşmaya veya projeye yazma yetkiniz yok",
        ) from exc
    except psycopg.Error:
        logger.exception("Sohbet geçmişi kaydedilemedi")
        return None, None


# Bir soruda UYAP dosya bilgisi belgesinden en çok bu kadar bölüm öne alınır; evraklar da aday kalsın.
UYAP_RECORD_SECTION_LIMIT = 3


def _interleave(first: list[RAGContext], second: list[RAGContext]) -> list[RAGContext]:
    """İki listeyi, kendi sıralarını bozmadan birer birer birleştirir (ilk öğe `first` listesinden)."""
    merged: list[RAGContext] = []
    for index in range(max(len(first), len(second))):
        merged.extend(items[index] for items in (first, second) if index < len(items))
    return merged


_CASE_STATUTE_ARTICLES = 3
_CASE_STATUTE_CHUNKS = 3


def _case_statute_contexts(connection, question: str, named_documents: list[RAGContext]) -> list[RAGContext]:
    """Hukuki soruya, konusuna uyan resmî doğrulanmış kanun maddelerini ekler (genel sohbet ve dava sohbeti).

    "İhtarnamede verilen süre kanuna uygun mu?" sorusunun sözcükleri hangi kanunun söz konusu olduğunu söylemez; sözcük
    araması ilgisiz kararlar getiriyordu (ölçüldü: 2026-10-06). Konu önce sorudan, soruda yoksa sorunun adıyla gösterdiği
    belgenin metninden çıkarılır (bütün dosyadan değil: başka belgelerdeki sözcükler konuyu saptırır). Madde numaraları
    sabit tablodan gelir (`api.statute_hints`), metin korpustan okunur ve beklenen konuyu taşımıyorsa eklenmez; burada
    hiçbir metin üretilmez. Eklenen madde yalnız ADAYDIR: cümle alaka süzgecinden ve kaynak-destek denetiminden geçer.
    """
    from api import statute_hints
    from api.ai.retrieval import STATUTE_RETRIEVAL_SQL, _execute_retrieval

    hints = statute_hints.suggest(question)
    if not hints and named_documents:
        hints = statute_hints.suggest(question + " " + " ".join(c.content[:1500] for c in named_documents[:2]))
    found: list[RAGContext] = []
    # An open rights overview spans several independent subjects. The ordinary
    # two-provision shortcut silently removed wages/leave/reinstatement. Keep
    # the larger, still bounded plan only for that explicitly broad request.
    broad_overview = bool(statute_hints.employment_rights_groups(question))
    article_limit = statute_hints.MAX_HINTS if broad_overview else _CASE_STATUTE_ARTICLES
    for hint in hints[:article_limit]:
        try:
            with connection.transaction():  # zaman aşımı yalnız bu ek sorguyu düşürür, asıl aramayı değil
                rows = _execute_retrieval(
                    connection, STATUTE_RETRIEVAL_SQL,
                    {"law_no": hint.law_no, "article_no": hint.article_no, "as_of": None, "top_k": _CASE_STATUTE_CHUNKS},
                    timeout="5s",
                )
        except psycopg.Error:
            logger.warning("Dava sorusu için madde ipucu okunamadı: %s m.%s", hint.law_no, hint.article_no)
            continue
        rows = [row for row in rows if row.source_type == "legislation" and row.verification == "official"]
        if rows and statute_hints.text_matches(hint, " ".join(row.content for row in rows)):
            if broad_overview and hint.anchor:
                # The main sentence of m.32 is in chunk 2, not its definition
                # chunk. Source diversity selection must retain the actual rule.
                from api.ai.search_plan import normalize
                rows.sort(key=lambda row: normalize(hint.anchor) not in normalize(row.content))
            found.extend(rows)
    return found


def _planned_statutes(request: AIAnswerRequest, question: str) -> list[RAGContext]:
    """Cheap exact verified lookup before repeating broad discovery per facet."""
    if (not cloud_allowed(request) or request.as_of is not None
            or case_law_requested(request.question) or case_law_requested(question)):
        return []
    try:
        with database_connection() as connection:
            return _case_statute_contexts(connection, question, [])
    except psycopg.Error:
        return []


def _seed_search_only(request: AIAnswerRequest, *, natural_mode: bool, generation_profile: str, cloud_provider: bool,
                      force_full: bool, has_seed: bool) -> bool:
    """True when the whole-question search may skip its vector lanes because `_free_answer` runs every part's own vector search."""
    return bool(natural_mode and generation_profile == 'default' and cloud_provider and cloud_allowed(request)
                and request.as_of is None and not force_full and not has_seed)


def _initial_public_statutes(request: AIAnswerRequest, question: str, diagnostics: dict) -> list[RAGContext]:
    """Provisional seeds, NOT a substitute for the per-part research/checker.

    The caller still plans every facet in _free_answer; a facet without usable
    local evidence takes broad discovery. Do not use for private, historical,
    explicit case-law or simple single-provision requests.
    """
    from api.ai.free_answer import simple_search_plan, _usable
    from api.ai.relevance import context_relevant
    from api.ai.provision_context import restore_provisions
    from api import statute_hints
    if (not cloud_allowed(request) or request.as_of is not None
            or case_law_requested(question) or re.search(r'\b(?:19|20)\d{2}\b', question)
            or simple_search_plan(question) is not None
            or len(statute_hints.suggest(question)) < 2):
        return []
    tick = monotonic()
    try:
        rows = _planned_statutes(request, question)
        if rows:
            with database_connection() as connection:
                rows = restore_provisions(rows, connection)
        rows = [c for c in verified_contexts(rows)
                if _usable(c, 36000) is not None and context_relevant(question, c)]
    except psycopg.Error:
        rows = []
    finally:
        diagnostics['provisional_seed_ms'] = round((monotonic() - tick) * 1000, 1)
    if rows:
        diagnostics.update(strategy='provisional_local_statutes', research_deferred=True,
                           partial=False, exhaustive=False)
    return rows


def _retrieve(
    request: AIAnswerRequest,
    *,
    user_id: UUID | None,
    query_embedding: list[float] | None,
    top_k: int,
    embedding_model: str,
    question: str | None = None,
    diagnostics: dict | None = None,
    statutes_on_timeout: bool = False,
    legislation_embedding: list[float] | None = None,
) -> list[RAGContext]:
    search_question = question or request.question
    selected = bool(request.selected_document_ids)
    case_id = office_project_case(user_id, request.office_project_id) if request.office_project_id else request.case_id
    if request.project_id is not None or case_id is not None or selected or request.office_project_id:
        if user_id is None:
            raise HTTPException(
                status_code=401,
                detail="Proje belgeleriyle çalışmak için oturum açmalısınız",
            )
        if selected:
            coverage = selected_document_coverage(user_id, request.selected_document_ids,
                None if request.office_project_id else case_id, **({'office_project_id':request.office_project_id} if request.office_project_id else {}))
            if diagnostics is not None:
                diagnostics["document_scope"] = coverage
        if request.office_project_id and not selected:
            if case_id is not None:
                sweep_unindexed(user_id, case_id=case_id)
            if diagnostics is not None:
                diagnostics['document_scope'] = project_document_coverage(user_id, request.office_project_id)
        elif case_id is not None and not selected:
            # Hangi yoldan geldiğinden bağımsız, henüz indekslenmemiş dava belgelerini bütçe içinde hazırlar.
            sweep_unindexed(user_id, case_id=case_id)
            if diagnostics is not None:
                diagnostics["document_scope"] = case_document_coverage(user_id, case_id)
        file_only = case_id is not None and is_case_file_question(search_question)
        with authenticated_database_connection(str(user_id)) as connection:
            document_contexts = retrieve_document_contexts(
                connection,
                question=search_question,
                project_id=None if request.project_id is None else str(request.project_id),
                case_id=None if case_id is None or request.office_project_id else str(case_id),
                **({'office_project_id':str(request.office_project_id)} if request.office_project_id else {}),
                top_k=top_k,
                query_embedding=query_embedding,
                embedding_model=embedding_model,
                **({"document_ids": [str(value) for value in request.selected_document_ids]} if selected else {}),
            )
            record = []
            if case_id is not None and not selected:
                # UYAP'tan çekilen dosya bilgileri (taraflar, dosya hesabı, sorgular, safahat) evrak değildir ama dosyanın
                # parçasıdır: soruyla ilgili bölümleri kullanıcının belgeleri arasına, en başa eklenir. "Borçlu kim?",
                # "Bakiye borç ne kadar?" gibi soruların cevabı evrak metninde değil bu kayıtlardadır.
                record = record_contexts(connection, user_id=user_id, case_id=case_id, question=search_question)
                if record:
                    # Belge araması sırayı Decimal olarak döndürür.
                    top = max((float(context.rank) for context in document_contexts), default=0.0)
                    record = [replace(context, rank=top + 1.0) for context in record[:UYAP_RECORD_SECTION_LIMIT]]
                    document_contexts = [*record, *document_contexts]
                if diagnostics is not None:
                    diagnostics["uyap_record_sections"] = len(record)
            legal_assessment = asks_for_legal_assessment(search_question) or (selected and case_law_requested(search_question))
            if (selected or request.office_project_id) and not legal_assessment:
                # Seçili belgenin olguları başka davaların kararlarındaki olgularla ikame edilemez.
                file_only = True
            if case_id is not None and record and not legal_assessment:
                # Sorunun karşılığı dosyanın UYAP kaydında var ve hukuki değerlendirme istenmiyor: başka davaların kararlarına
                # bakılmaz. "Takip kesinleşti mi?" sorusuna, dosyadaki "Kesinleşme bilgisi girildi: …" kaydı dururken ilgisiz
                # bir kararın genel cümleleriyle cevap veriliyordu (ölçüldü: 2026-10-10).
                file_only = True
            named: list[RAGContext] = []
            if missing_document_references(search_question, document_contexts):
                # Retrieval is bounded: do not claim the document is absent from the whole account.
                # Fail closed rather than substituting an unrelated document or public court decision.
                raise HTTPException(422, "Adını belirttiğiniz belge bu aramada bulunamadı. Belgeyi seçip yeniden sorun; metninin okunmuş olduğundan emin olun.")
            if case_id is not None or selected or request.office_project_id:
                named = documents_named_in(search_question, document_contexts)
                if named:
                    # Soru bir belgeyi adıyla gösteriyor ("ihtarnamede…"): yalnız o belgenin parçaları aranır. Hukuki
                    # değerlendirme de istenmiyorsa başka hiçbir kaynağa bakılmaz.
                    document_contexts = named
                    file_only = file_only or not legal_assessment
            if (
                case_id is not None
                and not file_only
                and not legal_assessment
                and documents_answer(search_question, document_contexts)
            ):
                # Dosya sözcüğü taşımayan olgu sorusu ("Depozito tutarı nedir?"): cevabı davanın belgelerinde yazıyorsa
                # yalnız o belgelerden cevaplanır. Karışık aramada model, kullanıcının sözleşmesi yerine başka bir davanın
                # kararındaki tutarı cevap diye seçebiliyordu (ölçüldü: 2026-10-06).
                file_only = True
            if diagnostics is not None:
                diagnostics["case_file_only"] = file_only
                if isinstance(diagnostics.get("document_scope"), dict):
                    diagnostics["document_scope"]["file_only"] = file_only
            if file_only:
                # "Davalının adresi nedir?" gibi kendi dosyasına dair soru: başka davaların kararlarından
                # alıntı yapılmaz; belgelerde yoksa "yeterli bilgi yok" denir.
                return document_contexts[:top_k]
            legal_contexts = retrieve_contexts(
                connection,
                question=search_question,
                top_k=top_k,
                query_embedding=query_embedding,
                embedding_model=embedding_model,
                as_of=request.as_of,
                diagnostics=diagnostics,
                legislation_embedding=legislation_embedding,
            )
            # Dava belgeleri ve hukuk kaynaklarının puanları aynı ölçekte değildir (ts_rank / RRF): iki liste kendi içinde
            # sıralanır ve sırayla birer birer alınır; ilk sırada kullanıcının kendi belgesi vardır. Belgeler önce, hukuk
            # kaynakları sonra dizildiğinde çok belgeli davada modele giden ilk kaynakların tamamı belge oluyor, hukuki
            # değerlendirme sorusu hiçbir hukuk kaynağına ulaşamıyordu (ölçüldü: 2026-10-06).
            if named and not case_law_requested(search_question):
                # Kullanıcının kendi belgesi hakkındaki hukuki soru ("ihtarnamede verilen süre kanuna uygun mu?"): başka
                # davaların kararları kullanılmaz. O kararlardaki olay cümleleri ("ihtarnamede 30 günlük süre verilmiş
                # olması nedeniyle … hukuki sonuç doğurmaz") kullanıcının belgesi hakkında söylenmiş gibi okunuyor; ölçülen
                # örnekte cümle ürün kirasına (TBK 362) ilişkindi, soru konut kirasıydı (2026-10-06). Kuralı kanun maddesi,
                # olguyu belge söyler. İçtihat isteyen soru ("Yargıtay", "emsal"…) bu süzgece girmez.
                legal_contexts = [context for context in legal_contexts if context.source_type == "legislation"]
            own = sorted(document_contexts, key=lambda context: context.rank, reverse=True)
            statutes = (
                _case_statute_contexts(connection, search_question, named) if case_id is not None or selected else []
            )
            known = {context.chunk_id for context in statutes}
            others = [
                *statutes,
                *(c for c in sorted(legal_contexts, key=lambda context: context.rank, reverse=True) if c.chunk_id not in known),
            ]
            return _interleave(own, others)[:top_k]
    with database_connection() as connection:
        timed_out: psycopg.errors.QueryCanceled | None = None
        try:
            contexts = retrieve_contexts(
                connection,
                question=search_question,
                top_k=top_k,
                query_embedding=query_embedding,
                embedding_model=embedding_model,
                as_of=request.as_of,
                diagnostics=diagnostics,
                legislation_embedding=legislation_embedding,
                parallel_public_vectors=True,
            )
        except psycopg.errors.QueryCanceled as exc:
            # Karar araması yoğun diskte ikinci denemede de zaman aşımına uğrayabilir (ölçüldü: 2026-10-08, art arda dört
            # deneme). Konunun resmî maddesi ayrı ve hızlı okunur; o varsa kullanıcı "kaynaklar aranamadı" hatası yerine
            # kanun maddesine dayanan cevabı alır ve aramanın eksik kaldığı açıkça bildirilir (partial).
            if not statutes_on_timeout or request.as_of is not None:
                raise
            timed_out, contexts = exc, []
        if request.as_of is None:
            # Genel soruda da konuya uyan resmî madde adayların başına eklenir. Sözcük araması "işe iade davası açma
            # süresi" sorusuna yalnız 2015-2016 kararlarını getiriyordu; o kararlar arabuluculuk zorunluluğundan önceki
            # usulü anlatır, güncel kural İş Kanunu m. 20'dedir (ölçüldü: 2026-10-06). Tarihli sorularda (as_of) eklenmez:
            # madde yalnız güncel hâliyle okunur.
            statutes = _case_statute_contexts(connection, search_question, [])
            if statutes:
                known = {context.chunk_id for context in statutes}
                contexts = [*statutes, *(context for context in contexts if context.chunk_id not in known)]
                if diagnostics is not None:
                    diagnostics["topic_statutes"] = len({context.source_id for context in statutes})
        if timed_out is not None:
            if not contexts:
                raise timed_out
            if diagnostics is not None:
                diagnostics["partial"] = True
                diagnostics["decision_search"] = "timeout"
        return contexts


async def _retrieve_with_warm_retry(request: AIAnswerRequest, **kwargs: Any) -> list[RAGContext]:
    """Soğuk önbellekte tüm arama kolları zaman aşımına uğrayabilir (API/veritabanı yeni açıldığında
    ya da uzun boşlukta ilk soru; ölçüldü: 2026-10-03). İlk deneme okuduğu sayfaları önbelleğe
    bıraktığından yeniden deneme çoğunlukla geçer; ikinci başarısızlık gerçek hata sayılır."""
    for attempt in (1, 2):
        try:
            # Son denemede karar araması yine düşerse konunun resmî maddesiyle yetinilir (bkz. _retrieve).
            return await asyncio.to_thread(_retrieve, request, statutes_on_timeout=attempt == 2, **kwargs)
        except psycopg.errors.QueryCanceled:
            if attempt == 2:
                raise
            logger.warning("Arama zaman aşımına uğradı (soğuk önbellek olabilir); bir kez yeniden deneniyor")
    raise AssertionError("unreachable")


async def execute_answer(
    request: AIAnswerRequest,
    user_id: UUID | None,
    *,
    on_stage: StageCallback | None = None,
    audit: AuditContext | None = None,
    _force_full_search: bool = False,
    generation_profile: GenerationProfile = "default",
) -> tuple[AIAnswerResponse, PipelineTimings]:
    # HTTP istek şemasında yoktur; yalnız güvenilen sunucu akışları seçebilir.
    if generation_profile not in {"default", "deep_research"}:
        raise ValueError("Bilinmeyen üretim profili")
    settings = get_settings()
    timings = PipelineTimings()
    started = monotonic()

    async def emit(stage: str, **extra: Any) -> None:
        if on_stage is None:
            return
        result = on_stage({"stage": stage, **extra})
        if asyncio.iscoroutine(result):
            await result

    # Strict server-owned social grammar, before source search/model warmup. A
    # mixed greeting + legal question never matches this route. Validate an
    # existing conversation's ownership and scope even for a one-word greeting.
    from api.ai.conversation_intent import conversation_reply, out_of_scope_reply
    from api.ai.arithmetic import arithmetic_reply
    social = conversation_reply(request.question)
    arithmetic = arithmetic_reply(request.question) if social is None else None
    off_topic = out_of_scope_reply(request.question) if cloud_allowed(request) else None
    social = social or arithmetic or off_topic
    if social is not None and generation_profile == "default":
        if not cloud_allowed(request) and user_id is None:
            raise HTTPException(401, "Çalışma alanı için oturum açmalısınız")
        await _load_history(request, user_id)
        return await _finish_without_evidence(
            request, user_id, text=social, kind="conversation", timings=timings,
            started=started, emit=emit, audit=audit,
            model_name=("decimal-arithmetic-v1" if arithmetic is not None else
                        "scope-router-v1" if off_topic is not None else "conversation-router-v1"),
        )
    await emit("searching")
    history_context = None
    if generation_profile == "default" and cloud_allowed(request):
        # Asking for the user's event facts is not a legal assertion and needs
        # neither corpus evidence nor a paid model. Always validate saved scope
        # and ownership first. Document questions stay on their reading route.
        history_context = await _load_history(request, user_id)
        from api.ai.arithmetic import rent_percentage_reply
        percentage = rent_percentage_reply(request.question, history_context[1])
        if percentage is not None:
            return await _finish_without_evidence(
                request, user_id, text=percentage, kind="conversation", timings=timings,
                started=started, emit=emit, audit=audit, model_name="declared-percentage-v1",
            )
        from api.ai.dialogue import missing_input_plan
        input_plan = missing_input_plan(request.question, (), history=history_context[0],
                                        prior_questions=history_context[1], allow_source_free=True)
        from api import statute_hints as _topic_hints
        # Kira artışında yasal sınır TÜFE oranına bağlıdır ve korpusta oran yok: orada önce sormak kasıtlıdır (testlerle kilitli).
        employment_inputs = {"gross_pay", "employment_dates", "termination_reason"}
        if (input_plan is not None and employment_inputs & set(input_plan.missing)
                and _topic_hints.suggest(request.question)):
            # Konusu bilinen soruda önce genel kural kaynaklarla anlatılır, eksik olgu sorusu cevabın sonuna eklenir
            # (kullanıcı 2026-10-25: "adam gibi cevap"; eskiden yalnız soru dönüyordu).
            timings.extra["followup_question"] = input_plan.question
            timings.extra["missing_inputs"] = list(input_plan.missing)
            input_plan = None
        if input_plan is not None:
            timings.extra["missing_inputs"] = list(input_plan.missing)
            return await _finish_without_evidence(
                request, user_id, text=input_plan.question, kind="clarification",
                timings=timings, started=started, emit=emit, audit=audit,
                model_name="dialogue-inputs-v1",
            )
    local_provider, provider = _answer_providers(settings, request, generation_profile)
    local_resources = provider is local_provider and getattr(provider, "name", "") != "bedrock"
    if local_resources:
        pause_embeddings("assistant")
    try:
        if local_resources and not settings.rag_query_embedding:
            await asyncio.to_thread(
                unload_ollama_model, settings.ollama_base_url, settings.embedding_model
            )
        return await _execute_answer_body(
            request,
            user_id,
            settings=settings,
            timings=timings,
            started=started,
            emit=emit,
            audit=audit,
            _force_full_search=_force_full_search,
            generation_profile=generation_profile,
            providers=(local_provider, provider),
            history_context=history_context,
        )
    finally:
        if local_resources:
            resume_embeddings()


def _answer_providers(settings, request, generation_profile):
    try:
        local = create_provider(
            provider_name=settings.ai_provider, model=settings.ai_model,
            ollama_base_url=settings.ollama_base_url,
            ollama_timeout_seconds=settings.ollama_timeout_seconds,
            ollama_max_output_tokens=settings.ollama_max_output_tokens,
            ollama_num_ctx=settings.ollama_num_ctx, ollama_keep_alive=settings.ollama_keep_alive,
        )
    except AIProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return local, answer_provider(settings, request, local, profile=generation_profile)


def _warm_cache_eligible(request: AIAnswerRequest, settings, provider: AIProvider, local_provider: AIProvider,
                         history, generation_profile: GenerationProfile) -> bool:
    """Only a plain, self-contained general question may use or feed the pre-computed answers: no case/project/document scope, no
    earlier turns, no historical date, the cloud route, and the natural-answer pipeline. Anything personal never qualifies."""
    return bool(
        getattr(settings, "warm_answer_cache_enabled", True) and getattr(settings, "rag_natural_answers", False)
        and getattr(settings, "free_answer_enabled", False) and generation_profile == "default"
        and cloud_allowed(request) and request.as_of is None and not history and request.conversation_id is None
        and provider is not local_provider and not (isinstance(provider, FallbackProvider) and provider.fell_back))


def _warm_cache_lookup(question: str) -> VerifiedAnswer | None:
    from api.ai import warm_cache
    try:
        with database_connection() as connection:
            return warm_cache.lookup(connection, question)
    except psycopg.Error:
        logger.warning("Önceden hazırlanmış cevap okunamadı; normal yoldan devam ediliyor")
        return None


async def _execute_answer_body(
    request: AIAnswerRequest,
    user_id: UUID | None,
    *,
    settings,
    timings: PipelineTimings,
    started: float,
    emit: StageCallback,
    audit: AuditContext | None = None,
    _force_full_search: bool = False,
    generation_profile: GenerationProfile = "default",
    providers: tuple[AIProvider, AIProvider] | None = None,
    history_context: tuple[tuple[HistoryTurn, ...], tuple[str, ...]] | None = None,
) -> tuple[AIAnswerResponse, PipelineTimings]:
    history, prior_questions = history_context if history_context is not None else await _load_history(request, user_id)
    from api.ai.query_vocabulary import standalone_definition
    if generation_profile == "default" and cloud_allowed(request) and standalone_definition(request.question):
        # Ownership/scope were checked above. This complete new question is not
        # a continuation of the previous event or off-topic turn. Do not pay to
        # rewrite it, import previous facts, or vary its cache key each repeat.
        history, prior_questions = (), ()
        timings.extra["history_context_strategy"] = "standalone_definition"
    natural_mode = getattr(settings, "rag_natural_answers", False)
    followup_question: str | None = timings.extra.get("followup_question")

    local_provider, provider = providers or _answer_providers(settings, request, generation_profile)

    from api.ai import warm_cache as _warm_cache
    # While the warm-up script is generating answers (it sets the collector) the stored ones must not answer for it.
    if _warm_cache.collector.get() is None and _warm_cache_eligible(request, settings, provider, local_provider, history,
                                                                    generation_profile):
        warm = await asyncio.to_thread(_warm_cache_lookup, request.question)
        if warm is not None:
            # A finished answer for this very question whose cited chunks are unchanged and still verified/current: no search, no
            # model call. It is saved to the user's conversation like any answer.
            timings.from_cache = True
            timings.extra["warm_cache"] = True
            warm = await asyncio.to_thread(_with_verification_note, request, warm)
            conversation_id: UUID | None = None
            message_id: UUID | None = None
            persist_started = monotonic()
            if user_id is not None:
                conversation_id, message_id = await asyncio.to_thread(
                    persist_answer, request, warm, user_id=user_id, model_name=provider.model, audit=audit, from_cache=True,
                    document_scope=None)
            timings.persist_ms = (monotonic() - persist_started) * 1000
            timings.total_ms = (monotonic() - started) * 1000
            response = _response_from_verified(
                request, warm, provider=provider, conversation_id=conversation_id, message_id=message_id, from_cache=True,
                timings=timings, consulted=list(warm.contexts))
            await emit("done", result=response.model_dump(mode="json"))
            return response, timings

    # Takip sorusu ("Peki bunun süresi?") önceki sorulara göre tek başına anlaşılır hâle getirilir; sonuç kodla
    # denetlenir (bkz. conversation_history.accept_rewrite) ve yalnız arama ile kanıt seçimini yönlendirir.
    interpreted: str | None = None
    from api.ai.dialogue import resume_question
    interpreted = resume_question(request.question, history, prior_questions)
    # Yeni ve tek başına anlaşılır sorularda (ör. kira artışından işe iade
    # konusuna geçiş) önceki sohbeti modele yeniden yazdırma: hem gereksiz
    # bulut çağrısını hem de yanlış konu taşıma riskini azaltır.
    if prior_questions and interpreted is None and needs_standalone_rewrite(request.question):
        rewrite_started = monotonic()
        async with _generation_slot(provider, local_provider):
            interpreted = await asyncio.to_thread(
                standalone_question, auxiliary_provider(provider, generation_profile),
                restore_turkish(request.question), prior_questions
            )
        timings.extra["question_rewrite_ms"] = round((monotonic() - rewrite_started) * 1000, 1)
        timings.extra["interpreted_question"] = interpreted
    # Türkçe karakter olmadan yazılan soru ("davaci kac yil") arama için geri getirilir; kullanıcının
    # yazdığı soru (`request.question`) olduğu gibi saklanır.
    search_question = restore_turkish(interpreted or retrieval_question(request.question, history))
    answer_question = interpreted or restore_turkish(request.question)
    from api.ai.dialogue import outcome_search_query
    event_reference_contexts = []
    research_aspects = ()
    research_evidence = None
    topic_query = outcome_search_query(request.question, history, prior_questions)
    if topic_query is not None and cloud_allowed(request):
        search_question = topic_query
        timings.extra["search_topic"] = "personal_employment_outcome"
        temporal = await asyncio.to_thread(
            lookup_event_basis, request.question, search_question,
            prior_questions=prior_questions, history=history, as_of=request.as_of,
        )
        if temporal is not None:
            timings.extra["event_basis"] = {"complete": temporal.complete,
                "unavailable": temporal.unavailable, "references": list(temporal.references),
                "as_of": temporal.event.applicable_on.isoformat()}
            if not temporal.complete:
                event_reference_contexts = await asyncio.to_thread(load_current_event_reference, temporal)
                if not event_reference_contexts:
                    from api.ai.event_context import compose_event_answer
                    return await _finish_without_evidence(
                        request,user_id,text=compose_event_answer("",temporal.event),kind="insufficient_sources",
                        timings=timings,started=started,emit=emit,audit=audit,model_name="event-scope-v1",
                    )
                timings.extra["event_reference_only"] = True
            # Use the explicit or independently parsed event date for discovery,
            # never mix current versions/future cases into this historical run.
            else:
                request = request.model_copy(update={"as_of": temporal.event.applicable_on})

    verify_task: asyncio.Future[list[RAGContext]] | None = None
    warmup_task: asyncio.Task[None] | None = None
    warmup = getattr(provider, "warmup", None)
    if callable(warmup):
        warmup_task = asyncio.create_task(asyncio.to_thread(warmup))

    try:
        fast_diagnostics: dict = {}
        # Ownership and the complete conversation scope were checked above.
        # A general, current-rule question does not become a private/historical
        # query merely because the user greeted us first. Keep the topic/date/
        # source-completeness gates inside try_fast_statute; scoped requests
        # retain their original conversation id and can never take this route.
        fast_conversation_id = request.conversation_id
        if natural_mode and generation_profile == "default" and cloud_allowed(request):
            fast_conversation_id = None
        fast_contexts = event_reference_contexts or ([] if _force_full_search or request.selected_document_ids else await asyncio.to_thread(
            try_fast_statute, question=search_question, as_of=request.as_of,
            project_id=request.project_id or request.case_id or request.office_project_id, conversation_id=fast_conversation_id,
            max_chunks=settings.rag_top_k, max_chars=settings.rag_context_chars,
            diagnostics=fast_diagnostics,
        ))
        if (not fast_contexts and not _force_full_search and natural_mode
                and generation_profile == 'default' and provider is not local_provider):
            # Do not pay the initial whole-corpus search just to rediscover
            # exact known provisions. These are seeds: _free_answer still
            # researches all facets and independently verifies the full answer.
            fast_contexts = await asyncio.to_thread(
                _initial_public_statutes, request, search_question, fast_diagnostics)
        if event_reference_contexts:
            fast_diagnostics.update(strategy="current_reference_only", research_deferred=True,
                                    partial=True, exhaustive=False)
        from api.ai.free_answer import simple_search_plan
        if (natural_mode and not fast_contexts and cloud_allowed(request)
                and simple_search_plan(search_question, history) is None
                and provider is not local_provider and callable(getattr(provider, "generate", None))
                and (request.as_of is not None or not re.search(r"\b(?:19|20)\d{2}\b", search_question))
                and getattr(settings, "rag_research_planning", True)):
            from api.ai.research_plan import make_plan
            plan_started = monotonic()
            async with _generation_slot(provider, local_provider):
                research_aspects = await asyncio.to_thread(
                    make_plan, auxiliary_provider(provider, generation_profile), search_question,
                    diagnostics=timings.extra.setdefault("research_plan", {}))
            timings.extra["research_plan_ms"] = round((monotonic()-plan_started)*1000, 1)
        timings.extra.update(fast_diagnostics)
        embed_started = monotonic()
        # General cloud chat: `_free_answer` plans the question and runs every part's own semantic search (decision + legislation
        # vectors). The whole-question semantic lanes of this first search only repeated that work in sequence before it (measured
        # 2026-10-31: ~20 s retrieval + 4.6 s embedding, then ~23 s of part searches). The first search keeps its word and statute
        # lanes as the seed pool; private, scoped, historical and local-model requests keep the full search.
        seed_only = _seed_search_only(request, natural_mode=natural_mode, generation_profile=generation_profile,
                                      cloud_provider=provider is not local_provider, force_full=_force_full_search,
                                      has_seed=bool(fast_contexts))
        timings.extra['seed_search_lexical_only'] = seed_only
        embedding_requested = settings.rag_query_embedding and not fast_contexts and not seed_only
        query_embedding, legislation_embedding = (
            await asyncio.gather(_embed_question(search_question), _embed_legislation_question(search_question))
            if embedding_requested
            else (None, None)
        )
        timings.embedding_ms = (
            (monotonic() - embed_started) * 1000 if embedding_requested else 0.0
        )
        if embedding_requested:
            timings.extra['query_embeddings'] = dict(
                shared_ready=query_embedding is not None, legislation_ready=legislation_embedding is not None,
            )

        statute_reference = explicit_statute_reference(search_question)
        if not natural_mode and statute_reference is not None and request.as_of is None and not fast_contexts:
            law_no, article_no = statute_reference
            await emit(
                "verifying_source",
                source_type="legislation",
                law_no=law_no,
                article_no=article_no,
            )
            verification_started = monotonic()
            verification_status = await asyncio.to_thread(
                verify_pending_statute,
                search_question,
                as_of=request.as_of,
            )
            timings.extra["on_demand_legislation"] = verification_status
            timings.extra["on_demand_legislation_ms"] = round(
                (monotonic() - verification_started) * 1000,
                1,
            )

        if not natural_mode and request.as_of is None and not fast_contexts:
            relevant_verification_started = monotonic()
            relevant_verification_status = await asyncio.to_thread(
                verify_relevant_pending_statute,
                search_question,
                as_of=request.as_of,
            )
            timings.extra[
                "on_demand_relevant_legislation"
            ] = relevant_verification_status
            timings.extra["on_demand_relevant_legislation_ms"] = round(
                (monotonic() - relevant_verification_started) * 1000,
                1,
            )

        retrieval_started = monotonic()
        seed_failed = False
        retrieval_diagnostics: dict = dict(fast_diagnostics) if fast_contexts else {}
        verification_diagnostics: dict = {}
        try:
            contexts = fast_contexts or await _retrieve_with_warm_retry(
                request,
                user_id=user_id,
                query_embedding=query_embedding,
                top_k=candidate_pool_size(settings.rag_top_k),
                embedding_model=settings.embedding_model,
                question=search_question,
                diagnostics=retrieval_diagnostics,
                legislation_embedding=legislation_embedding,
            )
            if seed_only and not contexts and settings.rag_query_embedding:
                # The word/statute seed found nothing (measured 2026-10-31: a mobbing question): the full search, with the
                # question's vectors, runs as before instead of ending with "no sources" before the part searches start.
                timings.extra['seed_search_lexical_only'] = False
                query_embedding, legislation_embedding = await asyncio.gather(
                    _embed_question(search_question), _embed_legislation_question(search_question))
                retrieval_diagnostics.clear()
                contexts = await _retrieve_with_warm_retry(
                    request,
                    user_id=user_id,
                    query_embedding=query_embedding,
                    top_k=candidate_pool_size(settings.rag_top_k),
                    embedding_model=settings.embedding_model,
                    question=search_question,
                    diagnostics=retrieval_diagnostics,
                    legislation_embedding=legislation_embedding,
                )
        except HTTPException:
            raise
        except psycopg.Error as exc:
            logger.exception("Hukuk kaynakları aranamadı")
            if not seed_only:
                raise HTTPException(
                    status_code=503, detail="Hukuk kaynakları aranamadı"
                ) from exc
            # The general chat's first search is only the seed pool: `_free_answer` runs its own search for every part. A database
            # that refused the seed (overload, timeout; measured 2026-10-31: two of twenty questions) is not a reason to fail the
            # request before the part searches had their chance. The research is flagged incomplete instead.
            contexts = []
            seed_failed = True
            retrieval_diagnostics["partial"] = True
            retrieval_diagnostics["decision_search"] = "timeout"
        if research_aspects:
            from api.ai.research_plan import search_aspects
            async def retrieve_aspect(query):
                statutes = await asyncio.to_thread(_planned_statutes, request, query)
                if statutes:
                    return statutes, False
                diagnostic = {}
                rows = await _retrieve_with_warm_retry(
                    request, user_id=user_id, query_embedding=None,
                    top_k=min(24, candidate_pool_size(settings.rag_top_k)),
                    embedding_model=settings.embedding_model, question=query,
                    diagnostics=diagnostic, legislation_embedding=None)
                return rows, bool(diagnostic.get("partial"))
            research_evidence, planned_rows = await search_aspects(research_aspects, retrieve_aspect)
            contexts = list({c.chunk_id: c for c in [*contexts, *planned_rows]}.values())
            if research_evidence.failed:
                retrieval_diagnostics["partial"] = True
            timings.extra["research_plan"].update(
                searched=len(research_aspects), incomplete=len(research_evidence.failed))
        timings.retrieval_ms = ((monotonic() - retrieval_started) * 1000
            + fast_diagnostics.get('fast_statute_ms', 0) + fast_diagnostics.get('provisional_seed_ms', 0))
        # Portal verification overlaps model warmup, never answer generation.
        candidates = list(contexts)
        timings.extra['retrieval'] = retrieval_diagnostics
        await emit('candidates_found', candidate_chunks=len(candidates),
                   candidate_documents=len({c.source_id for c in candidates}),
                   partial=bool(retrieval_diagnostics.get('partial')), exhaustive=False)
        verify_task = None if natural_mode else _start_live_verification(
            contexts, target_sources=settings.rag_top_k, diagnostics=verification_diagnostics,
        )
        if warmup_task is not None:
            await warmup_task
            warmup_task = None
    finally:
        if warmup_task is not None:
            warmup_task.cancel()
            try:
                await warmup_task
            except (asyncio.CancelledError, Exception):
                pass

    # Verify BEFORE cache, source previews or generation. A timeout must not
    # release pending text to the model or user, even if it is correctly quoted.
    if verify_task is not None:
        await emit("verifying_source", source_type="court_decision")
        contexts = await _resolve_verification(
            verify_task, contexts, wait=_PRE_GENERATION_VERIFY_WAIT_SECONDS, timings=timings
        )
        verify_task = None
    contexts = verified_contexts(contexts)
    if ((not contexts or _missing_requested_article(request.question, contexts) is not None)
            and generation_profile == 'default' and cloud_allowed(request)
            and request.as_of is None and not holds_private_documents(contexts)
            and getattr(settings, 'official_web_research_enabled', False)):
        # Do not return "no local source" before the approved public-web lane
        # can run. The adapter sends only numeric references/fixed vocabulary.
        from api.ai.official_research import research_official
        await emit('retrieving', source_type='official_web')
        web_result = await asyncio.to_thread(research_official, [search_question], contexts, public_scope=True)
        timings.extra['official_web'] = list(web_result.statuses)
        contexts = list({c.chunk_id: c for c in [*contexts, *web_result.contexts]}.values())
    verified_pool = contexts
    # A cloud writer reads a few more sources: the legislation-only branch adds up to two provisions, and with the
    # local 6-source limit they pushed out the decisions a nafaka answer rested on (2026-10-22). The local model keeps
    # its small window.
    from api.ai.retrieval import _LEGISLATION_PREFERRED
    answer_limit = settings.rag_top_k + (_LEGISLATION_PREFERRED if provider is not local_provider else 0)
    if research_evidence is not None and not holds_private_documents(verified_pool):
        from api.ai.research_plan import select_contexts
        contexts = select_contexts(verified_pool, [], research_evidence,
                                  max(answer_limit, len(research_aspects)*2), search_question)
    else:
        research_evidence = None
        contexts = select_answer_contexts(verified_pool, answer_limit, question=search_question)
    verification_stats = dict(verification_diagnostics)
    if timings.extra.get('live_verify') in ('timeout', 'error'):
        verification_stats['stop_reason'] = timings.extra['live_verify']
    summary = search_summary(candidates, verified_pool, contexts,
                             retrieval_diagnostics, verification_stats)
    timings.extra['search_summary'] = summary
    timings.extra['verification'] = verification_stats
    timings.extra['unverified_excluded'] = summary['unverified_excluded']
    logger.info('RAG discovery %s', summary)
    await emit('search_summary', **summary)
    if not contexts and not seed_failed:
        pending = int((retrieval_diagnostics.get('document_scope') or {}).get('pending') or 0)
        if (request.case_id is not None or request.office_project_id is not None) and pending:
            # Asıl neden "kaynak yok" değil, davadaki belgelerin henüz hazır olmaması (ör. OCR sürüyor).
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Bu davadaki {pending} belge henüz işleniyor (taranmış belgeler OCR ile okunur, "
                    "birkaç dakika sürebilir). İşlem bitince soruyu tekrar sorun."
                ),
            )
        scope = retrieval_diagnostics.get('document_scope') or {}
        if scope.get('file_only'):
            raise HTTPException(422, "Bu soru için çalışma alanınızdaki belgelerde yeterli bilgi bulunamadı. Projeye bağlı dava/belge yoksa önce bağlayın; hukuki araştırma için mevzuat veya içtihat istediğinizi belirtin.")
        missing_article = _missing_requested_article(request.question, [])
        if missing_article is not None:
            # A named article that nothing matched is answered about that article, not with the generic "narrow the question /
            # select a document" reply (measured 2026-10-30: "4857 m. 999 yoksa açıkça belirt" got the generic one).
            return await _finish_without_evidence(
                request, user_id, text=_missing_article_text(*missing_article, timings.extra.get('official_web')),
                kind="insufficient_sources", timings=timings, started=started, emit=emit, audit=audit,
            )
        if natural_mode:
            definition = await _general_definition_fallback(
                request, user_id, provider=provider, local_provider=local_provider,
                generation_profile=generation_profile, timings=timings, started=started, emit=emit, audit=audit,
            )
            if definition is not None:
                return definition
            from api.ai.event_context import build_event_context, compose_event_answer
            event = build_event_context(request.question, (), prior_questions=prior_questions,
                                        history=history, as_of=request.as_of)
            text = (compose_event_answer("", event, generation_failed=True) if event is not None else
                    "Bu soruyu yanıtlayacak yeterli bilgiyi kaynaklarımızda bulamadım. Konuyu biraz daraltabilir veya ilgili belgeyi seçebilir misiniz?")
            return await _finish_without_evidence(
                request, user_id,
                text=text,
                kind="insufficient_sources", timings=timings, started=started, emit=emit, audit=audit,
            )
        raise HTTPException(
            status_code=422,
            detail="Bu soru için yeterli resmî doğrulanmış kaynak bulunamadı. Portal doğrulaması tamamlanmamış veya eşleşmeyen kayıtlar cevaba alınmadı.",
        )

    await emit("sources_found", count=len(contexts), sources=_source_preview(contexts))
    if provider is not local_provider and holds_private_documents(contexts):
        # Scoped primary: local in legacy mode, explicitly authorized Bedrock
        # in deployment-wide cloud mode. Never reuse the public fallback route.
        provider = local_provider
    from api.ai.practical_answer import RentCalculationProvider, has_calculation_inputs, rent_basis
    calculation = None
    if not natural_mode or has_calculation_inputs(request.question, prior_questions):
        calculation = rent_basis(contexts, question=answer_question, user_question=request.question,
                                 prior_questions=prior_questions)
    if calculation is not None:
        provider = calculation
    # Natural answers use their server-owned verified object plus current
    # evidence fingerprints, never the exact-quotation cache gate.
    use_natural = natural_mode and calculation is None
    from api.uyap_record_document import RECORD_AUTHORITY
    if any(context.authority == RECORD_AUTHORITY for context in contexts):
        use_natural = False  # names and financial registry fields remain verbatim
    fingerprint = source_fingerprint(contexts)
    cache_key = answer_cache_key(
        # Aynı takip sorusu farklı konularda farklı yorumlanır: yorumlanmış soru anahtarın parçasıdır.
        question=request.question if interpreted is None else f"{request.question} | {interpreted}",
        project_id=request.project_id or request.case_id or request.office_project_id,
        as_of=request.as_of,
        model=provider_cache_model(provider, generation_profile),
        fingerprint=fingerprint,
        history_key=history_fingerprint(history),
        selected_document_ids=request.selected_document_ids,
        user_id=user_id if use_natural or request.selected_document_ids else None,
    )
    cached = answer_cache.get(cache_key)
    conversation_id: UUID | None = None
    message_id: UUID | None = None
    if cached is not None:
        timings.from_cache = True
        cached_contexts = await _resolve_verification(
            verify_task, contexts, wait=_CACHE_HIT_VERIFY_WAIT_SECONDS, timings=timings
        )
        cited_ids = [item["chunk_id"] for item in cached["citations"]]
        by_id = {str(context.chunk_id): context for context in cached_contexts}
        ordered = tuple(by_id[chunk_id] for chunk_id in cited_ids if chunk_id in by_id)
        cached_answer = (restore_verified_natural_answer(cached, cached_contexts) if use_natural else
                         verify_answer(cached["answer"], list(ordered), question=search_question,
                                       available_contexts=contexts))
        if len(ordered) != len(cited_ids):
            cached = None
        if cached is not None and cached_answer is not None and cached_answer.grounded:
            from dataclasses import replace as _replace
            cached_answer = _replace(cached_answer, summary=tuple(str(item) for item in (cached.get("summary") or ())))
            cached_answer = await asyncio.to_thread(_with_verification_note, request, cached_answer)
            persist_started = monotonic()
            if user_id is not None:
                conversation_id, message_id = await asyncio.to_thread(
                    persist_answer,
                    request,
                    cached_answer,
                    user_id=user_id,
                    model_name=provider.model,
                    audit=audit,
                    from_cache=True,
                    document_scope=retrieval_diagnostics.get("document_scope"),
                )
            timings.persist_ms = (monotonic() - persist_started) * 1000
            timings.total_ms = (monotonic() - started) * 1000
            response = _response_from_verified(
                request,
                cached_answer,
                provider=provider,
                conversation_id=conversation_id,
                message_id=message_id,
                from_cache=True,
                timings=timings,
                consulted=verified_pool,
            )
            await emit("done", result=response.model_dump(mode="json"))
            return response, timings

    # Old/invalid cache entries must go through generation and the current gate.
    timings.from_cache = False
    await emit("generating")
    synthesized: VerifiedAnswer | None = None
    extractive_fallback = False
    from api.ai.event_context import build_event_context
    event_for_generation = build_event_context(request.question, contexts,
                                               prior_questions=prior_questions, history=history,
                                               as_of=request.as_of,
                                               basis_complete=False if event_reference_contexts else None)
    missing = _missing_requested_article(request.question, contexts)
    if missing is not None:
        # "4857 sayılı Kanun madde 999" korpusta yoksa model çağrılmaz: modele ilgisiz kararlar okutmak sayfa numarası gibi
        # anlamsız eşleşmeler doğuruyordu (2026-10-25) ve kredi harcıyordu. Yokluk yalnız bizim doğrulanmış korpusumuz içindir.
        return await _finish_without_evidence(
            request, user_id, text=_missing_article_text(*missing, timings.extra.get('official_web')),
            kind="insufficient_sources", timings=timings, started=started, emit=emit, audit=audit,
        )
    try:
        if isinstance(provider, RentCalculationProvider):
            raw_answer = provider.basis_text
            timings.llm_ms = 0
        else:
            async with _generation_slot(provider, local_provider):
                llm_started = monotonic()
                if use_natural:
                    from api.ai.synthesis import synthesize_answer
                    free = None
                    free_route = False
                    if (getattr(settings, "free_answer_enabled", False)
                            # Yerel model de aynı kanıtlı düzene girebilir (kullanıcı 2026-10-30: "bedava olsun, bulutu boşver").
                            and (provider is not local_provider or getattr(settings, "free_answer_local", False))
                            and generation_profile == "default" and event_for_generation is None
                            and not holds_private_documents(contexts)
                            and request.project_id is None and request.case_id is None
                            and request.office_project_id is None and not request.selected_document_ids):
                        # Önce serbest cevap, sonra her cümlenin kanıtı (api/ai/free_answer.py). Kanıtlanabilen cümle yoksa ya
                        # da yol başarısız olursa `free` boş kalır ve aşağıdaki eski sentez yolu aynen çalışır.
                        free_route = True
                        partial_loop = asyncio.get_running_loop()

                        def push_partial(partial: VerifiedAnswer) -> None:
                            # Verified sentences only (never a draft): the user reads them while the rest is proven. The final
                            # answer replaces the preview; nothing here is saved. Runs in the worker thread, so the event is
                            # handed to the event loop.
                            preview = _response_from_verified(
                                request, partial, provider=provider, conversation_id=None, message_id=None, from_cache=False,
                                timings=timings, consulted=list(partial.contexts))
                            asyncio.run_coroutine_threadsafe(
                                emit("partial", preview=preview.model_dump(mode="json")), partial_loop)

                        free = await asyncio.to_thread(
                            _free_answer, provider, answer_question, _with_decisions(contexts, verified_pool, question=answer_question), history, timings,
                            auxiliary_provider(provider, generation_profile), None,
                            **({'prepared_plan': tuple((a.label, (a.query,)) for a in research_aspects)}
                               if research_aspects else {}),
                            public_web_scope=cloud_allowed(request) and request.as_of is None,
                            on_partial=(push_partial if getattr(settings, 'free_answer_stream_verified', True) else None))
                        free_info = timings.extra.get('free_answer') or {}
                        part_searches = timings.extra.get('part_searches', ())
                        if isinstance(timings.extra.get('search_summary'), dict) and part_searches:
                            # The answer was built from these per-part searches: if one of them ran out of time or answered from
                            # a sample, the research may be incomplete and the user is told so (graver kind wins).
                            summary = timings.extra['search_summary']
                            part_limit = worse_limit(*(item.get('limit') or (LIMIT_FAILED if item.get('partial') else LIMIT_NONE)
                                                       for item in part_searches))
                            summary['retrieval_limit'] = worse_limit(summary.get('retrieval_limit'), part_limit)
                            summary['retrieval_partial'] = bool(summary.get('retrieval_partial')) or part_limit != LIMIT_NONE
                        admission = free_info.get('source_admission') or {}
                        if admission.get('unusable') or admission.get('over_budget') or free_info.get('uncovered_parts'):
                            logger.warning('Assistant evidence admission: sources=%s parts=%s reason=%s',
                                           admission, free_info.get('part_admission'), free_info.get('reason'))
                    if free_route:
                        # Kullanıcı kararı 2026-10-25: genel sohbette eski kaynakla-sınırlı sentez yolu YOK. Serbest cevap
                        # cümle cümle kanıtlanamadıysa (free None) eski yola düşülmez; dürüst "doğrulayamadım" cevabı verilir.
                        synthesize_answer = _already_verified(free)
                    budget = getattr(settings, "rag_synthesis_context_chars", 24000)
                    if provider is local_provider and getattr(provider, "name", "") != "bedrock":
                        # Leave room for question, prompt and output on small
                        # local models. Never silently clip evidence mid-unit.
                        budget = min(budget, max(2400, settings.ollama_num_ctx * 2))
                    synthesized = await asyncio.to_thread(
                        synthesize_answer, provider, checker_provider=auxiliary_provider(provider, generation_profile),
                        repair_provider=auxiliary_provider(provider, generation_profile),
                        _generation_calls=timings.extra.setdefault("generation_calls", []),
                        question=answer_question, user_question=request.question,
                        contexts=contexts, max_context_chars=budget, history=history,
                        prior_questions=prior_questions,
                        diagnostics=timings.extra.setdefault("synthesis", {}),
                        # One bounded repair gets the concrete server-owned
                        # support failures, not a generic "try again". Every
                        # repaired sentence faces the same hard/semantic gates.
                        repair_reasons=frozenset({"draft_shape", "evidence", "numeric_polarity", "answer_focus", "research_coverage"}),
                        # Qwen selects complete evidence units by ID rather
                        # than recopying fragile PDF text into a JSON quote.
                        # Resolution and all semantic/numeric checks stay on.
                        compact_evidence=provider is not local_provider or 'qwen' in provider.model,
                        # The primary provider object is also named local_provider
                        # in single-provider Bedrock mode. Object identity is not
                        # a capability check; research needs the same bounded
                        # source-bound repair as ordinary cloud synthesis.
                        semantic_repair=provider is not local_provider or getattr(provider, "name", "") == "bedrock",
                        checker_format_retry=generation_profile == "deep_research",
                        as_of=request.as_of,
                        event_basis_complete=False if event_reference_contexts else None,
                        research_evidence=research_evidence,
                        ask_missing_inputs=followup_question is None,
                    )
                    timings.extra["answer_mode"] = "synthesis" if synthesized else "synthesis_unavailable"
                    if synthesized is None:
                        if free_route:
                            # No prompts, source bodies or user facts in logs.
                            # Previously this logged the unused synthesis dict
                            # ({}), losing the actual natural-answer failure.
                            details = timings.extra.get("free_answer") or {}
                            outcomes = details.get("sentence_outcomes") or {}
                            counts = {label: sum(str(value).startswith(label) for value in outcomes.values())
                                      for label in ("kod:", "denetçi_reddetti", "kaldı")}
                            logger.warning(
                                "Assistant natural answer unavailable: reason=%s checker=%s protocol=%s attempts=%s sentences=%s outcomes=%s",
                                details.get("reason"), details.get("checker_status"), details.get('checker_protocol_attempts'), details.get("attempts"), details.get("draft_sentences"), counts,
                            )
                        else:
                            logger.warning("Assistant synthesis unavailable: %s", timings.extra["synthesis"])
                        reason = (timings.extra.get("synthesis") or {}).get("reason")
                        # A failed natural answer is not permission to erase a
                        # research plan or dump an unsolicited full article.
                        # Exact quotations remain available when explicitly
                        # requested; they still pass the ordinary source gate.
                        quote_requested = _wants_source_text(request.question)
                        if (quote_requested and contexts and reason in (_MECHANICAL_SYNTHESIS_REJECTIONS | {"checker"})
                                and event_for_generation is None and research_evidence is None):
                            use_natural = False
                            extractive_fallback = True
                            timings.extra["answer_mode"] = "synthesis_then_quotes"
                    else:
                        logger.info("Assistant synthesis %s", timings.extra["synthesis"])
                if use_natural:
                    raw_answer = synthesized.text if synthesized is not None else ""
                else:
                    raw_answer = await asyncio.to_thread(
                        generate_grounded_answer,
                        # This call only selects exact evidence ids, not a new
                        # legal explanation. Use the existing auxiliary profile
                        # instead of spending reasoning tokens on copied text.
                        auxiliary_provider(provider, generation_profile) if generation_profile == 'default' else provider,
                        # Keep accents restored for the extractive relevance gate.
                        question=answer_question,
                        contexts=contexts,
                        max_context_chars=settings.rag_context_chars,
                        history=history,
                    )
                timings.llm_ms = (monotonic() - llm_started) * 1000
    except AIProviderError as exc:
        usage = getattr(provider, "last_usage", None)
        if usage is not None:
            timings.prompt_eval_count = usage.prompt_eval_count
            timings.eval_count = usage.eval_count
            timings.done_reason = usage.done_reason
            timings.extra["num_predict"] = usage.num_predict
            timings.extra["num_ctx"] = usage.num_ctx
            logger.info(
                "Ollama generation failed prompt_eval_count=%s eval_count=%s done_reason=%s num_predict=%s num_ctx=%s",
                usage.prompt_eval_count,
                usage.eval_count,
                usage.done_reason,
                usage.num_predict,
                usage.num_ctx,
            )
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    usage = getattr(provider, "last_usage", None)
    if usage is not None:
        timings.prompt_eval_count = usage.prompt_eval_count
        timings.eval_count = usage.eval_count
        timings.done_reason = usage.done_reason
        timings.extra["num_predict"] = usage.num_predict
        timings.extra["num_ctx"] = usage.num_ctx
        logger.info(
            "Ollama generation prompt_eval_count=%s eval_count=%s done_reason=%s num_predict=%s num_ctx=%s",
            usage.prompt_eval_count,
            usage.eval_count,
            usage.done_reason,
            usage.num_predict,
            usage.num_ctx,
        )

    if use_natural and synthesized is None:
        definition = await _general_definition_fallback(
            request, user_id, provider=provider, local_provider=local_provider,
            generation_profile=generation_profile, timings=timings, started=started, emit=emit, audit=audit,
        )
        if definition is not None:
            return definition
        # A rejected explanation is not permission to dump the entire law or
        # publish a second, less-checked model answer. This is an application
        # status, NOT a finding that the corpus lacks the requested information.
        from api.ai.event_context import build_event_context, compose_event_answer
        event = build_event_context(request.question, contexts, prior_questions=prior_questions,
                                    history=history, as_of=request.as_of,
                                    basis_complete=False if event_reference_contexts else None)
        from api.ai.source_digest import build_source_digest
        # Denetçi taslağı içerik olarak reddettiyse ("checker") kaynak metni basılmaz (testlerle kilitli politika); yalnız mekanik
        # ret (sayı/koşul tutarsızlığı, kapsam eksikliği) kaynak özetine düşer.
        digest = (build_source_digest(contexts, request.question)
                  if event is None and _wants_source_text(request.question)
                  and research_evidence is None
                  and (timings.extra.get("synthesis") or {}).get("reason") in _DIGEST_REASONS else None)
        if digest is None:
            text = (compose_event_answer("", event, generation_failed=True) if event is not None else
                    _BUSY_REPLY if (timings.extra.get("free_answer") or {}).get("reason") == "provider" else
                    "Kaynaklar bulundu ancak yanıtın doğrulama işlemi teknik bir sorun nedeniyle tamamlanamadı. Lütfen yeniden deneyin."
                    if (timings.extra.get("free_answer") or {}).get("reason") == "checker_protocol" else
                    _NON_LEGAL_REPLY if (timings.extra.get("free_answer") or {}).get("reason") == "not_legal"
                    or (not contexts and _looks_non_legal(request.question)) else
                    "İlgili kaynaklar bulundu ancak bu yanıtı güvenilir biçimde doğrulayamadım. Şu an kesin bir sonuç veremiyorum.")
            return await _finish_without_evidence(
                request, user_id,
                text=text,
                kind="insufficient_sources", timings=timings, started=started, emit=emit, audit=audit,
            )
        # Taslak denetimden geçmedi ama doğrulanmış kaynaklar var: yorumsuz, aynen aktarılmış kaynak metni gösterilir.
        timings.extra["answer_mode"] = "source_digest"
        synthesized = digest

    await emit("verifying")
    final_contexts = await _resolve_verification(
        verify_task, contexts, wait=_VERIFY_GRACE_SECONDS, timings=timings
    )
    verify_started = monotonic()
    answer = synthesized if synthesized is not None else verify_answer(raw_answer, final_contexts, question=search_question)
    safe_clarification = bool(synthesized is not None and answer.answer_kind in {"clarification", "insufficient_sources"}
                              and not answer.contexts and not answer.unverified_markers)
    if not answer.grounded and not safe_clarification:
        # Taslak yalnız kaynaktan aynen alınmış cümlelerden oluşur. Bir cümle denetimden geçmediğinde (konu dışı ya da
        # desteklenmeyen) cevabın tamamı reddedilmez: o satırlar atılır, kalan metin baştan ve aynı denetimle doğrulanır.
        pruned = prune_rejected_lines(raw_answer, answer)
        if pruned is not None:
            retried = verify_answer(pruned, final_contexts, question=search_question)
            if retried.grounded:
                timings.extra['pruned_lines'] = len(raw_answer.splitlines()) - len(pruned.splitlines())
                answer = retried
    timings.verification_ms = (monotonic() - verify_started) * 1000
    if fast_contexts and not answer.grounded and not safe_clarification:
        # A plausible provision is not proof that it answers the question.
        # Run the full pipeline once; no unsupported fast draft is published.
        timings.extra['fast_statute_fallback'] = 'unsupported_draft'
        return await _execute_answer_body(
            request, user_id, settings=settings, timings=timings, started=started,
            emit=emit, audit=audit, _force_full_search=True,
            generation_profile=generation_profile,
        )
    if not answer.grounded and not safe_clarification:
        # Never put a user's draft, case facts or private document text in logs.
        logger.warning("Yanıt reddedildi: desteklenmeyen=%d, çözülmeyen_işaret=%d, atıf=%d",
                       len(answer.unsupported_claims), len(answer.unverified_markers), len(answer.contexts))
        from api.ai.source_digest import build_source_digest
        digest = (build_source_digest(contexts, request.question) if event_for_generation is None
                  and _wants_source_text(request.question) and research_evidence is None
                  and (timings.extra.get("synthesis") or {}).get("reason") in _DIGEST_REASONS else None)
        if digest is not None:
            timings.extra["answer_mode"] = "source_digest"
            answer = digest
        elif is_insufficient_source_reply(
            answer.text or raw_answer
        ) or has_insufficient_source_signal(raw_answer):
            answer = VerifiedAnswer(
                text=(
                    "Mevcut doğrulanmış kaynaklarda bu soruya güvenilir ve kaynaklı "
                    "bir cevap vermek için yeterli bilgi bulunmuyor."
                ),
                contexts=(),
                unverified_markers=answer.unverified_markers,
                answer_kind="insufficient_sources",
            )
        else:
            raise HTTPException(
                status_code=422,
                detail="Yanıt kaynak metniyle doğrulanamadı; desteklenmeyen hukuki iddialar gösterilmiyor",
            )

    from api.ai.practical_answer import rent_summary
    practical = rent_summary(answer, question=answer_question, user_question=request.question,
                             prior_questions=prior_questions) if calculation is not None or not natural_mode else ()
    if not use_natural and synthesized is None and answer.grounded and not practical and getattr(settings, "rag_explanations", False):
        from api.ai.explanation import explain_verified_answer
        explanation_started = monotonic()
        async with _generation_slot(provider, local_provider):
            answer = await asyncio.to_thread(
                explain_verified_answer, auxiliary_provider(provider, generation_profile),
                question=search_question, answer=answer,
            )
        timings.extra["explanation_ms"] = round((monotonic() - explanation_started) * 1000, 1)

    from api.ai import statute_summary
    if practical:
        answer = replace(answer, summary=practical)
    elif not use_natural and synthesized is None and statute_summary.eligible(answer):
        # Uzun madde metninin üstüne denetlenmiş kısa özet: cevap metni ve atıflar değişmez (bkz. statute_summary).
        from dataclasses import replace as _replace
        summary_started = monotonic()

        async def _summary_generate(system: str, prompt: str) -> str:
            async with _generation_slot(provider, local_provider):
                return await asyncio.to_thread(auxiliary_provider(provider, generation_profile).generate,
                                              system_instruction=system, prompt=prompt)

        # Özet ek bir model çağrısıdır ve uzun maddede dakikaya yaklaşabilir (ölçüldü: 85 sn, 2026-10-06). Doğrulanmış
        # cevap o sırada hazırdır: önizleme olarak gönderilir, kullanıcı özeti beklerken cevabı okur. Önizleme kaydedilmez;
        # kalıcı cevap (özetiyle) her zamanki gibi "done" ile gelir.
        from api.ai.explanation import with_coverage_notice as _with_notice
        preview = _response_from_verified(
            request, _with_notice(answer, search_question), provider=provider, conversation_id=None,
            message_id=None, from_cache=False, timings=timings, consulted=verified_pool,
        )
        await emit("summarizing", preview=preview.model_dump(mode="json"))
        answer = _replace(answer, summary=await statute_summary.build(answer_question, answer, _summary_generate))
        timings.extra["statute_summary_ms"] = round((monotonic() - summary_started) * 1000, 1)
        timings.extra["statute_summary_bullets"] = len(answer.summary)

    from api.ai.explanation import with_coverage_notice
    if synthesized is None:
        answer = with_coverage_notice(answer, search_question)
    from api.ai.event_context import build_event_context, compose_event_answer
    event = build_event_context(request.question, contexts, prior_questions=prior_questions,
                                history=history, as_of=request.as_of,
                                basis_complete=False if event_reference_contexts else None)
    if event is not None:
        if answer.answer_kind == "clarification" and event.historical_basis_missing:
            # More event questions cannot repair missing historical source
            # coverage. Preserve known facts and disclose the actual blocker.
            answer = VerifiedAnswer(text=compose_event_answer("", event), contexts=(),
                                    unverified_markers=(), answer_kind="insufficient_sources")
        elif answer.answer_kind != "clarification":
            answer = replace(answer, text=compose_event_answer(answer.text, event, legal_reference=answer.grounded))
    if followup_question and answer.grounded and answer.answer_kind == "legal":
        answer = replace(answer, text=answer.text + "\n\n" + followup_question)
    answer = await asyncio.to_thread(_with_verification_note, request, answer)
    persist_started = monotonic()
    if user_id is not None:
        conversation_id, message_id = await asyncio.to_thread(
            persist_answer,
            request,
            answer,
            user_id=user_id,
            model_name=provider.model,
            audit=audit,
            document_scope=retrieval_diagnostics.get("document_scope"),
        )
    timings.persist_ms = (monotonic() - persist_started) * 1000
    response = _response_from_verified(
        request,
        answer,
        provider=provider,
        conversation_id=conversation_id,
        message_id=message_id,
        from_cache=False,
        timings=timings,
        consulted=verified_pool,
    )
    natural_cacheable = (use_natural and generation_profile == "default" and cloud_allowed(request)
                         and (timings.extra.get("free_answer") or {}).get("status") == "accepted"
                         and (timings.extra.get("free_answer") or {}).get("coverage_preserved") is not False
                         and not (timings.extra.get("free_answer") or {}).get("partial_answer")
                         and not (timings.extra.get("free_answer") or {}).get("uncovered_parts"))
    if (answer.grounded and (not use_natural or natural_cacheable) and not extractive_fallback
            and event is None
            and not (isinstance(provider, FallbackProvider) and provider.fell_back)):
        payload = _payload_from_response(response)
        if natural_cacheable:
            payload["_verified_natural_answer"] = answer
        answer_cache.put(cache_key, payload)
        from api.ai import warm_cache
        collect = warm_cache.collector.get()
        if (collect is not None and natural_cacheable and _warm_cache_eligible(request, settings, provider, local_provider, history,
                                                                              generation_profile)):
            collect(request.question, answer, provider_cache_model(provider, generation_profile))
    timings.total_ms = (monotonic() - started) * 1000
    await emit("done", result=response.model_dump(mode="json"))
    return response, timings


async def iter_answer_events(
    request: AIAnswerRequest,
    user_id: UUID | None,
    audit: AuditContext | None = None,
) -> AsyncIterator[dict[str, Any]]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def on_stage(event: dict[str, Any]) -> None:
        await queue.put(event)

    async def run() -> None:
        try:
            await execute_answer(request, user_id, on_stage=on_stage, audit=audit)
        except HTTPException as exc:
            await queue.put(
                {"stage": "error", "status": exc.status_code, "detail": exc.detail}
            )
        except Exception:
            logger.exception("AI yanıt üretimi başarısız")
            await queue.put(
                {
                    "stage": "error",
                    "status": 500,
                    "detail": "AI yanıtı üretilemedi",
                }
            )
        finally:
            await queue.put({"stage": "_end"})

    task = asyncio.create_task(run())
    try:
        while True:
            try:
                event = await asyncio.wait_for(
                    queue.get(),
                    timeout=_PROGRESS_HEARTBEAT_SECONDS,
                )
            except TimeoutError:
                yield {"stage": "ping"}
                continue
            if event.get("stage") == "_end":
                break
            yield event
    finally:
        await task
