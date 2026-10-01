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

## Kapsam dışı

Araştırma sayfası (`legal_rag_research_page`) hâlâ eski fonksiyonu kullanır.
