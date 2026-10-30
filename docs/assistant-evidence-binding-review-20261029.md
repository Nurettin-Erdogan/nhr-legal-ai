# 2. adım — Ret cümlesi ile gerçek kanıt biriminin eşleştirilmesi

## Bu adımın sınırı

Yeni API/LLM çağrısı, veri sorgusu, üretim dosyası değişikliği veya yeniden
başlatma yok. `scripts/diagnose_claim_evidence.py`, açıkça verilen yerel test
fixture'ını mevcut mekanik denetimden geçirir. Kaynak metni/kimliği/sürümü/
hash'i ve gerçekten bağlanan birimler görünür; geçiş sonucu bilerek
`requires_semantic_review` olur. Araç kendi başına resmîlik veya hukuki
doğruluk onayı üretmez.

## Tekrar üretilebilen ayrım

Kaydedilmiş izin cevabındaki gözlem: “bu asgari sürelerden 4 gün artırılır”
cümlesi `minimum_added` nedeniyle elenmişti. Bağlandığı birimler artırım ve
sözleşmeyle artırma birimleriydi; asgari hizmet süresini kuran birim bağlanmamıştı.

Tam eski model isteği elimizde olmadığından test, bu yapıyı **minimal sentetik
reprodüksiyon** olarak sabitler; eski isteğin eksiksiz yeniden oynatımı değildir:

1. Birim 1: izin süresinin ondört günden az olamayacağı.
2. Birim 2: yer altı işlerinde süreye dörder gün eklenmesi.
3. Cümle: “Bu asgari izin süreleri dört gün artırılır.”

Yalnız birim 2 bağlanırsa `minimum_added` reddi tekrar üretilir. Birim 1 ve 2
birlikte bağlanırsa mekanik ret kalkar; bağımsız anlam denetimine gönderilmesi
gerekir. Böylece bu belirli hata örüntüsünde ilk düzeltme hedefinin **kanıt
bağlantısı** olduğu gösterildi; bütün minimum retlerinin yanlış olduğu veya
doğal bir metnin otomatik olarak destekli olduğu iddia edilmedi.

## Korunan negatif kontroller

- Kaynak yalnız sabit süre söylerken sonradan “en az” eklemek hâlâ reddedilir.
- Dört gün yerine beş gün yazmak, ek kanıt birimi bağlansa da reddedilir.
- Kaynakta olmayan alıntı uydurmak reddedilir.
- Olmayan birim numarası geçerli kanıt sayılamaz.
- Fixture kaynağının metni/sürümü/kimliği değiştirilmez.

## Buradan sonraki uygulama işi

Onarım modeline yalnız “reddedildi” değil, **eksik bağlanan niteleme** ve
geçerli kanıt birimleri gösterilmeli. Son canlı turda eklenen
`mechanical_findings` / `repair_types` bu geri bildirimi taşımaya başladı;
başarısı henüz yeni canlı koşuyla kanıtlanmış değil. Cümleyi kelime benzerliğiyle
otomatik başka bir kaynağa bağlamak veya `minimum_added` korumasını kaldırmak
uygulanmayacak. Yanlış bağlantı için model düzeltmesi de aynı tam denetimden
geçecek.

Semantik retler için de aynı çiftli fixture gerekli: doğru doğal açıklama ve
aynı metnin yanlış sayı/koşul/özne/süre başlangıcı değiştirilmiş karşı örneği.
Eksiksiz eski kaynak snapshot'ı olmayan kayıtlar “inceleme bekliyor” kalır;
sahte bir onay sağlayıcısıyla eski LLM kararının doğrulandığı söylenmez.

## Test sonucu

Yeni altı fixture testi ve ilgili sayı, onarım, serbest cevap testleri:
**74 geçti, 0 başarısız, 0 atlanan**. Bu yeni araç tüm proje paketinin yeniden
çalıştırıldığı veya canlı modelin düzeldiği anlamına gelmez. Yeni kredi: 0 USD.
