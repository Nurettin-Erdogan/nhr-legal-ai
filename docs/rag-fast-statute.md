# Güncel maddeyle hızlı cevap, ayrı kaynak araştırması

Bu yol geniş korpus aramasını hızlandırdığı iddiasında bulunmaz: uygun sorularda
cevabın geniş aramayı beklemesini kaldırır. Toplama/embedding işçileri, canlı
korpus, DB şeması ve kaynak doğrulama kuralları değiştirilmez.

## Kapsam ve güvenlik

- Yalnız kısa ve güncel kira artışı, kıdem şartları ve itirazın iptali süresi
  soruları mevcut kanun/madde eşlemesiyle denenir. Emsal/karar, delil/ispat,
  tarihsel, çok konulu, proje ve devam eden sohbet soruları normal yolda kalır.
- Runtime bağlantısında salt okunur, bir saniye sorgu limitli madde araması
  yapılır. Bağlantı açma ve yoğun yük nedeniyle duvar saati daha uzun olabilir.
  Resmî kaynak, current sürüm ve silinmemiş kayıt filtreleri aynen korunur.
- Aynı madde için tek kaynak sürümü, bütün dönen parçaların resmî olması,
  ilgili kaynak cümlesi ve mevcut kapsam-koruma denetimi aranır. Bir fazla parça
  istenerek limit nedeniyle kesilme saptanır; sığmayan metin hız uğruna kesilmez.
- Eksiklik/hata/timeout durumunda normal RAG akışı kullanılır. Modelin hızlı
  taslağı kaynak denetimini geçmezse geniş akış **bir kez** yeniden çalışır;
  desteklenmeyen taslak kullanıcıya yayımlanmaz.
- Bu kontrol anlamsal yeterlilik veya mevzuatın mutlak doğruluğu garantisi
  değildir. Nihai atıf/metin denetimi, koşullar/istisnalar ve kapsam uyarıları kalır.

## Arayüz

`search_summary.retrieval_strategy=verified_statute`, `research_deferred=true`
ve `exhaustive=false` cevap sayacının yalnız madde aramasına ait olduğunu belirtir.
Son tamamlanan hızlı cevaptan sonra mevcut `/api/ai/sources` üzerinden ayrı ilk
araştırma sayfası otomatik açılır. Bu sayfa cevabı engellemez. Diğer sayfalar
"Devamını getir" ile istenir; tüm korpus arka planda sınırsız taranmaz.
Bekleyen adaylar mevcut resmî portal kontrolünden geçmeden listelenmez; portal
ve arama hataları kaynak panelinde görünür. Aynı component yükleme durumunu
değiştirdiğinde sonuçları silmez veya otomatik tekrar döngüsü başlatmaz.

Sohbeti/API'yi doğrudan kullanan istemcilerde ayrı araştırmayı istemci başlatır;
sunucuda kalıcı bir arka plan araştırma kuyruğu eklenmemiştir.

## Gerçek salt okunur smoke — 27 Eylül 2026

Yerel `qwen3.5:4b` ve canlı korpusla, worker kontrol sarmalayıcısı/portal yazımları
çalıştırılmadan gerçek cevap gövdesi denendi. Önbellek ve eşzamanlı yük süreleri
etkiler; aşağıdaki tekil ölçümler SLA veya p95 değildir.

| Soru | Madde kontrolü | Cevap gövdesi | Ayrı eski geniş metin araması |
| --- | --- | --- | --- |
| Kira/TÜFE | 0,059 sn | 0,847 sn, kaynak denetimi geçti | 4,033 sn, 48 belge |
| İtirazın iptali süresi | 0,030 sn | 6,194 sn, kaynak denetimi geçti | 4,047 sn, metin kolu timeout |
| Kıdem şartları | 0,030 sn | Hızlı yol reddedildi | Normal RAG yolu korunur |

Kıdem maddesi kapsam-koruma yeterlilik kontrolünü geçmedi; yalnız hızlı sonuç
almak için kısaltılmadı. Geniş sorgulardaki zaman aşımı ve model gecikmesi ayrıca
iyileştirilmelidir. UI/persist ve resmî portal gecikmeleri bu tabloya dahil değildir.

## Regresyon kontrolleri

- İzole release kopyası ve geçici test veritabanı: **569 Python testi geçti,
  1 atlandı**. Canlı DB kullanılmadı; yalnız test DB'si kaldırıldı.
- Arayüz: **14 test geçti**, TypeScript kontrolü geçti.
- Yanlış/eski/bekleyen madde, parça taşması, tarih/proje/sohbet kapsamı ve model
  reddinde tek seferlik geniş aramaya dönüş test edildi. Sayaçlar tam korpus
  sayısı gibi gösterilmiyor; otomatik araştırma yalnız son tamamlanan hızlı
  cevap için ilk sayfayı başlatıyor.
