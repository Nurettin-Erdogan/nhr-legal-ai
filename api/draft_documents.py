"""Dilekçe, ihtarname ve sözleşme taslağı: sabit iskelet + doğrulanmış olgu anlatımı + kodla eklenen resmî dayanak listesi.

Eski akış modele tüm belgeyi yazdırıp çıktıyı `[K1]` atıf denetiminden geçirmeye çalışıyordu; serbest biçimli bir taslak bu denetimi
geçemediği (ve yerel model 800 belirteçte kesildiği) için dilekçe, sözleşme ve analiz modüllerinin altısı da hata veriyordu.
Yeni tasarım kaynak kuralını gevşetmeden çalışır:

* **İskelet kodla kurulur** (başlıklar, taraf satırları, "SONUÇ VE İSTEM"). Boş alanlar `[…]` ile bırakılır, uydurulmaz.
* **Model yalnız olay anlatımını yazar** ve yalnız kullanıcının verdiği bilgilerle. Her paragraf kodda doğrulanır
  (`case_summary.bullet_supported`): verilen metinde olmayan tutar/tarih/numara, kanun ya da karar numarası ve verilenle örtüşmeyen
  paragraf elenir. Hiç paragraf kalmazsa kullanıcının kendi yazdığı olgular aynen kullanılır; taslak yine üretilir.
* **Hukuki nedenler modele yazdırılmaz.** Korpustan getirilen resmî doğrulanmış mevzuat ve kararlar kodla listelenir ve "otomatik
  bulundu, uygunluğunu kontrol edin" diye işaretlenir. Kaynak bulunamazsa bu bölüm boş bırakılır ve söylenir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from api.case_summary import bullet_supported, parse_bullets

MAX_PARAGRAPHS = 6

FACT_SYSTEM = (
    "Sen bir avukat asistanısın. Aşağıda müvekkilin verdiği olgular var. Bunları resmî dilekçe üslubuyla, numaralı kısa "
    "paragraflar hâlinde (en çok 6) yeniden yaz. YALNIZCA verilen bilgileri kullan. Kanun, madde, karar numarası, hukuki sonuç "
    "ya da tavsiye YAZMA; verilmeyen isim, tarih, tutar uydurma. Her paragraf '1.', '2.' gibi numarayla başlasın. Başlık ya da "
    "giriş cümlesi yazma."
)

DOC_LABELS = {
    "dilekce": "Dava Dilekçesi",
    "sozlesme": "Sözleşme",
    "ihtarname": "İhtarname",
    "diger": "Hukuki Belge",
}
GAP = "[…]"
NOTICE = (
    "_Taslaktır: `[…]` alanlarını doldurun. Olay anlatımı yalnız sizin verdiğiniz bilgilerle yazıldı ve kodla denetlendi; "
    "hukuki dayanak listesi korpustaki resmî doğrulanmış kaynaklardan otomatik eklendi, uygunluğunu avukat kontrol etmelidir._"
)


@dataclass
class Legal:
    """Kodla listelenen dayanaklar."""

    statutes: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)


def legal_references(contexts) -> Legal:
    """Resmî doğrulanmış mevzuat ve kararlar; `other` (Sayıştay vb.) ve doğrulanmamış kayıtlar listelenmez."""
    legal = Legal()
    seen: set[str] = set()
    for context in contexts:
        if context.verification != "official":
            continue
        if context.source_type == "legislation" and context.law_name and context.article_no:
            line = f"{context.law_name} ({context.law_no}) m. {context.article_no}" if context.law_no else f"{context.law_name} m. {context.article_no}"
            if context.article_title:
                line += f" — {context.article_title.strip().rstrip(':')}"
            bucket = legal.statutes
        elif context.source_type == "court_decision":
            line, bucket = context.reference_line, legal.decisions
        else:
            continue
        if line in seen:
            continue
        seen.add(line)
        bucket.append(line)
        legal.sources.append({"reference": line, "source_url": context.source_url, "verification": "official", "source_type": context.source_type})
    return legal


def given_text(parties: list[str], subject: str, details: str | None, extra: str = "") -> str:
    return "\n".join(part for part in ["; ".join(parties), subject, details or "", extra] if part)


def verified_paragraphs(model_output: str, given: str) -> list[str]:
    """Model paragraflarından verilen bilgiyle desteklenenler (en çok `MAX_PARAGRAPHS`)."""
    return [paragraph for paragraph in parse_bullets(model_output) if bullet_supported(paragraph, given)][:MAX_PARAGRAPHS]


def fallback_paragraphs(subject: str, details: str | None) -> list[str]:
    """Model çıktısı doğrulanamazsa kullanıcının kendi olguları: cümlelere bölünür, aynen kullanılır. Olgu verilmemişse boşluk bırakılır."""
    text = " ".join((details or "").split())
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if len(part.strip()) > 3]
    return sentences[:MAX_PARAGRAPHS] or [f"{GAP} (olayları, tarihleri ve tutarları burada anlatın)"]


def _numbered(paragraphs: list[str]) -> str:
    return "\n\n".join(f"{index}. {paragraph}" for index, paragraph in enumerate(paragraphs, start=1))


def _legal_section(legal: Legal) -> str:
    if not legal.statutes and not legal.decisions:
        return f"{GAP} _(Korpusta bu konuyla eşleşen doğrulanmış kaynak bulunamadı; hukuki nedenleri avukat eklemelidir.)_"
    lines = [f"- {line}" for line in legal.statutes]
    if legal.decisions:
        lines.append("")
        lines.append("_İlgili görülen emsal kararlar (otomatik bulundu, ilgisini kontrol edin):_")
        lines.extend(f"- {line}" for line in legal.decisions)
    if not legal.statutes:
        lines.insert(0, f"{GAP} _(Mevzuat dayanağı bulunamadı; yalnız karar bulundu.)_")
    return "\n".join(lines)


def _party(parties: list[str], index: int) -> str:
    return parties[index].strip() if len(parties) > index and parties[index].strip() else GAP


def build_document(doc_type: str, title: str | None, parties: list[str], subject: str, paragraphs: list[str], legal: Legal) -> str:
    label = DOC_LABELS.get(doc_type, DOC_LABELS["diger"])
    subject_line = " ".join(subject.split())
    body = _numbered(paragraphs)
    head = f"# {title.strip() if title and title.strip() else label}"
    if doc_type == "dilekce":
        parts = [
            head, "", f"**{GAP} MAHKEMESİNE**", "",
            f"**DAVACI:** {_party(parties, 0)}", f"**VEKİLİ:** Av. {GAP}", f"**DAVALI:** {_party(parties, 1)}", "",
            f"**KONU:** {subject_line}", "", "**AÇIKLAMALAR:**", "", body, "",
            "**HUKUKİ NEDENLER:**", "", _legal_section(legal), "",
            f"**DELİLLER:** {GAP}", "",
            "**SONUÇ VE İSTEM:**", "",
            f"Yukarıda açıklanan nedenlerle; {subject_line} yönündeki talebimin kabulüne karar verilmesini, yargılama giderleri ve vekâlet ücretinin davalıya yükletilmesini saygılarımla arz ve talep ederim. {GAP} (tarih)",
            "", f"Davacı Vekili Av. {GAP}",
        ]
    elif doc_type == "ihtarname":
        parts = [
            head, "", f"**KEŞİDECİ:** {_party(parties, 0)}", f"**MUHATAP:** {_party(parties, 1)}", "", f"**KONU:** {subject_line}", "",
            "**AÇIKLAMALAR:**", "", body, "", "**DAYANAK:**", "", _legal_section(legal), "",
            "**İHTAR:**", "",
            f"Yukarıda açıklanan hususlar nedeniyle, işbu ihtarnamenin tebliğinden itibaren {GAP} gün içinde {GAP} yerine getirilmediği takdirde yasal yollara başvuracağımı, bunun doğuracağı her türlü masraf ve zarardan sorumlu olacağınızı ihtar ederim. {GAP} (tarih)",
            "", f"Keşideci / Vekili: {GAP}",
        ]
    elif doc_type == "sozlesme":
        parts = [
            head, "", f"**TARAFLAR:** {_party(parties, 0)} ile {_party(parties, 1)}", "",
            f"**MADDE 1 – Sözleşmenin konusu:** {subject_line}", "", "**Olgular ve ön açıklamalar:**", "", body, "",
            f"**MADDE 2 – Bedel ve ödeme koşulları:** {GAP}", f"**MADDE 3 – Süre:** {GAP}", f"**MADDE 4 – Tarafların hak ve yükümlülükleri:** {GAP}",
            f"**MADDE 5 – Sona erme ve fesih:** {GAP}", f"**MADDE 6 – Gizlilik ve kişisel veriler:** {GAP}", f"**MADDE 7 – Uyuşmazlık çözümü ve yetkili mahkeme:** {GAP}",
            f"**MADDE 8 – Yürürlük:** {GAP}", "", "**Mevzuat dayanakları (otomatik; avukat kontrol etmelidir):**", "", _legal_section(legal), "",
            f"İmzalar: {_party(parties, 0)} / {_party(parties, 1)}  {GAP} (tarih)",
        ]
    else:
        parts = [
            head, "", f"**KONU:** {subject_line}", "", "**AÇIKLAMALAR:**", "", body, "",
            "**HUKUKİ NEDENLER:**", "", _legal_section(legal), "", f"**SONUÇ VE İSTEM:** {GAP}", "", f"{GAP} (tarih ve imza)",
        ]
    # Her parça kendi paragrafıdır: Markdown tek satır sonunu boşluğa çevirdiğinden (DAVACI/VEKİLİ/DAVALI satırları birleşirdi) boş satırla ayrılır.
    return "\n\n".join(part for part in parts if part != "") + f"\n\n---\n{NOTICE}\n"
