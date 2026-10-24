"""Konu → ilgili kanun maddesi ipuçları: dilekçe taslağı ve risk incelemesinde "ilk bakılacak maddeler" listesi.

Bu tablo hukuki cevap ya da kanıt DEĞİLDİR; yalnız hangi maddenin getirileceğini söyleyen bir arama ipucudur (bkz. `api.ai.relevance`
içindeki aynı ilke). Güvence iki katmandır:

* **Kaynak yine korpustur.** Bir ipucu ancak o madde korpusta resmî doğrulanmış ve güncel olarak bulunuyorsa listelenir; madde adı
  ve bağlantısı veritabanından gelir, bu dosyadan değil. Madde korpusta yoksa satır hiç gösterilmez.
* **Metin denetimi.** Her ipucu, getirilen madde metninde bulunması gereken sözcüklerle (`expect`) gelir; metin bu sözcükleri
  içermiyorsa (numara kaymış, madde değişmiş) ipucu atılır. Tablodaki her satır korpustaki resmî metne karşı bu denetimle
  doğrulandı (ilk tablo 2026-10-05, eklenen konular 2026-10-08); `scripts/verify_statute_hints.py` aynı denetimi istendiğinde tekrarlar.

Liste her zaman "otomatik öneri; uygunluğunu avukat kontrol etmelidir" diye sunulur. Tabloda olmayan konular için öneri yapılmaz.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from api.ai.search_plan import normalize


@dataclass(frozen=True)
class Hint:
    law_no: str
    article_no: str
    # Madde metninde (küçük harf, Türkçe katlanmamış) bulunması gereken sözcük köklerinden en az biri.
    expect: tuple[str, ...]
    # Maddenin, bu konunun ASIL KURALINI koyan cümlesinin ayırt edici parçası; resmî metinde aynen geçer
    # (`scripts/verify_statute_hints.py` denetler). Model o maddeden başka bir cümle seçip bunu atlarsa cevaba bu cümle de eklenir
    # (bkz. `api.ai.evidence_selection.include_rule_sentences`). Boşsa böyle bir güvence yoktur.
    anchor: str = ""


@dataclass(frozen=True)
class Topic:
    name: str
    # Her grup içinden en az bir kök olay metninde geçmelidir (gruplar VE ile bağlanır).
    groups: tuple[tuple[str, ...], ...]
    hints: tuple[Hint, ...]
    # Bu köklerden biri geçiyorsa konu eşleşmez (ör. "kira artışı" temerrüt değildir).
    unless: tuple[str, ...] = ()


def _h(law: str, article: str, *expect: str, anchor: str = "") -> Hint:
    return Hint(law, article, tuple(expect), anchor)


TOPICS: tuple[Topic, ...] = (
    Topic("kira_temerrut", (("kira", "kiracı"), ("ödenme", "ödeme", "temerrüt", "tahliye", "borc")),
          (_h("6098", "315", "temerrüd", "ifa etmez", anchor="yazılı olarak bir süre verip"), _h("6098", "352", "ihtar", "tahliye")), unless=("artış", "artır", "tüfe")),
    Topic("kira_icra_tahliye", (("kira", "kiracı"), ("ödeme emri", "icra", "takip")), (_h("2004", "269", "kira", "ödeme emri"),)),
    Topic("kira_artis", (("kira",), ("artış", "artır", "tüfe", "tespit")), (_h("6098", "344", "tüketici fiyat"), _h("6098", "345", "kira bedeli"))),
    Topic("kira_ihtiyac", (("kira", "kiracı"), ("ihtiyaç", "gereksinim", "yeniden inşa", "imar")), (_h("6098", "350", "gereksinim"), _h("6098", "351", "edinen"))),
    Topic("kidem", (("kıdem",), ("tazminat",)), (_h("1475", "14", "kıdem tazminat", anchor="her geçen tam yıl için işverence işçiye 30 günlük ücreti tutarında kıdem tazminatı ödenir"),)),
    Topic("ihbar", (("ihbar tazminat", "bildirim süre", "ihbar öneli"),), (_h("4857", "17", "bildirim", anchor="Bildirim şartına uymayan taraf"),)),
    Topic("fazla_calisma", (("fazla mesai", "fazla çalışma", "fazla sürelerle"),), (_h("4857", "41", "fazla çalışma", anchor="yüzde elli yükseltilmesi suretiyle ödenir"),)),
    # "izin" ek alınca ünlüsü düşer ("izne", "izni"): iki yazılış da aranır.
    Topic("yillik_izin", (("yıllık izin", "yıllık ücretli izin", "yıllık izn", "yıllık ücretli izn"),),
          (_h("4857", "53", "yıllık ücretli izin", anchor="en az bir yıl çalışmış olan işçilere"), _h("4857", "59", "izin ücret"))),
    # Daha özel konu önce gelir: boru hattı ilk iki ipucunu kullanır. "Geçersiz feshin sonuçları" sorusunda m. 21 öne geçmelidir.
    # "fesh" kökü "fesih/feshin/feshi/feshedilme" yazımlarının hepsini kapsar (ünlü düşmesi).
    Topic("gecersiz_fesih_sonuc", (("geçersiz fesh", "geçersiz fesih", "feshin geçersiz", "işe başlatma", "işe başlatıl"),
                                   ("sonuç", "tazminat", "boşta geçen", "işe başlat", "ücret")),
          (_h("4857", "21", "işe başlat", anchor="işe başlatmak zorundadır"),)),
    Topic("ise_iade", (("işe iade", "geçersiz fesih", "geçersiz fesh", "feshin geçersiz", "geçerli sebep", "geçerli neden"),),
          (_h("4857", "18", "geçerli", anchor="geçerli bir sebebe dayanmak zorundadır"),
           _h("4857", "20", "fesih bildirim", anchor="arabulucuya başvurmak zorundadır"),
           _h("4857", "21", "işe başlat", anchor="işe başlatmak zorundadır"))),
    Topic("haksiz_fesih_tazminat", (("haksız fesih", "haksız fesh", "haksız olarak fesh", "haksız şekilde fesh"),
                                    ("işçi", "iş sözleşme", "iş akd", "hizmet akd", "işveren")),
          (_h("4857", "17", "bildirim", anchor="Bildirim şartına uymayan taraf"), _h("1475", "14", "kıdem tazminat", anchor="her geçen tam yıl için işverence işçiye 30 günlük ücreti tutarında kıdem tazminatı ödenir"))),
    # The same already-validated retrieval hints for everyday first-person
    # narratives. These are candidate sources, never an entitlement decision.
    Topic("isten_cikarilma_anlatimi", (("çalıştım", "çalışıyordum", "işveren", "işyer", "işten", "maaş", "ücretim"),
                                       ("çıkarıldım", "çıkardı", "işten çıkar", "işten at", "kovuldum")),
          (_h("4857", "17", "bildirim", anchor="Bildirim şartına uymayan taraf"),
           _h("1475", "14", "kıdem tazminat", anchor="her geçen tam yıl için işverence işçiye 30 günlük ücreti tutarında kıdem tazminatı ödenir"))),
    Topic("esit_davranma", (("eşit davranma", "eşit işlem borc", "ayrımcılık tazminat"),), (_h("4857", "5", "ayrım yapılamaz", "eşit davranma", anchor="ayrım yapılamaz"),)),
    Topic("is_arabuluculuk", (("arabulucu",), ("işçi", "işe iade", "işveren", "iş mahkeme", "işçilik", "iş uyuşmazl", "iş davas", "iş hukuk")),
          (_h("7036", "3", "arabulucu", anchor="arabulucuya başvurulmuş olması dava şartıdır"),)),
    Topic("hakli_fesih_isci", (("işçi",), ("haklı neden", "haklı sebep", "derhal fesih")), (_h("4857", "24", "işçinin haklı"),)),
    Topic("hakli_fesih_isveren", (("işveren",), ("haklı neden", "haklı sebep", "derhal fesih", "devamsızlık", "mazeretsiz")), (_h("4857", "25", "işverenin haklı"),)),
    Topic("bosanma", (("boşan",),), (_h("4721", "166", "evlilik birliği", anchor="eşlerden her biri boşanma davası açabilir"),)),
    Topic("bosanma_tazminat", (("boşan",), ("tazminat",)), (_h("4721", "174", "tazminat"),)),
    Topic("nafaka", (("nafaka",),), (_h("4721", "169", "geçici önlem", "geçim"), _h("4721", "175", "yoksulluğa"), _h("4721", "182", "çocu"))),
    Topic("velayet", (("velayet", "velâyet"),), (_h("4721", "182", "çocu"), _h("4721", "336", "velâyet", "velayet"))),
    Topic("tuketici_ayipli_mal", (("ayıplı mal", "ayıplı ürün", "ayıplı araç"),), (_h("6502", "8", "ayıplı mal"), _h("6502", "11", "seçimlik", anchor="Malın ayıplı olduğunun anlaşılması durumunda tüketici"))),
    Topic("tuketici_ayipli_hizmet", (("ayıplı hizmet",),), (_h("6502", "13", "ayıplı hizmet"), _h("6502", "15", "seçimlik"))),
    Topic("satis_ayip", (("ayıp",), ("satış", "satıcı", "alıcı")), (_h("6098", "219", "ayıp"), _h("6098", "227", "seçimlik"))),
    Topic("haksiz_fiil", (("haksız fiil", "trafik kaza", "maddi tazminat", "manevi tazminat", "yaralan"),),
          (_h("6098", "49", "kusurlu"), _h("6098", "56", "manevi"))),
    Topic("trafik_kazasi", (("trafik kaza",),), (_h("2918", "85", "işleten"),)),
    Topic("itirazin_iptali", (("itirazın iptal",),), (_h("2004", "67", "itirazın iptal"),)),
    Topic("itirazin_kaldirilmasi", (("itirazın kaldırıl",),), (_h("2004", "68", "itirazın kaldırıl"),)),
    Topic("menfi_tespit", (("menfi tespit", "istirdat"),), (_h("2004", "72", "menfi tespit"),)),
    Topic("ihtiyati_tedbir", (("ihtiyati tedbir",),), (_h("6100", "389", "ihtiyati tedbir"),)),
    Topic("ihtiyati_haciz", (("ihtiyati haciz",),), (_h("2004", "257", "ihtiyati haciz"),)),
    Topic("sebepsiz_zenginlesme", (("sebepsiz zenginleş",),), (_h("6098", "77", "zenginleş"),)),
    Topic("borclu_temerrudu", (("temerrüt faizi", "borçlunun temerrüd", "alacağın tahsili", "alacak davası"),), (_h("6098", "117", "temerrüd"),)),
    Topic("eser_ayip", (("eser sözleşme", "yüklenici", "müteahhit"), ("ayıp", "eksik")), (_h("6098", "474", "ayıp"), _h("6098", "475", "ayıp"))),
    Topic("ortakligin_giderilmesi", (("ortaklığın giderilmesi", "izale-i şüyu", "izalei şuyu", "paylaşma davası"),), (_h("4721", "698", "paylaşma"), _h("4721", "699", "paylaşma"))),
    Topic("mirasin_reddi", (("mirasın redd", "reddi miras"),), (_h("4721", "605", "redde"),)),
    Topic("tenkis", (("tenkis", "saklı pay"),), (_h("4721", "560", "tenkis"),)),
    Topic("idari_iptal", (("iptal davası",), ("idari", "idare", "danıştay")), (_h("2577", "7", "dava açma süresi"),)),
    Topic("tam_yargi", (("tam yargı",),), (_h("2577", "12", "tam yargı"), _h("2577", "13", "idari eylem"))),
    Topic("aidat", (("aidat", "ortak gider", "kat malik"),), (_h("634", "20", "gider"),)),
    Topic("idari_istinaf", (("istinaf",), ("idari", "idare mahkeme", "vergi mahkeme", "bölge idare", "danıştay")), (_h("2577", "45", "istinaf", anchor="İdare ve vergi mahkemelerinin kararlarına karşı"),)),
    Topic("idari_temyiz", (("temyiz",), ("idari", "idare mahkeme", "vergi mahkeme", "bölge idare", "danıştay")), (_h("2577", "46", "temyiz"),)),
    Topic("kdk_basvuru", (("kamu denetçi", "ombudsman"), ("başvur", "şikayet")), (_h("6328", "17", "başvur", anchor="Kuruma başvuruda bulunulabilmesi için"),)),
    # 6216 sayılı Kanun (başvuru süresi ve usulü: m. 45-47) korpusta yok (2026-10-08); bulunan tek resmî dayanak Anayasa m. 148'dir.
    Topic("aym_bireysel_basvuru", (("bireysel başvuru",),), (_h("2709", "148", "bireysel başvuru"),)),
    Topic("adil_yargilanma", (("adil yargılanma", "hak arama hürriyet", "hak arama özgürlü"),), (_h("2709", "36", "adil yargılanma"),)),
)

MAX_HINTS = 6


def suggest(text: str) -> list[Hint]:
    """Olay/konu metniyle eşleşen konuların madde ipuçları (yinelenenler atılır, en çok `MAX_HINTS`)."""
    value = normalize(text)
    found: list[Hint] = []
    for topic in TOPICS:
        if any(term in value for term in topic.unless):
            continue
        if all(any(term in value for term in group) for group in topic.groups):
            for hint in topic.hints:
                if all((hint.law_no, hint.article_no) != (other.law_no, other.article_no) for other in found):
                    found.append(hint)
    return found[:MAX_HINTS]


def text_matches(hint: Hint, article_text: str) -> bool:
    """Getirilen madde metni ipucunun beklediği sözcüklerden birini içeriyor mu (numara kayması denetimi)."""
    value = normalize(article_text)
    return any(normalize(expected) in value for expected in hint.expect)


_SQL = """
SELECT ls.id, ls.source_url, legislation.law_name, legislation.law_no, legislation.article_no, legislation.article_title,
       (SELECT string_agg(chunk.content, E'\\n' ORDER BY chunk.chunk_index) FROM legal_chunks chunk WHERE chunk.legal_source_id = ls.id) AS content
FROM legislation_details legislation
JOIN legal_sources ls ON ls.id = legislation.legal_source_id
WHERE legislation.law_no = %(law_no)s AND legislation.article_no = %(article_no)s
  AND ls.source_type = 'legislation' AND ls.deleted_at IS NULL AND ls.is_current AND ls.ingest_status = 'ready'
  AND (
    (ls.metadata->>'verified_against_gazette' = 'true' OR ls.metadata->>'verified_against_mbs' = 'true')
    OR ls.metadata->>'verified_text_against_mbs' = 'true'
  )
LIMIT 1
"""

_TITLE_NOISE = re.compile(r"^\s*madde\s*no\s*:?\s*\d+\s*$", re.IGNORECASE)


def load_verified(connection, hints: list[Hint]) -> list[dict]:
    """İpuçlarından korpusta resmî doğrulanmış, güncel ve metni beklentiyle uyuşan maddeler (gösterime hazır)."""
    rows: list[dict] = []
    for hint in hints:
        row = connection.execute(_SQL, {"law_no": hint.law_no, "article_no": hint.article_no}).fetchone()
        if row is None or not text_matches(hint, row["content"] or ""):
            continue
        title = (row["article_title"] or "").strip().rstrip(":")
        line = f"{' '.join(row['law_name'].split())} ({row['law_no']}) m. {row['article_no']}"
        if title and not _TITLE_NOISE.match(title):
            line += f" — {title}"
        rows.append({"reference": line, "source_url": row["source_url"], "verification": "official", "source_type": "legislation",
                     "law_no": row["law_no"], "article_no": row["article_no"], "source_id": str(row["id"])})
    return rows
