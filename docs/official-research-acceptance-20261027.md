# Resmî web araştırması — devreye alma

## Uygulanan

- Normal, güncel ve özel kapsam içermeyen sohbet için
  `OFFICIAL_WEB_RESEARCH_ENABLED=true`; `.env` öncesinde git dışındaki
  `.local/env-backups/` dizinine yedeklendi. Anahtarlar raporlanmadı/değiştirilmedi.
- Yerel kaynak boşluğu ve açık madde eksikliği, erken olumsuz cevaptan önce
  resmî araştırmaya yönlendirilir. Çok başlıklı doğal cevap planı da yeni
  kalıcı kaynaklarla zenginleştirilir. Cümle/iddia denetimi korunur.
- Bağlı adaptörler: MBS ve Yargıtay. Diğer 19 katalog kurumu için canlı
  arama adaptörü bu değişikliğin kapsamında tamamlanmış değildir.
- Kişi bilgileri, ham soru, sohbet geçmişi, özel belgeler dış sorguya gitmez.
  Dış sorgu yalnız sayısal madde kimliği veya sabit hukuk arama terimidir.
- Farklı mevcut kaynak metni sohbet içinden üzerine yazılmaz. Kaynak kimliği,
  resmî tam metin ve kalıcı kayıt olmadan cevap için kanıt üretilmez.
- Gerçek Yargıtay kabulünde ilk denemede zaman aşımı yaratan tablolar arası
  OR sorgusu ayrı indeksli kimlik sorgularına bölündü; ikinci kabul geçti.

## Sonuçlar

- Tam çevrimdışı test takımı: **2810 passed, 442 skipped**, 1 mevcut
  Starlette/httpx kullanımdan kaldırma uyarısı. Test veritabanı tanımlı değil;
  atlanan testler başarılı kabul edilmedi. Ağ engeli aktifti.
- Gerçek MBS indirmesi: 6098 sayılı Kanun kimliği/başlığı doğrulandı,
  289.986 karakter.
- Gerçek araştırma koordinatörü: `6098 sayılı Kanun madde 315` →
  `document_verified` → korpustan 1 bağlam, kimlik `6098 / 315`.
- Gerçek Yargıtay araması: `kira`, 124.038 eşleşme, 2 kalıcı doğrulanmış
  kaynak, kaynak okuyucudan 6 parça. Tüm eşleşmeler okunmadı.
- API yeniden başlatıldı, `/health` 200; Uvicorn 127.0.0.1:8766'da başladı,
  başlangıç günlüğünde WinError 10048 yok.
- **Ücretli üretim/denetçi modeliyle son kullanıcı cevabı testi yapılmadı.**
  Yukarıdaki canlı testler yalnız resmî portal ve kaynak zinciri testidir;
  her hukuki sorunun eksiksiz yanıtlanacağının kanıtı değildir.

Korpus taramaları, embedding işçileri, Docker/veritabanı süreçleri ve model
seçimi değiştirilmedi. Commit/push yapılmadı.
