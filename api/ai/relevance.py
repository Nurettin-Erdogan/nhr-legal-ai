"""Conservative query intent constraints, not a legal correctness classifier.

Topic groups are retrieval hints, never evidence or hard-coded legal answers.
All groups must match the actual passage, not just citation metadata. Unknown
questions retain lexical ranking and the model's explicit abstention contract.
"""
from dataclasses import dataclass
import re

from api.ai.search_plan import normalize
from api.ai.query_vocabulary import expand_search_terms


_CASE_REQUEST = re.compile(r'\b(?:içtihat\w*|emsal\w*|karar(?:ı|ını|ında|ları|larını|larında)|'
                           r'yargıtay|danıştay|sayıştay|kdk|anayasa mahkemesi)\b')


def case_law_requested(question: str) -> bool:
    return bool(_CASE_REQUEST.search(normalize(question)))


@dataclass(frozen=True)
class Intent:
    name: str
    groups: tuple[tuple[str, ...], ...]
    statute: tuple[str, str] | None = None


def question_intent(question: str) -> Intent | None:
    q = normalize(question)
    # "zam" yalnız kelime başında ve "zaman" değilken kira artışıdır; "ne zaman ödenir",
    # "zamanaşımı" gibi sorular kira artışı niyetine düşmemeli (ölçüldü: 2026-10-02).
    if 'kira' in q and (any(t in q for t in ('tüfe', 'artış', 'artır')) or re.search(r'\bzam(?!an)', q)):
        return Intent('rent_increase', (('kira',), ('tüfe', 'tüketici fiyat', 'artış', 'artır')),
                      ('6098', '344'))
    if ('kira' in q and re.search(r'öde(?:mez|medi|miyor)|ödenme|temerrüt', q)
            and not re.search(r'ürün|hasılat|tarla|tarım|icra|ödeme emri|iki\s+.*ihtar', q)):
        # Reuse the existing corpus lookup hint (statute_hints.kira_temerrut).
        # General residential/non-payment questions must not borrow the longer
        # deadline from a different lease regime merely because ANN found it.
        return Intent('rent_default', (('kira', 'kiracı'), ('öde', 'ifa', 'temerrü', 'yazılı')),
                      ('6098', '315'))
    # Birden fazla tazminat/hak birlikte sorulursa tek bir maddeyi zorunlu tek
    # dayanak yapma. İlgili her madde yine doğrulanmış korpustan getirilir.
    if 'kıdem' in q and 'tazminat' in q and not any(term in q for term in ('ihbar', 'işe iade')):
        return Intent('severance', (('kıdem tazminat',), ('işçi', 'hizmet ak', 'iş sözleş', 'fesih', 'feshed')),
                      ('1475', '14'))
    if (re.search(r'çalıştım|çalışıyorum|çalışıyordum|işveren|işyer|işten|maaş|ücretim', q)
            and re.search(r'çıkarıldım|çıkardı|işten çıkar|işten at|kovuldum', q)):
        # Everyday employment narrative, not a conclusion about entitlement.
        # Do not select one sole primary provision: several possible components
        # need their own retrieved sources and case conditions.
        return Intent('employment_termination', (('işçi', 'işveren', 'iş sözleş', 'hizmet ak'),
                                                 ('fesih', 'feshed', 'bildirim', 'kıdem', 'tazminat')))
    if 'itirazın iptal' in q:
        return Intent('objection_annulment', (('itirazın iptal',),), ('2004', '67'))
    if 'işe iade' in q and (re.search(r'\bsüre', q) or any(t in q for t in ('ne zaman', 'kaç gün', 'kaç ay', 'kaç hafta'))):
        # Süreyle birlikte şart/hak sahipliği de sorulmuşsa yalnız m. 20'ye
        # kilitlenme: m. 18 koşullarının kaynak havuzuna girmesine izin ver.
        # Basit süre sorularındaki hızlı, güncel m. 20 yolu korunur.
        if re.search(r'şart\w*|koşul\w*|hak kazan\w*', q):
            return None
        # İşe iade için başvuru usulü 2017'de değişti (önce arabulucu, sonra dava). Sözcük araması bu soruya yalnız eski
        # usulü anlatan 2015-2016 kararlarını getiriyordu (ölçüldü: 2026-10-06); güncel kural İş Kanunu m. 20'dedir.
        return Intent('reinstatement_deadline', (('işe iade', 'arabulucu', 'iş mahkemesi'), ('ay içinde', 'hafta içinde')),
                      ('4857', '20'))
    if 'yıllık izin' in q and any(t in q for t in ('ispat', 'kanıt', 'yük')):
        return Intent('leave_proof', (('yıllık izin',), ('ispat yük', 'izin defter', 'imzalı')))
    if 'idari' in q and any(t in q for t in ('süre', 'kaç gün')):
        return Intent('administrative_deadline', (('idari', 'idare mahkeme', 'danıştay'),
                      ('süre', 'gün')), ('2577', '7'))
    if 'bireysel başvuru' in q:
        return Intent('constitutional_application', (('bireysel başvuru',),), ('6216', '47'))
    if 'ortak velayet' in q:
        if any(t in q for t in ('şart', 'koşul')):
            return Intent('joint_custody', (('ortak velayet',),
                          ('yarar', 'rıza', 'görüş', 'idrak', 'menfaat', 'uzlaş', 'istek', 'uyum')))
        return Intent('joint_custody', (('ortak velayet',),))
    return None


# Soru kalıbı ve kanun adı sözcükleri pasajın konusunu taşımaz: "4857 sayılı İş Kanunu madde 18 neyi düzenler?" sorusunda
# "kanunu/düzenler/neyi" pasajda geçmediği için doğru madde "alakasız" sayılıp cevap "yeterli kaynak yok" oluyordu (ölçüldü: 2026-10-04).
GENERIC_QUESTION_WORDS = frozenset((
    'kanun', 'kanunu', 'kanunun', 'kanununun', 'madde', 'maddesi', 'maddesinde', 'sayılı', 'sayili', 'neyi', 'neler', 'nelerdir',
    'nedir', 'düzenler', 'düzenlenir', 'düzenlenmiştir', 'düzenlemiştir', 'hangi', 'nasıl', 'hakkında', 'ilişkin',
    # "olmalı" her metindeki "olması/olmak/olmadığı" ile eşleşir: "İhtar süresi kaç gün olmalı?" sorusuna, içinde yalnız
    # "süre" ve "olması" geçen temyiz harcı muhtırası cümlesi "alakalı" sayılıp cevap oldu (ölçüldü: 2026-10-06).
    'olmalı', 'olmalıdır', 'olmak', 'olması', 'olacak', 'olarak', 'olan',
    # Kişi soran soru sözcüğü cevap satırında geçmez ("Alacaklı kimdir?" → "Alacaklı: …").
    'kimdir', 'kimler', 'kimlerdir',
))


_PAYMENT_STATUS_RE = re.compile(
    r"\b(?:öden(?:miş|di|memiş|medi|mektedir|memektedir|iyor|miyor)\w*|"
    r"öde(?:miş|di|memiş|medi|mektedir|memektedir|miyor)\w*|"
    r"yatırıl(?:mış|dı|mamış|madı)\w*|tahsil\s+edil(?:miş|di|memiş|medi)\w*|"
    r"ödeme(?:si|sinin)?\s+(?:yapıl(?:mış|dı|mamış|madı)\w*|yok\w*))"
)
_NEGATIVE_PAYMENT_RE = re.compile(r"memiş|medi|memekte|mıyor|miyor|muyor|müyor|mamış|madı|yok")
_CONDITIONAL_PAYMENT_RE = re.compile(
    r"\b(?:öden|öde|yatırıl)\w*(?:mişse|mışsa|memişse|mamışsa|diğinde|dığında|mediğinde|madığında|seydi|saydı)\b"
    r"|\b(?:halinde|hâlinde|durumunda|takdirde|aksi halde)\b"
    r"|\b\w+(?:mazsa|mezse|yorsa)\b"
    # A conditional payment rule may attach its condition to a different verb:
    # "iki ihtara sebep olmuşsa" and "sebep olması halinde" are both conditions,
    # not an assertion that the tenant actually failed to pay.
    r"|\b\w+(?:mişse|mışsa|muşsa|müşse)\b"
)
_UNPERFORMED_PAYMENT_DUTY_RE = re.compile(
    r"\b(?:bedel\w*|ücret\w*|alacağ\w*|ödeme\s+borc\w*|borc\w*|giderin?\w*)\b[^.;]{0,80}?\b(?:ifa\s+etmez\w*|yerine\s+getirmez\w*)"
)
_SHORT_PREDICATE_RE = re.compile(r"\b(?:yoktur|yok|değildir|bulunmamaktadır|bulunmuyor)\b")
_SUBJECT_SUFFIX_RE = re.compile(
    r"(?:larının|lerinin|larını|lerini|larında|lerinde|nun|nün|nın|nin|ları|leri|lar|ler)$"
)
_FACT_RELATION_PREFIXES = (
    "tarih", "tutar", "bedel", "miktar", "ödeme", "öden", "öde", "yatır", "tahsil", "durum", "süre",
    "başlang", "belge", "evrak", "karşılaştır", "karşılastır", "incele", "odaklan", "özetle", "raporla",
    "çekil", "veril", "hesapla", "bulun", "belirt", "göster", "yazıl", "yazan", "aylık", "günlük", "yıllık", "brüt",
)
_DOCUMENT_KINDS = ("vekaletname", "ihtarname", "sözleşme", "kontrat", "rapor", "dilekçe",
                   "makbuz", "tutanak", "mazbata", "tebligat", "fatura", "bordro", "protokol")


def short_document_fact(text: str) -> bool:
    """Allow short factual predicates, not arbitrary two-word document headings."""
    value = normalize(text)
    return bool(_PAYMENT_STATUS_RE.search(value) or _SHORT_PREDICATE_RE.search(value))


def payment_polarity_supported(claim: str, source: str) -> bool:
    """Do not turn an unpaid fact into a paid fact (or vice versa).

    This is a narrow subject/polarity guard, not verification of tense, chronology
    or conditional entailment; the separate model checker remains mandatory.
    Conflicting states for the same subject are not resolved by guessing.
    """
    required = {_NEGATIVE_PAYMENT_RE.search(match.group()) is not None
                for match in _PAYMENT_STATUS_RE.finditer(normalize(claim))}
    if not required:
        return True
    from api.ai.source_support import _document_units
    subjects = _fact_subjects(claim)
    known = set()
    conditional_claim = bool(_CONDITIONAL_PAYMENT_RE.search(normalize(claim)))
    for unit in _document_units(source):
        value = normalize(unit)
        if subjects and sum(stem in value for stem in subjects) < min(2, len(subjects)):
            continue
        if bool(_CONDITIONAL_PAYMENT_RE.search(value)) != conditional_claim:
            continue
        known.update(_NEGATIVE_PAYMENT_RE.search(match.group()) is not None
                     for match in _PAYMENT_STATUS_RE.finditer(value))
        if conditional_claim:
            # "ödemiyorsa" and "ödememesi durumunda" are the same negative
            # payment *condition*. Nominal forms are not added to the factual
            # payment-status parser: a hypothetical rule still cannot prove
            # that a user's rent has actually been paid or remains unpaid.
            known.update(bool(re.search(r"memesi|maması", match.group()))
                         for match in re.finditer(r"\b(?:öde|öden)(?:mesi|ması|memesi|maması)\b", value))
            # "ödeme borcunu ifa etmezse" (TBK m. 315) is the same negative payment condition as "ödemezse": a statute
            # often names the duty instead of the verb "ödemek" (2026-10-30: the rule's lead sentence was dropped for this).
            if _UNPERFORMED_PAYMENT_DUTY_RE.search(value):
                known.add(True)
    return required == known


def _fact_kinds(question: str) -> set[str]:
    from api.ai.passages import is_duration_question
    q = normalize(question)
    kinds = set()
    if is_duration_question(q):
        kinds.add("duration")
    if any(term in q for term in ("tarih", "ne zaman", "hangi gün")):
        kinds.add("date")
    if re.search(r"tutar\w*|bedel\w*|miktar\w*|kaç (?:tl|lira)|ücret", q) or ("ne kadar" in q and not kinds):
        kinds.add("amount")
    if _PAYMENT_STATUS_RE.search(q) or re.search(r"ödeme\s+durum", q):
        kinds.add("payment_status")
    return kinds


def _fact_subjects(question: str) -> set[str]:
    """Small lexical subject guard, not a semantic/legal truth classifier.

    Generic relations (payment/date/amount) cannot stand in for the requested subject.
    Noun suffix normalization keeps e.g. 'depozitonun' and 'nafakanın' attached to their subjects.
    """
    words = re.findall(r"\w+", _PAYMENT_STATUS_RE.sub(" ", normalize(question)))
    subjects = set()
    for word in words:
        if (len(word) < 4 or word.isdigit() or word in GENERIC_QUESTION_WORDS
                or word in _QUANTITY_QUESTION_WORDS or word in _DOCUMENT_GENERIC_VERBS
                or word.startswith(_FACT_RELATION_PREFIXES) or word.startswith(_DOCUMENT_KINDS)):
            continue
        word = _SUBJECT_SUFFIX_RE.sub("", word)
        subjects.add(word[:max(4, len(word) - 2)])
    roles = {"davac", "daval", "kirac", "işçi", "borçl", "alaca"}
    return subjects - roles if subjects - roles else subjects


def _fact_relevance(question: str, text: str) -> bool | None:
    """Reject wrong subject/value types before permissive short-fact matching."""
    kinds = _fact_kinds(question)
    if not kinds:
        return None
    from api.ai.passages import contains_duration
    value = normalize(_CITATION_MARKER_RE.sub(" ", text))
    matches = {
        "amount": bool(_AMOUNT_VALUE_RE.search(value) or re.search(r"[₺€$]\s*\d[\d.,]*", value)),
        "date": bool(_DATE_VALUE_RE.search(value) or re.search(r"\bher ayın\s+\d+\.?\s*gün", value)),
        "duration": contains_duration(value),
        "payment_status": bool(_PAYMENT_STATUS_RE.search(value)) and not _CONDITIONAL_PAYMENT_RE.search(value),
    }
    if not any(matches[kind] for kind in kinds):
        return False
    subjects = _fact_subjects(question)
    if subjects:
        # Each evidence line can answer one conjunct (rent AND deposit); do not
        # require both subjects to occur in a single source sentence.
        multiple = bool(re.search(r"\b(?:ve|veya|ile)\b", normalize(question)))
        return sum(stem in value for stem in subjects) >= (1 if multiple else min(2, len(subjects)))
    return None


def analysis_scope_relevant(instruction: str, text: str) -> bool:
    """Code guard for explicit narrow scopes; arbitrary instructions still need the model checker.

    Only the first restricted clause is used; later exclusions are not promoted to desired subjects.
    This only filters output and never makes an instruction into evidence.
    """
    match = re.search(r"\b(?:yalnızca|yalnız|sadece)\s+(.+)", normalize(instruction))
    if not match:
        return True
    scope = re.split(r"[.!?](?:\s|$)", match.group(1), maxsplit=1)[0]
    subjects = _fact_subjects(scope)
    if subjects and not any(stem in normalize(text) for stem in subjects):
        return False
    # A single bullet can mix a relevant fact with an unrelated second fact.
    # Do not rescue that bullet just because its first clause names the topic.
    for clause in re.split(r";\s*|,(?!\d)\s*|\s+ve\s+", normalize(text)):
        if _fact_subjects(clause) and re.search(r"\d", clause) and _fact_relevance(scope, clause) is False:
            return False
    return _fact_relevance(scope, text) is not False


def document_passage_relevant(question: str, text: str, *, document_hint: str = '') -> bool:
    """Kullanıcı belgesi cümlesi için alaka: konu-niyeti (mevzuat) kapısı uygulanmaz.

    `passage_relevant` hukuki bir konu (ör. kıdem tazminatı) tanıdığında cümlenin o konunun tüm
    terim gruplarını (kanun/fesih sözcükleri...) içermesini ister; bu, mevzuat ve karar pasajları
    için ayarlıdır. Bilirkişi raporu gibi bir belgedeki somut olgu cümlesi ("Kıdem tazminatı 8 yıl
    için 340.000 TL hesaplanmıştır") bu terimleri taşımaz ve eleniyordu. Belgede aranan, sorunun
    sözcükleriyle örtüşmedir; cevap yine kaynak-destek denetiminden geçer.

    `document_hint` cümlenin geldiği belgenin adı ve başlığıdır (bkz. `document_hint`). Sorudaki belge adı
    ("ihtarnamede", "kira sözleşmesinde") cümlenin içinde değil belgenin adında geçer; o sözcük belgeyi seçer, cümlede
    aranmaz. Böylece "İhtarnamede ne kadar süre verilmiş?" sorusu ihtarnamenin "30 gün içinde ödenmesi" cümlesini bulur.
    """
    q = normalize(question)
    value = normalize(text)
    references = explicit_document_references(question)
    if references and document_hint and not any(reference in normalize(document_hint) for reference in references):
        return False
    fact = _fact_relevance(question, text)
    if fact is not None:
        return fact
    # Tutar sorusunda süre değil tutar içeren cümle aranır (passage_relevant ile aynı kural).
    if any(t in q for t in ('kaç lira', 'harcı ne kadar', 'harç tutarı')):
        return bool(re.search(r'\b(?:tl|lira|harç|harcı|ücret)', value))
    stems = document_question_stems(question)
    if not stems:
        return True
    # Atıf işareti ("[K1]") cümlenin sözcüğü değildir; sayılırsa kısa olgu cümlesi "uzun" görünür.
    value = _CITATION_MARKER_RE.sub(' ', value)
    # Kısa olgu cümlesi ("Depozito 37.000 TL'dir.") sorunun yalnız bir sözcüğünü taşır. İki parçalı soruda ("kira bedeli ne kadar
    # ve depozito nedir?") ikinci parçanın cevabı bu yüzden eleniyor, cevap yarım kalıyordu (ölçüldü: 2026-10-05).
    short_fact = len(re.findall(r'\w+', value)) <= 9 and (bool(re.search(r'\d', value)) or short_document_fact(value))
    hint = normalize(document_hint)
    named = named_stems(question, stems, hint)
    remaining = stems - named
    if short_fact:
        # Belgenin adında da geçen sözcük ("kira" ↔ "kira sözleşmesi") o belgenin her kısa satırında bulunabilir; kısa
        # olgu indirimi için ad dışındaki bir soru sözcüğü aranır. Yoksa "Kira borcu ne kadar?" sorusuna sözleşmedeki
        # "Kira başlangıç tarihi …" satırı da cevap adayı oluyordu (ölçüldü: 2026-10-06).
        if any(stem in value for stem in (remaining if named and remaining else stems)):
            return True
    elif sum(stem in value for stem in stems) >= min(2, len(stems)):
        return True
    # Cümle sorunun sözcüklerini tek başına taşımıyor; belge adıyla seçilmişse ad olan sözcük cümlede aranmaz.
    if not named:
        return False
    if not remaining:
        return True  # soru yalnız belgeyi adlandırıyor ("İhtarnamede ne yazıyor?"): o belgenin her cümlesi konu içidir
    matched = sum(stem in value for stem in remaining)
    if any(base in hint for base in document_reference_bases(question)) and answers_question_type(q, value):
        # Soru belgeyi açıkça gösteriyor ("ihtarnamede…") ve süre/tarih/tutar soruyor; cümle o türden bir değer taşıyor.
        # Yalnız açık göstermede uygulanır: ad benzerliği ("kira" ↔ "kira sözleşmesi") tek başına bu indirimi vermez.
        matched += 1
    return matched >= (1 if short_fact else min(2, len(remaining)))


_CITATION_MARKER_RE = re.compile(r'\[k\d+\]')
_DATE_VALUE_RE = re.compile(
    r'\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b'
    r'|\b\d{1,2}\s+(?:ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık)\b'
)
_AMOUNT_VALUE_RE = re.compile(r'\d[\d.,]*\s*(?:(?:tl|lira|usd|eur|euro|dolar)\b|[₺€$])')
# Belgede ne yazdığını soran, kendisi konu taşımayan fiiller: cümlede aranmaz.
_DOCUMENT_GENERIC_VERBS = frozenset((
    'yazıyor', 'yazmaktadır', 'yazılmış', 'yazılı', 'diyor', 'geçiyor', 'geçmektedir', 'belirtilmiş', 'belirtiliyor',
    'verilmiş', 'verilen', 'yazılıdır', 'gösterilmiş',
))


def answers_question_type(normalized_question: str, normalized_text: str) -> bool:
    """Soru bir süre, tarih ya da tutar soruyor ve metinde o türden bir değer var mı? (İkisi de `normalize` edilmiş olmalı.)"""
    from api.ai.passages import contains_duration, is_duration_question
    if is_duration_question(normalized_question):
        return contains_duration(normalized_text)
    if any(t in normalized_question for t in ('ne zaman', 'tarih', 'hangi gün')):
        return bool(_DATE_VALUE_RE.search(normalized_text))
    if any(t in normalized_question for t in ('ne kadar', 'tutar', 'bedel', 'miktar', 'ücret', 'kaç tl', 'kaç lira')):
        return bool(_AMOUNT_VALUE_RE.search(normalized_text))
    return False


def named_stems(question: str, stems: set[str], normalized_hint: str) -> set[str]:
    """Soru sözcüklerinden belgenin adında/başlığında geçenler (belgeyi seçen, cümlede aranmayan sözcükler).

    Gövde adın içinde geçiyorsa ya da ek almış sözcüğün kökü ("sözleşmesinde" → "sözleşme") adın içindeyse sayılır.
    """
    if not normalized_hint:
        return set()
    bases = [base for base in document_reference_bases(question) if base in normalized_hint]
    return {stem for stem in stems if stem in normalized_hint or any(stem.startswith(base) for base in bases)}


def document_hint(context) -> str:
    """Belgeyi adlandıran metin: dosya adı ve, başlık gibi duruyorsa, içeriğin ilk satırı.

    İlk satır yalnız kısa ve noktasızsa başlık sayılır ("İHTARNAME", "Kira Sözleşmesi"); bir cümleyse belgenin adı değil
    içeriğidir ve ada katılmaz (aksi halde o cümlenin her sözcüğü "belge adı" sayılırdı).
    """
    first_line = next((line.strip() for line in (context.content or '').splitlines() if line.strip()), '')
    heading = first_line if len(first_line.split()) <= 8 and not first_line.endswith(('.', '!', '?', ':', ';', ',')) else ''
    return f'{context.title or ""} {heading}'.strip()


def document_question_stems(question: str) -> set[str]:
    """Sorunun belgede aranacak konu sözcüklerinin gövdeleri (soru kalıbı ve miktar sözcükleri hariç)."""
    from api.ai.search_plan import plan_search
    words = [w for w in plan_search(question).text.split() if len(w) >= 4
             and not w.isdigit() and w not in GENERIC_QUESTION_WORDS and w not in _QUANTITY_QUESTION_WORDS
             and w not in _DOCUMENT_GENERIC_VERBS]
    return {w[:max(4, len(w) - 2)] for w in words}


# "ihtarnamede", "sözleşmesinde", "raporda": bulunma eki almış sözcük bir belgeye işaret edebilir. Ek ve iyelik atılır;
# kalan kök bir belgenin adında/başlığında geçiyorsa soru o belgeyi kastediyordur.
_LOCATIVE_RE = re.compile(r'^(\w{4,}?)(?:n?d[ae]|t[ae])(?:ki)?$')
_POSSESSIVE_RE = re.compile(r'(?:s[ıiuü]|[ıiuü])$')
# Bulunma eki alsa da belge adı olmayan, her dosyada geçebilen sözcükler.
_NOT_DOCUMENT_NAMES = frozenset((
    'dava', 'dosya', 'belge', 'evrak', 'hal', 'durum', 'süre', 'tarih', 'konu', 'taraf', 'yer', 'zaman', 'için', 'hakkın',
    'sonun', 'şekil', 'ara', 'nere', 'bura', 'ora', 'tür', 'kapsam', 'çerçeve', 'aşama', 'süreç',
))


def document_reference_bases(question: str) -> set[str]:
    """Soruda bir belgeye işaret eden sözcüklerin kökleri ("ihtarnamede" → "ihtarname", "sözleşmeye göre" → "sözleşme")."""
    words = re.findall(r'\w+', normalize(question))
    bases: set[str] = set()
    for index, word in enumerate(words):
        candidates = []
        match = _LOCATIVE_RE.match(word)
        if match:
            candidates.append(match.group(1))
        if index + 1 < len(words) and words[index + 1] == 'göre':
            candidates.append(re.sub(r'(?:y|n)?[ae]$', '', word))
        for base in candidates:
            for form in (base, _POSSESSIVE_RE.sub('', base)):
                if len(form) >= 4 and form not in _NOT_DOCUMENT_NAMES:
                    bases.add(form)
    return bases


def documents_named_in(question: str, contexts) -> list:
    """Sorunun adıyla işaret ettiği belgelerin parçaları (dosya adı ya da başlık eşleşmesi); işaret yoksa boş liste."""
    bases = document_reference_bases(question)
    if not bases:
        return []
    return [context for context in contexts if any(base in normalize(document_hint(context)) for base in bases)]


def explicit_document_references(question: str) -> set[str]:
    """Unambiguous document kinds, not every locative ('mahkemede', 'Türkiye'de')."""
    return {kind for kind in _DOCUMENT_KINDS
            if any(base.startswith(kind) or kind.startswith(base) for base in document_reference_bases(question))}


def missing_document_references(question: str, contexts) -> set[str]:
    hints = [normalize(document_hint(context)) for context in contexts if context.source_type == "document"]
    # Dosya adları sık sık aksansız yazılır ("kira_sozlesmesi.pdf"): tür de ipucu da aksansız karşılaştırılır.
    from api.ai.turkish_text import fold
    folded = [fold(hint) for hint in hints]
    return {kind for kind in explicit_document_references(question) if not any(fold(kind) in hint for hint in folded)}


def documents_answer(question: str, contexts) -> bool:
    """Belgelerde sorunun konusunu taşıyan en az bir cümle var mı?

    Dava sohbetinde "bu soru önce kullanıcının kendi belgelerinden cevaplanabilir mi" kararı için kullanılır. Sorunun konu
    sözcüğü yoksa (yalnız "nedir?") belge eşleşmiş sayılmaz: karar verilemez, karışık aramaya bırakılır.
    """
    from api.ai.source_support import source_sentences
    stems = document_question_stems(question)
    if not stems:
        return False
    for context in contexts:
        hint = normalize(document_hint(context))
        named = named_stems(question, stems, hint)
        remaining = stems - named
        if not remaining:
            return True  # soru bu belgeyi adıyla soruyor
        # Cümle süzgecinden (document_passage_relevant) daha sıkıdır: tek ortak sözcük ("süre") belgeyi cevabın kaynağı
        # yapmaz; yoksa "Arabuluculuk başvuru süresi kaç gün?" sorusu, içinde yalnız "süre 1 yıldır" geçen sözleşmeye
        # kilitlenir ve hukuk kaynaklarına hiç bakılmaz. Kısa olgu satırı indirimi yalnız belge adıyla anılmışsa uygulanır
        # ("İhtarname hangi tarihte çekilmiş?" → ihtarnamedeki "Tarih: 10.04.2025").
        for sentence in source_sentences(context):
            value = normalize(sentence)
            if sum(stem in value for stem in stems) >= min(2, len(stems)):
                return True
            if named:
                matched = sum(stem in value for stem in remaining)
                short_fact = len(re.findall(r'\w+', value)) <= 9 and bool(re.search(r'\d', value))
                if matched >= min(2, len(remaining)) or (short_fact and matched >= 1):
                    return True
    return False


# Miktar/tutar soran soru sözcükleri: belgedeki cümlede geçmeleri beklenmez.
_QUANTITY_QUESTION_WORDS = frozenset(('kadar', 'kadardır', 'tutar', 'tutarı', 'tutarıdır', 'miktar', 'miktarı', 'kaçtır', 'tarihi', 'tarihinde'))


def passage_relevant(question: str, text: str, *, source_type: str | None = None, document_hint: str = '') -> bool:
    """Reject known topic mismatches even when the source is genuine."""
    if source_type == 'document':
        return document_passage_relevant(question, text, document_hint=document_hint)
    intent = question_intent(question)
    value = normalize(expand_search_terms(text))
    if intent and not all(any(re.search(r'(?<!\w)' + re.escape(term), value) for term in group) for group in intent.groups):
        return False
    if intent and intent.name == 'joint_custody' and any(t in normalize(question) for t in ('şart', 'koşul')):
        if not any(t in value for t in ('yarar', 'rıza', 'rızası', 'görüş', 'idrak', 'menfaat', 'uzlaş', 'istek', 'uyum')):
            return False
    q = normalize(question)
    # A duration is not an answer to a fee question (observed DeepSeek regression).
    if any(t in q for t in ('kaç lira', 'harcı ne kadar', 'harç tutarı')):
        return bool(re.search(r'\b(?:tl|lira|harç|harcı|ücret)', value))
    if intent is None:
        from api.ai.search_plan import plan_search
        words = [w for w in plan_search(question).text.split() if len(w) >= 4
                 and not w.isdigit() and w not in GENERIC_QUESTION_WORDS]
        if words:
            stems = set(w[:max(4, len(w)-2)] for w in words)
            return sum(w in value for w in stems) >= min(2, len(stems))
    return True


def context_relevant(question, context):
    from api.ai.source_support import _sentences
    # Everyday concepts need not be literal strings in the governing statute
    # (e.g. a provision defining dismissal protection may not say "işe iade").
    # Reuse the existing topic -> article map AND its actual-text predicate;
    # metadata alone is not enough. This is candidate relevance, not support
    # for an answer or a substitute for the independent claim checker.
    if context.source_type == 'legislation' and context.verification == 'official':
        from api.statute_hints import suggest, text_matches
        if any((context.law_no, context.article_no) == (hint.law_no, hint.article_no)
               and text_matches(hint, context.content) for hint in suggest(question)):
            return True
    # Retrieval may return a fragment (including a historical version). Only
    # generation requires complete sentences; don't lose valid search records.
    return any(passage_relevant(question, s) for s in _sentences(context.content, include_tail=True))


def relevant_contexts(question, contexts):
    return [c for c in contexts if context_relevant(question, c)]


def intent_tsquery(intent: Intent) -> str:
    # Let PostgreSQL's Turkish dictionary stem the words. Prefix expansion on
    # common terms fans out over millions of rows and is deliberately avoided.
    # These are Python prefix matches, NOT Turkish dictionary headwords.
    # Feeding "artır" to PostgreSQL stems it again to "ar", losing actual
    # increase passages and adding unrelated matches. Use complete forms for
    # SQL only; keep passage/citation relevance checks unchanged.
    sql_forms = {'artır': ('artırım', 'artırılması', 'artırma')}
    return ' & '.join('(' + ' | '.join(
        ' <-> '.join(word for word in form.split())
        for term in group for form in sql_forms.get(term, (term,))
    ) + ')' for group in intent.groups)


def focused_intent_tsquery(question: str, intent: Intent) -> str | None:
    """A statute-linked first pass, never evidence or an exhaustive search.

    Narrow rent increases, deadlines and general severance entitlement questions using the
    already mapped statute/article. Explicit case-law and evidence questions
    retain broad retrieval. No expected duration or legal conclusion is added.
    This is candidate selection, never a claim to have found every related case.
    """
    from api.ai.passages import is_duration_question
    q = normalize(question)
    entitlement = intent.name == 'severance' and bool(re.search(
        r'\b(?:şart\w*|koşul\w*|hak kazan\w*)', q))
    evidence = bool(re.search(r'\b(?:delil\w*|ispat\w*|kanıt\w*)', q))
    rent_increase = intent.name == 'rent_increase'
    if (not intent.statute or case_law_requested(question) or evidence
            or not (is_duration_question(question) or entitlement or rent_increase)):
        return None
    law, article = intent.statute
    if not law.isdigit() or not article.isdigit():
        return None
    return f'({intent_tsquery(intent)}) & {law} & {article}'


def semantic_search_text(question: str) -> str:
    """Query-only vocabulary expansion; not an answer or a change to stored vectors."""
    intent = question_intent(question)
    hints = {
        'rent_increase': 'kira bedelinin artırılması tüketici fiyat endeksi kira artışı',
        'leave_proof': 'yıllık izin kullanıldığının ispatı izin defteri imzalı belge işveren',
        'joint_custody': 'ortak velayet çocuğun üstün yararı ebeveynlerin görüşleri ortak velayet koşulları',
        'administrative_deadline': 'idari yargıda iptal davası açma süresi idare mahkemesi',
        'constitutional_application': 'Anayasa Mahkemesi bireysel başvuru süresi başvuru yollarının tüketilmesi',
    }
    hint = hints.get(intent.name, '') if intent else ''
    q = normalize(question)
    everyday = [terms for pattern, terms in _EVERYDAY_LEGAL_TERMS if pattern.search(q)]
    hint = ' '.join(part for part in [hint, *everyday] if part)
    expanded = expand_search_terms(question)
    if expanded != normalize(question):
        hint = ' '.join(part for part in (expanded, hint) if part)
    return f'{question}\nArama kavramları: {hint}' if hint else question


# Gündelik anlatım → kanun dili (yalnız arama içindir; cevap yine yalnız kaynak metinden yazılır). "İşveren işçiyi haklı sebep
# olmadan işten çıkarırsa" sorusu İş K. m. 17-21'e ulaşmıyor, kaynak eksikliği bildiriyordu (ölçüldü: 2026-10-22).
_EVERYDAY_LEGAL_TERMS = tuple((re.compile(pattern), terms) for pattern, terms in (
    (r"(?:çalıştım|çalışıyordum|maaş\w*|ücretim).{0,100}(?:çıkarıldım|kovuldum)|"
     r"(?:çıkarıldım|kovuldum).{0,100}(?:çalıştım|maaş\w*|ücretim)",
     "iş sözleşmesinin feshi işçi işveren ücret kıdem tazminatı bildirim süresi"),
    (r"işten (?:çıkar|at|kov|uzaklaştır)\w*|\bkovul\w*|\bkovma\w*", "iş sözleşmesinin feshi işverenin feshi bildirim süresi"),
    (r"sebep(?:siz| olmadan| göstermeden)|nedensiz|haksız yere|gerekçesiz", "geçerli sebep olmaksızın fesih feshin geçersizliği işe iade kıdem tazminatı ihbar tazminatı bildirim süresi"),
    (r"\bistifa\w*", "işçinin feshi iş sözleşmesinin işçi tarafından feshi"),
    (r"\bev sahib\w*", "kiraya veren"),
    (r"evden çıkar\w*|\btahliye\w*", "kiralananın tahliyesi"),
    (r"\bmaaş\w*", "ücret"),
    (r"\bmesai\w*", "fazla çalışma ücreti"),
    (r"\bzam\b(?!an)|\bzammı\b", "artış"),
    (r"\bmiras\w*", "mirasçılık tereke"),
    (r"\bkaza\w*", "haksız fiil tazminat"),
))
