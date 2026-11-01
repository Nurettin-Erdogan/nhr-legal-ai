# RAG arama sayacının görünürlüğü — 27 Eylül 2026

## Bileşen

`web/src/components/SearchSummary.tsx` her istek için dört ayrı sayıyı gösterir:
aday belge, kaynak kontrolünü geçen belge, modele verilen belge ve atıf yapılan
farklı belge. Belge sayısı parça sayısı değildir. Bu sayaçlar bütün korpusta
eşleşen toplamı göstermez; kart bu sınırlamayı açıkça belirtir.

Doğrulanamayan aday sayısı ve CAPTCHA, hız sınırı, zaman bütçesi veya veritabanı
hatası ayrı açıklanır. Arama kısmi ise uyarı görünür. Kontrolü geçen özel kullanıcı
belgesi de kanıt olabildiğinden bu sütunun adı "resmî belge" değildir.

`parseSearchSummary` eski/eksik/negatif/tutarsız sayıları reddeder. Yeni sayı
uydurmaz ve istekten gelen başka alanları arayüze taşımaz. Tarihî sohbetlerde
sayaç alanı yoksa kart gösterilmez.

## Yerel frontend bağlantısı ve Git kapsamı

İlk küçük commit yalnız bağımsız bileşen, veri tipi ve testleri içeriyordu.
Kullanıcının frontend geçişi onayından sonra TanStack/Vite arayüzü, gerekli
sohbet/büro API'leri ve bu entegrasyon birlikte yayımlanacak pakete alındı.

Yerel `LegalChat.tsx` ve `ai-api.ts` içine şu entegrasyon yapıldı:

- NDJSON `search_summary` olayı okunur; cevap beklenirken sayılar gösterilir.
- `done.result.search_summary` cevap mesajına bağlanır; atıf yapılan farklı belge
  sayısı `source_id` üzerinden hesaplanır.
- Başarısız isteğin özeti ve hata mesajı görünür kalır.
- Yeni sohbet/başka sohbet açılınca geçici özet temizlenir; çalışan istek sırasında
  sohbet değiştirip sayıları yanlış sohbete bağlamak engellenir.

Veri çekme/embedding işçisi değişiklikleri bu pakete alınmadı. Kullanıcının diğer
staged değişiklikleri korundu. Eski Supabase migration/ETL betikleri ve tasarım
arşivleri çalışır uygulamanın parçası değildir; yerelde kaldı.

## Testler

- `node --test tests/search-summary.test.mjs` (web içinde): 5 test geçti.
- `tsc --noEmit`: geçti.
- Yerel frontend `npm run build`: geçti.
- Render testleri gerçek React bileşeninde sütunları, farklı belge/atıf sayılarını,
  kısmi sonuç ve CAPTCHA uyarısını kontrol eder.
- Gerçek tarayıcı kontrolü giriş ekranına yönlendiği için tamamlanmadı; oturum
  açma otomasyonu yapılmadı. Tam uçtan uca UI testi henüz geçmiş sayılmaz.

## Gecikme ölçümü (korpus salt okunur)

`data/benchmarks/rag-fts-profile-20260927.json`: `EXPLAIN (ANALYZE, BUFFERS)` ile
yalnız metin aramasının aday ID/sıra döndüren SQL fonksiyonu ölçüldü. Model veya
portal çağrısı bu ölçüme dahil değildir.

| Soru | Mevcut oturum ayarı | Paralel sorgu işçisi kapalı |
| --- | --- | --- |
| Yıllık izin ispatı | 3,980 sn / 192 aday parça | 3,884 sn / 192 aday parça |
| TÜFE/kira artışı | 4 sn bütçesinde zaman aşımı | 4 sn bütçesinde zaman aşımı |

Yıllık izin ölçümünde ilk koşuda 40.244 shared-read blok kaydedildi. Bu, aramanın
buffer okuma yükünü gösterir; doğrudan fiziksel disk IO miktarı diye yorumlanmaz.
Canlı ingestion yükü/cache koşulları değiştiğinden tek ölçümden hızlanma iddia
edilmez. Paralel işçi ayarı anlamlı fayda göstermediği için uygulamaya alınmadı;
yalnız geçici, salt-okunur test bağlantısında denendi.

**Kalan iş:** yoğun konularda FTS sorgu planını/indeks stratejisini ölçerek
iyileştirmek; hazır korpusun resmî doğrulama engellerini sayaçlardan ayrı ele almak.
Doğrulama veya ilgililik filtresi gevşetilmedi; worker/ingestion ayarı değişmedi.
