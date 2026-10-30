"""Read-only public corpus audit. No provider calls, ingestion or DB writes."""
from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.db import database_connection
from api.legal import _VERIFIED_SOURCE_FILTER
from ingestion.text import content_hash

ROOT = Path(__file__).resolve().parents[1]

HEADING = re.compile(
    r"(?im)^[ \t]*(?:(EK|GEÇİCİ|GECICI)\s+)?MADDE\s+"
    r"(\d+(?:\s*/\s*[A-ZÇĞİÖŞÜ]+|[A-Z])?)(?=\s|[-–—.:\[])"
)


def heading_identity(prefix: str | None, number: str) -> str:
    prefix = (prefix or "").upper().replace("GECICI", "GEÇİCİ").replace("GEÇICI", "GEÇİCİ")
    return ((prefix + " ") if prefix else "") + re.sub(r"\s+", "", number.upper())


def stored_identity(value: str) -> str:
    value = value.upper().replace("GECICI", "GEÇİCİ").replace("GEÇICI", "GEÇİCİ").replace("MADDE", "")
    return re.sub(r"\s+", " ", value).strip().replace(" /", "/").replace("/ ", "/")


def audit() -> dict:
    counts = Counter()
    examples = defaultdict(list)
    lineages = defaultdict(set)
    current = Counter()
    laws = set()
    def note(kind, row, **extra):
        counts[kind] += 1
        if len(examples[kind]) < 30:
            examples[kind].append({"id": str(row["id"]), "law_no": row["law_no"],
                "type": row["legislation_type"], "stored_article": row["article_no"],
                "visible": row["visible"], **extra})

    with database_connection() as db:
        db.execute("SET TRANSACTION READ ONLY")
        db.execute("SET LOCAL statement_timeout = '15s'")
        db.execute("SET LOCAL lock_timeout = '2s'")
        with db.cursor(name="public_legislation_integrity_audit") as cursor:
            cursor.itersize = 250
            cursor.execute(f"""SELECT ls.id,ls.raw_text,ls.content_hash,ls.is_current,
                ls.ingest_status,d.law_no,d.article_no,d.legislation_type,
                ({_VERIFIED_SOURCE_FILTER}) AS visible
                FROM legislation_details d JOIN legal_sources ls ON ls.id=d.legal_source_id
                WHERE ls.deleted_at IS NULL""")
            for row in cursor:
                counts["rows_including_historical"] += 1
                text = row["raw_text"] or ""
                matches = list(HEADING.finditer(text))
                key = (row["legislation_type"], row["law_no"], row["article_no"])
                if matches:
                    first = heading_identity(*matches[0].groups())
                    lineages[key].add(first)
                if not row["is_current"]:
                    continue
                counts["current_rows"] += 1
                counts["current_visible_rows"] += bool(row["visible"])
                laws.add((row["legislation_type"], row["law_no"]))
                current[key] += 1
                if not text.strip():
                    note("empty_current_text", row)
                if row["content_hash"] != content_hash(text):
                    note("current_hash_mismatch", row)
                if not matches:
                    note("current_no_recognized_heading_candidate", row)
                    continue
                if first != stored_identity(row["article_no"]):
                    note("current_first_heading_mismatch", row, heading=first)
                others = sorted({heading_identity(*m.groups()) for m in matches[1:]} - {first})
                if others:
                    note("current_embedded_other_headings_candidate", row,
                         heading=first, embedded=others[:15])
    counts["current_type_law_pairs"] = len(laws)
    collisions = [{"type": k[0], "law_no": k[1], "stored_article": k[2],
                   "distinct_headings": sorted(v)} for k, v in lineages.items() if len(v) > 1]
    duplicates = [{"type": k[0], "law_no": k[1], "article": k[2], "rows": v}
                  for k, v in current.items() if v > 1]
    counts["lineages_with_distinct_heading_identities_candidate"] = len(collisions)
    counts["duplicate_current_type_law_article_keys"] = len(duplicates)
    return {"scope": "nondeleted public legislation only; no decisions or private data",
            "read_only": True, "counts": dict(counts), "examples": dict(examples),
            "lineage_identity_candidates": collisions[:100], "duplicate_keys": duplicates[:30],
            "caveat": "Embedded headings may be quoted amendments; candidates require inspection. "
                      "Absence of a record does not prove absence from official law. "
                      "Visibility flag alone does not validate article identity."}


if __name__ == "__main__":
    result = audit()
    output = ROOT / ".local/legislation-integrity-20261026.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["counts"], ensure_ascii=False))
    print("Public-corpus audit report:", output)
