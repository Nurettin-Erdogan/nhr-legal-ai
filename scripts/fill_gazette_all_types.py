"""Preview/apply: fill the empty Official Gazette fields (and the law identity) of KHK, regulations, communiqués and other documents.

`sync_laws_from_portal.py --fill` did this for the laws. The other document types are matched through their own stored portal link
(number, type, series) against the portal's list of that type, so a number that two types share is never mixed up. A value that is
already stored is never changed; the acceptance date goes into `metadata.law_identity` like for the laws.

  python scripts/fill_gazette_all_types.py            # preview counts
  python scripts/fill_gazette_all_types.py --apply
"""

import importlib.util
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from psycopg.types.json import Jsonb  # noqa: E402

from api.db import admin_database_connection  # noqa: E402

spec = importlib.util.spec_from_file_location("imp", ROOT / "scripts" / "import_new_documents_from_portal.py")
imp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(imp)

_TURS = (2, 4, 7, 8, 9, 19, 20, 21)
_LINK = re.compile(r"MevzuatNo=(\d+)&MevzuatTur=(\d+)&MevzuatTertip=(\d+)", re.I)
_PDF = re.compile(r"MevzuatMetin/(\d+)\.(\d+)\.(\d+)\.", re.I)


def triple(url: str):
    match = _LINK.search(url or '')
    if match:
        return match.group(1), int(match.group(2)), match.group(3)
    match = _PDF.search(url or '')
    return (match.group(3), int(match.group(1)), match.group(2)) if match else None


def main() -> None:
    apply_requested = '--apply' in sys.argv
    client = imp.mbs.MbsClient(timeout_seconds=40, max_retries=2)
    portal: dict[tuple[str, int, str], dict] = {}
    for tur in _TURS:
        for item in imp.listing(client, tur):
            key = imp.key_of(item)
            if key and key[1] == tur:
                portal[key] = item
    print(json.dumps(dict(portal_entries=len(portal))), flush=True)
    with admin_database_connection() as db:
        db.execute('SET TRANSACTION READ ONLY')
        db.execute("SET LOCAL statement_timeout = '280s'")
        rows = db.execute("""SELECT d.legal_source_id AS id, s.source_url, d.official_gazette_date IS NULL AS no_date,
                (d.official_gazette_no IS NULL OR d.official_gazette_no = '') AS no_number, NOT jsonb_exists(s.metadata, 'law_identity') AS no_identity
            FROM legislation_details d JOIN legal_sources s ON s.id = d.legal_source_id
            WHERE d.legislation_type NOT IN ('law', 'constitution') AND s.deleted_at IS NULL AND s.source_type = 'legislation'
              AND (d.official_gazette_date IS NULL OR d.official_gazette_no IS NULL OR d.official_gazette_no = ''
                   OR NOT jsonb_exists(s.metadata, 'law_identity'))""").fetchall()
    groups: dict[tuple, list] = defaultdict(list)
    counts: Counter = Counter()
    for row in rows:
        key = triple(row['source_url'])
        if key is None or key not in portal:
            counts['not_in_portal_list'] += 1
            continue
        groups[key].append(row)
    print(json.dumps(dict(rows_missing_something=len(rows), documents=len(groups), unmatched_rows=counts['not_in_portal_list'])), flush=True)
    if not apply_requested:
        return
    now = datetime.now(timezone.utc).isoformat()
    updated_columns = updated_metadata = 0
    for key, items in groups.items():
        entry = portal[key]
        gazette_date, accepted = imp._date(entry.get('resmiGazeteTarihi')), imp._date(entry.get('kabulTarih'))
        gazette_no = str(entry.get('resmiGazeteSayisi') or '').strip() or None
        identity = {'accepted': accepted.isoformat() if accepted else None, 'gazette_date': gazette_date.isoformat() if gazette_date else None,
                    'gazette_no': gazette_no, 'source': 'mbs_list', 'checked_at': now}
        ids = [row['id'] for row in items]
        with admin_database_connection() as db:
            db.execute("SET LOCAL statement_timeout = '120s'")
            with db.transaction():
                updated_columns += db.execute("""UPDATE legislation_details SET
                        official_gazette_date = COALESCE(official_gazette_date, %s),
                        official_gazette_no = CASE WHEN official_gazette_no IS NULL OR official_gazette_no = '' THEN %s ELSE official_gazette_no END
                    WHERE legal_source_id = ANY(%s) AND (official_gazette_date IS NULL OR official_gazette_no IS NULL OR official_gazette_no = '')""",
                                              (gazette_date, gazette_no, ids)).rowcount
                updated_metadata += db.execute("""UPDATE legal_sources SET metadata = metadata || jsonb_build_object('law_identity', %s::jsonb)
                    WHERE id = ANY(%s) AND NOT jsonb_exists(metadata, 'law_identity')""", (Jsonb(identity), ids)).rowcount
    print(json.dumps(dict(detail_rows_updated=updated_columns, source_rows_updated=updated_metadata)), flush=True)


if __name__ == '__main__':
    main()
