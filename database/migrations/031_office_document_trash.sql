-- Dava belgeleri için çöp kutusu: önce çöpe taşınır (geri alınabilir), sonra kalıcı silinir.
--
-- `deleted_at` dolu belge çöptedir: listelerde, aramada, indekslemede ve yineleme denetiminde görünmez
-- (uygulama katmanı `deleted_at IS NULL` filtresini uygular; bkz. docs/office-document-trash.md).
-- Türetilmiş `documents` / `document_chunks` kayıtlarına dokunulmaz, bu yüzden geri yükleme anlıktır
-- ve belge yeniden indekslenmez.
--
-- Kalıcı silme `ON DELETE CASCADE` ile türetilmiş metni ve parçaları da siler; önce o belgeye atıf
-- yapan sohbet cevapları uygulama tarafından temizlenir (`citations.document_chunk_id` RESTRICT'tir).
ALTER TABLE office_case_documents
  ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- Çöp kutusu listesi ve süresi dolanların toplanması için.
CREATE INDEX IF NOT EXISTS idx_office_case_docs_trash
  ON office_case_documents (owner_id, deleted_at)
  WHERE deleted_at IS NOT NULL;
