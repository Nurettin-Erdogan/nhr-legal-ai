# Tam test doğrulaması — 26 Ekim 2026

## Kapsam ve yöntem

Kullanıcının tüm testleri çalıştırma ve bulunan hataları düzeltme isteğiyle, önceki çevrimdışı denetimin atlanan entegrasyon testleri açıldı. Gerçek model sağlayıcıları çağrılmadı; kredi harcanmadı. Canlı API, canlı PostgreSQL ve embedding süreçleri yeniden başlatılmadı veya değiştirilmedi.

Veritabanı için mevcut yerel pgvector 0.8.6/PG16 imajından `nhr-assistant-audit-20261026` adlı ayrı, 768 MiB/1 CPU sınırlı test konteyneri kuruldu. Yalnız 127.0.0.1:55439 portuna açıldı; canlı veri diski bağlanmadı. Şema dosyaları salt okunur bağlandı. `nhr_legal_ai_test` içinde testler çalıştırıldı; ayrı `nhr_upgrade_test` içinde V1 yükseltmesi sınandı. Bu test ortamının erişim yöntemi yalnız izole, geçici test ortamına aittir; üretim yapılandırması değildir.

Tarayıcı testleri kullanıcı Chrome oturumunda değil, ayrı geçici Chromium profilinde çalışır. UYAP alan adları yerel HTTPS fixture sunucusuna yönlenir; harici çıkış çalışmayan yerel proxy ile engellenir. Python ağ engeli yalnız açıkça kaydedilmiş fixture portlarını kabul eder. Test veritabanı URL'si de host/port/veritabanı adı bakımından denetlenir; canlı uygulama portu ve canlı DB portu izin listesinde değildir.

## Bulunan ek hata ve düzeltme

Yeni kurulum şema dizisinde `office_bureau_decisions` tablosunun migration'ı eksikti. Başlangıçta yedi hesap dışa aktarma/UYAP dışa aktarma testi `UndefinedTable` hatası verdi. `database/init/064_bureau_assistant.sql` ile migration 063 yeni kuruluma eklendi. `test_fresh_install_includes_bureau_migration` kalıcı regresyon testi eklendi. Canlı veritabanına migration uygulanmadı.

Korpusa bağımlı bir sürüm-koruma testi, boş test veritabanında 5302 m.14 bulunmadığı için atlanıyordu. Yerel arşivde bulunan tek kayıt yalnız geçici test DB'sine yüklendi; test değiştirilmeden geçti. Bu bir ürün hatası değil, test veri önkoşuludur.

## Doğrulanan sonuçlar

| Kontrol | Sonuç |
| --- | --- |
| Backend, ayrı gerçek PostgreSQL dahil | 2847 geçti; sıfır başarısız, sıfır atlanan; 50,76 sn |
| Arayüz testleri | 568 geçti; sıfır başarısız, sıfır atlanan |
| TypeScript | Başarılı, exit 0 |
| Üretim derlemesi | Başarılı, exit 0; dağıtım yapılmadı |
| SQL V2 şema denetimleri | Başarılı |
| SQL V2 güvenlik denetimleri | Başarılı |
| SQL V1 → V2 yükseltme fixture ve assertions | Başarılı |
| Saldırgan/eşzamanlılık stres paketi tekrarı | Beş ayrı koşuda 21/21 başarılı |
| Chromium UYAP fixture testleri | 155 geçti; sıfır başarısız, sıfır atlanan; 27 dk 53 sn |

**Nihai toplam: 3002 Python + 568 arayüz = 3570 başarılı test; sıfır başarısız, sıfır atlanan.** SQL şema/güvenlik/yükseltme kontrolleri buna ek olarak başarılıdır. Tip kontrolü ve üretim derlemesi de geçti. Test beklentileri gevşetilmedi, başarısız testler silinmedi veya işaretlenerek atlanmadı.

Tarayıcı paketindeki 48.000 evraklı sentetik dosya, 52 MB ek, yarıda kesilen indirme, iptal, paralel aktarım, yanlış dava, oturum/yetki hatası ve kısmen bozuk dosya senaryoları geçti. Uzun hata senaryolarında `faulthandler_timeout=90` tanı amacıyla iş parçacığı dökümleri üretti; bu bir test zaman sınırı değildir. İlgili testler de sonunda başarılı tamamlandı; JUnit XML'de failures/errors/skipped sıfırdır.

Kanıtlar `.local/offline-audit-20261026/` içinde: `backend-db-complete.log/xml`, `frontend-recheck.log`, `typecheck-final.log`, `build-final.log`, `browser.log/xml`.

Veritabanı testlerinden sonra yalnız bu denetim için oluşturulan konteyner durduruldu; canlı konteynerler korundu. Geçici test verisi konteynerde kaldığı için yeniden üretim amacıyla tekrar başlatılabilir. SQL kontrolleri üretim DB'sinde değil bu konteynerde yapıldı.

## Sınırlar

Test başarısı gerçek modelin tüm hukuki soruları doğru yanıtlayacağının garantisi değildir. Gerçek UYAP oturumu, gerçek sağlayıcı üretimi ve gerçek korpusta performans/yük bu ücretsiz testte sınanmadı. Kaynak güvenliği ve test beklentileri gevşetilmedi. Önceki rapordaki lint/biçimlendirme borcu, bu davranışsal testlerden ayrıdır; tüm projeyi otomatik biçimlendirme yapılmadı.
