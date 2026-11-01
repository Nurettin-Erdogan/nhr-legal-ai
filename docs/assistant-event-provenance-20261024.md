# Asistan: kullanıcı olgusu, hesap ve hukuki dayanağın ayrılması

24 Ekim 2026. Bu çalışma, `assistant-dialogue-20261024.md` raporundan sonraki
kişisel işten ayrılma/tutar örneğinin incelenmesini ve API'ye uygulanmasını kaydeder.

## Kök neden ve değişiklikler

- Kullanıcının ücret/tarih beyanı, mevzuattan kanıtlanacak bir hukuk kuralı değildir.
  `user_facts` bunları tipli alanlar ve özgün metin aralıklarıyla toplar. Modelin
  önceki cevabındaki sayılar kullanıcı beyanı sayılmaz. Takvim farkı bağımsız
  hesaplanır; hukuken dikkate alınacak hizmet süresi veya tazminat sayılmaz.
- Konu araması ile olay girdileri ayrıdır. Ücret veya tarih içindeki rakamlar
  kanun numarası olarak aramaya verilmez. Önceki kullanıcı beyanları takip
  mesajında korunur; açık düzeltme/konu değişimi kuralları uygulanır.
- Hukuki iddiaların alıntı, sayı ve bağımsız anlam doğrulaması korunur. Kullanıcı
  olguları bu kontrollerin kanıt listesine eklenmez. Özel belge/dava/proje
  kapsamının buluta gönderilmemesi kuralı değişmedi.
- Tamamlanmış geçmiş tarihli kişisel olayda, bilinen madde adayları önce olay
  tarihine göre sınırlı ve salt okunur sorgulanır. Güncel metnin derlenme/sürüm
  tarihi geçmişte yürürlükte olduğunu kanıtlamaz. Eksik sonuç bütün korpusta
  kayıt bulunmadığı iddiasına dönüştürülmez.
- Tarihsel uygulanabilirlik gösterilemediyse kullanıcı olguları ve eksik olan
  dayanak açıkça anlatılır. Modeli tekrar sorgulamak veya uzun güncel maddeyi
  aynen dökmek bu eksikliği onarmaz; bu yedek yollar kişisel olayda kullanılmaz.
- Tek mesajdaki “çıkış parası” hedefinin, araya ücret ve başka sözcükler girdikten
  sonra gelen tarihi yanlışlıkla çıkış tarihi olarak etiketlemesi giderildi.
  Gerçek bitiş/giriş tarihi etiketleri sıra dışı yazılışta da korunur.
- Doğal taslakta önce bir destek kusuru, daha sonra bir cümle/biçim kusuru varsa
  düzeltme isteği artık iki kusuru da bildirir. Önceden ilk kusurun bilgisi
  kayboluyor ve tek düzeltme denemesi yalnız biçimi düzeltebiliyordu. Atomik
  iddia, sayı, anlam ve kaynak denetimleri gevşetilmedi; ek sınırsız deneme yok.

## Son doğrulamalar

- Son tam çevrimdışı Python paketi: **2228 geçti, 440 atlandı, 1 bağımlılık uyarısı**.
  Ara koşularda eşzamanlı değişen giriş/oturum testlerinde hatalar vardı;
  son koşuda bunlar da geçti. Bu çalışmada ilgili giriş dosyaları değiştirilmedi.
- Hedefli olgu/olay/sentez/yönlendirme paketi: **324 geçti**.
- `git diff --check`: temiz.
- Kullanıcı onayıyla yalnız `127.0.0.1:8766` API yeniden açıldı: health 200,
  Uvicorn başlangıcı doğrulandı, başlangıç günlüğünde `WinError 10048` yok.
  Yerel yeniden başlatma betiğinin süreç filtresi proje ve 8766 portuyla
  sınırlandı; ayrı 8767 süreci kapsam dışı bırakıldı.
- Gerçek HTTP selamlama: 200, doğal kısa cevap, 0,02 saniye.
- Ücret ve tarihlerin tek mesajda verildiği HTTP örneği: 200, 0,07 saniye,
  `application/event-scope-v1`, `insufficient_sources`, `grounded=false`.
  Beyanları ve takvim farkını gösterdi, tarihsel dayanak/hesap sınırlarının
  doğrulanmadığını açıkladı; kesin ödeme veya sahte atıf üretmedi.
- Genel kira sorusunda bağlantı `openrouter/deepseek/deepseek-v4-flash` ve
  TBK 315 ile `grounded=true` doğrulandı. İlk HTTP örneği 26,59 saniyede
  madde alıntısına döndü; bu doğal açıklama başarısı sayılmadı. Ret şeması
  incelenip yukarıdaki düzeltme geri bildirimi eklendi. Son izole model/pipeline
  koşusunda doğal açıklama, bütün denetimlerden geçerek `accepted/legal` oldu;
  biçim düzeltmesi ve bağımsız anlam düzeltmesi gerekti. Tek örnek tutarlılık
  veya sürekli düşük gecikme garantisi değildir.

Çalışma sırasında ayrı oturum/erişim listesi değişiklikleri de uygulandı.
Son oturumsuz HTTP tekrarının 401 dönmesi beklenen erişim korumasıdır; bu
koruma değiştirilmedi. Bu nedenle son doğal cevap kabulü izole pipeline
sürecinde yapıldı, oturumlu tarayıcı üzerinden yeniden doğrulanmadı.

Üç turlu aynı örnek önceki izole canlı süreçte sınandı; geçmiş yalnız test
sürecinde sağlandı. Gerçek kayıtlı sohbet değiştirilmedi. Son HTTP kontrolü
tek mesaj üzerinden yapıldı; bu, oturumlu sohbet kalıcılığı/RLS/tarayıcı kabul
testi değildir. Opt-in DB/tarayıcı testleri etkinleştirilmedi.

## Açık sınır ve sonraki iş

Bu bir genel kıdem/ihbar/net ödeme hesaplayıcısı değildir. Tarihsel örnekte
gerekli döneme uygulanabilir mevzuat sürümü ve dönemsel tavan/hesap parametreleri
getirilen doğrulanmış kaynaklarla sağlanamadı. Kesin hukuki tutar üretmek için
bu verilerin iç korpusta doğrulanması ve izlenebilir hukuk hesabı uygulanması
gerekir; model belleğinden veya internetten gizlice tamamlanmadı.

Embedding/çekici süreçleri, korpus görünürlük kuralları, veritabanı şeması,
anahtarlar, bakiye/ödeme ayarları değiştirilmedi. Commit veya push yapılmadı.
