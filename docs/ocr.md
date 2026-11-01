# OCR: taranmış belgeler

Taranmış PDF'ler, görüntü dosyaları (TIF/JPG/PNG) ve metin katmanı çözülemeyen PDF'ler (özel yazı tipi
kodlaması; gerçek bir UYAP PDF'inde okuyucu her harf yerine `/gid00001` döndürdü) **Tesseract OCR** ile
okunur. Yalnız **dava belgelerinde** (büro çalışma alanı) çalışır; senkron yüklemeler (`/api/documents`)
OCR çalıştırmaz.

## Kurulum (Windows)

```powershell
pip install pytesseract pillow pypdfium2          # requirements.txt'te
winget install --id UB-Mannheim.TesseractOCR -e   # Tesseract motoru (yönetici izni isteyebilir)
```

Türkçe dil paketi **zorunludur**. Yalnız İngilizce OCR ç/ş/ğ/ı'yı yanlış okur; bu, "çalışıyor" görünüp
sessizce hatalı metin üretmekten kötüdür. `tur` yoksa OCR **kullanılamaz** sayılır ve belge nedeniyle
"okunamadı" olur. Resmî `tessdata_best` Türkçe modeli proje dizinine konur (Program Files yazma izni ister;
`data/` git'e girmez):

```powershell
New-Item -ItemType Directory -Force data\tessdata
Invoke-WebRequest https://github.com/tesseract-ocr/tessdata_best/raw/main/tur.traineddata -OutFile data\tessdata\tur.traineddata
Copy-Item "C:\Program Files\Tesseract-OCR\tessdata\eng.traineddata" data\tessdata\
Copy-Item "C:\Program Files\Tesseract-OCR\tessdata\osd.traineddata" data\tessdata\
```

`api/ocr.py` Tesseract'ı `TESSERACT_CMD`, `PATH` ya da bilinen Windows yollarından bulur; dil verisi için
`TESSDATA_PREFIX`, yoksa `data/tessdata` kullanılır. Durum: `GET /api/office-ai/status` (`ocr`, `ocr_detail`).

## Davranış

- **Hangi sayfalar OCR'a gider:** metni olmayan ama görüntü içeren (taranmış) sayfalar ve çöp metin
  üreten sayfalar. Normal metinli sayfalar ve gerçekten boş sayfalar OCR'a gitmez.
- **Arka plan:** OCR dakikalar sürebilir, bu yüzden indeksleme işinde (arka plan iş parçacığı) yapılır.
  Soru anındaki hızlı yol (en çok 20 sn) OCR çalıştırmaz: OCR gereken belgeyi "bekliyor" bırakıp arka
  plana alır. Süren iş tekrar planlanmaz. Bu sırada sorulan soru "N belge henüz işleniyor" açıklamasını alır.
- **Sınırlar:** en çok 40 sayfa (`OCR_MAX_PAGES`); aşan belge kırpılıp "okundu" sayılmaz, nedeniyle
  reddedilir. Sayfa başına 120 sn zaman aşımı. Sayfalar ~216 dpi (`OCR_RENDER_SCALE=3.0`) işlenir.
- **Kalite kapısı:** OCR çıktısı da okunabilirlik denetiminden geçer; çöp çıktı indekslenmez.

## Dürüstlük: OCR hata yapar

Hukuk belgesinde yanlış okunan tek bir rakam (tutar, tarih, esas no) sonucu değiştirebilir. Bu yüzden:

- OCR ile okunan belge `documents.metadata.ocr = true` ile işaretlenir.
- Durum listesinde belgenin yanında **"OCR ile okundu"** rozeti vardır.
- Cevabın altındaki belge kapsamı "N belge OCR ile okundu; okuma hataları olabilir. Tutar, tarih ve
  numaraları belgenin aslından doğrulayın." uyarısını taşır ve OCR'lı belge varken uyarı rengindedir.
- OCR gürültüsü cevaba aynen yansıyabilir (örn. imza kutusundan "YEN BETER", onay kutusundan "HO").

## Testler

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ocr.py tests/test_document_ocr_index.py `
    tests/test_pdf_readability.py tests/test_case_pending_documents.py -q
```

`tests/test_ocr.py` içindeki gerçek Tesseract testleri Tesseract (`tur`) veya Arial yoksa atlanır;
diğerleri OCR motorunu taklit eder, motor gerektirmez.
