# Geçici SSD aktarımı — 28 Ekim 2026

Kullanıcı HDD görünmezken SSD'ye aktarımı açıkça onayladı; daha sonra HDD'ye
taşınacak. Bu değişiklik disk taşıma/silme, bulut kaynağı veya model çağrısı yapmaz.

## Güvenlik ve sınırlar

- Yeni AYM aktarımı `.local/official-data-campaign/raw/aym` altına yönlendirilir.
  Bu yalnız çocuk süreç ayarıdır; `.env` ve diğer çekici yolları değiştirilmez.
- En az 100 GiB SSD boş alanı korunur. Eşik her worker durma kontrolünde
  okunur; iş başlamadan da kontrol edilir. Bir HTTP isteğinin tamamlanması
  kadar gecikme olabilir. Mevcut diğer işlerin disk tüketimini sınırlandırmaz.
- Parti en çok 100 kayıt, kampanya en çok 100 partidir. Her parti mevcut
  worker kilidi ve checkpoint'ini kullanır. Kısmi sonuç, hata, CAPTCHA veya
  boş sonuçta sonraki partiye geçilmez. Otomatik hata yeniden denemesi yoktur.
- Yeni istemcide tüm yönlendirmeler izinli host/public IP/TLS doğrulamasından
  geçer; AYM UDF MIME istisnası yalnız resmî public attachment yoluna açıktır.
- `.local/official-data-campaign/STOP` sonraki güvenli kontrol noktasında durdurur.

## Gerçek durum

İlk 25 AYM kaydının tümü mevcut korpusta bulundu (`unchanged=25`); bunlar
yeni indirilmiş veya tekrar tam metin doğrulanmış kayıt diye sayılmadı.
Ardından mevcut imleçten en çok 10.000 kayıtlık sınırlı keşif/aktarım başlatıldı.
Durum `.local/official-data-campaign/aym-batch.json` içindedir; kampanyanın
başlatılması tüm koleksiyonun tamamlandığı anlamına gelmez.

AYM worker kodu ayrıntılı incelenince beş karar türünü desteklediği doğrulandı:
bireysel başvuru, norm denetimi, siyasi parti, Yüce Divan, yasama dokunulmazlığı.
Bu yüzden önceki 22 koleksiyon/12 eksik adaptör envanteri **25 koleksiyon/
11 eksik adaptör** olarak düzeltildi. Bu bir veri sayısı değil kod yeteneği
envanteridir; her türün canlı kapsamı hâlâ ayrıca uzlaştırılmalıdır.

Mevcut kanun yenileme ve kamu metin/hash taraması ayrı süreçlerde sürer.
Yeni kurumların eksik adaptörleri bunların tamamlanmasıyla otomatik oluşmaz.
