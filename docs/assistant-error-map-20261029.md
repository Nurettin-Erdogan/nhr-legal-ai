# 1. adım — Kayıtlı cevapların hata haritası

29 Ekim 2026. Bu inceleme yeni model çağrısı, internet, veritabanı sorgusu,
API yeniden başlatması veya korpus değişikliği yapmaz. Araç:
`scripts/audit_assistant_runs.py`; makine çıktısı:
`.local/assistant-error-map-20261029.json`.

Beş raporda sekiz tamamlanmış cevap ve tamamlanmış cevaba bağlanmayan altı
çağrı var. Bunlar iki bütçe kesintisinin öncesindeki çağrılardır; ücret
hesabından çıkarılmadı. Eski harcama 0,035362180 USD; bu incelemenin yeni
harcaması 0 USD. Bütün raporların ledger farkı sıfır.

## Katman bazında bulgular

| Bulgu | Somut gözlem | Kanıtın sınırı | Durum / sonraki iş |
| --- | --- | --- | --- |
| Kaynak kabulü | Sekiz cevabın altısında kullanılamayan veya karakter bütçesine girmeyen aday var | Düşen adayın soruyu cevapladığını veya tek gerekli kaynak olduğunu kanıtlamaz | Her gerekli alt sorunun gerçek kanıt birimlerini izlemek gerekli |
| Sayı / birim | İlk icra cevabında iki `number_or_unit` reddi; sonraki tekrarında yok | Aynı model taslağı tekrar üretilmedi; kontrollü karşılaştırma değil | `sen e` birimi için önceki düzeltme ve negatif test mevcut |
| Sayısal niteleme | Son izin cevabında `minimum_added` reddi sürüyor | Yanlış kod reddi mi, yetersiz kaynak birimi bağlantısı mı: rapor tek başına belirleyemez | Ret cümlesi + gerçekten bağlanan birimler birlikte dondurulmalı; minimum koruması kaldırılmamalı |
| Anlam denetimi | Sekiz cevabın sekizinde en az bir semantik ret var | Retlerin hepsi yanlış değildir. Modelin `why` açıklaması tek başına doğruluk kanıtı değildir | Pozitif ve negatif, kaynak-cümle eşli inceleme seti gerekli |
| Ret kimliği | İlk icra kaydında kodun elediği cümle kimliğine semantik gerekçe de bağlı | Eski aday/draft numaralarının karışmasıyla uyumlu | Önceki düzeltme ve regresyon mevcut; bu kayıt yeni kodun çalışması değil |
| Kapsam ölçümü | İzin kaydında `coverage_preserved=true`, `partial_answer=true` | Kapsam ve açılış cümlesinin kaybı farklı ölçülerdir; tek başına mantıksal çelişki kanıtı değil | Nihai metin için alt-soru bazlı kapsam matrisi gerekli |
| Süre | Bir idari cevapta planlama 46,8 sn, çıktı tavanına ulaşan yardımcı çağrı 43,9 sn | Kullanıcı cevabının uzun yazılması değil, planlama gecikmesi | Sonradan eklenen sıkı plan şeması sonraki ayrı çağrıda çalıştı; hız garantisi değil |
| Süre | İlk idari cevapta arama 19,4 sn; işe iadede yazım+denetim 22,8 sn | Her sorunun yavaşlığı aynı katmanda değil | Plan, arama ve denetim ayrı optimizasyon hedefi olmalı |

Bu sayılar düzeltmeler arasında alınmış eski koşuların envanteridir; güncel
kodun başarı oranı veya aynı soruda istatistiksel üstünlük değildir.

## Önce neyi ele alacağız?

1. **Semantik ret / kanıt bağlantısı ayrımı:** Bir cümle, bağlı kaynak birimi,
   tam madde bağlamı, kullanıcı olgusu ve ret gerekçesi birlikte incelenecek.
   Sırf denetçi reddetti diye doğru bilgi kodla zorla geçirilmeyecek; sırf
   kaynak başlığı var diye destek var sayılmayacak.
2. **Nihai kapsam matrisi:** Madde numarasının atıfta bulunması değil,
   sorulan koşul/süre/istisna/yolun gösterilen cümlede açıklanması izlenecek.
3. **Gecikme:** Kaynak doğruluğu korunarak ağır arama ve tekrar zinciri
   ayrı ölçülecek; tüm cevaba birden süre sınırı koyup kesmek çözüm değil.

## Mevcut kayıtlardan neyi tekrar üretemiyoruz?

Kayıtlar bütün yazıcı/denetçi istek gövdelerini veya bütün kaynak metinlerinin
o andaki sürümünü saklamıyor. İstek özetleri, cümle retleri ve bazı künye/
kanıt numaraları var. Dolayısıyla bu araç eski LLM kararını tekrar çalıştırmaz;
**hata sinyallerini deterministik olarak yeniden çıkarır**. Tam kaynak olmadan
bir ret için otomatik “yanlış ret” etiketi üretmek güvenilir değildir.

Sonraki inceleme fixture'larında yalnız sentetik kamu soruları ve sürümü/
hash'i belirli doğrulanmış kamu metni kullanılmalı. Özel sohbet, UYAP belgesi,
istemci başlığı veya anahtar bu değerlendirme özetine taşınmamalı.

## Test

Yeni araç için dokuz test; ilgili eski değerlendirme, onarım ve sayısal
regresyonlarla birlikte **55 geçti, 0 başarısız, 0 atlanan**. Bu turda bütün
proje testleri yeniden çalıştırılmış sayılmaz. Üretim asistan dosyaları ve
çalışan API bu adımda değiştirilmedi.
