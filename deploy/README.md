# AWS sunucusuna kurulum (tek sunucu, kartsız plan)

Hedef: `m7i-flex.large` (2 vCPU, 8 GiB RAM) + 450 GB gp3 disk, Ubuntu 24.04, `eu-north-1`. Her şey tek makinede Docker ile çalışır:
veritabanı, API, web, Ollama (gömme modelleri) ve Caddy (HTTPS). Metin üretimi AWS Bedrock'tadır (AGENTS.md, "Tek bulut sağlayıcı kararı").

> Bu makine dar: 354 GB'lık veritabanı için 8 GiB RAM küçüktür. Kuruluma geçmeden önce gerçek arama gecikmelerini ölçün
> (aşağıda "Ölçüm"); yetersizse aynı disk ve verilerle sunucu tipi büyütülür (kısa durma, yeniden taşıma yok).

## 0. Önkoşullar (yerel makinede)

1. Fiziksel yedek alınmış ve S3'e yüklenmiş olmalı: `s3://nhr-pgbackrest-eun1-20261104-7319/physical-20261104/pgdata`
   (yedek: `E:\JurisAI\basebackup-20261104`; yükleme günlüğü `s3sync.log` içinde "SON GECIS BITTI" yazmalı).
2. Belgeler (`uploads/`, ~14 GiB) S3'e yüklenmiş olmalı: `aws s3 sync uploads s3://<depo>/uploads`.
3. Üretim ayarları üretilmiş olmalı (depo dışına):
   `.\.venv\Scripts\python.exe scripts\make_production_env.py --site <IP-ile-sslip>.sslip.io --out E:\JurisAI\env.production`
   Alan adı almadan HTTPS için `sslip.io` kullanılır: sunucunun IP'si `13.60.1.2` ise adres `13-60-1-2.sslip.io`.

## 1. Sunucu (bir kez)

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 unzip git
sudo systemctl enable --now docker
# 8 GB takas alanı: bellek dar olduğundan ani tepe yükte işlem öldürülmesin
sudo fallocate -l 8G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
curl -sSL https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o /tmp/awscli.zip && unzip -q /tmp/awscli.zip -d /tmp && sudo /tmp/aws/install
sudo mkdir -p /srv/nhr/{pgdata,uploads,api-data,ollama} && sudo chown ubuntu:ubuntu /srv/nhr
```

Sunucunun S3 okuma yetkisi **IAM rolüyle** verilir (anahtar sunucuya konmaz). `aws sts get-caller-identity` rolü göstermeli.

## 2. Veriyi indir

```bash
B=s3://nhr-pgbackrest-eun1-20261104-7319
aws s3 sync $B/physical-20261104/pgdata /srv/nhr/pgdata --only-show-errors
aws s3 sync $B/uploads /srv/nhr/uploads --only-show-errors
sudo chown -R 999:999 /srv/nhr/pgdata && sudo chmod 700 /srv/nhr/pgdata    # postgres kullanıcısı
sudo chown -R 10001:10001 /srv/nhr/uploads /srv/nhr/api-data               # API kullanıcısı
```

## 3. Uygulama

```bash
git clone <depo> /srv/nhr/app && cd /srv/nhr/app          # ya da yerelden rsync ile
cp <env.production> /srv/nhr/.env.production && chmod 600 /srv/nhr/.env.production
docker compose -f deploy/docker-compose.prod.yml --env-file /srv/nhr/.env.production up -d db
docker compose -f deploy/docker-compose.prod.yml logs -f db      # "database system is ready" görünene kadar (kurtarma dakikalar sürebilir)
```

Geri yüklemeden sonra **veritabanı parolalarını değiştirin** (geri yüklenen veritabanında yereldeki eski parolalar vardır):

```bash
. /srv/nhr/.env.production
docker compose -f deploy/docker-compose.prod.yml exec -T db psql -U nhr_app -d nhr_legal_ai \
  -c "ALTER ROLE nhr_app PASSWORD '$POSTGRES_PASSWORD'" -c "ALTER ROLE nhr_runtime PASSWORD '$NHR_RUNTIME_DB_PASSWORD'"
docker compose -f deploy/docker-compose.prod.yml --env-file /srv/nhr/.env.production up -d --build
docker compose -f deploy/docker-compose.prod.yml exec ollama sh -c "ollama pull nomic-embed-text && ollama pull bge-m3"
```

## 4. Doğrulama (trafik açmadan önce)

- `https://<adres>/` açılır, `/health` 200 ve `database=connected` döner.
- Erişim listesi (`allowlist`) modunda, listede olmayan hesap giremez; yönetici girer.
- Arama, kaynak okuyucu, belge açma, Mevzuat ekranı, sohbet (Bedrock) çalışır.
- Kullanıcı izolasyonu: iki hesapla, birinin belgesi diğerinde görünmez (RLS).
- Eski ifşa olmuş AWS anahtarları silinmiş, `make_production_env.py` çıktısı Git'te yok.

## Ölçüm

Soğuk (ilk) ve sıcak aramaları kaydedin: Mevzuat listesi, karar arama, anlam araması, bir sohbet cevabı. Sonuçlar kabul edilemezse
sunucu tipini büyütün (EC2 konsolu: durdur → tip değiştir → başlat); disk ve veri değişmez.

## Bilinen eksikler

- UYAP eklentisi hâlâ `localhost` adreslerine bağlı; üretim adresi eklenti manifestine ve `WEB_ORIGINS`'e eklenip yeniden paketlenmeli
  (`scripts/build_store_extension.py`).
- Toplayıcılar (resmî portal), gömme işleri ve doğrulama betikleri bu sunucuda **çalışmaz**; veri kaynağı yerel makinedir.
- Yedekleme: sunucuda düzenli veritabanı ve belge yedeği henüz kurulmadı.
