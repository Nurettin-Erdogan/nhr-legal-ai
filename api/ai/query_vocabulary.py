"""Search vocabulary only: expansions are never admissible answer evidence."""
import re

# Full-token replacements prevent e.g. TÜFE -> tüfek. The same vocabulary is
# used for lexical queries, query embeddings and passage relevance/ranking.
_TERMS = {
    "tüfe": "tüketici fiyat endeksi", "tufe": "tüketici fiyat endeksi",
    "üfe": "üretici fiyat endeksi", "ufe": "üretici fiyat endeksi",
    "sgk": "sosyal güvenlik kurumu", "kvkk": "kişisel verilerin korunması",
    "hmk": "hukuk muhakemeleri kanunu", "cmk": "ceza muhakemesi kanunu",
    "tbk": "türk borçlar kanunu", "tck": "türk ceza kanunu",
    "iik": "icra iflas kanunu", "ıik": "icra iflas kanunu", "ıık": "icra iflas kanunu",
    "aym": "anayasa mahkemesi", "aihm": "avrupa insan hakları mahkemesi",
    "kdv": "katma değer vergisi", "ötv": "özel tüketim vergisi", "otv": "özel tüketim vergisi",
}
_TOKEN = re.compile(r"\b(?:" + "|".join(map(re.escape, sorted(_TERMS, key=len, reverse=True))) + r")\b")


def expand_search_terms(text: str) -> str:
    normalized = text.replace("İ", "i").lower()
    return _TOKEN.sub(lambda match: _TERMS[match.group()], normalized)


def has_search_abbreviation(text: str) -> bool:
    return bool(_TOKEN.search(text.replace("İ", "i").lower()))


def definition_evidence_score(question: str, text: str) -> float:
    """Rank a term's explicit expansion above incidental uses; not verification."""
    q = question.replace("İ", "i").lower()
    if not re.search(r"\b(?:nedir|ne demek|ne anlama gelir)\b", q):
        return 0.0
    value = text.replace("İ", "i").lower()
    for token in _TOKEN.findall(q):
        term = _TERMS[token]
        aliases = "|".join(re.escape(alias) for alias, expansion in _TERMS.items() if expansion == term)
        # A nearby parenthesized abbreviation is an explicit source relation.
        if re.search(re.escape(term) + r"\s*\(\s*(?:" + aliases + r")\s*\)", value):
            return 20.0
    return 0.0


def standalone_definition(question: str) -> bool:
    """An explicitly named concept, never 'bu nedir' or a user's event fact."""
    q = question.replace("İ", "i").lower().strip(" ?.!\t\r\n")
    match = re.fullmatch(r"([a-zçğıöşü]+(?: [a-zçğıöşü]+){0,5}) (?:nedir|ne demek|ne anlama gelir)", q)
    if not match:
        return False
    words = match[1].split()
    references = {"bu", "bunun", "bunlar", "bunların", "o", "onun", "şu", "şunun", "aynı",
                  "önceki", "yukarıdaki", "benim", "bizim", "senin", "sizin", "bana", "bende"}
    if any(word in references for word in words):
        return False
    # Conservative: possession or a reference to an individual document/event
    # may require context. A false negative merely keeps the usual history.
    return not any(re.search(r"(?:[ıiuü]m|[ıiuü]n|[ıiuü]mız|[ıiuü]miz|daki|deki)$", word) for word in words)
