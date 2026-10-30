# Asistan kök neden incelemesi — 24 Ekim 2026

Bu rapor, olası nedenleri uygulamanın gerçek katalog/sorgu planı ve geçmiş
okuyucusu üzerinden ayırır. Üretim verileri üzerinde tam tarama, ağır
`EXPLAIN ANALYZE`, kullanıcı sohbeti okuma/değiştirme veya embedding durdurma yapılmadı.

## Ölçülmüş bulgular

| Katman | Kanıt ve sınır |
| --- | --- |
| Vektör üretimi | Sorgu vektörü mevcut, `nomic-embed-text`, 768 boyut; saklama sütunu `vector(768)`. Boyut uyumsuzluğu görülmedi. Bu, bütün korpusun gömülü veya modellerin her sürümünün eşdeğer olduğunu kanıtlamaz. |
| Ana vektör indeksi | `legal_chunks` için kullanılabilir HNSW/IVFFlat yoktu. Mevzuatın ortak ve M3 HNSW indeksleri geçerli/hazırdı. |
| Büyük arama planı | `EXPLAIN` (çalıştırmadan) ana sorguda HNSW yerine `idx_legal_chunks_embedded` üzerinden milyonlarca tahmini satırın taranıp mesafeye göre sıralanacağını gösterdi. Önceki gerçek örneklerde bu kol 3 saniyede zaman aşımına uğruyordu. |
| Geçmiş | Gerçek `prior_questions_from_rows`, kullanıcı sorularını yerel-model görüntüleme sınırı olan 300 karakterde kesiyordu. Ücret/tarihler 300. karakterden sonra kalınca takipte olgular yok oluyordu. Ağ/DB olmadan aynı gerçek okuyucu üzerinden yeniden üretildi. |
| Örnek parça bütünlüğü | Doğrulanmış TBK 315 ve 344 ile İş K. 17 bütün; 1475/14'ün beş parçasından birinde yarım son cümle ayıklaması gerekiyordu. Bu örneklerde tamamen kullanılamayan parça yoktu; bütün korpusta parçalama sorunu olmadığı iddia edilmez. |
| Model/denetim | Önceki canlı örnekte doğru kaynaklar yazıcıya verilerek doğal TBK 315 cevabı kabul edilmişti. Bazı taslakların elenmesi ayrıca mevcut; bütün retlerin embedding kaynaklı olduğu söylenemez. |

Temizlik betiği `scripts/clear_unverified_embeddings.py`, indeksi kaldırma ve
`--rebuild` adımlarını ayrı çalıştırabiliyor. Bu, kodda olası bir yolun kanıtıdır;
tek başına hangi operatörün ne zaman indeksi kaldırdığını kanıtlamaz.

## Devreye alınan kod düzeltmeleri

- `vector_index.shared_vector_index_ready`, salt okunur ve kısa süreli katalog
  kontrolüyle gerçekten geçerli/hazır, doğru sütuna ve cosine operatörüne ait
  bir ortak ANN indeksi olup olmadığını denetler. Sonuç veritabanı/rol bazında
  15 saniye tutulur; indeks bitince API yeniden açılmadan kullanılabilir.
- İndeksin yokluğu kesin biliniyorsa milyonlarca vektörü sıralayan kol çalışmaz.
  Mevzuatın indeksli ortak/M3 aramaları ve kelime araması devam eder; sonuç
  `partial=true`, `semantic_index_status=missing`, `skipped_unindexed` olarak
  dürüstçe işaretlenir. Bu, kayıp anlamsal şeridi geri getirmek değildir.
- Geçmişin kullanıcı-olgu kanalı, API'nin kabul ettiği 2000 karakterlik mesajı
  korur. Yerel modele verilen kısa görüntüleme geçmişi ayrı kalır. Yalnız gerçek
  sosyal mesajlar atılır; kullanıcı oranı/tutarı içeren hesap mesajı unutulmaz.
  Önceki asistan cevabından yeni kullanıcı olgusu türetilmez.
- Kullanıcı/scope/RLS, doğrulanmış kaynak, tarihsel uygulanabilirlik ve
  hukuki iddia denetimleri değiştirilmedi. API yeniden açıldı, sağlık 200.

## İndeks onarımı ve durum

Kullanıcı, embedding sürerken `CONCURRENTLY` kurulumu açıkça onayladı.
[pgvector resmî kılavuzu](https://github.com/pgvector/pgvector#indexing), yazıları
engellememek için üretimde eşzamanlı indeks oluşturmayı önerir. Kurulum 512 MB
bakım belleği ve ek paralel işçi olmadan başlatıldı; global DB ayarı değiştirilmedi.

İlk denemenin 5 saniyelik kilit sınırı mevcut uzun UPDATE'leri beklerken doldu;
0 baytlık geçersiz/hazır-olmayan indeks kaydı kaldı. Yalnız bu kayıt, doğru tablo
ve sıfır boyut tekrar doğrulandıktan sonra `DROP INDEX CONCURRENTLY` ile temizlendi.
Hiçbir vektör/metin/kullanıcı satırı silinmedi. Yeniden deneme mevcut yazıcıları
iptal etmeden bekledi ve gerçek kurulum aşamasına geçti.

Son kontrol anında: `building index: loading tuples`, 206.675 işlenen vektör,
729 MB indeks; `indisvalid=false`, `indisready=false`. Bu bir tamamlanma yüzdesi
veya süre tahmini değildir; indeks henüz hazır değildi.

Kurulum günlüğü: `.local/legal-ann-build-20261024-retry.out.log`.
Bağımsız, yalnız okuyan son-kontrol yardımcısı, indeks geçerli/hazır olunca
`nhr_runtime` üzerinden planın ANN kullandığını ve gerçek sorgunun 3 saniyelik
bütçede sonuç verdiğini bir kez sınayacak, sonra kapanacak. Bu fiziksel sorgu
testidir; hukuki cevap doğruluğu testi değildir. En çok 24 saat hazır olmayı bekler.
Sonuç: `.local/legal-ann-verify-20261024-v2.out.log`.

Kurulumun bitmesi ve son-kontrolün başarılı olması ayrı koşullardır; bu rapor
ikisini de tamamlanmış saymaz. Test başarısız olursa geçerli indeks otomatik silinmez.

## Doğrulama

- Python: **2288 geçti, 440 atlandı**, bir bağımlılık deprecation uyarısı.
- Gerçek kaynak araması (LLM yok): velayet örneğinde 3,32 saniye, 50 aday parça;
  ana vektör sıralaması atlandı, iki mevzuat vektör kolu ve kelime kolu başarılı.
  Bu tek ölçüm genel hız/eksiksizlik garantisi değildir.
- Uzun mesajın sonunda kalan ücret/tarihlerin gerçek geçmiş okuyucusunda
  korunduğu; sosyal metin ve asistanın türettiği sayılarla karışmadığı test edildi.
- `git diff --check` temiz. Kullanıcı verisi, sağlayıcı anahtarı veya ödeme ayarı
  yazdırılmadı/değiştirilmedi. Commit/push yapılmadı. Embedding işçileri durdurulmadı.
