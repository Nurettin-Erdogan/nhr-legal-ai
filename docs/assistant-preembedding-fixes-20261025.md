# Embedding sürerken hazırlanan asistan düzeltmeleri

Durum: kod ve çevrimdışı testler hazır; bu çalışma API/Docker yeniden başlatmadı,
canlı veritabanına migration veya yazı uygulamadı, embedding işçilerine dokunmadı.
Dinamik planlayıcı kapalı kalıyor; canlı kabul testi henüz tamamlanmış değildir.

## Hafıza

- Son iki soru-cevaplık model geçmişi ile kullanıcı olay hafızası ayrıldı.
- Mevcut, silinmemiş kullanıcı mesajları aynı sohbet ve mevcut RLS altında ayrıca
  okunuyor. Yeni tablo veya mesaj içeriğinin ayrı bir hafıza kopyası oluşturulmadı.
- Okuma operasyonel olarak en son 512 kullanıcı mesajıyla sınırlı; bu sınırsız,
  kalıcı kişi/proje hafızası iddiası değildir. Önceki sekiz mesajlık olay kesmesi
  kaldırıldı. Sınıra ulaşan çok uzun sohbetler için gelecekte sayfalama/olay kaydı
  tasarımı ayrıca değerlendirilmeli.
- Modelin ham kullanıcı beyanı bağlamı sıkıştırılıyor: en güncel tipli olay
  bilgilerinin gerçek ana mesajları, düzeltme/ret/neden kayıtları ve son mesajlar
  taşınıyor. Özgün kullanıcı mesajı indeksleri korunuyor; AI özeti hukuk kaynağı
  veya kullanıcı beyanı yapılmıyor.
- Açıkça başka müvekkil/kişi/olaya geçişte önceki olay bilgisi sıfırlanıyor.
  Bu, çoklu olaylar arasında kendiliğinden kişi eşleştirme yaptığı anlamına gelmez.

Regresyonlar: 60 takip mesajından sonra ücret/tarih korunması, son düzeltmenin
geçerliliği, geçersiz son tarihin eski geçerli tarihle doldurulmaması, başka
müvekkile eski ücretin taşınmaması, görünmeyen sohbetten hafıza okunmaması.

## Cevap başarısızlığı

Genel doğal cevap denetimden geçmediğinde araştırma planını silip dört mevzuat
parçasından uzun alıntı cevabına dönme kaldırıldı. Başarısız açıklama yayımlanmaz;
durum açıkça bildirilir. Kullanıcı açıkça aynen/tam metin istiyorsa doğrulanmış
alıntı yolu mevcut kaynak denetimleriyle kullanılabilir.

Bu düzenleme reddedilen her cevabı kendiliğinden başarılı hâle getirmez. Doğal
sentez, kaynak kapsamı ve bağımsız denetim canlı örneklerle hâlâ ölçülmelidir.

## Üretim kuyruğu

Bulut istekleri yerel modelin tek ortak asenkron kuyruğundan ayrıldı; aynı olay
döngüsünde en çok dört bulut üretim dizisi ilerleyebilir. Bu token veya yanıt boyu
kotası değildir; sınırsız ağ fan-out'u da değildir. API anahtarı/bakiye/ödeme
ayarları değiştirilmedi ve her isteğin hukuki denetim akışı korunuyor.

Doğrudan Ollama üretimi ve buluttan yerele dönüş aynı reentrant thread kilidini
kullanıyor; bulut paralelliği yerel modele eşzamanlı yüklenme izni vermiyor.
Bekleyen bulut görevi iptal edildiğinde slot kaybı olmadığı test edildi.

## Son doğrulama

- Python: **2365 geçti, 440 atlandı**, bir bağımlılık deprecation uyarısı.
  `NHR_TEST_DATABASE_URL` yalnız test sürecinde boş bırakılarak gerçek DB testleri
  devre dışı tutuldu; atlananlar başarılı sayılmıyor.
- Hedefli hafıza/sentez/yönlendirme: 384 geçti.
- Hedefli kuyruk/sağlayıcı/yönlendirme: 136 geçti.
- `py_compile` ve `git diff --check` başarılı.
- Bu turda ücretli model çağrısı, canlı sohbet değişikliği, commit/push yapılmadı.

Embedding/bakım tamamlandığında: aktif işlem olmadığı doğrulanarak yalnız API
yeniden başlatılmalı; oturumlu uzun sohbet, kaynaklı genel cevap, düzeltme ve yeni
olay senaryoları gerçek modelle sınanmalı. Araştırma planlayıcısı ancak kendi
uçtan uca kapsam testi geçince açılmalı. ANN indeksinin kullanılabilirliği, sorgu
planı ve doğrulanmış kaynak bulma başarımı ayrı koşullardır.
