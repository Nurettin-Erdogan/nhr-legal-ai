from __future__ import annotations

import re
from dataclasses import dataclass

from api.ai.rag import RAGContext, uncited_claims
from api.ai.source_support import unsupported_source_claims

_MARKER_PATTERN = re.compile(r"\[\s*K\s*(\d+)\s*\]", re.IGNORECASE)
_SPACE_BEFORE_PUNCTUATION = re.compile(r"[ \t]+([.,;:!?])")
_REPEATED_SPACE = re.compile(r"[ \t]{2,}")
_FOREIGN_SCRIPT_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
_NUMERIC_CLAIM_RE = re.compile(r"(?<![\w])\d+(?:[.,]\d+)*(?![\w])")
_TRAILING_MARKERS_RE = re.compile(
    r"([.!?])[ \t]*((?:\[\s*K\s*\d+\s*\][ \t]*)+)", re.IGNORECASE
)
_INSUFFICIENT_SOURCE_RE = re.compile(
    r"(kaynak(larda|lar)?\s+((bu konuda\s+)?yeterli bilgi|yetersiz)"
    r"|yeterli kaynak (yok|bulunamadı)"
    r"|atıf (yapılamıyor|yapamadım)"
    r"|verilen kaynaklarla.{0,160}(h\u00fck\u00fcm|bilgi|sonu\u00e7).{0,60}bulunma"
    r"|verilen kaynaklar (aras\u0131nda|ile).{0,160}(do\u011frudan|direkt)"
    r".{0,100}(at\u0131f|h\u00fck\u00fcm|bilgi).{0,60}(bulunma|yap\u0131lma)"
    r"|bilgi(lerin)? eksikli\u011fi nedeniyle)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class VerifiedAnswer:
    text: str
    contexts: tuple[RAGContext, ...]
    unverified_markers: tuple[str, ...]
    unsupported_claims: tuple[str, ...] = ()
    foreign_script_detected: bool = False
    # Uzun kanun maddesi cevabının üstünde gösterilen, denetlenmiş yapay zekâ özeti (bkz. api.ai.statute_summary). Cevap metni
    # ve atıflar bundan bağımsızdır; `grounded` hesabına girmez.
    summary: tuple[str, ...] = ()

    @property
    def grounded(self) -> bool:
        return (
            bool(self.contexts)
            and not self.unverified_markers
            and not self.unsupported_claims
            and not self.foreign_script_detected
        )


def verify_answer(answer: str, contexts: list[RAGContext], *, question: str = "",
                  available_contexts: list[RAGContext] | None = None) -> VerifiedAnswer:
    """Validate extractive source support and resolve retrieved citation markers.

    The prompt tells the model to cite what it used, but nothing stops it from
    inventing a marker or citing a source it never received. Markers outside the
    retrieved range are stripped from the text so a reader never sees a reference
    that resolves to nothing, and the returned contexts are limited to the
    sources the answer actually leans on rather than everything retrieval found.
    Even a valid marker is rejected unless its complete claim matches source text.
    This is not a semantic entailment or legal-correctness guarantee.
    """
    cited: list[int] = []
    unverified: list[str] = []
    for raw_index in _MARKER_PATTERN.findall(answer):
        index = int(raw_index)
        if 1 <= index <= len(contexts):
            if index not in cited:
                cited.append(index)
        elif f"K{raw_index}" not in unverified:
            unverified.append(f"K{raw_index}")

    positions = {original: position for position, original in enumerate(cited, start=1)}

    def renumber(match: re.Match[str]) -> str:
        position = positions.get(int(match.group(1)))
        return f"[K{position}]" if position else ""

    text = _MARKER_PATTERN.sub(renumber, answer)
    if unverified:
        text = _SPACE_BEFORE_PUNCTUATION.sub(r"\1", text)
        text = _REPEATED_SPACE.sub(" ", text)

    cited_contexts = tuple(contexts[index - 1] for index in cited)
    unsupported = list(uncited_claims(text, len(cited_contexts)))
    unsupported.extend(_unsupported_numeric_claims(text, cited_contexts))
    unsupported.extend(unsupported_source_claims(text, cited_contexts))
    if question:
        from api.ai.authority import answer_uses_primary_basis
        if not answer_uses_primary_basis(question, cited_contexts,
                                         contexts if available_contexts is None else available_contexts):
            unsupported.append('Genel mevzuat yanıtı getirilen birincil mevzuat kaynağına dayanmıyor.')
    if question:
        from api.ai.relevance import document_hint, passage_relevant
        from api.ai.authority import on_statute_topic, primary_legislation_markers, topic_statute_terms
        primary = primary_legislation_markers(question, list(cited_contexts))
        related_primary = {i for i in primary if passage_relevant(question, cited_contexts[i-1].content)}
        topic = topic_statute_terms(question, list(cited_contexts))
        # A real citation is necessary, but an unrelated quotation is not an answer.
        for line in text.splitlines():
            markers = {int(i) for i in _MARKER_PATTERN.findall(line)}
            # A provision's dependent qualifications need not repeat every query
            # keyword. Exact source support above is STILL mandatory for them.
            statutory_qualification = bool(markers) and markers.issubset(related_primary)
            # Yalnız kullanıcı belgelerine atıf yapan satır, mevzuat konu kapısıyla değil belge
            # alaka kuralıyla değerlendirilir (bkz. relevance.document_passage_relevant).
            document_only = bool(markers) and all(
                1 <= m <= len(cited_contexts) and cited_contexts[m - 1].source_type == 'document'
                for m in markers
            )
            hint = ' '.join(document_hint(cited_contexts[m - 1]) for m in sorted(markers)) if document_only else ''
            # Sorunun konusunu düzenleyen resmî maddenin cümlesi soru sözcüklerini taşımayabilir; maddenin konu
            # sözcüğünü taşıyorsa alakalıdır (bkz. authority.topic_statute_terms). Kaynak-destek denetimi yine zorunludur.
            topic_statute = bool(markers) and all(
                m in topic and on_statute_topic(line, topic[m]) for m in markers
            )
            if (markers and not statutory_qualification and not topic_statute
                    and not passage_relevant(question, line, source_type='document' if document_only else None,
                                             document_hint=hint)):
                unsupported.append(line)
    return VerifiedAnswer(
        text=text.strip(),
        contexts=cited_contexts,
        unverified_markers=tuple(unverified),
        unsupported_claims=tuple(dict.fromkeys(unsupported)),
        foreign_script_detected=bool(_FOREIGN_SCRIPT_RE.search(text)),
    )


def _number_tokens(text: str) -> set[str]:
    without_markers = _MARKER_PATTERN.sub("", text)
    return {
        token.replace(".", "").replace(",", "")
        for token in _NUMERIC_CLAIM_RE.findall(without_markers)
    }


def _unsupported_numeric_claims(
    text: str, contexts: tuple[RAGContext, ...]
) -> tuple[str, ...]:
    """Reject cited sentences whose concrete numbers do not occur in their evidence."""
    normalized = _TRAILING_MARKERS_RE.sub(
        lambda match: f" {match.group(2).strip()}{match.group(1)} ", text
    )
    unsupported: list[str] = []
    for line in normalized.splitlines():
        for sentence in re.split(r"(?<=[.!?])\s+", line.strip()):
            sentence = sentence.strip()
            if not sentence:
                continue
            numbers = _number_tokens(sentence)
            if not numbers:
                continue
            markers = {
                int(raw)
                for raw in _MARKER_PATTERN.findall(sentence)
                if 1 <= int(raw) <= len(contexts)
            }
            if not markers:
                continue
            evidence = " ".join(
                f"{contexts[index - 1].reference_line} {contexts[index - 1].content}"
                for index in markers
            )
            if not numbers.issubset(_number_tokens(evidence)):
                unsupported.append(sentence)
    return tuple(unsupported)


def _claim_key(text: str) -> str:
    """Satırın yalnız sözcük dizisi: atıf işareti, noktalama ve boşluk farkları sayılmaz.

    Denetimler aynı cümleyi farklı biçimlerde bildirir (işaret yeniden numaralanır, sondaki işaret noktadan önceye alınır).
    """
    return " ".join(re.findall(r"\w+", _MARKER_PATTERN.sub(" ", text).casefold()))


def prune_rejected_lines(answer: str, verified: VerifiedAnswer) -> str | None:
    """Denetimden geçmeyen satırları taslaktan çıkarır; çıkarılacak satır yoksa ya da geriye bir şey kalmıyorsa None.

    Yalnız satır ÇIKARIR, hiçbir şey eklemez ya da değiştirmez; sonucu çağıran yeniden `verify_answer` ile doğrular. Satırla
    eşleşmeyen ret gerekçeleri (ör. "birincil mevzuat kaynağına dayanmıyor") satır çıkararak giderilemez: o durumda None döner
    ve cevap eskisi gibi reddedilir.
    """
    rejected = [key for key in (_claim_key(claim) for claim in verified.unsupported_claims) if len(key) >= 8]
    if not rejected or verified.unverified_markers or verified.foreign_script_detected:
        return None
    lines = answer.splitlines()
    cited = [line for line in lines if _MARKER_PATTERN.search(line)]
    keys = {id(line): _claim_key(line) for line in cited}
    # Her gerekçe taslaktaki bir satıra oturmalı; oturmayan gerekçe varsa sorun satır çıkararak çözülmez.
    if not all(any(reason in key for key in keys.values()) for reason in rejected):
        return None
    dropped = {id(line) for line in cited if any(reason in keys[id(line)] for reason in rejected)}
    if len(dropped) == len(cited):
        return None
    kept = [line for line in lines if id(line) not in dropped]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return text or None


def is_insufficient_source_reply(text: str) -> bool:
    compact = " ".join(text.split())
    if not compact or len(compact) > 600:
        return False
    if _MARKER_PATTERN.search(compact):
        return False
    return bool(_INSUFFICIENT_SOURCE_RE.search(compact))


def has_insufficient_source_signal(text: str) -> bool:
    """Reddedilecek karma bir taslakta kaynak yetersizliği itirafı var mı?

    Bu sonuç tek başına model metnini güvenilir yapmaz. Pipeline bu sinyali
    yalnız model metninin tamamını atıp sabit, hukuki iddia içermeyen bir
    yetersizlik mesajı göstermek için kullanır.
    """

    compact = " ".join(_MARKER_PATTERN.sub("", text).split())
    return bool(compact) and len(compact) <= 900 and bool(
        _INSUFFICIENT_SOURCE_RE.search(compact)
    )
