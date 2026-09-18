"""Fixed 20-question regression set for the grounded-answer pipeline."""

from __future__ import annotations

from typing import TypedDict


class EvalQuestion(TypedDict):
    id: str
    topic: str
    question: str
    expect_source_types: tuple[str, ...]


REGRESSION_QUESTIONS: tuple[EvalQuestion, ...] = (
    {
        "id": "kidem",
        "topic": "kıdem tazminatı",
        "question": "Kıdem tazminatına hak kazanma şartları nelerdir?",
        "expect_source_types": ("legislation", "court_decision"),
    },
    {
        "id": "haksiz-fesih",
        "topic": "haksız fesih",
        "question": "İş sözleşmesinin haksız feshinde işçi hangi tazminatları talep edebilir?",
        "expect_source_types": ("legislation", "court_decision"),
    },
    {
        "id": "yillik-izin",
        "topic": "yıllık izin",
        "question": "Yıllık ücretli izin hakkı nasıl hesaplanır ve ispat yükü kimdedir?",
        "expect_source_types": ("legislation", "court_decision"),
    },
    {
        "id": "zamanasimi",
        "topic": "zamanaşımı",
        "question": "İşçilik alacaklarında zamanaşımı süresi nedir?",
        "expect_source_types": ("legislation", "court_decision"),
    },
    {
        "id": "idari-islem",
        "topic": "idari işlem",
        "question": "İdari işlemin iptali davasında dava açma süresi ne kadardır?",
        "expect_source_types": ("legislation", "court_decision"),
    },
    {
        "id": "aym-basvuru",
        "topic": "Anayasa Mahkemesi kararı",
        "question": "Anayasa Mahkemesine bireysel başvuru süresi ve şartları nelerdir?",
        "expect_source_types": ("court_decision", "legislation"),
    },
    {
        "id": "is-kanunu-18",
        "topic": "mevzuat maddesi",
        "question": "4857 sayılı İş Kanunu madde 18 neyi düzenler?",
        "expect_source_types": ("legislation",),
    },
    {
        "id": "hakli-fesih",
        "topic": "haklı fesih",
        "question": "İşverenin haklı nedenle derhal fesih hâlleri nelerdir?",
        "expect_source_types": ("legislation", "court_decision"),
    },
    {
        "id": "ihbar",
        "topic": "ihbar tazminatı",
        "question": "İhbar tazminatı hangi durumlarda doğar?",
        "expect_source_types": ("legislation", "court_decision"),
    },
    {
        "id": "fazla-mesai",
        "topic": "fazla mesai",
        "question": "Fazla çalışma ücreti nasıl hesaplanır?",
        "expect_source_types": ("legislation", "court_decision"),
    },
    {
        "id": "ise-iade",
        "topic": "işe iade",
        "question": "İşe iade davasının koşulları nelerdir?",
        "expect_source_types": ("legislation", "court_decision"),
    },
    {
        "id": "mobbing",
        "topic": "mobbing",
        "question": "İşyerinde psikolojik taciz iddiasında ispat yükü kime aittir?",
        "expect_source_types": ("court_decision", "legislation"),
    },
    {
        "id": "kdk",
        "topic": "idari işlem",
        "question": "Kamu Denetçiliği Kurumuna başvuru şartları nelerdir?",
        "expect_source_types": ("other", "legislation"),
    },
    {
        "id": "danistay",
        "topic": "idari işlem",
        "question": "İdari yargıda istinaf ve temyiz yolları nasıl işler?",
        "expect_source_types": ("legislation", "court_decision"),
    },
    {
        "id": "iyuk-7",
        "topic": "mevzuat maddesi",
        "question": "2577 sayılı İdari Yargılama Usulü Kanunu madde 7 dava açma süresini nasıl düzenler?",
        "expect_source_types": ("legislation",),
    },
    {
        "id": "esit-davranma",
        "topic": "eşit davranma",
        "question": "İş Kanununda eşit davranma ilkesi nasıl korunur?",
        "expect_source_types": ("legislation", "court_decision"),
    },
    {
        "id": "ucret-faizi",
        "topic": "ücret",
        "question": "Ücret alacağında faiz hangi tarihten itibaren işlemeye başlar?",
        "expect_source_types": ("court_decision", "legislation"),
    },
    {
        "id": "gecersiz-fesih",
        "topic": "haksız fesih",
        "question": "Geçersiz feshin işçi açısından sonuçları nelerdir?",
        "expect_source_types": ("legislation", "court_decision"),
    },
    {
        "id": "anayasa-36",
        "topic": "Anayasa Mahkemesi kararı",
        "question": "Anayasanın 36. maddesi adil yargılanma hakkını nasıl düzenler?",
        "expect_source_types": ("legislation", "court_decision"),
    },
    {
        "id": "idari-para",
        "topic": "idari işlem",
        "question": "İdari para cezasına karşı başvuru ve itiraz yolu nedir?",
        "expect_source_types": ("legislation", "court_decision", "other"),
    },
)
