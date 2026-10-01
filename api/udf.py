"""UYAP UDF dosyalarından metin çıkarma.

UDF, içinde `content.xml` bulunan bir zip arşividir. Belge metni kök `<content>` öğesinin CDATA
bölümündedir; paragraf öğelerindeki `<content startOffset=".." length=".."/>` etiketleri yalnız
biçim aralığıdır ve metin taşımaz. Etiketleri silen bir düzenli ifade CDATA'nın içindeki metni de
sildiği için gerçek bir UDF'den boş sonuç döner; bu yüzden XML gerçekten ayrıştırılır.

Dosya kullanıcıdan gelen güvenilmeyen girdidir: açılmış boyut sınırlanır, DOCTYPE/ENTITY
içeren XML (varlık genişletme saldırısı) reddedilir.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile

MAX_CONTENT_XML_BYTES = 20 * 1024 * 1024
_FORBIDDEN_XML = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)


class UdfError(ValueError):
    """UDF okunamadı; mesaj kullanıcıya gösterilebilir."""


def _content_xml(data: bytes) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            name = next(
                (item.filename for item in archive.infolist() if item.filename.lower().endswith("content.xml")),
                None,
            )
            if name is None:
                raise UdfError("UDF dosyasında content.xml bulunamadı.")
            if archive.getinfo(name).file_size > MAX_CONTENT_XML_BYTES:
                raise UdfError("UDF içeriği izin verilen boyutu aşıyor.")
            with archive.open(name) as stream:
                raw = stream.read(MAX_CONTENT_XML_BYTES + 1)
    except zipfile.BadZipFile as exc:
        raise UdfError("UDF dosyası geçerli bir arşiv değil.") from exc
    if len(raw) > MAX_CONTENT_XML_BYTES:
        raise UdfError("UDF içeriği izin verilen boyutu aşıyor.")
    return raw


def extract_udf_text(data: bytes, limit: int | None = None) -> str:
    """UDF belge metnini döndürür; boş olabilir. Okunamayan dosyada `UdfError` fırlatır."""
    raw = _content_xml(data)
    if _FORBIDDEN_XML.search(raw):
        raise UdfError("UDF içeriği güvenli olmayan XML bildirimi içeriyor.")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise UdfError("UDF içeriği ayrıştırılamadı.") from exc

    # Metin kökün doğrudan `content` çocuğundadır. Bulunmazsa (farklı sürüm) tüm metin düğümleri.
    node = root.find("content")
    text = node.text if node is not None and node.text else ""
    if not text.strip():
        text = " ".join(part.strip() for part in root.itertext() if part and part.strip())
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    return text[:limit] if limit is not None else text
