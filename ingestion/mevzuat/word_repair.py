"""Resmî PDF'ten gelen bölünmüş sözcükleri ("tarafı ndan", "Kanu nun", "ödene n") güvenle birleştirir.

PDF metin çıkarımı bazı sözcüklerin sonuna ek parçası yapıştırmadan bırakır. Burada yalnız şunlar yapılır:
  - Bölünen parça tek başına Türkçe sözcük olmayan bir ek parçasıdır (n, nun, ndan, leri, sı, yla ...).
  - Sol sözcük + parça birleşince korpusta yeterince (>= MIN_VOCAB) geçen gerçek bir sözcük oluşur.
  - Tek harfli "n" parçasından sonra gelen sözcük bir parça ya da korpusta hiç geçmeyen bir kırıntı değildir (n sonraki sözcüğe aitse
    sola birleştirilmez: "olan n umarası"); daha uzun parçalar için sonraki sözcüğe bakılmaz (zincirleme bölünmeler olur).
  - Sol sözcük + parça geçerli değilse ama parça + SAĞdaki sözcük korpusta gerçek bir sözcük oluşturuyorsa parça sağa birleşir
    ("alfabe sı rasına" -> "alfabe sırasına", "her n erede" -> "her nerede").
Hiçbir harf eklenmez ya da silinmez; yalnız tek bir boşluk kalkar (`only_spaces_removed` bunu doğrular).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from api.ai.turkish_text import lower_tr

TOKEN = re.compile(r"[^\W\d_]+")
FRAGMENTS = ("n", "nı", "ni", "nu", "nü", "yla", "yle", "nin", "nın", "nun", "nün", "ndan", "nden", "ndaki", "ndeki",
             "ları", "leri", "sı", "si", "dır", "dir", "dur", "dür")
_SPLIT = re.compile(r"\b([^\W\d_]{3,}) (" + "|".join(sorted(FRAGMENTS, key=len, reverse=True)) + r")\b(?=[\s.,;:])")
_NEXT_TOKEN = re.compile(r"\s+([^\W\d_]+)")
MIN_VOCAB = 5
# Tek başına sözcük olamayacak uzun ek parçaları için korpusta bir kez geçmesi yeter (nadir sözcükler: "mıntakaları n").
# "dur" (komut), "si" (nota) ve tek harfli "n" gerçek sözcük ya da sağdaki sözcüğün başı olabilir: sıkı eşik.
STRICT_FRAGMENTS = frozenset({"n", "dur", "dir", "dır", "dür", "si", "sı"})
MIN_VOCAB_LONG = 1
MIN_NEXT_VOCAB = 2


def build_vocabulary(texts: Iterable[str]) -> Counter:
    vocabulary: Counter = Counter()
    for text in texts:
        vocabulary.update(lower_tr(word) for word in TOKEN.findall(text))
    return vocabulary


@dataclass(frozen=True, slots=True)
class Join:
    left: str
    fragment: str
    kind: str = "suffix"  # "suffix": sol sözcüğe eklenir; "prefix": parça sağdaki sözcükle birleşir ("alfabe sı rasına")


def rejoin_split_words(text: str, vocabulary: Counter) -> tuple[str, list[Join]]:
    """(düzeltilmiş metin, yapılan birleştirmeler)."""
    joins: list[Join] = []
    pieces: list[str] = []
    position = 0
    for match in _SPLIT.finditer(text):
        if match.start() < position:
            continue
        left, fragment = match.group(1), match.group(2)
        following = _NEXT_TOKEN.match(text, match.end())
        needed = MIN_VOCAB if fragment in STRICT_FRAGMENTS else MIN_VOCAB_LONG
        if not left.isupper() and vocabulary[lower_tr(left + fragment)] >= needed:
            # Parça sol sözcüğe aittir. Tek harfli "n" sağdaki sözcüğün başı da olabilir ("olan n umarası"): sağ sözcük kırıntıysa dokunma.
            if fragment == "n" and following:
                word = lower_tr(following.group(1))
                if word in {lower_tr(f) for f in FRAGMENTS} or vocabulary[word] < MIN_NEXT_VOCAB:
                    continue
            pieces.append(text[position : match.start()] + left + fragment)
            position = match.end()
            joins.append(Join(left, fragment))
        elif following and vocabulary[lower_tr(fragment + following.group(1))] >= MIN_VOCAB and not left.isupper():
            # Parça sağdaki sözcüğe aittir: "alfabe sı rasına" -> "alfabe sırasına" (sol sözcük + parça geçerli bir sözcük değil).
            pieces.append(text[position : match.start()] + left + " " + fragment + following.group(1))
            position = following.end()
            joins.append(Join(fragment, following.group(1), "prefix"))
    if not joins:
        return text, joins
    pieces.append(text[position:])
    return "".join(pieces), joins


def only_spaces_removed(before: str, after: str) -> bool:
    """Boşluk dışında hiçbir karakter değişmedi (güvenlik denetimi)."""
    strip = re.compile(r"\s+")
    return strip.sub("", before) == strip.sub("", after)
