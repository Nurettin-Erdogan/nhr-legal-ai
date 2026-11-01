"""Yerel modelleri AYNI kanıt listesiyle, altın etiketli sorularda karşılaştırır (kaynak cümlesi seçimi).

  python scripts/bench_selection_models.py freeze                                    # adayları dondurur, kanun cümlelerini gösterir
  python scripts/bench_selection_models.py run <model> [think|nothink] [etiket] [shuffle]   # dondurulmuş adaylarla çalıştırır, puanlar

Her soruda modele giden istem uygulamadakiyle aynıdır (`selection_instruction` + `selection_prompt`). Altın etiket: cevabı taşıyan
kanun cümlesinin ayırt edici parçası (`must`). Puan: hepsi seçildi mi, en az biri seçildi mi, seçimin kaçı kanun maddesinden.
`shuffle`: aynı adaylar karışık sırayla verilir; model cümleyi yerinden değil içeriğinden bulmalıdır.

Dondurulan adaylar ve sonuçlar `data/benchmarks/` altında kalır (depoya girmez: korpus metni içerir). Karşılaştırma yalnız
yereldeki Ollama'ya gider; `.env` ve korpus değişmez. Sonuçlar: docs/local-model-comparison.md.
"""

import json
import re
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
sys.stdout.reconfigure(encoding="utf-8")
BENCH_DIR = ROOT / "data" / "benchmarks" / "selection-models-20261009"
CASES_FILE = BENCH_DIR / "cases.json"
OLLAMA = "http://127.0.0.1:11434"
CALL_TIMEOUT = (
    150  # sn; etkileşimli kullanımda bundan uzun süren seçim zaten kullanılamaz
)

# must: seçilen cümlelerde bulunması gereken parçalar (her biri ayrı bir cümleyi gösterir). Yalnız kanun metni açık olan
# sorular alındı; etiketler korpustaki resmî madde metninden yazıldı.
CASES = [
    {
        "id": "haksiz-fesih",
        "q": "İş sözleşmesinin haksız feshinde işçi hangi tazminatları talep edebilir?",
        "must": ["Bildirim şartına uymayan taraf", "kıdem tazminatı ödenir"],
    },
    {
        "id": "ise-iade",
        "q": "İşe iade davasının koşulları nelerdir?",
        "must": [
            "Otuz veya daha fazla işçi çalıştıran",
            "arabulucuya başvurmak zorundadır",
        ],
    },
    {
        "id": "gecersiz-fesih",
        "q": "Geçersiz feshin işçi açısından sonuçları nelerdir?",
        "must": ["işe başlatmak zorundadır", "en az dört aylık ve en çok sekiz aylık"],
    },
    {
        "id": "ihbar",
        "q": "İhbar tazminatı hangi durumlarda doğar?",
        "must": ["Bildirim şartına uymayan taraf"],
    },
    {
        "id": "esit-davranma",
        "q": "İş Kanununda eşit davranma ilkesi nasıl korunur?",
        "must": ["ayrım yapılamaz"],
    },
    {
        "id": "fazla-calisma",
        "q": "Fazla çalışma ücreti nasıl hesaplanır?",
        "must": ["yüzde elli yükseltilmesi"],
    },
    {
        "id": "yillik-izin",
        "q": "Yıllık ücretli izne hak kazanma şartları nelerdir?",
        "must": ["en az bir yıl çalışmış olan işçilere"],
    },
    {
        "id": "kira-temerrut",
        "q": "Kiracı kirayı ödemezse kiraya veren ne yapabilir?",
        "must": ["yazılı olarak bir süre verip"],
    },
    {
        "id": "bosanma",
        "q": "Evlilik birliğinin sarsılması nedeniyle boşanmanın şartları nelerdir?",
        "must": ["eşlerden her biri boşanma davası açabilir"],
    },
    {
        "id": "kdk",
        "q": "Kamu Denetçiliği Kurumuna başvuru şartları nelerdir?",
        "must": ["Kuruma başvuruda bulunulabilmesi için"],
    },
    {
        "id": "ayipli-mal",
        "q": "Tüketici ayıplı malda hangi haklara sahiptir?",
        "must": ["Malın ayıplı olduğunun anlaşılması durumunda tüketici"],
    },
    {
        "id": "hakli-fesih-isveren",
        "q": "İşveren hangi hallerde iş sözleşmesini haklı nedenle derhal feshedebilir?",
        "must": ["İşverenin haklı nedenle derhal fesih hakkı Madde 25"],
    },
    {
        "id": "hakli-fesih-isci",
        "q": "İşçi hangi hallerde haklı nedenle derhal fesih yapabilir?",
        "must": ["İşçinin haklı nedenle derhal fesih hakkı Madde 24"],
    },
    {
        "id": "is-arabuluculuk",
        "q": "İş uyuşmazlıklarında dava açmadan önce arabulucuya başvurmak zorunlu mudur?",
        "must": ["arabulucuya başvurulmuş olması dava şartıdır"],
    },
    {
        "id": "idari-istinaf",
        "q": "İdare mahkemesi kararına karşı istinaf yoluna nasıl başvurulur?",
        "must": ["İdare ve vergi mahkemelerinin kararlarına karşı"],
    },
]


def freeze():
    from api.ai import pipeline
    from api.ai.evidence_selection import (
        evidence_candidates,
        selection_instruction,
        selection_prompt,
    )
    from api.config import get_settings
    from api.schemas import AIAnswerRequest

    settings = get_settings()
    frozen = []
    for case in CASES:
        contexts = None
        for attempt in range(4):
            try:
                contexts = pipeline._retrieve(
                    AIAnswerRequest(question=case["q"]),
                    user_id=None,
                    query_embedding=None,
                    top_k=pipeline.candidate_pool_size(settings.rag_top_k),
                    embedding_model=settings.embedding_model,
                    question=case["q"],
                    diagnostics={},
                    statutes_on_timeout=attempt >= 1,
                )
                break
            except Exception as exc:  # noqa: BLE001
                print(
                    f"   {case['id']}: arama denemesi {attempt + 1} başarısız ({type(exc).__name__})"
                )
        if contexts is None:
            continue
        chosen = pipeline.select_answer_contexts(
            pipeline.verified_contexts(contexts), settings.rag_top_k, question=case["q"]
        )
        evidence = evidence_candidates(
            case["q"], chosen, per_source_chars=1200, total_chars=4500
        )
        if not evidence:
            print(f"   {case['id']}: aday yok")
            continue
        row = {
            **case,
            "system": selection_instruction(chosen, evidence),
            "prompt": selection_prompt(case["q"], chosen, evidence),
            "evidence": [
                {
                    "id": e.id,
                    "marker": e.marker,
                    "text": e.text,
                    "statute": chosen[e.marker - 1].source_type == "legislation",
                    "ref": f"{chosen[e.marker - 1].law_no}/{chosen[e.marker - 1].article_no}"
                    if chosen[e.marker - 1].source_type == "legislation"
                    else "karar",
                }
                for e in evidence
            ],
        }
        frozen.append(row)
        print(f"== {case['id']} | {case['q']} | aday {len(evidence)}")
        for item in row["evidence"]:
            if item["statute"]:
                print(f"   {item['id']:3} {item['ref']:9} {item['text'][:170]}")
        missing = [
            m
            for m in case["must"]
            if not any(m in item["text"] for item in row["evidence"])
        ]
        if missing:
            print(f"   !! etiket adaylarda yok: {missing}")
    CASES_FILE.write_text(
        json.dumps(frozen, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\n{len(frozen)} soru donduruldu → {CASES_FILE.name}")


def ask(model, think, system, prompt, num_ctx=4096, num_predict=768):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "think": think,
        "keep_alive": "10m",
        "options": {"temperature": 0, "num_ctx": num_ctx, "num_predict": num_predict},
    }
    if not think:
        payload["format"] = "json"
    t = time.monotonic()
    try:
        body = httpx.post(
            f"{OLLAMA}/api/chat", json=payload, timeout=CALL_TIMEOUT
        ).json()
    except httpx.TimeoutException:
        return "", "", time.monotonic() - t, {"done_reason": "zaman aşımı"}
    message = body.get("message", {})
    return (
        message.get("content", ""),
        message.get("thinking", ""),
        time.monotonic() - t,
        body,
    )


def selected_ids(raw, known):
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    match = re.search(r"\{.*\}", text, flags=re.S)
    try:
        ids = json.loads(match.group(0)).get("evidence_ids") if match else None
    except (ValueError, AttributeError):
        ids = None
    if (
        not isinstance(ids, list)
        or len(ids) > 4
        or any(not isinstance(i, str) or i not in known for i in ids)
    ):
        return None
    return list(dict.fromkeys(ids))


def shuffled(case):
    """Aynı adaylar, karışık sırayla ve yeniden numaralanmış (sabit tohum): model cümleyi yerinden değil içeriğinden bulmalı."""
    import random

    head, body = case["prompt"].split("KAYNAK CÜMLELERİ:\n", 1)
    blocks = body.split("\n\n")
    assert len(blocks) == len(case["evidence"]), (
        case["id"],
        len(blocks),
        len(case["evidence"]),
    )
    order = list(range(len(blocks)))
    random.Random(case["id"]).shuffle(order)
    evidence, texts = [], []
    for position, index in enumerate(order, 1):
        old = case["evidence"][index]
        block = blocks[index]
        assert block.startswith(old["id"] + " "), (case["id"], block[:20])
        texts.append(f"E{position}" + block[len(old["id"]) :])
        evidence.append({**old, "id": f"E{position}"})
    return {
        **case,
        "prompt": head + "KAYNAK CÜMLELERİ:\n" + "\n\n".join(texts),
        "evidence": evidence,
    }


def run(model, think, label, shuffle=False):
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    if shuffle:
        cases = [shuffled(case) for case in cases]
    t = time.monotonic()
    httpx.post(
        f"{OLLAMA}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": "merhaba"}],
            "stream": False,
            "think": False,
            "keep_alive": "10m",
            "options": {"num_predict": 4, "num_ctx": 8192 if think else 4096},
        },
        timeout=600,
    )
    print(
        f"model yüklendi ({time.monotonic() - t:.0f} sn)", flush=True
    )  # yükleme süresi ölçüme girmez
    rows = []
    for case in cases:
        known = {e["id"]: e for e in case["evidence"]}
        # Düşünme açıkken bağlam ve çıktı payı artırılır: düşünce metni çıktı payından yer.
        raw, thinking, took, body = ask(
            model,
            think,
            case["system"],
            case["prompt"],
            num_ctx=8192 if think else 4096,
            num_predict=2048 if think else 768,
        )
        ids = selected_ids(raw, known)
        picked = [known[i] for i in ids] if ids else []
        must = case["must"]
        found = [m for m in must if any(m in e["text"] for e in picked)]
        row = {
            "id": case["id"],
            "seconds": round(took, 1),
            "valid": ids is not None,
            "picked": ids or [],
            "statute_picked": sum(1 for e in picked if e["statute"]),
            "must": len(must),
            "found": len(found),
            "thinking_chars": len(thinking),
            "done": body.get("done_reason"),
        }
        rows.append(row)
        mark = (
            "—"
            if not must
            else ("TAM" if len(found) == len(must) else "KISMEN" if found else "YOK")
        )
        print(
            f"{case['id']:20} {took:6.1f} sn | geçerli {str(row['valid']):5} | seçilen {len(picked)} (kanun {row['statute_picked']}) | etiket {len(found)}/{len(must)} {mark:6} | {ids}",
            flush=True,
        )
    labeled = [r for r in rows if r["must"]]
    summary = {
        "model": model,
        "think": think,
        "karışık": shuffle,
        "sorular": len(rows),
        "geçerli": sum(r["valid"] for r in rows),
        "etiketli": len(labeled),
        "tam": sum(r["found"] == r["must"] for r in labeled),
        "en_az_bir": sum(r["found"] > 0 for r in labeled),
        "etiket_cümlesi": f"{sum(r['found'] for r in labeled)}/{sum(r['must'] for r in labeled)}",
        "kanundan_seçim": f"{sum(r['statute_picked'] for r in rows)}/{sum(len(r['picked']) for r in rows)}",
        "süre_ortanca": sorted(r["seconds"] for r in rows)[len(rows) // 2],
        "süre_en_uzun": max(r["seconds"] for r in rows),
    }
    print("ÖZET", json.dumps(summary, ensure_ascii=False))
    (BENCH_DIR / f"{label}.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


if __name__ == "__main__":
    if sys.argv[1] == "freeze":
        freeze()
    else:
        model = sys.argv[2]
        think = len(sys.argv) > 3 and sys.argv[3] == "think"
        shuffle = "shuffle" in sys.argv[3:]
        label = next(
            (a for a in sys.argv[4:] if a != "shuffle"),
            re.sub(r"\W+", "-", model) + ("-think" if think else ""),
        )
        run(model, think, label + ("-karisik" if shuffle else ""), shuffle)
