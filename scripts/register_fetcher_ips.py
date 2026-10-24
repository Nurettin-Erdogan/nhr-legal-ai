"""Yeniden başlatılan çekici sunucuların YENİ IP'lerini dağıtıcı listesine işler (AWS durdur-başlat IP'yi değiştirir).

  python scripts/register_fetcher_ips.py < tablo.txt      # satırlar: "<Name> ... <IPv4>" (Codex tablosu yapıştırılır)

Ad eşlemesi: nhr-fetcher-aws -> aws; nhr-aws2..30 -> aws2..aws30; nhr-aws31..50 -> n31..n50; nhr-embed11..50 -> m11..m50.
`data/campaign/fetcher-stopped.txt` içinden çıkarılır. Sonra: .local/allnodes2.txt yenilenir.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUB = ROOT / "scripts" / "fetcher_hub.py"
STOPPED = ROOT / "data" / "campaign" / "fetcher-stopped.txt"


def hub_name(name: str) -> str | None:
    if name == "nhr-fetcher-aws":
        return "aws"
    m = re.fullmatch(r"nhr-aws(\d+)", name)
    if m:
        n = int(m.group(1))
        return f"aws{n}" if 2 <= n <= 30 else (f"n{n}" if 31 <= n <= 50 else None)
    m = re.fullmatch(r"nhr-embed(\d+)", name)
    if m and 11 <= int(m.group(1)) <= 50:
        return f"m{int(m.group(1))}"
    return None


def main() -> int:
    text = HUB.read_text(encoding="utf-8")
    updated, unmatched, seen = [], [], set()
    for line in sys.stdin.read().splitlines():
        name = re.search(r"\b(nhr-[a-z]+-?[a-z]*\d*)\b", line)
        ip = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", line)
        if not name or not ip:
            continue
        node = hub_name(name.group(1))
        if node is None:
            unmatched.append(name.group(1))
            continue
        pattern = re.compile(r'("%s": \{"host": "ubuntu@)[0-9.]+(")' % re.escape(node))
        text, count = pattern.subn(r"\g<1>%s\g<2>" % ip.group(1), text)
        if count:
            updated.append((node, ip.group(1)))
            seen.add(node)
        else:
            unmatched.append(f"{name.group(1)} (listede yok)")
    HUB.write_text(text, encoding="utf-8")
    stopped = [l.strip() for l in STOPPED.read_text(encoding="utf-8").splitlines() if l.strip()] if STOPPED.exists() else []
    STOPPED.write_text("".join(f"{n}\n" for n in stopped if n not in seen), encoding="utf-8")
    print(f"güncellenen: {len(updated)} | durdurulmuş listede kalan: {len(stopped) - len(seen)} | eşleşmeyen: {unmatched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
