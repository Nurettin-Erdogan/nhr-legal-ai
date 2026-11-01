# Google ile giriş (FastAPI)

Bu akış Google OpenID Connect **authorization code + PKCE** kullanır. Tarayıcı
Google kodunu yalnız API callback'ine gönderir; API Google ID token imzasını,
issuer/audience/son kullanma zamanını, nonce'u ve doğrulanmış e-postayı kontrol
eder. Google token'ı veritabanına veya tarayıcıya kaydedilmez. Uygulama kendi
`HttpOnly` oturum çerezini üretir. Kalıcı eşleme e-postaya değil Google `sub`
değerine dayanır.

## Yerel kurulum

1. [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
   üzerinden OAuth onay ekranını ayarlayın. Uygulama test modundaysa giriş
   yapacak Google hesaplarını test kullanıcısı olarak ekleyin.
2. **OAuth client ID → Web application** oluşturun. Authorized redirect URI:
   `http://localhost:8766/api/auth/google/callback`. Bu değer birebir eşleşmeli.
   Uygulamayı `127.0.0.1` yerine `localhost` ile açın; iki hostname'in çerezleri
   birbirine taşınmaz.
3. Proje kökündeki Git'e eklenmeyen `.env` dosyasına ekleyin (gerçek secret'ı
   sohbet mesajına veya `web/.env` dosyasına koymayın):

   ```env
   GOOGLE_CLIENT_ID=...apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=...
   GOOGLE_REDIRECT_URI=http://localhost:8766/api/auth/google/callback
   GOOGLE_WEB_CALLBACK_URL=http://localhost:3000/auth/callback
   ```

4. Mevcut veritabanına `database/migrations/029_google_auth.sql` dosyasını
   `nhr_app` yönetici rolüyle **bir kez** uygulayın. Yeni/verisiz Docker DB'de
   `database/init/030_google_auth.sql` otomatik uygulanır. Örneğin PowerShell'de:

   ```powershell
   Get-Content -Raw .\database\migrations\029_google_auth.sql |
     docker compose exec -T db psql -U nhr_app -d nhr_legal_ai -v ON_ERROR_STOP=1 -1
   ```

5. API'yi `.env` değişikliğinden sonra yeniden başlatın. `GET
   http://localhost:8766/api/auth/google/status` yanıtı `{"configured":true}`
   olmalı. `http://localhost:3000/auth` üzerinde Google düğmesi aktif olur.

## Mevcut e-posta/şifre hesabı

Aynı e-postayı taşıyan Google hesabı **otomatik bağlanmaz**; böylece e-posta
eşleşmesi hesap ele geçirmeye yol açmaz. Önce normal şifreyle giriş yapın,
**Ayarlar → Google hesabını bağla** seçeneğini kullanın. Google'ın doğrulanmış
e-postası mevcut kullanıcı e-postasıyla aynı olmalı. Sonraki girişlerde Google
`sub` eşlemesiyle aynı hesaba girilir.

`ALLOW_REGISTRATION=false` yeni Google hesabı açılmasını da kapatır; daha
önceden bağlanmış Google hesapları giriş yapabilir.

## Üretim ortamı

`GOOGLE_REDIRECT_URI` ve `GOOGLE_WEB_CALLBACK_URL` gerçek HTTPS alan adlarıyla
yeniden ayarlanmalı; ilki Google Cloud'da authorized redirect URI olarak birebir
kaydedilmeli. `AUTH_COOKIE_SECURE=true`, HTTPS ve uygun `CORS_ORIGINS` gereklidir.
Client secret yalnız API sunucusunda tutulur. Google Calendar yetkisi istenmez;
bu entegrasyon sadece oturum açma içindir.

Kaynaklar: [Google web-server OAuth akışı](https://developers.google.com/identity/protocols/oauth2/web-server),
[Google OpenID Connect token doğrulama](https://developers.google.com/identity/openid-connect/openid-connect).
