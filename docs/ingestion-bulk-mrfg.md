# Toplu üçüncü taraf korpus (mrfg) ve gece çalışması

`mrfg/turkish-court-decisions` (HuggingFace, CC0) Yargıtay ve Danıştay kararlarının
üçüncü taraf bir derlemesidir. **Resmî portalla doğrulanmış sayılmaz.** Kayıtlar
`ingestion_method = 'bulk_seed'`, `ingest_status = 'pending'`,
`metadata.official_verified = false` ile girer; arayüzde resmî sayıdan ayrı gösterilir
ve cevaplarda "üçüncü taraf, resmî portalla doğrulanmadı" notuyla anılır.

Alınmayanlar: UYAP Emsal ve AYM kayıtları (bu kaynaklarda doğrulama yolu yok) ve
maskeli (`masked_count > 0`: TCKN/IBAN/telefon vb.) kayıtlar.

## Örnek doğrulama (ölçüm, veritabanına yazmaz)

`scripts/verify_hf_sample.py --source yargitay|danistay --n 100 --delay 15` rastgele
kararları resmî portaldan çekip metinleri karşılaştırır. 2026-09-19 ölçümü: 269 karar
(Yargıtay 49, Danıştay 220), içerik sapması yok; farklar boşluk/satır sonu; 27 karar
portalda açılamadı. Bu, kaynağın kalitesini gösterir; **tek tek doğrulamanın yerine geçmez**.

## Aktarım

```powershell
python scripts/import_hf_mrfg.py --source danistay
python scripts/import_hf_mrfg.py --source yargitay
```

Dosya dosya indirir, aktarır, siler; `bulk:hf_mrfg:<kaynak>` kontrol noktasıyla yeniden
başlatılabilir. Resmî `ready` kayıtla çakışanlar otomatik atlanır (`official_ready`).
Chunk yazmaz.

## Parçalama (aranabilir yapma)

```powershell
python scripts/chunk_bulk_seed.py --workers 12
```

- İşçiler `hashtext(id) mod N` ile bölünür; `NOT EXISTS (chunk)` sayesinde tekrar
  çalıştırmak çift parça üretmez.
- **İşçi sayısını değiştirirsen** `bulk:pending_chunks:*` kontrol noktalarını sıfırla ve
  yeni sayıya göre `last_id`'yi, ilk parçalanmamış kararın hemen öncesine ayarla; yoksa
  her işçi baştan, parçalanmışları tek tek atlayarak başlar ve disk tıkanır.
- Öldürülen işçinin veritabanı sorgusu sürer: yeniden başlatmadan önce yetim
  `SELECT ls.id, ls.raw_text ...` oturumlarını sonlandır.
- Darboğaz işlemci değil disk (BufferIO/WALWrite); işçi sayısını artırmak hızlandırmaz.
- Bitince `VACUUM (ANALYZE, PARALLEL 0)` gerekir (`scripts/post_chunk_maintenance.py`).

## İşletme (kesintisiz çalışma)

| Bileşen | Görev |
| --- | --- |
| `scripts/sentinel.ps1` | 7 resmî kaynak kolunu (Yargıtay/Danıştay kampanyaları, AYM, KDK, mevzuat, doğrulama) yeniden başlatır |
| `scripts/supervisor.ps1` | Nöbetçi, API, DB kabı, parçalama işçileri, disk alanı (<40 GB'da durdurur), bakım |
| `scripts/keep_awake.ps1` | Uykuyu engeller (Windows ayarını değiştirmez) |

Durdurmak için `data/campaign/SENTINEL_STOP` ve `data/campaign/SUPERVISOR_STOP`
dosyalarını oluştur. Bilgisayar yeniden başlarsa hiçbiri kendiliğinden gelmez.

## Arama performansı (~21M parça)

Darboğaz disk okumasıdır (arama indeksi 31 GB, parça tablosu 29 GB). Önlemler:

- **PostgreSQL ayarları ([docker-compose.yml](../docker-compose.yml)):** `shared_buffers`
  128 MB → 6 GB, `effective_cache_size` 10 GB, `shm_size` 64 MB → 1 GB (paralel taramanın
  "could not resize shared memory segment" hatasını bitirir), SSD için `random_page_cost=1.5`
  ve `effective_io_concurrency=200`. Ölçülen kazanç (2026-09-20, soğuk önbellekle):

  | Sorgu | 128 MB | 6 GB |
  | --- | --- | --- |
  | kıdem & tazminat | 38-52 sn | 18-20 sn |
  | iptal & tapu & tescil | 67-69 sn | 47-55 sn |
  | haksız & fesih | 0,4-4 sn | 0,2-0,4 sn |

  Uçtan uca (API, önbellek ısındıktan sonra): 8 yaygın sorgunun 7'si 3,5 sn altında,
  yalnız çok yaygın kalıplar (`manevi tazminat`) ~20 sn. Öncesinde bazı sorgular 45 sn'de
  zaman aşımıyla 503 dönüyordu.
- Arama işleminde `work_mem = 64MB`, `jit = off` (varsayılan 4 MB ile sıralama diske taşıyor).
- Tam sürüm 12 sn'de bitmezse `legal_rag_current_lexical_hits_bounded` (migration 018):
  eşleşmelerin ilk 60 bin tanesini sıralar; süre öngörülebilir, kapsam kısmi.
- Docker'ın 64 MB `/dev/shm`'i büyük paralel taramada dolar (`could not resize shared memory
  segment`, DiskFull); API aynı sorguyu paralel işçisiz yeniden dener.
- Kalan yavaş nokta çok yaygın kalıplardır; sınırlı aramaya geçiş eşiği (12 sn) düşürülerek
  ya da sık aranan kararlar için ayrı bir hızlı alt küme ile iyileştirilebilir.
- RAG hattı (`api/ai/retrieval.py`) aynı fonksiyonu kullanır; yalnız `work_mem` eklendi,
  sınırlı sürüme geçiş yok.

## Doğrulama (üçüncü taraf kayıtları resmîleştirme)

`scripts/verify_seeds.py --source yargitay|danistay` kayıtları **kimlikle doğrudan** çeker
(arama isteği harcamaz), metin boşluk farkları dışında aynıysa kaydı `ready` + resmî
`ingestion_method` yapar ve resmî metni yazar. Uyuşmazsa kayıt değiştirilmez,
`metadata.verify_status='mismatch'` işaretlenir.

- **Hız kendini ayarlar (AIMD):** 429/CAPTCHA'da aralık büyür, 20 başarıda %5 küçülür
  (taban `--min-delay`, varsayılan 4,5 sn ≈ 13 istek/dk). Portal sınırı IP başına olduğundan
  işçi sayısını artırmak hızlandırmaz; tek süreç sınırın hemen altında kalır.
- **Danıştay'ın "hiddencontent bulunamadı" yanıtı** hız sınırının yumuşak biçimidir, kararın
  eksik olduğu anlamına gelmez: yavaşlayıp aynı kaydı yeniden dener.
- **Metin karşılaştırması** üç biçimde dener: ham resmî metin, üçüncü taraf temizliğinden
  geçmiş hâli ve boşlukları tümüyle atılmış anahtar. (Kayıtlı metinlerde `"İçtihat Metni"`
  başlığının bitişik yazılması gibi boşluk kayıpları var.)
- **Atıf önceliği:** cevapta bir `bulk_seed` kaydına atıf yapılınca
  `api/ai/verification_queue.py` onu `seed_verification_queue` tablosuna ekler; doğrulayıcı
  her turda önce bu kuyruğu boşaltır. Portala giden süreç yine tektir, ek CAPTCHA riski yok.
- **Hız gerçeği:** portal başına ≈700 karar/saat. 10,2 milyon kayıt bu hızla ≈300 gün eder;
  bu yüzden kapsam hedefi "hepsi" değil, "atıf yapılan + en yeni" olmalıdır.
- Kampanyalar (`backfill_campaign.py`) aynı portal sınırını paylaşır: doğrulayıcı çalışırken
  `data/campaign/PAUSE_CAMPAIGNS` dosyası nöbetçinin kampanya başlatmasını engeller.

## Kapsam boşlukları (2026-09-20 ölçümü)

| Eksik | Miktar | Neden |
| --- | --- | --- |
| UYAP Emsal (yerel/istinaf) | ~815.700 | Resmî portal adaptörü yok, doğrulanamaz |
| Yargıtay 6 Ağu 2026 sonrası | bilinmiyor | Veri seti anlık görüntüsünden yeni |
| Danıştay 13 May 2026 sonrası | binlerce | Veri setinde 2026 yılı yalnız 312 karar |
| Yargıtay 1997 öncesi | bilinmiyor | Veri seti 1997'de başlıyor |
| Maskeli + karantina | 4.350 + 1.829 | KVKK maskesi / bozuk kayıt |

Bu boşlukları arama tabanlı kampanyalar kapatır; doğrulayıcı yalnız elimizdeki kayıtları
resmîleştirir.

## Bilinen tuzaklar

- `worker/known_sources.py` sorguları `source_type` filtresi olmadan tekil indeksi
  (`source_type, external_id`) kullanamaz ve milyonlarca satırda tam tarama yapar;
  filtre eklendi.
- Kampanyalar tam metni olan kayıtları "zaten var" sayıyordu; `bulk_seed` kayıtlar bu
  istisnadan çıkarıldı (`worker/known_sources.py`), yoksa hiç doğrulanmazlardı.
- API ağır `count(*)` değerlerini `data/cache/slow_counts.json` içinde saklar; açılışta
  bunu sunar, arka planda yeniler. Parça sayısı `n_live_tup` ile canlı (yaklaşık) gösterilir.
- Ağır sayımlar **ayrı sorgularda** çalışmalı: tek blokta iken 21M satırlık chunk sayımı
  120 sn sınırını aşıyor ve aynı istisna üçüncü taraf sayısını da tazelenmemiş bırakıyordu
  (kutudaki sayı doğrulama ilerlese de donuk kalıyordu).
