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
from pydantic import BaseModel, ConfigDict, Field

from api.case_summary import bullet_supported, parse_bullets

FACT_SYSTEM = (
    "Sen bir avukat asistanısın. Aşağıda müvekkilin verdiği olgular var. Bunları resmî dilekçe üslubuyla, numaralı kısa "
    "paragraflar hâlinde yeniden yaz. Hiçbir olay veya koşulu atlama. YALNIZCA verilen bilgileri kullan. Kanun, madde, karar numarası, hukuki sonuç "
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


class DraftFields(BaseModel):
    """Explicit user instructions, never inferred legal findings or model evidence."""
    model_config = ConfigDict(extra="forbid")
    authority: str = Field(default="", max_length=500)
    representative: str = Field(default="", max_length=500)
    evidence: str = Field(default="", max_length=8000)
    requests: str = Field(default="", max_length=8000)
    payment: str = Field(default="", max_length=4000)
    term: str = Field(default="", max_length=4000)
    obligations: str = Field(default="", max_length=8000)
    termination: str = Field(default="", max_length=4000)
    confidentiality: str = Field(default="", max_length=4000)
    dispute: str = Field(default="", max_length=4000)
    effective_date: str = Field(default="", max_length=500)
    notice_period: str = Field(default="", max_length=1000)
    notice_demand: str = Field(default="", max_length=8000)
    notice_consequence: str = Field(default="", max_length=4000)


def _field_text(fields: DraftFields, name: str) -> str:
    # Keep user terms literal: do not let a typed heading become Markdown structure.
    value = getattr(fields, name).strip()
    return re.sub(r"([\\`*_{}\[\]<>#!|])", r"\\\1", value) if value else GAP
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
    # Konu ipucu tablosundan gelen, korpusta resmî metniyle doğrulanmış maddeler (api.statute_hints).
    suggested: list[str] = field(default_factory=list)


MAX_DECISIONS = 3
# Emsal listesinde üst derece mahkemesi önce gelir; ilk derece kararı ancak başka karar yoksa gösterilir.
_COURT_RANK = (("hukuk genel kurulu", 0), ("ceza genel kurulu", 0), ("içtihadı birleştirme", 0), ("anayasa mahkemesi", 1),
               ("yargıtay", 1), ("danıştay", 1), ("bölge adliye", 2), ("bölge idare", 2))


def _court_rank(reference: str) -> int:
    lowered = reference.replace("İ", "i").lower()
    return next((rank for needle, rank in _COURT_RANK if needle in lowered), 3)


def legal_references(contexts, *, question: str = "", suggested: list[dict] | None = None) -> Legal:
    """Resmî doğrulanmış mevzuat ve kararlar; `other` (Sayıştay vb.) ve doğrulanmamış kayıtlar listelenmez.

    `question` verilirse kararlar konuyla ilgisine göre süzülür (havuz içi alaka: `consulted_relevance`) ve üst derece mahkemesi
    öne alınır; en çok `MAX_DECISIONS` karar listelenir. Tahliye dilekçesine ilgisiz beş Asliye Ticaret kararı "emsal" diye
    ekleniyordu (ölçüldü: 2026-10-05). `suggested`: konu ipuçlarından gelen doğrulanmış maddeler; listenin başına konur.
    """
    legal = Legal()
    seen: set[str] = set()
    for row in suggested or []:
        if row["reference"] not in seen:
            seen.add(row["reference"])
            legal.suggested.append(row["reference"])
            legal.sources.append({key: row[key] for key in ("reference", "source_url", "verification", "source_type")})
    hinted = {(row.get("law_no"), row.get("article_no")) for row in suggested or []}
    keep = None
    if question:
        from api.ai.consulted_relevance import relevant_chunk_ids

        keep = relevant_chunk_ids(question, [context for context in contexts if context.verification == "official"])
    decisions: list[tuple[int, int, str, object]] = []
    for position, context in enumerate(contexts):
        if context.verification != "official":
            continue
        if question and context.source_type == "legislation":
            # A corpus-relative score is not a relevance proof: an unrelated
            # regulation can be the "best" of a poor candidate pool. Require
            # topic overlap in its title as well, unless this is a code explicitly
            # identified by a verified subject hint.
            from api.ai.consulted_relevance import _stems
            from api.ai.search_plan import normalize

            title = normalize(context.law_name or "")
            anchors = _stems(question)
            hinted_laws = {row.get("law_no") for row in suggested or []}
            if context.law_no not in hinted_laws and not any(stem in title for stem in anchors):
                continue
        if context.source_type == "legislation" and context.law_name and context.article_no:
            if (context.law_no, context.article_no) in hinted:
                continue  # aynı madde önerilenlerde zaten var
            if keep is not None and context.chunk_id not in keep:
                continue
            line = f"{context.law_name} ({context.law_no}) m. {context.article_no}" if context.law_no else f"{context.law_name} m. {context.article_no}"
            if context.article_title:
                line += f" — {context.article_title.strip().rstrip(':')}"
            if line in seen:
                continue
            seen.add(line)
            legal.statutes.append(line)
            legal.sources.append({"reference": line, "source_url": context.source_url, "verification": "official", "source_type": context.source_type})
        elif context.source_type == "court_decision":
            if keep is not None and context.chunk_id not in keep:
                continue
            line = context.reference_line
            if line in seen:
                continue
            seen.add(line)
            decisions.append((_court_rank(line), position, line, context))
    # İlk derece mahkemesi kararı emsal diye listelenmez (bağlayıcı içtihat değildir ve arama sonucu çoğu kez konu dışıdır).
    decisions = [item for item in decisions if item[0] <= 2]
    for _, _, line, context in sorted(decisions, key=lambda item: (item[0], item[1]))[:MAX_DECISIONS]:
        legal.decisions.append(line)
        legal.sources.append({"reference": line, "source_url": context.source_url, "verification": "official", "source_type": context.source_type})
    return legal


def given_text(parties: list[str], subject: str, details: str | None, extra: str = "") -> str:
    return "\n".join(part for part in ["; ".join(parties), subject, details or "", extra] if part)


MIN_FACT_CHARS = 40  # bundan kısa olgu metniyle model çağrılmaz: yazacak olgu yoktur, model uydurur


def has_facts(details: str | None, extra: str = "") -> bool:
    """Kullanıcı gerçekten olgu verdi mi? Yalnız konu satırıyla model "davalı da talepte bulunmaktadır" gibi cümleler uyduruyordu."""
    return len(" ".join(f"{details or ''} {extra}".split())) >= MIN_FACT_CHARS


LONG_SUBJECT_CHARS = 120  # bu kadar uzun bir konu metni olgu anlatımıdır (kullanıcı olayları "Konu" alanına yazmıştır)


def facts_source(subject: str, details: str | None, extra: str = "") -> str | None:
    """Olay anlatımı için kullanıcı metni: ayrıntı alanı doluysa o; boşsa yalnız UZUN bir konu metni (kullanıcının kendi sözleri).

    Kısa bir konu satırı olgu sayılmaz (model onunla "davalı da talepte bulunmaktadır" gibi cümleler uyduruyordu); uzun konu metni ise
    kullanıcının yazdığı olaylardır ve cümleler yine `given_text` içinde (konu dâhil) kod denetiminden geçer.
    """
    if has_facts(details, extra):
        return details
    cleaned = " ".join(subject.split())
    return cleaned if len(cleaned) >= LONG_SUBJECT_CHARS else details


def short_subject(subject: str, limit: int = 160) -> str:
    """KONU satırı için ilk cümle (uzun olay anlatımı satırda tekrar edilmez); çok uzun tek cümle sözcük sınırında kısaltılır."""
    cleaned = " ".join(subject.split())
    first = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0] if cleaned else cleaned
    if len(first) > limit:
        first = first[:limit].rsplit(" ", 1)[0].rstrip(",;:")
    return first.rstrip(".")


def split_sentences(paragraph: str) -> list[str]:
    from api.ai.source_support import _sentences

    return [sentence.strip() for sentence in _sentences(paragraph) if sentence.strip()]


def verified_paragraphs(model_output: str, given: str) -> list[list[str]]:
    """Model paragraflarının verilen bilgiyle desteklenen CÜMLELERİ (paragraf başına liste).

    Denetim cümle düzeyindedir: doğru bir cümlenin yanına eklenen uydurma cümle ("Bu tutar … yetersizliği sonucu oluşmuştur")
    paragrafla birlikte geçiyordu (ölçüldü: 2026-10-05). Desteklenmeyen cümle atılır, paragrafın geri kalanı korunur.
    """
    paragraphs: list[list[str]] = []
    for paragraph in parse_bullets(model_output):
        kept = [sentence for sentence in split_sentences(paragraph) if bullet_supported(sentence, given)]
        if kept:
            paragraphs.append(kept)
    return paragraphs


def join_paragraphs(paragraphs: list[list[str]]) -> list[str]:
    return [" ".join(sentences) for sentences in paragraphs if sentences]


def fallback_paragraphs(subject: str, details: str | None) -> list[str]:
    """Model çıktısı doğrulanamazsa kullanıcının kendi olguları: cümlelere bölünür, aynen kullanılır.

    Olgu verilmemişse konu cümlesi ilk paragraf olur ve ayrıntı için boşluk bırakılır (bölüm tümüyle boş kalmaz).
    """
    text = " ".join((details or "").split())
    sentences = [part for part in split_sentences(text) if len(part) > 3]
    if sentences:
        return sentences
    gap = f"{GAP} (olayları, tarihleri ve tutarları burada anlatın)"
    topic = " ".join(subject.split()).rstrip(".")
    return [f"Dava konusu: {topic}.", gap] if topic else [gap]


def _numbered(paragraphs: list[str]) -> str:
    return "\n\n".join(f"{index}. {paragraph}" for index, paragraph in enumerate(paragraphs, start=1))


def _legal_section(legal: Legal) -> str:
    if not legal.suggested and not legal.statutes and not legal.decisions:
        return f"{GAP} _(Korpusta bu konuyla eşleşen doğrulanmış kaynak bulunamadı; hukuki nedenleri avukat eklemelidir.)_"
    lines: list[str] = []
    if legal.suggested:
        lines.append("_Konuya göre otomatik önerilen maddeler (resmî metinle doğrulandı; uygunluğunu avukat kontrol etmelidir):_")
        lines.extend(f"- {line}" for line in legal.suggested)
    if legal.statutes:
        if lines:
            lines.append("")
        lines.append("_Aramada bulunan diğer mevzuat (ilgisini kontrol edin):_")
        lines.extend(f"- {line}" for line in legal.statutes)
    if not legal.suggested and not legal.statutes:
        lines.append(f"{GAP} _(Mevzuat dayanağı otomatik belirlenemedi; avukat eklemelidir.)_")
    if legal.decisions:
        lines.append("")
        lines.append("_İlgili görülen emsal kararlar (otomatik bulundu, ilgisini kontrol edin):_")
        lines.extend(f"- {line}" for line in legal.decisions)
    return "\n".join(lines)


# Kullanıcı tarafları "Davacı: Ayşe Demir" diye yazabilir; iskelet zaten "DAVACI:" başlığını basar ("DAVACI: Davacı: Ayşe Demir"
# çıkıyordu, ölçüldü: 2026-10-05). Rol öneki atılır ve taraf doğru sıraya konur (ilk sıra: davacı/keşideci/kiraya veren...).
_FIRST_ROLES = ("davacı", "davaci", "keşideci", "kesideci", "alacaklı", "alacakli", "başvuran", "basvuran", "kiraya veren", "satıcı", "işveren", "müvekkil")
_SECOND_ROLES = ("davalı", "davali", "muhatap", "borçlu", "borclu", "karşı taraf", "karsi taraf", "kiracı", "kiraci", "alıcı", "işçi")
_ROLE_PREFIX = re.compile(
    r"^\s*(" + "|".join(sorted((*_FIRST_ROLES, *_SECOND_ROLES), key=len, reverse=True)) + r")\b\s*(?:vekili\s*)?[:\-–]?\s+(.+)$",
    re.IGNORECASE,
)


def order_parties(parties: list[str]) -> list[str]:
    """Rol öneklerini ("Davalı: X") atar ve tarafları [birinci taraf, ikinci taraf, ...] sırasına koyar."""
    first: list[str] = []
    second: list[str] = []
    rest: list[str] = []
    for raw in parties:
        text = " ".join(raw.split())
        if not text:
            continue
        match = _ROLE_PREFIX.match(text.replace("İ", "i").replace("I", "ı") if text[:1] in "İI" else text)
        role = match.group(1).replace("İ", "i").lower().strip() if match else ""
        if role in _FIRST_ROLES:
            first.append(match.group(2).strip())
        elif role in _SECOND_ROLES:
            second.append(match.group(2).strip())
        else:
            rest.append(text)
    if not first and not second:
        return rest
    ordered = [", ".join(first) if first else (rest.pop(0) if rest else ""), ", ".join(second) if second else (rest.pop(0) if rest else "")]
    return [*ordered, *rest]


def _party(parties: list[str], index: int) -> str:
    return parties[index].strip() if len(parties) > index and parties[index].strip() else GAP


def build_document(doc_type: str, title: str | None, parties: list[str], subject: str, paragraphs: list[str], legal: Legal,
                   draft_fields: DraftFields | dict | None = None) -> str:
    fields = draft_fields if isinstance(draft_fields, DraftFields) else DraftFields.model_validate(draft_fields or {})
    def supplied(name: str) -> str:
        return _field_text(fields, name)
    label = DOC_LABELS.get(doc_type, DOC_LABELS["diger"])
    subject_line = short_subject(subject)
    body = _numbered(paragraphs)
    # A short KONU line is presentation only, not permission to drop the rest.
    full_subject = " ".join(subject.split())
    if doc_type != "sozlesme" and full_subject.rstrip(".") != subject_line and full_subject not in " ".join(paragraphs):
        body = f"Konuya ilişkin verilen açıklama: {full_subject}\n\n{body}"
    parties = order_parties(parties)
    head = f"# {title.strip() if title and title.strip() else label}"
    if doc_type == "dilekce":
        parts = [
            head, "", f"**{supplied('authority') if fields.authority.strip() else GAP + ' MAHKEMESİNE'}**", "",
            f"**DAVACI:** {_party(parties, 0)}", f"**VEKİLİ:** {supplied('representative')}", f"**DAVALI:** {_party(parties, 1)}", "",
            f"**KONU:** {subject_line}", "", "**AÇIKLAMALAR:**", "", body, "",
            "**HUKUKİ NEDENLER:**", "", _legal_section(legal), "",
            f"**DELİLLER:** {supplied('evidence')}", "",
            "**SONUÇ VE İSTEM:**", "",
            supplied('requests'),
            "", f"Davacı Vekili Av. {GAP}",
        ]
    elif doc_type == "ihtarname":
        parts = [
            head, "", f"**KEŞİDECİ:** {_party(parties, 0)}", f"**MUHATAP:** {_party(parties, 1)}", "", f"**KONU:** {subject_line}", "",
            "**AÇIKLAMALAR:**", "", body, "", "**DAYANAK:**", "", _legal_section(legal), "",
            "**İHTAR:**", "",
            f"**Talep edilen işlem:** {supplied('notice_demand')}",
            f"**Süre ve başlangıcı:** {supplied('notice_period')}",
            f"**Yerine getirilmemesi hâlindeki bildirim:** {supplied('notice_consequence')}",
            f"**Tarih:** {supplied('effective_date')}",
            "", f"Keşideci / Vekili: {GAP}",
        ]
    elif doc_type == "sozlesme":
        parts = [
            head, "", f"**TARAFLAR:** {_party(parties, 0)} ile {_party(parties, 1)}", "",
            f"**MADDE 1 – Sözleşmenin konusu:** {subject.strip()}", "", "**Olgular ve ön açıklamalar:**", "", body, "",
            f"**MADDE 2 – Bedel ve ödeme koşulları:** {supplied('payment')}", f"**MADDE 3 – Süre:** {supplied('term')}", f"**MADDE 4 – Tarafların hak ve yükümlülükleri:** {supplied('obligations')}",
            f"**MADDE 5 – Sona erme ve fesih:** {supplied('termination')}", f"**MADDE 6 – Gizlilik ve kişisel veriler:** {supplied('confidentiality')}", f"**MADDE 7 – Uyuşmazlık çözümü ve yetkili mahkeme:** {supplied('dispute')}",
            f"**MADDE 8 – Yürürlük:** {supplied('effective_date')}", "", "**Mevzuat dayanakları (otomatik; avukat kontrol etmelidir):**", "", _legal_section(legal), "",
            f"İmzalar: {_party(parties, 0)} / {_party(parties, 1)}  {GAP} (tarih)",
        ]
    else:
        parts = [
            head, "", f"**KONU:** {subject_line}", "", "**AÇIKLAMALAR:**", "", body, "",
            "**HUKUKİ NEDENLER:**", "", _legal_section(legal), "", f"**SONUÇ VE İSTEM:** {GAP}", "", f"{GAP} (tarih ve imza)",
        ]
    # Her parça kendi paragrafıdır: Markdown tek satır sonunu boşluğa çevirdiğinden (DAVACI/VEKİLİ/DAVALI satırları birleşirdi) boş satırla ayrılır.
    return "\n\n".join(part for part in parts if part != "") + f"\n\n---\n{NOTICE}\n"
