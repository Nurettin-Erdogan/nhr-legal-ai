-- Büro (UYAP dahil) dava belgelerinin metinleri, RAG'in mevcut belge hattına (`documents` /
-- `document_chunks`: parça, tsvector, embedding, atıf) bağlanır. Dosyanın kaynağı
-- `office_case_documents` kalır; burada yalnız türetilmiş metin ve durum tutulur.
--
-- Kapsam: türetilen `documents` satırı `project_id IS NULL` ile yaratılır, yani RLS gereği yalnız
-- yükleyen kullanıcıya görünür. Dava kapsamı sorguda `office_case_documents.case_id` üzerinden
-- türetilir; belge sonradan başka davaya bağlanırsa ayrıca güncelleme gerekmez.
--
-- Silme: kaynak belge silinirse türetilmiş belge ve tüm parçaları `ON DELETE CASCADE` ile silinir.
ALTER TABLE documents
  ADD COLUMN IF NOT EXISTS office_case_document_id UUID
  REFERENCES office_case_documents(id) ON DELETE CASCADE;

-- Bir kaynak belgenin en çok bir türetilmiş kaydı olur; yeniden indeksleme aynı satırı günceller.
CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_office_case_document
  ON documents (office_case_document_id)
  WHERE office_case_document_id IS NOT NULL;

-- Yabancı anahtar denetimi RLS'i atladığı için başkasının belgesine bağlanma bu tetikleyiciyle
-- engellenir: işlev çağıranın yetkisiyle çalışır, yani yalnız kendi belgelerini görür.
DROP TRIGGER IF EXISTS documents_own_office_document ON documents;
CREATE TRIGGER documents_own_office_document
  BEFORE INSERT OR UPDATE OF office_case_document_id ON documents
  FOR EACH ROW
  WHEN (NEW.office_case_document_id IS NOT NULL)
  EXECUTE FUNCTION office_require_own_references('office_case_document_id:office_case_documents');
