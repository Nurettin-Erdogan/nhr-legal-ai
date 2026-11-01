# Tam test denetimi — 29 Ekim 2026

Kullanıcı bütün testlerin çalıştırılmasını istedi. Canlı API, korpus, veri
çekicileri ve embedding süreçleri değiştirilmedi. Gerçek ücretli model çağrısı
yapılmadı. Testlerin dış ağı süreç düzeyinde engellendi.

## Doğrulanmış sonuçlar

| Paket | Sonuç |
| --- | --- |
| Backend + gerçek izole PostgreSQL | 3193 geçti; 0 başarısız; 0 atlanan |
| Arayüz davranış testleri | 574 geçti; 0 başarısız; 0 atlanan |
| TypeScript | Geçti |
| Üretim derlemesi | Geçti; dağıtım yapılmadı |
| SQL V2 şema denetimi | Geçti; transaction geri alındı |
| SQL V2 güvenlik/RLS denetimi | Geçti; transaction geri alındı |
| SQL V1→V2 yükseltme denetimi | Yeni ayrı `nhr_upgrade_20261029_test` içinde geçti |
| Chromium eklenti testleri | 155 geçti; 0 başarısız; 0 atlanan; 27 dk 36 sn |
| Lint | Başarısız: 14453 hata, 23 uyarı; çoğu biçimlendirme |

Backend koşusu `scripts/run_isolated_acceptance.py` ile yalnız
`127.0.0.1:55439/nhr_legal_ai_test` üzerinde çalıştı. Chromium paketi aynı
koşuda kapalı bırakılıp geçmiş sayılmadı: ayrı süreçte `NHR_BROWSER_TESTS=1`
ile bütün dosya çalıştırıldı. Her sürecin geçici klasörü ayrı.

Nihai toplam: **3348 Python + 574 arayüz = 3922 başarılı davranış testi;
0 başarısız ve 0 atlanan**. Ek 60 testlik stres/sağlayıcı tekrarı da geçti;
tekrarlar bu toplama yeniden eklenmedi. Lint başarılı değildir.

## Düzeltilen test bağımsızlığı

`test_corpus_5302_article_14_reingest_preserves_versions` tekrar kullanılabilen
test DB'sinde önceden bir arşiv sürümü bulunmadığını varsayıyordu. Beklenti
gevşetilmedi: artık önceki kimliklerin korunduğunu, iki sentetik sürümün
eklendiğini ve yeniden aktarımın hiçbir sürümü değiştirmediğini doğruluyor.
Önceden var olan kayıtlar silinmedi. İzole paket yeniden baştan geçti.

İlk denemede ortak `.local/tmp/pytest` klasörüne erişim hatası vardı; yeni,
ayrı basetemp ile yeniden çalıştırıldı. Hatalı ilk koşular başarı sayılmadı.

## Kanıtlar ve sınırlar

- `.local/backend-final-20261029.xml`
- `.local/browser-audit-20261029.xml`
- `.local/lint-audit-20261029.log`

Ağ engelinin kendi saldırgan testi bir gerçek bağlantı girişimini daha ağ
bağlantısı kurulmadan engelledi; bu beklenen test başarısıdır. Gerçek
sağlayıcının hukuki doğruluğu, Hızlı/Dengeli/Yüksek canlı kalite/maliyet farkı,
gerçek UYAP oturumu ve büyük üretim korpusunun gecikmesi bu sentetik testlerden
kanıtlanmış olmaz. Lint borcu otomatik toplu biçimlendirmeyle gizlenmedi.
Chromium koşusunda ek iki ağ girişimi de engellendi; harici portala erişim
başarısı olarak yorumlanmadı. Test için başlatılan izole konteyner denetim
sonunda durduruldu; test verileri tekrar üretim için korundu.
