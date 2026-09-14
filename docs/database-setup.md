# Veritabanı Kurulumu

İlk MVP için PostgreSQL + pgvector kullanıyoruz. Veritabanı Docker ile çalışır; böylece ekipte herkes aynı sürümü kullanır.

## 1. Repoyu klonla

```powershell
git clone https://github.com/Nurettin-Erdogan/nhr-legal-ai.git
cd nhr-legal-ai
git checkout setup/database-foundation
```

## 2. Yerel ortam dosyasını oluştur

```powershell
Copy-Item .env.example .env
```

`.env` içindeki `POSTGRES_PASSWORD` değerini sadece kendi bilgisayarında değiştir. `.env` Git'e gönderilmez.

## 3. PostgreSQL'i başlat

Docker Desktop açıkken:

```powershell
docker compose up -d
```

Durumu kontrol et:

```powershell
docker compose ps
```

Logları izle:

```powershell
docker compose logs -f db
```

## 4. Bağlantıyı test et

```powershell
docker compose exec db psql -U nhr_app -d nhr_legal_ai
```

psql içinde:

```sql
\dt
SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pgcrypto');
```

Çıkış:

```sql
\q
```

## 5. DBeaver bağlantısı

- Host: `localhost`
- Port: `5432`
- Database: `nhr_legal_ai`
- Username: `nhr_app`
- Password: `.env` dosyasındaki `POSTGRES_PASSWORD`

## İlk şema

Başlangıç tabloları:

- `users`: kullanıcı hesapları
- `projects`: dava/dosya/çalışma alanları
- `documents`: kullanıcı belgeleri
- `document_chunks`: RAG için kullanıcı belgesi parçaları
- `conversations`: sohbet oturumları
- `messages`: kullanıcı/asistan mesajları
- `legal_sources`: mevzuat, içtihat ve diğer hukuk kaynakları
- `legal_chunks`: hukuk kaynaklarının RAG parçaları
- `citations`: AI cevapları ile kaynaklar arasındaki bağlantı

## Not: embedding boyutu

`embedding` kolonları şimdilik boyutsuz `VECTOR` olarak tanımlandı. Kullanacağımız embedding modeli kesinleştiğinde boyut (ör. `VECTOR(1024)`) sabitlenecek ve HNSW/IVFFlat indeksi eklenecek. Böylece daha model seçilmeden veritabanını yanlış bir boyuta kilitlemiyoruz.

## Veritabanını sıfırlama

Sadece yerel geliştirmede tüm verileri silip yeniden kurmak için:

```powershell
docker compose down -v
docker compose up -d
```

`down -v` mevcut yerel veritabanı verilerini tamamen siler.
