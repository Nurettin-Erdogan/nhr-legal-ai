"""Cevapta alıntılanmayan "incelenen kaynaklar" için havuz-içi alaka süzgeci.

Arama kolları sözcük eşleşmesine dayanır; yaygın bir kelime ("ihtiyaç") alakasız kararları da
getirir ("ihtiyati haciz", trafik kazası). Sıralama puanı (`rank`) bunu ayırt etmez: alakasız bir
karar, cevapta kullanılan kararla neredeyse aynı puanı alabilir. Ayırt eden şey, sorunun HAVUZDA az
kararda geçen kelimeleridir ("tahliye"). Her soru kökü, havuzdaki kararlarda ne kadar nadir
geçiyorsa o kadar ağırlık alır (idf); bir karar, havuzun en yüksek puanının belirli bir oranını
aşıyorsa listelenir. Genel hukuk/bağlaç kelimeleri ("nedeniyle", "açılan", "dava") puanlanmaz.

Bu yalnız GÖSTERİM süzgecidir: cevabın dayanağını, doğrulamayı ve atıfları etkilemez.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from uuid import UUID

from api.ai.rag import RAGContext
from api.ai.search_plan import normalize, plan_search

# Bir karar, havuzun en yüksek puanının bu oranını geçmiyorsa listelenmez.
KEEP_SCORE_RATIO = 0.4
MIN_POOL = 4
# Her hukuk metninde bulunan ya da soruyu şekillendiren genel kelimeler (kök olarak).
_GENERIC_STEMS = frozenset(
    {
        "kanun", "madde", "sayılı", "sayili", "dava", "davac", "davalı", "karar", "mahkeme",
        "nedeniy", "nedenle", "sebebiy", "açıl", "aran", "aranır", "ilişki", "hakkın", "durumda",
        "halind", "olması", "olmas", "gerekl", "gerek", "yapıl", "yapılab", "verilir", "verilebil",
        "nelerd", "kadar", "zaman", "süre", "sonra", "önce", "dair", "ilgili", "uyarın", "gör",
    }
)


def _stems(question: str) -> set[str]:
    stems = set()
    for word in plan_search(question).text.split():
        if len(word) < 4 or word.isdigit():
            continue
        stem = word[: max(4, len(word) - 3)]
        if any(stem.startswith(generic) or generic.startswith(stem) for generic in _GENERIC_STEMS):
            continue
        stems.add(stem)
    return stems


def relevant_chunk_ids(question: str, contexts: Sequence[RAGContext]) -> set[UUID]:
    """Soruyla ilgili görünen bağlamların `chunk_id` kümesi. Emin olunamayınca hepsini korur."""
    everything = {context.chunk_id for context in contexts}
    stems = _stems(question)
    if not stems or len(contexts) < MIN_POOL:
        return everything
    texts = {context.chunk_id: normalize(context.content) for context in contexts}
    total = len(contexts)
    weight = {}
    for stem in stems:
        found = sum(stem in text for text in texts.values())
        if found:
            weight[stem] = math.log((total + 1) / (found + 0.5))
    if not weight:
        return everything
    scores = {
        chunk_id: sum(w for stem, w in weight.items() if stem in text) for chunk_id, text in texts.items()
    }
    best = max(scores.values())
    if best <= 0:
        return everything
    return {chunk_id for chunk_id, score in scores.items() if score >= KEEP_SCORE_RATIO * best}
