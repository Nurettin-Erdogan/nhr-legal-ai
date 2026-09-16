"""Resmî portallarda 2026-09-16 tarihinde doğrulanmış coverage tabanları.

Tarih tahmin edilmez. Hit görülmeyen ama SUCCESS dönen yıllar boştur; hata
dönen aralık complete yazılmaz. Ayrıntı: docs/ingestion-worker.md.
"""

from __future__ import annotations

from datetime import date

# karararama.yargitay.gov.tr: boş arananKelime + yıl penceresi.
# 1995 SUCCESS filtered=0; 2000 SUCCESS filtered=103 (en eski hit).
# Tarihsiz boş kelime AdaletRuntimeException (ERROR) — kullanılmaz.
YARGITAY_CORPUS_START = date(2000, 1, 1)

# karararama.danistay.gov.tr: 1981 SUCCESS 0; 1982 SUCCESS 9.
DANISTAY_CORPUS_START = date(1982, 1, 1)

# kararlar.ombudsman.gov.tr IndexPaging karbas/karbit %d/%m/%Y:
# 2013–2016 filtered=0; 2017 filtered=459.
KDK_CORPUS_START = date(2017, 1, 1)

# api/core/public/search 422 literals; en eski kararTarihi (ASC):
# BireyselBasvuru 2012-12-25, NormDenetimi 1962-09-05, SiyasiParti 1963-08-04,
# YasamaDokunulmazligi 1967-08-02. YuceDivan ASC kararTarihi bu oturumda boş.
AYM_DECISION_TYPES = (
    "BireyselBasvuru",
    "NormDenetimi",
    "SiyasiParti",
    "YuceDivan",
    "YasamaDokunulmazligi",
)
