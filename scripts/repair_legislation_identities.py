"""Dry-run by default. Split unambiguous lettered article aliases in place.

Never changes source/chunk ids, text, hashes, embeddings or revision snapshots.
Apply requires the exact preview digest and writes an exclusive public-data backup
before the transaction commits. Mixed/prefixed/uncertain text is not repaired.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from psycopg.types.json import Jsonb
from ingestion.mevzuat.identity import article_headings

ROOT = Path(__file__).resolve().parents[1]


def digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


def build_plan(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["details"]["legislation_identity_id"]].append(row)
    changes, skipped = [], []
    for gid, group in groups.items():
        group.sort(key=lambda r: r["source"]["revision"])
        old = group[0]["details"]["article_no"]
        buckets = defaultdict(list)
        reason = None
        for row in group:
            source, detail = row["source"], row["details"]
            headings = article_headings(source["raw_text"] or "")
            if (not re.fullmatch(r"\d+", old) or detail["article_no"] != old
                    or len(headings) != 1 or headings[0].start >= 300
                    or not re.fullmatch(re.escape(old) + r"(?:(?:/)?[A-ZÇĞİÖŞÜ])?", headings[0].identity)
                    or not (source["external_id"] or "").endswith(":m." + old)):
                reason = "ambiguous_heading_or_identity"
                break
            buckets[headings[0].identity].append(row)
        if not reason and not any(k != old for k in buckets):
            continue
        if not reason and any(v[-1]["source"]["effective_to"] is not None for v in buckets.values()):
            reason = "effective_end_requires_review"
        if reason:
            skipped.append({"identity_id": gid, "reason": reason})
            continue
        for article, partition in buckets.items():
            for index, row in enumerate(partition):
                source, detail = row["source"], row["details"]
                changes.append({"id": source["id"], "old_identity_id": gid,
                    "law_no": detail["law_no"], "type": detail["legislation_type"],
                    "old_article": old, "article": article,
                    "external_id": source["external_id"].rsplit(":m.", 1)[0] + ":m." + article,
                    "is_current": index == len(partition)-1,
                    "superseded_by_id": partition[index+1]["source"]["id"] if index+1 < len(partition) else None})
    return {"changes": changes, "skipped": skipped, "digest": digest(rows)}


def load_rows(db):
    candidates = set()
    with db.cursor(name="repair_identity_scan") as cursor:
        cursor.itersize = 250
        cursor.execute("""SELECT d.legislation_identity_id,d.article_no,s.raw_text
          FROM legislation_details d JOIN legal_sources s ON s.id=d.legal_source_id
          WHERE s.deleted_at IS NULL AND d.article_no ~ '^[0-9]+$'""")
        for row in cursor:
            heads = article_headings(row["raw_text"] or "")
            if heads and heads[0].start < 300 and re.fullmatch(
                    re.escape(row["article_no"]) + r"(?:/)?[A-ZÇĞİÖŞÜ]", heads[0].identity):
                candidates.add(row["legislation_identity_id"])
    if not candidates:
        return []
    rows = db.execute("""SELECT to_jsonb(s) AS source,to_jsonb(d) AS details
        FROM legislation_details d JOIN legal_sources s ON s.id=d.legal_source_id
        WHERE d.legislation_identity_id=ANY(%s) AND s.deleted_at IS NULL
        ORDER BY d.legislation_identity_id,s.revision,s.id""", (list(candidates),)).fetchall()
    # No merging with independently existing correct identities is inferred.
    conflicts = set()
    for change in build_plan(rows)["changes"]:
        if db.execute("""SELECT 1 FROM legislation_details
            WHERE legislation_type=%s AND law_no=%s AND article_no=%s
              AND legislation_identity_id<>%s LIMIT 1""",
            (change["type"],change["law_no"],change["article"],change["old_identity_id"])).fetchone():
            conflicts.add(change["old_identity_id"])
    if conflicts:
        raise RuntimeError("Conflicting existing canonical identities; manual review required")
    return rows


def apply_plan(db, rows, expected_digest, backup):
    plan = build_plan(rows)
    if expected_digest != plan["digest"]:
        raise RuntimeError("Preview digest changed; no writes allowed")
    changes = plan["changes"]
    ids = [c["id"] for c in changes]
    if not ids:
        return 0
    group_ids = list({c["old_identity_id"] for c in changes})
    db.execute("SELECT id FROM legislation_identities WHERE id=ANY(%s::uuid[]) FOR UPDATE", (group_ids,))
    members = db.execute("""SELECT legal_source_id FROM legislation_details
        WHERE legislation_identity_id=ANY(%s::uuid[])""", (group_ids,)).fetchall()
    if {str(r["legal_source_id"]) for r in members} != set(ids):
        raise RuntimeError("Identity membership changed; fresh preview required")
    # Lock and compare every affected row, not just its hash. Concurrent ingestion
    # must cause a fresh preview rather than overwriting new state.
    db.execute("SELECT id FROM legal_sources WHERE id=ANY(%s::uuid[]) FOR UPDATE", (ids,))
    db.execute("SELECT legal_source_id FROM legislation_details WHERE legal_source_id=ANY(%s::uuid[]) FOR UPDATE", (ids,))
    locked = db.execute("""SELECT to_jsonb(s) AS source,to_jsonb(d) AS details
        FROM legislation_details d JOIN legal_sources s ON s.id=d.legal_source_id
        WHERE s.id=ANY(%s::uuid[])""", (ids,)).fetchall()
    before = {r["source"]["id"]:r for r in rows if r["source"]["id"] in ids}
    if {r["source"]["id"]:r for r in locked} != before:
        raise RuntimeError("Concurrent corpus change; transaction aborted")
    citations = db.execute("""SELECT c.id,c.source_title FROM citations c
        JOIN legal_chunks k ON k.id=c.legal_chunk_id WHERE k.legal_source_id=ANY(%s::uuid[])""", (ids,)).fetchall()
    backup.parent.mkdir(parents=True, exist_ok=True)
    with backup.open("x", encoding="utf-8") as file:
        json.dump({"plan":plan,"before":locked,"citation_titles":citations}, file,
                  ensure_ascii=False,indent=2,default=str)
        file.flush()
        import os
        os.fsync(file.fileno())
    chunk_before = db.execute("""SELECT id,legal_source_id,content_hash FROM legal_chunks
        WHERE legal_source_id=ANY(%s::uuid[]) ORDER BY id""", (ids,)).fetchall()
    db.execute("UPDATE legal_sources SET is_current=false WHERE id=ANY(%s::uuid[])", (ids,))
    for change in changes:
        source, detail = before[change["id"]]["source"], before[change["id"]]["details"]
        db.execute("""INSERT INTO legislation_identities(legislation_type,law_no,article_no,canonical_name)
            VALUES(%s,%s,%s,%s) ON CONFLICT(legislation_type,law_no,article_no) DO NOTHING""",
            (change["type"],change["law_no"],change["article"],detail["law_name"]))
        identity = db.execute("""SELECT id FROM legislation_identities
            WHERE legislation_type=%s AND law_no=%s AND article_no=%s""",
            (change["type"],change["law_no"],change["article"])).fetchone()["id"]
        title = re.sub(r"(\bm\.\s*)" + re.escape(change["old_article"]) + r"(?=\s|$)",
                       lambda m:m[1]+change["article"], source["title"], count=1)
        db.execute("""UPDATE legislation_details SET article_no=%s,legislation_identity_id=%s
            WHERE legal_source_id=%s""", (change["article"],identity,change["id"]))
        db.execute("""UPDATE legal_sources SET external_id=%s,title=%s,superseded_by_id=%s,
            metadata=metadata || %s WHERE id=%s""",
            (change["external_id"],title,change["superseded_by_id"],Jsonb({"article_identity_repair":{
                "preview_digest":expected_digest,"previous_article":change["old_article"],
                "canonical_article":change["article"]}}),change["id"]))
        if title != source["title"]:
            db.execute("""UPDATE citations SET source_title=%s WHERE source_title=%s
                AND legal_chunk_id IN (SELECT id FROM legal_chunks WHERE legal_source_id=%s)""",
                (title,source["title"],change["id"]))
    for change in changes:
        if change["is_current"]:
            db.execute("UPDATE legal_sources SET is_current=true WHERE id=%s", (change["id"],))
    chunk_after = db.execute("""SELECT id,legal_source_id,content_hash FROM legal_chunks
        WHERE legal_source_id=ANY(%s::uuid[]) ORDER BY id""", (ids,)).fetchall()
    if chunk_before != chunk_after:
        raise RuntimeError("Chunk identity changed; rolling back")
    db.execute("SET CONSTRAINTS ALL IMMEDIATE")
    return len(changes)


def main():
    from api.db import admin_database_connection
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-digest")
    args = parser.parse_args()
    with admin_database_connection() as db:
        if not args.apply:
            db.execute("SET TRANSACTION READ ONLY")
        db.execute("SET LOCAL statement_timeout='20s'")
        db.execute("SET LOCAL lock_timeout='2s'")
        rows = load_rows(db)
        plan = build_plan(rows)
        print(json.dumps(plan,ensure_ascii=False,default=str,indent=2))
        if args.apply:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup = ROOT / '.local/corpus-repair-backups' / f'identity-{stamp}.json'
            count = apply_plan(db,rows,args.expected_digest,backup)
            print(f"Repaired source rows: {count}; backup: {backup}")


if __name__ == '__main__':
    main()
