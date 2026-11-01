-- Tam taramayı periyodik tekrarlayan kaynaklar (ör. AYM) aynı kaydı her turda karantinaya
-- yeniden yazıyordu. Uygulama artık açık kaydı güncelliyor; bu indeks o aramayı karşılar.
-- CONCURRENTLY: tabloyu kilitlemez; transaction dışında (psql -f) çalıştırılmalıdır.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_legal_source_quarantine_open_lookup
    ON legal_source_quarantine (source_adapter, external_id, reason_code)
    WHERE resolved_at IS NULL;
