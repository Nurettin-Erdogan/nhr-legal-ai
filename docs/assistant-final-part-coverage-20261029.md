# 4. adım — Nihai alt-soru kapsamı

## Bulunan boşluk

Eski son kontrol, alt sorunun kaynak kimlikleri ile gösterilen cevabın kaynak
kimliklerinin kesişimine bakıyordu. Aynı madde hem koşulu hem süreyi taşıyorsa,
yalnız koşulu açıklayan cümle iki alt soruyu da cevaplamış gibi görünebiliyordu.
Global `coverage_preserved` tek başına hangi bölümün eksildiğini göstermiyordu.

## Yeni akış

Birden fazla **planlanmış** alt soru varsa mevcut bağımsız denetçi çağrısı,
her alt soru için `part_id`, onu açıklayan `claim_ids`, `complete` ve `why`
döndürür. Ek bir normal LLM çağrısı yoktur. OpenRouter/OpenAI katmanındaki
sıkı şema bu alanı zorunlu kılar; eski tek-parça ve diğer sentez sözleşmeleri
değişmez. OpenAI Docs kuralları uyarınca nesneler `additionalProperties=false`
ve tanımlı alanlar `required` olarak düzenlendi:
https://developers.openai.com/api/docs/guides/structured-outputs .

Protokol doğrulayıcı gerçek bool/tamsayı, benzersiz ve tam alt-soru kimlikleri,
geçerli cümle kimlikleri ister. Eksik harita eski global onayla geçerli kabul
edilmez. Varsa mevcut sınırlı biçim düzeltmesi aynı kanıtla tekrar yapılır;
yine hatalıysa cevap onaylanmaz.

Son metin kurulduktan sonra:

1. Denetçi cümle kimlikleri orijinal taslak kimliklerine çevrilir.
2. Gerçekten gösterilen cümleler izlenir; reddedilmiş veya tekrar diye
   çıkarılmış cümleler kapsam kanıtı sayılmaz.
3. Gerekli cümlesi kaybolan bölüm eksik olur. Global olumlu işaret bunu aşamaz;
   global olumsuz işaret de haritayla otomatik olumluya çevrilmez.
4. Eksik bölüm adları mevcut onarım isteğine verilir. Aynı kaynağın tekrar
   bulunması tek başına tamamlanma sayılmaz.

Kaynak bulunamaması (`uncovered_parts`) ve cümle düzeyinde eksiklik
(`incomplete_parts`) ayrı tutulur. Bu, ifade/bağlantı hatasının otomatik olarak
yeni geniş kaynak aramasına dönüşmesini önler. Kısmi cevap tamamlanmış cevap
önbelleğine giremez.

## Sınırlar

Bu, modelin semantik kararını matematiksel olarak doğrulamaz. Model bir
cümleyi yanlışlıkla iki alt soruya bağlayabilir. Ayrıca planlayıcının tek
başlık içine sakladığı alt talepler bu çok-parçalı kontrolle otomatik olarak
ayrıştırılmaz. Henüz "bütün sorular eksiksiz cevaplanır" denemez.

Eklenmiş testler aynı kaynağın iki soruya kullanılması, elenen cümle, tekrar
filtresi, aday/orijinal kimlik farkı, eksik/bozuk harita ve hedefli onarımı
kapsar. Sahte sağlayıcı testleri akışı doğrular, gerçek Luna kalitesini değil.

Yeni ücretli çağrı, üretim API yeniden başlatması veya korpus değişikliği yok.
Yeni çıktı sözleşmesi gerçek sağlayıcıda henüz bu sürümle sınanmadı.

## Testler

İlgili geniş çevrimdışı paket: **513 geçti, 0 başarısız, 0 atlanan**.
İzole PostgreSQL backend koşusu: **3276 geçti, 0 başarısız, 0 atlanan**,
81,46 saniye. Kanıt: `.local/part-coverage-20261029.xml`.
Test konteyneri koşudan sonra durduruldu; üretim API/veritabanına dokunulmadı.
Tarayıcı/arayüz dosyaları değişmedi; bu adımda yeniden tarayıcı koşusu yok.
