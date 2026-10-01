"""OCR (Tesseract): taranmış PDF, görüntü ve metin katmanı çözülemeyen PDF sayfaları için.

Hukuk belgelerinde yanlış okunan tek bir harf (tutar, tarih, esas no) sonucu değiştirebilir. Bu yüzden:
- Türkçe dil paketi (`tur`) zorunludur; yalnız `eng` ile ç/ş/ğ/ı yanlış okunur, bu "çalışıyor" görünüp
  sessizce hatalı metin üretmekten kötüdür. `tur` yoksa OCR **kullanılamaz** sayılır.
- OCR ile okunan belge çağıranın tarafında işaretlenir (`ProcessedDocument.ocr`) ve arayüzde
  "OCR ile okundu; hata olabilir" diye gösterilir.
- Sayfa sayısı sınırlıdır; sınırı aşan belge kırpılıp "okundu" sayılmaz, nedeniyle reddedilir.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_OCR_PAGES = int(os.getenv("OCR_MAX_PAGES", "40"))
# ~216 dpi: A4 sayfada okuma kalitesi ile hız/bellek arasında denge.
RENDER_SCALE = float(os.getenv("OCR_RENDER_SCALE", "3.0"))
PAGE_TIMEOUT_SECONDS = int(os.getenv("OCR_PAGE_TIMEOUT", "120"))
_WINDOWS_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


class OcrUnavailable(RuntimeError):
    """OCR çalıştırılamıyor; mesaj kullanıcıya gösterilebilir."""


class OcrTooLarge(RuntimeError):
    """Belge OCR sayfa sınırını aşıyor; mesaj kullanıcıya gösterilebilir."""


_LOCAL_TESSDATA = Path(__file__).resolve().parents[1] / "data" / "tessdata"


def _configure_tessdata() -> None:
    """Dil verisi klasörü: `TESSDATA_PREFIX` verilmişse ona, yoksa projedeki `data/tessdata`'ya bakılır.

    Program Files altına yazmak yönetici izni ister; Türkçe model (`tur.traineddata`, tessdata_best)
    bu yüzden proje dizinindeki `data/tessdata` içinde tutulur (git'e girmez, bkz. docs/ocr.md).
    """
    if os.environ.get("TESSDATA_PREFIX"):
        return
    if (_LOCAL_TESSDATA / "tur.traineddata").is_file():
        os.environ["TESSDATA_PREFIX"] = str(_LOCAL_TESSDATA)


def find_tesseract() -> str | None:
    configured = os.getenv("TESSERACT_CMD", "").strip()
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("tesseract")
    if found:
        return found
    return next((path for path in _WINDOWS_CANDIDATES if Path(path).is_file()), None)


def ocr_status() -> tuple[bool, str]:
    """(kullanılabilir mi, değilse kullanıcıya gösterilebilir neden)."""
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return False, "OCR için `pytesseract` ve `Pillow` kurulu değil (pip install pytesseract pillow pypdfium2)."
    command = find_tesseract()
    if command is None:
        return False, "Tesseract OCR kurulu değil."
    _configure_tessdata()
    try:
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = command
        languages = set(pytesseract.get_languages(config=""))
    except Exception:  # noqa: BLE001 - tesseract çalıştırılamadı
        logger.warning("Tesseract dil listesi alınamadı", exc_info=True)
        return False, "Tesseract OCR çalıştırılamadı."
    if "tur" not in languages:
        return False, "Tesseract'ın Türkçe dil paketi (tur.traineddata) kurulu değil; yalnız İngilizce OCR hatalı okur."
    return True, ""


def _engine():
    import pytesseract

    ok, reason = ocr_status()
    if not ok:
        raise OcrUnavailable(reason)
    pytesseract.pytesseract.tesseract_cmd = find_tesseract()
    return pytesseract


def _prepare(picture):
    from PIL import ImageOps

    picture = ImageOps.exif_transpose(picture)
    picture = picture.convert("L")  # gri tonlama
    return ImageOps.autocontrast(picture)


def _read(engine, picture) -> str:
    text = engine.image_to_string(
        _prepare(picture), lang="tur+eng" if _has_eng(engine) else "tur", timeout=PAGE_TIMEOUT_SECONDS
    )
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def _has_eng(engine) -> bool:
    try:
        return "eng" in set(engine.get_languages(config=""))
    except Exception:  # noqa: BLE001
        return False


def ocr_image_pages(data: bytes) -> list[tuple[int, str]]:
    """Görüntü baytlarını (çok sayfalı TIFF dahil) okur; (sayfa no, metin) döndürür."""
    from PIL import Image, ImageSequence

    engine = _engine()
    try:
        with Image.open(io.BytesIO(data)) as picture:
            frames = getattr(picture, "n_frames", 1)
            if frames > MAX_OCR_PAGES:
                raise OcrTooLarge(f"Görüntü {frames} sayfa; OCR en çok {MAX_OCR_PAGES} sayfa okur.")
            pages = []
            for number, frame in enumerate(ImageSequence.Iterator(picture), start=1):
                pages.append((number, _read(engine, frame.copy())))
            return pages
    except (OcrTooLarge, OcrUnavailable):
        raise
    except Exception as exc:  # noqa: BLE001 - bozuk görüntü
        raise OcrUnavailable("OCR için görüntü okunamadı veya bozuk.") from exc


def pdf_page_count(data: bytes) -> int:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(data)
    try:
        return len(document)
    finally:
        document.close()


def ocr_pdf_pages(data: bytes, pages: list[int]) -> dict[int, str]:
    """PDF'in verilen sayfalarını (1 tabanlı) görüntüye çevirip okur."""
    import pypdfium2 as pdfium

    if len(pages) > MAX_OCR_PAGES:
        raise OcrTooLarge(f"PDF'de OCR gereken {len(pages)} sayfa var; OCR en çok {MAX_OCR_PAGES} sayfa okur.")
    engine = _engine()
    try:
        document = pdfium.PdfDocument(data)
    except Exception as exc:  # noqa: BLE001 - parolalı/bozuk PDF
        raise OcrUnavailable("PDF OCR için açılamadı.") from exc
    results: dict[int, str] = {}
    try:
        for number in pages:
            page = document[number - 1]
            try:
                picture = page.render(scale=RENDER_SCALE).to_pil()
                results[number] = _read(engine, picture)
            finally:
                page.close()
    finally:
        document.close()
    return results
