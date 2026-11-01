"""SSS sayfasındaki hukuki dayanakları resmî doğrulanmış korpusa karşı denetler (yalnız okur).

`web/src/lib/faq.ts` içindeki her `b("Kanun", "no", "madde", "beklenen")` girdisi için: madde korpusta resmî doğrulanmış ve
güncel olarak var mı, metni beklenen ifadeyi taşıyor mu? Sorun varsa satırı yazar ve 1 ile çıkar. Sayfaya yeni hukuki
cevap eklendiğinde ya da mevzuat güncellendiğinde çalıştırılır:

    .venv\\Scripts\\python.exe scripts\\verify_faq_sources.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ENTRY = re.compile(r'\bb\(\s*"([^"]+)"\s*,\s*"(\d+)"\s*,\s*"(\d+)"\s*,\s*"([^"]+)"\s*\)')


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    sys.stdout.reconfigure(encoding="utf-8")
    from api.db import database_connection
    from api.statute_hints import _SQL
    from api.ai.search_plan import normalize

    entries = ENTRY.findall((ROOT / "web" / "src" / "lib" / "faq.ts").read_text(encoding="utf-8"))
    if not entries:
        print("faq.ts içinde dayanak girdisi bulunamadı (biçim değişmiş olabilir).")
        return 1
    problems = 0
    with database_connection() as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        for law_name, law_no, article_no, expected in dict.fromkeys(entries):
            row = connection.execute(_SQL, {"law_no": law_no, "article_no": article_no}).fetchone()
            if row is None:
                problems += 1
                print(f"YOK      {law_no} m. {article_no} ({law_name}): korpusta resmî doğrulanmış güncel madde bulunamadı")
            elif normalize(expected) not in normalize(row["content"] or ""):
                problems += 1
                print(f"UYUŞMUYOR {law_no} m. {article_no} ({law_name}): metinde “{expected}” yok → {(row['content'] or '')[:160]!r}")
            else:
                print(f"tamam    {law_no} m. {article_no} — {' '.join(row['law_name'].split())}")
    print(f"\n{len(dict.fromkeys(entries))} dayanak denetlendi; sorunlu: {problems}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
