# Kavram araması ve karar bağlamı — 28 Ekim 2026

## Ölçülen

Ücretli model veya dış web araması olmadan, kamu korpusunda salt okunur tekrar:

- `Muris muvazaası deliller ve değerlendirme ölçütleri` sorgusu 13 aday
  getiriyordu. Seçilenler ağırlıkla görev/ticari dava tartışmalarıydı.
- `muris muvazaası` ayrı sorgusu Yargıtay 1. Hukuk Dairesi ve HGK kararlarını
  getirdi. Bu sorguda zaman aşımı/katmanlı arama kaydı var; tam korpus taraması
  tamamlandı denilemez.
- Seçilen `E. 2021/6970, K. 2021/7965` kaydında keşif, rayiç bedel,
  tanık beyanları ve irade araştırmasına değinen kaynak cümlesi mevcut.
  Bu bulgu, kullanıcının sorusunun tamamını cevaplamaya yeterli olduğunun
  bağımsız doğrulaması değildir; farklı hukuki sebeplere ilişkin bölümler
  cevaba karıştırılmamalı, mevcut iddia/mahkeme görüşü denetimi korunmalıdır.
- Bazı kararlar yaklaşık 1.800 karakterlik giriş parçasıyla seçiliyordu.
  Aynı resmî kaydın diğer bölümlerinin mevcut olması, ilk parçanın bunları
  içermesini sağlamaz.

## Düzeltme

1. Korunan bileşik hukuk kavramları için uzun sorgu korunur, kavramın kendisi
   de bağımsız yerel arama kolunda araştırılır. Sadece bu örnek değil; işe iade,
   ortak velayet, kıdem tazminatı gibi kayıtlı kavramlarda aynı algoritma işler.
2. `muris muvazaası` korunan arama kavramı ve kamu portalı arama sözlüğüne
   eklendi. Bunlar kanıt/hukuki cevap değildir.
3. Seçilen resmî kararın en çok 20.000 karakterlik tam metni aynı kaynak,
   parça, sürüm/revizyon ve SHA-256 eşleşmesiyle geri alınır. Özel, doğrulanmamış,
   değişmiş veya fazla büyük kaynaklar genişletilmez. Kaynak kimliği değişmez;
   rol, iddia, kapsam ve cevap denetimleri kaldırılmaz.

## Doğrulama ve sınır

- Tam çevrimdışı takım: **2824 passed, 442 skipped**, 1 mevcut deprecation
  uyarısı. Test veritabanı tanımlı olmadığı için atlananlar başarılı sayılmadı.
- Salt okunur gerçek korpus tekrarı kısa kavram kolunun ilgili kararları ve
  kullanılabilir delil cümlelerini getirdiğini gösterdi.
- Son kullanıcı cevabı gerçek üretim/denetçi modeliyle yeniden çalıştırılmadı;
  bu turda model kredisi harcanmadı. Bu yüzden eski cevabın tam olarak hangi
  model cümlesini neden elediği ve yeni cevabın eksiksiz olacağı iddia edilmiyor.
- Tüm resmî kurumlar bağlanmış değildir; mevcut iki canlı adaptörün kapsamı
  değiştirilmedi. Veri/embedding/Docker süreçlerine dokunulmadı.
- API yeniden başlatma için aktif işlem durumu ayrıca soruldu.
