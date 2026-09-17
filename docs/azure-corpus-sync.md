# Azure korpusunu yerel PostgreSQL'e aktarma

Azure VM PostgreSQL portu dışarıya açılmaz. `scripts/sync_azure_corpus.py`,
bilinen SSH host anahtarını doğrulayarak VM içindeki `psql` çıktısını okur.
Yalnız `legal_sources`, `legal_chunks`, karar/mevzuat detayları, mevzuat
kimlikleri ve kaynak revizyonları aktarılır. Kullanıcı, müvekkil, proje,
belge, sohbet ve yerel embedding verisi kopyalanmaz veya silinmez.

Ön koşullar: VM'ye `ssh nhr@20.91.186.253` erişimi, yerel Docker/PostgreSQL,
`.env` içinde yerel `DATABASE_ADMIN_URL`, uygulanmış migrationlar ve
`.venv` içindeki Python bağımlılıkları. SSH anahtarı/DB şifresi Git'e konmaz.

```powershell
.\.venv\Scripts\python.exe scripts\sync_azure_corpus.py --dry-run --full
.\.venv\Scripts\python.exe scripts\sync_azure_corpus.py --full
.\.venv\Scripts\python.exe scripts\sync_azure_corpus.py
```

İlk aktarım `--full` yapar. Sonraki çağrılar `data/azure-corpus-sync-state.json`
imlecinden bir dakika geri gidip değişenleri tekrar tarar; işlem idempotenttir.
Çakışan içerik sessizce ezilmez ve komut sıfır dışı kodla çıkar. Kaynaklar
veritabanında tek tek transaction ile yazılır. Eksik parça ve detaylar eklenir;
mevcut yerel embedding korunur. İmleç yalnızca başarılı aktarım sonrasında
ilerler. Ayrıntılı günlük `data/azure-corpus-sync.log` dosyasındadır.

Altı saatte bir yerel Windows görevi kurmak için:

```powershell
.\scripts\install_azure_corpus_sync.ps1 -Frequency SixHours
```

Günlük 03.00 alternatifi `-Frequency Daily` kullanır. Görev yalnızca mevcut
kullanıcı oturum açmışken çalışır; bilgisayar kapalı/uykudayken veya SSH
erişimi yokken veri çekilemez. Sonraki başarılı çalışmada imleçten devam eder.
Görev kurulmadan önce aynı isimli görevi ezmez. Yerel bilgisayarın sürekli
açık olmadığı üretim düzeninde, VM'nin özel ağından erişilen kalıcı bir
PostgreSQL hedefi ve ayrı zamanlayıcı gerekir; yerel port internete açılmaz.
