# AWS taşıma ön kontrolü — 2026-11-02

Henüz AWS kaynağı oluşturulmadı veya veri yüklenmedi.

## Ölçülen kaynak

- PostgreSQL `nhr_legal_ai`: `pg_database_size` sonucu 354 GB.
- Başlıca tablolar: legal_chunks 253 GB, legal_sources 52 GB,
  legal_source_revisions 34 GB, legislation_chunk_vectors yaklaşık 5,7 GB.
- Kullanıcı/office tabloları için kaba alt toplam: 922 MB (tam yedek boyutu değildir).
- Yerel uploads: 40.984 dosya, 13,88 GiB.
- Ölçüm anında C: 40,8 GiB boş, E: 767,4 GiB boş.
- Kullanıcının eu-north-1 CloudShell çıktısı: Standard On-Demand 16 vCPU;
  running/pending instance sorgusu boş. Hesap kimliği CLI ile henüz teyit edilmedi.

## Karar kapıları

1. Kullanıcı verisi + evrak yedeğini HDD'de tamamla ve arşiv bütünlüğünü doğrula.
   `scripts/backup_user_data.py` korpusu bilerek dışlar; tam göç yedeği değildir.
2. Büyük korpus için tutarlı tam PostgreSQL yedeği ve bağımsız geri yükleme planla.
   Çalışan Docker VHDX dosyası kopyalanmaz. Canlı yazılar varsa dump ve evrakların
   aynı kesim anına alınması için son eşitleme/bakım penceresi gereklidir.
3. Sunucu için kapasite adayı: en az 16 GiB RAM ile pilot ölçüm;
   yaklaşık 500–600 GiB gp3 disk. Kesin kapasite yük testiyle belirlenir.
   T3 CPU kredileri, Bedrock, trafik ve yedekler maliyete ayrıca dahil edilir.
4. Hesap planı/izinli tipler ve bölgesel fiyatlar doğrulanıp kullanıcı maliyeti
   onaylamadan EC2/EBS açılmaz. Kredi ödeme garantisi veya harcama sınırı değildir.
5. PostgreSQL yalnız özel Docker ağı/localhost erişimli kalır. Mevcut compose
   host portunu bütün arayüzlere açabilir; doğrudan internete deploy edilmez.
6. Mevcut nomic/bge-m3 vektörleri korunur; arama sorgularına aynı embedding
   modelleri gerekir. Bedrock metin üretiminin bulunması embedding'i kaldırmaz.
7. Güncel çalışma ağacı commit edilmemiş değişiklikler içeriyor; yalnız GitHub
   klonu son yerel değişiklikleri içermez. Gizli bilgiler/evraklar Git'e eklenmez.
8. HTTPS, erişim listesi, RLS, oturum, belge açma, arama ve kaynaklı cevaplar
   doğrulanmadan trafik taşınmaz veya yerel kopya silinmez.

## Yedek başlangıcı

Kullanıcı yedeği hedefi: `E:\JurisAI\migration-preflight-20261102`.
Tamamlanma, arşiv testi ve geri yükleme ayrı ayrı raporlanmalıdır; yalnız dosyanın
oluşması doğrulanmış yedek sayılmaz. Yedekler kişisel/hukuki veri içerir;
erişimi kısıtlı, tercihen şifreli tutulmalı ve ikinci fiziksel kopya planlanmalıdır.
