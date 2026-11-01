# Normal sohbet hız turu — 28 Ekim 2026

Bu tur yalnız normal sohbet gecikmesini ele alır. Ekran görüntülerindeki cevap
kapsamı eksiklerinin bütünüyle çözüldüğü veya sistemin kusursuz olduğu iddiası yoktur.
Mevcut kirli çalışma ağacı korunmuştur; model, `.env`, kredi limiti, veri/embedding
işçileri veya resmî portalların hız sınırları değiştirilmedi.

## Değişiklikler

1. Çok parçalı, güncel ve genel sorularda tam/doğrulanmış yerel madde adayları
   bulunabiliyorsa ilk geniş korpus araması yerine geçici başlangıç havuzu kurulur.
   Bu bir kapsam garantisi değildir. Sonraki parça planı, kaynak araması ve bağımsız
   denetçi aynen çalışır. Kaynağı bulunmayan parça geniş aramaya gider.
2. Özel belge/dava/proje, tarihsel soru, açık karar talebi ve tek maddelik basit
   sorular bu geçici havuz yoluna alınmaz. Tam arama zorlandığında da yol atlanır.
3. Kaynağı zaten mevcut ifadenin düzeltilmesi ile gerçekten eksik kaynak ayrılır.
   Boş parça bağları ve açık `kaynak_eksik:` denetim tanısı yeni arama açabilir;
   sırf bir koşulun yanlış anlatılması her elenen cümle için yeni arama başlatmaz.
   Tanı etiketi onay/kanıt değildir; revize cevap aynı denetimlerden geçer.
4. OpenRouter'ın eski DeepSeek/Azure JSON istisnası OpenAI modellerine yayılmıyor.
   Seçili `openai/gpt-6-luna` kataloğunda `response_format` ve `structured_outputs`
   desteği salt okunur kontrol edildi. Planlayıcı JSON nesnesi; denetçi mevcut dört
   üst alanlı protokolü zorlayan JSON şeması ister. Normal cevabın yazımı düz metin
   olarak kalır. Parametreleri destekleyen uç noktalar istenir.
   Sayı/alıntı/kapsam kontrolleri ve yanlış/olumsuz denetim sonucunu reddetme değişmez.
   Şemalı çıktı hukuki doğruluk garantisi değildir.

JSON protokolü OpenAI Docs'un [yapılandırılmış çıktı rehberi](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat)
temel alınarak düzenlendi. Şema yalnız biçimi denetler; sunucu doğrulamasının yerini almaz.

## Ölçüm ve sınırlar

Gerçek PostgreSQL + mevcut OpenRouter/Luna kullanılarak sentetik genel soruda
doğrudan `execute_answer` ölçüldü. HTTP oturumu, tarayıcı çizimi ve kaydedilmiş
sohbet yazımı ölçüme dahil değildir.

| Aşama | Önceki kontrollü koşu | Son kontrollü koşu |
| --- | ---: | ---: |
| İlk aday kaynaklara ulaşma | 5,33 sn | 0,10 sn |
| İlk retrieval süresi | 5.016 ms | 78 ms |
| Soru embedding süresi | 287 ms | 0 ms (mevcut maddelerle başlandı) |
| Toplam süre | 15,84 sn (tek yazım denemesi) | 21,59 sn (iki yazım denemesi) |

İlk hazırlık aşaması hızlandı; toplam sürenin aynı oranda iyileştiği söylenemez.
Ara sürümlerde aynı soru 32,16 ve 24,48 saniyede, farklı/eksik cevaplarla döndü.
Son koşuda `provider=openrouter`, `model=openai/gpt-6-luna`, `grounded=true`,
`coverage_preserved=true` ve atıflar 4857/18 ile 4857/20 idi. Bu bayraklar tek
başına bütün koşul/istisnaların doğru ve eksiksiz anlatıldığını kanıtlamaz.
Kalan toplam gecikmenin büyük kısmı planlama + yazım/bağımsız denetim/revizyondur.
10 saniye üst sınırı veya tüm soru dağılımı için p95 garantisi verilmedi.

## Testler

Son standart backend koşusu: **2900 geçti, 443 atlandı, 0 başarısız**, 1 mevcut
Starlette/httpx kullanımdan kaldırma uyarısı. Atlananlar tamamlanmış sayılmıyor;
izole test veritabanı, tarayıcı veya ayrıca etkinleştirme isteyen testlerdir.

Yeni kontroller: özel/tarihsel kaynak izolasyonu, yanlış/eksik/doğrulanmamış
başlangıç maddesi reddi, eksik alt soru için geniş aramanın korunması,
ifade revizyonunda gereksiz arama yapılmaması, kaynak eksikliğinde aramanın
açılması ve JSON şemasının olumsuz denetim sonucuna da izin vermesi.
