-- "Embedding hazır" sayacı: 21M parçalı tabloda `embedding IS NOT NULL` sayımı tam tarama
-- gerektiriyordu (>120 sn, sayaç donuyordu). Kısmi indeks yalnız embedding'i olanları tutar;
-- sayım indeks-only taramayla milisaniyeler sürer.
-- CONCURRENTLY: tabloyu kilitlemez; transaction dışında (psql -f) çalıştırılmalıdır.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_legal_chunks_embedded
    ON legal_chunks (id)
    WHERE embedding IS NOT NULL;
