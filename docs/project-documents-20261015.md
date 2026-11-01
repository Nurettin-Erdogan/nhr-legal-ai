# Büro projelerinde belge çalışma alanı

## Kullanım

Projeler → bir proje → **Belgeler** sekmesinde “Arşivden belge bağla”.
Dosyalar ekranına yüklenen veya UYAP'tan alınan mevcut belgeler seçilir.
Yeni dosyanın ilk yüklemesi hâlâ Dosyalar ekranından yapılır; projeye bağlamak
dosyayı kopyalamaz, mevcut dava/istemci bağlantısını değiştirmez.

Proje kapsamı doğrudan bağlanan belgeler ile bağlı davanın evraklarının
birleşimidir. İki yoldan da gelen belge tek satırdır. “Bağlantıyı kaldır”
onayından sonra yalnız proje-belge ilişkisi silinir; kaynak dosya yerinde kalır.
Belge bağlı davadan da geliyorsa görünmeye devam eder. Kaynağın çöp kutusuna
taşınması onu bütün proje aramalarından çıkarır; geri alınırsa ilişki korunur.

Aranabilir belgeler seçilip analiz/özet/risk/taslak akışlarına taşınabilir.
Proje kimliği geçici, kullanıcıya özel sessionStorage bağlamında tutulur;
belge içerikleri URL'ye yazılmaz. Kuyruk `project_id` alanıyla büro projesine
bağlanır; sonuç projenin AI Çıktıları listesine kaydolur. Taslak seçim paneli
ve asistan yalnız bu proje kapsamındaki belgeleri listeler.

Sohbet, dava bağlantısı olmayan projenin doğrudan belgelerini de arar.
Lexical, geniş yedek ve hybrid sorgular aynı kapsamı kullanır. Açık belge
seçimi, yalnız aynı hesaba ait olmasıyla projeye giremez: proje üyeliği de
kontrol edilir. Hukuki kaynakların mevcut doğrulama/atıf denetimi korunur.
Olgu sorusu başka davaların olgularıyla cevaplanmaz. OCR ve okunamayan/bekleyen
belgeler açıkça gösterilir. Arama ilgili parçaları getirir; bütün metni okumuş
sayılmaz. Tam metin çalışması kalıcı belge kuyruğundan yapılır.

## Teknik ve güvenlik

- Yeni `office_project_documents` tablosu: UUID uygulamada, `(project_id,
  document_id)` unique, owner RLS + FORCE RLS, invoker owner/FK tetikleyicisi.
  Kullanıcı izolasyonu veya mevcut belge provenance/doğrulama statüsü değişmez.
- Kaynak dosya/proje gerçekten silinirse yalnız bağlantı satırları cascade ile
  temizlenir. Bağlantıyı kaldırmak belge, dava veya sohbeti silmez.
- API: GET/POST `/api/office/projects/{id}/documents`, DELETE
  `/api/office/projects/{id}/documents/{document_id}`. Toplu bağlama en fazla
  2000 kimlik, idempotent; tek bir yetkisiz/çöp kaynak varsa bütün istek reddedilir.
  İndekslenmemiş kaynaklar mevcut arka plan hattına verilir; başarısız belgeler
  sınırsız yeniden denenmez. İç dosya yolları liste yanıtına konmaz.
- Liste 500'lük sayfalardan toplanır; tekrar veya eksik sayfa tespit edilirse
  “tam liste” diye gösterilmez. Arayüz tek görünümde 50 bin belgeyi aşarsa açık
  hata verir; sessizce ilk kısmı göstermez. Kuyruk seçimi en fazla 2000 belgedir.
- İş başlatılırken, işlenen her belgede ve sonuç kaydedilirken proje kapsamı
  yeniden denetlenir. Kaldırılmış kaynakların türetilmiş metni son çıktıya
  kaydedilmez. Daha önce tamamlanmış çıktılar tarihsel, kullanıcıya özel kayıttır.
- Hesap/proje değişiminde görünüm yeniden kurulur; geç kalan yanıt yeni hesaba
  taşınmaz. Hesap dışa aktarımına bağlantı üst verileri dahildir. Yeni tablo
  genel `office` sorgu/yazma allowlist'ine açılmaz; yalnız özel API'den yönetilir.

## Kurulum ve test

Önce önceki sohbet kapsamı migrationı (053), ardından:

```powershell
.\.venv\Scripts\python.exe scripts/apply_project_documents_migration.py --apply
```

Yeni kurulum karşılığı `database/init/055_office_project_documents.sql`.
Migration eklemelidir; mevcut belge/sohbet verisini taşımaz veya silmez.
API yeniden başlatılmalıdır.

Regresyonlar: `tests/test_project_documents.py`, `tests/test_conversation_scope.py`,
`web/tests/project-documents.test.mjs`, `project-documents-ui.test.mjs`,
`ai-runner.test.mjs`. Gerçek PostgreSQL kabulü
`scripts/check_document_selection.py` ve `scripts/check_conversation_scope.py`:
yalnız kendilerinin oluşturduğu, sentetik, rastgele adlı test DB'sinde çalışır
ve sonunda yalnız bu DB'yi kaldırır. Canlı kullanıcı verisi kopyalanmaz.

Bu çalışma yeni bir UYAP indirme denemesi, tüm özel belgelerde model kalite
garantisi veya gerçek tarayıcıda görsel kabul sonucu değildir.

## 15.10.2026 kabul sonucu

- Python **1463 geçti, 386 atlandı**; atlanan opt-in/DB testleri başarılı sayılmadı.
- Web **427 geçti**; TypeScript ve üretim derlemesi başarılı. Değişen arayüz/API
  dosyalarında hedefli ESLint temiz.
- Ayrı sentetik PostgreSQL'de iki kabul scripti geçti: owner RLS, doğrudan/dava
  birleşimi, lexical/hybrid, idempotent bağlama, scope dışı seçim reddi,
  yalnız bağlantıyı kaldırma, kaynak dosyanın korunması ve bağlantı kaldırılmış
  analiz kaynağının son çıktıya kaydedilmemesi sınandı. Test DB'leri kaldırıldı.
- Yerel migration uygulandı ve yalnız API yeniden başlatıldı. Canlı health
  `ok/database connected`; yeni GET/POST/DELETE uç noktaları OpenAPI'de var,
  oturumsuz belge listesi isteği 401. Gerçek kullanıcı belgelerine bağlama/silme
  işlemi veya yeni model kalite denemesi yapılmadı.
