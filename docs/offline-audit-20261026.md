# Ücretsiz çevrimdışı denetim — 26 Ekim 2026

**Güncel devam raporu:** [Tam test doğrulaması](assistant-complete-tests-20261026.md). Bu dosyanın aşağıdaki ilk denetim sonuçları tarihsel kayıttır; sonraki test-veritabanı koşusu ve ek kurulum düzeltmesi devam raporunda yer alır.

## Kullanıcı onayından sonraki düzeltme

İlk denetimden sonra kullanıcı düzeltmeleri istedi. `_fully_approved_ids` artık tüm denetim şemasını, benzersiz/tam kimlik kümesini ve gerçek boolean alanlarını doğrulayan ortak denetimi kullanıyor. Genel bilgi istisnasında serbest model çıktısı yerine yalnız soruyla eşleşen gözden geçirilmiş tanımlardan aynen seçilmiş metin kabul ediliyor; ek cümle, görünmez karakter, farklı konu veya listede olmayan ifade reddediliyor. Bu kısıtlama yalnız kaynaksız kısa tanım istisnasında; kaynaklı hukuki cevap yolunda değil. Liste dışındaki kavramlar için bu istisna model çağrısı yapmıyor.

Sonraki tam çevrimdışı koşu: **2561 geçti, 0 başarısız, 440 atlandı**, 19,40 saniye. Kanıt: `.local/offline-audit-20261026/backend-after-fixes.log` ve `backend-after-fixes.xml`. Aşağıdaki ilk denetim sonuçları tarihsel kanıt olarak korunmuştur. Bu sonuç canlı model başarısını veya atlanan entegrasyon testlerinin geçtiğini göstermez. Çalışan API yeniden başlatılmadı.

## Sonuç

Sistem tamamen sorunsuz olarak değerlendirilemez. Yeni saldırgan regresyon testleri iki doğrulama açığını gösterdi. Bu denetimde üretim davranışı değiştirilmedi; düzeltme gerektiren durumlar başarısız testlerle kaydedildi. Mevcut çalışma ağacı korunmuş, commit veya dağıtım yapılmamıştır.

| Kontrol | Sonuç |
| --- | --- |
| Python test paketi, yeni stres testleri dahil | 2551 geçti, 3 başarısız, 440 atlandı; 23,26 sn |
| Arayüz testleri | 568 geçti, 0 başarısız |
| TypeScript tip kontrolü | Geçti |
| Üretim derlemesi | Geçti; dağıtılmadı |
| Python derleme kontrolü: api, ingestion, scripts | Geçti; list_feedback.py açıklamasında escape uyarısı var |
| git diff --check | Geçti |
| Arayüz lint, tüm kapsam | 14416 hata, 23 uyarı |
| Arayüz lint, yalnız src | 7775 hata, 23 uyarı |
| Canlı yerel API /health | 200, veritabanı bağlı |
| Oturumsuz conversations/projects/documents/account-export | Dördü de 401 |

## Bulunan iki sorun

1. **Denetleyici yanıtında yinelenen cümle kimliği kabul ediliyor.** `api/ai/synthesis.py` içindeki `_fully_approved_ids`, iki cümlelik denetimde aynı kimliğin iki kez gelmesini tümüyle reddetmiyor. Şema uzunluğu doğru görünse de kimliklerin benzersizliği garanti edilmiyor. Yeni test bu bozuk girdinin onay üretebildiğini gösteriyor. Bunun tek başına canlı kullanıcıya yanlış cevap verildiğini kanıtlamadığına dikkat edilmeli.
2. **Genel bilgi çıkışı konu ve anlam bakımından yeterince sınırlandırılmıyor.** `api/ai/general_information.py` filtresi, “TÜFE nedir?” sorusuna sahte sağlayıcı tarafından verilen koşulsuz iş hukuku sonuçlarını kabul edebiliyor. İki farklı ifade aynı açığı gösteriyor. Bunlar gerçek model çağrıları değil, bilerek yanlış hazırlanmış test girdileridir. Sözcük engelleme listesi eşanlamlı ifadeleri kaçırabiliyor; kaynak gerektiren hukuki sonuç ile genel tanım ayrımı güçlendirilmeli.

Üç başarısız test, üç ayrı kök neden değil: bir kimlik doğrulama hatası ve aynı genel-bilgi açığının iki örneğidir. Başarısız testler `tests/test_offline_adversarial_stress.py` dosyasında korunmuştur.

## Zorlama kapsamı

- 2000 rastgele kanun/madde ayrıştırma kombinasyonu.
- 2000 kısaltma, sözcük sınırı ve normalleştirme kontrolü.
- Dört iş parçacığında 1000'er önbellek işlemi; kapasite ve kullanıcı anahtarı ayrımı.
- 500 değişen kaynak kanıtı/önbellek geçerliliği senaryosu.
- 1000 eşzamanlı sahte üretim görevi; dört etkin üretim yuvası sınırı.
- 300 bekleyen görevden 100'ünün iptali; kalanların tamamlanması ve yuvaların geri alınması.
- 500 aşırı uzun istek, boş girdi, bozuk JSON denetimi, karma hukuk/konu dışı soru ve hatalı genel bilgi girdileri.
- Mevcut paketlerde kimlik doğrulama, RAG, atıf, sayısal dayanak, özel belge yönlendirmesi, sohbet, UYAP ayrıştırma/yeniden deneme ve arayüz akışları.

Bunlar gerçek 1000 kullanıcı yük testi veya büyük PostgreSQL üzerinde gecikme ölçümü değildir. Sahte sağlayıcı kullanan deterministik stres testleridir; canlı kullanıcı verisine ve çalışan embedding işlerine yük bindirilmemiştir.

## Kredi ve güvenlik sınırı

Python test süreçlerinde `scripts/offline_guard/sitecustomize.py`, Node süreçlerinde `scripts/offline_guard/node.cjs` ağ engeli etkinleştirildi. Gerçek bulut modeli çağrısı yapılmadı. Python engeli dört bağlantı girişimini durdurdu: biri özellikle engeli sınayan test, üçü test fonksiyonu dışındaki yürütmeden geldi; son üçün kaynağı bu raporda belirlenmiş değildir. İzin verilen tek Python bağlantı istisnası Windows asyncio'nun kendi yerel socketpair mekanizmasıdır.

Canlı API'de yalnız yukarıdaki yerel GET kontrolleri yapıldı; cevap üretme uç noktasına istek gönderilmedi. Anahtar, parola, ödeme ayarı, AWS kaynakları ve çalışan süreçler değiştirilmedi. Veritabanı migration'ı, yeniden başlatma veya veri silme yapılmadı.

## Çalıştırılmayanlar ve sınırlar

- 285 test ayrı test veritabanı gerektiriyor. `NHR_TEST_DATABASE_URL` tanımlanmadı; canlı veritabanı test veritabanı olarak kullanılmadı. Gerçek RLS/SQL bütünlük testleri bu nedenle geçmiş sayılamaz.
- 155 UYAP Chromium testi opt-in. Mevcut fixture yerel HTTPS ve API sunucuları ile ayrı Chromium süreci açıyor; bu süreç kullanılan Python/Node ağ engelinin kapsamı dışında kalacağından bu denetimde etkinleştirilmedi. Çalıştırmak için tarayıcı sürecine de dış ağı kapatan ayrı güvenli test düzeni gerekli. Gerçek UYAP portalı test edilmedi.
- Gerçek model kalitesi, sağlayıcı erişilebilirliği, bakiye ve uçtan uca ücretli üretim doğrulanmadı.
- Lint hataları çoğunlukla biçimlendirme: yalnız src içinde 7756 Prettier, 18 explicit-any ve bir gereksiz escape hatası var. 23 uyarının 15'i React refresh, sekizi hook bağımlılığı. Otomatik düzeltme uygulanmadı; bunlar 7775 çalışma zamanı arızası anlamına gelmez.

## Kanıtlar ve tekrar çalıştırma

Ham sonuçlar git dışı `.local/offline-audit-20261026/` dizinindedir: `backend.log`, `backend.xml`, `stress.log`, `stress.xml`, `frontend-tests.log`, `typecheck.log`, `build.log`, `lint.log`, `lint-source.json`, `live-readonly.json`.

Python için proje kökünden:

```powershell
$auditRoot = (Get-Location).Path
$env:NHR_OFFLINE_AUDIT = '1'
$env:PYTHONPATH = "$auditRoot\scripts\offline_guard;$auditRoot"
$env:NHR_TEST_DATABASE_URL = ''
.\.venv\Scripts\python.exe -m pytest -q -p tests.offline_network_guard
```

Arayüz için aynı test kabuğunda:

```powershell
$env:NODE_OPTIONS = "--require=$auditRoot/scripts/offline_guard/node.cjs"
npm.cmd test --prefix web
npm.cmd run typecheck --prefix web
npm.cmd run build --prefix web
```

Bu ortam değişkenleri yalnız denetim kabuğunda kullanılmalı; çalışan uygulamanın başlatma ortamına eklenmemelidir.
