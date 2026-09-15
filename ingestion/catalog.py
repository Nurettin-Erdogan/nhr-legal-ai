"""Çekilecek ilk hukuk korpusunun sabit kataloğu.

Bu liste ürünün 'başlangıç kütüphanesi'dir; tek tek CLI bayrağı ezberlemeye
gerek kalmadan `collect` komutu buradaki işleri sırayla çalıştırır.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LawJob:
    law_no: str
    name: str
    types: tuple[str, ...] = ("KANUN",)


@dataclass(frozen=True, slots=True)
class YargitayJob:
    keyword: str
    chamber: str = ""
    max_decisions: int = 25


@dataclass(frozen=True, slots=True)
class CollectProfile:
    name: str
    laws: tuple[LawJob, ...]
    yargitay: tuple[YargitayJob, ...]
    max_articles_per_law: int
    mevzuat_delay_seconds: float
    yargitay_delay_seconds: float


STARTER_LAWS = (
    LawJob("2709", "Türkiye Cumhuriyeti Anayasası"),
    LawJob("4721", "Türk Medeni Kanunu"),
    LawJob("6098", "Türk Borçlar Kanunu"),
    LawJob("6100", "Hukuk Muhakemeleri Kanunu"),
    LawJob("5237", "Türk Ceza Kanunu"),
    LawJob("5271", "Ceza Muhakemesi Kanunu"),
    LawJob("4857", "İş Kanunu"),
    LawJob("2004", "İcra ve İflas Kanunu"),
)

STARTER_YARGITAY = (
    YargitayJob("kıdem tazminatı", "9. Hukuk Dairesi", 25),
    YargitayJob("haksız fiil", "4. Hukuk Dairesi", 20),
    YargitayJob("tapu iptali", "1. Hukuk Dairesi", 20),
)

PROFILES = {
    "smoke": CollectProfile(
        name="smoke",
        laws=(LawJob("4857", "İş Kanunu"),),
        yargitay=(YargitayJob("kıdem tazminatı", "9. Hukuk Dairesi", 3),),
        max_articles_per_law=5,
        mevzuat_delay_seconds=0.4,
        yargitay_delay_seconds=1.5,
    ),
    "starter": CollectProfile(
        name="starter",
        laws=STARTER_LAWS,
        yargitay=STARTER_YARGITAY,
        max_articles_per_law=2000,
        mevzuat_delay_seconds=1.0,
        yargitay_delay_seconds=1.5,
    ),
}
