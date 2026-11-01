# Açık kontrollerin yeniden koşusu — 2026-10-29

Kullanıcı bu tur en fazla 0,05 USD canlı ölçüm ve boş API'nin yeniden
başlatılmasını onayladı. Kart, bakiye, otomatik yükleme ve `.env` değişmedi.

## Arayüz ve lint

- Arayüz: 574 geçti, 0 başarısız, 0 atlanan.
- TypeScript: çıkış 0.
- ESLint: 0 hata, 23 uyarı. Eksik Hook bağımlılıkları, cleanup/ref ve
  Fast Refresh uyarıları var; temiz sonuç diye sunulmaz.
- Üretim derlemesi: ikinci doğrulama komutu çıkış 0. İlk PowerShell
  yönlendirmesinde stderr uyarısı `NativeCommandError` olarak işaretlendi;
  `cmd /c` ile tekrar doğrulandı, uyarılar gizlenmedi.
- Ruff 0.14.3 yalnız `.local/qa-tools` içine kuruldu. `api ingestion scripts
  tests` üzerinde varsayılan kurallarla **297 bulgu**: E402 96, E701 69,
  E702 42, F811 41, F401 35, F841 6, E741 3, E401 3, F541 2.
  Otomatik düzeltme veya kural susturma yapılmadı. F811 sonuçları test
  fixture ithalatlarıyla aynı adlı parametrelerden geliyor; bu rapor
  test fonksiyonlarının üzerine yazıldığını göstermiyor.
- Son değişen `free_answer.py`: kullanılmayan `dataclasses.replace` ve
  `mapping` değişkeni. Lint bulguları canlı cevap eksikliğinin kanıtı değildir.

## Gerçek Luna ölçümü

Mevcut `scripts/assistant_eval.py`, low düşünme düzeyi, sentetik genel hukuk
soruları, yalnız bu test için 4096 çıktı token tavanı. Üretim ayarları değişmedi.
Resmî web ingestion bu ayrı test sürecinde kapalı, mevcut gerçek korpus okunuyor;
sohbet kaydı yazılmıyor. Bu nedenle HTTP/UI veya canlı internet araştırması
uçtan uca performansı değildir. Aynı sırada sentetik Chromium paketi çalışıyordu;
ölçüm kontrollü donanım benchmark'ı değildir.

| Soru | Toplam sn | Ücretli çağrı | Bu çağrıların HTTP süresi | Maliyet USD | Kısmi |
| --- | ---: | ---: | ---: | ---: | --- |
| İşe iade | 54,214 | 5 | 21,870 | 0,003826005 | Evet |
| İcra | 38,980 | 5 | 20,394 | 0,003867485 | Evet |
| İdare | 33,691 | 3 | 11,401 | 0,001636430 | Hayır |
| Yıllık izin | 20,288 | 5 | 16,394 | 0,001496760 | Evet |

Toplam **0,010826680 USD**, 18 çağrı, 4 tamamlanmış cevap; bütçe aşılmadı.
Dört cevapta otomatik kaynak kontrolleri geçti. Bu, hukuki doğruluk veya bütün
alt taleplerin eksiksiz karşılandığı garantisi değildir. Yeni ücretli çağrı yok.

### Somut bulgular

İşe iade ve izinde semantik denetçi alt parça kapsamını tam işaretlemişken,
onaylı cümlelerin sonraki tekrar filtresinde çıkarılması final kapsamını
eksiltiyor (sırasıyla 2 ve 1 cümle). Bu nedenle yalnız kaynak bulmayı düzeltmek
yeterli değil. Kaybolan cümlenin gerçek tekrar mı ek koşul mu olduğu ayrı
kanıtlanmalı; eksiklik bayrağı körlemesine kaldırılmamalı.

İcrada bazı doğal çıkarımlar denetçide reddediliyor; son cevap alternatif yolun
süresini tam vermiyor. İzin cevabı süre dilimlerini artık aktarıyor; yine de
kapsam filtresinde açık sorun var. Dört ölçüm de 10 saniye hedefini geçiyor.
Ücretli HTTP süreleri toplam sürenin tamamını açıklamıyor; kalan süreyi doğrudan
"model yavaş" diye adlandırmak doğru değil. Ertelenmiş arama/yerel aşamaların
daha ayrıntılı zamanlaması gerekiyor.

## Dağıtım ve kanıt

API yeni süreçle başlatıldı; sağlık 200 ve Uvicorn 127.0.0.1:8766 satırı
doğrulandı. Yeni model/veritabanı işçisi başlatılmadı. Kod değişikliği yapılmadı.

- `.local/recheck-assistant-live-20261029.json`
- `.local/recheck-python-lint-20261029.json`
- `.local/recheck-web-tests-20261029.log`
- `.local/recheck-web-lint-20261029.log`
- `.local/recheck-web-types-20261029.log`
- `.local/recheck-web-build-confirm-20261029.log`

Tarayıcı paketi: ilk kısıtlı süreç başlangıçta takıldı, yalnız doğrulanmış test
süreç ağacı kapatıldı. Gerekli süreç izniyle aynı 155 test yeniden başlatıldı;
sonuç henüz bekleniyor, tamamlanmış sayılmıyor.
