# Beş asistan modu: inceleme ve kabul kaydı — 2026-11-02

Bu kayıt yayın onayı değildir. Otomatik kontrol, sentetik gerçek model denemesi ve gerçek tarayıcı testi ayrı değerlendirilir.

## Gerçek arayüz yolları

| Sekme | Arayüz | Sunucu yolu |
| --- | --- | --- |
| Sohbet | LegalChat | ortak execute_answer hattı |
| Derin araştırma | DeepResearch | kalıcı rapor + üç sıralı araştırma ekseni |
| Belge analizi | AIRunner + DocumentJobPanel | document_jobs.process_window → analyze_document_window |
| Özetle | AIRunner + DocumentJobPanel | document_jobs.process_window → summarize_document |
| Risk incelemesi | AIRunner + DocumentJobPanel | document_jobs.process_window → _risk → üç araştırma ekseni |

Eski office_analysis doğrudan uç noktası, belge kuyruğuyla aynı yol değildir. Eski yolda elde edilen süreler, kuyruk uçtan uca kullanıcı süresi olarak sunulmaz.

## Bu tur bulunan ve giderilen hatalar

- Risk raporunda alt eksen hataları kuyruk tarafından kaybediliyordu. Artık errors taşınır, eksik işlem partial olabilir.
- grounded=true yalnız kalan iddiaların kaynak desteğini anlatıyor; tüm alt soruların karşılandığı anlamına gelmiyordu. coverage_complete ayrı alan olarak API, rapor, risk ve araştırma arayüzüne taşındı. Bilinmeyen eski kayıtlarda null kalır.
- Derin araştırmanın her bölümü doğrulanmış gibi yazılan sabit tanıtım metni düzeltildi.
- Araştırma durum sorgusu hatasında yeniden kontrol düğmesi eklendi. Yerel model kullanıldığına ilişkin eski açıklama kaldırıldı.
- Yüzde/yarısı ifadelerinin yanlış elenmesi için önceki düzeltme genişletildi. “Yüzde ellisi” biçimi tanınırken “yüzde kırkı” ile %50'nin eşit sayılmadığı negatif testle denetlenir.

## Kontroller

- Arayüzün tam Node test koşusu: 608 başarılı, 0 atlanan.
- Ortak sohbet, geçmiş, kaynak seçimi, sayılar, sentez, belge kuyruğu, derin araştırma, analiz ve yeni kapsam API alanı: izole veritabanı ve ağ engeli ile 658 başarılı, 0 atlanan.
- TypeScript kontrolü başarılı.
- Asistanın incelenen beş arayüz dosyasının ESLint kontrolü başarılı; CRLF/biçim bulguları yalnız bu dosyalarda biçimlendirildi.
- Bir Starlette bağımlılık kullanımdan-kaldırma uyarısı mevcut; çalışma hatası olarak sayılmadı.

## Sentetik canlı belge işçisi denemesi

Gerçek kullanıcı belgeleri kullanılmadı; kalıcı kullanıcı işi oluşturulmadı. Bu süreler işçinin tek pencere süresidir; yükleme, kuyruk bekleme, kimlik doğrulama veya tarayıcı çizimini kapsamaz.

| Mod | Süre | Gözlem |
| --- | --- | --- |
| Belge analizi | 4,1 sn | Beş bulgu korundu; oran, vade, teslim ve hariç giderler mevcut |
| Özetle | 3,4 sn | Beş bulgu korundu; yarısı/yarısı ödeme planı mevcut |
| Risk incelemesi | 157 sn | Üç eksenli uzun rapor; tekrarlar ve eksik alt-konu açıklaması var; hız kabulü başarısız |

Normal sohbetin son ayrı canlı koşusu: 11,4 sn, Bedrock `deepseek.v3.2`, grounded=true ve coverage_complete=true. Tek soruluk ölçümdür; genel gecikme garantisi değildir. Bu koşuda retrieval yaklaşık 30 ms sürdü; bu örnekte ana süre veritabanı araması değildir.

Derin araştırmanın son canlı koşusu: 50,9 sn; üç başlıktan yalnız biri kaynaklı cevap üretti, biri doğrulanamadı, biri önceki metnin tekrarı olduğu için kaldırıldı. İş döngüsü done olsa da kalite kabulü başarısızdır.

İlk ek sohbet ölçümünde test betiği slots kullanan süre nesnesini vars() ile okumaya çalışıp TypeError verdi. Bu ürün hatası olarak raporlanmadı; betik düzeltildi ve yalnız sohbet tekrar ölçüldü.

## Açık kalanlar

### 0,02 USD onaylı canlı ölçüm

- İlk deneme kısıtlı komut ortamında yanıt alamadı; anahtarsız ağ tanısı dış bağlantının WinError 10013 ile engellendiğini gösterdi. Ağ izinli koşu ayrı çıktı dizinine kaydedildi.
- Test sürecinde her Bedrock çağrısı öncesi UTF-8 girdi boyutu + çerçeve payı ve 2048 çıktı tokenı üzerinden muhafazakâr fiyat üst sınırı denetlendi. Bu sınır yalnız ölçüm betiğine aittir; .env ve uygulama çıktı ayarları değiştirilmedi. API hata yanıtlarında belirsiz maliyet rezervi korunur, tekrar otomatik çağrı yapılmaz.
- Karar ekseni: 6,04 sn (retrieval 0,89 sn; model zinciri 4,56 sn), Bedrock deepseek.v3.2. grounded=false, citation_count=0; cevap yalnız “Sözleşmeniz hangi tarihte başladı ve ne zaman yenileniyor?” oldu. Kalite kabulü BAŞARISIZ; hızlı olması başarılı hukuk cevabı olduğu anlamına gelmez.
- İki yanıtlı çağrının kullanımı: 14180 giriş + 78 çıkış tokenı. AWS Standard fiyatıyla ($0,62/$1,85 / milyon token) tahmini 0,00893590 USD; fatura mutabakatı değildir. Sonraki usul çağrısı kalan bütçeye göre üst sınırda izin alamadığı için gönderilmedi; usul ekseni model performansı olarak ölçülmüş sayılmaz.
- Canlı hatanın kökü: _clarification_options, kaynaktaki genel sözleşme/ödeme sözcükleri nedeniyle gereksiz olay sorularını modele sunuyordu. Bu kontroller somut tarih/tutar hesabı isteğiyle sınırlandı; salt açıklama isteğinin bu sorularla değiştirilmesi kodda reddedilir. Kaynak ve sayı doğrulaması korunur. Yeni regresyonlarla 435 odak test geçti, sentez Ruff temiz.
- Bu son açıklama-sorusu düzeltmesi henüz ikinci bir ücretli model koşusunda doğrulanmadı. Yeni ücretli çağrı yapılmadı; tüm asistanın sorunsuzluğu iddia edilmez.

### Araştırma hattının ek incelemesi

- Araştırma eksenleri artık özgün olay anlatımını korur. Mevzuat ipucu veya konu kısaltması olay bilgisinin yerine geçmez. Üç eksenin görevleri ayrı belirtilir; büro araştırmasındaki gereksiz ön-kısaltma model çağrısı kaldırıldı.
- Sentetik eksen ölçümünde arama 3,2–4,9 sn, model işlemleri 11,6–18,5 sn sürdü. Mevzuat ekseni başarılı; karar ekseni checker_schema, usul ekseni dropped_coverage nedeniyle başarısız oldu. Bu ölçüm başarı sayılmadı.
- Derin araştırmada bozuk denetçi biçimi için yalnız bir yeniden değerlendirme eklendi. Özgün kaynak ve iddialar tekrar denetlenir; hatalı biçim veya ret otomatik onaya çevrilmez. Bu son değişikliğin canlı kazanımı henüz ölçülmedi.
- Ek izole kabul koşusu: 357 başarılı, 0 atlanan, 1 Starlette uyarısı; gerçek ağ çağrıları engellendi. Bu sayı önceki 658'e ek bağımsız test sayısı değildir; örtüşen odak koşusudur.
- Bedrock tek sağlayıcı nesnesinin kimliği yerel sağlayıcıyla aynı olduğundan, kaynakla sınırlı sentezin onarım seçeneği kapalı kalıyordu. Bedrock ve bulut araştırmasında tek kaynak-bağımlı onarım etkinleştirildi; yerel Ollama davranışı korunur. Gerçek execute_answer entegrasyon testi her iki profilde bunu doğrular.
- Sentez çıktısının kaynak eksikliği/kapsam bilgisi artık coverage_complete alanına taşınır; onarımda alt tanıdan üst yanıta aktarılır. Belirsiz tanı otomatik tam-kapsam başarısı sayılmaz.
- 2026-11-02 ek tam çevrimdışı koşu: 3706 başarılı, 0 atlanan. Chromium dosyaları ayrı, açıkça etkinleştirilmiş koşuda sınanıyor; bu 3706 sayısına dahil değiller. İki uyarı: Starlette deprecation ve bilerek bozuk TIFF test verisi.
- Ağ engelleyicisi tam koşuda bir gerçek ağ girişimini durdurdu: bu, engelleyicinin kendisini sınayan testin beklenen davranışıdır; bağlantı kurulmadı.
- Tam arayüz testleri yeniden 608 başarılı, 0 atlanan; TypeScript başarılı. Ruff kuruldu; api/ai dizini ve araştırma/belge/özet çekirdeğinin lint kontrolü temiz.
- İlk tam koşudaki 145 kurulum hatası eski sabit geçici klasörün Windows erişim kilidinden kaynaklandı. Test çalıştırıcısı her koşuda yeni proje-altı klasör kullanır; eski klasörler zorla silinmedi. İkinci koşudaki mağaza paketleme izni hatası, geliştirme tünel izninin üretime taşınmasından kaynaklandı; üretim host izinleri açık listeyle sınırlandı ve tekrar test edildi. Geliştirme manifesti değiştirilmedi.
- Ayrı Chromium koşusu tamamlandı: 155 başarılı, 0 atlanan, 0 başarısız (1673,38 sn). Ek bundled-key tarayıcı koşusu: 2 başarılı, 0 atlanan. Bunlar yerel sahte portal/API üzerinde gerçek Chromium testleridir; açık kullanıcı oturumunun canlı JurisAI testi veya gerçek UYAP portalı doğrulaması değildir. Chromium koşusunda ağ engelleyicisi test fonksiyonu dışından gelen iki bağlantı girişimini engelledi.
- Beş asistan arayüz dosyasının ESLint kontrolü yeniden temiz. API yeniden başlatıldı; sağlık 200, Uvicorn 127.0.0.1:8766 başlangıç kaydı mevcut. Son düzeltmeler sonrası ücretli model çağrısı yapılmadı; yeni canlı kalite/hız ölçümü için en fazla 0,02 USD AWS kredi izni istendi, henüz onay alınmadı.

1. Riskin her belge penceresinde üç ayrı genel araştırma yürütmesi pahalıdır. Darboğaz süreleri ayrıca ölçülmeden genel hız kazanımı iddia edilmez.
2. Karar ekseninin gerçekten ilgili karar taşıması ve istenen tüm alt konuları karşılaması için daha güçlü kabul seti gerekir. Salt kaynak adedi başarı değildir.
3. Gerçek tarayıcı etkileşimi henüz doğrulanmadı: hem Windows native pipe hem browser access host erişilemiyor. Kullanıcı yeniden bağladığını bildirdikten sonra da envanter boş kaldı. Mock arayüz testleri gerçek kullanıcı testi sayılmaz.
4. Canlı kullanıcı hesabıyla kuyruk başlatma → sekme değiştirme → geri gelme → durdur/devam → çıktı aç/kopyala akışı tarayıcı bağlantısı geldiğinde tamamlanmalıdır.
5. Uzun ve çok belgeli canlı kalite testi henüz yapılmadı. Kuyrukta tüm pencerelerin kapsanması otomatik testle sınanmıştır; bu durum bütün belgelerin anlamsal olarak eksiksiz özetlendiğini kanıtlamaz.

Veri aktarımı, üretim PostgreSQL/Docker süreçleri ve kullanıcı belgeleri değiştirilmedi. Test veritabanı ayrı konteynerdir. Commit yapılmadı.
