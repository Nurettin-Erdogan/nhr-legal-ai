# Asistan davranışı: kaynaklı doğal cevap ve takip akışı

24 Ekim 2026. Önceki `assistant-event-provenance-20261024.md` raporuna ek
çalışma. Eski, eksik tarihsel dayanakta erken durma davranışı aşağıdaki açık
referans kapsamıyla genişletildi; tarihsel kesinlik koşulları kaldırılmadı.

## Ürün referansı

[Apilex'in resmî asistan tanıtımı](https://www.apilex.ai/tr/asistan), doğal dille
araştırma, kaynaklı yanıt ve güncel mevzuatı öne çıkarıyor. Bu kamuya açık ürün
akışı referans alındı; sayfa iç mimari, model veya doğrulama algoritması hakkında
teknik kanıt sağlamıyor. İç sistemleri bildiğimiz, ürünlerini kopyaladığımız veya
aynı kalite/hızın garanti edildiği iddia edilmiyor. JurisAI yalnız kendi uygun
doğrulanmış kaynaklarını kullanmaya devam ediyor; araştırılan ürün sayfası
hukuki yanıt kaynağına veya uygulamanın arama araçlarına eklenmedi.

## Değişiklikler

- Açık kullanıcı oranıyla basit kira artışı hesabı artık mevzuat aramıyor.
  Decimal hesabı, yalnız kullanıcı mesajlarındaki tek anlamlı tutarla yapılır;
  para birimi tahmin edilmez. Sonuç `application/declared-percentage-v1`,
  `conversation`, `grounded=false` olarak sunulur; yasal tavan veya hak değildir.
  Hukuki uygunluk, birleşik faiz, birden fazla tutar/oran, özel belge kapsamı ve
  belirsiz ifadeler bu kısa yola girmez. Sohbet sahipliği önce denetlenir.
- Dönemi/türü belirsiz genel kira tavanı sorusu yalnız gerekli nötr girdileri
  sorar. Bilinen ay ve kira türü yeniden istenmez. `20000` kira bedelinin `2000`
  yılı sanılması düzeltildi; yıl taraması sözcük sınırı ve para birimini dikkate alır.
- Sondaki yalnız sunum amaçlı “kısa ve anlaşılır anlat” ifadesi, “ve” içerdiği
  için ikinci hukuk konusu sanılmıyor. Tarih, ayrı hukuk konusu ve açık kanun
  referansı silinmez; özgün kullanıcı metni üretimde korunur.
- Kaynaktaki ana kural, mevcut doğrulanmış konu ipucunun gerçek metindeki
  karşılığıyla yazıcıya gösterilir. Genel eylem/hak sorusunda ana kuralın
  dayanağı elenip yalnız yardımcı süre kalırsa cevap tamamlanmış sayılmaz.
  İpucu bir hukuk kanıtı değildir; gerçek kaynakta yoksa kural eklenmez.
- Türkçe olumsuz ortaç/ulaç ve koşul eklerinin (`uymayan`, `ödemezse` gibi)
  yanlış pozitif/koşulsuz sayılması düzeltildi. “Geçemez” ile “üst sınırdır”
  biçimindeki aynı tavanın farklı dilbilgisel anlatımı ayrıca yasak sanılmıyor;
  sayı, maksimum, diğer olumsuzluk/koşullar ve bağımsız anlam denetimi korunuyor.
  Koşullu ödeme kuralı, gerçek kullanıcının ödeme yaptığının kanıtı olmuyor.
- Bulut yazıcısına yerel modelin üst üste binen uzun talimatları yerine daha
  kısa bir kaynak/kanıt sözleşmesi veriliyor. Her hukuki iddia hâlâ tam kaynak
  birimleriyle, mekanik sayı/kapsam kontrolleriyle ve bağımsız denetçiyle doğrulanır.
  Hatalı taslak için somut ret kategorileriyle bir sınırlı düzeltme denenir.
- Geçmiş olayın gerekli sürümleri bulunamadığında mevcut doğrulanmış madde
  referansları sınırlı, salt okunur sorguyla getirilebilir. Bunlar yalnız açıkça
  etiketlenmiş genel açıklamadır; eksik tarihsel dayanak tamamlandı sayılmaz.
  Gerekli maddelerden biri eksikken diğerinin geçerli tarih aralığı bulunması da
  kesin geçmiş hak/tutar doğrulaması yapamaz. Kesin toplam ödeme hesaplanmaz.

## Son kontroller

- Python: **2277 geçti, 440 atlandı**, bir bağımlılık deprecation uyarısı.
- Web: **566 geçti**, sıfır başarısız/atlanan; TypeScript kontrolü başarılı.
- `git diff --check`: temiz.
- Yalnız proje API'si yeniden açıldı: `127.0.0.1:8766`, health 200.

Son izole canlı model/korpus kontrolleri:

| Örnek | Gözlem |
| --- | --- |
| Kiracı kirayı ödemezse ne yapılabilir? Kısa ve anlaşılır anlat. | 22,24 sn; `openrouter/deepseek/deepseek-v4-flash`, doğal kısa cevap, `grounded=true`, TBK 315; sentez `accepted/legal` |
| Kira artışı en fazla ne kadar olabilir? | 0,00 sn yuvarlatılmış; yalnız yenileme ay/yıl ve kira türü soruldu, kanun dökülmedi |
| 20.000 TL kira %20 artışla kaç olur? | 0,00 sn yuvarlatılmış; 24.000 TL ve 4.000 TL artış; mevzuat/model çağrısı yok |
| İzin verilen üç turlu geçmiş işten ayrılma örneği | 11,29 sn; kullanıcı olguları korundu; mevcut 1475/14 ve 4857/17 destekli açıklama gösterildi; tarihsel kesin hak/ödeme olmadığı açıkça belirtildi |

Son satır, yazıcı talimatının son kısaltılmasından önce ölçüldü; kapsam korumaları
değişmedi. Bu süreçlerde geçmiş yalnız test sürecinde sağlandı; gerçek sohbet
kaydı değiştirilmedi. Bunlar oturumlu tarayıcı/RLS kalıcılık kabul testinin yerine
geçmez. Gerçek serviste oturumsuz isteklerin 401 alması erişim korumasıdır.

## Açık sınırlar

Ara koşularda bazı taslaklar hâlâ elendi veya alıntı yoluna döndü; genel hız
iyileşmesi ya da her soruda aynı kalitenin garantisi yok. Geniş korpus aramasında
eşzamanlı embedding altında semantik dal zaman aşımı ve kısmi aday sonuçları
görüldü. Eksik dönemsel TÜFE, tazminat tavanı veya tarihsel mevzuat sürümü model
belleğinden tamamlanmıyor. Bir genel hukuki ödeme hesaplayıcısı bu paketle kurulmadı.

Embedding/veri çekici süreçleri, görünür kaynak uygunluğu, şema, gizli bilgiler,
ödeme ayarları ve planlar değiştirilmedi. Başka görevlerin mevcut değişiklikleri
korundu. Commit/push yapılmadı.
