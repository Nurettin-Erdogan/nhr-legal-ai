"""Shared grounded-answer pipeline: retrieve, cache, generate, verify, persist."""

from __future__ import annotations

import asyncio
import logging
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
from api.ai.document_selection import selected_document_coverage
from api.ai.cache import (
    answer_cache,
    answer_cache_key,
    history_fingerprint,
    source_fingerprint,
)
from api.ai.conversation_history import (
    ConversationNotFound,
    load_conversation_context,
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
from api.ai.discovery import candidate_pool_size, select_answer_contexts, search_summary
from api.ai.fast_statute import try_fast_statute
from api.ai.event_lookup import lookup_event_basis
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
_MECHANICAL_SYNTHESIS_REJECTIONS = frozenset({"evidence", "draft_shape", "numeric_polarity", "source_shape", "budget",
                                              # claims WE left out made an otherwise fully supported answer incomplete
                                              "dropped_coverage",
                                              # the writer claimed a source gap the checker rejected (sources cover it)
                                              "unconfirmed_source_gap"})


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
        document_scope=(
            None if timings is None else (timings.extra.get('retrieval') or {}).get('document_scope')
        ),
    )


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
) -> tuple[AIAnswerResponse, PipelineTimings]:
    """Conversation/status is not a legal finding and must never be marked grounded."""
    answer = VerifiedAnswer(text=text, contexts=(), unverified_markers=(), answer_kind=kind)
    provider = _ServerReplyProvider(model=model_name)
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


_CASE_STATUTE_ARTICLES = 2
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
    for hint in hints[:_CASE_STATUTE_ARTICLES]:
        try:
            with connection.transaction():  # zaman aşımı yalnız bu ek sorguyu düşürür, asıl aramayı değil
                rows = _execute_retrieval(
                    connection, STATUTE_RETRIEVAL_SQL,
                    {"law_no": hint.law_no, "article_no": hint.article_no, "as_of": None, "top_k": _CASE_STATUTE_CHUNKS},
                    timeout="2s",
                )
        except psycopg.Error:
            logger.warning("Dava sorusu için madde ipucu okunamadı: %s m.%s", hint.law_no, hint.article_no)
            continue
        rows = [row for row in rows if row.source_type == "legislation" and row.verification == "official"]
        if rows and statute_hints.text_matches(hint, " ".join(row.content for row in rows)):
            found.extend(rows)
    return found


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
    from api.ai.conversation_intent import conversation_reply
    from api.ai.arithmetic import arithmetic_reply
    social = conversation_reply(request.question)
    arithmetic = arithmetic_reply(request.question) if social is None else None
    social = social or arithmetic
    if social is not None and generation_profile == "default":
        if not cloud_allowed(request) and user_id is None:
            raise HTTPException(401, "Çalışma alanı için oturum açmalısınız")
        await _load_history(request, user_id)
        return await _finish_without_evidence(
            request, user_id, text=social, kind="conversation", timings=timings,
            started=started, emit=emit, audit=audit,
            model_name="decimal-arithmetic-v1" if arithmetic is not None else "conversation-router-v1",
        )
    await emit("searching")
    history_context = None
    if generation_profile == "default" and cloud_allowed(request):
        # Asking for the user's event facts is not a legal assertion and needs
        # neither corpus evidence nor a paid model. Always validate saved scope
        # and ownership first. Document questions stay on their reading route.
        history_context = await _load_history(request, user_id)
        from api.ai.dialogue import missing_input_plan
        input_plan = missing_input_plan(request.question, (), history=history_context[0],
                                        prior_questions=history_context[1], allow_source_free=True)
        if input_plan is not None:
            timings.extra["missing_inputs"] = list(input_plan.missing)
            return await _finish_without_evidence(
                request, user_id, text=input_plan.question, kind="clarification",
                timings=timings, started=started, emit=emit, audit=audit,
                model_name="dialogue-inputs-v1",
            )
    local_provider, provider = _answer_providers(settings, request, generation_profile)
    local_resources = provider is local_provider
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
    natural_mode = getattr(settings, "rag_natural_answers", False)

    local_provider, provider = providers or _answer_providers(settings, request, generation_profile)

    # Takip sorusu ("Peki bunun süresi?") önceki sorulara göre tek başına anlaşılır hâle getirilir; sonuç kodla
    # denetlenir (bkz. conversation_history.accept_rewrite) ve yalnız arama ile kanıt seçimini yönlendirir.
    interpreted: str | None = None
    from api.ai.dialogue import resume_question
    interpreted = resume_question(request.question, history, prior_questions)
    if prior_questions and interpreted is None:
        rewrite_started = monotonic()
        async with _generation_lock:
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
                from api.ai.event_context import compose_event_answer
                return await _finish_without_evidence(
                    request,user_id,text=compose_event_answer("",temporal.event),kind="insufficient_sources",
                    timings=timings,started=started,emit=emit,audit=audit,model_name="event-scope-v1",
                )
            # Use the explicit or independently parsed event date for discovery,
            # never mix current versions/future cases into this historical run.
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
        fast_contexts = [] if _force_full_search or request.selected_document_ids else await asyncio.to_thread(
            try_fast_statute, question=search_question, as_of=request.as_of,
            project_id=request.project_id or request.case_id or request.office_project_id, conversation_id=fast_conversation_id,
            max_chunks=settings.rag_top_k, max_chars=settings.rag_context_chars,
            diagnostics=fast_diagnostics,
        )
        timings.extra.update(fast_diagnostics)
        embed_started = monotonic()
        embedding_requested = settings.rag_query_embedding and not fast_contexts
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
        except HTTPException:
            raise
        except psycopg.Error as exc:
            logger.exception("Hukuk kaynakları aranamadı")
            raise HTTPException(
                status_code=503, detail="Hukuk kaynakları aranamadı"
            ) from exc
        timings.retrieval_ms = (monotonic() - retrieval_started) * 1000 + fast_diagnostics.get('fast_statute_ms', 0)
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
    verified_pool = contexts
    # A cloud writer reads a few more sources: the legislation-only branch adds up to two provisions, and with the
    # local 6-source limit they pushed out the decisions a nafaka answer rested on (2026-10-22). The local model keeps
    # its small window.
    from api.ai.retrieval import _LEGISLATION_PREFERRED
    answer_limit = settings.rag_top_k + (_LEGISLATION_PREFERRED if provider is not local_provider else 0)
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
    if not contexts:
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
        if natural_mode:
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
        provider = local_provider  # kullanıcı belgesi hiçbir zaman buluta gönderilmez
    from api.ai.practical_answer import RentCalculationProvider, has_calculation_inputs, rent_basis
    calculation = None
    if not natural_mode or has_calculation_inputs(request.question, prior_questions):
        calculation = rent_basis(contexts, question=answer_question, user_question=request.question,
                                 prior_questions=prior_questions)
    if calculation is not None:
        provider = calculation
    # Paraphrases cannot be revalidated by the exact-quotation cache gate. Do
    # not cache them until their full claim/evidence proof can be rechecked.
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
        user_id=user_id if request.selected_document_ids else None,
    )
    cached = None if use_natural else answer_cache.get(cache_key)
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
        cached_answer = verify_answer(cached["answer"], list(ordered), question=search_question,
                                      available_contexts=contexts)
        if len(ordered) != len(cited_ids):
            cached = None
        if cached is not None and cached_answer.grounded:
            from dataclasses import replace as _replace
            cached_answer = _replace(cached_answer, summary=tuple(str(item) for item in (cached.get("summary") or ())))
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
                                               as_of=request.as_of)
    try:
        if isinstance(provider, RentCalculationProvider):
            raw_answer = provider.basis_text
            timings.llm_ms = 0
        else:
            async with _generation_lock:
                llm_started = monotonic()
                if use_natural:
                    from api.ai.synthesis import synthesize_answer
                    budget = getattr(settings, "rag_synthesis_context_chars", 24000)
                    if provider is local_provider:
                        # Leave room for question, prompt and output on small
                        # local models. Never silently clip evidence mid-unit.
                        budget = min(budget, max(2400, settings.ollama_num_ctx * 2))
                    synthesized = await asyncio.to_thread(
                        synthesize_answer, provider, checker_provider=auxiliary_provider(provider, generation_profile),
                        question=answer_question, user_question=request.question,
                        contexts=contexts, max_context_chars=budget, history=history,
                        prior_questions=prior_questions,
                        diagnostics=timings.extra.setdefault("synthesis", {}),
                        # A content repair (quote/number) never succeeded in 2026-10-22 measurements and cost 8-26 s;
                        # those drafts go straight to the verified-quote route. A malformed draft is still repaired.
                        repair_reasons=frozenset({"draft_shape"}),
                        compact_evidence=provider is not local_provider,
                        semantic_repair=provider is not local_provider and generation_profile == "default",
                        as_of=request.as_of,
                    )
                    timings.extra["answer_mode"] = "synthesis" if synthesized else "synthesis_unavailable"
                    if synthesized is None:
                        logger.warning("Assistant synthesis unavailable: %s", timings.extra["synthesis"])
                        reason = (timings.extra.get("synthesis") or {}).get("reason")
                        if contexts and reason in _MECHANICAL_SYNTHESIS_REJECTIONS and event_for_generation is None:
                            # The free-form writer often paraphrases a quote, and the strict evidence gate rightly
                            # rejects it before any checker ran. That used to end as "oluşturamadım" (measured
                            # 2026-10-22: 20/20 eval questions). Fall back to the verified-quote answer with its short
                            # checked summary (statute_summary) — the route that scored 20/20 grounded on 2026-10-18.
                            # A draft the independent checker rejected never gets this second route.
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
        # A rejected explanation is not permission to dump the entire law or
        # publish a second, less-checked model answer. This is an application
        # status, NOT a finding that the corpus lacks the requested information.
        from api.ai.event_context import build_event_context, compose_event_answer
        event = build_event_context(request.question, contexts, prior_questions=prior_questions,
                                    history=history, as_of=request.as_of)
        text = (compose_event_answer("", event, generation_failed=True) if event is not None else
                "İlgili kaynaklar bulundu ancak bu yanıtı güvenilir biçimde doğrulayamadım. Şu an kesin bir sonuç veremiyorum.")
        return await _finish_without_evidence(
            request, user_id,
            text=text,
            kind="insufficient_sources", timings=timings, started=started, emit=emit, audit=audit,
        )

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
        if is_insufficient_source_reply(
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
        async with _generation_lock:
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
            async with _generation_lock:
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
                                history=history, as_of=request.as_of)
    if event is not None:
        if answer.answer_kind == "clarification" and event.historical_basis_missing:
            # More event questions cannot repair missing historical source
            # coverage. Preserve known facts and disclose the actual blocker.
            answer = VerifiedAnswer(text=compose_event_answer("", event), contexts=(),
                                    unverified_markers=(), answer_kind="insufficient_sources")
        elif answer.answer_kind != "clarification":
            answer = replace(answer, text=compose_event_answer(answer.text, event, legal_reference=answer.grounded))
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
    if (answer.grounded and not use_natural and not extractive_fallback
            and event is None
            and not (isinstance(provider, FallbackProvider) and provider.fell_back)):
        answer_cache.put(cache_key, _payload_from_response(response))
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
