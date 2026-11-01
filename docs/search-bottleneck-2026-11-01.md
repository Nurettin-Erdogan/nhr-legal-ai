# Kaynak araması darboğaz teşhisi — 2026-11-01

Bu çalışma teşhistir: üretim sorguları, indeksler, süre sınırları ve veri
değiştirilmedi. Model cevabı üretilmedi, kredi harcanmadı. Sentetik kamusal
sorgular kullanıldı; özel belge/sohbet içeriği okunmadı. SQL planında yalnız
SELECT çalıştırıldı. Genel sohbetin kullandığı paralel mod da ayrıca sınandı.

## Ölçülen dallar

| Sorgu | Madde | Karar ANN | Mevzuat ortak vektör | Mevzuat M3 | Kelime araması/yedekler | Toplam |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Kira bildirimi, seri | 0.138 | 16.963 | — | — | 12.957 | 30.596 |
| İşe iade, seri | — | 15.215 | 10.722 | 7.522 | 10.519 + 7.163 | 51.725 |
| Havale/itiraz, seri | — | 12.624 | 5.963 | 1.933 | 4.001 | 24.931 |
| İşe iade, paralel | — | 7.923 | 4.650 | 3.455 | 4.867 + 7.342 | 16.104 |

Süreler saniyedir. Paralel satır genel sohbetin mevcut
`parallel_public_vectors=True` yoludur; yeni bir optimizasyon uygulanmadı.
Seri ölçüm bütün sohbet isteklerini temsil etmez. İki mod farklı zamanlarda
ve değişen disk/önbellek koşullarında çalıştığı için kontrollü hızlanma oranı
çıkarılamaz. Dört ölçüm de kısmi döndü; kelime kolunda zaman aşımı ve yedek
arama görüldü. Gerçek cevap üretimi ve resmî web araştırması bu sürelerde yoktur.

## İndeks ve EXPLAIN kanıtı

- İkili HNSW `idx_legal_chunks_embedding_bq`: geçerli/hazır, 8499 MB.
- Genel GIN metin indeksi: 31 GB; official GIN: 8398 MB; ikisi de geçerli/hazır.
- PostgreSQL `shared_buffers`: 327680 × 8 KB = 2.5 GiB.
- Docker/WSL'ye görünen toplam bellek: yaklaşık 6.768 GiB.
- NHR DB gözlem anında 4.732 GiB kullanıyordu. Bu değerler bir örneklem olup
  yalnız bellek büyütmenin sorunu çözeceğini kanıtlamaz.
- `EXPLAIN (ANALYZE, BUFFERS)` karar ANN sorgusu: 13.209 sn.
- HNSW coarse index scan: 10.584 sn; 600 aday; 15040 shared read block
  (yaklaşık 117.5 MiB), 3911 shared hit block.
- Tüm sorgu: 17876 shared read block (yaklaşık 139.7 MiB), 15863 hit;
  geçici diske sıralama taşması yok (temp read/write = 0).
- Plan beklenen HNSW indeksini kullanıyor; bu örnekte eksik ANN indeksi veya
  tüm vektörleri sıralayan sequential scan yok. Adayların tam vektörleri ve
  güvenlik/kaynak metadata join'leri ek erişim yapıyor; RLS kaldırılmadı.
- `DataFileRead` beklemesi canlı oturumlarda görüldü. PostgreSQL shared read
  blok sayısı işletim sistemi fiziksel disk okumasıyla birebir aynı değildir.

## Arka plan yükü

Bakım bağlantısıyla salt okunur durum sorgusunda yaklaşık iki saattir aktif
bir autovacuum işçisi `DataFileRead` beklerken görüldü. Aktif indeks oluşturma
işi yoktu. Autovacuum'un gecikmeye katkısı kontrollü önce/sonra ölçülmedi;
yalnız mevcut ek I/O yükü olarak kaydedildi. İptal edilmedi/devre dışı bırakılmadı.

## Sonuç ve sonraki çalışma

Kanıtlanan darboğazlar:

1. Hazır embedding üretimi değil, vektör indeks/aday erişimi ve kaynak getirme.
2. Yavaş kelime aramalarının zaman aşımı, ardından yedek ve kavram araması
   zinciri; bu durum kısmi sonuç işaretini de tetikliyor.
3. Seri çağrı yollarında bağımsız dalların süreleri toplanıyor. Genel sohbet
   bazı yolları zaten paralelleştirdiği için tek başına yeni paralellik çözüm değil.

İlerleme sırası: kontrollü aynı-sorgu plan/buffer karşılaştırması; kaynak ve
RLS koşullarını koruyarak kelime sorgusunu daha seçici yapmak; aday metadata
erişimindeki tekrarları incelemek; gerçek bellek/çalışma kümesi ve bakım I/O
yükünü hesaba katarak önbellek/altyapı değerlendirmesi. Aday sayısını azaltıp
arama kapsamını sessizce daraltmak veya doğrulanmış kaynak filtresini
kaldırmak hız kazanımı olarak kabul edilmemeli.

Ham kanıtlar git dışı `.local` dosyalarında:
`embedding-retrieval-branches-20261101.json`,
`embedding-retrieval-parallel-20261101.json`, `semantic-explain-20261101.json`.
