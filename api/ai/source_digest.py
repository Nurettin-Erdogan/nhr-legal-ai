"""Son çare cevap: model taslağı denetimden geçemediğinde bulunan doğrulanmış kaynakların metni aynen gösterilir.

Eskiden bu durum "İlgili kaynaklar bulundu ancak doğrulayamadım" ile bitiyordu ve kullanıcı elinde kaynak olduğu hâlde hiçbir şey
görmüyordu (ölçüldü: 2026-10-25, nafaka ve kira artışı soruları). Burada hiçbir hukuki iddia ÜRETİLMEZ: kaynaklar resmî doğrulanmış
kayıtlardan alınır, metin kaynaktan kesilip aynen aktarılır, her parça kendi atfıyla (K1..Kn) gelir ve yorum yapılamadığı açıkça
söylenir. Konu tablosundaki (`api.statute_hints`) maddeler öne alınır; mevzuat varsa karar metni kullanılmaz (karar parçası
çoğu zaman sorunun cevabı değildir).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from api import statute_hints
from api.ai.rag import RAGContext
from api.ai.trust import usable_as_evidence
from api.ai.verification import VerifiedAnswer

MAX_SOURCES = 3
_MAX_CHARS = 900
_NOTICE = ("Bu soruya kaynaklara dayanan bir yorum denetimden geçemedi; aşağıda soruyla en ilgili doğrulanmış kaynaklar, "
           "metinleri aynen aktarılarak gösteriliyor. Yorum için bir avukata danışın.")


def _excerpt(content: str) -> str:
    text = re.sub(r"\s+", " ", content or "").strip()
    if len(text) <= _MAX_CHARS:
        return text
    cut = text[:_MAX_CHARS]
    end = max(cut.rfind(". "), cut.rfind("; "))
    return (cut[: end + 1] if end > _MAX_CHARS // 2 else cut.rstrip()) + " …"


def _label(context: RAGContext) -> str:
    if context.source_type == "legislation" and context.law_name and context.article_no:
        return f"{' '.join(context.law_name.split())} m. {context.article_no}"
    return context.title


def build_source_digest(contexts: Sequence[RAGContext], question: str) -> VerifiedAnswer | None:
    usable = [c for c in contexts if usable_as_evidence(c) and c.verification == "official" and (c.content or "").strip()]
    laws = [c for c in usable if c.source_type == "legislation"]
    pool = laws or [c for c in usable if c.source_type == "court_decision"]
    if not pool:
        return None
    topic = {(h.law_no, h.article_no) for h in statute_hints.suggest(question)}
    pool.sort(key=lambda c: (c.law_no, str(c.article_no)) not in topic)
    chosen: list[RAGContext] = []
    seen: set = set()
    for context in pool:
        key = (context.source_id, context.chunk_index) if context.source_type != "legislation" else (context.law_no, context.article_no)
        if key in seen:
            continue
        seen.add(key)
        chosen.append(context)
        if len(chosen) == MAX_SOURCES:
            break
    parts = [f"{_label(context)}: “{_excerpt(context.content)}” [K{index}]" for index, context in enumerate(chosen, 1)]
    return VerifiedAnswer(text=_NOTICE + "\n\n" + "\n\n".join(parts), contexts=tuple(chosen), unverified_markers=(),
                          answer_kind="legal")
