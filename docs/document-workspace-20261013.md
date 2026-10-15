# Tam metin belge çalışma alanı

## Kapsam

- Yeni arayüzde analiz, toplu özet, risk incelemesi ve seçili belgelerden taslak
  `/api/office-ai/jobs` kalıcı kuyruğunu kullanır. Tek işte en fazla 2000 belge;
  yapıştırılan metinde en fazla 2 milyon karakter. Eski senkron API'lerin küçük
  istek limitleri korunur; yeni arayüz onları çok belgeli iş için kullanmaz.
- Metnin tamamı pencerelere ayrılır. Son pencere atılmaz. Risk penceresi,
  araştırma hattının soru sınırından ad ve yönerge payı çıkarılarak hesaplanır.
- Özet maddeleri kaynak metin ve ikinci model denetimiyle süzülür. Reddedilen
  maddeler/bölüm hataları raporlanır; iş `partial` olur. Hukuki risk çıktıları
  mevcut kaynaklı araştırma/atıf doğrulama hattından geçer. Üçüncü taraf
  kaynakların doğrulama etiketleri korunur.
- Taslak ana gövdesi her belgenin bütün pencerelerinden doğrulanmış olguları
  içerir. Kullanıcı açıklamaları ayrı belirtilir; dayanaklar kodla eklenir.
  Bu, tüm dosyalar arasında çelişkileri otomatik çözen bir hukuki görüş değildir.
- Sunucu yeniden başlarsa son bölüm ilerlemesi saklıdır. Kullanıcı paneli
  açtığında süresi dolmuş 90 saniyelik lease devralınır. Bir hesapta bir aktif
  iş çalışır. Durdurma yeni bölümleri ve son kaydı engeller; sürmekte olan
  model çağrısı hemen iptal edilmeyebilir. Başarısız/eksik iş yeniden denenebilir.
- Tabloda zorunlu owner RLS, audit, uygulamada üretilen UUID vardır.
  Kaynak kalıcı silinirse ilgili kuyruk ve iş çıktıları tetikleyiciyle silinir.
  AI geçmişindeki sonuç silinirse bağlı iş de temizlenir; yeniden deneme eski
  kısmi çıktıyı yenisiyle değiştirir, yetim türetilmiş metin bırakmaz.
  Hesap dışa aktarımına kuyruk da dahildir; iç lease değerleri hariçtir.

## Kurulum

```powershell
.\.venv\Scripts\python.exe scripts/apply_document_jobs_migration.py --apply
```

API yeniden başlatılmalıdır. Migration mevcut belgeleri veya hesapları silmez.
Yeni boş Docker kurulumunda `database/init/053_document_jobs.sql` uygulanır.

## 14.10.2026: belge seçimi ve talimat odaklı inceleme

- AIRunner'ın dört araştırma modunda seçili belgeler artık yalnız arayüzde
  kalmaz: `selected_document_ids` ile kaynaklı RAG hattına gönderilir. Bunlar
  `office_case_documents.id` kimlikleridir; en fazla 40, tekrarsız. `case_id`
  verilirse seçimi daraltır; `project_id` ile karıştırılmaz.
- İki cevap uç noktasında da seçim RLS altında doğrulanır. Başka hesaba ait,
  silinmiş veya farklı davadaki belge için 404; metni/parçaları hazır olmayan
  seçim için 409 döner. Seçimin yalnız okunabilen alt kümesiyle sessizce
  ilerlenmez. Pipeline aramadan hemen önce erişimi yeniden kontrol eder.
- Lexical, geniş yedek ve hybrid arama aynı seçime bağlıdır. Seçilmemiş dava
  kayıtları eklenmez; yalnız olgu sorularında genel korpustaki başka davaların
  olguları kullanılmaz. Hukuki değerlendirmede mevcut kaynak/atıf doğrulaması
  korunur. Hızlı mevzuat kestirmesi seçili belgeleri atlayamaz; önbellek anahtarı
  seçim ve sahibini ayırır. OCR ve kullanıcı belgesi uyarıları korunur.
- Araştırma ilgili parçaları getirir; bütün seçili belgelerin tamamını okumuş
  sayılmaz. Tam metni bölüm bölüm işlemek için belge kuyruğu kullanılır.
- Kuyruktaki `document_analysis` artık genel özet çağırmak yerine kullanıcının
  talimatına odaklanır. Talimat JSON'da belge metninden ayrıdır ve doğrulama
  kanıtına katılmaz. Yapıştırılan metin için ayrı talimat alanı vardır.
  Bulgular kaynak metin ve ikinci model denetiminden geçer; ilgili doğrulanmış
  bulgu yoksa genel özetle ikame edilmez, bölüm uyarısı gösterilir.
- Bu inceleme bölüm düzeyinde olgu çıkarımıdır; belgeler arasında bütünsel
  çelişki analizi veya bağımsız bir hukuki görüş olarak sunulmaz.

Doğrulama: tam Python paketi **1442 geçti, 386 atlandı**. Atlanan testler başarılı
sayılmadı. Ayrı sentetik PostgreSQL/pgvector veritabanında gerçek `nhr_runtime`
RLS ile seçim, dava kesişimi, lexical/hybrid/geniş arama, OCR ve silinmiş/hazır
olmayan belge kontrolleri ayrıca geçti (`scripts/check_document_selection.py`).
Yalnız bu scriptin oluşturduğu geçici DB kaldırıldı; canlı belgeler değiştirilmedi.
Web tarafında **411 test**, TypeScript, üretim derlemesi ve değişen arayüz/API
dosyalarında hedefli ESLint kontrolü geçti. Gerçek bileşenin seçim/Çalıştır
olayları, API gövdesi ve hata iletimleri regresyon testleriyle sınanır.
Bu değişiklik yeni migration istemez. Yerel API yeniden başlatıldı; `/health`
veritabanı bağlı/ok ve canlı OpenAPI yeni seçim alanını gösteriyor.
Gerçek kullanıcı belgelerinde yeni model kalite testi veya canlı görsel
kabul bu çalışmada yapılmadı.

## Google Drive

Dosyalar ekranındaki Google Picker kullanıcıdan `drive.file` erişimi ister;
yalnız seçilen dosyalar tarayıcıdan indirilip açık aktarım onayı sonrası mevcut
belge yükleme/indeksleme hattına gönderilir. Google erişim jetonu API'ye veya
tarayıcı kalıcı deposuna kaydedilmez. Hesap değişirse seçim temizlenir ve eski
seçim yeni hesaba aktarılmaz. Dosya başına sınır 50 MB. Google Docs DOCX olarak
alınır; diğer Google-native türler şimdilik desteklenmez. Drive'a geri yazılmaz.

Yönetici ayarları: `GOOGLE_DRIVE_CLIENT_ID` (yoksa `GOOGLE_CLIENT_ID`),
`GOOGLE_PICKER_API_KEY`, `GOOGLE_CLOUD_PROJECT_NUMBER`. Drive API ve Picker API
etkin olmalı. OAuth web istemcisinde uygulamanın JavaScript origin'i ve
`drive.file` kapsamı tanımlanmalı. Public API key referrer/API kısıtlı olmalı;
client secret arayüze verilmez. Uygulamayı üçüncü kişilere yayınlamadan önce
Google consent/publishing durumunu kontrol edin.

Kaynak: [Google Picker](https://developers.google.com/workspace/drive/picker/guides/web-picker),
[GIS token model](https://developers.google.com/identity/oauth2/web/guides/use-token-model),
[Drive indirme/export](https://developers.google.com/workspace/drive/api/guides/manage-downloads).

## Microsoft Word

`web/public/word/taskpane.html` Office.js görev bölmesi: kullanıcı kendi
JurisAI parolasıyla giriş yapar, seçimini veya açık belge metnini okur, gönderilecek
metni görür ve açık düğmeyle işi başlatır. Sonuç seçimin **sonuna** düz metin
olarak eklenir; mevcut belge üzerine yazılmaz. Jeton yalnız bellektedir.
Google-only hesap için önce JurisAI hesabında parola kurmak gerekir; Word
görev bölmesinde Google OAuth girişi henüz yoktur.

`WORD_ADDIN_ORIGIN=https://uygulama-adresi` geçerli HTTPS origin olmalı;
aynı adresteki `/api` istekleri API'ye proxy edilmelidir. Geliştirmede localhost
görev bölmesi API için 8766'yı kullanır; Word'e sideload yine güvenilir HTTPS
gerektirir. Ayarlar → Bağlantılar manifest indirmesini yalnız origin ayarlıysa
gösterir. Manifest `/api/integrations/word/manifest`; ReadWriteDocument, WordApi
1.1. Yönetici Microsoft 365 dağıtımı veya Word sideload yapmalıdır. Mağaza yayını
ve gerçek Microsoft 365 tenant kabul testi bu kod değişikliğinden ayrıdır.

Kaynak: [Word Add-ins](https://learn.microsoft.com/en-us/office/dev/add-ins/word/word-add-ins-programming-overview),
[Word tutorial](https://learn.microsoft.com/en-us/office/dev/add-ins/tutorials/word-tutorial).

## Sayfa düzeni

A4/Letter, 10–35 mm kenar boşluğu, 9–16 punto, 1–2 satır aralığı,
sol/iki yana hizalama ve sayfa numarası. Önizleme, DOCX ve PDF aynı düzen
ayarını kullanır; düzen metadata'da kaydedilir. PDF'de Türkçe font gömülür.
Tam Word masaüstü eşdeğeri değildir: gelişmiş tablo/madde akışı, değişiklik
izleme ve Word/Drive çift yönlü senkronizasyon dahil değildir.

## 13.10.2026 kabul sonucu

- Python: **1418 geçti, 385 atlandı**. Atlanan opt-in/veritabanı testleri
  başarılı sayılmadı. Windows'taki eski geçici test dizininin erişim hatası
  nedeniyle son koşu yeni, ayrı `--basetemp` ile yapıldı.
- Web: **403 geçti**; TypeScript ve üretim derlemesi geçti. Yeni kuyruk,
  Drive, düzen ve dışa aktarma modüllerinde hedefli ESLint kontrolü temiz.
- `scripts/check_document_jobs_schema.py`: canlı veri kopyalamadan geçici
  ayrı `*_test` veritabanında gerçek PostgreSQL/RLS testi. Kullanıcı
  izolasyonu, sahte owner reddi, tek aktif iş, kaynak/AI çıktısı silinince
  türetilmiş kayıtların temizlenmesi ve diğer hesabın korunması geçti.
  Yalnız bu komutun oluşturduğu sentetik DB sonunda kaldırıldı.
- Canlı Chrome: sentetik 304 karakterlik özet işi modelden ve kaynak madde
  denetiminden geçti, `1/1` tamamlandı; tarih, tutar ve olumsuzluk korundu.
  Sunucu/sayfa yenilemesinden sonra iş ve sonuç tekrar açıldı.
  Gerçek UYAP belgeleri değiştirilmedi veya yeniden aktarılmadı.
- Canlı düzenleyici: Letter, 25 mm, 12 punto, 2 satır aralığı ve iki yana
  hizalama DOM ve görselde doğrulandı. Gerçek üretilen DOCX XML'inde boyut,
  boşluk, Türkçe metin, vurgu ve sayfa alanları; gerçek PDF baytlarında
  Letter ölçüsü ve gömülü font otomatik testte doğrulandı.
- **Canlı Drive/Word kabulü henüz tamamlanmadı:** bu ortamda Picker API
  anahtarı, Cloud proje numarası ve Word HTTPS origin'i yok. Kod ve ayar
  ekranı hazır; Google hesabı bağlama ve gerçek Word dağıtımı başarılıymış
  gibi gösterilmez. Mevcut Google-only hesap Word görev bölmesinde giriş
  için önce JurisAI parolası belirlemelidir; bu işlem otomatik yapılmadı.
- Tüm 1382 gerçek evrakta model kalite/yük testi yapılmadı. Otomatik
  testler 2000 kimlik kabulünü, dört belgeden fazla işlemi, uzun metnin son
  penceresini, durdurmayı, devam etmeyi ve kısmi hata bildirimini sınar;
  tüm olguların modelce kusursuz özetleneceğine garanti vermez.
