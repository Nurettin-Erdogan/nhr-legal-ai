# Hukuk araması: soğuk sorgu performansı

## Sorun

`/api/legal/search` ilk çağrıda 10–40 sn sürüyor, bazen 503 ("veritabanına ulaşılamıyor") dönüyordu.

Neden: eşleşen **her** parça `ts_rank_cd` ile puanlanıyordu. Puan için parçanın `tsvector`'ü (TOAST) okunur;
~28M parçalık korpusta yaygın bir sözcük yüz binlerce rastgele okuma demektir. Docker/WSL2 diskinde tek
istekli okuma ~2,2 ms olduğundan soğuk sorgu on saniyeler sürer. Paralel tarama IO'yu ~4 kat artırır ama
yetmez.

## Çözüm: katmanlı arama

`legal_rag_current_lexical_hits_tiered(p_query, p_limit, p_seed_cap)` (migration 032 / init 033):

| Katman | Kapsam | Davranış |
| --- | --- | --- |
| Resmî | `embedding IS NOT NULL` (~2,4M parça, resmî portalla doğrulanmış kaynaklar) | Küçük kısmi GIN dizini `idx_legal_chunks_search_vector_official` ile **tam** puanlanır, örnekleme yok |
| Doğrulanmamış toplu | `embedding IS NULL` (`bulk_seed`, `pending`) | Eşleşmelerin ilk `p_seed_cap` (5 000) tanesi puanlanır; aşılırsa `capped = true` |

Uygunluk koşulu (`ready` + doğrulanmış mevzuat, ya da bekleyen `bulk_seed` karar) tam sürümle aynıdır;
doğrulanmamış kayıtlar yine aranabilir ve ayrı gösterilir, yalnız tarama kapsamı sınırlanır.

API `LegalSearchResponse.partial` alanını döndürür: toplu katman sınırlandıysa ya da tam sürüm zaman
aşımına uğrayıp sınırlı sürüme düşüldüyse `true`. Zaman aşımı artık 503 değil **504** ve açıklayıcı mesajla
döner ("Arama zaman aşımına uğradı; daha belirgin sözcüklerle yeniden deneyin"). Gerçek veritabanı hatası 503
olarak kalır.

## Yedek basamaklar (`api/legal.py`)

1. Katmanlı VE araması (15 sn). Soğuk diskte doğrulanmamış toplu katman yetişmezse:
2. Yalnız resmî katman, `p_seed_cap = 0` (toplu katman atlanır, sonuç `partial = true`).
3. VE sorgusu hiç sonuç vermezse geniş (VEYA) yedek: `legal_rag_current_lexical_hits_official_bounded` yalnız
   resmî katmanda ilk 10 000 eşleşmeyi puanlar (hepsini puanlamak 382 bin eşleşmede 29 sn sürüyordu; bu 2,7 sn).
   Bu yedek her zaman kısmidir.

Hâlâ zaman aşımı olursa 504 döner.

## Dizini kurma (büyük veritabanı)

`CREATE INDEX CONCURRENTLY` transaction dışında çalışır (`psql -f`). Büyük korpusta ~10 dk sürer ve yazmayı
engellemez. **`lock_timeout` koyma**: son aşamada eski transaction'ları (ör. uzun süren sayım sorguları)
bekler; kısa bir `lock_timeout` dizini geçersiz (`indisvalid = false`) bırakır. Bu olursa:

```sql
SET maintenance_work_mem = '2GB'; SET lock_timeout = 0;
REINDEX INDEX CONCURRENTLY public.idx_legal_chunks_search_vector_official;
```

## Testler

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_tiered_lexical_search.py -q
```

Veritabanı testleri `NHR_TEST_DATABASE_URL` ister: resmî katmanın eksiksiz puanlandığını, toplu katman
sınırını ve `capped` bayrağını, katmanlı sonucun sınır aşılmadığında tam fonksiyonla aynı olduğunu ve
uygunluk koşulunun iki katmanda da geçerli olduğunu doğrular.

## Cevap hattı (RAG getirmesi)

`api/ai/retrieval.py` önce tam sıralı sözcük aramasını (8 sn) dener; kaliteyi korumak için hızlı olduğunda
aynen kalır. Soğuk diskte zaman aşımına uğrarsa aynı sorgu `legal_rag_current_lexical_hits_tiered`
(toplu katmanda ilk 3 000 eşleşme) ile 8 sn bütçeyle yeniden denenir; teşhiste dal durumu
`timeout_then_tiered`, `partial = true` olur. İkisi de düşerse hata verilir ("kaynak yok" denmez).
Ölçüm (soğuk): "kıdem tazminatı şartları" tam sürüm >30 sn, katmanlı 7,5 sn.

## Araştırma sayfası (`/api/ai/sources`)

`legal_rag_research_page` eşleşen HER parçanın tsvector'ünü açar (ifade denetimi + `ts_rank_cd`). Canlı korpusta (2026-10-04)
"kıdem tazminatı", "ihtiyati tedbir", "işe iade", "tapu iptal tescil" **90 sn'de bile bitmedi**; API 15 sn'de kesip 504 veriyordu.
Neden: metin ancak ifade ("kıdem tazminatı" kelimeleri yan yana mı?) ve puan için gerekiyor, yaygın konuda bu yüz binlerce rastgele okuma.

`legal_rag_research_page_bounded` (migration 037, init 038) adayları önce **yalnız dizinle** seçer (`p_filter`: ifadesiz AND sorgusu;
GIN metin açmadan yanıtlar), metni yalnız sınırlı sayıda aday için açar:

- resmî katman (`embedding IS NOT NULL`, kısmi GIN dizini): ilk `p_max_official` aday,
- toplu/doğrulanmamış katman: ilk `p_max_seed` aday (0 = hiç taranmaz).

Adaylar sınırların altındaysa sonuç eski fonksiyonla aynıdır (`partial = false`). Sınır aşılırsa `partial = true`: toplam "en az" sayıdır,
yanıtta `partial` alanı gelir ve arayüz "Konu çok geniş, liste eksik olabilir; aramayı daralt" uyarısı gösterir. İfade koşulu korunur
(adaylar ifadesiz seçilse de sonuçta ifade şarttır); uygunluk koşulu ve resmî/doğrulanmamış ayrımı eski fonksiyonla aynıdır.

`api/ai/research.py` üç kademe dener (`RESEARCH_ATTEMPTS`): 2 000 resmî + 1 000 toplu aday (9 sn); zaman aşımında 500 resmî, toplu katman yok (7 sn);
son olarak 120 resmî (5 sn). Soğuk disk ve yazan arka plan işleri (embedding döngüsü) canlıda ilk kademeyi sık sık aşıyor. Hiçbiri yetmezse 504 (sahte boş/tam liste yok). Migration 037 uygulanmamış veritabanında eski tam arama (15 sn) kullanılır.

**Sıralama:** önce resmî doğrulanmış kaynaklar (`ingest_status = 'ready'`), sonra puan. Sayfa yalnız doğrulanmış sonuçları gösterdiğinden, yüksek puanlı doğrulanmamış
toplu kayıtlar ilk sayfaları doldurup listeyi boş bırakıyordu (ilk sayfada 10 adaydan 2 kaynak + 8 "doğrulama bekleyen"). Sıralamadan sonra ölçüm (2026-10-04, 5 yaygın konu,
ilk iki sayfa): her sayfada 10 doğrulanmış kaynak, 0 bekleyen. Doğrulanmamış kayıtlar yine hiçbir zaman "resmî" diye sunulmaz; yalnızca sırada sonraya gider.

Ölçüm (canlı korpus, soğuk; ilk sayfa / sonraki sayfa): kıdem tazminatı 10,8 / 0,6 sn · ihtiyati tedbir 9,2 / 0,4 · işe iade 7,3 / 0,6 ·
boşanma nafaka 8,2 / 0,2 · tapu iptal tescil 11,4 / 1,0 · kira tespit 12,1 / 0,6. Önceki durum: 40 sn ile >90 sn arası, çoğu 504.

```powershell
# Uygulama (önce test veritabanına, sonra canlıya)
docker exec -i nhr-legal-ai-db psql -U nhr_app -d nhr_legal_ai_test -v ON_ERROR_STOP=1 < database/migrations/037_research_page_bounded.sql
```

## Kapsam dışı

RAG hattının kendi aramaları yukarıdaki katmanlı fonksiyonları kullanır; araştırma sayfası artık sınırlı fonksiyonu kullanır.
