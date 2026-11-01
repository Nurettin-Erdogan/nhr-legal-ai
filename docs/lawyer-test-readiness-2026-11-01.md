# Avukat pilot testi öncesi durum — 2026-11-01

## Bu tur doğrulananlar

- API `/health`: HTTP 200, `database=connected`.
- `/api/ai/status`: `provider=bedrock`, `model=deepseek.v3.2`,
  `configured=true`, `embedding_model=nomic-embed-text`, `semantic_search_ready=true`.
  Bunlar yapılandırma/hazırlık kontrolleridir; ücretli çıkarım yapılmadı.
- Arayüz: 598 test geçti; başarısız, atlanan ve iptal edilen yok.
- TypeScript kontrolü ve ESLint başarılı; üretim derlemesi başarılı.
- İzole 55439 veritabanında seçilmiş backend paketi: 277 geçti, atlanan yok.
  Bedrock yönlendirme, free-answer, paralel retrieval, capped-official-tier,
  büro asistanı/review, office validation ve UYAP alan testleri çalıştırıldı.
  Dış ağ bariyeri aktif; gerçek ağ çağrısı girişimi 0.
- Önceki `test_search_reports_partial_when_the_official_tier_is_capped`
  hatası bu seçilmiş tekrar koşusunda tekrar oluşmadı.
- Ana sayfa, `/auth`, asistan, davalar, UYAP, büro asistanı, mevzuat,
  belgeler, işler ve müvekkiller adresleri HTTP 200 döndü.
  Bu, oturum açmış kullanıcıyla etkileşimli ekran testi değildir.
- Oturumsuz hukuk araması ve büro asistanı API istekleri 401 ile reddedildi.
- Canlı erişim modu salt okunur sorguda `allowlist`.
- `git diff --check` başarılı. Kaynak kodu değiştirilmedi; yeniden başlatma yapılmadı.
- Yalnız bu kontrol için açılan mevcut izole test konteyneri yeniden durduruldu.

## Açık kalanlar / sınırlar

- Tam backend ve gerçek Chromium UYAP paketi bu tur yeniden çalıştırılmadı.
  Önceki tam sentetik UYAP koşusunda 4 köprü zaman aşımı vardı; tekil tekrarların
  geçmesi tam paket başarısı değildir (bkz. `qa-bureau-2026-11-01.md`).
- Gerçek Bedrock cevap kalitesi, bütün alt soruların karşılanması ve cevap
  gecikmesi bu ücretsiz koşuda doğrulanmadı; `/status` kimlik bilgilerinin
  sağlayıcı tarafından kabul edildiğini kanıtlamaz.
- Mevcut tarayıcı oturumunun görsel kontrolü yapılamadı: native helper kernel
  assets hatası ve browser access host unavailable. Kullanıcı oturumu atlatılmadı.
- Son veri denetimi kayıtları mevzuat kapsamı, metin ve embedding eksikleri
  bildiriyor. Bunlar bu tur yeniden sayılmadı; korpusun eksiksizliği iddia edilmez.
  `embed_progress.json` eski (20 Eylül); güncel ilerleme kanıtı olarak kullanılmaz.
- Aktif embedding yükü son ölçümde CPU %86 ve yaklaşık 3 GiB boş RAM bıraktı;
  avukat testindeki hız gözlemini etkileyebilir. İşçiler değiştirilmedi.
- `localhost` yalnız test eden kişinin kendi bilgisayarını gösterir. Uzak pilot
  için güvenli yayımlanmış adres ve erişim listesi kontrolü gerekir; bu taramada
  tünel, port veya yeni erişim açılmadı.

## Sonuç

Kontrollü avukat geri bildirimi/pilot testi yapılabilir; tamamlanmış ve tüm
senaryolarda doğrulanmış ticari sürüm olarak sunulmamalı. Test hesabı ve erişim
adresi netleştirilmeli; hukuki doğruluk, kaynak uygunluğu, takip soruları ve
cevap süresi ayrı kaydedilmelidir. Pilot için gerçek müvekkil verisi yerine
sentetik veya anonim örnek tercih edilmeli.
