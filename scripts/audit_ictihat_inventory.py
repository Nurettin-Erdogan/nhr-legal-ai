"""muhammedturan envanterinin 2 shard'lık kalite testi. HTTP/Bedesten yok."""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingestion.hf_700k import jsonable_id, parse_case_no, parse_date_field  # noqa: E402
from ingestion.http_download import download_http  # noqa: E402

DATASET = "muhammedturan/turk-ictihat-kararlari-fulltext"
DATA_DIR = ROOT / "data" / "eval" / "ictihat-inventory"
HF = (
    "https://huggingface.co/datasets/muhammedturan/turk-ictihat-kararlari-fulltext"
    "/resolve/main/data/train-{index:05d}-of-00099.parquet"
)
SHARDS = (0, 1)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ids: list[str] = []
    parsed_esas = 0
    parsed_karar = 0
    parsed_date = 0
    has_text = 0
    text_lens: list[int] = []
    columns: Counter[str] = Counter()
    rows = 0
    for shard in SHARDS:
        dest = DATA_DIR / f"train-{shard:05d}-of-00099.parquet"
        download_http(HF.format(index=shard), dest)
        table = pq.read_table(dest)
        columns.update(table.column_names)
        n = table.num_rows
        rows += n
        id_col = table.column("document_id").to_pylist() if "document_id" in table.column_names else []
        esas = table.column("esas_no").to_pylist() if "esas_no" in table.column_names else [None] * n
        karar = table.column("karar_no").to_pylist() if "karar_no" in table.column_names else [None] * n
        tarih = table.column("karar_tarihi").to_pylist() if "karar_tarihi" in table.column_names else [None] * n
        text = table.column("text") if "text" in table.column_names else None
        lengths = pc.utf8_length(pc.fill_null(text, "")).to_pylist() if text is not None else [0] * n
        for index, raw_id in enumerate(id_col):
            ident = jsonable_id(raw_id)
            if ident:
                ids.append(ident)
            if parse_case_no(esas[index]):
                parsed_esas += 1
            if parse_case_no(karar[index]):
                parsed_karar += 1
            if parse_date_field(tarih[index]):
                parsed_date += 1
            length = int(lengths[index] or 0)
            text_lens.append(length)
            if length > 80:
                has_text += 1
    unique = len(set(ids))
    report = {
        "dataset": DATASET,
        "taken_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "shards": list(SHARDS),
        "rows": rows,
        "document_id_present": len(ids),
        "document_id_unique": unique,
        "duplicate_id_rate": round((len(ids) - unique) / max(len(ids), 1), 6),
        "esas_parse_rate": round(parsed_esas / max(rows, 1), 4),
        "karar_parse_rate": round(parsed_karar / max(rows, 1), 4),
        "date_parse_rate": round(parsed_date / max(rows, 1), 4),
        "has_fulltext_rate": round(has_text / max(rows, 1), 4),
        "fulltext_rows": has_text,
        "columns": sorted(columns),
        "sample_ids": ids[:12],
        "http_fetches": 0,
        "usable_as_inventory": unique > 0 and unique / max(len(ids), 1) > 0.99,
    }
    path = DATA_DIR / "quality_2shard.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["usable_as_inventory"]:
        raise SystemExit("envanter kalite testi başarısız")


if __name__ == "__main__":
    main()
