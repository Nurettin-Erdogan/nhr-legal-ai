"""Fixed 20-question regression set for the grounded-answer pipeline."""

from __future__ import annotations

from typing import NotRequired, TypedDict


class EvalQuestion(TypedDict):
    id: str
    topic: str
    question: str
    expect_source_types: tuple[str, ...]
    must_terms: tuple[str, ...]
    expect_law_no: NotRequired[str]
    expect_article_no: NotRequired[str]


REGRESSION_QUESTIONS: tuple[EvalQuestion, ...] = (
    {
        "id": "kidem",
        "topic": "kıdem tazminatı",
        "question": "Kıdem tazminatına hak kazanma şartları nelerdir?",
        "expect_source_types": ("legislation", "court_decision"),
        "must_terms": ("kıdem", "tazminat"),
        "expect_law_no": "4857",
    },
    {
        "id": "haksiz-fesih",
        "topic": "haksız fesih",
        "question": "İş sözleşmesinin haksız feshinde işçi hangi tazminatları talep edebilir?",
        "expect_source_types": ("legislation", "court_decision"),
        "must_terms": ("fesih", "tazminat"),
        "expect_law_no": "4857",
    },
    {
        "id": "yillik-izin",
        "topic": "yıllık izin",
        "question": "Yıllık ücretli izin hakkı nasıl hesaplanır ve ispat yükü kimdedir?",
        "expect_source_types": ("legislation", "court_decision"),
        "must_terms": ("yıllık", "izin"),
        "expect_law_no": "4857",
        "expect_article_no": "53",
    },
    {
        "id": "zamanasimi",
        "topic": "zamanaşımı",
        "question": "İşçilik alacaklarında zamanaşımı süresi nedir?",
        "expect_source_types": ("legislation", "court_decision"),
        "must_terms": ("zamanaşımı",),
    },
    {
        "id": "idari-islem",
        "topic": "idari işlem",
        "question": "İdari işlemin iptali davasında dava açma süresi ne kadardır?",
        "expect_source_types": ("legislation", "court_decision"),
        "must_terms": ("iptal", "dava"),
        "expect_law_no": "2577",
        "expect_article_no": "7",
    },
    {
        "id": "aym-basvuru",
        "topic": "Anayasa Mahkemesi kararı",
        "question": "Anayasa Mahkemesine bireysel başvuru süresi ve şartları nelerdir?",
        "expect_source_types": ("court_decision", "legislation"),
        "must_terms": ("bireysel", "başvuru"),
        "expect_law_no": "6216",
    },
    {
        "id": "is-kanunu-18",
        "topic": "mevzuat maddesi",
        "question": "4857 sayılı İş Kanunu madde 18 neyi düzenler?",
        "expect_source_types": ("legislation",),
        "must_terms": ("geçerli sebep", "fesih"),
        "expect_law_no": "4857",
        "expect_article_no": "18",
    },
    {
        "id": "hakli-fesih",
        "topic": "haklı fesih",
        "question": "İşverenin haklı nedenle derhal fesih hâlleri nelerdir?",
        "expect_source_types": ("legislation", "court_decision"),
        "must_terms": ("haklı", "fesih"),
        "expect_law_no": "4857",
        "expect_article_no": "25",
    },
    {
        "id": "ihbar",
        "topic": "ihbar tazminatı",
        "question": "İhbar tazminatı hangi durumlarda doğar?",
        "expect_source_types": ("legislation", "court_decision"),
        "must_terms": ("ihbar", "tazminat"),
        "expect_law_no": "4857",
        "expect_article_no": "17",
    },
    {
        "id": "fazla-mesai",
        "topic": "fazla mesai",
        "question": "Fazla çalışma ücreti nasıl hesaplanır?",
        "expect_source_types": ("legislation", "court_decision"),
        "must_terms": ("fazla", "çalışma"),
        "expect_law_no": "4857",
        "expect_article_no": "41",
    },
    {
        "id": "ise-iade",
        "topic": "işe iade",
        "question": "İşe iade davasının koşulları nelerdir?",
        "expect_source_types": ("legislation", "court_decision"),
        "must_terms": ("işe iade",),
        "expect_law_no": "4857",
    },
    {
        "id": "mobbing",
        "topic": "mobbing",
        "question": "İşyerinde psikolojik taciz iddiasında ispat yükü kime aittir?",
        "expect_source_types": ("court_decision", "legislation"),
        "must_terms": ("psikolojik taciz", "ispat"),
    },
    {
        "id": "kdk",
        "topic": "idari işlem",
        "question": "Kamu Denetçiliği Kurumuna başvuru şartları nelerdir?",
        "expect_source_types": ("other", "legislation"),
        "must_terms": ("kamu denetçi", "başvuru"),
        "expect_law_no": "6328",
    },
    {
        "id": "danistay",
        "topic": "idari işlem",
        "question": "İdari yargıda istinaf ve temyiz yolları nasıl işler?",
        "expect_source_types": ("legislation", "court_decision"),
        "must_terms": ("istinaf", "temyiz"),
        "expect_law_no": "2577",
    },
    {
        "id": "iyuk-7",
        "topic": "mevzuat maddesi",
        "question": "2577 sayılı İdari Yargılama Usulü Kanunu madde 7 dava açma süresini nasıl düzenler?",
        "expect_source_types": ("legislation",),
        "must_terms": ("dava açma", "süre"),
        "expect_law_no": "2577",
        "expect_article_no": "7",
    },
    {
        "id": "esit-davranma",
        "topic": "eşit davranma",
        "question": "İş Kanununda eşit davranma ilkesi nasıl korunur?",
        "expect_source_types": ("legislation", "court_decision"),
        "must_terms": ("eşit davranma",),
        "expect_law_no": "4857",
        "expect_article_no": "5",
    },
    {
        "id": "ucret-faizi",
        "topic": "ücret",
        "question": "Ücret alacağında faiz hangi tarihten itibaren işlemeye başlar?",
        "expect_source_types": ("court_decision", "legislation"),
        "must_terms": ("ücret", "faiz"),
    },
    {
        "id": "gecersiz-fesih",
        "topic": "haksız fesih",
        "question": "Geçersiz feshin işçi açısından sonuçları nelerdir?",
        "expect_source_types": ("legislation", "court_decision"),
        "must_terms": ("geçersiz", "fesih"),
        "expect_law_no": "4857",
    },
    {
        "id": "anayasa-36",
        "topic": "Anayasa Mahkemesi kararı",
        "question": "Anayasanın 36. maddesi adil yargılanma hakkını nasıl düzenler?",
        "expect_source_types": ("legislation", "court_decision"),
        "must_terms": ("adil yargılanma",),
        "expect_article_no": "36",
    },
    {
        "id": "idari-para",
        "topic": "idari işlem",
        "question": "İdari para cezasına karşı başvuru ve itiraz yolu nedir?",
        "expect_source_types": ("legislation", "court_decision", "other"),
        "must_terms": ("idari para",),
    },
)
