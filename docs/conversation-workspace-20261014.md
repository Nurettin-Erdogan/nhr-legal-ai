# Dava/proje sohbet geçmişi

## Davranış

- Dava içindeki “Belgelerle Sor” sohbetleri `conversations.case_id` ile saklanır.
  Kompakt geçmiş seçicisinden yeniden açılabilir, yeni sohbet başlatılabilir
  veya yalnız seçilen sohbet silinebilir. Liste son 50 sohbeti gösterir.
- Büro projesinde “Sohbet” sekmesi vardır. `office_project_id`, çekirdek
  araştırma/RAG `project_id` alanından ayrıdır. Büro projesi davaya bağlıysa
  mevcut bağlı davanın belgeleri ve UYAP kayıtları aranır; değilse belge varmış
  gibi davranılmaz. Hukuki araştırma hukuk kaynaklarına gider, dosyaya özgü
  olgular başka davaların kararlarından cevaplanmaz.
- Genel sohbet geçmişinden dava/proje/belge seçimli bir sohbet açıldığında
  kayıtlı kapsam da yüklenir ve sonraki soruya gönderilir. Kapsam ve varsa
  seçili belge sayısı görünür; ilgili dava/projeye bağlantı vardır.
- Hesap veya sabit dava/proje değişiminde bileşen yeniden kurulur. Geç kalan
  geçmiş/cevap sonucu yeni hesabın ekranını dolduramaz. Kaynakların
  doğrulanmadı/kullanıcı belgesi ayrımı korunur. OCR/belge kapsamı uyarısı
  mesaj metadata'sında saklanır ve geçmiş açıldığında tekrar gösterilir.

## Güvenlik ve veri

Migration: `database/migrations/053_conversation_workspace_scope.sql`.
Yeni boş kurulum karşılığı: `database/init/054_conversation_workspace_scope.sql`.

```powershell
.\.venv\Scripts\python.exe scripts/apply_conversation_scope_migration.py --apply
```

Migration eklemelidir; sohbet/belge silmez ve eski sohbetleri içeriklerinden
tahmin ederek davalara bağlamaz. Eski kapsamı bilinmeyen sohbetler genel
geçmişte kalır. Güncel kodla açılan sohbetler kapsamlı kaydedilir. API yeniden
başlatılmadan yeni alanlar ve arayüz birlikte kullanıma alınmamalıdır.

Mevcut conversation/message/citation RLS politikaları değiştirilmez. Büro
kapsamı `project_id=NULL` olduğu için yalnız oluşturana görünür; ortak
çekirdek proje üyelik yetkisi bu özel veriye genişletilmez. Yeni invoker
tetikleyicisi RLS altında owner/FK eşleşmesini ve belge alt kümesini denetler;
sonradan dava, büro projesi veya belge seçiminin değiştirilmesini engeller.
Dava/büro projesi gerçekten silinirse ona doğrudan bağlı sohbetler FK cascade
ile silinir. Hesap dışa aktarımında yeni kapsam alanları da bulunur.

Sohbete devam isteğinde kapsam üretimden önce doğrulanır; uyuşmazlık 409 olur.
Kayıt öncesinde satır kilidiyle yeniden doğrulanır. Mesaj/atıf kimlikleri
uygulamada üretilir; INSERT RETURNING kullanılmaz. Denetim kaydına içerik değil
kapsam kimlikleri ve belge/atıf sayıları yazılır.

## Testler

`tests/test_conversation_scope.py`, `tests/test_conversations_api.py`,
`web/tests/legal-chat.test.mjs`, `web/tests/ai-stream.test.mjs`;
gerçek PostgreSQL kabulü `scripts/check_conversation_scope.py`.
Sonuncusu yalnız kendisinin oluşturduğu rastgele adlı sentetik `*_test`
veritabanında çalışır, mevcut conversation RLS fonksiyonlarını kullanır,
kapsamlı kayıt/yeniden açma/devam, yabancı FK reddi, değişmez kapsam ve cascade
temizliğini sınar; sonunda yalnız o DB'yi kaldırır. Canlı veriler kopyalanmaz.

Bu çalışma projelere bağımsız belge iliştirme yönetimi, Word/Drive dağıtımı,
eski sohbetlere otomatik dava atama veya modelin tüm dosyayı eksiksiz
anlayacağına dair bir garanti içermez. Büro projesinin dava bağı değişirse
yeni sorular güncel bağlı davayı kullanır; eski cevaplar tarihsel kayıttır.

## 14.10.2026 kabul sonucu

- Python: **1454 geçti, 386 atlandı**. Atlanan veritabanı/opt-in testleri
  başarılı sayılmadı.
- Web: **418 test geçti**, TypeScript, üretim derlemesi ve değişen arayüz/API
  dosyalarında hedefli ESLint kontrolü temiz.
- Ayrı sentetik PostgreSQL kabulü geçti; yalnız test DB'si kaldırıldı.
- Şema migrationı yerel uygulama DB'sine uygulandı. Eski sohbetler ve gerçek
  belgeler silinmedi veya tahminle başka kapsama taşınmadı. Yalnız API hizmeti
  yeniden başlatıldı; sağlık kontrolü `ok/database connected`, canlı OpenAPI
  yeni büro projesi isteğini ve dava geçmişi alanlarını gösteriyor.
- Gerçek bileşenin açma/gönderme olaylarıyla kayıtlı kapsam, yanlış dava
  reddi, hesap değişiminde temizleme ve geç gelen cevap izolasyonu sınandı.
  Canlı tarayıcıda görsel kabul ve gerçek özel belgelerde model kalite testi
  bu turda yapılmadı; bunlar başarılıymış gibi raporlanmaz.
