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
| `POST /api/office/cases/{case_id}/documents` | Multipart `file`: dava erişimini kontrol eder; belgeyi ve dava/müvekkil ilişkisini kaydeder (50 MB). |
| `POST /api/office/cases/{case_id}/documents/{document_id}/link` | Sahibinin henüz davaya bağlanmamış belgesini bağlar; başka dava veya uyumsuz müvekkil için 409 döner. |
| `POST /api/office-ai/run`, `/document`, `/petition` | Belge analizi, özet, risk, sözleşme, dilekçe üretimi. |
| `POST /api/office-ai/ocr` | OCR (Tesseract + `tur` dil paketi kurulu olmalı; yoksa 503). |
| `POST /api/public/uyap-ingest`, `/api/public/v1/documents/upload` | UYAP eklentileri; bağlantı anahtarıyla yetkilendirilir. |
| `POST /api/public/basvuru` | Oturumsuz başvuru formu (IP başına 10 dakikada 5). |

Arayüzde `supabase.from(...)` çağrıları `web/src/lib/db.ts` uyumluluk katmanıyla bu uç noktalara gider.
Desteklenmeyenler: `or()` ve tam metin arama.

## Dava evrakları

`/dashboard/cases/<id>` ekranındaki **Evraklar** sekmesinde dosya yüklenebilir veya mevcut
bağlantısız belgeler dosya adıyla aranıp sayfalanarak seçilebilir. Başka davadan otomatik taşıma
yapılmaz. Başarılı işlemden sonra dava detayındaki liste backend'den yeniden okunur.
Bu işlem yalnız özel dosya saklama ve ilişkilendirmedir; OCR, chunking veya RAG indeksleme yapmaz.

Yeni yükleme UUID dosya anahtarı kullanır; mevcut dosyanın üzerine yazmaz. Belge satırı ve denetim
kaydı aynı kullanıcı transaction'ında oluşturulur. Commit öncesindeki hatada yalnız yeni dosya
temizlenir. Commit yanıtı belirsizse olası başarılı kaydı bozmamak için dosya korunur, olay loglanır
ve istemci listeyi kontrol etmeye yönlendirilir; otomatik yeniden yükleme yapılmaz. Disk/DB arasında
dağıtık transaction yoktur: süreç çökmesi veya belirsiz commit sonrası sahipsiz dosyaların yönetici
tarafından incelenmesi gerekebilir. Bu dosyalar otomatik silinmez.

## Atıf kuralı (üretim akışları)
Modele yalnız doğrulanmış korpus kaynakları `[K1]…` ile verilir. Kaynak bulunamazsa üretim yapılmaz.
Çıktı ortak `verify_answer` denetiminden geçer; eksik, desteklenmeyen veya ilgisiz iddia varsa
HTTP 422 döner, model çıktısı gösterilmez/kaydedilmez. Bu katı alıntı denetimi serbest belge
taslaklarını da reddedebilir; belge üretimi tamamlanmış bir ürün özelliği sayılmamalıdır.
Kullanıcının yüklediği "karar" kişisel belge deposuna gider; korpusa girmez ve doğrulanmış sayılmaz.

## Bilinen sınırlar
- Yerel model yavaştır (bir dilekçe birkaç dakika); bağlam penceresi küçüktür (`OLLAMA_NUM_CTX`).
- OCR motoru bu makinede kurulu değildir.
- Dava belgelerinin (UYAP dahil) aranabilir yapılması: [office-document-rag.md](office-document-rag.md).
- UYAP eklentileri varsayılan olarak `http://localhost:8766` adresine gönderir.
- Bağlantı anahtarı düz saklanır (arayüz tekrar gösterir); RLS ve iptal (`revoked`) ile korunur.

## Genel arama (üst çubuk)

`GET /api/office/search?q=` (`api/office_search.py`) oturum sahibinin dava, müvekkil, belge ve görevlerinde arar; her
gruptan en çok 5 kayıt döner. Yalnız sahibin satırları görünür (RLS + açık `owner_id` koşulu), çöpteki belge
aranmaz. Büyük/küçük harf ve "İ/I/ı" farkı gözetilmez ("DEMİR" = "demir"); kullanıcının yazdığı `%` ve `_` joker
sayılmaz. Müvekkil TC/vergi numarasıyla da bulunur ama numara yanıta konmaz. Hukuk korpusu burada aranmaz; kutu aynı
terimi İçtihat, Mevzuat ve Hukuk Asistanı sayfalarına taşıyan kısayollar sunar (`?q=` ile; asistanda soru yalnız
kutuya yazılır, gönderilmez). Arayüz: `web/src/components/GlobalSearch.tsx` ("/" ya da Ctrl+K ile odaklanır). Kutu
dar ekranda (telefon) gösterilmez.

## Takvim, hatırlatma ve form denetimleri

- Davanın "Sonraki Duruşma" tarihi ve açık görevlerin son tarihi takvimde salt okunur etkinlik olarak görünür
  (`web/src/lib/calendar-derived.ts`); kaynağı dava/görev kaydıdır, takvim tablosuna kopyalanmaz.
- Zamanı gelen hatırlatmalar üst çubuktaki zilde gösterilir; e-posta kanalı yalnız SMTP kuruluysa açıktır
  ([account-security.md](account-security.md)).
- Müvekkil formunda TC kimlik no (11 hane + denetim hanesi), vergi no (10 hane + denetim hanesi; şahıs işletmesinde
  TC kimlik no) ve telefon (10–15 rakam) doldurulmuşsa denetlenir (`web/src/lib/client-form.ts`). Alanlar isteğe
  bağlıdır. Denetim yalnız arayüzdedir.
