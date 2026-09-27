# RAG aday havuzu ve doğrulama — 27 Eylül 2026

Bu değişiklik veri çekme işçilerini, ingestion ayarlarını veya korpus şemasını
değiştirmez. Yalnız soru anındaki kaynak bulma/doğrulama akışını değiştirir.

## Akış

1. `RAG_TOP_K` cevap bağlamının büyüklüğüdür; artık arama havuzunun büyüklüğü değildir.
   Varsayılan 6 için 48 aday parça alınır (üst sınır 96).
2. Genel konu sorularında anlamsal arama başarılı olsa da kelime araması çalışır.
   Mevzuat 3 sn, ANN 3 sn, kelime araması 4 sn sorgu bütçesi kullanır. Aynı
   bağlantıda sıralı çalışırlar; "paralel" veya sabit toplam gecikme garantisi yoktur.
   Açık kanun/madde sorusu doğrudan ilgili maddeyi arar, alakasız kararlara genişlemez.
3. İlgisiz metin filtreleri, güncellik/tarih kontrolleri, model kimliği ve RLS korunur.
   ANN en fazla 192 ham aday ister. Mevcut embedding'i olmayan kayıtlar metin
   indeksinden aday olabilir. Metni/parçası/indeksi olmayan kayıtlar aranamaz.
4. Sıralı havuzdan resmî kaynaklar korunur; bekleyen kararlar resmî portal metniyle
   karşılaştırılır. Eşleşmeyen adaydan sonra sıradaki belge denenir. Cevap akışında
   en fazla 12 farklı belgeye istek yapılır; **ortak 12 saniye bütçesi sıfırlanmaz**.
   Hedef 6 uygun farklı belgedir. CAPTCHA, 429 veya istek zaman aşımında yeni
  portal isteği başlatılmaz. Araştırma uç noktasının varsayılanı hâlâ 4 belgedir.
   Veritabanından tam karar metni yalnız denenecek en fazla 12 belge için okunur;
   48 adayın tamamının büyük metinleri gereksiz yere yüklenmez.
5. Doğrulanmış havuzdan önce farklı belgeler seçilir; sonra boş yer varsa aynı
   belgenin ek parçaları alınır. Modele varsayılan en fazla 6 parça verilir.
   Hazır korpus metni resmî metinle eşleşmeden modele, önizlemeye veya atfa çıkmaz.

Bu bir konu kapsamı/eksiksiz hukuki cevap garantisi değildir. 48 aday bir toplam
eşleşme sayısı değildir. ANN yaklaşık aramadır; sorgu bütçesi, indeks kapsamı ve
portal erişimi kapsama etki eder. Cevapta iki atıf olabilir; bu iki aday bulunduğu
anlamına gelmez. Kanıt cümlesi seçimi ve yerel modelin bağlam bütçesi ayrıca sınırlıdır.

## Ölçüm ve istemci sözleşmesi

NDJSON akışında `candidates_found` ve `search_summary` olayları; başarılı JSON
cevabında `search_summary` alanı eklenir. Mevcut alanlar değişmez. Sayaçlar yalnız
bu isteğin adaylarını açıklar, metin veya özel belge künyesi içermez:

- `candidate_chunks`, `candidate_documents`, `pending_documents`
- `verified_documents`, `selected_documents`, `unverified_excluded` (belge sayısı)
- `verification_attempted`, `verification_promoted`, `verification_stop`
- `lexical_candidates`, `semantic_candidates`, `retrieval_partial`, `exhaustive=false`

`selected_documents` cevap modeline verilenlerdir; atıf sayısı değildir.
`verified_documents` kullanıcı belgesi kanıtını da kapsayabilir; bunlar resmî
mevzuat/karar sayısı diye etiketlenmemelidir. Sayılar güncel istek için hesaplanır;
eski sohbet mesajları için uydurulmaz. Frontend bu alanları henüz göstermeyebilir.
Eksik doğrulama nedeniyle cevap üretilemese de özet olayı hata olayından önce gelir.

## Gerçek korpus kontrolü

Salt-okunur ilk ölçüm (`data/benchmarks/rag-discovery-20260927.json`):

| Soru | Havuz | Süre | Durum |
| --- | --- | --- | --- |
| Ortak velayet koşulları | 29 farklı belgeden 41 ilgili parça; 19 parça bekleyen | 2,83 sn | ANN ve kelime araması tamamlandı |
| TÜFE/kira artışı | 33 farklı belgeden 37 ilgili parça | 4,72 sn | Kelime kolu zaman aşımı; resmî madde ve ANN korundu |
| Yıllık izin ispatı | Uygun sonuç üretilemedi | 4,63 sn | ANN adayları ilgisiz; kelime kolu zaman aşımı |

Bu ölçüm portal doğrulaması veya cevap üretimi yapmaz. İlk raporun `count` alanı
doğrulanmış aday parça sayısıydı; değerlendirme aracı artık `count` ile model
bağlamını, `verified_candidate_documents` ile doğrulanmış belge havuzunu ayırır.

Henüz çözülmeyenler: yoğun konularda FTS gecikmesi, korpus embedding kapsamı,
portal engelleri ve sorunun bütün koşul/istisnalarını kapsadığını değerlendiren
etiketli test seti. Bunları gizlemek için doğrulama veya ilgililik filtresi gevşetilmedi.

Tekrarlı gerçek API testi (`rag-discovery-api-recheck-20260927.json`): ortak
velayet için 29 aday belge, 17 bekleyen, 12 doğrulanmış, modele seçilen 6 belge,
cevapta kullanılan 2 resmî atıf; uçtan uca 14,49 sn. Bir bekleyen belge için
portal isteği zaman bütçesinde tamamlanamadı, doğrulanmamış atıf yayınlanmadı.
İlk API denemesi aynı soruda arama zaman aşımı nedeniyle 503 döndü; sonraki
başarı bunu gizlemez. Kira cevabı doğrulanmış tek maddeyle 22,11 sn sürdü.
Yıllık izin tekrar aramasında 48 bekleyen belge bulundu; doğrulama için toplu
metin yüklemesi zaman aşımına uğradı, 422 döndü. Bunun ardından tam metin okuma
en fazla 12 denenecek belgeyle sınırlandı. Portal doğrulamasının canlı ortamda
başarılı şekilde aday tamamladığı henüz gösterilmedi; tamamlama mantığı kontrollü
regresyon testinde doğrulandı.

## Regresyonlar

`tests/test_rag_discovery.py`: ANN varken embedding'siz metin adayının bulunması,
istek genelinde süre/istek sınırı, ilk dört uyumsuz kayıttan sonra aday tamamlama,
CAPTCHA/zaman aşımında durma, aynı belgeye tek istek, model bağlamı ile havuzun
ayrılması, farklı belge seçimi ve sayımların atıf/toplam sayı ile karıştırılmaması.
Tam yerel test koşusunda worker/model kontrol hook'ları stub'lanır; gerçek
veri çekimi veya embedding süreçleri testler tarafından değiştirilmez.
