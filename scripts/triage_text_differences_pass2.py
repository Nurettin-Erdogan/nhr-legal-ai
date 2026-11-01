"""Read-only, pass 2: of the `stored_missing` candidates, which really lack a paragraph of the official article?

`triage_text_differences.py` calls an article `stored_missing` when 8 % of the cleaned official text is absent from the stored text.
Reading a sample showed that most of those are not content: change-table titles at the end of the last article ("...YÜRÜRLÜĞE GİRİŞ
TARİHLERİNİ GÖSTEREN ÇİZELGE"), section captions ("DÖRDÜNCÜ KISIM"), footnote text, the article's caption repeated. This pass lists the
official LINES the stored text lacks, drops those kinds, and keeps an article only when what remains is a real paragraph:

  * a line that starts like a paragraph or list item ("(2) ", "a) ", "(25) (Ek:RG-...)") or is a full sentence ending in a full stop,
  * at least 60 characters of such lines together,
  * and the stored text is (almost) a subset of the official one, so refreshing would only ADD official text, never remove any.

Output: `.local/article_text_real_missing.jsonl` with the missing lines, for review before anything is written.
"""

import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
import importlib.util  # noqa: E402

from api.db import admin_database_connection  # noqa: E402
from ingestion.mevzuat.text_verify import _comparison_key, extract_article_text, fetch_official_pdf_text  # noqa: E402

spec = importlib.util.spec_from_file_location("tri", ROOT / "scripts" / "triage_text_differences.py")
tri = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tri)

_IN = ROOT / ".local" / "article_text_triage.jsonl"
_OUT = ROOT / ".local" / "article_text_real_missing.jsonl"
_PAUSE_SECONDS = 2.0
_PARAGRAPH_START = re.compile(r"^\s*(?:\(\d{1,3}\)|[a-zçğıöşü]\)|[0-9]{1,2}\.|\([A-Za-z]\)|\(Ek:|\(Değişik)")
_FOOTNOTE_LINE = re.compile(r"ibaresi|ibareleri|yürürlükten kaldırılmıştır|değiştirilmiştir|eklenmiştir|teselsül|metne işlendiği|Resmî Gazete", re.I)
_TABLE_OR_CAPTION = re.compile(r"ÇİZELGE|TABLO|LİSTE|^[A-ZÇĞİÖŞÜ0-9 ,.:;()/'’\"“”-]{12,}$|(?:BİRİNCİ|İKİNCİ|ÜÇÜNCÜ|DÖRDÜNCÜ|BEŞİNCİ|ALTINCI|YEDİNCİ|SEKİZİNCİ|DOKUZUNCU|ONUNCU)\s+(?:KISIM|BÖLÜM)")


def real_missing_lines(stored: str, official: str) -> tuple[list[str], float]:
    stored_clean = tri.strip_footnotes(tri.without_caption(stored))
    official_clean = tri.strip_footnotes(tri.without_caption(official))
    stored_key = _comparison_key(stored_clean)
    kept = []
    for raw in official_clean.split(chr(10)):
        line = raw.strip()
        key = _comparison_key(line)
        if len(key) < 25 or key in stored_key:
            continue
        if _TABLE_OR_CAPTION.search(line) or (_FOOTNOTE_LINE.search(line) and not _PARAGRAPH_START.match(line)):
            continue
        if _PARAGRAPH_START.match(line) or (line.endswith('.') and len(line) >= 60):
            kept.append(line)
    official_key = _comparison_key(official_clean)
    # share of the stored text that the official text lacks: a refresh must not remove stored content
    from difflib import SequenceMatcher
    matched = sum(block.size for block in SequenceMatcher(None, stored_key, official_key, autojunk=False).get_matching_blocks())
    return kept, 1 - matched / max(len(stored_key), 1)


def main() -> None:
    rows = [json.loads(line) for line in _IN.read_text(encoding='utf-8').splitlines() if line.strip()]
    candidates = [row for row in rows if row['kind'] == 'stored_missing']
    by_pdf: dict[str, list[dict]] = defaultdict(list)
    for row in candidates:
        by_pdf[row['pdf']].append(row)
    done = set()
    if _OUT.exists():
        for line in _OUT.read_text(encoding='utf-8').splitlines():
            try:
                done.add(json.loads(line)['id'])
            except (ValueError, KeyError):
                continue
    print(json.dumps(dict(candidates=len(candidates), documents=len(by_pdf), already=len(done)), ensure_ascii=False), flush=True)
    with admin_database_connection() as db:
        db.execute('SET TRANSACTION READ ONLY')
        db.execute("SET LOCAL statement_timeout = '120s'")
        for pdf, items in sorted(by_pdf.items(), key=lambda kv: -len(kv[1])):
            todo = [item for item in items if item['id'] not in done]
            if not todo:
                continue
            try:
                full = fetch_official_pdf_text('https://www.mevzuat.gov.tr/MevzuatMetin/' + pdf, timeout_seconds=60)
            except Exception as exc:
                print(json.dumps(dict(pdf=pdf, error=type(exc).__name__)), flush=True)
                time.sleep(_PAUSE_SECONDS)
                continue
            real = 0
            for item in todo:
                stored = db.execute("SELECT raw_text FROM legal_sources WHERE id = %s", (item['id'],)).fetchone()
                if not stored:
                    continue
                lines, stored_not_in_official = real_missing_lines(stored['raw_text'] or '', extract_article_text(full, item['article']))
                verdict = 'real_missing_paragraph' if sum(len(x) for x in lines) >= 60 and stored_not_in_official <= 0.05 else 'noise'
                real += verdict == 'real_missing_paragraph'
                with _OUT.open('a', encoding='utf-8') as file:
                    file.write(json.dumps(dict(id=item['id'], pdf=pdf, article=item['article'], verdict=verdict,
                                               stored_not_in_official=round(stored_not_in_official, 3), lines=lines[:6]),
                                          ensure_ascii=False) + chr(10))
            print(json.dumps(dict(pdf=pdf, candidates=len(todo), real=real), ensure_ascii=False), flush=True)
            time.sleep(_PAUSE_SECONDS)


if __name__ == '__main__':
    main()
