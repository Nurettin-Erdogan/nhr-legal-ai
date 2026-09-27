# Araştırma sonuçları ile cevap atıfları ayrı

`GET /api/ai/sources?q=...&limit=10&offset=0`, yerel **aranabilir güncel korpus**
içindeki koşullara uyan farklı kaynakları sayfalar. `027_rag_research_page.sql`
ile gelen salt-okuma fonksiyonu yalnız genel hukuk korpusuna erişir; kullanıcı
belgelerine erişmez. Kaynaklar tekilleştirildikten sonra
sayfalama yapılır. `total`, bu arama koşullarına uyan farklı kaynak sayısıdır;
aday havuzu sayısı veya tüm Türkiye kararlarının sayısı değildir.

Silinmiş/karantinadaki, henüz parçalanmamış ve arama için uygun olmayan kayıtlar
bu kapsamda değildir. Mevzuatın güncel sürümleri ve mevcut karar kaynakları
aranır. Tarihsel mevzuat için mevcut `as_of` akışı ayrı kalır. Yeni veri geldikçe
offset sayfalarının sırası değişebilir; arayüz tekrarları kimlik üzerinden ayıklar.

- Kaynak listesi model cevabından bağımsız yüklenir; model başarısız olsa da kalır.
- Kaynak taraması kullanıcı düğmeye bastığında açılır. Cevap üretilirken ikinci
  bir tam sayım sorgusu kendiliğinden başlatılmaz.
- `third_party` rozetleri korunur. Bu uç nokta portal doğrulaması yapmaz,
  işçi durdurmaz, embedding üretmez, veritabanına yazmaz.
- Sorgu 15 saniyede tamamlanmazsa HTTP 504 döner. Sınırlı aday havuzuna sessizce
  geçilip “tüm sonuçlar bulundu” denmez.

Soru planlayıcısı soru kalıplarını çıkarır; ilk iki anlamlı sözcükte kesmez.
Tanımlı bileşik kavramlar (ör. ortak velayet) sözcük yakınlığıyla zorunlu tutulur;
“ortak çocuk ... velayet” tek başına eşdeğer sayılmaz. Bu deterministik bir
başlangıçtır; bütün Türkçe hukuki eşanlamları veya tüm ilgili kararları bulma
garantisi değildir. Sıfır sonuçta ifade koşulu sessizce gevşetilmez.

RAG, geniş aday havuzunu sıraladıktan sonra model için seçilmiş kaynaklar kullanır.
`RAG_TOP_K` yalnız model bağlamıdır, sonuç listesinin sınırı değildir. Yerel ayar
6 parça/900 karakter ve 4096 token pencereye yükseltilmiştir; uzun metnin başı
yerine soruyla örtüşen **tam cümleler** seçilir. Tek modele sınırsız belge yığılmaz.
Embedding veya veri toplama yapılandırması bu değişiklikle değiştirilmez.

## 27 Eylül RAG düzeltmesi

Model artık hukuki cümleleri yeniden yazmak yerine kendisine verilen tam kaynak
cümlelerinin kimliklerini seçer. Sunucu bu kimlikleri gerçek metne bağlar; mevcut
atıf, sayı ve tam metin destek kontrolleri sonrasında gösterir. Bu bir **kaynak
alıntısı cevabıdır**, kalibre edilmiş bir hukuki yorum/parafraz sistemi değildir.
Kaynak metniyle eşleşme, kararın güncelliğinin veya her olaya uygulanabilirliğinin
garantisi değildir. Üçüncü taraf kaynakların doğrulanmadı rozeti korunur.

Numaralı paragrafların ve mahkeme isimlerinin noktalama işaretleri artık hatalı
"kaynaksız cümle" oluşturmaz. Süre sorularında aynı kavramı ve soru sözcüklerini
koruyan ek arama yapılır; süre/başlangıç bildiren cümleler öne alınır. Bu ek arama
4 saniyede durur; başarılı ilk aramanın sonuçlarını iptal etmez.

Kaynak listesinde tam metin ve detaylar sayım öncesi değil, yalnız seçilen sayfa
için okunur. Fonksiyon yoksa eski sorguya geri dönülür; geçişte 027 migrationını
admin bağlantısıyla uygulayın. Mevcut kayıtlar, sürümler veya indeksler değişmez.

Gerçek, salt-okuma ölçümü (portal doğrulaması, geçmişe kayıt ve işçi durdurma yok):

```powershell
.\.venv\Scripts\python.exe scripts\smoke_rag_readonly.py --include-research
```

27 Eylül yerel sıcak test: itirazın iptali cevabı 6,05 sn, geniş kaynak sayfası
2,77 sn (25.871 eşleşme); ortak velayet cevabı 1,63 sn, kaynak sayfası 0,16 sn
(42 eşleşme). Her iki cevap metin destek kontrolünü geçti. İlkinde üçüncü taraf
Yargıtay kaydı, ikincisinde resmî AYM kaydı kullanıldı. Bunlar tek makinedeki
örnek ölçümlerdir; API'nin canlı doğrulama/kayıt sürelerini ve soğuk model yükleme
süresini garanti etmez. Önceki geniş liste sorgusu 15 sn'de zaman aşımına uğradı.

Çalışan HTTP API kontrolünde itirazın iptali cevabı 14,56 sn'de HTTP 200 ve
`grounded=true` döndü (canlı doğrulama dahil). Geniş kaynak listesi yük altında
bir kez yine 15 sn zaman aşımına uğradı, sonraki gerçek HTTP isteğinde 6,56 sn'de
200/25.872 eşleşme döndü. Soğuk disk/yoğun işçi yükünde gecikme bütçesi hâlâ bir
sınırdır; test sonucu "bütün gecikmeler giderildi" anlamına gelmez.
Ortak velayet için gerçek cevap API'si 6,92 sn'de HTTP 200 ve `grounded=true`
döndü. İzole test veritabanıyla gönderilecek backend kopyası: 413 geçti, 1 atlandı.
