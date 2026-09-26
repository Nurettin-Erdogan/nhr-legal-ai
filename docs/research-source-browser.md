# Araştırma sonuçları ile cevap atıfları ayrı

`GET /api/ai/sources?q=...&limit=10&offset=0`, yerel **aranabilir güncel korpus**
içindeki koşullara uyan farklı kaynakları sayfalar. Mevcut tam FTS fonksiyonunu
`NULL` limit (`LIMIT ALL`) ile çağırır. Kaynaklar tekilleştirildikten sonra
sayfalama yapılır. `total`, bu arama koşullarına uyan farklı kaynak sayısıdır;
aday havuzu sayısı veya tüm Türkiye kararlarının sayısı değildir.

Silinmiş/karantinadaki, henüz parçalanmamış ve arama için uygun olmayan kayıtlar
bu kapsamda değildir. Mevzuatın güncel sürümleri ve mevcut karar kaynakları
aranır. Tarihsel mevzuat için mevcut `as_of` akışı ayrı kalır. Yeni veri geldikçe
offset sayfalarının sırası değişebilir; arayüz tekrarları kimlik üzerinden ayıklar.

- Kaynak listesi model cevabından bağımsız yüklenir; model başarısız olsa da kalır.
- Eski sohbetlerin tamamı açılışta otomatik taranmaz; eski sorularda kullanıcı
  aramayı açar. En son soru otomatik aranır.
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
