# Kaynaklı cevabı kayıpsız sunma — 2026-10-29

## Uygulanan değişiklikler

1. `free_answer` tekrar filtresi kelime kümelerinin yüzde benzerliğini artık
   kullanmıyor. Bütün kelimeler, kısa kelimeler, sayılar, sayısal yazım ve
   karşılaştırma işaretleri sıralı olarak korunuyor. Yalnız tam token dizisi
   önceki onaylı cümlede bulunduğunda ve kanıt bağları aynı olduğunda tekrar
   bastırılıyor. Farklı kanıtla aynı sözcükler ayrı kalıyor.
2. Gerçek tekrarın kapsam kaydı, kaldırılmış kimliği başarı diye saymak yerine
   aynı kanıtlı, zaten gösterilen cümle kimliğine bağlanıyor. Eşleşme yalnız
   kaynak denetiminden geçen cümlelerde oluşturuluyor. Gösterilmeyen veya
   reddedilen hedef kapsamı tamamlayamaz. Negatif testler korunuyor.
3. Bağımsız denetçi talimatında gerekli/yeterli koşul ayrımı açıklandı.
   Kaynak bir koşulu açıkça zorunlu kılıyorsa, o koşulun yokluğunun yalnız
   belirtilen yolu kapattığı açıklama sırf olumsuz cümle kaynakta aynen
   yazılmıyor diye reddedilmemeli. Başka yolları kapatma, koşuldan otomatik hak
   çıkarma, istisna atlama yine yasak. Bu bir prompt iyileştirmesidir;
   gerçek modelin yanlış retlerinin tamamen bittiği henüz kanıtlanmadı.
4. Yerel doğrudan madde erişiminin kapsam izni internet araştırmasının aç/kapa
   ayarından ayrıldı. Genel/güncel soru yerel hızlı yola internet kapalıyken de
   girebilir. İnternet çağrısı hâlâ kendi ayarıyla kapalı kalır. Özel/tarihsel
   kapsam kısıtları değişmedi. Eksik parçalar geniş aramaya devam eder.
5. Asistan çekirdeğinde kullanılmayan değişken/ithalatlar kaldırıldı;
   routes içindeki geriye uyumlu `_embed_question` dışa aktarımı korundu.
6. AuthProvider callback bağımlılıkları, hata sınırının Error nesnesi,
   müvekkil adı filtresi, belge arama bağımlılıkları, takvim tarih hesabı ve
   iki cleanup/ref kullanımı düzenlendi. Genel biçimlendirme veya kural
   susturma yoluyla bütün depo temiz gösterilmedi.

## Hızın kanıtı ve sınırları

Kaydedilmiş son canlı koşuda parça aramaları 3,7–31,7 sn, yazım/denetim
12,8–17,8 sn civarındaydı (idare örneği yazım/denetim 8,9 sn).
Koşu internetsiz olduğu için yerel hızlı yolun da yanlışlıkla kapanması
özellikle bu ölçümde ağır aramayı tetikliyordu. Üretimde internet açıkken
aynı kazancın tekrar elde edileceği iddia edilmez.

Yeni deterministik regresyon, gerçek tekrar nedeniyle fazladan yazım/denetim
turu yapılmadığını gösteriyor: bir yazıcı ve bir denetçi çağrısıyla tamamlanıyor.
Bu, gerçek Luna'nın 10 saniyeye indiğinin kanıtı değildir. Yeni ücretli çağrı
yapılmadı; önceki 0,010826680 USD harcama tekrar edilmedi.

## Kontroller

- İlk tüm backend koşusu: 3298 geçti, 0 başarısız, 0 atlanan.
- Kaynak bağları için ek test sonrası son tam koşu: **3299 geçti,
  0 başarısız, 0 atlanan**, 85,63 sn. XML: `.local/lossless-final-full-20261029.xml`.
- 574 arayüz testi geçti; TypeScript ve üretim derlemesi çıkış 0.
- `ruff check api/ai` ve değişen dedup/kapsam testleri temiz.
- Genel Python depo raporunda 291 bulgu kaldı (önce 297); otomatik toplu
  düzenleme yapılmadı. ESLint 0 hata, 15 Fast Refresh uyarısı (önce 23).
- 155 gerçek Chromium/sentetik portal testi önceki kontrol turunda geçti;
  bu değişiklikler UYAP uzantısını değiştirmedi, paket bu tur yeniden koşulmadı.

## Dağıtım

Kullanıcı aktif işlem olmadığını onayladı. API yeniden başlatıldı, sağlık 200
ve Uvicorn 127.0.0.1:8766 doğrulandı. Son kaynak-bağı korumasını içeren
3299 testi geçen sürümle yeniden başlatma tamamlandı; sağlık yanıtı 200.
Embedding, üretim veritabanı, veri işçileri, sağlayıcı modeli ve `.env` değişmedi.

Kanıt dosyaları `.local/lossless-*20261029*` altında. Her test sonucu kendi
koşusuna aittir; eski tarayıcı sonucu yeni frontend görsel testi diye sunulmaz.
