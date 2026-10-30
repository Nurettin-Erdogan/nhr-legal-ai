# Normal sohbet: yerel kaynak önceliği — 28 Ekim 2026

## Uygulanan değişiklikler

- Basit, tek konulu ve kullanılabilir yerel kaynaklı soruda ilk kaynak havuzu
  yeniden kullanılır. Aynı soru için ikinci planlama/arama yapılmaz.
- Sırf kaynak havuzunu doldurmak için her soruya ek karar araması yapılmaz;
  açık karar isteği varsa bu yol korunur.
- Resmî web araştırması, açık güncellik isteğinde veya bir araştırma başlığında
  ilgili kullanılabilir kaynak eksikse çalışır. Yerel kaynak hazırsa rutin web
  çağrısı atlanır. Özel kapsam, tarihsel soru ve dış URL güvenlik sınırları
  mevcut üst akışta korunur; bu yönlendirme dışarıya kullanıcı verisi göndermez.
- Bir önceki cümlesi doğrulanmış ve gösterilmiş paragraf geçişi sırf yeni
  paragraf başında olduğu için atılmaz. Desteklenmeyen öncüle bağlı geçiş
  korunmaz. Her hukuki iddianın denetimi devam eder.
- Kullanıcının kaldırdığı genel eksiklik ön eki geri eklenmedi. Kısmi sonuç
  tanısı ve tam cevap önbelleği dışında tutma davranışı korunur.
- Aşama sürelerine seçilen denemenin yazım/denetim süreleri ve deneme sayısı
  eklendi. Bu sayılar kaynak metni veya kullanıcı sorusu içermez.

## Doğrulama

- Backend son koşu: 2885 geçti, 443 atlandı, 0 başarısız (standart pytest koşusu).
- Yeni sentetik entegrasyon testi, hazır yerel kaynaklı basit soruda modelle
  planlama, ikinci arama ve resmî ağ çağrısının yapılmadığını doğrular.
- Yönlendirme testleri güncellik, kaynak yokluğu, ilgisizlik, farklı mahkeme,
  ayrı iki karar şartı ve çok parçalı soru sınırlarını kapsar.
- Gerçek bulut ölçümü aşağıdadır. Sabit saniye veya eksiksizlik garantisi yoktur.

Kaynak hazır bulunması semantik kapsamın bütünüyle karşılandığı anlamına
gelmez. Cümle/kapsam denetçisi ve gerektiğinde hedefli yeniden araştırma
korunur. Bu değişiklik korpus içeriğini veya kaynak güven düzeyini değiştirmez.

## Canlı ölçüm ve ikinci düzeltme turu

Sentetik genel sorular, gerçek PostgreSQL ve mevcut OpenRouter/Luna ile doğrudan
`execute_answer` hattında ölçüldü. Tarayıcı, HTTP oturumu ve kaydedilmiş sohbet
yazımı bu ölçümün kapsamında değildir. Başka kullanıcı verisi kullanılmadı.

| Ölçüm | Süre |
| --- | ---: |
| Basit kira sorusu (ilk bulut ölçümü) | 5,84 sn |
| Aynı basit sorunun önbellekli tekrarı | 0,03 sn |
| Çok parçalı soru, ilk bulut ölçümü | 54,66 sn |
| Aynı çok parçalı soru, son kod | 15,84 sn |

Son çok parçalı sonuç `openrouter / openai/gpt-6-luna`, `grounded=true`,
tek yazım/denetim denemesi ve `coverage_preserved=true` döndürdü; 4857/18,
4857/20 ve 7036/3 atıfları kullanıldı. Bu, tek kontrollü koşudur; tüm soru
dağılımında gecikme yüzdelikleri veya kusursuz hukuk doğruluğu kanıtı değildir.
İlk sandbox koşusundaki ağ engeli yerel modele geri dönüşe neden olmuştu;
o koşu bulut performansı sayılmadı.

Bulunan ortak hatalar ve düzeltmeler:

- Doğru madde, gündelik konu ifadesini aynen içermeyince ilgisiz sayılıyordu.
  Mevcut konu–madde eşlemesi, gerçek madde metni için `text_matches` denetimiyle
  alaka değerlendirmesine eklendi; yalnız metadata yeterli değildir.
- Planın sayısal referansları önce doğrudan doğrulanmış güncel madde sorgusuyla
  çözülür. Her parça kullanılabilir ve ilgili yerel kaynak bulursa geniş fan-out
  ertelenir; kapsam/açılış başarısızlığında mevcut tek revizyon bütçesinde açılır.
  Tarihsel/özel kapsam ve açık karar talepleri bu yerel-plan kestirmesini kullanmaz.
- Yinelenen plan sorguları iş kuyruğuna yalnız bir kez konur; parça bağları korunur.
- İsimlendirilmiş kanun sorgusuna farklı kanun metni o kanunun metni gibi katılmaz;
  bağımsız kavram/parça kolları ve karar adayları korunur.
- Hatalı bir ifade her zaman eksik kaynak demek değildir. Kaynağı mevcut bir
  ifade revizyonunda her elenen cümle için yeniden geniş arama yapılmaz.
- Denetçi, atıf yapılan kaynağın tamamını görür; ilgisiz, kullanılmamış hitler
  çıkarılır. Cevapta temsil edilmeyen bir parçanın kaynakları kapsam denetimi
  için yine gönderilir. Kaynak numaraları ve tam koşul/istisnalar korunur.
- Denetçi paragraf bağlamını görür; diğer cümleler bağımsız hukuki kanıt değildir.
  Kapsam değerlendirmesi yalnız onaylanıp gösterilebilecek cümlelerin birleşimi
  üzerinden istenir; kodda elenen ifadeler ayrıca belirtilir.

Testlerde sayı/alıntı/yanlış yön/özel kapsam/atıf denetimi kaldırılmadı. Test
çalıştırıcısına yalnız üst süreçte `-X utf8` verilince sekiz alt-süreç yardım
testinde Windows kod sayfası uyumsuzluğu görüldü; standart belgelenmiş pytest
komutuyla tüm etkin testler geçti. 443 atlanan test tamamlanmış sayılmıyor
(izole test veritabanı, tarayıcı veya açık opt-in isteyen testler).

Anahtar limiti değiştirilmedi. Canlı ölçümler öncesi/sonrası salt okunur limit
sorgusu yaklaşık 0,0331 USD kullanım farkı gösterdi; eşzamanlı başka kullanım
varsa bu farkın tamamı yalnız bu ölçümlere atfedilemez.
