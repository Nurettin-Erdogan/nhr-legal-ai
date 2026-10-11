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
| Resmî | `embedding IS NOT NULL` (~2,4M parça, resmî portalla doğrulanmış kaynaklar) | Küçük kısmi GIN dizini `idx_legal_chunks_search_vector_official` ile **tam** puanlanır; 2026-10-08'dan beri eşleşme 5 000'i aşarsa ilk 5 000'i (aşağıda "Resmî katmanın üst sınırı") |
| Doğrulanmamış toplu | `embedding IS NULL` (`bulk_seed`, `pending`) | Eşleşmelerin ilk `p_seed_cap` (önce 5 000, şimdi 3 000) tanesi puanlanır; aşılırsa `capped = true` |

Uygunluk koşulu (`ready` + doğrulanmış mevzuat, ya da bekleyen `bulk_seed` karar) tam sürümle aynıdır;
doğrulanmamış kayıtlar yine aranabilir ve ayrı gösterilir, yalnız tarama kapsamı sınırlanır.

API `LegalSearchResponse.partial` alanını döndürür: toplu katman sınırlandıysa ya da tam sürüm zaman
aşımına uğrayıp sınırlı sürüme düşüldüyse `true`. Zaman aşımı artık 503 değil **504** ve açıklayıcı mesajla
döner ("Arama zaman aşımına uğradı; daha belirgin sözcüklerle yeniden deneyin"). Gerçek veritabanı hatası 503
olarak kalır.

## Yedek basamaklar (`api/legal.py`)

1. Katmanlı VE araması (10 sn; önce 15 sn). Soğuk diskte yetişmezse:
2. Yalnız resmî katman, `p_seed_cap = 0` ve `p_official_cap = 1 500` (toplu katman atlanır, sonuç `partial = true`; 20 sn).
3. VE sorgusu hiç sonuç vermezse geniş (VEYA) yedek: `legal_rag_current_lexical_hits_official_bounded` yalnız
   resmî katmanda ilk 10 000 eşleşmeyi puanlar (hepsini puanlamak 382 bin eşleşmede 29 sn sürüyordu; bu 2,7 sn).
   Bu yedek her zaman kısmidir.

Hâlâ zaman aşımı olursa 504 döner.

## Resmî katmanın üst sınırı (2026-10-08, migration 050 / init 051)

Yukarıdaki tasarımda resmî katman **her** eşleşmeyi puanlıyordu. Çok sözcüklü aramada eşleşme azdır (ölçülen 11
aramada 33-5 673 parça) ve sorun olmaz; yaygın tek sözcükte katman patlıyordu:

| Arama | Resmî eşleşme | Önce | Sonra |
| --- | --- | --- | --- |
| tazminat | 492 070 | 35 sn, sonra **504** | 1,0-3,9 sn |
| kira | — | 13,3 sn | 2,7 sn |
| icra takibi | — | 16,4 sn | 4,2 sn |
| itirazın iptali icra inkar tazminatı | 54 291 | 16,0 sn | 3,5 sn |

Doğrulanmış korpus büyüdükçe bu süre de büyüyordu. Değişenler:

- **`p_official_cap` (varsayılan 5 000).** Resmî katmanda en çok bu kadar eşleşme puanlanır. Eşleşme sınırın
  altındaysa katman yine **tam** puanlanır ve sonuç değişmez; aşılırsa `capped = true` döner, yanıt `partial` olur.
  `p_official_cap <= 0` sınırı kaldırır. Üç parametreli eski çağrılar varsayılan sınırla çalışır.
- **Toplu katmanda uygunluk sırayla denetlenir.** Önceden taranan bütün parçalar kaynak tablosuyla birleştiriliyordu;
  artık resmî katmandaki gibi puan sırasıyla ve yalnız gerektiği kadar bakılır. Aynı sorguda dokunulan sayfa
  ~60 000'den ~37 000'e indi (5 aramada ölçüldü); sonuç kümesi aynıdır.
- **Toplu katman sınırı 5 000 → 3 000** (`_SEARCH_SEED_CAP`). Örnek zaten tablo sırasındaki ilk eşleşmelerdir;
  dokunulan sayfa ~19 000'e iner.
- **Zaman aşımı yedeği:** ilk deneme 10 sn'de bitmezse toplu katman atlanır ve resmî katmandan 1 500 eşleşme
  puanlanır (ölçülen: 0,2 sn). Yedeğin süresi 20 sn kalır: API yeni açıldığında arka plandaki sayım/ısınma sorguları
  diski meşgul eder ve açılıştan hemen sonraki ilk arama iki denemede de 10 sn'yi aşabiliyor (ölçüldü).

Sınır aşıldığında hangi parçaların puanlandığı tablo sırasına bağlıdır (dizin taramasının verdiği ilk eşleşmeler);
en iyi 5 000 değil **ilk** 5 000'dir. Bu yüzden sonuç her zaman "kısmi" diye işaretlenir.

Ölçüm (canlı korpus, veri çekimi ve embedding arkada çalışırken; `.local/search_bench.py`):

| Küme | Ortanca (ilk arama) | En uzun | Hata |
| --- | --- | --- | --- |
| 12 olağan arama, önce | 3,4 sn | 16,0 sn | 0 |
| 12 taze olağan arama, sonra | 1,8 sn | 3,1 sn | 0 |
| 12 geniş arama (tek sözcük), sonra | 2,7 sn | 4,2 sn* | 1* |

\* "tazminat" API yeniden başlatıldıktan hemen sonra soruldu ve 504 verdi (yukarıdaki açılış yükü); sonraki
denemede ve yeni yaygın sözcüklerde ("karar", "mahkeme", "işçi", "ceza") 0,8-2,2 sn.

Süreler önbellek durumuna ve arka plan yüküne göre oynar; "dokunulan sayfa" sayısı oynamaz ve asıl karşılaştırma odur.

Testler: `tests/test_capped_official_tier.py`.

## Yük altında dayanıklılık (2026-10-10)

10 Ekim gecesi arama ve asistan ~5 kat yavaşladı (aynı sorgularda ilk arama ortancası 1,8 sn → 11 sn; 12 sorgunun 10'u toplu
katmanda 10 sn'yi doldurup ancak ondan sonra resmî katmana düşüyordu; asistanın 20 soruluk ölçümünde ortanca 12 → 24 sn).

**Neden (ölçüldü):** embedding işçisinin kesin sayımı (`SELECT count(*) FROM legal_chunks WHERE embedding IS NOT NULL`,
`scripts/embed_chunks.py`) art arda çalışıyor, her biri ~4 dk sürüyordu: aynı anda 2 istemci × 2 paralel işçi, 20 sn'de 256 bin
sayfa disk okuması (~100 MB/sn), veritabanı kapsayıcısı CPU %276. Görünürlük haritası embedding'i yeni yazılan sayfalarda dolu
olmadığından dizin-yalnız tarama her satır için tabloya iniyordu. Bu yük altında toplu katmanın 31 GB'lık GIN dizini bellekte
kalamıyor: tek aramada dizin taraması 5,6 sn (6 bin fiziksel okuma), satır okuması 4,9 sn; resmî katman aynı sorguda 0,26 sn.
Veri tarafı bu oturumda değiştirilmedi; veri oturumuna bildirildi, o da sayımı 6 saatte bire indirdi ve görünürlük haritası
için `VACUUM (INDEX_CLEANUP OFF)` başlattı.

**Arama tarafında yapılanlar** (belirtiyi hafifletir, yükü kaldırmaz):

- Katmanlı aramanın ilk süresi 10 sn → 4 sn (`_SEARCH_FULL_TIMEOUT`). Resmî katman ilk denemede okunmuş olduğundan yedek
  çoğu zaman hemen döner; olağan yükte katmanlı arama 0,9-3,1 sn'de bittiği için 4 sn onu kesmez.
- Asistan araması üç basamaklı: tam sıralı (2,5 sn) → katmanlı (4 sn; önce 8 sn) → **yalnız resmî katman**, en çok 1 500
  eşleşme (4 sn). Önceden ikinci basamak da düşünce arama hata veriyor, soru ikinci kez baştan deneniyordu.
- **Toplu katman sigortası** (`api/ai/seed_tier.py`): sınırlı toplu katman taraması art arda 3 kez zaman aşımına uğrarsa
  2 dakika boyunca hiç denenmez; hukuk araması doğrudan resmî katmandan 1 500 eşleşmeyle, asistan araması yalnız resmî
  katmanla döner ve sonuç "kısmi" işaretlenir. Süre dolunca bir kez yeniden denenir. Tam sıralı sürümün yetişmemesi sigortayı
  açmaz (o, olağan koşulda da sık sık yetişmez). Durum süreç belleğindedir.

- **Az sonuçta bekleme:** toplu katman atlandığında (sigorta açık ya da ilk deneme yetişmedi) resmî sonuç sayfayı
  doldurmuyorsa toplu katman 10 sn'lik süreyle bir kez daha denenir (`_SEARCH_SPARSE_SEED_TIMEOUT`). Sigorta açıkken
  ölçülen aramalarda "vasi atanması kısıtlama" 2, "trampa sözleşmesi ayıp" 4 sonuçla dönüyordu; liste neredeyse boş
  kalıyor, "konu çok geniş" uyarısı da yanıltıyordu. Sayfa resmî sonuçla doluyorsa beklenmez.

Doğrulanmamış kayıtlar atlandıkları sürece hiç taranmaz; "resmî" diye sunulmaları söz konusu değildir, sonuç yalnız eksiktir
ve öyle işaretlenir.

Ölçüm (aynı yük sürerken; her küme taze sorgulardan): sigortasız ve 10 sn süreyle ortanca 11,2 sn → 4 sn süreyle 5,6 sn →
sigortayla 6,1 sn (bu son ölçüm VACUUM'un başladığı ana denk geldi; aralık 1,3-18,7 sn). Bu sayılar düzeltmenin değil
yükün büyüklüğünü gösterir. Hiçbir aramada hata dönmedi.

Bakım bittikten sonra (VACUUM 19 dk sürdü; önbellek soğuk, taze sorgular):

| Durum | Ortanca (ilk arama) | En uzun | Kısmi | Not |
| --- | --- | --- | --- | --- |
| Sigorta açık kalmışken | 1,7 sn | 5,7 sn | 12 / 12 | toplu katman hiç denenmedi; az sonuçlu aramalar 2-7 sonuçla döndü |
| "Az sonuçta bekleme" ile, yeniden başlatma sonrası | 4,5 sn | 8,2 sn | 5 / 12 | resmî sonucu az olan aramalarda doğrulanmamış kayıtlar geri geldi |

Soğuk önbellekte iki katmanlı sorgunun kendisi 4-12 sn sürüyor (6 sorguda doğrudan ölçüldü: 4,1-11,9 sn; 4,5-14,5 bin
fiziksel okuma, okuma başına ~1,2 ms). 8 Ekim'deki 1,8 sn'lik ortanca daha sıcak bir önbellekle alınmıştı; önbellek ısındıkça
bu sayılara yaklaşması beklenir, **yeniden ölçülmedi**.

Ölçüm dersi: arama yavaşladığında önce `pg_stat_activity`'ye bakın. Uzun süren bir `count(*)` ya da tarama varsa dizinle,
planla uğraşmadan önce o bulunmalı (bu sefer yarım saat plan ve dizin seçimi incelendi; asıl neden tek sorguda görünüyordu).

Testler: `tests/test_seed_tier_breaker.py`, `tests/test_retrieval_full_ranking_budget.py`.

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

`api/ai/retrieval.py` önce tam sıralı sözcük aramasını dener; kaliteyi korumak için hızlı olduğunda
aynen kalır. Zaman aşımına uğrarsa aynı sorgu `legal_rag_current_lexical_hits_tiered`
(toplu katmanda ilk 3 000, resmî katmanda en çok 5 000 eşleşme) ile 8 sn bütçeyle yeniden denenir; teşhiste dal durumu
`timeout_then_tiered`, `partial = true` olur. İkisi de düşerse hata verilir ("kaynak yok" denmez).
Ölçüm (soğuk): "kıdem tazminatı şartları" tam sürüm >30 sn, katmanlı 7,5 sn.

**Tam sıralı sürümün ilk süresi (2026-10-08):** geniş arama kolunda 8 sn yerine 2,5 sn
(`_FULL_RANKING_FIRST_BUDGET_MS`). Ölçülen altı olağan sorunun üçünde tam sürüm 8 sn'yi doldurup zaman aşımına
uğruyor, ardından katmanlı sürüm <1 sn'de dönüyordu (toplam ~9 sn); yetişen sorgular 0,2-1,1 sn'de bitiyordu.
Sonra: sekiz taze sorudan beşi tam sürümle 0,1-2,4 sn, üçü katmanlı sürümle 3,2-10,3 sn (soğuk diskte katmanlı sürümün
kendisi 0,7-7,8 sn sürebiliyor). Maddeye bağlı odaklı aramanın ortak 8 sn'lik süresi değişmedi.
Testler: `tests/test_retrieval_full_ranking_budget.py`.

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
