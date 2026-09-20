"""Üçüncü taraf veri setinden örnek al, resmî portalla karşılaştır. Veritabanına YAZMAZ.

python scripts/verify_hf_sample.py --source yargitay --n 30 --delay 8
Çıktı: data/eval/hf-verify/<source>.jsonl
"""
from __future__ import annotations
import argparse, json, random, re, sys, time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ingestion.text import html_to_text, normalize_text  # noqa: E402

DS = "mrfg/turkish-court-decisions"
MASK = re.compile(r"\[(TCKN|IBAN|KART|TELEFON|EPOSTA)\]")


def _get(url: str) -> dict:
    for attempt in range(6):
        try:
            with urlopen(Request(url, headers={"User-Agent": "nhr-verify"}), timeout=60) as r:
                return json.load(r)
        except Exception:  # noqa: BLE001
            if attempt == 5:
                raise
            time.sleep(5 * (attempt + 1))


def hf_rows(config: str, offset: int, length: int = 1) -> list[dict]:
    url = f"https://datasets-server.huggingface.co/rows?dataset={quote(DS)}&config={config}&split=train&offset={offset}&length={length}"
    return [x["row"] for x in _get(url)["rows"]]


def hf_total(config: str) -> int:
    url = f"https://datasets-server.huggingface.co/size?dataset={quote(DS)}&config={config}"
    return int(_get(url)["size"]["config"]["num_rows"])


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", MASK.sub("", s)).strip().casefold()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["yargitay", "danistay"], required=True)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--delay", type=float, default=8.0)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    if a.source == "yargitay":
        from ingestion.yargitay.portal import YargitayPortalClient as C
    else:
        from ingestion.danistay.portal import DanistayPortalClient as C
    client = C()
    total = hf_total(a.source)
    rnd = random.Random(a.seed)
    out = ROOT / "data" / "eval" / "hf-verify" / f"{a.source}.jsonl"
    done = 0
    with out.open("a", encoding="utf-8") as fh:
        while done < a.n:
            row = hf_rows(a.source, rnd.randrange(total))[0]
            rec = {"document_id": row["document_id"], "court": row["court"], "esas": row["esas_no"], "karar": row["karar_no"],
                   "tarih": row["karar_tarihi"], "hf_len": row["text_len"], "masked": row["masked_count"]}
            try:
                html = client.fetch_document_html(row["document_id"])
                if a.source == "danistay":
                    from ingestion.danistay.scraper import extract_decision_text
                    off = extract_decision_text(html)
                else:
                    off = normalize_text(html_to_text(html))
                a_, b_ = norm(row["text"]), norm(off)
                rec.update(official_len=len(off), exact=a_ == b_, contains=(a_ in b_ or b_ in a_),
                           ratio=round(min(len(a_), len(b_)) / max(len(a_), len(b_), 1), 4))
            except Exception as e:  # noqa: BLE001
                rec["error"] = str(e)[:160]
                if "CAPTCHA" in str(e).upper() or "captcha" in type(e).__name__.lower():
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n"); print("CAPTCHA; duruldu"); return 3
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n"); fh.flush()
            done += 1
            print(done, {k: rec.get(k) for k in ("exact", "contains", "ratio", "masked", "error")}, flush=True)
            time.sleep(a.delay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
