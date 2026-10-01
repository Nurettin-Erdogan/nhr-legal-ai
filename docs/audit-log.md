# Denetim günlüğü

`activity_logs` tablosu kim, ne zaman, hangi kaydı üzerinde ne yaptı sorusunu yanıtlar. Kod:
`api/audit.py` (yazım), `api/admin_audit.py` (yönetici okuması).

## İlke: olay kaydedilir, içerik kaydedilmez

Günlük tek başına kişisel veri deposuna dönüşmemelidir. **Yazılmaz:** soru ve cevap metni,
belge içeriği, dosya ve proje adı, e-posta, ad-soyad, parola. **Yazılır:** kimlik numaraları
(kullanıcı, proje, belge, sohbet, istek), eylem adı, zaman, IP, tarayıcı bilgisi ve sayısal ya da
mantıksal özetler (parça sayısı, `grounded`, atıf sayısı).

## Kaydedilen olaylar

| Eylem | Ne zaman | Metadata | Hata politikası |
| --- | --- | --- | --- |
| `auth.login` | Başarılı giriş | — | En iyi çaba |
| `auth.login_failed` | Başarısız giriş (hesap yok, parola yanlış, hesap pasif) | `reason`, `email_fingerprint` | En iyi çaba |
| `auth.register` | Hesap oluşturma | — | En iyi çaba |
| `auth.logout` | Oturumlu çıkış | — | En iyi çaba |
| `project.create` | Proje oluşturma | `matter_type` | **Katı** |
| `document.upload` | Belge yükleme | `extension`, `file_size`, `chunk_count` | **Katı** |
| `conversation.delete` | Sohbet silme (yalnız gerçekten silindiyse) | — | **Katı** |
| `ai.answer` | Oturumlu kullanıcının AI cevabı | `message_id`, `model`, `grounded`, `from_cache`, `citation_count`, `third_party_citations`, `document_citations` | En iyi çaba |

* **Katı:** denetim kaydı iş kaydıyla aynı transaction'dadır. Denetim yazılamazsa iş de geri alınır;
  denetlenmemiş yazım kalmaz.
* **En iyi çaba:** denetim savepoint içinde denenir; hata olursa yalnız loglanır. Denetim tablosundaki
  bir sorun girişi ya da cevap üretmeyi engellemesin diye.
* **Başarısız giriş** ayrı bir bağlantıyla yazılır: 401 fırlatmak transaction'ı geri alırdı. Aktör
  boştur (kimlik doğrulanamadı); e-posta yerine sha256'nın ilk 16 hanesi yazılır, böylece aynı adres
  tekrar tanınır ama adres okunamaz. Üç başarısızlık nedeni aynı 401 yanıtını döndürür.
* Anonim (oturumsuz) AI cevapları kaydedilmez: aktör yoktur ve RLS aktörsüz satırı uygulama rolüne
  yazdırmaz.

## Erişim kontrolü

* **INSERT** yalnız `actor_user_id = app_current_user_id()` iken (RLS). Oturum öncesi olaylar
  `nhr_app` ile yazılır; bu, kimlik doğrulama öncesi sorgular için tanımlı istisnadır.
* **SELECT** yalnız kendi kayıtları ya da `admin` rolü için.
* **UPDATE / DELETE** politikası yoktur: uygulama rolü kayıtları değiştiremez ya da silemez.
* `GET /api/admin/audit` yalnız yöneticiye açıktır. Filtreler: `action`, `actor_user_id`,
  `project_id`, `before`; `limit` en çok 200. Yazma ucu yoktur.

## Bilinen sınırlar

* **IP adresi doğrudan bağlanan istemcinindir.** `X-Forwarded-For` bilinçli olarak okunmaz; güvenilen
  bir ters vekil tanımlanmadan istemci günlüğe istediği IP'yi yazdırabilirdi. Uygulama bir vekilin
  arkasında çalışacaksa vekil adresi yazılır; güvenilen vekil desteği eklenmelidir.
* **Okuma olayları kaydedilmez** (belge/sohbet görüntüleme, arama). Yalnız yazma, kimlik doğrulama ve
  AI cevabı vardır.
* **Saklama süresi ve arşivleme tanımlı değildir.** Tablo büyür; KVKK saklama politikası netleşince
  silme/arşiv işi eklenmelidir.
* **Değiştirilemezlik uygulama rolü için geçerlidir.** `nhr_app` (tablo sahibi) RLS'i aşar; veritabanı
  yöneticisi kayıtları değiştirebilir. Bu gerekiyorsa günlüğün dışarıya (append-only depo) akıtılması
  gerekir.
* **Kaydedilmeyenler:** kaydedilen kaynaklar, müvekkil işlemleri ve belge silme henüz yok; bu
  özellikler yazıldığında `api/audit.py` içine eylem adı eklenip aynı desenle kaydedilmelidir.
