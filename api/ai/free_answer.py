"""Kaynaklardan akıcı cevap: model bizim kanun ve kararlarımızı okuyup paragraflar yazar; kaynaktan kopan cümle sessizce çıkar.

Kullanıcı kararı 2026-10-25 (son hâli): "bizim kararları oku, bizim kararlardan güzel bir paragraf çıkar; her yere 'doğrulanamadı'
yazıp durma". Önceki iki düzen şunlardı: (1) kaynakla-sınırlı sentez: her cümle bir kaynak cümlesine mekanik bağlıydı ve sözcük
bazlı kapılar doğru cümleleri reddediyordu (aynı soru 5/5 cevapsız); (2) serbest cevap + cümle başına arama: cevap, kaynağı
olmayan "ezber" cümlelerle doluyordu ve çoğu "doğrulanamadı" etiketi alıyordu (kira sorusunda 16 cümlenin 14'ü; içinde yanlış
bilgi de vardı). Bu düzen ikisinin iyi yanını alır:

1. Model, soru için bulunmuş doğrulanmış kaynakları (mevzuat + Yargıtay/Danıştay kararları) OKUR ve yalnız onlara dayanarak,
   kural → uygulama sırasıyla akıcı paragraflar yazar; her cümleye dayandığı kaynak cümlelerinin numaralarını ekler.
2. Kodun kapıları (`synthesis._checked_claim`, serbest-yol gevşekliğiyle): alıntı gerçekten o kaynakta mı, sayı/birim, eklenen
   alt/üst sınır, mutlaklık, ödeme yönü. Takılan cümle çıkarılır.
3. Bağımsız denetçi (`CHECK_INSTRUCTION`) her cümleyi kaynak metnine karşı sınar; tam onaylanmayan cümle çıkarılır.
4. Cevap yalnız kalan cümlelerden kurulur; paragraf sonlarına gerçek kaynakların atfı [K#] eklenir. Etiket ya da uyarı notu YOK:
   gösterilen her cümle kanıtlıdır. Az cümle kalırsa (`None`) çağıran dürüstçe "doğrulayamadım" der.
"""

from __future__ import annotations

import json
from hashlib import sha256
import logging
import re
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from time import monotonic

from api.ai import synthesis
from api.ai.providers import AIProvider, AIProviderError
from api.ai.rag import HistoryTurn, RAGContext
from api.ai.verification import VerifiedAnswer

logger = logging.getLogger(__name__)

_MIN_SENTENCES_KEPT = 1
_POOL_CHARS = 36_000
_RETRY_ONLY_BEFORE_SECONDS = 45.0
_MIN_SENTENCES_FOR_FINAL = 5  # a single-part answer with fewer proven sentences is rewritten even when the checker only says "incomplete"
_FORMAT_RETRY_BEFORE_SECONDS = 100.0
_MAX_ATTEMPTS = 2  # 3 denemede kredi hızla bitiyordu (2026-10-25); biçim ve kanıt hataları düzeltildikten sonra 2 yeterli

WRITE_INSTRUCTION = """JurisAI Türk hukuk asistanısın. sources içindeki kaynakları (mevzuat ve Yargıtay/Danıştay kararları) OKU ve soruyu
YALNIZ bu kaynaklardaki bilgilerle, bir avukatın müvekkiline anlatır gibi akıcı, açıklayıcı ve sade Türkçeyle cevapla.
ONARIM MODU: Kullanıcı yükünde targeted_repair varsa aşağıdaki bütün cevap/ilk paragraf talimatları yerine yalnız
eksik veya reddedilmiş bilgiyi tamamlayan YENİ cümleleri yaz. Korunan cümleleri eş anlamlı sözcüklerle dahi yeniden
anlatma; yeni giriş veya sonuç özeti yazma. Korunan metin sunucuda kalacak ve yazdığın eklerle birlikte yeniden
denetlenecek. Her ek cümle yine sources kanıt birimlerine bağlanmalıdır; korunan metin hukuki kanıt değildir.
PARÇA MODU: Kullanıcı yükünde write_only_part varsa soru birkaç parçaya bölünmüş ve her parça AYRI bir çağrıda yazılıyor demektir.
Yalnız write_only_part.question parçasını yaz: ilk cümle bu parçanın doğrudan cevabı olsun; diğer parçaları ve bütün sorunun
genel girişini yazma, onlar başka çağrılarda yazılıyor; other_parts_written_separately içindeki konuları ANLATMA ve tekrar etme.
Bu parça için sources içindeki bütün kaynakları kullanabilirsin.
ŞART/KOŞUL/SÜREÇ PARÇALARI: Parça şartları, koşulları, adımları ya da hakları soruyorsa ilk cümleyi birden çok kaynak cümlesini
toplayan bir özet yapma ("şartlar şunlardır: hem işçi hem işyeri…" gibi); denetçi bunu kaynakta olmayan sentez sayıp reddeder ve parça
eksik görünür. Bunun yerine her şartı kendi cümlesinde, tek bir kaynak cümlesine (en çok yanındaki bir iki cümleye) bağlayarak yaz;
ilk cümle şartlardan ilkini söylesin.
Düzen: birbirine bağlı cümleleri AYNI paragrafta art arda satırlara yaz; boş satırı yalnız konu gerçekten değiştiğinde kullan
(her cümleyi ayrı paragraf yapma). Aynı bilgiyi, aynı kaynakla, iki kez yazma.
Bunun dışında bütün diğer kurallar aynen geçerlidir.
Kullanıcı yalnız bir kavramın anlamını soruyorsa kısa tanımla cevapla; kaynaklarda o kavramın geçtiği ilgisiz ödeme,
tarife veya dava örneklerini sırf kaynakta var diye cevaba ekleme. Kaynağın tanımlamadığı özelliği genel bilginden tamamlama.
Kanun maddesini ya da karar cümlesini kopyalama; kendi cümlenle, ama anlamı, koşulu ve istisnayı değiştirmeden anlat.
Kaynağı kullanıcıya tercüme eden bir hukukçu gibi açıkla: teknik terimi gerektiğinde sadeleştir, kuralın sorulan olay bakımından
ne anlama geldiğini yalnız kaynakların desteklediği ölçüde anlat. Kaynak metinlerini arka arkaya yapıştırma; birbirini tekrar eden
bilgileri birleştir. Kullanıcı aynen madde metni veya doğrudan alıntı istemedikçe kaynak cümlelerini aynen aktarmayı tercih etme.
Uzunluğu kullanıcının isteğine göre belirle: kısa/özet isterse kısa, ayrıntı isterse ayrıntılı yaz. Uzunluk belirtilmemişse soruyu
eksiksiz ve anlaşılır yanıtlayacak kadar yaz; gereksiz tekrar ve dolgu yapma. Sabit paragraf veya cümle sayısı sınırı yoktur. Kuralı,
koşullarını, istisnalarını, sürelerini ve sonuçlarını birbirine bağlayarak paragraflar kur. Mevzuat ve karar birlikte varsa önce kuralı
(kanun), sonra uygulamayı (hangi mahkeme ya da daire ne demiş) anlat; karardan söz ederken mahkemeyi/daireyi ve yılı söyle.
Cevap, kullanıcının sorusuna yazılmış TEK ve bütünlüklü bir cevap gibi okunsun: kaynakları tek tek sırayla anlatma, hepsini
harmanlayıp soruyu yanıtla. Soru birden çok parça içeriyorsa (örneğin hem süre hem şart soruluyorsa) her parçayı yanıtla, her
paragraf sorunun bir parçasını cevaplasın. İlk paragraf sorunun kısa ve doğrudan cevabı olsun; yalnız evet/hayır sorusuysa
"evet" ya da "hayır" diye başla. "Haklarım neler?", "Ne yapmalıyım?", "Ne kadar?" sorularında sorulan sonucu veya eksik bilgiyi
doğrudan söyle; ilgisiz bir onayla başlama. Koşulları ve istisnaları sonra aç. Madde numarasını yalnız kullanıcıya yararlıysa an; bir kaynak metni "bu Kanunun 17 nci
maddesi" gibi KENDİ kanununa atıf yapıyorsa o maddeyi başka bir kanuna (ör. 4857) bağlama, emin değilsen madde numarası vermeden
anlat ("işçinin ahlak ve iyi niyet kurallarına aykırı davranışı nedeniyle haklı fesih" gibi); ilk cümleyi YALNIZ kaynaklarda açıkça yazan en temel kuralla kur, kaynakta
tam yazmayan bir ayrıntıyı (başlangıç tarihi, oran, süre gibi) ilk cümleye koyma, onu kaynağın desteklediği sonraki cümlelere bırak; sonraki paragraflar koşulları, istisnaları, süreleri ve yargı uygulamasını açsın.
Bir karardan söz ederken mahkemeyi, daireyi, yılı ve karar içeriğini YALNIZ o kaynağın künyesinde (reference) ve metninde yazdığı
kadarıyla söyle; künyede olmayan daire, yıl ya da sonuç ekleme. Kararı anlatan cümleye o kararın cümle numarasını ekle.
Bir kararı sırf bulunduğu için anlatma: sorulan hukuki meseleye gerçekten dayanak olmalı. Fesih bildiriminin eksikliği
sorulmuşken yalnız ödeme süresini inceleyen kararı bu eksikliğin emsali diye sunma. Bir kararın sorulan meseleyi ele
almadığını kendin de söylüyorsan, o kararı cevabı doldurmak için ekleme; kullanıcı özellikle karar karşılaştırması istemişse ayrımı anlat.
Bir ihtarın belirli fesih/tahliye yoluna yeterli olmamasıyla her amaç bakımından geçersiz olması aynı sonuç değildir;
kaynağın desteklediği sonuç ve kapsamla sınırlı anlat, genel bir geçersizlik sonucu ekleme.
Kullanıcıya "siz" diye hitap et. Kullanıcının verdiği sayıyı kanundaki dilime dikkatle yerleştir: "3 yıldır çalışıyorum" diyen
kişi "üç yıldan fazla" dilimine girmez, "bir buçuk yıldan üç yıla kadar" dilimine girer; emin değilsen iki dilimi birlikte söyle. Dilimi cümlede kaynaktaki sözlerle ADLANDIR ("bir buçuk yıldan üç yıla kadar çalışmış işçi için altı hafta; siz 3 yıldır çalıştığınız
için bu dilimdesiniz"); yalnızca "üç yıldır çalıştığınız için altı hafta" yazma. Yükte user_number_warnings varsa onlara aynen uy. Bir hakkın ya da tazminatın adını (kıdem tazminatı, ihbar
tazminatı, nafaka türleri, zamanaşımı, faiz gibi) yalnız o adı ya da kanunun kendi karşılığını açıkça yazan kaynak cümlesine bağlayarak
kullan; kaynağın başka bir şeyden söz eden cümlesinden "bu durumda şu hakkınız da etkilenmez" gibi çıkarım yazma. Kaynaklarda olmayan hiçbir bilgi, sayı, süre, oran, tarih ya da madde numarası yazma; kaynaklar
bir konuyu karşılamıyorsa o konuyu hiç yazma. Bilgiyi uydurma ya da ezberinden tamamlama.
Biçim: paragraflar BOŞ SATIRLA ayrılır; her cümle KENDİ SATIRINDA olsun ve sonuna " @@ " ile onu destekleyen kaynak cümlelerinin
numaraları eklensin: kaynak.cümle biçiminde, boşlukla ayrılmış (örnek: "... ödemek zorundadır. @@ 1.3 2.1"). Numaralar sources
içindeki source ve evidence_units.unit değerleridir; cümleyi gerçekten destekleyen TAM cümleleri seç, gerekli koşul ya da istisna
başka bir cümledeyse onu da yaz. Başlık, madde işareti, köşeli parantez, bağlantı kullanma.
Bir istisna cümlesi önceki cümledeki süreye veya koşula gönderme yapıyorsa ve açıklamana o süreyi yazıyorsan, hem süreyi
belirten önceki kaynak birimini hem istisna birimini göster. Aynı kaynağın başka bir cümlesindeki sayıyı tek başına istisna
biriminin kanıtıymış gibi kullanma. Kaynağın şartını, başvuru aşamasını ve sürenin başlangıç olayını cümlede koru.
Süre veya başvuru yolu anlatırken yalnız rakamı söyleme: kimin, hangi iddia veya koşulla, hangi olaydan itibaren,
hangi makama ve hangi sürede başvuracağını kaynağın desteklediği ölçüde birlikte açıkla. Bir istisna biriminde sayı
yazmıyorsa önceki birimin sayısını istisnaya tekrar eklemek yerine istisnayı kaynaktaki kapsamıyla anlatabilirsin.
parts varsa soru bu parçalardan oluşur: her parçayı (sırayla) ayrı paragrafta cevapla ve o parçayı önce kendi sources listesindeki
kaynaklarla anlat; bir parçanın kaynakları o parçayı karşılamıyorsa o parça için hiçbir şey yazma (kod bunu kullanıcıya ayrıca söyler)."""

PLAN_INSTRUCTION = """Türk hukuku araştırma planlayıcısısın. Verilen kullanıcı sorusunu, cevaplanması gereken AYRI hukuki parçalara böl
(tek konuysa tek parça; en çok 4). Her parça için Türk mevzuatında ve Yargıtay/Danıştay kararlarında arama yapmaya uygun 1-2 kısa
arama ifadesi yaz; ilgili kanunun adını biliyorsan ifadeye ekle (ör. "Türk Medeni Kanunu mal rejiminin tasfiyesi zamanaşımı").
Gündelik anlatımı hukuki arama terimlerine çevir; yalnız kullanıcı cümlesini tekrar etme.
Süre/zamanaşımı/dava açma süresi soran parçada arama ifadelerinden biri YALNIZ konu kavramı ve "zamanaşımı" sözcüğünden oluşsun
(ör. "katılma alacağı zamanaşımı"); uzun cümle kurma, çünkü uzun ifade hiç sonuç getirmez. Her parça için gerekirse en çok iki
kanun/madde arama ipucunu references içinde belirt: law_no ve article_no yalnız bildiğin numaralardır. Emin değilsen boş bırak.
Bu numaralar HUKUKİ KANIT DEĞİLDİR, cevaba aktarılmaz; yalnız korpusta doğrulanmış gerçek metni aramak içindir. Parçalar yalnız birbirinden BAĞIMSIZ konular için olsun (ör. nafaka / velayet / mal paylaşımı süresi, ya da kıdem tazminatı /
ihbar tazminatı); aynı konunun alt başlıklarını ya da aynı kuralın farklı yönlerini AYRI parça yapma, çünkü çakışan parçalar
aynı bilgiyi tekrar anlatır. Parçaları şu sırayla ver: kullanıcının ASIL sorusunun doğrudan cevabı (ör. "ikisini birlikte alabilir miyim") ilk parça olsun,
ayrıntı parçaları ondan sonra gelsin. Birden çok
usul yolu/şart soruluyorsa ayrı parçalara böl; bir yolun kaynağını diğer yolun kanıtı yerine kullanma.
Parça sorusu kullanıcının sorduğunu kısaca tekrar etsin; cevap, sayı, süre ya da hukuki sonuç YAZMA. Soru hukukla hiç ilgili
değilse (yemek tarifi, hava durumu, sohbet gibi) parts boş olsun ve "legal": false yaz; hukuki bir yönü olabilecek her soruda
(ör. "TÜFE nedir", "komşum ağacımı kesti") "legal": true. Yalnız JSON, TEK SATIRDA, girinti ve satır sonu olmadan (çıktı uzunluğu süreyi belirler):
{"legal":true,"parts":[{"question":"...","queries":["...","..."],"references":[{"law_no":"...","article_no":"..."}]}]}"""

# Önceki cümleye gönderme yapan ya da onu sürdüren başlangıçlar: önündeki cümle çıkarılmışsa bu cümle tek başına yanıltıcıdır
# ("Ancak, kesilen zamanaşımından sonra on yıl olduğu görüşü benimsenmemiştir" asıl kural olmadan cevabın tek cümlesi kalmıştı).
LEAD_INSTRUCTION = """Aşağıda kullanıcının sorusu ve KAYNAKLARLA DOĞRULANMIŞ cümleler (verified_sentences) var. Yalnız bu cümlelerde yazan
bilgiyle, sorunun doğrudan cevabını TEK cümlede yaz: soru evet/hayır türündeyse "evet, şu koşullarla ..." ya da "hayır, ..." diye
başla; süre, şart ya da tutar soruluyorsa onu söyle. Doğrulanmış cümlelerde olmayan hiçbir bilgi, sayı, süre ya da madde numarası
ekleme; koşulları ve istisnaları koru. "siz" diye hitap et. Cümlenin sonuna " @@ " ve dayandığın cümlelerin id numaralarını
(boşlukla ayrılmış) ekle, örnek: "... açabilirsiniz. @@ 3 5". Yalnız bu tek satırı yaz; başka hiçbir metin ekleme. Cümlede "doğrulanmış cümle" ya da "kaynak" gibi iç işleyişi anan sözcük kullanma;
doğrulanmış cümleler soruyu doğrudan cevaplamıyorsa yalnız YOK yaz."""

_LEAD = re.compile(r"^\s*(?P<text>.+?)\s*@@\s*(?P<ids>(?:\d+[\s,]*)+)\s*$")
_DANGLING = re.compile(
    r"^(?:Bu|Bunun|Bunlar|Bunların|Bunu|Buna|Bunda|Söz konusu|Anılan|Aynı|O|Şu|Ancak|Ayrıca|Bunun yanında|Bunların yanında|"
    r"Öte yandan|Dolayısıyla|Buna göre|Buna karşılık|Bununla birlikte|Ne var ki|Fakat|Ama|Yine|Ek olarak|Ayrıca da|"
    # An enumeration step whose first step was removed ("İkinci şart ise ..." with no first condition shown, 2026-10-30).
    r"(?:İkinci|Üçüncü|Dördüncü) (?:şart|koşul|olarak)|İkincisi|Üçüncüsü|Dördüncüsü|Son olarak|Diğer (?:bir )?(?:şart|koşul))\b",
    re.I)
# "@@ 1.3 2.1" ya da aralık "@@ 4.1-4.4": kaynak.cümle numaraları. Model sık sık BİR SATIRA BİRDEN ÇOK cümle yazıp her birinin sonuna
# ayrı numara koyuyor ("... @@ 1.1 Bu süre ... @@ 1.3"); satır numara bloklarından bölünür (ölçüldü: 2026-10-25).
_REFS = re.compile(r"@@\s*((?:\d+\.\d+(?:\s*-\s*\d+\.\d+)?)(?:[\s,]+\d+\.\d+(?:\s*-\s*\d+\.\d+)?)*)")

# A malformed reference ("@@ 2.3.c 2.4") leaves ".c 2.4" in front of the next sentence (seen in a live answer, 2026-10-25).
_LEADING_JUNK = re.compile(r"^(?:[.,;:]\s*)?(?:[a-zçğıöşü]\s+)?(?:\d+\.\d+[\s,]*)+(?=[^\d\s])")


def _evidence(block: str) -> list[dict]:
    units: list[dict] = []
    for first, last in re.findall(r"(\d+\.\d+)(?:\s*-\s*(\d+\.\d+))?", block):
        source, unit = (int(x) for x in first.split("."))
        end_source, end_unit = (int(x) for x in last.split(".")) if last else (source, unit)
        if end_source == source and unit <= end_unit <= unit + 6:
            units.extend({"source": source, "unit": number} for number in range(unit, end_unit + 1))
    return units[:12]


def _parse(raw: str) -> list[list[tuple[str, list[dict]]]]:
    """Satır biçimi: "cümle @@ 1.3 2.1" (bir satırda birden çok cümle olabilir). Paragraflar boş satırla ayrılır. Numarasız ya da
    geçersiz cümle atılır; hiç cümle kalmazsa ValueError."""
    if not isinstance(raw, str):
        raise ValueError("Unexpected draft")
    paragraphs: list[list[tuple[str, list[dict]]]] = []
    for block in re.split(r"\n\s*\n", raw.replace("\r\n", "\n").strip()):
        sentences: list[tuple[str, list[dict]]] = []
        # The model often puts "@@ 1.1 2.4" on the line BELOW its sentence (measured 2026-10-25: the kıdem+ihbar answer was
        # thrown away 3 times in a row as "no sentences"), so a paragraph is read as one text, not line by line.
        joined = " ".join(re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", line).strip() for line in block.split("\n"))
        pieces = _REFS.split(joined)
        # split() with one group: [text, refs, text, refs, ..., trailing text]; trailing text has no numbers and is dropped
        for text, refs in zip(pieces[0::2], pieces[1::2]):
            text = _LEADING_JUNK.sub("", text.strip())
            if (not text or re.search(r"[\[\]<>{}@]", text) or synthesis._FOREIGN_SCRIPT.search(text)
                    or re.search(r"https?://|www\.", text, re.I) or synthesis._INJECTION.search(text)):
                continue
            evidence = _evidence(refs)
            if evidence:
                # A writer can bind several sentences to one evidence block.
                # Judge them separately: one unsafe conclusion must not erase
                # an adjacent, independently supported explanation.
                sentences.extend((sentence, evidence) for sentence in synthesis._sentences(text)
                                 if len(sentence) >= 12)
        if sentences:
            paragraphs.append(sentences)
    if not paragraphs:
        raise ValueError("No evidence-linked sentences")
    return paragraphs


_FORMAT_REMINDER = ("Önceki cevabın biçimi geçersizdi. HER cümle ayrı satırda ve sonunda ' @@ ' ile kaynak cümle numaraları (örn. '@@ 1.2 2.1') "
                    "olmalı; numarasız cümle yazma, köşeli parantez ve madde işareti kullanma.")


def _reasons(verdict: str) -> dict[str, str]:
    """The checker's optional per-claim reasons, for diagnosis only (never shown to the user)."""
    try:
        claims = synthesis._json(verdict).get("claims", [])
    except (ValueError, TypeError, AttributeError, RecursionError):
        return {}
    return {str(c.get("id")): (str(c.get("why") or "")
                               + (" | kaynakta olmayan: " + "; ".join(map(str, c["added"])) if c.get("added") else ""))[:300]
            for c in claims if isinstance(c, dict) and (c.get("why") or c.get("added"))}


NOT_LEGAL: list[tuple[str, tuple[str, ...]]] = []  # the planner judged the question not legal at all


def simple_search_plan(question: str, history=()):
    """A single known legal topic needs no model to repeat it as a query."""
    from api.ai.search_plan import plan_search, research_queries, normalize
    from api.ai.relevance import question_intent, case_law_requested
    from api.ai.conversation_history import needs_standalone_rewrite
    q = normalize(question)
    # Missing punctuation must not turn several requested dimensions into a
    # supposedly simple topic. This only disables the shortcut; the planner
    # still determines the actual parts, without inventing legal answers.
    requests = re.findall(r'\b(?:hangi|nasıl|nasil|kaç|kac|nedir|nelerdir|neden|ne\s+zaman|ne\s+kadar)\b', q)
    if (len(q) > 180 or q.count('?') > 1 or re.search(r'[,;\n]|\b(?:ve|ayrıca|birlikte|karşılaştır)\b', q)
            or len(requests) > 1 or re.search(r'\?\s*\S', q)
            or case_law_requested(q) or re.search(r'\b(?:19|20)\d{2}\b', q)
            or (history and needs_standalone_rewrite(question))):
        return None
    if not plan_search(question).phrase and question_intent(question) is None:
        return None
    return [(question, research_queries(question))]


def plan_question(provider: AIProvider, question: str, history: Sequence[HistoryTurn] = ()) -> list[tuple[str, tuple[str, ...]]]:
    """The question's separate legal parts with search phrases for each (one short model call). The plan only steers the search;
    nothing of it is shown as an answer. Any failure means one part: the question itself. An empty list (`NOT_LEGAL`) means the
    planner found nothing legal in it (2026-10-25: "en iyi pizza tarifi" became "pizza tarifiyle ilgili hukuki bir sorun var mı"
    and was answered with copyright statutes)."""
    simple = simple_search_plan(question, history)
    if simple is not None:
        return simple
    fallback = [(question, (question,))]
    payload = {"question": question, "history_for_understanding_only": [t.question for t in history][-3:]}
    try:
        # The usual planning call takes 3-5 s but one in three took 23 s (measured 2026-10-31); a second identical request after
        # 8 s keeps the whole answer from waiting for the slow one.
        verdict = synthesis._json(_generate_hedged(provider, hedge_after=_HEDGE_PLAN_AFTER, system_instruction=PLAN_INSTRUCTION,
                                                   prompt=json.dumps(payload, ensure_ascii=False)))
        parts = verdict.get("parts")
    except (AIProviderError, ValueError, TypeError, AttributeError, RecursionError):
        return fallback
    if verdict.get("legal") is False and not parts:
        return NOT_LEGAL
    plan: list[tuple[str, tuple[str, ...]]] = []
    for part in parts if isinstance(parts, list) else []:
        if not isinstance(part, dict) or not isinstance(part.get("question"), str):
            continue
        text = " ".join(part["question"].split())[:200]
        raw_queries = part.get('queries')
        queries = tuple(" ".join(q.split())[:160] for q in (raw_queries if isinstance(raw_queries, list) else [])
                        if isinstance(q, str) and q.strip() and not synthesis._INJECTION.search(q))[:2]
        references = []
        raw_references = part.get('references')
        for reference in (raw_references if isinstance(raw_references, list) else [])[:2]:
            if not isinstance(reference, dict) or set(reference) != {'law_no', 'article_no'}:
                continue
            law, article = reference['law_no'], reference['article_no']
            if (isinstance(law, str) and re.fullmatch(r'[0-9]{1,5}', law)
                    and isinstance(article, str) and re.fullmatch(r'[0-9]{1,3}(?:/[A-Za-z])?', article)):
                references.append(f'{law} sayılı Kanun m. {article}')
        # Each authority query still passes the exact source-type/current/trust
        # lookup. A fabricated/missing reference produces no evidence or answer.
        queries = tuple(dict.fromkeys([*references, *queries]))
        if len(text) >= 5 and not synthesis._INJECTION.search(text):
            plan.append((text, queries or (text,)))
    return plan[:4] or fallback


_ASKS_PERIOD = re.compile(r"zamanaşımı|hak düşürücü|hangi süre|ne kadar süre|kaç (?:gün|ay|yıl|hafta)|(?:dava|başvuru|itiraz|temyiz|istinaf|şikayet|şikâyet)\w*\s+(?:açma\s+)?(?:süre|müddet)", re.IGNORECASE)
_PERIOD_STATED = re.compile(r"\d+(?:,\d+)?\s*(?:iş günü|gün|hafta|ay|yıl|saat)")


def _asks_period(text: str) -> bool:
    return bool(_ASKS_PERIOD.search(text))


def _states_period(text: str) -> bool:
    from api.ai.numeric_support import spell_numbers
    from api.ai.search_plan import normalize
    return bool(_PERIOD_STATED.search(spell_numbers(normalize(text))))


def _uncovered_note(missing: Sequence[str], question: str) -> str:
    """Names the parts we found no verified source for. A part's wording comes from the planner, so it is quoted only when it
    carries no number the user did not write (it must never smuggle in a period or amount)."""
    asked = set(re.findall(r"\d+", question))
    named = [text.rstrip(" ?.") for text in missing if set(re.findall(r"\d+", text)) <= asked and len(text) <= 160]
    if len(named) == len(missing):
        return ("Şu bölüm için bu araştırmada yeterli doğrulanmış dayanak elde edemedim: "
                + "; ".join(f"“{text}”" for text in named) + ".")
    return "Sorunuzun bir bölümü için bu araştırmada yeterli doğrulanmış dayanak elde edemedim. Bu, korpusta ilgili hüküm bulunmadığı anlamına gelmez."


def _repeat_of(text: str, shown: list[str]) -> int | None:
    """Only lossless lexical containment, never semantic word-set similarity.

    Short tokens carry numbers, negation and exceptions too. Dropping them or
    comparing sets could delete a new deadline, boundary or eligibility rule.
    Both sentences have already passed source checking; only a complete,
    ordered token sequence can reuse an earlier displayed sentence here.
    """
    text = re.sub(r"^Bu nedenle\s+", "", text, flags=re.I)
    token_pattern = r"\d+(?:[.,]\d+)*|\w+|[<>=+%/−-]"
    words = re.findall(token_pattern, text.casefold())
    if not words:
        return None
    for index, previous in enumerate(shown):
        other = re.findall(token_pattern, previous.casefold())
        if any(other[start:start + len(words)] == words for start in range(len(other) - len(words) + 1)):
            return index
    return None


_CROSS_PART_DUPLICATE_INSTRUCTION = """Aşağıdaki cümlelerin hepsi kaynaklarıyla ayrı ayrı doğrulanmış, bir cevabın farklı bölümlerinden gelen cümlelerdir.
Görevin yalnız tekrarları bulmak: sonraki bir cümlenin TÜM anlamı (her koşul, istisna, kişi, süre, tutar, karar ve sonuç dahil) daha önceki
bir cümlede zaten varsa onu tekrar say. Yeni koşul, istisna, sayı, süre, karar veya örnek içeren cümle tekrar değildir. Sözcük benzerliği
yeterli değildir; emin değilsen listeye alma. Yeni bilgi ekleme, cümleleri değerlendirme.
Yalnız JSON: {"duplicate_claims":[{"id":4,"duplicate_of":1}]} (duplicate_of, id'den küçük olmalı; tekrar yoksa boş liste)."""


def _cross_part_duplicates(provider, candidates, part_starts) -> list[dict]:
    """Repeats between different question parts, found by one independent call over the candidate sentences.

    It runs while the per-part checks run (measured 2026-10-31: 14.7 s when run after them). The verdict only counts for pairs
    that both end up approved (see the assembly), so a refused sentence can never be the reason another one is dropped.

    The per-part checkers run in parallel and each sees only its own part, so the same fact written under two or three parts
    ("hesaplama", "fark", "örnek") was never flagged (measured 2026-10-31: one paragraph shown three times). Any failure here only
    leaves the repeat in place; it can never remove or add a claim by itself.
    """
    from bisect import bisect_right
    ids = list(range(1, len(candidates) + 1))
    approved = set(ids)
    part_of = {i: bisect_right(list(part_starts), candidates[i - 1][0]) for i in ids}
    if len(set(part_of.values())) < 2 or len(ids) < 4:
        return []
    try:
        raw = provider.generate(system_instruction=_CROSS_PART_DUPLICATE_INSTRUCTION,
                                prompt=json.dumps({"claims": [{"id": i, "text": candidates[i - 1][1].text} for i in ids]},
                                                  ensure_ascii=False))
        entries = synthesis._json(raw).get("duplicate_claims", [])
        found = []
        for entry in entries:
            if (isinstance(entry, dict) and set(entry) == {"id", "duplicate_of"} and entry["id"] in approved
                    and entry["duplicate_of"] in approved and entry["duplicate_of"] < entry["id"]
                    and part_of[entry["id"]] != part_of[entry["duplicate_of"]]):
                found.append({"id": entry["id"], "duplicate_of": entry["duplicate_of"]})
        return found
    except Exception:  # noqa: BLE001 - a failed duplicate pass leaves the (proven) repeat in place
        logger.warning("Çapraz bölüm tekrar denetimi başarısız", exc_info=True)
        return []


def _repeats(text: str, shown: list[str]) -> bool:
    return _repeat_of(text, shown) is not None


LEAD_CHECK_INSTRUCTION = synthesis.CHECK_INSTRUCTION + """
Yükte user_number_warnings varsa onlar kullanıcının sayısını hangi dilime koyman gerektiğini söyler (kaynak değildir): o dilime
uygulanan cümleyi, kaynak birimde o dilim bulunuyorsa doğru say; üst dilimin değerini kullanıcıya uygulayan cümleyi reddet.
KAYNAKTA OLMAYAN EKLEME KONTROLÜ: Her iddia için önce, iddiada olup alıntılanan kaynak birimlerinde AÇIKÇA bulunmayan YENİ
HUKUKİ BİLGİYİ ara: bir hak ya da tazminat türü, hukuki sonuç, süre, kişi, kurum, koşul. Varsa o iddiaya "added":["..."] alanı
ekle, her birini kısaca yaz ve supported=true verme. Sözcük farkı, eşanlamlı, sadeleştirme ya da soruda geçen olgunun
kullanıcıya uygulanması ekleme sayılmaz. Soruda geçen bir hakkın (ör. kıdem tazminatı) adı kaynak birimde geçmiyorsa, kaynağın
başka bir şeyden söz eden cümlesinden o hakkın etkilenmediği sonucunu çıkarmak EKLEMEDİR; kaynak o hakkı söylemelidir.
Ekleme yoksa "added" alanını hiç yazma. Kullanıcının sayısını yalnız ilgili dilime ("üç yıla kadar" dilimine) uygulayan ve
"üç yıldan fazla" demeyen iddiayı, bu dilimi kaynak birimde bulunuyorsa reddetme.
GEREKLİ KOŞULDAN SINIRLI ÇIKARIM: Kaynak belirli bir yol için bir koşulun zorunlu olduğunu açıkça söylüyorsa,
"bu koşul yoksa bu belirli yola dayanamazsınız" açıklamasını sırf kaynak aynı olumsuz cümleyi yazmıyor diye reddetme.
Örneğin yalnız belirli belgeyle kullanılabilen bir yol anlatılıyorsa o belge olmadan O YOLUN kullanılamayacağı açıklanabilir.
Bu, başka hiçbir yola başvurulamayacağı anlamına gelmez. Gerekli koşulu yeterli koşul sayma: koşulun varlığından otomatik
hak/sonuç çıkarma. Kaynakta gereklilik açık değilse, alternatif veya istisna varsa bunları yok sayan mutlak çıkarımı reddet.
KAYNAKLI DOĞAL AÇIKLAMA (bütün iddialar için): evidence'taki doğrulanmış kurallardan zorunlu olarak çıkan açıklama,
yalnız kaynak cümlelerini başka sözcüklerle birleştirdiği veya kullanıcının açıkça verdiği olaya bağladığı için reddedilmez.
Bu izin cümle numarasına bağlı değildir; ilk cümlede kabul edilen aynı kaynaklı çıkarım sonraki cümlede de aynı denetimle
değerlendirilir. Kaynaktaki genel kuralın kullanıcı sorusundaki açık olayla eşleştirilmesi yeni bir hukuk kuralı eklemek değildir.
Ancak uygulanabilirlik için gereken ve soruda verilmeyen bir şartın sağlandığını varsaymak, olay benzerliğini kanıt yerine
koymak veya kaynakta olmayan yeni bir hukuki sonuç üretmek yasaktır. Bütün öncüller evidence veya user_question içinde
açıkça bulunmalı; kuralın koşulları, istisnaları, öznesi ve süre başlangıcı değişmemelidir.
Evidence'ta bulunmayan yeni olgu, sayı, süre, şart, istisna ekliyorsa; evidence'taki şart ya da istisnayı düşürüp koşulsuz ve
mutlak bir sonuç söylüyorsa; evidence'ın söylediğinin tersini çıkarıyorsa supported=false ve scope_preserved=false ver.
KULLANICININ KENDİ OLGULARI (bütün iddialar için): user_question'da kullanıcının KENDİSİNİN verdiği olgulara ("3 yıldır
çalışıyorum", "işveren beni çıkardı") evidence'taki kuralı, kuralın şart ve istisnalarını koruyarak uygulayan cümle "kişisel
sonuca atlama" sayılmaz; kural evidence'ta, olgu soruda olduğu sürece supported=true verilebilir. Kullanıcının VERMEDİĞİ bir
olguyu varsayan ya da kuralın bir şartını kullanıcı lehine sağlanmış sayan cümle supported=false kalır. Sınırlara dikkat:
kullanıcı "3 yıldır" dediyse bu "üç yıldan fazla / üç yılı aşan" şartını KARŞILAMAZ (üç yıla kadar olan dilime girer); kullanıcının
sayısını kanundaki sınırın öbür yanına koyan cümle supported=false.
Bir iddiada herhangi bir alan false ise o iddiaya bir "why" alanı ekle: yalnız eksik ya da yanlış olanı söyle (hangi bilgi kaynakta yok ya da
neyi değiştiriyor). İddiayı ve kaynağı yeniden anlatma, "İddia ... diyor" diye başlama. Onaylanan iddiaya "why" ekleme. JSON'u TEK SATIRDA, girinti ve satır sonu olmadan yaz (çıktı uzunluğu süreyi belirler).
İLGİ: question_parts olsun veya olmasın, karar anlatımı sorulan hukuki meseleye katkı vermelidir; yalnız aynı kanun/maddeyi
anması yeterli değildir. Fesih uyarısının eksikliği sorusunda yalnız otuz günlük sürenin dolmasını inceleyen bir kararı,
fesih uyarısına emsal gibi anlatan cümle relevant=false/scope_preserved=false olur. Kullanıcı özellikle kararları karşılaştırmak
veya belirli bir kararın neden uygulanmayacağını öğrenmek istiyorsa bu ayrımı açıklamak ilgilidir.
Belirli fesih/tahliye yolunun koşulunu karşılamamayı, bütün amaçlar için genel geçersizlik diye genişletme; böyle bir
genişletmede scope_preserved=false ver. question_parts verildiyse bir iddia ancak bu parçalardan birini doğrudan cevaplıyorsa relevant=true olur. Kaynakta yazsa da
sorulan parçaya cevap olmayan arka plan bilgisi (ör. mal paylaşımı süresi sorulmuşken kanunun yürürlük geçiş hükümleri, başka bir
davanın süresi) relevant=false.
coverage_preserved değerlendirmesini taslağın tamamına değil, yalnız supported=true, relevant=true ve scope_preserved=true
verdiğin cümlelerin BİRLİKTE oluşturduğu nihai cevaba göre yap. Reddettiğin bir cümledeki başvuru aşaması, süre, şart veya
istisna onaylanan cümlelerde yoksa sorunun o bölümünü cevaplanmış sayma ve coverage_preserved=false ver.
discarded_before_review içindeki metinler kod denetiminde elenmiştir; yayımlanmaz ve cevap kapsamına sayılamaz.
Bir cümlede "aynı süre", "bu süre" deniyorsa yalnız o cümlenin ilk bölümündeki açık süreye gönderme yapması, sayının ikinci
kez yazılmaması nedeniyle ret sebebi değildir; anlamı, başlangıç olayı ve kapsamı gerçekten aynı olmalıdır.
claims içindeki paragraph alanı yalnız sunum bağlamıdır, hukuki kanıt değildir. Aynı paragraftaki onaylanmış cümlelerde
açıkça kurulmuş şartı veya istisnayı her cümlede kelimesi kelimesine tekrarlamak zorunlu değildir; doğal açıklamayı
birlikte oku. Örneğin kuralı ihtiyatla özetleyen bir cümleyi, aynı paragrafta doğru anlatılan istisnayı o cümlede de
tekrarlamadığı için reddetme. Ancak başka cümle kaynak yerine geçmez, elenen cümleler bu bağlamı tamamlayamaz;
kesin/genel bir hükmün tersini söyleyen cümleyi, yanlış sayıyı veya farklı kapsamı bu yolla onaylama.
Ret gerekçesi (why) yazdığında başına şu tanı etiketlerinden uygun olanı koy: kaynakta gerekli kural/olgu gerçekten yoksa
"kaynak_eksik:", kaynakta kural var ama cümle koşulu/istisnayı/süre başlangıcını yanlış veya eksik aktarıyorsa
"ifade_duzelt:", iddia soruyla ilgisizse "ilgisiz:". Etiketler yalnız yeniden aramayı yönlendirir; onay değildir.
Mevcut kaynakta bulunan bir koşulu yazarın atlaması kaynak eksikliği DEĞİLDİR."""

# Denetçi cevabı: gerekçe metni olmadan (reddedilenlerin gerekçeleri `_explain_rejections` ile arka planda istenir)
LEAD_CHECK_INSTRUCTION_DEFERRED = LEAD_CHECK_INSTRUCTION.replace(
    'Bir iddiada herhangi bir alan false ise o iddiaya bir "why" alanı ekle: yalnız eksik ya da yanlış olanı söyle (hangi bilgi kaynakta yok ya da\nneyi değiştiriyor). İddiayı ve kaynağı yeniden anlatma, "İddia ... diyor" diye başlama. Onaylanan iddiaya "why" ekleme. JSON\'u TEK SATIRDA, girinti ve satır sonu olmadan yaz (çıktı uzunluğu süreyi belirler).',
    'Bu çağrıda "why" alanı YAZMA: iddia başına yalnız id ve üç boolean alanı ver; reddedilen iddiaların gerekçeleri ayrıca istenir\n(gerekçe metni cevabı geciktiriyordu). part_coverage kayıtlarındaki kısa why alanı bundan etkilenmez. JSON\'u TEK SATIRDA, girinti ve\nsatır sonu olmadan yaz (çıktı uzunluğu süreyi belirler).')
assert LEAD_CHECK_INSTRUCTION_DEFERRED != LEAD_CHECK_INSTRUCTION


_ABOUT_SOURCES = re.compile(r"\b(?:sağlanan|paylaşılan|verilen|sunulan|mevcut|diğer)\s+kaynak\w*"
                            r"|\b(?:paylaşılan |verilen |sunulan |mevcut )?kaynak(?:lar)?(?:ınız|ımız)?(?:da|ta)\b"
                            # The assistant speaking about itself: what it holds, reaches or can answer. No legal source proves such a
                            # sentence, and it contradicted the answer: "the two Yargıtay decisions are not in my hands" stood under
                            # a paragraph citing both (measured 2026-10-30). What could not be found is said by the code.
                            r"|\belimde(?:ki)?\b|\b(?:ulaş|eriş)(?:abil)?diğim|\berişim(?:im|imiz)\b"
                            r"|\b(?:cevapla|yanıtla|ver|sun|oluştur|çıkar|bul)(?:abil|ama|eme)?(?:iyorum|irim|m|yız|yiz|dım|dim)\b"
                            r"|\buydur(?:madan|mayacağım|mam)\b", re.IGNORECASE)
_INTERNAL_WORDS = re.compile(r"doğrulanmış|doğrulanmam|cümle|kaynaklarda yer|verified", re.IGNORECASE)


def _repair_lead(provider: AIProvider, checker: AIProvider, question: str, proven: dict, pool: list[RAGContext],
                 views: list[dict], info: dict | None = None) -> "synthesis._Claim | None":
    """Cevabın ilk cümlesi (soruya doğrudan cevap) kanıtlanamadıysa, KANITLANMIŞ cümlelerden çıkan tek cümlelik doğrudan cevap
    yazdırılır. Kanıtı, dayandığı kanıtlı cümlelerin kaynak cümleleridir; aynı kod kapılarından ve bağımsız denetçiden geçmezse
    kullanılmaz (ölçüldü: 2026-10-25, ilk cümle ~%40 kaybolup cevap "Kıdem hesabında..." gibi yan bilgiyle başlıyordu)."""
    payload = {"question": question, "verified_sentences": [{"id": n, "text": proven[n].text} for n in sorted(proven)]}
    try:
        raw = provider.generate(system_instruction=LEAD_INSTRUCTION, prompt=json.dumps(payload, ensure_ascii=False))
    except AIProviderError:
        return None
    # "@@ 3 5" may come on the line below the sentence (same habit as in the draft): read the reply as one line.
    match = _LEAD.match(" ".join(raw.split())) if isinstance(raw, str) and raw.strip() else None
    if not match:
        return None
    text = match["text"].strip()
    note = info.__setitem__ if info is not None else (lambda *_: None)
    note("debug_lead", text)
    chosen = [n for n in dict.fromkeys(int(x) for x in re.findall(r"\d+", match["ids"])) if n in proven][:6]
    if (not chosen or not 12 <= len(text) <= 500 or _INTERNAL_WORDS.search(text) or re.search(r"[\[\]<>{}@]", text) or synthesis._FOREIGN_SCRIPT.search(text)
            or synthesis._INJECTION.search(text)):
        return None
    evidence, seen = [], set()
    for n in chosen:
        for source, span in proven[n].evidence:
            if (source, span) not in seen:
                seen.add((source, span))
                evidence.append({"source": source, "quote": span})
    try:
        claim = synthesis._checked_claim(0, text, evidence[:12], pool, views, lenient=True, conclusion=True, known=question)
    except (synthesis._Rejected, ValueError, TypeError, KeyError) as error:
        note("debug_lead_why", f"kod: {error}")
        return None
    check = {"question": question, "user_question": question,
             "sources": [{k: v for k, v in view.items() if k != "units"} for view in views],
             "claims": [{"id": 1, "text": claim.text, "evidence": [{"source": s, "quote": q} for s, q in claim.evidence],
                         **({"mechanical_notes": list(claim.notes)} if claim.notes else {})}],
             "question_to_user": None, "source_gap": False}
    try:
        verdict = checker.generate(system_instruction=LEAD_CHECK_INSTRUCTION, prompt=json.dumps(check, ensure_ascii=False))
    except AIProviderError:
        return None
    approved = synthesis._fully_approved_ids(verdict, 1)
    note("debug_lead_why", "onaylandı" if approved else "denetçi reddetti: " + str(verdict)[:300])
    return claim if approved else None


_HEDGE_WRITE_AFTER = 20.0  # seconds; the usual part write takes 8-18 s
_HEDGE_CHECK_AFTER = 15.0  # seconds; the usual part check takes 4-12 s
_HEDGE_PLAN_AFTER = 8.0  # seconds; the usual planning call takes 3-5 s


def _generate_hedged(provider: AIProvider, *, hedge_after: float, **kwargs) -> str:
    """One call; if it is still running after `hedge_after` seconds the same request is sent a second time and whichever comes
    back first is used (measured 2026-10-30: one of four parallel calls took 45 s for 600 tokens, and the answer waits for the
    slowest). The late duplicate is left to finish on its own. The request is identical, so nothing about the result's checking
    changes; an error of one copy is only an error when the other fails as well."""
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

    executor = ThreadPoolExecutor(max_workers=2)
    try:
        first = executor.submit(provider.generate, **kwargs)
        done, _ = wait([first], timeout=hedge_after)
        if done:
            return first.result()
        second = executor.submit(provider.generate, **kwargs)
        pending = {first, second}
        error = None
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                try:
                    return future.result()
                except AIProviderError as exc:
                    error = exc
        raise error
    finally:
        executor.shutdown(wait=False)


class _HedgedProvider:
    """The same provider whose `generate` is hedged (see `_generate_hedged`); everything else is passed through."""

    def __init__(self, inner: AIProvider, hedge_after: float):
        self._inner, self._hedge_after = inner, hedge_after

    def generate(self, **kwargs) -> str:
        return _generate_hedged(self._inner, hedge_after=self._hedge_after, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


TRIAGE_INSTRUCTION = """Hukuki kaynak ayıklayıcısısın. Kullanıcı sorusu (ve varsa alt soruları) ile numaralı kaynakların künyesi ve ilk satırları
verilir. YALNIZ konusu soruyla AÇIKÇA ilgisiz olan kaynakların numaralarını ver (ör. soru komşu ağacı iken kaynak terör zararları
tazminatı, ceza infaz kurumları ya da tapu iptali davası). Aynı konuya bir yandan değen, tamamlayıcı ya da genel kuralı koyan
kaynakları LİSTELEME. Emin değilsen kaynağı listeleme. Hukuki cevap yazma. Yalnız JSON: {"unrelated":[3,7]}"""


def _drop_unrelated_sources(provider: AIProvider, question: str, contexts: Sequence[RAGContext],
                            parts: Sequence[tuple[str, frozenset]]) -> list[int]:
    """Numbers (1-based) of the sources the model finds clearly off-topic. Word search brings in decisions that only share a
    word with the question (measured 2026-10-30: a neighbour's tree question got a terror-damages case and a title-deed case;
    the writer used them, the checker rightly refused them, and the retry chain cost 150 s). Conservative on purpose: any
    failure, an empty answer or an answer that would leave a part without a source drops nothing."""
    if len(contexts) < 3:
        return []
    payload = {"question": question, "alt_sorular": [text for text, _ in parts] if len(parts) > 1 else [],
               "sources": [{"id": i, "kunye": c.reference_line[:110], "baslangic": " ".join(c.content.split())[:240]}
                           for i, c in enumerate(contexts, 1)]}
    try:
        data = synthesis._json(provider.generate(system_instruction=TRIAGE_INSTRUCTION,
                                                 prompt=json.dumps(payload, ensure_ascii=False)))
        dropped = {n for n in data["unrelated"] if type(n) is int and 1 <= n <= len(contexts)}
    except (AIProviderError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return []
    kept = [c for n, c in enumerate(contexts, 1) if n not in dropped]
    if not kept:
        return []
    for _text, chunk_ids in parts:  # every part keeps its sources when all of them were marked
        if chunk_ids and not any(c.chunk_id in chunk_ids for c in kept):
            dropped -= {n for n, c in enumerate(contexts, 1) if c.chunk_id in chunk_ids}
    return sorted(dropped)


EXPLAIN_INSTRUCTION = """Bağımsız kaynak-destek denetçisisin. Aşağıdaki iddialar aynı denetçi tarafından REDDEDİLDİ. Her biri için, yazarın
cümleyi düzeltebilmesi için gerekçeyi yaz: hangi bilgi kaynak birimlerinde yok ya da cümle kaynağın söylediğini nasıl değiştiriyor.
Gerekçenin başına nedenini ayır: kaynak havuzunda gereken dayanak yoksa "kaynak_eksik:", dayanak var ama cümle koşulu, sınırı ya da
kapsamı bozmuşsa "ifade_duzelt:", cümle soruyla ilgisizse "ilgisiz:" yaz. İddiayı ve kaynağı yeniden anlatma. Yalnız JSON, tek satırda:
{"reasons":[{"id":1,"why":"ifade_duzelt: ..."}]}"""

_EXPLAIN_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ret-gerekcesi")


def _explain_rejections(checker: AIProvider, question: str, rejected: list[tuple[int, "synthesis._Claim"]],
                        views: list[dict]) -> dict[str, str]:
    """Reasons for the rejected sentences, as {draft sentence number: reason}. Started in the background right after the verdict:
    the first check no longer writes prose reasons (they were two thirds of its output and sat on the critical path), and only a
    retry needs them. Any failure only means no reasons."""
    if not rejected:
        return {}
    cited = {source for _, claim in rejected for source, _ in claim.evidence}
    payload = {"question": question,
               "sources": [{k: v for k, v in view.items() if k != "units"} for view in views if view["source"] in cited],
               "rejected_claims": [{"id": number, "text": claim.text,
                                    "evidence": [{"source": source, "quote": span} for source, span in claim.evidence]}
                                   for number, claim in rejected]}
    try:
        data = synthesis._json(_HedgedProvider(checker, _HEDGE_CHECK_AFTER).generate(
            system_instruction=EXPLAIN_INSTRUCTION, prompt=json.dumps(payload, ensure_ascii=False)))
        return {str(item["id"]): str(item["why"]) for item in data["reasons"]
                if isinstance(item, dict) and type(item.get("id")) is int and isinstance(item.get("why"), str)}
    except (AIProviderError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return {}


def _write_parts_in_parallel(provider: AIProvider, payload: dict, part_sources: Sequence[tuple[str, set]]):
    """One writer call per part of the question, all at once: the answer takes as long as its longest part, not the sum.

    Every call gets ALL sources (input size hardly changes the time; output length does) and is told which single part to
    write. The parts' drafts are joined in order and then go through exactly the same code gates and the independent
    checker as a single draft. Returns (raw text, flat numbers of each part's first sentence), or None when any part fails
    to come back in the expected shape: the caller then writes the whole answer in one call, so nothing is ever left out."""
    from concurrent.futures import ThreadPoolExecutor

    def write(item) -> str:
        number, (text, _found) = item
        part_payload = {**payload, "write_only_part": {
            "part": number, "question": text,
            "other_parts_written_separately": [other for index, (other, _) in enumerate(part_sources, 1) if index != number]}}
        return _generate_hedged(provider, hedge_after=_HEDGE_WRITE_AFTER, system_instruction=WRITE_INSTRUCTION,
                                prompt=json.dumps(part_payload, ensure_ascii=False))

    try:
        with ThreadPoolExecutor(max_workers=len(part_sources)) as pool_executor:
            raws = list(pool_executor.map(write, enumerate(part_sources, 1)))
        starts, total = [], 0
        for index, raw in enumerate(raws):
            paragraphs = _parse(raw)
            if len(paragraphs) > 1 and all(len(paragraph) == 1 for paragraph in paragraphs):
                # a writer that puts a blank line after every sentence: one part reads as one paragraph
                raws[index] = re.sub(r"\n[ \t]*\n+", "\n", raw.strip())
            starts.append(total + 1)
            total += sum(len(paragraph) for paragraph in paragraphs)
    except (AIProviderError, ValueError, TypeError, KeyError, RecursionError):
        return None
    return "\n\n".join(raws), starts


class _PartPreview:
    """Shows the VERIFIED sentences of the question's parts to the user as each part's own check comes back, in part order.

    Only sentences the independent checker approved are ever shown (never a draft), the sentence filters of the final assembly are
    applied in the same order, and the cumulative text is replaced by the final answer when it arrives. The first part is the
    question's main point, so the reader gets it as soon as it is proven instead of when the slowest part is done."""

    def __init__(self, emit: "Callable[[VerifiedAnswer], None]", candidates: list, paragraph_numbers: list[int],
                 pool: list[RAGContext], parts: int) -> None:
        self.emit, self.candidates, self.paragraph_numbers, self.pool = emit, candidates, paragraph_numbers, pool
        self.parts, self.ready, self.released = parts, {}, 0
        self.paragraphs: list[str] = []
        self.shown: list[str] = []
        self.shown_claims: list = []
        self.used: set[int] = set()

    def __call__(self, part: int, numbers: list[int], verdict: str | None, sub_info: dict) -> None:
        logger.info("Önizleme: bölüm %d denetimi döndü (%d cümle); sırada bekleyen bölüm %d", part + 1, len(numbers), self.released + 1)
        if numbers:
            approved = synthesis._fully_approved_ids(verdict, len(numbers)) if sub_info.get("checker_protocol_status") == "valid" else None
            if approved is None:
                self.ready[part] = (numbers, set())  # not shown, but later parts must not wait for it
            else:
                self.ready[part] = (numbers, {numbers[local - 1] for local in approved})
        else:
            self.ready[part] = ([], set())
        grew = False
        while self.released < self.parts and self.released in self.ready:
            grew = self._release(*self.ready.pop(self.released)) or grew
            self.released += 1
        if grew and self.paragraphs:
            self.emit(VerifiedAnswer(text="\n\n".join(self.paragraphs),
                                     contexts=tuple(self.pool[source - 1] for source in sorted(self.used)), unverified_markers=()))

    def _release(self, numbers: list[int], approved: set[int]) -> bool:
        from api.ai.decision_attribution import with_case_identity
        by_paragraph: dict[int, list[str]] = {}
        for index in sorted(numbers):
            if index not in approved:
                continue
            number, claim = self.candidates[index - 1]
            paragraph = self.paragraph_numbers[number - 1]
            if _ABOUT_SOURCES.search(claim.text) or (_DANGLING.match(claim.text) and paragraph not in by_paragraph):
                continue
            duplicate = _repeat_of(claim.text, self.shown)
            if duplicate is not None and self.shown_claims[duplicate].evidence == claim.evidence:
                continue
            by_paragraph.setdefault(paragraph, []).append(with_case_identity(claim.text, claim.evidence, self.pool))
            self.shown.append(claim.text)
            self.shown_claims.append(claim)
            self.used.update(source for source, _ in claim.evidence)
        self.paragraphs.extend(" ".join(sentences) for sentences in by_paragraph.values())
        return bool(by_paragraph)


def _check_parts_in_parallel(checker: AIProvider, *, payload: dict, candidates: list, part_sources: Sequence[tuple[str, set]],
                             part_starts: Sequence[int], allow_format_retry: bool,
                             on_part_done: "Callable | None" = None,
                             instruction: str = LEAD_CHECK_INSTRUCTION) -> "tuple[str, list, list] | None":
    """The independent check, one call per part of the question, all at once (the length of a verdict, mostly the reasons for
    rejected sentences, decides how long the check takes).

    Each call sees its part's sentences (numbered from 1 again), every source, and only that part as the question to cover.
    The verdicts are merged into ONE verdict of the usual shape, with the sentence numbers and the per-part coverage mapped back,
    so everything after it is unchanged. A part with no sentence left has no coverage. Any call that is not a clean, valid
    verdict makes the caller run the ordinary single check instead; nothing is ever approved on a partial or malformed result.
    `on_part_done(part, candidate_numbers, verdict, sub_info)` is called, in the calling thread, as each part's own check comes back
    (parts without a sentence are reported first with an empty list): the caller can show a verified part before the slowest
    part is done. A failing callback never touches the result.
    Returns (verdict JSON, per-part coverage rows, duplicate rows) or None."""
    from bisect import bisect_right
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from api.ai.checker_protocol import check_claims
    from api.ai.part_coverage import INSTRUCTION as COVERAGE_INSTRUCTION

    groups: list[list[int]] = [[] for _ in part_sources]
    for index, (number, _claim) in enumerate(candidates, 1):
        groups[max(0, bisect_right(list(part_starts), number) - 1)].append(index)
    active = [(part, ids) for part, ids in enumerate(groups) if ids]

    def check(item):
        part, ids = item
        local = {original: position for position, original in enumerate(ids, 1)}
        sub_payload = {**payload, "question_parts": [part_sources[part][0]],
                       "claims": [{**payload["claims"][original - 1], "id": local[original]} for original in ids]}
        sub_info: dict = {}
        verdict = check_claims(_HedgedProvider(checker, _HEDGE_CHECK_AFTER), instruction=instruction + COVERAGE_INSTRUCTION,
                               payload=sub_payload,
                               allow_format_retry=allow_format_retry, diagnostics=sub_info, part_count=1)
        return part, ids, verdict, sub_info

    def report(*arguments):
        if on_part_done is None:
            return
        try:
            on_part_done(*arguments)
        except Exception:  # noqa: BLE001 - a preview problem must never change or lose a checked answer
            logger.exception("Kısmi önizleme bildirimi başarısız")

    for part in range(len(part_sources)):
        if not groups[part]:
            report(part, [], None, {})
    try:
        with ThreadPoolExecutor(max_workers=len(active)) as pool_executor:
            futures = [pool_executor.submit(check, item) for item in active]
            results = []
            for future in as_completed(futures):
                finished = future.result()
                results.append(finished)
                report(*finished)
        results.sort(key=lambda row: row[0])
        claims, duplicates, coverage, by_part = [], [], True, {}
        for part, ids, verdict, sub_info in results:
            if sub_info.get("checker_protocol_status") != "valid":
                return None
            value = synthesis._json(verdict)
            coverage = coverage and value["coverage_preserved"] is True
            claims.extend({**claim, "id": ids[claim["id"] - 1]} for claim in value["claims"])
            row = sub_info["checker_part_coverage"][0]
            by_part[part] = {"part_id": part + 1, "claim_ids": [ids[i - 1] for i in row["claim_ids"]],
                             "complete": row["complete"], "why": row["why"]}
            duplicates.extend({"id": ids[d["id"] - 1], "duplicate_of": ids[d["duplicate_of"] - 1]}
                              for d in sub_info.get("checker_duplicates", ()))
        rows = [by_part.get(part) or {"part_id": part + 1, "claim_ids": [], "complete": False,
                                      "why": "kaynak_eksik: bu bölüm için kanıtlanabilir cümle yazılamadı"}
                for part in range(len(part_sources))]
        merged = {"claims": sorted(claims, key=lambda claim: claim["id"]), "coverage_preserved": coverage,
                  "source_only": True, "clarification_safe": True}
    except (AIProviderError, ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError):
        return None
    return json.dumps(merged, ensure_ascii=False), rows, duplicates


def _usable(context: RAGContext, budget: int) -> RAGContext | None:
    """The context itself, or its text without a cut-off tail (same rule as `synthesize_answer`); None if unusable."""
    if context.source_type == "document":
        return None  # a user's own document never reaches this route (it stays on the local model)
    if synthesis._source_views([context], budget):
        return context
    trimmed = synthesis._without_cut_off_tail(context)
    if trimmed is not None and synthesis._source_views([trimmed], budget):
        return trimmed
    return None


def _binding_stamp(context):
    return [str(value) for value in (context.source_id, context.source_version, context.revision,
                                    context.version_date, context.effective_from, context.effective_to)]


def _binding_snapshot(flat, pool, views):
    """Request-local provenance; never a new evidence source or log payload."""
    result = {}
    for number, (_text, references) in enumerate(flat, 1):
        bindings = []
        for reference in references:
            source, unit = reference.get('source'), reference.get('unit')
            if type(source) is not int or not 1 <= source <= len(pool) or type(unit) is not int:
                continue
            units = views[source - 1]['units']
            if not 1 <= unit <= len(units):
                continue
            bindings.append({'chunk_id': str(pool[source - 1].chunk_id), 'unit': unit,
                'source_stamp': _binding_stamp(pool[source - 1]),
                'content_hash': sha256(pool[source - 1].content.encode()).hexdigest(),
                'unit_hash': sha256(units[unit - 1].encode()).hexdigest()})
        result[str(number)] = bindings
    return result


def _remap_preserved(saved, pool, views):
    """Checked sentences of the previous attempt, re-bound to the CURRENT source pool by chunk identity and unit digest.

    A revision adds sources and re-orders the pool, so the old (source, unit) numbers point elsewhere; the whole answer used to be
    rewritten (measured 2026-10-30: 55 s for the second attempt). A sentence is kept only when each source it rests on is still in
    the pool and the cited unit is byte-identical; the merged draft is then checked again in full, nothing is trusted unchecked."""
    index = {str(c.chunk_id): i for i, c in enumerate(pool, 1)}
    result = []
    for item in saved:
        text, references = item[0], item[1]
        group = item[2] if len(item) > 2 else None
        evidence = []
        for reference in references:
            position = index.get(reference["chunk_id"])
            units = views[position - 1]["units"] if position else ()
            unit = reference["unit"]
            if not position or not 1 <= unit <= len(units) or sha256(units[unit - 1].encode()).hexdigest() != reference["unit_hash"]:
                evidence = []
                break
            evidence.append({"source": position, "unit": unit})
        if evidence:
            result.append(((text, evidence), group if group is not None else object()))
    return _regroup(result)


def _regroup(items):
    """[(sentence, paragraph key), ...] in order -> paragraphs; consecutive sentences with the same key share a paragraph."""
    paragraphs: list[list] = []
    previous = None
    for sentence, key in items:
        if paragraphs and key == previous:
            paragraphs[-1].append(sentence)
        else:
            paragraphs.append([sentence])
        previous = key
    return paragraphs


def _repair_targets(feedback, previous, pool, views):
    available = {str(c.chunk_id): i for i, c in enumerate(pool, 1)}
    targets = []
    for number, text in feedback.get('rejected_claims', {}).items():
        resolved = []
        old_bindings = previous.get('bindings', {}).get(str(number), [])
        for binding in old_bindings:
            index = available.get(binding['chunk_id'])
            if (index is None or _binding_stamp(pool[index - 1]) != binding['source_stamp']
                    or sha256(pool[index - 1].content.encode()).hexdigest() != binding['content_hash']):
                continue
            units, unit = views[index - 1]['units'], binding['unit']
            if 1 <= unit <= len(units) and sha256(units[unit - 1].encode()).hexdigest() == binding['unit_hash']:
                resolved.append({'source': index, 'unit': unit})
        targets.append({'original_sentence_id': number, 'rejected_text_not_evidence': text,
            'mechanical_finding': feedback.get('mechanical_findings', {}).get(number),
            'checker_finding': feedback.get('checker_findings', {}).get(number),
            'previous_bindings_in_current_sources': resolved,
            'binding_status': 'unchanged' if old_bindings and len(resolved) == len(old_bindings) else 'unresolved'})
    return targets


def _rejection_categories(info: dict) -> dict[str, str]:
    """Diagnostic categories, never an approval or evidence substitute."""
    result = {}
    for number, outcome in info.get("sentence_outcomes", {}).items():
        if outcome == "kaldı":
            continue
        why = str(info.get("debug_why", {}).get(str(number), "")).casefold()
        if str(outcome).startswith("kod:"):
            category = "numeric_or_polarity" if "numeric_polarity" in outcome else "evidence_binding"
        elif why.startswith("kaynak_eksik:"):
            category = "missing_evidence"
        elif why.startswith("ifade_duzelt:"):
            category = "wording_or_condition"
        else:
            category = "semantic_rejection"
        result[str(number)] = category
    return result


def free_verified_answer(provider: AIProvider, **kwargs) -> VerifiedAnswer | None:
    """En çok iki deneme. Model arada yanlış kaynak numarası yazıp bütün cümleleri düşürebiliyor (aynı soru bir koşuda 15/16,
    ötekinde 0/5; ölçüldü: 2026-10-25) ve cevabın ilk cümlesi (soruya doğrudan cevap) kanıtlanamayınca geriye yalnız yan bilgi
    kalabiliyor (zamanaşımı: "beş yıl" kuralı düştü, cevap "Ancak ... on yıl görüşü benimsenmemiştir" diye başladı).
    Bu durumlarda veya uzun taslağın önemli bölümü çıkarıldıysa, geçen süre 45 saniyeyi aşmadıysa
    mevcut iki denemelik bütçe içinde yeniden yazdırılır; sağlayıcı hatası denenmez.

    Seçim: ilk cümlesi kanıtlı cevap önceliklidir. Açılış kanıtlanamadığında tek başına anlaşılabilen
    diğer kanıtlı cümleler kısmi cevap olarak korunur; cümle sayısı bir doğruluk ölçütü değildir."""
    info = kwargs.get("diagnostics")
    info = {} if info is None else info
    kwargs["diagnostics"] = info
    started = monotonic()
    stronger = kwargs.pop("stronger_provider", None)  # a failed first attempt is retried with the stronger model (when configured)
    deferred_research = kwargs.pop('deferred_research', False)
    on_partial = kwargs.get("on_partial")
    attempts: list[tuple[VerifiedAnswer | None, dict]] = []
    # Request-local only: source-linked survivors may be reused for a patch,
    # but the combined answer must pass the full verifier again.
    kwargs["repair_state"] = {}
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        info.clear()
        answer = _free_verified_answer(stronger if attempt > 1 and stronger is not None else provider,
                                       checker_format_retry=attempt == 1, **kwargs)
        info["attempts"] = attempt
        info["rejection_categories"] = _rejection_categories(info)
        attempts.append((answer, dict(info)))
        # A surviving opening is not evidence of a complete answer. The checker
        # may have removed central rights while leaving peripheral paragraphs.
        # Reuse the existing two-attempt budget and recheck the revision fully.
        lost = max(0, info.get('removed', 0) - info.get('repeated_removed', 0)
                   - info.get('semantic_repeated_removed', 0))
        substantial_loss = info.get("draft_sentences", 0) >= 6 and lost >= 2 and (
            lost * 3 >= info.get("draft_sentences", 1)
        )
        incomplete = info.get("coverage_preserved") is False
        logger.info("Serbest cevap deneme %d: cevap=%s lead_removed=%s substantial_loss=%s incomplete=%s kept=%s removed=%s sebep=%s "
                    "taslak=%s tekrar=%s hedefli_onarim=%s paralel_yazma=%s paralel_denetim=%s kategoriler=%s",
                    attempt, answer is not None, info.get("lead_removed"), substantial_loss, incomplete,
                    info.get("kept"), info.get("removed"), info.get("reason"), info.get("draft_sentences"),
                    info.get("repeated_removed"), info.get("targeted_repair"), info.get("parallel_write"),
                    info.get("parallel_check"), info.get("rejection_categories"))
        if incomplete:
            logger.info("Eksik bulunan bölümler: %s | kapsam=%s", info.get("incomplete_parts"),
                        [(row["part_id"], row["why"][:160]) for row in info.get("final_part_coverage", ()) if not row["complete"]])
        # A second attempt pays off when something the sources can supply is missing: a part with no sentence at all, or a part
        # the checker says lacks its sources. When every incomplete part already has sentences and the checker only finds the
        # list of conditions "not complete", a rewrite gave the same sentences again (measured 2026-10-30: 25-50 s for nothing).
        rows = info.get("final_part_coverage", ())
        open_parts = [row for row in rows if not row.get("complete")]
        empty_part = bool(info.get("uncovered_parts")) or any(not row.get("displayed_sentence_ids") for row in open_parts)
        if not incomplete:
            retry_worthy = True
        elif rows and not open_parts:
            # The per-part table says every part is covered; a global "not complete" flag next to it is the checker contradicting
            # itself (measured 2026-10-30: 13 good sentences, then a 60 s retry that made the answer worse).
            retry_worthy = False
        elif not rows:
            # A single-part question has no per-part table to consult. The checker's global "not complete" next to a sizeable proven
            # answer was repeated by the rewrite (measured 2026-10-31: 13 proven sentences, a 30 s second attempt with the same
            # verdict). A rewrite is worth it only for what it can supply: an opening, a large loss, too little, or a source gap.
            source_gap = any(isinstance(why, str) and why.strip().casefold().startswith('kaynak_eksik:')
                             for why in (info.get('debug_why') or {}).values())
            retry_worthy = bool(info.get('lead_removed') or substantial_loss or answer is None
                                or info.get('kept', 0) < _MIN_SENTENCES_FOR_FINAL or source_gap)
        else:
            retry_worthy = empty_part or any(str(row.get("why", "")).startswith("kaynak_eksik") for row in open_parts)
        # What only a rewrite can supply: no opening, a large loss, or a part with no sentence at all. A part that merely lacks
        # sources is worth a retry only when the extra search below finds some.
        needs_rewrite = bool(info.get("lead_removed") or substantial_loss or empty_part or answer is None)
        if answer is not None and not info.get("lead_removed") and not substantial_loss and not (incomplete and retry_worthy):
            if len(attempts) == 1:
                if incomplete:
                    info["partial_answer"] = True  # kept out of the full-answer cache, as for any incomplete answer
                return answer
            break  # select the better verified attempt below
        if info.get('checker_protocol_retries', 0):
            # A checker-only retry replaces the outer writer+checker retry;
            # never add a hidden extra repair cycle or spend more call budget.
            break
        retryable = answer is not None or info.get("reason") in {"too_few_proven", "draft_shape", "checker"}
        # A draft in the wrong format produced nothing to wait for: it is retried (with a format reminder) even after a slow write.
        patience = _FORMAT_RETRY_BEFORE_SECONDS if info.get("reason") == "draft_shape" else _RETRY_ONLY_BEFORE_SECONDS
        kwargs["format_reminder"] = info.get("reason") == "draft_shape"
        explain = kwargs["repair_state"].get("explain_future")
        if explain is not None and info.get("debug_removed"):
            try:
                reasons = explain.result(timeout=25)
            except Exception:  # noqa: BLE001 - no reasons only means a less informed rewrite
                reasons = {}
            if reasons:
                info["debug_why"] = {**(info.get("debug_why") or {}), **reasons}
                info["rejection_categories"] = _rejection_categories(info)
        if info.get("debug_removed"):
            kwargs["revision_feedback"] = {
                "removed_sentences": list(info["debug_removed"].values()),
                "rejected_claims": dict(info["debug_removed"]),
                "checker_findings": info.get("debug_why", {}),
                "mechanical_findings": {n: result for n, result in info.get("sentence_outcomes", {}).items()
                                        if str(result).startswith("kod:")},
                "repair_types": _rejection_categories(info),
                "instruction": (
                    "Önceki taslakta bu ifadeler doğrulanamadı ve çıkarıldı. "
                    "Sorunun ana başlıklarını atlama: mevcut kaynaklardan desteklenebilen "
                    "ifadeleri gerekli koşullarla yeniden yaz ve doğru kanıt birimlerine bağla. "
                    "Kod sayı/birim/sınır reddi verdiyse ilgili sayı, birim ve nitelemeyi gerçekten içeren kaynak "
                    "birimlerini seç; yalnız başka cümledeki bir sayıyı veya önceki cevabı kanıt sayma. "
                    "Bu geri bildirim hukuki kaynak değildir; desteklenmeyen iddiayı tekrarlama."
                ),
            }
        if incomplete:
            feedback = kwargs.setdefault("revision_feedback", {})
            if info.get('decision_coverage'):
                feedback['decision_coverage'] = info['decision_coverage']
            if info.get('incomplete_parts'):
                feedback['incomplete_parts'] = list(info['incomplete_parts'])
            feedback['part_findings'] = [row for row in info.get('final_part_coverage', ())
                                         if not row['complete']]
            feedback["coverage_issue"] = (
                "Denetçi cevabın sorunun tamamını karşılamadığını belirtti. Orijinal sorudaki her alt soruyu "
                "ayrı değerlendir; koşullar ve istisnalar sorulduysa ikisini de yalnız mevcut kanıtlarla açıkla. "
                "Geçici önlemleri nihai hakların cevabı yerine koyma. Eksik başlık için kanıt yoksa uydurma."
            )
        if attempt == _MAX_ATTEMPTS or not retryable or monotonic() - started > patience:
            break  # a second slow attempt would double the wait (measured 90 s answers, 2026-10-25)
        if on_partial is not None and answer is not None and not info.get("uncovered_parts"):
            try:  # the verified answer of this attempt is readable while the second attempt completes it
                on_partial(answer)
            except Exception:  # noqa: BLE001
                logger.exception("Kısmi cevap bildirimi başarısız")
        if answer is not None:
            kwargs.setdefault("revision_feedback", {})["previous_verified_answer"] = answer.text
            kwargs["revision_feedback"]["preservation_instruction"] = (
                "Bu önceki denemede doğrulanmış cevaptır. Desteklenen bilgileri kaybetmeden eksik bölümleri tamamla. "
                "Önceki cevap bağımsız bir kaynak değildir: her cümleyi yeniden sources kanıt birimlerine bağla."
            )
        # A rejected paraphrase is not proof that sources are missing. Re-query
        # only structurally unbound parts, not each sentence the writer worded
        # incorrectly. Revisions still recheck all claims against the evidence.
        retrieve = kwargs.get("retrieve")
        available_ids = {c.chunk_id for c in kwargs.get("contexts", ()) if _usable(c, _POOL_CHARS) is not None}
        missing_parts = [text for text, ids in kwargs.get("parts", ()) if not ids & available_ids]
        missing_parts.extend(info.get("uncovered_parts", ()))
        part_questions = [text for text, _ in kwargs.get('parts', ())]
        missing_parts.extend(part_questions[row['part_id'] - 1]
                             for row in info.get('final_part_coverage', ())
                             if not row['complete'] and row['why'].strip().casefold().startswith('kaynak_eksik:')
                             and 1 <= row['part_id'] <= len(part_questions))
        if info.get('decision_coverage', {}).get('complete') is False:
            missing_parts.append(kwargs['question'])
        evidence_missing = any(isinstance(why, str) and why.strip().casefold().startswith('kaynak_eksik:')
                               for why in (info.get('debug_why') or {}).values())
        if deferred_research and evidence_missing and (incomplete or info.get('lead_removed')):
            # Readiness was provisional, but a wording/condition rejection is
            # not a missing-source finding. Open broad discovery for an explicit
            # evidence gap, not merely because the writer needs a revision.
            missing_parts.extend(text for text, _ in kwargs.get('parts', ()))
        if retrieve is not None and missing_parts:
            from api.ai.evidence_pool import balanced_evidence
            queries = list(missing_parts)
            queries = list(dict.fromkeys(q for q in queries if 5 <= len(q) <= 700))[:3]
            lanes, bindings = [], {}

            def search(query):
                try:
                    return query, balanced_evidence([retrieve(query)], 6)
                except Exception:  # optional evidence enrichment cannot discard a checked answer
                    return query, None

            # One search per missing part, all at once: run one after the other they were ~10 s of dead time between the attempts
            # (measured 2026-10-30). Whatever finishes is used; a failed search only means that part gets no extra source.
            if queries and monotonic() - started <= patience:
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=len(queries)) as search_pool:
                    for query, lane in search_pool.map(search, queries):
                        if lane is not None:
                            lanes.append(lane)
                            bindings[query] = {c.chunk_id for c in lane}
            extra = balanced_evidence(lanes, 6)
            existing = list(kwargs.get("contexts", ()))
            known = {c.chunk_id for c in existing}
            added = [c for c in extra if c.chunk_id not in known]
            if not added and not needs_rewrite and not deferred_research:
                break  # the only finding was missing sources and the search found none: a rewrite would repeat the same sentences
            # The same fixed character budget applies to the revision. Put new
            # evidence between existing chunks so a full first pool cannot
            # silently exclude every newly found source at the budget boundary.
            kwargs["contexts"] = balanced_evidence([existing, added], len(existing) + len(added))
            # Bind newly discovered chunks to the part whose query found them.
            # Do not label every new source as evidence for every question part.
            kwargs["parts"] = [(text, ids | frozenset(bindings.get(text, ())))
                               for text, ids in kwargs.get("parts", ())]
            kwargs.setdefault("revision_feedback", {})["additional_verified_sources"] = len(added)
        kwargs["on_draft"] = None  # the preview was already shown for the first attempt
    answered = [(a, i) for a, i in attempts if a is not None]
    info.clear()
    if not answered:
        info.update(attempts[-1][1])
        info["attempts"] = len(attempts)
        return None
    # More sentences do not make a better conversational answer when its direct
    # opening was rejected. Prefer a verified/repaired opening, then coverage.
    # The opening only decides between answers of comparable size: a three-sentence answer with an opening is not better than
    # a ten-sentence one without (measured 2026-10-30), the lawyer asked for the whole answer.
    most_kept = max(pair[1].get("kept", 0) for pair in answered)
    best_answer, best_info = max(
        answered,
        key=lambda pair: (pair[1].get("coverage_preserved") is not False,
                          pair[1].get("kept", 0) * 2 >= most_kept and not pair[1].get("lead_removed", False),
                          pair[1].get("kept", 0)),
    )
    info.update(best_info)
    info["attempts"] = len(attempts)
    if best_info.get('lead_removed') or best_info.get('coverage_preserved') is False:
        info['partial_answer'] = True  # incomplete candidates must not enter the full-answer cache
    # A removed opening alone does not establish missing coverage. Retain
    # diagnostics, but only an actual coverage finding warrants this warning.
    if best_info.get("coverage_preserved") is False:
        info["partial_answer"] = True
    return best_answer


def _free_verified_answer(
    provider: AIProvider, *, question: str, contexts: Sequence[RAGContext],
    retrieve: Callable[[str], list[RAGContext]] | None = None, history: Sequence[HistoryTurn] = (),
    checker_provider: AIProvider | None = None, diagnostics: dict | None = None,
    checker_format_retry: bool = False,
    on_draft: Callable[[str], None] | None = None, format_reminder: bool = False,
    parts: Sequence[tuple[str, frozenset]] = (),
    revision_feedback: dict | None = None,
    repair_state: dict | None = None,
    parallel_parts: bool = False,
    triage_sources: bool = False,
    on_partial: "Callable[[VerifiedAnswer], None] | None" = None,
    explain_in_background: bool = False,
) -> VerifiedAnswer | None:
    info = diagnostics if diagnostics is not None else {}
    started = monotonic()
    from api.ai.providers import OllamaProvider
    local_structured = isinstance(provider, OllamaProvider)  # every local model shares its window with instructions and output
    # The local runner shares its window with instructions and output. This
    # bounds evidence admission, not user answer length; never clip a source.
    pool_chars = min(_POOL_CHARS, max(2400, provider.num_ctx - provider.max_output_tokens)) if local_structured else _POOL_CHARS

    def fail(reason: str) -> None:
        info.update(status="fallback", reason=reason, seconds=round(monotonic() - started, 1))
        return None

    # sources: the question's own verified sources, usable ones only, within the character budget
    pool: list[RAGContext] = []
    seen: set = set()
    used_chars = 0
    contexts = list(contexts)
    # Off-topic sources are removed BEFORE the character budget, so relevant ones take their place. A repeat attempt reuses the
    # first attempt's decision: the repair state is bound to the exact source pool.
    triage_started = monotonic()
    unrelated_ids = set((repair_state or {}).get("unrelated_chunks", ()))
    if triage_sources and not unrelated_ids and not local_structured and not revision_feedback:
        unrelated_ids = {contexts[n - 1].chunk_id for n in _drop_unrelated_sources(provider, question, contexts, parts)}
    if unrelated_ids:
        logger.info("Alakasız kaynak ayıklama: %d/%d çıkarıldı: %s", len(unrelated_ids), len(contexts),
                    [c.reference_line[:60] for c in contexts if c.chunk_id in unrelated_ids])
        contexts = [c for c in contexts if c.chunk_id not in unrelated_ids]
    info["triage_dropped"] = len(unrelated_ids)
    info["triage_seconds"] = round(monotonic() - triage_started, 1)
    admission = dict(received=len(contexts), unusable=0, duplicate=0, over_budget=0, accepted=0)
    for context in contexts:
        usable = _usable(context, pool_chars)
        if usable is None:
            admission['unusable'] += 1
            continue
        if usable.chunk_id in seen:
            admission['duplicate'] += 1
            continue
        if used_chars + len(usable.content) > pool_chars:
            admission['over_budget'] += 1
            continue
        seen.add(usable.chunk_id)
        used_chars += len(usable.content)
        pool.append(usable)
    admission['accepted'] = len(pool)
    info['source_admission'] = admission
    if not pool:
        return fail("no_sources")
    views = synthesis._source_views(pool, pool_chars)
    if not views:
        return fail("source_shape")
    info["sources"] = [c.reference_line[:70] for c in pool]
    fingerprint = (tuple(str(c.chunk_id) for c in pool), json.dumps(views, ensure_ascii=False, sort_keys=True, default=str))
    previous = dict(repair_state or {})
    if repair_state is not None:
        repair_state.clear()
    preserved = previous.get("paragraphs", []) if previous.get("fingerprint") == fingerprint else []
    if not preserved and previous.get("chunk_paragraphs"):
        preserved = _remap_preserved(previous["chunk_paragraphs"], pool, views)

    # 1. the model reads the sources and writes flowing paragraphs, each sentence tied to the source sentences it rests on
    payload = {
        "question": question,
        "history_for_understanding_only": [{"question": t.question, "answer": t.answer} for t in history],
        "sources": [{**{k: v for k, v in view.items() if k not in {"text", "units"}},
                     "evidence_units": [{"unit": i, "text": unit} for i, unit in enumerate(view["units"], 1)]}
                    for view in views]}
    from api.ai.numeric_support import user_threshold_notes
    threshold_notes = user_threshold_notes([c.content for c in pool], question)
    if threshold_notes:
        payload["user_number_warnings"] = threshold_notes
    # each part of the question with the pool numbers of the sources found for it (see `plan_question`)
    part_sources = [(text, {i for i, c in enumerate(pool, 1) if c.chunk_id in ids}) for text, ids in parts]
    admitted_ids = {c.chunk_id for c in pool}
    info['part_admission'] = [dict(part=n, discovered=len(ids), admitted=len(ids & admitted_ids))
                              for n, (_text, ids) in enumerate(parts, 1)]
    info["plan"] = [text for text, _ in part_sources]
    if len(part_sources) > 1:
        payload["parts"] = [{"part": n, "question": text, "sources": sorted(found)}
                            for n, (text, found) in enumerate(part_sources, 1)]
    if format_reminder:  # the previous attempt came back without a single valid "cümle @@ s.u" line
        payload["format_reminder"] = _FORMAT_REMINDER
    if revision_feedback:
        payload["revision_feedback_not_evidence"] = revision_feedback
        targets = _repair_targets(revision_feedback, previous, pool, views)
        if targets:
            payload['rejected_claim_repairs'] = {
                'targets': targets,
                'instruction': (
                    'Bunlar önceki başarısız kaynak bağlantılarıdır; kanıt veya doğru bağlantı önerisi değildir. '
                    'Eksik sayı/birim/alt-üst sınır/koşul için sources içindeki gerçek birimleri incele; '
                    'gereken diğer birim varsa cümlenin @@ bağlantısına onu da ekle. '
                    'unresolved durumunda eski kaynak numarasını kopyalama. '
                    'Kaynak desteklemiyorsa koşulu kaldırarak veya sayı değiştirerek geçirmeye çalışma.'
                ),
            }
    if preserved:
        payload["targeted_repair"] = {
            "retained_sentences_not_evidence": [[text for text, _ in paragraph] for paragraph in preserved],
            "instruction": (
                "Yalnız eksik veya reddedilen bölümü tamamlayan cümleleri yaz; korunan cümleleri tekrar yazma. "
                "Sorunun tamamını anlamak için korunan cümleleri oku ancak onları kanıt sayma. "
                "Yeni her cümleyi sources içindeki kanıt birimlerine @@ biçimiyle bağla."
            ),
        }
    raw = ""
    part_starts: list[int] = []
    lead_numbers = {1}  # flat numbers of the sentences that open a part: each is the direct answer to its part
    parallel_raw = None
    if parallel_parts and len(part_sources) > 1 and not local_structured and not preserved and not revision_feedback:
        written = _write_parts_in_parallel(provider, payload, part_sources)
        if written is not None:
            parallel_raw, part_starts = written
            lead_numbers = set(part_starts)
            info["parallel_write"] = len(part_sources)
        else:
            info["parallel_write_fallback"] = True
    try:
        if local_structured:
            from api.ai.local_synthesis_schema import synthesis_schema
            schema = synthesis_schema('draft', payload)
            local_instruction = synthesis.CLOUD_WRITE_INSTRUCTION + (
                '\nHer evidence kaydı kaynak ve tam cümle numarasıdır: {"source":1,"unit":2}. '
                'Kaynak içindeki değişiklik dipnotunu güncel ana hüküm yerine kullanma. '
                'Taraf iddiasını veya alt mahkeme görüşünü Yargıtay hükmü diye sunma. '
                'Genel araştırma sorusunu kişisel tutar/tarih sorusuna dönüştürme. '
                'Yalnız claims, question, source_gap alanlarıyla JSON yaz.')
            if preserved:
                local_instruction += ('\nONARIM MODU: targeted_repair varsa korunan cümleleri yeniden yazma; '
                                      'yalnız eksik bölümü tamamlayan yeni kanıtlı cümleleri yaz.')
            structured = provider.generate_structured(system_instruction=local_instruction,
                prompt=json.dumps(payload, ensure_ascii=False), schema=schema)
            value = json.loads(structured)
            # Format adaptation only: the ordinary parser, exact source-unit
            # resolver, numeric guards and independent checker still run below.
            raw = '\n\n'.join(claim['text'] + ' @@ ' + ' '.join(
                f"{item['source']}.{item['unit']}" for item in claim['evidence']) for claim in value['claims'])
        else:
            raw = parallel_raw if parallel_raw is not None else provider.generate(
                system_instruction=WRITE_INSTRUCTION, prompt=json.dumps(payload, ensure_ascii=False))
        info["write_seconds"] = round(monotonic() - started, 1)
        paragraphs = _parse(raw)
        if preserved:
            # No unchecked concatenation: this merged draft goes through all
            # numeric, evidence and independent semantic checks below.
            combined = [*paragraphs, *preserved] if previous.get("lead_removed") else [*preserved, *paragraphs]
            seen_sentences = set()
            paragraphs = []
            for paragraph in combined:
                unique = []
                for text, evidence in paragraph:
                    key = (text, tuple((e["source"], e["unit"]) for e in evidence))
                    if key not in seen_sentences:
                        seen_sentences.add(key)
                        unique.append((text, evidence))
                if unique:
                    paragraphs.append(unique)
            info["targeted_repair"] = True
    except AIProviderError:
        return fail("provider")
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        info["draft_error"] = str(exc)[:80]
        info["debug_draft"] = raw[:1200]
        return fail("draft_shape")
    flat = [(text, evidence) for paragraph in paragraphs for text, evidence in paragraph]
    if repair_state is not None:
        repair_state['bindings'] = _binding_snapshot(flat, pool, views)
    paragraph_numbers = [i for i, paragraph in enumerate(paragraphs, 1) for _ in paragraph]
    info["draft_sentences"] = len(flat)
    if on_draft is not None:
        try:  # the text is on screen while it is being proven; the proven version replaces it
            on_draft("\n\n".join(" ".join(text for text, _ in paragraph) for paragraph in paragraphs))
        except Exception:  # noqa: BLE001
            logger.exception("Taslak önizlemesi gönderilemedi")

    # 2. the code's own gates, sentence by sentence
    candidates: list[tuple[int, synthesis._Claim]] = []
    outcome: dict[int, str] = {}
    for number, (text, evidence) in enumerate(flat, 1):
        try:
            from api.ai.decision_attribution import irrelevant_case_filler
            if irrelevant_case_filler(text, question):
                raise synthesis._Rejected('answer_focus', number, ('irrelevant_case_filler',))
            candidates.append((number, synthesis._checked_claim(number, text, evidence, pool, views, lenient=True, conclusion=number in lead_numbers, known=question)))
        except synthesis._Rejected as exc:
            outcome[number] = f"kod:{exc.reason}:{','.join(exc.checks)}"
            info.setdefault("debug_rejected", {})[str(number)] = {"cümle": text[:400], "kanıt": evidence}
        except (ValueError, TypeError, KeyError):
            outcome[number] = "kod:kanıt_biçimi"
    if len(candidates) < _MIN_SENTENCES_KEPT:
        info["sentence_outcomes"] = {str(k): v for k, v in sorted(outcome.items())}
        info["debug_removed"] = {str(n): text[:400] for n, (text, _) in enumerate(flat, 1)}
        info["debug_draft"] = raw[:1800]
        return fail("too_few_proven")

    # 3. independent check of every remaining sentence against its source text
    # Check the full context of cited sources, not dozens of unrelated search
    # hits. Keep source numbers stable and retain evidence for an entirely
    # unrepresented part so the checker can still detect missing coverage.
    check_source_ids = {source for _, claim in candidates for source, _ in claim.evidence}
    for _text, found in part_sources:
        if not found & check_source_ids:
            check_source_ids.update(found)
    check_views = [view for view in views if view['source'] in check_source_ids]
    info['checker_source_count'] = len(check_views)
    check_payload = {
        "question": question, "user_question": question,
        "sources": [{k: v for k, v in view.items() if k != "units"} for view in check_views],
        "claims": [{"id": i, "text": claim.text, "paragraph": paragraph_numbers[number-1],
                    "evidence": [{"source": source, "quote": span} for source, span in claim.evidence],
                    **({"mechanical_notes": list(claim.notes)} if claim.notes else {})}
                   for i, (number, claim) in enumerate(candidates, 1)],
        "question_to_user": None, "source_gap": False}
    if threshold_notes:
        check_payload["user_number_warnings"] = threshold_notes  # the same tier guidance the writer got; not evidence
    if outcome:
        check_payload["discarded_before_review"] = [flat[n-1][0] for n in outcome]
    if len(part_sources) > 1:
        check_payload["question_parts"] = [text for text, _ in part_sources]
    from api.ai.part_coverage import INSTRUCTION as COVERAGE_INSTRUCTION
    coverage_parts = len(part_sources) if len(part_sources) > 1 else 0
    # reasons for the refused sentences are asked for separately, in the background (see `_explain_rejections`)
    check_instruction = LEAD_CHECK_INSTRUCTION_DEFERRED if explain_in_background else LEAD_CHECK_INSTRUCTION
    verdict = None
    duplicates_future = (_EXPLAIN_POOL.submit(_cross_part_duplicates, checker_provider or provider, candidates, part_starts)
                         if part_starts and coverage_parts and len(candidates) >= 4 else None)
    if part_starts and coverage_parts:
        merged = _check_parts_in_parallel(checker_provider or provider, payload=check_payload, candidates=candidates,
                                          part_sources=part_sources, part_starts=part_starts,
                                          allow_format_retry=checker_format_retry, instruction=check_instruction,
                                          on_part_done=(_PartPreview(on_partial, candidates, paragraph_numbers, pool, len(part_sources))
                                                        if on_partial is not None else None))
        if merged is not None:
            verdict, info["checker_part_coverage"], duplicate_rows = merged
            info.pop("checker_duplicates", None)
            if duplicate_rows:
                info["checker_duplicates"] = duplicate_rows
            info.update(checker_protocol_status="valid", checker_protocol_attempts=["valid"], checker_protocol_retries=0,
                        parallel_check=len(part_sources))
        else:
            info["parallel_check_fallback"] = True
    try:
        if verdict is None:
            from api.ai.checker_protocol import check_claims
            verdict = check_claims(checker_provider or provider,
                                  instruction=check_instruction + (COVERAGE_INSTRUCTION if coverage_parts else ''),
                                  payload=check_payload, allow_format_retry=checker_format_retry,
                                  diagnostics=info, part_count=coverage_parts)
    except AIProviderError:
        return fail("provider")
    info["check_seconds"] = round(monotonic() - started - info.get("write_seconds", 0), 1)
    if info.get('checker_protocol_status') in {'source_policy_rejected', 'clarification_rejected'}:
        # A well-formed negative verdict is a substantive refusal, not a
        # transport/schema failure. Coverage is intentionally unavailable for
        # these verdicts; checking for it first hides the actual rejection.
        info['checker_status'] = info['checker_protocol_status']
        reasons = _reasons(verdict)
        info['debug_why'] = {str(number): reasons.get(str(index), info['checker_status'])
                             for index, (number, _) in enumerate(candidates, 1)}
        info['debug_removed'] = {str(number): claim.text[:400] for number, claim in candidates}
        info['sentence_outcomes'] = {str(number): 'denetçi_reddetti' for number, _ in candidates}
        return fail('checker')
    if coverage_parts and 'checker_part_coverage' not in info:
        return fail('checker_protocol')
    approved = synthesis._fully_approved_ids(verdict, len(candidates))
    if approved is not None and preserved:
        # A sentence approved in the previous attempt (code gates AND independent checker), re-bound to byte-identical source units
        # and passing the code gates again, stays approved. Re-judging it gave a different verdict on the same input (measured
        # 2026-10-30: 11 approved sentences, 9 of them refused on the repeat check, and the retry made the answer worse). The
        # checker still sees every sentence for the coverage verdict; only its sentence-level refusal of old approvals is not final.
        def _key(text, evidence):
            return text, tuple((e["source"], e["unit"]) for e in evidence)
        earlier = {_key(text, evidence) for paragraph in preserved for text, evidence in paragraph}
        sticky = {index for index, (number, _claim) in enumerate(candidates, 1) if _key(*flat[number - 1]) in earlier}
        info["sticky_approved"] = len(sticky - approved)
        approved = approved | sticky
    if duplicates_future is not None:
        try:
            extra = duplicates_future.result(timeout=1.0)
        except Exception:  # noqa: BLE001 - no verdict in time: the repeat stays, nothing is dropped
            extra = []
        known = {row["id"] for row in info.get("checker_duplicates", ())}
        if extra:
            info["checker_duplicates"] = [*info.get("checker_duplicates", ()), *(row for row in extra if row["id"] not in known)]
    if explain_in_background and approved is not None and repair_state is not None and not local_structured:
        refused = [(number, claim) for index, (number, claim) in enumerate(candidates, 1) if index not in approved]
        # in the background, so the answer is not delayed: only a retry waits for it (see `free_verified_answer`)
        repair_state["explain_future"] = (_EXPLAIN_POOL.submit(_explain_rejections, checker_provider or provider, question, refused, views)
                                          if refused else None)
    # Checker IDs enumerate candidates *after* mechanical rejection. Map back
    # to original draft IDs before attaching feedback or classifying failures.
    # Otherwise sentence 2's condition finding could be sent as sentence 1's
    # repair instruction after sentence 1 failed the numeric gate.
    candidate_reasons = _reasons(verdict)
    original_reasons = {str(number): candidate_reasons[str(index)]
                        for index, (number, _) in enumerate(candidates, 1)
                        if str(index) in candidate_reasons}
    try:
        info["coverage_preserved"] = synthesis._json(verdict).get("coverage_preserved") is True
    except (ValueError, TypeError, AttributeError, RecursionError):
        info["coverage_preserved"] = False
    info["checker_status"] = (info.get('checker_protocol_status', 'invalid_or_not_source_only') if approved is None else
                              "all_rejected" if not approved else "approved_subset")
    # Preserve concrete revision feedback even when no sentence is approved.
    # A malformed verdict is not a rejection/approval of any individual claim.
    if approved is not None:
        info["sentence_outcomes"] = {
            **{str(k): v for k, v in outcome.items()},
            **{str(number): "kaldı" if index in approved else "denetçi_reddetti"
               for index, (number, _) in enumerate(candidates, 1)},
        }
        info["debug_removed"] = {
            str(n): flat[n-1][0][:400] for n in range(1, len(flat)+1)
            if info["sentence_outcomes"].get(str(n)) != "kaldı"
        }
    if not approved:
        info["debug_verdict"] = str(verdict)[:1500]
        info["debug_why"] = original_reasons
        return fail('checker_protocol' if info.get('checker_protocol_status', '').startswith('invalid_') else "checker")
    info["debug_why"] = original_reasons
    proven = {number: claim for index, (number, claim) in enumerate(candidates, 1) if index in approved}
    for number, _claim in candidates:
        outcome.setdefault(number, "kaldı" if number in proven else "denetçi_reddetti")
    lead = None
    info["lead_removed"] = 1 not in proven and lead is None
    info["sentence_outcomes"] = {str(k): v for k, v in sorted(outcome.items())}
    info["debug_removed"] = {str(n): flat[n - 1][0][:400] for n, v in outcome.items() if v != "kaldı"}
    if len(proven) < _MIN_SENTENCES_KEPT:
        return fail("too_few_proven")

    # 4. the answer is built from what survived, keeping the paragraphs; markers are the real sources of each paragraph
    lines: list[str] = []
    cursor = 0
    pending_lead = lead
    shown: list[str] = [lead.text] if lead is not None else []
    displayed_ids: set[int] = set()
    shown_ids: list[int] = []
    duplicate_aliases: dict[int, int] = {}
    semantic_duplicates = {
        candidates[row['id'] - 1][0]: candidates[row['duplicate_of'] - 1][0]
        for row in info.get('checker_duplicates', ())
        if row['id'] in approved and row['duplicate_of'] in approved
    }
    from api.ai.numeric_support import same_numeric_scope
    for paragraph in paragraphs:
        kept = [pending_lead] if pending_lead is not None else []  # the repaired direct answer opens the first paragraph
        pending_lead = None
        for offset in range(len(paragraph)):
            claim = proven.get(cursor + offset + 1)
            # Çıkarılan cümleye gönderme yapan cümle ("Bu tazminatın hesabında...") kendi başına anlamsız kalır: onunla gider.
            previous = proven.get(cursor + offset)
            previous_was_shown = previous is not None and previous.text in shown
            if claim is not None and _DANGLING.match(claim.text) and not kept and not previous_was_shown:
                info["dangling_removed"] = info.get("dangling_removed", 0) + 1
                proven.pop(cursor + offset + 1)
                continue
            if claim is not None and _ABOUT_SOURCES.search(claim.text):
                # "Kaynaklarda ... bulunmuyor" is not an answer; what we could not find is said by the code, not the model.
                info["about_sources_removed"] = info.get("about_sources_removed", 0) + 1
                proven.pop(cursor + offset + 1)
                continue
            if claim is not None:
                target = semantic_duplicates.get(cursor + offset + 1)
                target = duplicate_aliases.get(target, target)
                if (target in displayed_ids and target in proven
                        and same_numeric_scope(proven[target].text, claim.text)):
                    # Only an explicit independent equivalence verdict over two approved claims (the kept one is shown and
                    # proven, so nothing unproven is added) and the same numeric scope permit semantic deduplication.
                    # No fuzzy word similarity gate.
                    info['semantic_repeated_removed'] = info.get('semantic_repeated_removed', 0) + 1
                    duplicate_aliases[cursor + offset + 1] = target
                    continue
                duplicate = _repeat_of(claim.text, shown)
                if (duplicate is not None
                        and proven[shown_ids[duplicate]].evidence == claim.evidence):
                    info["repeated_removed"] = info.get("repeated_removed", 0) + 1
                    duplicate_aliases[cursor + offset + 1] = shown_ids[duplicate]
                    continue
            if claim is not None:
                kept.append(claim)
                shown.append(claim.text)
                shown_ids.append(cursor + offset + 1)
                displayed_ids.add(cursor + offset + 1)
        cursor += len(paragraph)
        if not kept:
            continue
        # Kullanıcı kararı 2026-10-25: paragraf sonlarında [K1] [K2] işareti yok (cevabı parçalı gösteriyordu). Kullanılan kaynaklar
        # cevabın altındaki "Kaynaklar" listesinde (`contexts`) durur; her cümle zaten kanıtlanmıştır.
        from api.ai.decision_attribution import with_case_identity
        lines.append(" ".join(with_case_identity(claim.text, claim.evidence, pool) for claim in kept))
    if not lines:
        return fail("too_few_proven")  # the dangling-sentence rule can empty the answer (measured with pro: an accepted empty reply)
    if repair_state is not None:
        saved_bindings = repair_state.get("bindings", {})
        repair_state.update(fingerprint=fingerprint, lead_removed=info["lead_removed"], unrelated_chunks=list(unrelated_ids),
                            # Sentences keep their paragraph: one paragraph per sentence turned a repaired answer into a column of
                            # single lines (measured 2026-10-30).
                            paragraphs=_regroup([((text, evidence), paragraph_numbers[n - 1])
                                                 for n, (text, evidence) in enumerate(flat, 1) if n in displayed_ids]),
                            chunk_paragraphs=[(text, saved_bindings.get(str(n), []), paragraph_numbers[n - 1])
                                              for n, (text, evidence) in enumerate(flat, 1) if n in displayed_ids])
    displayed_claims = [claim for n, claim in proven.items() if n in displayed_ids]
    shown_sources = {source for claim in displayed_claims for source, _ in claim.evidence}
    used = list(dict.fromkeys(source for claim in displayed_claims for source, _ in claim.evidence))
    from api.ai.decision_requirements import distinct_decisions, requested_decision_count
    requested_count = requested_decision_count(question)
    if requested_count > 1:
        cited_count = distinct_decisions(question, [pool[i - 1] for i in used])
        info['decision_coverage'] = dict(requested=requested_count, cited=cited_count,
                                         complete=cited_count >= requested_count)
        if cited_count < requested_count:
            info['coverage_preserved'] = False
            info['partial_answer'] = True
    if info.get("dangling_removed") or info.get("about_sources_removed"):
        # Coverage was judged before these structural filters. It cannot be
        # carried over as complete after removing a distinct checked claim.
        info["coverage_preserved"] = False
        info["partial_answer"] = True
    if coverage_parts:
        from api.ai.part_coverage import final_coverage
        matrix = final_coverage(info['checker_part_coverage'],
            {i: number for i, (number, _) in enumerate(candidates, 1)}, displayed_ids,
            duplicate_aliases=duplicate_aliases)
        info['final_part_coverage'] = matrix
        incomplete_parts = [part_sources[row['part_id'] - 1][0] for row in matrix if not row['complete']]
        if incomplete_parts:
            info['incomplete_parts'] = incomplete_parts
            info['coverage_preserved'] = False
            info['partial_answer'] = True
    missing = [text for text, found in part_sources if not found & shown_sources] if len(part_sources) > 1 else []
    # A part that asks for a period is not answered by sentences that state none (2026-10-30: "mal paylaşımı için hangi süre"
    # was "covered" by a sentence on when the period starts for a foreign judgment, with no period named at all).
    for text, found in part_sources:
        if text not in missing and _asks_period(text) and not any(
                _states_period(claim.text) for claim in displayed_claims if found & {source for source, _ in claim.evidence}):
            missing.append(text)
    if missing:
        # A part of the question without a single proven sentence is not dropped silently (measured 2026-10-25: "mal paylaşımı
        # için hangi süre" got no source and the answer skipped it). This is not a legal claim, only what we could not find.
        info["uncovered_parts"] = missing
        info["coverage_preserved"] = False
        info["partial_answer"] = True
        lines.append(_uncovered_note(missing, question))
    info.update(status="accepted", reason="source_prose", kept=len(displayed_claims), removed=len(flat) - len(displayed_claims),
                cited_decisions=sum(1 for i in used if pool[i - 1].source_type == "court_decision"),
                pool_decisions=sum(1 for c in pool if c.source_type == "court_decision"),
                seconds=round(monotonic() - started, 1))
    return VerifiedAnswer(text="\n\n".join(lines), contexts=tuple(pool[i - 1] for i in used), unverified_markers=())
