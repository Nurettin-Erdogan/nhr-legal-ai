r"""UYAP'a girmeden denemek için kurgusal dava belgeleri üretir (UDF, DOCX, taranmış PDF/PNG).

    .\.venv\Scripts\python.exe scripts\make_uyap_test_files.py [hedef_klasör]

Belgelerdeki kişi, firma ve tutarlar tamamen uydurmadır; hiçbiri gerçek bir dosyaya ait değildir.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

ESAS = "2025/412"
MAHKEME = "İstanbul 5. İş Mahkemesi"

DILEKCE = f"""T.C. {MAHKEME.upper()}
DOSYA NO: {ESAS} Esas

DAVACI: Ahmet Örnek (kurgusal)
DAVALI: Deneme Tekstil Sanayi A.Ş. (kurgusal)
KONU: Kıdem tazminatı ve ihbar tazminatı alacağının tahsili talebidir.

AÇIKLAMALAR:
1. Davacı, davalı işyerinde 01.03.2015 - 15.04.2023 tarihleri arasında 8 yıl 1 ay süreyle çalışmıştır.
2. İş sözleşmesi davalı işveren tarafından haklı bir neden olmaksızın feshedilmiştir.
3. Davacıya kıdem tazminatı ve ihbar tazminatı ödenmemiştir.
SONUÇ VE İSTEM: Fazlaya ilişkin haklar saklı kalmak kaydıyla kıdem tazminatı ve ihbar tazminatının davalıdan tahsiline karar verilmesini talep ederiz.
"""

BILIRKISI = f"""BİLİRKİŞİ RAPORU
Mahkeme: {MAHKEME}    Esas No: {ESAS}

Davacının 8 yıl 1 ay çalıştığı, son brüt ücretinin 42.000 TL olduğu anlaşılmıştır.
Kıdem tazminatı 340.000 TL olarak hesaplanmıştır. İhbar tazminatı 8 hafta üzerinden 77.000 TL'dir.
Davalının, fesih tarihinden önce yazılı bildirim yaptığına dair belge sunmadığı görülmüştür.
Fazla çalışma ücreti talebi bulunmamaktadır.
"""

KARAR = f"""{MAHKEME.upper()}
GEREKÇELİ KARAR   Esas No: {ESAS}   Karar No: 2026/118

Davanın KABULÜNE, 340.000 TL kıdem tazminatı ve 77.000 TL ihbar tazminatının
fesih tarihinden itibaren yasal faiziyle birlikte davalıdan tahsiline karar verilmiştir.
Karar tebliğinden itibaren iki hafta içinde istinaf yoluna başvurulabilir.
"""


def _udf(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "content.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<template format_id="1.8"><content><![CDATA[{text}]]></content></template>',
        )
    return buffer.getvalue()


def _scan(text: str):
    """Yazıyı bir sayfa görüntüsüne çevirir (taranmış belge gibi: seçilebilir metni yoktur)."""
    from PIL import Image, ImageDraw, ImageFont

    candidates = [r"C:\Windows\Fonts\arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    font = next((ImageFont.truetype(path, 30) for path in candidates if Path(path).is_file()), None)
    if font is None:
        raise SystemExit("Taranmış örnek için bir TrueType yazı tipi (Arial/DejaVu) gerekir.")
    image = Image.new("L", (1240, 1754), 255)
    draw = ImageDraw.Draw(image)
    y = 120
    for line in text.splitlines():
        draw.text((100, y), line, fill=0, font=font)
        y += 46
    return image


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("uyap-test-dosyalari")
    target.mkdir(parents=True, exist_ok=True)

    (target / "01_Dava_Dilekcesi.udf").write_bytes(_udf(DILEKCE))
    (target / "02_Bilirkisi_Raporu.udf").write_bytes(_udf(BILIRKISI))

    from docx import Document

    document = Document()
    for paragraph in KARAR.strip().splitlines():
        document.add_paragraph(paragraph)
    document.save(target / "03_Gerekceli_Karar.docx")

    scan = _scan(BILIRKISI)
    scan.save(target / "04_Taranmis_Rapor.pdf", "PDF", resolution=150)  # metinsiz PDF → OCR gerekir
    _scan(DILEKCE).save(target / "05_Taranmis_Dilekce.png")

    (target / "OKU.txt").write_text(
        "Bu belgeler kurgusaldir; gercek bir dosyaya ait degildir.\n"
        f"Dava: {MAHKEME}, {ESAS} Esas. UYAP aktarim denemesi icindir.\n",
        encoding="utf-8",
    )
    print(f"{len(list(target.iterdir()))} dosya yazıldı: {target.resolve()}")


if __name__ == "__main__":
    main()
