# Çalışma alanı belge içeriği araması

Dosyalar → **Belge içeriğinde ara**. Belge adı/dosya bilgisi aramasından
ayrıdır. UYAP ve elle yüklenen belgelerde, dava bağlantısı zorunlu olmadan,
yalnız oturum sahibinin aktif belgelerinde çalışır.

- En az 2, en çok 100 karakter; yazılan kelime/ifade birebir aranır.
  Türkçe büyük/küçük harf çiftleri ve ardışık boşluk/satır sonları normalize
  edilir. `%`, `_` ve `\` SQL jokeri sayılmaz. Anlamsal/AI araması değildir.
- `documents.status='ready'` olan kaydın **tüm document_chunks** metinlerinde
  arar, kısa `content_excerpt` alanıyla sınırlı değildir. İlk eşleşen parça
  gösterilir; aynı belgedeki birden fazla eşleşme belge sayısını artırmaz.
- Eşleşen bölüm düz metin olarak vurgulanır. HTML çalıştırılmaz. Kaynakta
  sayfa numarası varsa gösterilir; yoksa sayfa uydurulmaz.
- Kaynak, klasör, kategori, sıralama ve mevcut toplu listeleme korunur.
  İçerik sorgusunda eşleşen klasörler otomatik açılır.
- Aranabilirlik sayacı seçili kaynak/klasör/kategori kapsamını **sorgudan önce**
  sayar. İşlenmeyen/OCR bekleyen ve okunamayan belgeler açıkça belirtilir;
  sıfır eşleşme, işlenmemiş belgelerde de ifadenin olmadığı anlamına gelmez.

## Güvenlik ve işletim

`GET /api/office/case-documents/search?search_in=content&q=…` mevcut oturum
doğrulamasını ve `nhr_runtime` RLS bağlantısını kullanır. Kaynakta açık
`owner_id` koşulu, türetilmiş kayıtta aynı `uploaded_by` eşleşmesi vardır.
Kaynak/türetilmiş kayıttaki silinen belgeler dışlanır. Sorgu parametreleri
bağlanır; içerik aramasındaki SQL sorguları 8 saniye ile sınırlandırılır.
Yeni tablo/migration, model çağrısı veya korpus aktarımı gerekmez. Arama
kendisi belgeyi yeniden okumaz/indekslemez; mevcut indeksin durumunu gösterir.

## Doğrulama

`tests/test_document_content_search.py`: düz metin kesiti, Türkçe/boşluk,
literal joker, kimlik doğrulama ve kapsam doğrulaması; PostgreSQL JSON
fixture'larıyla gerçek sorgular (geç parçadaki eşleşme, sayfa, birden fazla
parça, başka kullanıcı, çöp ve silinmiş/başkasına ait/başarısız indeks,
klasör/kategori/kaynak kapsamı ve sayfalama). JSON fixture'ları gerçek
tabloları CTE ile gölgeler; kullanıcı arşivine yazılmaz.

XML/EYP ve iç içe UYAP ZIP ekleri de güvenli ayrıştırma başarılıysa bu aynı
indekste aranır. Arşiv eşleşmesinde iç ek yolu bölüm başlığında/metinde korunur.
İmza baytları aranmaz ve EYP imzasının doğrulandığı iddia edilmez. Karma PDF
ve çok sayfalı görüntüde okunamayan sayfa sessizce atlanıp tamamı hazır
gösterilmez. Ayrıştırıcı sürümü yenilendiğinde eski indeks açık yeniden
indeksleme sırasında güncellenir; içerik araması kendiliğinden ağır OCR başlatmaz.

`web/tests/content-match-excerpt.test.mjs`: gerçek React HTML çıktısında
XSS kaçışı, işaretleme ve bilinmeyen sayfa. `file-browser.test.mjs`: oturum,
iptal sinyali, içerik arama parametresi, kesit ve aranabilirlik verisi.
