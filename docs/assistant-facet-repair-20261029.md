# Canlı ölçümden sonra kaynak kapsamı onarımı

29 Ekim 2026. Yeni ücretli çağrı yapılmadan uygulanmıştır.

## Kaynak açığı

Son canlı icra testinde planın ikinci parçası birden fazla başvuru yolunu
soruyor, fakat kesin yerel madde kolu yalnız modelin belirttiği referansları
okuyordu. Bir parçada herhangi bir madde bulunması hızlı yolun hazır sayılması
için yeterliydi. Mevcut `statute_hints` kataloğundaki diğer ilgili referanslar
bu kolda kullanılmıyordu.

Kesin yerel referanslar artık o plan parçasının mevcut katalog ipuçlarıyla
birleştirilip tekilleştiriliyor. Sayılar arama ipucudur; metin yalnız doğrulanmış
korpustan okunur, geri gelen metin yine kullanılabilirlik/alaka/kanıt/denetçi
kontrollerinden geçer. Tarihsel ve özel kapsam bu genel-sohbet hızlı yoluna
alınmamıştır. Regresyon testi, planlayıcı yalnız m. 67 verdiğinde m. 66 ve 68'in
de arandığını, aynı referansın iki kez sorgulanmadığını kontrol eder.

## Hedefli onarım

Denetçinin alt soru kapsam gerekçeleri onarım yüküne ayrıca aktarılıyor.
Gerekçede açık `kaynak_eksik:` varsa yalnız ilgili alt soru yeniden araştırılır.
`ifade_duzelt:` ise eldeki kaynaklarla yazım/koşul onarımı yapılır; gereksiz geniş
arama tetiklenmez. Bu, yeni bir model çağrısı veya sınırsız döngü eklemez; mevcut
iki denemelik bütçe korunur. Eksik kaynak ile kötü anlatımı ayırmak semantik
denetçinin sorumluluğudur; bu ayrımın gerçek modeldeki başarısı henüz ölçülmedi.

## Doğrulama sınırları

İlgili 139 test geçti; tüm Python lint kontrolü temiz. Geniş backend regresyonu
ayrı test veritabanında 3.330 başarılı, 0 başarısız, 0 atlanan testle tamamlandı
(95,43 saniye; `.local/assistant-facet-20261029.xml`). İki mevcut uyarı önceki
koşuyla aynı: Starlette/httpx deprecation ve kasıtlı bozuk TIFF/EXIF verisi.
Test veritabanı koşu sonunda durduruldu. UYAP tarayıcı paketi bu değişikliklerin
kapsamı değildir ve bu tur çalıştırılmadı. Gerçek model kalite/hız iyileşmesi bu
ücretsiz testlerin sonucu olarak kanıtlanmış sayılmaz.
