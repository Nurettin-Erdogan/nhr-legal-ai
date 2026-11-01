\set ON_ERROR_STOP on
-- Mevzuat anlam araması güncel maddeleri göremiyordu (2026-10-30).
--
-- Sorun: `legislation_chunk_vectors` (migration 060) bir KOPYA tablodur ve satırı yalnız legal_chunks.embedding (eski 768 boyutlu
-- model) dolu olan parçalar için oluşur. Mevzuat yeniden aktarılınca ortaya çıkan yeni sürümlerin (ör. TMK m. 737, 740, 750
-- revision 2, is_current) 768 boyutlu vektörü hiç üretilmedi; bu yüzden kopya tabloda satırları yok, `embed_legislation_m3.py` yalnız
-- "satırı olan ama embedding_m3 boş" parçaları doldurduğundan onlara hiç ulaşmadı. Ölçüm: güncel mevzuat parçalarının 23.474'ü
-- (%23) m3 vektörsüzdü; gündelik dille sorulan soruda en yakın adaylar hep eski (is_current = false) sürümlerdi ve güncel süzgeçte
-- eleniyordu ("Komşum ağacımın dallarını kesti" 0 kaynak).
--
-- Çözüm: eski model vektörü artık zorunlu değil. Eksik satırları `scripts/embed_legislation_m3.py` kendisi (idempotent) oluşturur
-- ve doldurur. Tetikleyiciye dokunulmaz: karar parçalarının toplu aktarımına satır başına ek sorgu bindirilmez.
BEGIN;
ALTER TABLE public.legislation_chunk_vectors ALTER COLUMN embedding DROP NOT NULL;
COMMIT;
