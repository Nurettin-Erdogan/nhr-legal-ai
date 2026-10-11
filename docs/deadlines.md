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

## Tebliğ mazbatasından başlangıç adayı (2026-10-10)

`api/service_records.py` (`GET /api/office/cases/{case_id}/service-records`), `web/src/lib/service-records.ts`,
`web/src/components/ServiceRecordCandidates.tsx` (Süreler sekmesinde, safahat önerilerinin üstünde).

Safahat tarihi işlem tarihidir; tebliğ gününü **mazbata** yazar. Davanın e-tebliğ mazbatalarındaki satırlar okunur (iki tarih
yazımı vardır: `03/09/2026 10:15` ve `2026-09-03 10:15:07`):

| Satır (mazbatada yazdığı gibi) | Okunan |
| --- | --- |
| "… UETS tarafından teslim alındı." | UETS'in teslim aldığı an |
| "… tebligat alanına (hesabına) başarılı bir şekilde konuldu." | **Muhatabın hesabına ulaştığı gün** |
| "Tebligat, alıcısı tarafından açıldı." | Açıldığı an (varsa) |
| "… mevzuat gereği belirlenen süre sonunda otomatik olarak …" | Mazbatanın yazdığı "yapılmış sayıldı" günü |

- **Yapılmış sayılma günü iki yoldan gelir:** mazbatanın kendi satırı ve hesap (hesaba ulaşma + 5 gün). Tutuyorlarsa tek aday
  sunulur; tutmuyorlarsa **ikisi de** uyarıyla sunulur, biri sessizce seçilmez.
- **Hesap kuralı sabit iddia değildir.** Cümle ("Elektronik yolla tebligat, muhatabın elektronik adresine ulaştığı tarihi
  izleyen beşinci günün sonunda yapılmış sayılır.") korpustaki resmî doğrulanmış Tebligat Kanunu kaydında aynen bulunuyorsa
  uygulanır; bulunmuyorsa gün hesaplanmaz ve arayüz bunu söyler. Atıf kaydın madde numarasından değil metindeki başlıktan
  okunur: korpusta 7201 m. 7 kaydı m. 7 ile m. 7/a'yı birlikte taşır, kural "Madde 7/a" başlığının altındadır.
- Gün hafta sonuna ya da tatile rastlıyorsa bu **söylenir, gün kaydırılmaz** (uygulamayı avukat değerlendirir).
- Aday seçmek yalnız "süre başlangıcı" kutusunu doldurur; hiçbir süre kendiliğinden başlatılmaz.
- Kâğıt mazbata taranmış belgedir, OCR metninden tarih güvenle okunamaz: "tarihi okunamadı" diye **sayılır**, uydurulmaz.
  Yanıt yalnız dava sahibine verilir; başkasının davası ile olmayan dava aynı 404'ü alır.

Gerçek tarayıcıda (uydurma mazbatalarla) doğrulandı: tutan kayıt tek aday, tutmayan kayıt iki aday + uyarı, Cumartesi'ye
rastlayan gün uyarılı; adaya tıklayınca tarih doluyor ve HMK 345 ile son gün doğru hesaplanıyor (08.09.2026 → 22.09.2026).

Gerçek veride (2026-10-10, 25 dava, yalnız sayılar): 176 tebliğ evrakının 79'u e-tebliğ mazbatası olarak okundu; **79'unun
79'unda** mazbatanın yazdığı gün, hesaba ulaşma gününden tam 5 gün sonraydı (hesapla tutuyor). 58'inde "açıldı" satırı da var.
Kalan 97 evrak kâğıt mazbata ya da giden zarftır ("Kapalı Tebligat") ve tarih okunmaz.

Sınırlar: mazbatada hangi evrakın tebliğ edildiği ("BU ZARFTA … VARDIR") yazdığı gibi gösterilir, türü yorumlanmaz. Kâğıt
tebligatta tebliğ günü okunmaz. Aktarım o gün yarıda kaldığı için (968 evrak) hesaptaki mazbataların tamamı ölçülmedi.

## Dosya durum özeti

`UYAP Bilgileri` sekmesinin başında `web/src/lib/uyap-case-summary.ts`: dosya bilgileri, UYAP'ın yazdığı Toplam Alacak / Yatan Para / Bakiye Borç,
tahsilat-reddiyat özeti, taraf sayısı ve rol dağılımı, safahat kayıt sayısı + ilk/son tarih + son 5 kayıt + en sık işlem türleri. Yalnız UYAP'ın
yazdığı metin ve kayıt **sayıları** kullanılır; aşama tahmini, tutar toplama ya da yorum yoktur.

Testler: `web/tests/deadlines.test.mjs`, `web/tests/uyap-detail-view.test.mjs`, `tests/test_service_records.py`,
`web/tests/service-records.test.mjs`; gerçek tarayıcı denetimi: `.local/check_sureler.py`, `.local/check_teblig_adaylari.py`.
