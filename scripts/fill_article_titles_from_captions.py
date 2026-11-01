"""Preview/apply: fill the missing article captions of the laws from the captions already cut off the previous article.

The portal tree gives no caption for most articles ("Madde No: 342" is stored as the title). In the official PDF an article's caption stands
directly in front of its "MADDE" line, so it was glued to the end of the PREVIOUS article's text; `repair_next_article_captions.py` cut it
off and kept it in `metadata.caption_trim.removed` ("E. Kira bedeli\\nI. Genel olarak2" -> article 343's caption). That is official PDF
text that was already verified, so the caption of article N+1 is the last line of what was removed from article N:

  * only a caption that is empty or the "Madde No: ..." placeholder is ever replaced; a stored real caption is never touched;
  * the caption is the LAST removed line (the one directly before the article), with the footnote digit glued to its last word removed;
  * a last line that is a part/chapter heading (BÖLÜM, KISIM, AYIRIM, all capitals) is not a caption and leaves the title empty;
  * the previous values are written to a backup before anything changes.

  python scripts/fill_article_titles_from_captions.py            # preview counts and samples
  python scripts/fill_article_titles_from_captions.py --apply
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from api.ai.rag import real_article_title  # noqa: E402
from api.db import admin_database_connection  # noqa: E402

_CHAPTER = re.compile(r"(?:BİRİNCİ|İKİNCİ|ÜÇÜNCÜ|DÖRDÜNCÜ|BEŞİNCİ|ALTINCI|YEDİNCİ|SEKİZİNCİ|DOKUZUNCU|ONUNCU)\s+(?:BÖLÜM|KISIM|AYIRIM)"
                      r"|^[A-ZÇĞİÖŞÜ0-9 ,.:;()/'’\"“”-]{6,}$|^MADDE\b|^(?:GEÇİCİ|EK)\s", re.U)
_BACKUPS = ROOT / ".local" / "corpus-repair-backups"


def caption_of(removed: str) -> str | None:
    lines = [line.strip() for line in removed.split(chr(10)) if line.strip()]
    if not lines:
        return None
    last = re.sub(r"(?<=[a-zçğıöşüâîû])[0-9]{1,3}$", "", lines[-1]).strip()
    if not last or len(last) > 160 or _CHAPTER.search(last) or last.endswith(('.', ';', ':')) and len(last.split()) > 12:
        return None
    return last


def next_article(article_no: str) -> str | None:
    return str(int(article_no) + 1) if re.fullmatch(r"\d{1,5}", article_no or "") else None


def main() -> None:
    apply_requested = '--apply' in sys.argv
    now = datetime.now(timezone.utc)
    with admin_database_connection() as db:
        db.execute("SET LOCAL statement_timeout = '280s'")
        trimmed = db.execute("""SELECT d.law_no, d.article_no, s.metadata->'caption_trim'->>'removed' AS removed
            FROM legislation_details d JOIN legal_sources s ON s.id = d.legal_source_id
            WHERE d.legislation_type = 'law' AND s.is_current AND s.deleted_at IS NULL AND s.ingest_status = 'ready'
              AND jsonb_exists(s.metadata, 'caption_trim')""").fetchall()
        candidates: dict[tuple[str, str], str] = {}
        for row in trimmed:
            following, caption = next_article(row['article_no']), caption_of(row['removed'] or '')
            if following and caption:
                candidates[(row['law_no'], following)] = caption
        targets = db.execute("""SELECT d.legal_source_id, d.law_no, d.article_no, d.article_title FROM legislation_details d
            JOIN legal_sources s ON s.id = d.legal_source_id
            WHERE d.legislation_type = 'law' AND s.is_current AND s.deleted_at IS NULL AND s.ingest_status = 'ready'
              AND (d.article_title IS NULL OR d.article_title = '' OR d.article_title ~* '^Madde No:\\s*\\S+\\s*$')""").fetchall()
    updates = [(row['legal_source_id'], row['article_title'], candidates[(row['law_no'], row['article_no'])], row['law_no'], row['article_no'])
               for row in targets if (row['law_no'], row['article_no']) in candidates
               and real_article_title(row['article_title']) is None]
    print(json.dumps(dict(trimmed_articles=len(trimmed), articles_without_caption=len(targets), fillable=len(updates)), ensure_ascii=False), flush=True)
    for _id, _old, new, law, article in updates[:8]:
        print(f"   {law} m.{article}: {new!r}")
    if not apply_requested or not updates:
        return
    _BACKUPS.mkdir(parents=True, exist_ok=True)
    backup = _BACKUPS / ('article-titles-' + now.strftime('%Y%m%dT%H%M%S') + '.jsonl')
    with backup.open('x', encoding='utf-8') as file:
        for source_id, old, new, law, article in updates:
            file.write(json.dumps(dict(legal_source_id=str(source_id), law=law, article=article, previous_title=old, new_title=new),
                                  ensure_ascii=False) + chr(10))
    written = 0
    with admin_database_connection() as db:
        db.execute("SET LOCAL statement_timeout = '280s'")
        with db.transaction():
            for source_id, old, new, law, article in updates:
                written += db.execute("""UPDATE legislation_details SET article_title = %s WHERE legal_source_id = %s
                    AND (article_title IS NULL OR article_title = '' OR article_title ~* '^Madde No:\\s*\\S+\\s*$')""",
                                      (new, source_id)).rowcount
    print(json.dumps(dict(written=written, backup=str(backup)), ensure_ascii=False))


if __name__ == '__main__':
    main()
