"""Resmî hukuk metinlerinden Türkçe karakter sözlüğü çıkarır ve doğruluğunu ölçer.

    .\\.venv\\Scripts\\python.exe scripts\\build_tr_vocabulary.py            # kur ve ölç
    .\\.venv\\Scripts\\python.exe scripts\\build_tr_vocabulary.py --eval-only # yalnız ölç

Yalnız `ingest_status = 'ready'` (resmî portalla doğrulanmış) kaynaklar okunur; hiçbir şey yazılmaz ve
korpusa veri alınmaz, yalnız sözcük sıklıkları sayılır. Kaynakların `hashtext(id) mod 10 < 8` olanları
sözlüğü kurar, `= 9` olanları ölçüm için ayrı tutulur (aynı metinle hem öğrenip hem sınamamak için).

Sonuç `api/ai/resources/tr_diacritics.json.gz` içine yazılır (bkz. api/ai/turkish_text.py).
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402

from api.ai import turkish_text  # noqa: E402
from api.ai.turkish_text import fold, follows_suffix_marker, lower_tr, restore_turkish  # noqa: E402
from api.config import get_settings  # noqa: E402

TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)
ASCII_FOLD_UPPER = str.maketrans("ÇĞİÖŞÜâîûÂÎÛ", "CGIOSUaiuAIU")
ASCII_FOLD_LOWER = str.maketrans("çğıöşü", "cgiosu")
MIN_TOTAL = 3  # bir ASCII biçim için en az bu kadar örnek
AMBIGUOUS_RATIO = 0.04  # az görülen biçim, çok görülenin en az bu oranı kadarsa belirsizdir (ise/işe)
AMBIGUOUS_MIN = 20
NEIGHBORS = 40


def ascii_text(text: str) -> str:
    return text.translate(ASCII_FOLD_UPPER).translate(ASCII_FOLD_LOWER)


def source_ids(connection, *, holdout: bool, limit: int) -> list:
    condition = "= 9" if holdout else "< 8"
    connection.execute("SELECT setseed(0.42)")  # örneklem tekrarlanabilir olsun
    return [
        row[0]
        for row in connection.execute(
            "SELECT id FROM legal_sources WHERE ingest_status = 'ready' AND deleted_at IS NULL AND is_current "
            "AND source_type IN ('court_decision', 'other', 'legislation') "
            f"AND mod(abs(hashtext(id::text)), 10) {condition} ORDER BY random() LIMIT %s",
            (limit,),
        ).fetchall()
    ]


def chunk_texts(connection, ids: list, batch: int = 100):
    for start in range(0, len(ids), batch):
        for (content,) in connection.execute(
            "SELECT content FROM legal_chunks WHERE legal_source_id = ANY(%s)", (ids[start : start + batch],)
        ).fetchall():
            yield content


def tokens_of(text: str) -> list[str | None]:
    """Küçük harfli Türkçe sözcükler; güvenilmez belirteçler None (ayraç) sayılır.

    Güvenilmez: tamamen büyük harfli (başlık/kısaltma) ve içinde ASCII büyük `I` olanlar. Metinlerde
    "Idare", "Istanbul" gibi İ'si noktasız yazılmış sözcükler çok; `I` hep `ı` sayılırsa "idare" için
    yanlış bir "ıdare" biçimi öğrenilir. Büyük `İ` (noktalı) belirsiz değildir.
    """
    result: list[str | None] = []
    for token in TOKEN.findall(text):
        if len(token) < 2 or token.isupper() or "I" in token:
            result.append(None)
        else:
            result.append(lower_tr(token))
    return result


def build(connection, sources: int) -> dict:
    ids = source_ids(connection, holdout=False, limit=sources)
    print(f"{len(ids)} kaynak okunuyor (eğitim)…")
    counts: dict[str, Counter] = defaultdict(Counter)
    corpus: list[list[str | None]] = []
    chunks = 0
    for content in chunk_texts(connection, ids):
        tokens = tokens_of(content)
        corpus.append(tokens)
        chunks += 1
        for word in tokens:
            if word:
                counts[fold(word)][word] += 1
    print(f"{chunks} parça, {sum(sum(c.values()) for c in counts.values()):,} sözcük, {len(counts):,} ASCII biçim")

    mapping: dict[str, str] = {}
    ambiguous: dict[str, dict] = {}
    for key, surfaces in counts.items():
        total = sum(surfaces.values())
        if total < MIN_TOTAL:
            continue
        best, best_count = surfaces.most_common(1)[0]
        plain = surfaces.get(key, 0)
        accented = {w: n for w, n in surfaces.items() if w != key}
        if not accented:
            continue  # yalnız ASCII biçimi görülüyor: değişecek bir şey yok
        top_accented, top_count = max(accented.items(), key=lambda item: item[1])
        if plain and min(plain, top_count) >= AMBIGUOUS_MIN and min(plain, top_count) / max(plain, top_count) >= AMBIGUOUS_RATIO:
            candidates = {key: {}} | {w: {} for w, n in accented.items() if n >= AMBIGUOUS_MIN}
            ambiguous[key] = {"default": best, "candidates": candidates}
        elif best != key:
            mapping[key] = best

    print(f"{len(mapping):,} düz eşleme, {len(ambiguous):,} belirsiz sözcük")
    # Belirsiz sözcükler için komşu sözcük istatistiği (ikinci geçiş, bellekteki metin üzerinden).
    stats = {key: {cand: {"p": Counter(), "n": Counter()} for cand in entry["candidates"]} for key, entry in ambiguous.items()}
    for tokens in corpus:
        for index, word in enumerate(tokens):
            if not word:
                continue
            key = fold(word)
            if key not in stats or word not in stats[key]:
                continue
            previous = tokens[index - 1] if index > 0 else None
            following = tokens[index + 1] if index + 1 < len(tokens) else None
            if previous:
                stats[key][word]["p"][fold(previous)] += 1
            if following:
                stats[key][word]["n"][fold(following)] += 1
    for key, entry in ambiguous.items():
        entry["candidates"] = {
            cand: {
                side: dict(counter.most_common(NEIGHBORS))
                for side, counter in stats[key][cand].items()
            }
            for cand in entry["candidates"]
        }
    return {"map": mapping, "ambiguous": ambiguous}


def write(data: dict) -> None:
    turkish_text.RESOURCE.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(turkish_text.RESOURCE, "wt", encoding="utf-8", compresslevel=9) as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    size = turkish_text.RESOURCE.stat().st_size / 1024
    print(f"yazıldı: {turkish_text.RESOURCE.relative_to(ROOT)} ({size:.0f} KB)")
    turkish_text._vocabulary.cache_clear()


# Arama `normalize` ile â/î/û'yu a/i/u'ya eşitler; şapkalı/şapkasız fark gerçek hata değildir.
CIRCUMFLEX = str.maketrans("âîû", "aiu")


def same_word(expected: str, produced: str) -> bool:
    """Üretilen sözcük beklenenle aynı mı? Büyük harfli sözcükte `I` hem `ı` hem `i` olabilir."""
    # ASCII `I` hem `ı` hem `i` olabilir ("İdare" ASCII'ye çevrilince "Idare" olur): ikisi de kabul.
    options = {lower_tr(produced), produced.lower()}
    return expected.translate(CIRCUMFLEX) in {option.translate(CIRCUMFLEX) for option in options}


def evaluate(connection, sources: int) -> None:
    """Ayrı tutulan kaynaklarda: metni ASCII'ye çevir, geri getir, orijinalle karşılaştır."""
    ids = source_ids(connection, holdout=True, limit=sources)
    accented_total = accented_right = ascii_total = ascii_changed = 0
    errors: Counter = Counter()
    false_changes: Counter = Counter()
    chunks = 0
    for content in chunk_texts(connection, ids):
        chunks += 1
        matches = list(TOKEN.finditer(content))
        original = [match.group() for match in matches]
        restored = TOKEN.findall(restore_turkish(ascii_text(content)))
        if len(original) != len(restored):
            continue  # hizalama bozulursa (beklenmez) o parça atlanır
        for match, after in zip(matches, restored):
            before = match.group()
            if len(before) < 2 or (before.isupper() and len(before) < 4) or "I" in before:
                continue  # kısaltma ve noktasız-I belirsizliği ölçüme girmez (bilinçli: bkz. tokens_of)
            if follows_suffix_marker(content, match.start()):
                continue  # kesme işareti/rakamdan sonraki ekler ("Yargıtay'ın", "30'uncu") bilinçli değişmez
            low_before = lower_tr(before)
            low_after = lower_tr(after)
            if low_before != fold(low_before):
                accented_total += 1
                if same_word(low_before, after):
                    accented_right += 1
                else:
                    errors[(low_before, low_after)] += 1
            else:
                ascii_total += 1
                if not same_word(low_before, after):
                    ascii_changed += 1
                    false_changes[(low_before, low_after)] += 1
    print(f"\nÖLÇÜM ({len(ids)} ayrı kaynak, {chunks} parça)")
    if accented_total:
        print(f"  Türkçe karakterli sözcükler : {accented_right:,}/{accented_total:,} doğru geri getirildi = %{100 * accented_right / accented_total:.2f}")
    if ascii_total:
        print(f"  Zaten ASCII olan sözcükler  : {ascii_changed:,}/{ascii_total:,} yanlışlıkla değişti = %{100 * ascii_changed / ascii_total:.3f}")
    print("  En sık yanlış geri getirmeler (orijinal -> üretilen):")
    for (before, after), n in errors.most_common(15):
        print(f"    {n:6,}  {before} -> {after}")
    print("  En sık yanlışlıkla değişen ASCII sözcükler:")
    for (before, after), n in false_changes.most_common(10):
        print(f"    {n:6,}  {before} -> {after}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=int, default=6000, help="eğitim kaynağı sayısı")
    parser.add_argument("--holdout", type=int, default=800, help="ölçüm kaynağı sayısı")
    parser.add_argument("--eval-only", action="store_true")
    args = parser.parse_args()
    url = get_settings().admin_database_url
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL tanımlı değil")
    with psycopg.connect(url) as connection:
        connection.execute("SET statement_timeout = '300s'")
        if not args.eval_only:
            write(build(connection, args.sources))
        evaluate(connection, args.holdout)


if __name__ == "__main__":
    main()
