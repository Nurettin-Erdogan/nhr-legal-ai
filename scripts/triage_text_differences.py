"""Read-only: sort the article texts that differ from their official PDF into harmless noise and real content differences.

`scripts/verify_article_texts.py` lists every stored article whose text is not equal to the official PDF extract
(`.local/article_text_differences.jsonl`, 6 429 rows on 2026-11-01). Most are not wrong data: the PDF extract carries page footnotes in
the middle of an article ("2 19/5/2022 tarihli ve ... şeklinde değiştirilmiştir."), words split by a space ("belirti lir"), and the
stored text (from the portal's article HTML) carries the article's caption in front. Both texts are cleaned of captions and
footnotes, then compared character-wise on the normalised key; only what the OFFICIAL text has and the stored text lacks can mean
missing content in the stored article, so that is what is counted:

  same_after_cleaning  - nothing of the official text is missing (the stored text has all of it)
  official_cut_short   - the official extract stops early (a "Madde ..." line inside the article); the stored text is the longer one
  stored_missing       - at least 8 % (and 80 characters) of the cleaned official text is absent from the stored text: a real finding

  python scripts/triage_text_differences.py [--limit 50]
"""

import json
import re
import sys
import time
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from api.db import admin_database_connection  # noqa: E402
from ingestion.mevzuat.text_verify import _comparison_key, extract_article_text, fetch_official_pdf_text  # noqa: E402

_IN = ROOT / ".local" / "article_text_differences.jsonl"
_OUT = ROOT / ".local" / "article_text_triage.jsonl"
_PAUSE_SECONDS = 2.0
_FOOTNOTE_WORDS = re.compile(r"Resmî Gazete|Resmi Gazete|tarihli ve|sayılı|değiştirilmiştir|eklenmiştir|kaldırılmıştır|ibaresi|iptal", re.I)
_FOOTNOTE_START = re.compile(r"^\s*(?:\[\d{1,3}\]|\d{1,3})\s+\S")
_FOOTNOTE_END = re.compile(r"(?:miştir|mıştır|muştur|müştür|edilmiştir|dir|dır|dur|dür|tir|tır)\.\s*(?:\d{0,3})\s*$")
_HEADING = re.compile(r"(?im)^\s*(?:EK\s+GEÇİCİ\s+|EK\s+|GEÇİCİ\s+)?MADDE\s+\d")


def strip_footnotes(text: str) -> str:
    """Drop footnote paragraphs: a line that starts with a footnote number and mentions an amendment, up to the line that ends it."""
    lines, kept, skipping = text.split(chr(10)), [], False
    for line in lines:
        if not skipping and _FOOTNOTE_START.match(line) and _FOOTNOTE_WORDS.search(line):
            skipping = not _FOOTNOTE_END.search(line)
            continue
        if skipping:
            skipping = not _FOOTNOTE_END.search(line)
            continue
        kept.append(line)
    return chr(10).join(kept)


def without_caption(text: str) -> str:
    """The stored text starts with the article's caption lines; the official extract starts at the heading."""
    match = _HEADING.search(text)
    return text[match.start():] if match else text


def classify(stored: str, official: str) -> dict:
    a = _comparison_key(strip_footnotes(without_caption(stored)))
    b = _comparison_key(strip_footnotes(without_caption(official)))
    if not b:
        return dict(kind='official_empty')
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    missing = sum(j2 - j1 for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag in ('insert', 'replace'))
    in_stored_only = sum(i2 - i1 for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag in ('delete', 'replace'))
    result = dict(official_chars=len(b), stored_chars=len(a), official_missing_in_stored=missing, stored_not_in_official=in_stored_only)
    if missing < max(80, 0.08 * len(b)):
        result['kind'] = 'same_after_cleaning'
    elif in_stored_only >= 0.4 * len(a) and len(a) > len(b):
        result['kind'] = 'official_cut_short'
    else:
        result['kind'] = 'stored_missing'
    return result


def main() -> None:
    limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 0
    rows = [json.loads(line) for line in _IN.read_text(encoding='utf-8').splitlines() if line.strip()]
    # only articles where the stored text is not clearly longer than the official one can be missing content
    rows = [row for row in rows if row['stored_len'] <= 1.25 * max(row['official_len'], 1)]
    by_pdf: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_pdf[row['law_no']].append(row)
    done = set()
    if _OUT.exists():
        for line in _OUT.read_text(encoding='utf-8').splitlines():
            try:
                done.add(json.loads(line)['id'])
            except (ValueError, KeyError):
                continue
    print(json.dumps(dict(candidates=len(rows), documents=len(by_pdf), already=len(done)), ensure_ascii=False), flush=True)
    with admin_database_connection() as db:
        db.execute('SET TRANSACTION READ ONLY')
        db.execute("SET LOCAL statement_timeout = '120s'")
        for count, (pdf, items) in enumerate(sorted(by_pdf.items(), key=lambda kv: -len(kv[1])), 1):
            if limit and count > limit:
                break
            todo = [item for item in items if item['id'] not in done]
            if not todo:
                continue
            try:
                full = fetch_official_pdf_text('https://www.mevzuat.gov.tr/MevzuatMetin/' + pdf, timeout_seconds=60)
            except Exception as exc:  # the document cannot be fetched now; its rows stay untriaged
                print(json.dumps(dict(pdf=pdf, error=type(exc).__name__)), flush=True)
                time.sleep(_PAUSE_SECONDS)
                continue
            for item in todo:
                stored = db.execute("SELECT raw_text FROM legal_sources WHERE id = %s", (item['id'],)).fetchone()
                if not stored:
                    continue
                result = classify(stored['raw_text'] or '', extract_article_text(full, item['article']))
                result.update(id=item['id'], pdf=pdf, article=item['article'])
                with _OUT.open('a', encoding='utf-8') as file:
                    file.write(json.dumps(result, ensure_ascii=False) + chr(10))
            print(json.dumps(dict(pdf=pdf, articles=len(todo)), ensure_ascii=False), flush=True)
            time.sleep(_PAUSE_SECONDS)


if __name__ == '__main__':
    main()
