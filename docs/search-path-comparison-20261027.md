# Liste ve asistan araması: aynı sorgu karşılaştırması

27 Ekim 2026. Sentetik sorgu: `kira zammı`. Yerel PostgreSQL üzerinde salt
okunur çalışıldı. Model üretimi, embedding veya ücretli sağlayıcı çağrısı yok.
Araç: `scripts/compare_public_search_paths.py`. Bu incelemede asistan davranışı
değiştirilmedi ve API yeniden başlatılmadı.

## Ölçüm

İlk, soğuk liste araması 9,19 saniyede 246 aday ve `partial=true` döndürdü.
Tekrarında 2,62 saniyede 257 aday ve `partial=false` döndü. Sonuç sayısı bu
arama yolunun zaman aşımı/katmanlı fallback davranışından etkileniyor; tam
korpus toplamı veya soruyu cevaplayan karar sayısı olarak okunmamalı.

Asistanın yalnız sözcük kolu ikinci ölçümde:

- `rent_increase` niyetini tanıdı; TBK 6098/344 güncel maddesini 0,011 sn'de aldı.
- `lexical_focused` 1,194 sn'de 192 parça aldı. Madde dahil 107 kaynak belgesi.
- İlgi filtresi 192 karar parçasının tümünü geçirdi.
- Sıralama/çeşitleme sonrasında 48 parça kaldı; seçici yalnız TBK 344'ü tuttu.
- `_with_decisions` havuzun ilk üç karar parçasını ekledi: Danıştay 12. Daire
  2021/2404–2023/1325, Yargıtay 3. HD 2025/6193–2026/2965 ve
  Yargıtay 3. HD 2024/2574–2025/2204.
- Liste ilk 10 kaynak kimliğiyle asistanın 48 sonucunun kesişimi sıfırdı.
  Farklı sorgu genişletme ve sıralama kullandıkları için bu tek başına hata değil.

## Somut kaynak seçimi sorunu

Modele eklenen ilk karar parçası
`22a0d215-56de-4388-b9ae-e4f23a0800e0`, kaynak
`0512feae-9820-40c5-8261-37c30068a242`, açıkça
**DAVACININ İDDİALARI** başlığıyla başlıyor. Vakıf konutlarının kira artışına
ilişkin tarafın itirazlarını taşıyor; kendi başına Danıştay'ın hukuki kabulü değil.
İçinde 6098/344 ve kira artışı sözcükleri bulunduğundan ilgili sayılıp üstte
sıralanıyor. Böyle bir parça geçerli bir arama sonucu olabilir; ancak sınırlı
cevap kanıt havuzunda mahkemenin gerekçesi yerine yer kaplıyor.

`api/ai/discovery.py` genel soruda birincil mevzuata öncelik veriyor (bu bilinçli
güvenlik politikası). `api/ai/pipeline.py::_with_decisions` sonraki üç kararı
parçanın konuşmacı/bölüm rolünü değerlendirmeden ekliyor. Mevcut
`decision_attribution.py` ve bağımsız denetçi, üretim sonrasında yanlış mahkeme
atıflarını engellemeye çalışıyor; seçim aşamasındaki bu kalite kaybını çözmüyor.

## Sonuç ve sınır

Bu sorguda 'asistan veriye erişemiyor' teşhisi yanlış: doğru kanun maddesi ve
çok sayıda karar parçası getiriliyor. Ölçülen sorunlar: liste yolunda literal
kelime eşleşmelerinin konu isabeti sanılması, cevap yolunda aşırı daralan
havuz ve taraf iddiası/gerekçe ayrımı olmadan yardımcı karar seçimi.

Bu test vektör kolunu, soru planlayan modeli, cümle denetimini ve belirli bir
eski sohbetin ret nedenini çalıştırmadı. Dolayısıyla her başarısız cevabın tek
nedeni bulunduğu veya düzeltildiği iddia edilemez.

Bir sonraki düzeltme hedefi: kaynak güveni veya hukuki denetimi gevşetmeden
karar parçasının bölüm/konuşmacı rolünü seçimde kullanmak; ilgili gerekçe ve
aynı kararın bağlamını adaylaştırmak. Taraf iddiaları aramadan silinmemeli,
mahkeme görüşü gibi kullanılmamalı. Sadece daha fazla parça veya daha uzun
timeout vermek bu sorunu tek başına çözmez.
