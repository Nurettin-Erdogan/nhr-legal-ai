# Karar kanıtı seçimi düzeltmesi — 27 Ekim 2026

Ölçülen hata: `kira zammı` sorgusunda asistan TBK 344 ve 192 karar parçası
bulmasına rağmen sınırlı karar havuzunun ilk yuvasına Danıştay kararındaki
`DAVACININ İDDİALARI` bölümünü ekliyordu. Bulgu:
`docs/search-path-comparison-20261027.md`.

## Değişiklikler

- `decision_attribution.py`: çoğul İDDİALARI, TALEPLERİ, SAVUNMALARI başlıkları
  da tanınır. Böyle bir bölüm mahkemenin görüşü diye aktarılamaz.
- Aynı parça içindeki her bilinen bölüm kendi metniyle, soruyla ilgisi
  değerlendirilerek sıralama ipucu üretir: inceleme/gerekçe, bilinmeyen bölüm,
  alt mahkeme anlatımı, taraf iddiası/savunması. Bu bir hukuki doğruluk veya
  güven sertifikası değildir. Başlıksız metin mahkeme gerekçesi ilan edilmez.
- Retrieval kalite puanı bu ipucunu aynı kaynağın hangi parçasının öne
  çıkacağına uygular; veri silinmez ve arama güven filtresi değişmez.
- Model seçicisinde yalnız karar konumları yeniden sıralanır; mevzuat ve
  kullanıcı belgelerinin konumları/öncelikleri korunur.
- Yardımcı karar ekleme yalnız doğrulanmış ve farklı kaynak kimliklerini
  kullanır. Üç yuva aynı kararın üç parçasıyla doldurulmaz. Hem ilk havuz hem
  ek arama aynı seçimi kullanır.
- Cümle kanıtı, bağımsız denetçi, birincil mevzuat ve özel veri/bulut kuralları
  gevşetilmedi. Model veya ücret ayarı değişmedi.

## Doğrulama

- Odaklı 68 test geçti.
- Ağ bariyerli tüm Python paketi: **2654 geçti, 442 atlandı, 1 uyarı**.
  DB entegrasyon testleri test DB'si tanımlanmadığı için dahil değil.
  Bariyer 4 bağlantı girişimini engelledi; birisi bariyerin kasıtlı testiydi.
- Aynı yerel sorgu tekrarlandı: liste 257 sonuç (`partial=false`), asistan
  192 sözcük adayı + TBK 344, 107 farklı kaynak. TBK 344 model havuzunda kaldı;
  davacı iddiası parçası üç karar yuvasından çıktı. Yerine Yargıtay 3. HD
  2024/1083–2025/1439 parçası girdi. Diğer iki karar yuvası korundu.
- Bu canlı ölçüm yalnız arama ve seçimdir; ücretli cevap üretimi yapılmadı.

## Kalan sınırlar

Bu sınırlı başlık tanıyıcı tüm karar şablonlarını ayrıştıramaz. Başlık önceki
parçada kaldıysa bölüm bilinmeyen sayılır; tam karar bağlamını daha sonra
geri getirme gerekir. Kararın kaynağı doğru olsa bile eski rejim, olaya özgü
sonuç ve farklı uyuşmazlık türleri ayrıca denetlenmelidir. Tüm asistan
sorunlarının çözüldüğü iddia edilmez.

Kullanıcı aktif işlem olmadığını onayladıktan sonra API yeniden başlatıldı:
`/health` 200, startup complete ve 127.0.0.1:8766 dinleme kaydı doğrulandı;
WinError 10048 yok. Kanun taraması canlı. Bağımsız metin/hash taramasının
692.500 kayıtta Windows checkpoint dosya kilidiyle durduğu görüldü; atomik
checkpoint değişimine sınırlı yeniden deneme eklendi (4 odaklı test geçti)
ve tarama kayıtlı ilerlemeden yeniden başlatıldı. Commit/push yok.
