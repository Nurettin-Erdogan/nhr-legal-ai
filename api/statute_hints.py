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
    # Procedural evidence is independent of the underlying dispute. These are
    # retrieval addresses only; the official corpus text remains the evidence.
    Topic("dava_sarti_arabuluculuk", (("arabulucu",),),
          (_h("6325", "18/B", "kira ilişkisinden", "komşu hakkından"),
           _h("6325", "18/A", "dava şartı", "son tutana"))),
    Topic("kira_temerrut", (("kira", "kiracı"), ("ödenme", "ödeme", "ödemiyor", "ödemedi", "temerrüt", "borc")),
          (_h("6098", "315", "temerrüd", "ifa etmez", anchor="yazılı olarak bir süre verip"), _h("6098", "352", "ihtar", "tahliye")), unless=("artış", "artır", "tüfe")),
    Topic("kira_icra_tahliye", (("kira", "kiracı"), ("ödeme emri", "icra", "takip")), (_h("2004", "269", "kira", "ödeme emri"),)),
    # 2026-10-30: "Kira sözleşmesi bitti ama kiracı evi boşaltmıyor, tahliye için ne yapmalıyım?" yalnız temerrüt maddelerini getirdi; konutta
    # sözleşmenin süre bitiminde kendiliğinden uzaması (m. 347) ve icra yoluyla tahliye (İİK m. 272) hiç gelmedi. Ödememe sözcüğü geçen soru
    # temerrüt konusunda kalır.
    Topic("kira_sure_tahliye", (("kira", "kiracı", "ev sahibi"), ("tahliye", "boşalt", "boşaltmıyor", "çıkmıyor", "bitti", "sona erdi", "süresi bit")),
          (_h("2004", "272", "tahliye"), _h("6098", "347", "uzatılmış sayılır", anchor="sözleşme aynı koşullarla bir yıl için uzatılmış sayılır")),
          unless=("ödenme", "ödemi", "ödemedi", "ödemez", "temerrüt", "borc", "artış", "artır", "tüfe", "depozito")),
    Topic("kira_artis", (("kira",), ("artış", "artır", "tüfe", "tespit", "zam yap", "zam gel", "zamm", "zamlı")),
          (_h("6098", "344", "tüketici fiyat", anchor="Tarafların yenilenen kira dönemlerinde uygulanacak kira bedeline ilişkin anlaşmaları"),
           _h("6098", "345", "kira bedeli"))),
    # Gündelik sorular (2026-10-24): depozito, sözleşmenin uzaması ve kira alacağının zamanaşımı kira sorularında en sık gelenlerdir.
    Topic("kira_depozito", (("depozito", "güvence bedel", "teminat"), ("kira", "kiracı", "ev sahibi")),
          (_h("6098", "342", "güvence", anchor="bu güvence üç aylık kira bedelini aşamaz"),)),
    Topic("kira_uzama", (("kira", "kiracı", "ev sahibi"), ("süresi bit", "süre bit", "uzar", "uzamış", "uzatıl", "yenilen", "sözleşmeyi sona", "çıkarabilir", "çıkarmak")),
          (_h("6098", "347", "uzatılmış sayılır", anchor="sözleşme aynı koşullarla bir yıl için uzatılmış sayılır"),), unless=("artış", "artır", "tüfe")),
    Topic("kira_zamanasimi", (("zamanaşımı", "zaman aşımı"), ("kira bedel", "kira alacağ", "kira borc")),
          (_h("6098", "147", "kira bedelleri", anchor="Kira bedelleri, anapara faizleri ve ücret gibi diğer dönemsel edimler"),)),
    Topic("kira_ihtiyac", (("kira", "kiracı"), ("ihtiyaç", "gereksinim", "yeniden inşa", "imar")), (_h("6098", "350", "gereksinim"), _h("6098", "351", "edinen"))),
    Topic("kidem", (("kıdem",), ("tazminat",)), (_h("1475", "14", "kıdem tazminat", anchor="her geçen tam yıl için işverence işçiye 30 günlük ücreti tutarında kıdem tazminatı ödenir"),)),
    # 2026-10-25: "Kıdem ve ihbarı alabilir miyim, hangi durumlarda alamam?" kıdemi kaybettiren haklı feshi (1475 m. 14'ün
    # atıf yaptığı "17/II", bugün 4857 m. 25/II) hiç getirmiyordu; cevap "alamazsınız" kısmını hep atlıyordu.
    Topic("kidem_kaybi", (("kıdem",), ("alama", "alamaz", "hangi durum", "kaybed", "hak kazanama", "ödenmez", "yanar")),
          (_h("4857", "25", "ahlak ve iyi niyet"),)),
    Topic("ihbar", (("ihbar tazminat", "bildirim süre", "ihbar öneli"),), (_h("4857", "17", "bildirim", anchor="Bildirim şartına uymayan taraf"),)),
    Topic("fazla_calisma", (("fazla mesai", "fazla çalışma", "fazla sürelerle"),), (_h("4857", "41", "fazla çalışma", anchor="yüzde elli yükseltilmesi suretiyle ödenir"),)),
    # "izin" ek alınca ünlüsü düşer ("izne", "izni"): iki yazılış da aranır.
    Topic("yillik_izin", (("yıllık izin", "yıllık ücretli izin", "yıllık izn", "yıllık ücretli izn"),),
          (_h("4857", "53", "yıllık ücretli izin", anchor="en az bir yıl çalışmış olan işçilere"), _h("4857", "59", "kullanmadığı yıllık izin"))),
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
    Topic("hakli_fesih_isci", (("işçi",), ("haklı neden", "haklı sebep", "derhal fesih")), (_h("4857", "24", "işçi, aşağıda yazılı hallerde iş sözleşmesini"),)),
    Topic("hakli_fesih_isveren", (("işveren",), ("haklı neden", "haklı sebep", "derhal fesih", "devamsızlık", "mazeretsiz")), (_h("4857", "25", "işveren, aşağıda yazılı hallerde iş sözleşmesini"),)),
    Topic("bosanma", (("boşan",),), (_h("4721", "166", "evlilik birliği", anchor="eşlerden her biri boşanma davası açabilir"),)),
    Topic("bosanma_tazminat", (("boşan",), ("tazminat",)), (_h("4721", "174", "tazminat"),)),
    Topic("nafaka", (("nafaka",),), (_h("4721", "169", "geçici önlem", "geçim"), _h("4721", "175", "yoksulluğa"), _h("4721", "182", "çocu"))),
    Topic("velayet", (("velayet", "velâyet"),), (_h("4721", "182", "çocu"), _h("4721", "336", "velâyet", "velayet"))),
    # 2026-10-30: "Aldığım telefon iki ayda bozuldu, satıcıdan neler isteyebilirim?" yalnız "ayıplı mal" denince eşleşiyordu; "telefon"
    # sözcüğünden ceza infaz mevzuatı ve ceza dairesi kararları geldi, tüketici kanunu hiç gelmedi. Günlük anlatım aynı maddelere bağlanır.
    Topic("tuketici_ayipli_mal", (("ayıplı mal", "ayıplı ürün", "ayıplı araç", "ayıplı", "bozuldu", "bozulan", "arızalandı", "arızalı",
                                   "defolu", "garantisi", "garanti kapsam", "değişim hakk", "iade etmek istiyorum"),
                                  ("satıcı", "mağaza", "tüketici", "aldığım", "aldık", "satın aldı", "ürün", "telefon", "cihaz", "araç",
                                   "ayıplı mal", "ayıplı ürün")),
          (_h("6502", "11", "seçimlik", anchor="Malın ayıplı olduğunun anlaşılması durumunda tüketici"), _h("6502", "10", "altı ay"),
           _h("6502", "12", "zamanaşımı", anchor="iki yıllık zamanaşımına tabidir"), _h("6502", "8", "ayıplı mal"))),
    Topic("tuketici_ayipli_hizmet", (("ayıplı hizmet",),), (_h("6502", "13", "ayıplı hizmet"), _h("6502", "15", "seçimlik"))),
    Topic("satis_ayip", (("ayıp",), ("satış", "satıcı", "alıcı")), (_h("6098", "219", "ayıp"), _h("6098", "227", "seçimlik"))),
    # TMK m. 919-1030 korpusa 2026-10-24'te eklendi (sunucu taramasıyla bulunan eksik); yolsuz tescil = tapu iptal ve tescil davasının dayanağı.
    Topic("tapu_iptal_tescil", (("tapu",), ("iptal", "yolsuz tescil", "tescil davası", "tescil")),
          (_h("4721", "1025", "yolsuz", anchor="Bir aynî hak yolsuz olarak tescil edilmiş"), _h("4721", "1023", "iyiniyet"), _h("4721", "716", "tescil"))),
    Topic("haksiz_fiil_zamanasimi", (("zamanaşımı", "zaman aşımı"), ("haksız fiil", "trafik kaza", "kazası", "kazada", "yaralan", "maddi tazminat", "manevi tazminat")),
          (_h("6098", "72", "zamanaşımına uğrar", anchor="iki yılın ve her hâlde fiilin işlendiği tarihten başlayarak on yılın geçmesiyle zamanaşımına uğrar"),),
          unless=("kıdem", "ihbar", "iş sözleşme", "işçi", "kira")),
    Topic("haksiz_fiil", (("haksız fiil", "trafik kaza", "maddi tazminat", "manevi tazminat", "yaralan"),),
          (_h("6098", "49", "kusurlu"), _h("6098", "56", "manevi"))),
    # 2026-10-30: "Hakaret suçundan şikayet var, şikayet süresi nedir, uzlaştırma ne demek?" kamu ihale ve alan adı mevzuatı getirip cevapsız kaldı;
    # TCK/CMK korpusta var, konu ipucu yoktu. Aynı gün: trafik idari para cezasına itiraz (Kabahatler Kanunu m. 27: 15 gün, sulh ceza hakimliği).
    Topic("sikayet_suresi", (("şikayet süre", "şikâyet süre", "şikayet hakk", "şikâyet hakk", "şikayete bağlı", "şikâyete bağlı"),),
          (_h("5237", "73", "şikayet", "şikâyet"),)),
    Topic("uzlastirma", (("uzlaştır", "uzlaşma"),), (_h("5271", "253", "uzlaştırma"),)),
    Topic("hakaret", (("hakaret", "sövme"),), (_h("5237", "125", "onur"), _h("5237", "73", "şikayet", "şikâyet"))),
    Topic("idari_para_cezasi_itiraz", (("idari para ceza", "idarî para ceza", "idari yaptırım", "trafik ceza", "trafik para ceza"),
                                       ("itiraz", "süre", "nasıl", "iptal", "dava")),
          (_h("5326", "27", "sulh ceza"),)),
    Topic("trafik_kazasi", (("trafik kaza",),), (_h("2918", "85", "işleten"),)),
    # 2026-10-30: "Trafik kazasında araç hasarı ve yaralanma... kimden hangi tazminatı isteyebilirim?" yalnız m. 85'i getirdi; zorunlu sigorta
    # (m. 91, kapsam dışı m. 92) ve kazadan doğan zararlarda zamanaşımı (m. 109: iki yıl, en geç on yıl) hiç gelmedi.
    Topic("trafik_sigorta", (("trafik kaza", "araç kaza", "motorlu araç", "trafik sigorta", "zorunlu mali"),
                             ("sigorta", "kasko", "araç hasar", "hasar", "tazminat", "kimden")),
          (_h("2918", "91", "mali sorumluluk sigortası"), _h("2918", "92", "kapsamı dışında"))),
    Topic("trafik_zamanasimi", (("trafik kaza", "araç kaza", "motorlu araç"), ("zamanaşımı", "zaman aşımı", "dava süresi", "dava açma süresi", "ne kadar süre", "hangi süre")),
          (_h("2918", "109", "iki yıl", "on yıl"),)),
    Topic("itirazin_iptali", (("itirazın iptal",),), (_h("2004", "67", "itirazın iptal"),)),
    Topic("ilamsiz_takip_dayanak", (("ilamsız", "icra takib"), ("senet", "borç", "para alacağ")),
          (_h("2004", "42", "paranın ödenmesine", "teminatın verilmesine"), _h("2004", "58", "senet yoksa borcun sebebi"))),
    Topic("takibe_itiraz_yollari", (("ilamsız", "icra", "takip", "takibe"), ("itiraz",)),
          (_h("2004", "62", "itiraz etmek", "yedi gün"), _h("2004", "66", "itiraz takibi durdurur"), _h("2004", "67", "itirazın iptal"),
           _h("2004", "68", "itirazın kaldırıl"))),
    Topic("itirazin_kaldirilmasi", (("itirazın kaldırıl",),), (_h("2004", "68", "itirazın kaldırıl"),)),
    Topic("menfi_tespit", (("menfi tespit", "istirdat"),), (_h("2004", "72", "menfi tespit"),)),
    Topic("ihtiyati_tedbir", (("ihtiyati tedbir",),), (_h("6100", "389", "ihtiyati tedbir"),)),
    Topic("ihtiyati_haciz", (("ihtiyati haciz",),), (_h("2004", "257", "ihtiyati haciz"),)),
    Topic("sebepsiz_zenginlesme", (("sebepsiz zenginleş",),), (_h("6098", "77", "zenginleş"),)),
    Topic("borclu_temerrudu", (("temerrüt faizi", "borçlunun temerrüd", "alacağın tahsili", "alacak davası"),), (_h("6098", "117", "temerrüd"),)),
    Topic("eser_ayip", (("eser sözleşme", "yüklenici", "müteahhit"), ("ayıp", "eksik")), (_h("6098", "474", "ayıp"), _h("6098", "475", "ayıp"))),
    Topic("ortakligin_giderilmesi", (("ortaklığın giderilmesi", "izale-i şüyu", "izalei şuyu", "paylaşma davası"),), (_h("4721", "698", "paylaşma"), _h("4721", "699", "paylaşma"))),
    # 2026-10-25: "Mirası reddetmek istiyorum, süresi ne kadar?" 606'yı getirmiyordu (ret süresi); ücret faizi sorusu cevapsız kalıyordu.
    Topic("mirasin_reddi", (("miras", "terekey"), ("redd", "reddet", "ret süre", "ret hak")),
          (_h("4721", "605", "redde"), _h("4721", "606", "üç ay", anchor="Miras, üç ay içinde reddolunabilir"))),
    Topic("ucret_faizi", (("ücret", "maaş", "işçilik alacağ", "alacağ"), ("faiz",), ("işçi", "işveren", "iş sözleşme", "maaş", "ücret")),
          (_h("4857", "34", "ücret", "yirmi gün"), _h("6098", "117", "temerrüd"), _h("6098", "120", "faiz"))),
    # 2026-10-25: "İşçilik alacaklarında zamanaşımı" Ticaret Kanunu ve SGK maddelerini getiriyor, cevap hiç kurulamıyordu.
    Topic("iscilik_zamanasimi", (("zamanaşımı", "zaman aşımı"), ("işçilik", "işçi", "iş sözleşme", "kıdem", "ücret alacağ", "maaş")),
          (_h("6098", "146", "on yıl"), _h("6098", "147", "beş yıl"), _h("4857", "32", "ücret"))),
    Topic("tenkis", (("tenkis", "saklı pay"),), (_h("4721", "560", "tenkis"),)),
    Topic("idari_iptal", (("iptal davası",), ("idari", "idare", "danıştay")), (_h("2577", "7", "dava açma süresi"),)),
    Topic("idari_yargi_gorev", (("idari", "idare", "belediye", "ruhsat"), ("görevli mahkeme", "hangi mahkeme", "görev",)),
          (_h("2576", "5", "idare mahkemeleri"),)),
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


def employment_rights_groups(text: str) -> tuple[frozenset[tuple[str, str]], ...]:
    """Retrieval coverage for an open dismissal-rights question, not entitlements.

    Narrow, dated and explicit-reference questions retain their own source plan.
    Each group is a subject to investigate in verified text; alternative articles
    in one group do not require two repetitive explanations of the same subject.
    """
    value = normalize(text)
    from api.ai.relevance import case_law_requested
    if (case_law_requested(text)
            or re.search(r"\b(?:sadece|yalnız\w*|salt)\b|\b(?:19|20)\d{2}\b|\b\d{1,4}[./-]\d{1,2}[./-]\d{1,4}\b", value)
            or re.search(r"\b\d{4}\s*(?:sayılı|m\.|madde)|\b(?:madde|m\.)\s*\d", value)
            or not re.search(r"işten (?:çıkar\w*|at\w*)|kovul\w*|iş sözleşme\w*.*(?:fesih|fesh|feshed)|işveren.*çıkar\w*", value)
            or not re.search(r"hak\w*\s+(?:ne\w*|hangi\w*)|hangi\s+(?:hak\w*|alacak\w*)|neler\w*\s+(?:talep|istey|alabil)", value)):
        return ()
    return (frozenset({("1475", "14")}), frozenset({("4857", "17")}),
            frozenset({("4857", "32")}), frozenset({("4857", "59")}),
            frozenset({("4857", "18"), ("4857", "20")}))


_EMPLOYMENT_RIGHTS_HINTS = (
    _h("1475", "14", "kıdem tazminat", anchor="her geçen tam yıl için işverence işçiye 30 günlük ücreti tutarında kıdem tazminatı ödenir"),
    _h("4857", "17", "bildirim", anchor="Bildirim şartına uymayan taraf"),
    _h("4857", "32", "iş sözleşmelerinin sona ermesinde", anchor="İş sözleşmelerinin sona ermesinde, işçinin ücreti"),
    _h("4857", "59", "kullanmadığı yıllık izin", anchor="işçinin hak kazanıp da kullanmadığı yıllık izin"),
    _h("4857", "18", "geçerli", anchor="geçerli bir sebebe dayanmak zorundadır"),
    _h("4857", "20", "fesih bildirim", anchor="arabulucuya başvurmak zorundadır"),
)


def suggest(text: str) -> list[Hint]:
    """Olay/konu metniyle eşleşen konuların madde ipuçları (yinelenenler atılır, en çok `MAX_HINTS`)."""
    value = normalize(text)
    found: list[Hint] = list(_EMPLOYMENT_RIGHTS_HINTS) if employment_rights_groups(text) else []
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
  AND legislation.legislation_type IN ('law', 'constitution', 'decree')
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
