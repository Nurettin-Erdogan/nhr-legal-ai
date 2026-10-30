# Asistan ve uygulama kabul kontrolü — 28 Ekim 2026

## Güvenli test ortamı

- Canlı korpus kopyalanmadı/değiştirilmedi; veri işçilerine müdahale edilmedi.
- Geçici pgvector PostgreSQL: yalnız 127.0.0.1:55439, ayrı `nhr_legal_ai_test`, 1 CPU / 1 GiB sınırı.
- Şema `database/init` dosyalarından sıfırdan kuruldu. Bulut anahtarları test ortamına aktarılmadı.
- Python ağ bariyeri yalnız izole test DB'sine ve tarayıcı testlerinin yerel sahte portallarına izin verir.
- Ücretli model çağrısı yapılmadı. Backend ağ bariyerindeki tek ret, bariyerin kendisini sınayan negatif testtir.
- Backend koşusu bitince yalnız bu koşuda oluşturulan test konteyneri ve sentetik veri diski
  kaldırıldı; canlı veritabanı ve diğer konteynerler korunmuştur.

## Sonuçlar

| Kontrol | Sonuç |
| --- | --- |
| Backend birim + izole DB entegrasyon + gerçek yerel OCR + ağ bariyeri | 3130 geçti, 0 başarısız, 0 atlandı |
| Arayüz Node testleri | 570 geçti, 0 başarısız, 0 atlandı |
| TypeScript | Başarılı |
| Üretim derlemesi | Başarılı |
| Gerçek Chromium / sahte yerel UYAP | 155 geçti, 0 başarısız, 0 atlandı; 27 dakika 50 saniye |
| ESLint | Başarısız: 14410 biçimlendirme, 18 explicit-any, 1 gereksiz kaçış hatası; 23 uyarı |

Toplam 3285 Python/backend/tarayıcı + 570 arayüz testi: **3855 geçti, 0 başarısız,
0 atlandı**. Python/tarayıcı ağ bariyeri iki harici bağlantı girişimini engelledi;
gerçek UYAP veya ücretli sağlayıcıya test isteği gönderilmedi.

Raporlar: `.local/acceptance-backend-20261028.xml`, `.local/browser-acceptance-20261028.xml`,
`.local/acceptance-lint-20261028.json`.

Önceden atlanan 5302/m14 sürüm regresyon testi artık canlı arşive veya hazır korpus kaydına
bağımlı değildir. Kendi iki sentetik sürümünü yalnız test transaction'ında oluşturur;
eski sürümlerin korunduğu ve yeniden aktarımın idempotent olduğu aynı assert'lerle sınanır.
Bir denetim kaldırılmadı, test zorla geçmiş gösterilmedi.

## Canlı korpusta ayrıca bulunan sorun

`scripts/audit_statute_admission.py` salt okunur olarak çalıştırıldı; model/embedding çağrısı yok.
Yapılandırılmış 70 temel mevzuat referansının 70'i bulundu. 58'i cevap kanıtı olarak kabul edildi;
12'si metin şekli/sınır denetimini geçemedi:

- 2004/257, 2918/85, 4721/1023
- 6098/77, 117, 120, 146, 227, 342, 345, 350
- 6325/18-A

Bu, genel bir "veri yok" sonucu değildir. İncelenen kayıtlar sonraki maddenin başlığını
sonlarında taşıyor. Bazı komşu madde başlıkları boş veya `Madde No: ...` olduğundan
aynı resmî PDF/hash denetimi tek başına başlık sınırını belirlemeye yetmiyor.
Sayısal/koşullu başlıkları tahminle kesmek mevcut istisna/koşul güvenliğini zayıflatabilir;
bu kontrol gevşetilmedi. Resmî başlık/sınır metadatası ayrıca düzeltilmeli ve 70 referanslık
kontrol tekrarlanmalı. Çevrimdışı testlerin geçmesi bu canlı veri sorununun çözüldüğü anlamına gelmez.

## Canlı servis sınırı

- `/health`: `status=ok`, `database=connected`.
- Son 300 günlük satırında port çakışması yok; bir bulut zaman aşımı var.
- Yapılandırma OpenRouter / `openai/gpt-6-luna`, zaman aşımı 90 saniye.
- Sağlayıcının yeni canlı cevap üretimi sınanmadı; kredi harcanmadı.
- Kullanıcı aktif işlem olmadığını onayladı. Yalnız API mevcut `.local/restart_api.ps1`
  betiğiyle yeniden başlatıldı; sağlık HTTP 200, `Uvicorn running on http://127.0.0.1:8766`
  satırı doğrulandı. Yeniden başlatma günlüğünde port çakışması yok.

Sonuç: otomatik backend/arayüz testleri başarılıdır, fakat bütün canlı asistan cevaplarının
sorunsuz olduğu veya verinin eksiksiz olduğu iddia edilmez. Lint ve kaynak sınırı sorunları açıktır.
