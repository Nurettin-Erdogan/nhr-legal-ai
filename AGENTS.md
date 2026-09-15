# nhr-legal-ai

NHR Yazılım'ın avukatlara sunulmak üzere geliştirdiği ticari Türk hukuku AI
platformu. Kişisel bir araç değil. Apilex referanslardan biridir, birebir
kopyalanmaz.

## Ürünün iki temel parçası

Bunlar alternatif değil, aynı platformun birlikte geliştirilen parçalarıdır.

1. **Merkezi Türk hukuk bilgi tabanı** — mevzuat, Yargıtay, Danıştay, AYM ve
   ileride diğer karar kaynakları.
2. **Kullanıcıya özel çalışma alanı** — müvekkil, proje/dava, yüklenen
   belgeler, sohbetler ve kaydedilen kaynaklar.

## Öncelik sırası

1. Mevcut RAG/citation çekirdeğini sağlamlaştır
2. Mevzuat ingestion
3. Yargıtay korpusunu büyüt, metadata kalitesini iyileştir
4. Belge yükleme, parsing, document chunking, proje bazlı RAG
5. Sohbet geçmişi
6. Müvekkil / proje / belge / sohbet ilişkileri
7. Belge üretme ve analiz akışları
8. Gemini/Claude/OpenAI çoklu sağlayıcı yönlendirmesi

## Değişmez kurallar

**Kaynaksız hukuki iddia üretilmez.** Doğrulanabilir kaynak olmadan karar,
mevzuat maddesi veya hukuki sonuç uydurulamaz. Kaynak yetersizse bu açıkça
söylenir. Bu kural model promptunda kalmaz; üretilen cevabın gerçekten
getirilen kaynaklara dayandığı kod tarafında doğrulanır.

**AI katmanı sağlayıcıdan bağımsız kalır.** İlk geliştirme Gemini ile devam
eder ama üretim ve embedding çağrıları arayüz arkasında tutulur. Model sıfırdan
eğitilmez.

**Güvenlik ve KVKK sonradan eklenmez.** Kullanıcı izolasyonu, RLS, denetim
kaydı ve secret yönetimi mimarinin parçasıdır. Yeni bir tablo veya uç nokta
eklenirken erişim kontrolü aynı commit'te düşünülür. Uygulama veritabanına
`nhr_runtime` rolüyle bağlanır; `nhr_app` yalnızca migration, korpus aktarımı
ve kimlik doğrulama öncesi sorgular içindir. Kullanıcıya ait tablolara satır
eklerken kimliği uygulamada üret, `RETURNING id` kullanma — gerekçesi
[docs/database-setup.md](docs/database-setup.md) içinde.

**`main` dalına doğrudan push veya merge yapılmaz.** Geliştirme
`feature/legal-ai` üzerinde sürer.

## Teknik yerleşim

| Dizin | Sorumluluk |
| --- | --- |
| `database/` | V2 şeması, RLS politikaları, bütünlük tetikleyicileri, migrationlar |
| `ingestion/` | Hukuk korpusunu toplama, ayrıştırma, parçalama ve aktarma |
| `api/` | FastAPI: hukuk arama, RAG, kimlik doğrulama, projeler |
| `web/` | Next.js arayüzü |

Veritabanı PostgreSQL 16 + pgvector, Docker ile `localhost:5433`. Kurulum ve
migration adımları için [docs/database-setup.md](docs/database-setup.md),
korpus aktarımı için [docs/ingestion-yargitay.md](docs/ingestion-yargitay.md)
ve [docs/ingestion-mevzuat.md](docs/ingestion-mevzuat.md).

Testler ağ ve veritabanı olmadan çalışır; veritabanı testleri
`NHR_TEST_DATABASE_URL` tanımlıysa devreye girer ve yazdıklarını geri alır.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
