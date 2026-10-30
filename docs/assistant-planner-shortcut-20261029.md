# Kısa sorularda kapsam kaybı — 2026-10-29

## Bulgu ve düzeltme

`simple_search_plan`, tanınmış tek konu için model planlama çağrısını atlar.
Ancak noktalama eksik olduğunda “İşe iade şartları nelerdir hangi sürede
başvurulur” gibi birden fazla talep de bu kestirme yola girebiliyordu.
Bu, tek başlık altında kalan taleplerin ayrı takip edilmesini engelliyordu.

Birden fazla açık soru ifadesi veya soru işaretinden sonra devam eden talep
varsa artık kestirme kullanılmaz. Mevcut planlayıcı özgün sorunun tamamını
alır. Kod hukuk cevabı üretmez, maddeleri tahmin etmez, kaynak doğrulama
kurallarını gevşetmez. Tek talepli basit sorularda model çağrısız yol korunur.

## Doğrulama

- Yeni 9 test: noktalamasız çoklu talepler, soru işareti sonrası devam,
  basit soruların kestirmeyi koruması ve iki arama hattının planlayıcıdan gelişi.
- Yalıtılmış PostgreSQL backend paketi: **3285 geçti, 0 başarısız,
  0 atlanan**, 81,08 saniye. XML: `.local/planner-coverage-20261029.xml`.
- İki mevcut EXIF uyarısı var. Gerçek ağ engeli aktif; kasıtlı engel testi
  dışında gerçek ağ çağrısı yapılmadı.
- Tarayıcı uzantısı paketi bu backend koşusuna dahil değildir; bu adımda
  frontend/uzantı değişmedi ve tarayıcı paketi yeniden çalıştırılmadı.
- Ruff denendi fakat yerel sanal ortamda modül/komut yok; lint temiz denemez.

## Açık kalanlar

Bu kontrol bir dil anlama garantisi değildir. Planlayıcı hâlâ bir talebi
atlayabilir veya birkaç talebi tek parçada birleştirebilir. Bu adım yalnız
kanıtlanan kestirme hatasını giderir; bütün soruların eksiksiz yanıtlanacağını
veya canlı modelin hızlandığını kanıtlamaz.

Yeni ücretli çağrı, API yeniden başlatması, üretim veritabanı/korpus değişikliği
yapılmadı. Test konteyneri koşudan sonra durduruldu. Değişiklik henüz çalışan
API'ye alınmadı. Sonraki kontrol planlayıcı çıktısının özgün sorudaki taleplerle
eşleşmesi ve ardından izinli canlı süre/kapsam ölçümüdür.
