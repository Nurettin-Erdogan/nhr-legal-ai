"""Dış veri çekme ilerleme tablosu: 7 kaynak, son turdan bu yana artış ve kalan.

  python scripts/collection_table.py [--interval 300]   # sürekli; her turda bir tablo yazar
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# 2026-09-20 18:33 (doğrulayıcılar durdurulduğunda) resmî sayılar; bundan sonraki artış = yeni çekilen.
BASE = {"yargitay": 9489, "danistay": 10027}
# Kapsam raporunun (portal toplamı - bizde) sonucu: çekilmesi gereken eksik karar sayısı.
MISSING0 = {"yargitay": 9_984_824 - 9_814_158, "danistay": 412_162 - 383_016}
PORTAL = {"kdk": 16_065, "aym": 15_794}
MEVZUAT_PORTAL_DOCS = 917 + 63 + 56 + 110 + 172 + 186 + 5011 + 4361 + 29
STATE = ROOT / "data" / "campaign" / "table-prev.json"
HISTORY = ROOT / "data" / "campaign" / "progress-history.jsonl"
CHART = ROOT / "data" / "campaign" / "progress.html"


def stats() -> dict:
    with urllib.request.urlopen("http://127.0.0.1:8766/api/legal/stats", timeout=15) as r:
        return json.load(r)


_MEVZUAT_DOCS_CACHE = ROOT / "data" / "campaign" / "mevzuat-docs-cache.json"


def mevzuat_docs() -> int:
    """Belge sayısı ağır bir sorgu (tüm mevzuat üzerinde DISTINCT); yükte işçileri zaman aşımına uğratıyordu,
    bu yüzden 30 dakikada bir hesaplanır, arada önbellekten okunur."""
    try:
        cached = json.loads(_MEVZUAT_DOCS_CACHE.read_text(encoding="utf-8"))
        if time.time() - cached["ts"] < 1800:
            return int(cached["n"])
    except (OSError, ValueError, KeyError):
        cached = None
    try:
        with psycopg.connect(os.environ["DATABASE_ADMIN_URL"]) as c:
            c.execute("SET default_transaction_read_only=on")
            c.execute("SET statement_timeout='60s'")
            n = c.execute(
                "SELECT count(DISTINCT metadata->>'mevzuat_id') FROM legal_sources WHERE source_type='legislation'"
            ).fetchone()[0]
    except psycopg.Error:
        if cached:
            return int(cached["n"])
        raise
    _MEVZUAT_DOCS_CACHE.write_text(json.dumps({"ts": time.time(), "n": n}), encoding="utf-8")
    return n


def new_sources() -> dict[str, int]:
    """Sayıştay ve Uyuşmazlık kayıtları (source_type='other': küçük küme) + İstinaf aktarım ilerlemesi."""
    counts = {"sayistay": 0, "uyusmazlik": 0, "rekabet": 0, "emsal_seen": 0}
    with psycopg.connect(os.environ["DATABASE_ADMIN_URL"]) as c:
        c.execute("SET default_transaction_read_only=on")
        c.execute("SET statement_timeout='120s'")
        for name, n in c.execute(
            "SELECT split_part(external_id, ':', 1), count(*) FROM legal_sources "
            "WHERE source_type = 'other' AND is_current AND external_id ~ '^(sayistay|uyusmazlik|rekabet):' GROUP BY 1"
        ).fetchall():
            counts[name] = n
    try:
        text = (ROOT / "data" / "logs" / "import-emsal.log").read_text(encoding="utf-8", errors="ignore")
        seen = [int(x.replace(",", "")) for x in __import__("re").findall(r"sat.r=([\d,]+)", text)]
        counts["emsal_seen"] = seen[-1] if seen else 0
    except OSError:
        pass
    return counts


def fmt(n: int | None) -> str:
    return "-" if n is None else f"{n:,}".replace(",", ".")


def delta(now: int, prev: int | None) -> str:
    return "-" if prev is None else f"{now - prev:+,}".replace(",", ".")


def _write_chart(now: dict, y_new: int, d_new: int) -> None:
    """Geçmiş satırlarından kendini yenileyen grafik sayfası yazar (file:// ile açılır)."""
    point = {"t": time.strftime("%H:%M"), "ts": int(time.time()), "yargitay": y_new, "danistay": d_new, "bedesten": now["bedesten"], "belge": now["mevzuat_docs"]}
    with HISTORY.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(point) + "\n")
    points = [json.loads(line) for line in HISTORY.read_text(encoding="utf-8").splitlines() if line.strip()]
    cover = [
        ("Yargıtay", round(100 * (9_814_158 + y_new) / 9_984_824, 2)),
        ("Danıştay", round(100 * (383_016 + d_new) / 412_162, 2)),
        ("AYM", 100.0),
        ("KDK", round(100 * now["kdk"] / PORTAL["kdk"], 2)),
        ("Bedesten (belge)", round(100 * now["mevzuat_docs"] / MEVZUAT_PORTAL_DOCS, 2)),
    ]
    html = _CHART_HTML.replace("__POINTS__", json.dumps(points)).replace("__COVER__", json.dumps(cover)).replace("__NOW__", time.strftime("%H:%M:%S"))
    CHART.write_text(html, encoding="utf-8")


_CHART_HTML = """<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta http-equiv="refresh" content="120">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Veri çekme ilerlemesi</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
:root{--bg:#fbfaf7;--card:#fff;--ink:#1d2b26;--mut:#6a766f;--line:#e4e1d8;--a:#1f6f5a;--b:#c2793a;--c:#3b6cb0}
@media (prefers-color-scheme:dark){:root{--bg:#141816;--card:#1b211e;--ink:#e8eee9;--mut:#93a09a;--line:#2b342f;--a:#5fc4a5;--b:#e0a266;--c:#7fa7e0}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,Segoe UI,sans-serif;padding:20px 16px 40px}
main{max-width:1100px;margin:0 auto}h1{font-size:20px;margin:0 0 4px}.sub{color:var(--mut);margin:0 0 18px;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.card h2{font-size:14px;margin:0 0 8px}.big{font-size:26px;font-weight:650}.mut{color:var(--mut);font-size:12px}
.row{display:flex;align-items:center;gap:10px;margin:8px 0;font-size:13px}.row b{width:130px;font-weight:550}
.bar{flex:1;height:10px;background:var(--line);border-radius:6px;overflow:hidden}.bar i{display:block;height:100%;background:var(--a)}
canvas{max-height:230px}
</style></head><body><main>
<h1>Dış veri çekme ilerlemesi</h1><p class="sub">Son güncelleme __NOW__ · sayfa 2 dakikada bir yenilenir · portal toplamına göre (doğrulanmamışlar dahil)</p>
<div class="grid" id="stats"></div>
<div class="card" style="margin-top:14px"><h2>Kapsam (portal toplamına göre)</h2><div id="cover"></div></div>
<div class="grid" style="margin-top:14px">
<div class="card"><h2>Yargıtay: yeni çekilen karar (birikimli)</h2><canvas id="c1"></canvas></div>
<div class="card"><h2>Danıştay: yeni çekilen karar (birikimli)</h2><canvas id="c2"></canvas></div>
<div class="card"><h2>Bedesten: çekilen mevzuat maddesi</h2><canvas id="c3"></canvas></div>
<div class="card"><h2>Tablo aralığında artış (Yargıtay / Danıştay)</h2><canvas id="c4"></canvas></div>
</div></main>
<script>
const P=__POINTS__, COVER=__COVER__;
const last=P[P.length-1], first=P[0];
const hrs=Math.max((last.ts-first.ts)/3600,0.01);
const perHour=k=>Math.round((last[k]-first[k])/hrs);
const fmt=n=>n.toLocaleString('tr-TR');
document.getElementById('stats').innerHTML=[
 ['Yargıtay yeni karar',last.yargitay,perHour('yargitay')+' /saat'],
 ['Danıştay yeni karar',last.danistay,perHour('danistay')+' /saat'],
 ['Bedesten madde',last.bedesten,perHour('bedesten')+' /saat']
].map(([a,b,c])=>`<div class="card"><div class="mut">${a}</div><div class="big">${fmt(b)}</div><div class="mut">${fmt(parseInt(c))} /saat (grafik aralığı)</div></div>`).join('');
document.getElementById('cover').innerHTML=COVER.map(([n,v])=>`<div class="row"><b>${n}</b><div class="bar"><i style="width:${Math.min(v,100)}%"></i></div><span>%${v.toFixed(2).replace('.',',')}</span></div>`).join('');
const css=getComputedStyle(document.documentElement);const col=n=>css.getPropertyValue(n).trim();
const labels=P.map(p=>p.t);
const base={responsive:true,plugins:{legend:{display:false}},scales:{x:{ticks:{color:col('--mut'),maxTicksLimit:8},grid:{display:false}},y:{ticks:{color:col('--mut')},grid:{color:col('--line')}}},elements:{point:{radius:2},line:{tension:.25}}};
const line=(id,key,c)=>new Chart(document.getElementById(id),{type:'line',data:{labels,datasets:[{data:P.map(p=>p[key]),borderColor:col(c),backgroundColor:col(c)+'22',fill:true}]},options:base});
line('c1','yargitay','--a');line('c2','danistay','--b');line('c3','bedesten','--c');
const diff=k=>P.map((p,i)=>i?p[k]-P[i-1][k]:0);
new Chart(document.getElementById('c4'),{type:'bar',data:{labels,datasets:[{label:'Yargıtay',data:diff('yargitay'),backgroundColor:col('--a')},{label:'Danıştay',data:diff('danistay'),backgroundColor:col('--b')}]},options:{...base,plugins:{legend:{display:true,labels:{color:col('--mut')}}}}});
</script></body></html>"""


def _system() -> dict:
    """Disk ve çalışan süreç sayıları."""
    import shutil
    import subprocess

    free_gb = round(shutil.disk_usage("C:\\").free / 1e9)
    counts = {"embed": 0, "kampanya": 0, "sayistay": 0, "rekabet": 0, "uyusmazlik": 0, "emsal": 0, "mevzuat": 0}
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | ForEach-Object { $_.CommandLine }"],
            capture_output=True, text=True, timeout=40, encoding="utf-8", errors="ignore",
        ).stdout.splitlines()
        for line in out:
            for key, needle in (("embed", "embed_chunks"), ("kampanya", "backfill_campaign"), ("sayistay", "collect_sayistay"),
                                ("rekabet", "collect_rekabet"), ("uyusmazlik", "collect_uyusmazlik"),
                                ("emsal", "import_hf_mrfg"), ("mevzuat", "source mevzuat")):
                if needle in line:
                    counts[key] += 1
    except (OSError, subprocess.SubprocessError):
        pass
    # Her işçi hem başlatıcı hem çocuk süreç olarak görünür: ikiye böl.
    return {"disk": free_gb, **{k: (v + 1) // 2 for k, v in counts.items()}}


def _eta(remaining: float, per_hour: float) -> str:
    if remaining <= 0:
        return "tamam"
    if per_hour <= 0:
        return "bekleme/durgun"
    hours = remaining / per_hour
    if hours < 1:
        return f"~{round(hours * 60)} dk"
    if hours < 48:
        return f"~{hours:.1f} saat"
    return f"~{hours / 24:.1f} gün"


def emsal_pulled() -> int:
    """Resmî Emsal çekiminin (collect_emsal.py) bu güne kadar eklediği yeni karar sayısı."""
    try:
        return int(json.loads((ROOT / "data" / "campaign" / "emsal-collect.json").read_text(encoding="utf-8")).get("created", 0))
    except (OSError, ValueError):
        return 0


def render() -> str:
    s = stats()
    cd, leg, third = s["court_decisions"], s["legislation_verification"], s["third_party"]
    adm = s["administrative"]
    now = {
        "ts": time.time(),
        "yargitay": cd["yargitay"],
        "danistay": cd["danistay"],
        "aym": cd["anayasa_mahkemesi"],
        "emsal_ver": cd.get("istinaf_emsal", 0),
        "emsal_pulled": emsal_pulled(),
        "kdk": adm["kamu_denetciligi_kurumu"],
        "bedesten": leg["bedesten"],
        "mevzuat_docs": mevzuat_docs(),
        **{f"n_{k}": v for k, v in new_sources().items()},
        "emb_ready": s["embeddings"]["ready"],
        "emb_pending": s["embeddings"]["pending"],
        "rg_dogr": leg["both_verified"] + leg["gazette_only"],
        "mbs_dogr": leg["both_verified"] + leg["mbs_only"],
    }
    prev = json.loads(STATE.read_text()) if STATE.exists() else {}
    STATE.write_text(json.dumps(now))
    p = lambda k: prev.get(k)  # noqa: E731
    dt_hours = max((now["ts"] - prev["ts"]) / 3600, 1 / 3600) if prev.get("ts") else None

    def rate(key: str) -> float:
        return (now[key] - prev[key]) / dt_hours if dt_hours and key in prev else 0.0

    def hourly(key: str) -> str:
        return "-" if not dt_hours or key not in prev else fmt(round(rate(key)))

    y_new = now["yargitay"] - BASE["yargitay"]
    d_new = now["danistay"] - BASE["danistay"]
    y_left = max(MISSING0["yargitay"] - y_new, 0)
    d_left = max(MISSING0["danistay"] - d_new, 0)
    m_left = max(MEVZUAT_PORTAL_DOCS - now["mevzuat_docs"], 0)
    sy_left = max(51_774 - now["n_sayistay"], 0)
    uy_left = max(15_083 - now["n_uyusmazlik"], 0)
    rk_left = max(10_444 - now["n_rekabet"], 0)
    em_left = max(815_702 - now["n_emsal_seen"], 0)
    cursor_note = "önce resmî kayıtlar"
    for name in ("embed-seed-cursor-0of3.json", "embed-seed-cursor.json"):
        try:
            cursor_note = "doğrulanmamışlarda " + json.loads((ROOT / "data" / "campaign" / name).read_text(encoding="utf-8"))["date"] + " tarihine inildi"
            break
        except (OSError, ValueError, KeyError):
            continue

    rows = [
        ("Yargıtay (boşluk)", f"+{fmt(y_new)} yeni", delta(now["yargitay"], p("yargitay")), hourly("yargitay"), f"~{fmt(y_left)} karar", _eta(y_left, rate("yargitay"))),
        ("Danıştay (boşluk)", f"+{fmt(d_new)} yeni", delta(now["danistay"], p("danistay")), hourly("danistay"), f"~{fmt(d_left)} karar", _eta(d_left, rate("danistay"))),
        ("İstinaf resmî çekim (veri setinde olmayanlar)", fmt(emsal_pulled()), delta(emsal_pulled(), p("emsal_pulled")), hourly("emsal_pulled"), "~70 bin+ (2022-26), 2018-21 ölçülmedi", "portal sınırı"),
        ("İstinaf doğrulama (resmî oldu)", fmt(now["emsal_ver"]), delta(now["emsal_ver"], p("emsal_ver")), hourly("emsal_ver"), f"~{fmt(third['istinaf_emsal'])} doğrulanmadı", "portal sınırı"),
        ("AYM (bireysel)", fmt(now["aym"]), delta(now["aym"], p("aym")), hourly("aym"), "tamam", "-"),
        ("KDK", fmt(now["kdk"]), delta(now["kdk"], p("kdk")), hourly("kdk"), f"{fmt(PORTAL['kdk'] - now['kdk'])} dosyasız", "-"),
        ("Bedesten (mevzuat)", f"{fmt(now['mevzuat_docs'])} belge / {fmt(now['bedesten'])} madde", delta(now["bedesten"], p("bedesten")) + " madde", hourly("bedesten") + " madde", f"~{fmt(m_left)} belge", _eta(m_left, rate("mevzuat_docs"))),
        ("Sayıştay", f"{fmt(now['n_sayistay'])} karar", delta(now["n_sayistay"], p("n_sayistay")), hourly("n_sayistay"), f"~{fmt(sy_left)} karar", _eta(sy_left, rate("n_sayistay"))),
        ("Uyuşmazlık Mah.", f"{fmt(now['n_uyusmazlik'])} karar", delta(now["n_uyusmazlik"], p("n_uyusmazlik")), hourly("n_uyusmazlik"), f"~{fmt(uy_left)} karar", _eta(uy_left, rate("n_uyusmazlik"))),
        ("Rekabet Kurulu", f"{fmt(now['n_rekabet'])} karar", delta(now["n_rekabet"], p("n_rekabet")), hourly("n_rekabet"), f"~{fmt(rk_left)} karar", _eta(rk_left, rate("n_rekabet"))),
        ("İstinaf (Emsal) aktarım", f"{fmt(now['n_emsal_seen'])} / 815.702", delta(now["n_emsal_seen"], p("n_emsal_seen")), hourly("n_emsal_seen"), f"~{fmt(em_left)} satır", _eta(em_left, rate("n_emsal_seen"))),
        ("Embedding", f"{fmt(now['emb_ready'])} hazır", delta(now["emb_ready"], p("emb_ready")) + " parça", hourly("emb_ready"), f"{fmt(now['emb_pending'])} parça", _eta(now["emb_pending"], rate("emb_ready"))),
        ("Resmî Gazete (doğrulama)", f"{fmt(now['rg_dogr'])} madde", delta(now["rg_dogr"], p("rg_dogr")), hourly("rg_dogr"), "çekme sonrası", "-"),
        ("MBS (doğrulama)", f"{fmt(now['mbs_dogr'])} madde", delta(now["mbs_dogr"], p("mbs_dogr")), hourly("mbs_dogr"), "çekme sonrası", "-"),
    ]
    try:
        _write_chart(now, y_new, d_new)
    except Exception as exc:  # noqa: BLE001 - grafik hatası tabloyu engellemesin
        print(f"grafik hatası: {type(exc).__name__} {str(exc)[:60]}", flush=True)

    system = _system()
    resmi_total = s["decision_count"]
    def bar(have: float, total: float) -> str:
        share = 1.0 if total <= 0 else max(0.0, min(have / total, 1.0))
        filled = round(share * 20)
        return f"{'█' * filled}{'░' * (20 - filled)} %{share * 100:.1f}"

    y_have = cd["yargitay"] + third["yargitay"]
    d_have = cd["danistay"] + third["danistay"]
    official_all, seed_all = s["decision_count"], s["seed_count"]
    pct_rows = [
        ("Yargıtay (resmî + arşiv / portal)", fmt(y_have), fmt(y_have + y_left), bar(y_have, y_have + y_left)),
        ("Danıştay (resmî + arşiv / portal)", fmt(d_have), fmt(d_have + d_left), bar(d_have, d_have + d_left)),
        ("AYM bireysel başvuru", fmt(now["aym"]), fmt(PORTAL.get("aym", now["aym"])), bar(now["aym"], PORTAL.get("aym", now["aym"]))),
        ("KDK", fmt(now["kdk"]), fmt(PORTAL["kdk"]), bar(now["kdk"], PORTAL["kdk"])),
        ("Bedesten mevzuat (belge)", fmt(now["mevzuat_docs"]), fmt(MEVZUAT_PORTAL_DOCS), bar(now["mevzuat_docs"], MEVZUAT_PORTAL_DOCS)),
        ("Sayıştay", fmt(now["n_sayistay"]), fmt(51_774), bar(now["n_sayistay"], 51_774)),
        ("Uyuşmazlık Mahkemesi", fmt(now["n_uyusmazlik"]), fmt(15_083), bar(now["n_uyusmazlik"], 15_083)),
        ("Rekabet Kurulu", fmt(now["n_rekabet"]), fmt(10_444), bar(now["n_rekabet"], 10_444)),
        ("İstinaf (Emsal) veri seti aktarımı (resmî portal kapsamı ~%75-80)", fmt(now["n_emsal_seen"]), fmt(815_702), bar(now["n_emsal_seen"], 815_702)),
        ("Embedding (parça)", fmt(now["emb_ready"]), fmt(now["emb_ready"] + now["emb_pending"]), bar(now["emb_ready"], now["emb_ready"] + now["emb_pending"])),
        ("Yargı kararı resmî doğrulama", fmt(official_all), fmt(official_all + seed_all), bar(official_all, official_all + seed_all)),
    ]
    out = [
        f"TABLO {time.strftime('%H:%M')} (önceki tabloya göre)",
        "",
        "**TAMAMLANMA (yüzde)**",
        "| Kaynak | Elde | Hedef | İlerleme |",
        "| --- | --- | --- | --- |",
        *[f"| {a} | {b} | {c} | {d} |" for a, b, c, d in pct_rows],
        "",
        "**ÇEKİM**",
        "| Kaynak | Şu an | Son tablo | Saatlik hız | Kalan | Tahmini bitiş |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    out += [f"| {a} | {b} | {c} | {d} | {e} | {f} |" for a, b, c, d, e, f in rows]
    out += [
        "",
        "**TOPLAM VERİ**",
        "| Kalem | Adet |",
        "| --- | --- |",
        f"| Yargı kararı | {fmt(s['decision_count'] + s['seed_count'])} |",
        f"| · resmî doğrulanmış | {fmt(resmi_total)} (Yargıtay {fmt(cd['yargitay'])}, Danıştay {fmt(cd['danistay'])}, AYM {fmt(cd['anayasa_mahkemesi'])}, İstinaf {fmt(cd.get('istinaf_emsal', 0))}) |",
        f"| · doğrulanmadı (hazır arşiv) | {fmt(s['seed_count'])} (Yargıtay {fmt(third['yargitay'])}, Danıştay {fmt(third['danistay'])}, İstinaf {fmt(third['istinaf_emsal'])}, AYM norm {fmt(third['aym_norm_denetimi'])}) |",
        f"| İdarî karar | {fmt(s['other_count'])} (KDK {fmt(adm['kamu_denetciligi_kurumu'])}, Sayıştay {fmt(adm.get('sayistay', 0))}, Uyuşmazlık {fmt(adm.get('uyusmazlik_mahkemesi', 0))}, Rekabet {fmt(now['n_rekabet'])}) |",
        f"| Mevzuat | {fmt(now['bedesten'])} madde, {fmt(s['legislation_count'])} doğrulanmış |",
        f"| Parça (aranabilir metin) | {fmt(s['chunk_count'])} |",
        f"| Embedding | {fmt(now['emb_ready'])} hazır / {fmt(now['emb_pending'])} bekliyor ({cursor_note}) |",
        "",
        f"**SİSTEM:** disk {system['disk']} GB boş · embedding işçisi {system['embed']} · Yargıtay/Danıştay kampanya {system['kampanya']} · "
        f"Sayıştay {system['sayistay']} · Rekabet {system['rekabet']} · Uyuşmazlık {system['uyusmazlik']} · istinaf aktarım {system['emsal']} · mevzuat {system['mevzuat']}",
    ]
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=300)
    args = parser.parse_args()
    while True:
        try:
            print(render(), flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"TABLO HATA: {type(exc).__name__} {str(exc)[:80]}", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
