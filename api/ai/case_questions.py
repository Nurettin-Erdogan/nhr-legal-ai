"""Dava kapsamlı sohbette "bu dosyada ne yazıyor?" soruları yalnız dava belgelerinden cevaplanır.

Genel korpus başka davaların kararlarını içerir. "Davalının adresi nedir?" ya da "Bilirkişi ne kadar
hesaplamış?" gibi kullanıcının KENDİ dosyasına dair olgu soruları, başka bir davanın kararından
alıntıyla cevaplanırsa kullanıcı yanıltılır. Bu yüzden böyle sorularda yalnız dava belgeleri aranır;
belgelerde karşılığı yoksa uydurma yerine "yeterli bilgi yok" denir.

Sezgisel ve bilerek muhafazakârdır: hukuki değerlendirme/mevzuat belirtisi taşıyan soru karışık
(belge + hukuk kaynağı) aranır.
"""

from __future__ import annotations

import re

from api.ai.turkish_text import restore_turkish

# Kullanıcının dosyasındaki olguya işaret eden sözcükler.
_FILE_FACT_MARKERS = (
    "bilirkişi", "davacı", "davalı", "dilekçe", "tebligat", "vekil", "tanık", "müvekkil",
    "dosyada", "dosyadaki", "belgede", "belgelerde", "belgeye göre", "belgelere göre", "raporda",
    "kararda", "bu dava", "bu dosya", "hesaplamış", "karar vermiş", "karar vermiştir", "mahkeme ne karar",
    "esas no", "karar no", "mahkemesi", "dava konusu",
)
# Hukuki değerlendirme ya da mevzuat/içtihat isteyen sorular: belge + hukuk kaynağı birlikte aranır.
_LAW_MARKERS = (
    "madde", "kanun", "mevzuat", "yargıtay", "danıştay", "içtihat", "emsal", "tbk", "hmk", "tck", "cmk",
    "anayasa", "yönetmelik", "hak kazan", "hak doğ", "geçerli mi", "yasal mı", "mümkün mü", "şartları",
    "şartı", "koşul", "zamanaşımı", "hak düşürücü", "sorumlu mu", "hukuka", "hukuken", "yasaya",
    "kanuna", "uygulan", "ne olur", "ne yapmalı", "nasıl", "gerekir", "gerekli mi", "yükümlü",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("İ", "i").replace("I", "ı").lower()).strip()


def is_case_file_question(question: str) -> bool:
    """Soru yalnız dava belgelerinde cevaplanması gereken bir olgu sorusu mu?"""
    q = _normalize(restore_turkish(question))  # "bilirkisi raporunda" gibi ASCII yazılan sorular da
    if not any(marker in q for marker in _FILE_FACT_MARKERS):
        return False
    return not any(marker in q for marker in _LAW_MARKERS)
