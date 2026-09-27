# Büro çalışma alanı

Web arayüzündeki büro ekranları (müvekkil, dava, görev, takvim, hatırlatma, arama kaydı, belge/UYAP,
AI çıktıları, başvurular) verilerini artık **kendi PostgreSQL'imizde** tutar; Supabase ve Lovable AI
Gateway kullanılmaz. Üretim yerel modelle (DeepSeek/Ollama) yapılır.

## Şema ve erişim
- Migration: `database/migrations/026_office_workspace.sql` (yeni kurulum: `database/init/027_...`).
  Tablolar `office_` önekiyle açılır; RAG çalışma alanındaki `projects`/`clients`/`documents` ile karışmaz.
- Her satır yalnız sahibine (`owner_id`) görünür (RLS). Eski şemadaki "admin her şeyi görür" istisnası
  kaldırıldı. Tek istisna `office_basvurular`: sahipsiz (siteden gelen) başvuruyu yalnız admin görür.
- Yabancı anahtar denetimi RLS'i atladığı için `office_require_own_references` tetikleyicisi, bağlanan
  kaydın çağıranın kendi kaydı olmasını şart koşar.
- Yazımlar `activity_logs`'a içeriksiz işlenir (`office.insert|update|upsert|delete`, dosya ve UYAP olayları).

## API
| Uç nokta | Görev |
| --- | --- |
| `POST /api/office/{tablo}` | Genel sorgu (select/insert/update/upsert/delete). Tablo ve sütunlar izin listesindedir. |
| `POST /api/office/storage/upload`, `GET .../download`, `POST .../remove` | Dosya deposu (`<DOCUMENT_STORAGE_DIR>/office/<kullanıcı>/…`), yalnız kendi klasörü. |
| `POST /api/office-ai/run`, `/document`, `/petition` | Belge analizi, özet, risk, sözleşme, dilekçe üretimi. |
| `POST /api/office-ai/ocr` | OCR (Tesseract + `tur` dil paketi kurulu olmalı; yoksa 503). |
| `POST /api/public/uyap-ingest`, `/api/public/v1/documents/upload` | UYAP eklentileri; bağlantı anahtarıyla yetkilendirilir. |
| `POST /api/public/basvuru` | Oturumsuz başvuru formu (IP başına 10 dakikada 5). |

Arayüzde `supabase.from(...)` çağrıları `web/src/lib/db.ts` uyumluluk katmanıyla bu uç noktalara gider.
Desteklenmeyenler: `or()` ve tam metin arama.

## Atıf kuralı (üretim akışları)
Modele yalnız doğrulanmış korpus kaynakları `[K1]…` ile verilir. Kaynak bulunamazsa üretim yapılmaz.
Çıktı ortak `verify_answer` denetiminden geçer; eksik, desteklenmeyen veya ilgisiz iddia varsa
HTTP 422 döner, model çıktısı gösterilmez/kaydedilmez. Bu katı alıntı denetimi serbest belge
taslaklarını da reddedebilir; belge üretimi tamamlanmış bir ürün özelliği sayılmamalıdır.
Kullanıcının yüklediği "karar" kişisel belge deposuna gider; korpusa girmez ve doğrulanmış sayılmaz.

## Bilinen sınırlar
- Yerel model yavaştır (bir dilekçe birkaç dakika); bağlam penceresi küçüktür (`OLLAMA_NUM_CTX`).
- OCR motoru bu makinede kurulu değildir.
- UYAP eklentileri varsayılan olarak `http://localhost:8766` adresine gönderir.
- Bağlantı anahtarı düz saklanır (arayüz tekrar gösterir); RLS ve iptal (`revoked`) ile korunur.
