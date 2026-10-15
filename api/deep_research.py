"""Derin araştırma: tek bir hukuki soruyu sabit araştırma eksenlerine bölen, kodda doğrulanan çok adımlı iş.

Eski "Agent" sayfası tek geçişli bir cevap üretiyordu ama "doktrin ve karşılaştırmalı hukuk" gibi korpusta olmayan kaynaklar vaat
ediyordu. Bu modül gerçekten çok adımlıdır ve yalnız elinde olanı söyler:

1. **Plan (belirleyici):** soru üç eksene ayrılır: ilgili mevzuat, yargı kararları, süre/ispat/usul. Plan model çıktısı değildir.
2. **Adımlar:** her eksen için mevcut cevap hattı (`execute_answer`) çalışır: kaynak getirme, kodda atıf ve destek doğrulaması, kaynak yoksa
   "yetersiz" cevabı. Bu modül hiçbir hukuki metin üretmez; her adımın cevabı kendi doğrulamasından geçmiş olarak gelir.
3. **Rapor (belirleyici):** adım cevapları başlıklar altında, kendi kaynaklarıyla birleştirilir. Kaynağı bulunamayan eksen "kaynak
   bulunamadı" diye açıkça yazılır. Doğrulanmamış (üçüncü taraf) kaynaklar rozetle ayrı gösterilir.

Soru metni günlüğe yazılmaz: olay anlatımı müvekkil bilgisi içerebilir.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Awaitable, Callable
from uuid import UUID

logger = logging.getLogger(__name__)

MAX_QUESTION_CHARS = 1500
MIN_QUESTION_CHARS = 15
_JOB_TTL_SECONDS = 3600
_MAX_JOBS = 50


@dataclass(frozen=True)
class Axis:
    key: str
    title: str
    suffix: str  # soruya eklenen kısa, aranabilir ifade: arama bu sözcüklerle ilgili kaynak türüne yönelir


AXES: tuple[Axis, ...] = (
    Axis("mevzuat", "İlgili mevzuat", "kanun maddesi hüküm şartları"),
    Axis("ictihat", "Yargı kararları", "Yargıtay kararı"),
    Axis("usul", "Süre, ispat ve usul", "süre zamanaşımı ispat yükü"),
)


def plan(question: str, hints: list[dict] | None = None) -> list[tuple[Axis, str]]:
    """Soruyu eksenlere böler: her eksen için soru + kısa ek ifade.

    Konu ipucu varsa (api.statute_hints) mevzuat ekseni doğrudan o maddeyi sorar ("6098 sayılı kanun madde 315"): arama, uzun bir
    olay anlatımının sözcükleriyle madde bulamıyor ve bölüm "yeterli bilgi yok" diye boş kalıyordu (ölçüldü: 2026-10-05).
    """
    base = " ".join(question.split())[: MAX_QUESTION_CHARS - 60].rstrip(" ?.")
    steps = []
    for axis in AXES:
        if axis.key == "mevzuat" and hints:
            steps.append((axis, f"{hints[0]['law_no']} sayılı kanun madde {hints[0]['article_no']}"))
        else:
            steps.append((axis, f"{base} {axis.suffix}"))
    return steps


# --- Olay anlatımını araştırma konusuna indirgeme ---------------------------------------------------------------------------
# "Kiracı 3 aydır kirayı ödemiyor, ihtarname çektik, 30 gün geçti. Tahliye davası açarsak risklerimiz neler?" gibi bir anlatım
# aramaya olduğu gibi verilince üç eksen de boş dönüyordu. Model anlatımı tek cümlelik konuya indirger; sonuç kodla denetlenir:
# yalnız anlatımdaki sözcükler kullanılabilir (konu, süre, kanun uydurulamaz). Güvenli değilse anlatımın kendisi kullanılır.

CONDENSE_SYSTEM = (
    "Bir avukatın anlattığı olayı, hukuk kaynaklarında aranacak TEK cümlelik konuya indir. Yalnız olayda geçen kavramları kullan; "
    "yeni olgu, süre, sayı, kanun ya da madde EKLEME. Soru sorma, cevap verme, tavsiye yazma. En çok 20 sözcük. "
    'Örnek: "Kiracı 3 aydır kirayı ödemiyor, ihtarname çektik. Tahliye davası açarsak riskler neler?" -> '
    '{"topic":"Kiracının kira bedelini ödememesi nedeniyle ihtarname ve tahliye davası"}. '
    'Yalnız JSON döndür: {"topic":"..."}'
)
_CONDENSE_FREE = frozenset(
    "için icin olan olarak ilişkin iliskin hakkında nedeniyle sebebiyle halinde durumunda bakımından açısından yönünden ve ile veya "
    "davası davasında dava talebi talep hukuki sorumluluk sorumluluğu koşulları şartları sonuçları riskleri riski".split()
)
_WORDS = __import__("re").compile(r"[0-9a-zçğıöşüâîû]+")


def needs_condensing(question: str) -> bool:
    """Uzun ya da birden çok cümleli anlatım: aramaya olduğu gibi verilmez."""
    import re

    text = " ".join(question.split())
    return len(text) > 140 or len(re.findall(r"[.!?]\s+\S", text)) >= 1


def accept_topic(candidate: object, narrative: str) -> str | None:
    """Modelin önerdiği araştırma konusunu denetler; anlatımda olmayan içerik sözcüğü ya da sayı varsa reddeder."""
    if not isinstance(candidate, str):
        return None
    topic = " ".join(candidate.split()).strip(" .")
    if not 15 <= len(topic) <= 220 or "?" in topic or "[" in topic:
        return None
    fold = lambda text: text.replace("İ", "i").replace("I", "ı").lower()  # noqa: E731
    source = " ".join(_WORDS.findall(fold(narrative)))
    words = [word for word in _WORDS.findall(fold(topic)) if len(word) >= 4]
    content = [word for word in words if word not in _CONDENSE_FREE]
    if len(content) < 2:
        return None
    foreign = 0
    for word in content:
        if word.isdigit():
            if word not in source:
                return None  # anlatımda olmayan sayı (süre, madde no) eklenemez
            continue
        # Türkçe çekim kökü değiştirir ("ödemiyor" / "ödememesi"): ilk dört harf karşılaştırılır.
        if word[:4] not in source:
            foreign += 1  # "kira bedeli" gibi doğal bir eş anlatım olabilir; birden fazlası konu uydurmadır
    if foreign > 1:
        return None
    if any(number not in source for number in __import__("re").findall(r"\d+", topic)):
        return None
    return topic


@dataclass
class StepResult:
    key: str
    title: str
    question: str
    answer: str = ""
    grounded: bool = False
    citations: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    # Cevap önceki bir başlıkla aynıysa tekrar gösterilmez; neden burada yazılır (hata değildir).
    note: str | None = None

    def as_dict(self, *, with_question: bool = False) -> dict[str, Any]:
        data = {
            "key": self.key,
            "title": self.title,
            "answer": self.answer,
            "grounded": self.grounded,
            "citations": self.citations,
            "error": self.error,
            "note": self.note,
        }
        if with_question:
            data["question"] = self.question
        return data


@dataclass
class ResearchJob:
    id: UUID
    owner_id: UUID
    question: str
    state: str = "running"  # running | done | failed
    stage: str = "Plan hazırlanıyor…"
    steps: list[StepResult] = field(default_factory=list)
    total: int = len(AXES)
    error: str | None = None
    started: float = 0.0
    saved_id: UUID | None = None
    conversation_id: UUID | None = None
    # Anlatım araştırma konusuna indirgendiyse o konu (şeffaflık için raporda gösterilir).
    topic: str | None = None
    # Konu ipuçlarından gelen, resmî metniyle doğrulanmış maddeler (ilk bakılacaklar).
    hints: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "state": self.state,
            "stage": self.stage,
            "total": self.total,
            "done": len(self.steps),
            "error": self.error,
            "steps": [step.as_dict() for step in self.steps],
            "saved_id": str(self.saved_id) if self.saved_id else None,
            "topic": self.topic,
            "hints": [{"reference": hint["reference"], "source_url": hint.get("source_url")} for hint in self.hints],
        }


class JobRegistry:
    """İşlem içi iş kaydı (yalnız ilerleme). Sonuç bitince veritabanına yazılır; yeniden başlatmada kayıt gider, sonuç kalır."""

    def __init__(self) -> None:
        self._jobs: dict[UUID, ResearchJob] = {}
        self._tasks: set[asyncio.Task] = set()

    def clear(self) -> None:
        self._jobs.clear()

    def running_for(self, owner_id: UUID) -> ResearchJob | None:
        return next((job for job in self._jobs.values() if job.owner_id == owner_id and job.state == "running"), None)

    def latest_for(self, owner_id: UUID) -> ResearchJob | None:
        return max((job for job in self._jobs.values() if job.owner_id == owner_id), key=lambda job: job.started, default=None)

    def add(self, job: ResearchJob, runner: Awaitable[None]) -> None:
        job.started = monotonic()
        for key in [key for key, value in self._jobs.items() if value.state != "running" and job.started - value.started > _JOB_TTL_SECONDS]:
            del self._jobs[key]
        while len(self._jobs) >= _MAX_JOBS:
            finished = [value for value in self._jobs.values() if value.state != "running"]
            if not finished:
                break
            del self._jobs[min(finished, key=lambda value: value.started).id]
        self._jobs[job.id] = job
        task = asyncio.ensure_future(runner)
        self._tasks.add(task)  # görev referansı tutulmazsa toplayıcı işi yarıda kesebilir
        task.add_done_callback(self._tasks.discard)


registry = JobRegistry()

# (soru, sohbet kimliği) -> cevap nesnesi: `AIAnswerResponse` benzeri (answer, grounded, citations, conversation_id)
AnswerFn = Callable[[str, UUID | None], Awaitable[Any]]


def _citation_payload(citation: Any) -> dict[str, Any]:
    source_id = getattr(citation, "source_id", None)
    return {
        "marker": citation.marker,
        "source_id": str(source_id) if source_id is not None else None,
        "excerpt": getattr(citation, "excerpt", None),
        "reference": citation.reference,
        "source_url": citation.source_url,
        "verification": citation.verification,
        "source_type": citation.source_type,
    }


async def run_job(
    job: ResearchJob,
    answer: AnswerFn,
    on_done: Callable[[ResearchJob], Awaitable[None]] | None = None,
    *,
    condense: Callable[[str], Awaitable[str | None]] | None = None,
    statute_hints: Callable[[str], Awaitable[list[dict[str, Any]]]] | None = None,
) -> None:
    """Planın her eksenini sırayla çalıştırır. Bir adımın hatası yalnız o adıma yazılır; diğer adımlar sürer.

    `condense`: uzun olay anlatımını araştırma konusuna indirger (None dönerse anlatım aynen kullanılır).
    `statute_hints`: konuya göre resmî doğrulanmış madde ipuçları.
    """
    try:
        topic = job.question
        if condense is not None and needs_condensing(job.question):
            job.stage = "Olay anlatımı araştırma konusuna indirgeniyor…"
            try:
                topic = (await condense(job.question)) or job.question
            except Exception:  # noqa: BLE001 - indirgeme başarısızsa anlatımın kendisi aranır
                logger.warning("Araştırma konusu çıkarılamadı; anlatım aynen kullanılacak")
        job.topic = topic if topic != job.question else None
        if statute_hints is not None:
            try:
                job.hints = await statute_hints(job.question)
            except Exception:  # noqa: BLE001 - ipucu yoksa plan arama ile sürer
                logger.warning("Madde ipuçları alınamadı")
        steps = plan(topic, job.hints)
        seen: set[str] = set()
        for index, (axis, question) in enumerate(steps, start=1):
            job.stage = f"{index}/{len(steps)}: {axis.title} aranıyor ve yazılıyor…"
            step = StepResult(key=axis.key, title=axis.title, question=question)
            try:
                response = await answer(question, job.conversation_id)
                step.answer = response.answer
                fingerprint = " ".join(response.answer.split())
                if fingerprint in seen:
                    # Tanınan konularda (ör. kıdem tazminatı) hat her eksende aynı kanun metnini döndürebilir: tekrarlanmaz.
                    step.answer = ""
                    step.note = "Bu başlık için ayrı bir cevap bulunamadı: aynı kaynaklar önceki başlıkta sunuldu."
                    job.steps.append(step)
                    continue
                seen.add(fingerprint)
                step.grounded = bool(response.grounded)
                step.citations = [_citation_payload(citation) for citation in response.citations]
                job.conversation_id = job.conversation_id or response.conversation_id
            except Exception as exc:  # noqa: BLE001 - bir eksenin hatası diğerlerini durdurmaz
                detail = getattr(exc, "detail", None)
                step.error = str(detail) if isinstance(detail, str) and detail else "Bu başlık için cevap üretilemedi."
                if not isinstance(detail, str):
                    logger.exception("Derin araştırma adımı başarısız")
            job.steps.append(step)
        usable = [step for step in job.steps if step.answer and not step.error]
        if not usable:
            job.state = "failed"
            job.error = "Hiçbir başlık için cevap üretilemedi."
            job.stage = "Tamamlanamadı."
            return
        job.stage = "Rapor kaydediliyor…"
        if on_done is not None:
            try:
                await on_done(job)
            except Exception:  # noqa: BLE001 - kayıt başarısızsa rapor bu oturumda yine görünür
                logger.exception("Derin araştırma raporu kaydedilemedi")
        job.state = "done"
        job.stage = "Tamamlandı."
    except Exception:  # noqa: BLE001
        logger.exception("Derin araştırma işi çöktü")
        job.state = "failed"
        job.error = "Araştırma işi beklenmedik biçimde durdu."
        job.stage = "Tamamlanamadı."


# Kaynak etiketi (AGENTS.md, kullanıcı kararı 2026-10-15): resmî metinle karşılaştırılmış kayıt "Resmî metin ✓"; karşılaştırılmamış
# kayıt olumsuz ibare de ✓ de almaz (künyesiyle durur). Modele verilen kaynak metnindeki uyarı satırı ayrıdır ve aynen kalır.
_BADGE = {"official": " (Resmî metin ✓)", "user_document": " (kullanıcı belgesi)"}


def render_markdown(question: str, steps: list[StepResult], *, topic: str | None = None, hints: list[dict[str, Any]] | None = None) -> str:
    """Raporu okunur metin olarak birleştirir. Model metni eklenmez; adım cevapları kendi atıflarıyla gelir."""
    lines = [f"# Derin araştırma raporu", "", f"**Soru:** {' '.join(question.split())}", ""]
    if topic:
        lines.extend([f"**Araştırılan konu:** {topic}", ""])
    if hints:
        lines.append("**İlk bakılacak maddeler** _(konuya göre otomatik öneri; resmî metinle doğrulandı, uygunluğunu avukat kontrol etmelidir)_")
        lines.extend(f"- {hint['reference']}" for hint in hints)
        lines.append("")
    lines.append(
        "_Bu rapor yalnız JurisAI hukuk korpusundaki kaynaklara dayanır; her bölümün cevabı kendi kaynaklarına karşı doğrulanmıştır. "
        "Doktrin ve karşılaştırmalı hukuk kaynakları korpusta yoktur. Hukuki görüş yerine geçmez._"
    )
    lines.append("")
    for index, step in enumerate(steps, start=1):
        lines.append(f"## {index}. {step.title}")
        if step.error:
            lines.append(f"_Bu başlık tamamlanamadı: {step.error}_")
        elif step.note:
            lines.append(f"_{step.note}_")
        else:
            lines.append(step.answer.strip())
            if not step.grounded:
                lines.append("_Bu bölümün cevabı kaynaklarla yeterince desteklenemedi; dikkatle okuyun._")
            if step.citations:
                lines.append("")
                lines.append("**Kaynaklar**")
                lines.extend(f"- [{c['marker']}] {c['reference']}{_BADGE.get(c.get('verification'), '')}" for c in step.citations)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
