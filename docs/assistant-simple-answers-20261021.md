# Sade sohbet ve kira hesabı — 21.10.2026

## Değişiklik

- Kullanıcı soru balonundaki otomatik, geniş korpus araştırması kaldırıldı.
- Tekrarlanan açıklama metinleri, asistan alt başlığı ve boş kapsamın yazdırdığı
  `0` kaldırıldı. Dayanak, atıflar ve tarama ayrıntıları kapalı `Kaynaklar` içindedir.
- Eksik belge/kısmi arama ve doğrulanamayan cevap uyarıları gizlenmez.
- Soruya odaklı kira hesabı ve eksik girdi akışı `api/ai/practical_answer.py` içindedir.
  `18 bin` gibi tutarlar kullanıcının sorularından okunur; modelin soru yorumundan
  tutar/oran alınmaz. Aritmetik Decimal ile yapılır. Birden çok tutar belirsizdir;
  tarih/kimlik numarası kira sayılmaz. Saf aritmetik sorusunda yalnız sonuç verilir.
- Yasal tavan sorusunda oran uydurulmaz; yenileme dönemi/tür gibi eksik bilgiler
  sorulur. Kullanıcının verdiği yüzde yasal izin olarak onaylanmaz.

## Kaynak ve model güvenliği

Hızlı hesap yolunda getirilen resmî TBK 344 cümleleri aynı `verify_answer`
denetiminden geçer. Doğrulanmamış kaynak, kullanıcı belgesi veya başka maddeler
bu kısa yola sokulmaz. Doğrulanmış tam dayanak kaynaklar bölümünde kalır; hesap
cevabı dil modeli cevabı diye sunulmaz (`provider=calculation`,
`model=decimal+verified-basis-v1`). Normal hukuk soruları mevcut bulut/yerel
model ve kaynak denetimi hattını korur. Eski sohbetler yeniden yazılmaz.

## Bilinen sınır

Güncel/aya özgü TÜİK oranını otomatik getiren entegrasyon bu değişiklikte yoktur.
Bu nedenle bir yenileme ayı söylendiğinde gerçek azami oran kendiliğinden
hesaplanmış sayılmaz. Saf yüzde hesabı ile hukuken uygulanabilecek oran farklı
sonuçlardır. Bu değişiklik bütün hukuk konularının GPT benzeri serbest sentezini
tamamladığımız ya da hukuki doğruluğu garanti ettiğimiz anlamına gelmez.

## Kontrol

- Python: 1705 geçti, 428 ortam bağımlı test atlandı.
- Web: 544 geçti; TypeScript kontrolü ve üretim derlemesi başarılı.
- API yeniden başlatıldı; sağlık 200 / database connected.
- Kaydetmeden sentetik gerçek API isteği: 18 bin kira için oran uydurulmadan
  yenileme ayı/yılı ve tür soruldu; grounded=true, bir kaynak, 7,63 saniye.
- Gerçek Chrome arayüzü: %20 verilen sentetik örnekte 18.000 -> 21.600 TL,
  artış 3.600 TL. Kaynaklar açılıp dayanağa erişim doğrulandı; son görüntü
  `.local/assistant-simple-final-20261021.jpg`. Sentetik test sohbetleri korunur.
- Kullanıcı belgesi silinmedi/gönderilmedi. Commit veya push yapılmadı.
