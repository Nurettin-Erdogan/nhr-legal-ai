# Klasör rehberi

## Kalıcı proje dosyaları

| Dizin | İçerik |
| --- | --- |
| `api/` | Backend, kimlik doğrulama, arama ve RAG |
| `web/` | Web arayüzü |
| `database/` | Şema, migration ve RLS |
| `ingestion/` | Kaynakları toplama ve ayrıştırma |
| `worker/` | Veri çekimi işçileri ve zamanlama |
| `scripts/` | Tekrar kullanılabilir operasyon komutları |
| `tests/` | Kalıcı otomatik testler |
| `docs/` | Kurulum, mimari ve operasyon belgeleri |
| `.github/` | CI iş akışları |

## Yalnız bu bilgisayardaki dosyalar

| Konum | Kullanım |
| --- | --- |
| `data/` | Korpus, indirmeler, loglar ve işçi durumu; geçici dosya değildir |
| `uploads/` | Kullanıcının yüklediği belgeler; silinmez |
| `.env` | Yerel ayarlar ve sırlar; Git'e gönderilmez |
| `.venv/` | Python çalışma ortamı |
| `.local/tmp/` | Test ve tek seferlik deneme çıktıları |
| `.local/archive/` | Eski denemeler, çalışma kopyaları ve geri dönüş yedekleri |

Eski kök `.tmp-*` ve `.pytest-*` klasörleri, 2026-09-27 düzenlemesinde
`.local/archive/cleanup-<tarih-saat>/` altında adları korunarak bir araya getirilir.
Bu işlem kaynak kodunun veya veritabanının yeniden yapılandırılması değildir.
Arşivde sır veya test verisi bulunabileceğinden bu klasör yayımlanmaz.

Varsayılan `python -m pytest` artık `.local/tmp/pytest` kullanır.
**Pytest `--basetemp` hedefini temizleyebilir:** bu konuma kod, yedek veya
gerçek veri koymayın. Eşzamanlı testlerde farklı hedefler seçin, örneğin
`--basetemp=.local/tmp/pytest-rag-<benzersiz-kimlik>`.

Yeni geçici klasörleri proje köküne açmayın. Tekrar kullanılacak komutları
testleriyle birlikte `scripts/` altında tutun. Arşivlenmiş betikler eski mutlak
yollara veya commit'lere bağlı olabilir; incelemeden yeniden çalıştırmayın.
Bir yedeği geri almak için gerekli dosyayı arşivden inceleyerek kopyalayın;
mevcut çalışma dosyalarının veya `.git/index` dosyasının üzerine topluca yazmayın.
