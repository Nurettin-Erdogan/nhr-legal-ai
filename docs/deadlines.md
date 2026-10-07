# Yasal süre hesabı ve dosya durum özeti (2026-10-06)

Dava sayfasında iki yeni parça: **Süreler** sekmesi ve **UYAP Bilgileri** sekmesinin başındaki **Dosya durumu özeti**.

## Süreler

`web/src/lib/deadlines.ts` süreyi bir **kural tablosu** ve HMK m. 92-93 hesap ilkeleriyle hesaplar; `DeadlineCalculator.tsx` arayüzdür. Sonuç
"Takvime ekle" ile `deadline` türünde, dava bağlantılı, 1 gün önceden hatırlatmalı takvim kaydı olur.

Kural dayanakları 2026-10-06'da uygulamanın kendi resmî mevzuat kaynağından (korpus) metin olarak doğrulandı:

| Kural | Süre | Dayanak |
| --- | --- | --- |
| Cevap dilekçesi | 2 hafta (dava dilekçesinin tebliğinden) | HMK m. 127/1 |
| İstinaf (hukuk) | 2 hafta | HMK m. 345/1 |
| Temyiz (hukuk) | 2 hafta | HMK m. 361/1 |
| İstinaf (ceza) | 2 hafta (gerekçeli hükmün tebliğinden) | CMK m. 273/1 |
| Temyiz (ceza) | 2 hafta | CMK m. 291/1 |
| İşe iade: arabulucu | 1 ay (fesih bildiriminin tebliğinden) | 4857 s. İş K. m. 20/1 |
| İşe iade: dava | 2 hafta (son tutanaktan) | 4857 s. İş K. m. 20/1 |
| Ödeme emrine itiraz | 7 gün | İİK m. 62/1 |
| İcra mahkemesine şikâyet | 7 gün (öğrenmeden) | İİK m. 16/1 |
| Kambiyo takibi: şikâyet / imza itirazı | 5 gün | İİK m. 168/3-4 |

Doğrulama sırasında iki ezber hata yakalandı ve düzeltildi: ceza istinaf/temyiz süresi artık **iki hafta**dır (7 gün / 15 gün değil); İİK 168
kambiyo senedi takibidir, genel itiraz süresi İİK 62'dedir.

**Hesap ilkeleri:** gün sürede tebliğ günü sayılmaz, hafta/ay sürede başladığı güne karşılık gelen gün (ayda yoksa ayın son günü); son gün hafta
sonu/resmî tatile (sabit tatiller + 2025-2027 dinî bayramlar) rastlarsa ilk iş günü (HMK m. 93). **Adli tatil (20 Temmuz–31 Ağustos) otomatik
uygulanmaz:** işin adli tatile tabi olup olmadığı bilinemez; HMK kurallarında HMK m. 104'e göre uzamış tarih ayrıca gösterilir, diğerlerinde uyarı.
CMK/İİK/İş K. kurallarında "kendi süre/tatil hükmünü kontrol edin" uyarısı çıkar. 2025-2027 dışındaki yıllarda bayram tarihi yoktur ve uyarı verilir.

**Güvenlik ilkesi:** hiçbir süre kendiliğinden başlatılmaz. Safahattaki tebligat/ödeme emri/karar kayıtları yalnız tarihi doldurmak için **önerilir**
(safahat tarihi işlem tarihidir, gerçek tebliğ günü olmayabilir); başlangıcı kullanıcı doğrular. Hesap yardımcıdır, hukuki görüş değildir.

Dinî bayram tarihleri (2025-2027) Diyanet takvimine göre elle girildi; resmî takvimle teyit edilmelidir (`HOLIDAY_YEARS`, `RELIGIOUS`).

## Dosya durum özeti

`UYAP Bilgileri` sekmesinin başında `web/src/lib/uyap-case-summary.ts`: dosya bilgileri, UYAP'ın yazdığı Toplam Alacak / Yatan Para / Bakiye Borç,
tahsilat-reddiyat özeti, taraf sayısı ve rol dağılımı, safahat kayıt sayısı + ilk/son tarih + son 5 kayıt + en sık işlem türleri. Yalnız UYAP'ın
yazdığı metin ve kayıt **sayıları** kullanılır; aşama tahmini, tutar toplama ya da yorum yoktur.

Testler: `web/tests/deadlines.test.mjs`, `web/tests/uyap-detail-view.test.mjs`; gerçek tarayıcı denetimi: `.local/check_sureler.py`.
