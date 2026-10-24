# Asistan sohbet akışı — 24 Ekim 2026

## Devreye alınan değişiklikler

- Netleştirme soruları hukuki iddia değildir. Açık kişisel işten ayrılma/tutar
  ve kira artışı sorularında eksik olay girdileri, genel kapsamda kaynak araması
  ve model çağrısından önce nötr sunucu sorularıyla toplanır. Bu yanıtlar
  `clarification`, `grounded=false`, `application/dialogue-inputs-v1` olarak
  etiketlenir; kaynaklı hukuk cevabı gibi sunulmaz.
- Özel dava/proje/belge soruları bu genel giriş kısayoluna alınmaz. Mevcut
  sohbetin sahibi ve kapsamı, kısayoldan önce de kontrol edilir.
- Sunucunun netleştirme olarak kaydettiği soru sonraki tura taşınır. Önceki
  yetersizlik ve sosyal cevaplar hukuki bağlam/evidence yapılmaz. Son kullanıcı
  ifadeleri ayrı bağlam olarak tutulur; asistanın veya başka bir karardaki
  örnek kişinin ücret/tarihleri kullanıcı olgusu sayılamaz.
- Kullanıcı aynı bilgileri birkaç turda verirse kalan alanlar sorulur.
  Brüt/net ayrımı, düzeltme, açık konu/olay değişimi ve bilgi paylaşmayı
  reddetme/bilmeme durumları için regresyonlar eklendi. Otomatik giriş
  kontrolleri sınırlı konuları kapsar; diğer sorular kaynakla denetlenen doğal
  üretim yolunda kalır. Bütün hukuk konularını kapsayan bir form sistemi değildir.
- Açık giriş yanıtı, eski kullanıcı sorusuyla birleştirilerek aramaya taşınır;
  bunun için ek modelle yeniden yazım gerekmeyebilir. Daha fazla kullanıcı
  turu okunur; yazıcıya geçmiş, hukuki kanıt olarak değil olay bağlamı olarak
  gönderilir.
- Günlük işten çıkarılma anlatımları için mevcut iş hukuku madde adayları ve
  arama terimleri kullanılır. Bu eşleme hak kazanma kararı değildir; maddeler
  yine doğrulanmış korpustan getirilir ve cevap ayrıca denetlenir.
- Hukuki anlam içermeyen, açık iki sayılı matematik ifadeleri Decimal ile
  hesaplanır. Tarih, para birimli belirsiz metin, hukuki sonuç, yüzde tavanı ve
  formül çıkarımı bu kısayola alınmaz. Bu yol bir tazminat hesaplayıcısı değildir.
- Bulut yazıcının düzgün biçimli bağımsız denetimden ret aldığı taslak, genel
  sohbet profilinde en fazla bir kez yeniden yazılabilir. Eski taslak
  yayımlanmaz; yeni taslak bütün kaynak/sayı/kip/kapsam kapılarından ve yeni bir
  bağımsız onaydan geçmek zorundadır. Onaylanmayan cevap yayımlanmaz.
- Kaynak bulunması ile cevabın doğrulanamaması farklı metinlerle belirtilir.
  Kira artışında eksik dönemsel oran, kullanıcıdan öğrenilecek olay bilgisiyle
  karıştırılmaz. Kaynaklı yazılı bildirim adımı gerçekten anlatılmış genel kira
  cevabına, adımlar hiç anlatılmamış gibi uyarı eklenmez; açık mahkeme/icra
  prosedürü eksikliğine ilişkin uyarı korunur.

## Kontroller

| Kontrol | Sonuç |
| --- | --- |
| Son tam Python koşusu | 2120 geçti, 433 atlandı, 1 bağımlılık deprecation uyarısı |
| Web testleri | 558 geçti |
| TypeScript | Başarılı |
| `git diff --check` | Temiz |
| Son API başlangıcı | Uvicorn `127.0.0.1:8766`, health 200, port çakışması yok |

DB ve tarayıcı opt-in testleri bu koşuda etkinleştirilmedi. Kaydedilmiş gerçek
kullanıcı sohbeti üzerinde yeni test kaydı oluşturulmadı. Sentetik çok turlu
canlı testte geçmiş yalnız test sürecinde sağlandı; gerçek model ve gerçek
doğrulanmış kamu kaynakları kullanıldı. Bu, tüm kalıcılık/RLS/tarayıcı akışlarının
yeniden uçtan uca kabul edildiği anlamına gelmez.

### Son gerçek HTTP kontrolleri

| İstek | Sonuç | Süre |
| --- | --- | ---: |
| İşten çıkarılma / kişisel tutar sorusu | HTTP 200; brüt ücret, giriş–çıkış tarihleri, ayrılma nedeni soruldu; hukuki iddia/atıf yok | 0,02 sn |
| `10 * 40000 kaç eder?` | HTTP 200; `400.000`; uygulama aritmetik yolu, hukuki sonuç değil | 0,01 sn |
| Kiracı kirayı ödemezse ev sahibi ne yapabilir? | HTTP 200; `openrouter / deepseek/deepseek-v4-flash`, `grounded=true`, TBK 315; kısa kaynaklı cevap | 15,34 sn |

Sentetik takip örneklerinde ücret verildikten sonra aynı ücret sorulmadı;
tarih ve ayrılma nedeni istendi. Olay girdileri tamamlanınca gerçek model
getirilen kaynaklara göre başka bir uygulanabilirlik bilgisini sordu. Kira
yenileme dönemi ve konut bilgisi tamamlanınca TBK 344 ile desteklenen kısım
açıklandı; eksik dönemsel oran uydurulmadı.

## Sınırlar ve korunan işler

İlk canlı denemelerde yanlış/eksik kaynak seçimi ve modelin ret alması görüldü;
son başarılı örnekler bütün soruların sorunsuz olduğunun kanıtı değildir.
Geniş taramalı takip örnekleri yaklaşık 47 saniye sürdü. Eşzamanlı embedding
sırasında sorgu vektörü/karar araması zaman aşımı yaşayabilir; bu testler
kalıcı hız veya eksiksizlik garantisi değildir.

Embedding süreçleri, veri çekiciler, veritabanı şeması, korpus görünürlük
kuralları, bulut anahtarları/ödeme ayarları değiştirilmedi. Yalnız API,
kullanıcının aktif işlem olmadığını bildirmesi ve onayıyla yeniden başlatıldı.
Eski cevaplar geriye dönük düzenlenmedi. Önceden mevcut commit edilmemiş
çalışmalar korundu; commit/push yapılmadı.

İzleyen kabul işi: daha geniş konu setinde gerçek model kalite ölçümü,
çok kullanıcılı üretim kuyruğu ve izole DB + tarayıcı testleri. Genel denetimde
belirtilen gizlilik metni, SMTP ve yayın erişim politikası bu paketin konusu
değildir; bunlar hâlâ ayrıca ele alınmalıdır.
