# Hesap güvenliği: kayıt onayı, şifre, hesabın silinmesi, e-posta

Kullanıcının kendi hesabı üzerindeki işlemler `api/account.py` içindedir; arayüz karşılığı **Ayarlar** sayfası
(`web/src/components/AccountSettings.tsx`), giriş sayfası (`web/src/routes/auth.tsx`) ve sıfırlama sayfasıdır
(`web/src/routes/sifre-sifirla.tsx`). Şema: migration `047_account_security.sql`.

## Kayıt onayı

- Kayıt isteği `terms_accepted: true` taşımazsa reddedilir (400). Kabul anı ve metin sürümü kullanıcı satırına
  yazılır (`users.terms_accepted_at`, `users.terms_version`). Google ile ilk girişte onay kutusu aynı şekilde
  istenir ve yeni hesaba yazılır.
- **Açık iş:** Kullanım Şartları ve Gizlilik Politikası sayfaları hâlâ *taslak* ibaresi taşır; yayından önce bir
  hukukçu tarafından tamamlanmalı ve `terms_version` yeni sürümle güncellenmelidir.

## Şifre değiştirme

`POST /api/account/password` mevcut şifreyi ister. Başarılı değişiklik `users.sessions_valid_after` değerini
ilerletir: eski şifreyle açılmış **bütün** oturumlar kapanır, isteği yapan tarayıcıya yeni çerez verilir.
15 dakikada 8 hatalı denemeden sonra istek 429 ile reddedilir (sayım `activity_logs` üzerinden yapılır).

## Şifre sıfırlama

| Adım | Uç nokta | Not |
| --- | --- | --- |
| Durum | `GET /api/auth/password-reset/status` | E-posta gönderimi kurulu mu (`email` / `manual`) |
| İstek | `POST /api/auth/password-reset/request` | Hesap var olsun olmasın aynı yanıt (hesap sayımı yapılamaz) |
| Onay | `POST /api/auth/password-reset/confirm` | Tek kullanımlık anahtar + yeni şifre |

- Anahtar 60 dakika geçerlidir, bir kez kullanılır; veritabanına yalnız SHA-256 özeti yazılır
  (`auth_password_resets`; RLS açık, politika yok, `nhr_runtime` erişemez).
- Yeni istek önceki açık anahtarları geçersiz kılar. Başarılı sıfırlama bütün oturumları kapatır.
- IP başına 15 dakikada 10 istek, 8 hatalı onay sınırı vardır.
- **E-posta kurulu değilse** istek bağlantı göndermez; arayüz bunu açıkça söyler ("sistem yöneticinize başvurun").
  Yönetici, kullanıcının kimliğini başka yoldan doğruladıktan sonra bağlantıyı elle üretir:

  ```powershell
  .\.venv\Scripts\python.exe scripts\create_password_reset_link.py kullanici@ornek.com
  ```

## Hesabın silinmesi (KVKK)

`POST /api/account/delete` şifreyi ve `HESABIMI SİL` ifadesini ister. Silme tek işlemde:

- sohbetleri, belgeleri (dosyalarıyla), büro kayıtlarının tamamını (`office_*`), proje/müvekkil kayıtlarını ve
  üyelikleri **kalıcı olarak siler**;
- kullanıcı satırını **anonimleştirir** (e-posta `silindi-<rastgele>@deleted.invalid`, ad boş, hesap pasif,
  `deleted_at` dolu). Satır, denetim kayıtlarının bütünlüğü için tutulur; denetim kayıtlarında içerik yoktur.

Silinen e-postayla yeniden kayıt olunabilir; eski verilere erişim geri gelmez.

## E-posta (SMTP)

`api/mailer.py` yalnız ortam değişkenleriyle çalışır; değerler `.env` içinde durur, koda ya da veritabanına yazılmaz.

| Değişken | Anlamı |
| --- | --- |
| `SMTP_HOST`, `SMTP_PORT` (varsayılan 587) | Sunucu |
| `SMTP_USER`, `SMTP_PASSWORD` | Kimlik (gerekmiyorsa boş) |
| `SMTP_FROM` | Gönderen adres (zorunlu) |
| `SMTP_STARTTLS` | Varsayılan `true` |
| `WEB_BASE_URL` | Bağlantıların kökü; boşsa `CORS_ORIGINS` içindeki ilk adres |

`SMTP_HOST` ve `SMTP_FROM` boşsa e-posta **kurulu değil** sayılır. Bu durumda:

- şifre sıfırlama bağlantısı gönderilmez (yukarıdaki yönetici betiği kullanılır);
- hatırlatmalarda "e-posta" kanalı arayüzde kapalıdır; e-posta gitmiş gibi davranılmaz.

Kuruluysa `api/reminder_mailer.py` dakikada bir, zamanı gelmiş ve kanalı e-posta olan hatırlatmaları gönderir
(en çok 24 saat gecikmeyle; gönderilen `sent` olur ve `notified_at` yazılır).

## Hatırlatma bildirimi (uygulama içi)

Üst çubuktaki zil (`web/src/components/ReminderBell.tsx`) zamanı gelen hatırlatmaları dakikada bir yoklar, bir kez
ekranda duyurur ve `notified_at` yazar. Bildirim yalnız uygulama açıkken görünür; tarayıcı kapalıyken haber veren
tek kanal e-postadır.

## Testler

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_account.py tests/test_reminder_mailer.py -q
```

Veritabanı testleri `NHR_TEST_DATABASE_URL` ister; test veritabanında migration 047 uygulanmış olmalıdır.
