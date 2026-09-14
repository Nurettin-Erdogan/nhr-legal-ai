\if :{?embedding_dimensions}
\else
\echo 'HATA: embedding_dimensions zorunludur. Örnek: psql -v embedding_dimensions=1024 -f database/migrations/004_configure_embeddings.sql'
\quit 3
\endif

BEGIN;

CREATE OR REPLACE FUNCTION configure_embedding_storage(p_dimensions INT)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
  IF p_dimensions <= 0 OR p_dimensions > 2000 THEN
    RAISE EXCEPTION
      'HNSW vector indeksi için embedding_dimensions 1 ile 2000 arasında olmalıdır; verilen değer: %',
      p_dimensions;
  END IF;

  IF EXISTS (
    SELECT 1
    FROM document_chunks
    WHERE embedding IS NOT NULL
      AND vector_dims(embedding) <> p_dimensions
  ) THEN
    RAISE EXCEPTION
      'document_chunks içinde % boyutuyla uyumsuz embedding var.',
      p_dimensions;
  END IF;

  IF EXISTS (
    SELECT 1
    FROM legal_chunks
    WHERE embedding IS NOT NULL
      AND vector_dims(embedding) <> p_dimensions
  ) THEN
    RAISE EXCEPTION
      'legal_chunks içinde % boyutuyla uyumsuz embedding var.',
      p_dimensions;
  END IF;

  EXECUTE format(
    'ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(%s) USING embedding::vector(%s)',
    p_dimensions,
    p_dimensions
  );

  EXECUTE format(
    'ALTER TABLE legal_chunks ALTER COLUMN embedding TYPE vector(%s) USING embedding::vector(%s)',
    p_dimensions,
    p_dimensions
  );
END;
$$;

SELECT configure_embedding_storage(:embedding_dimensions);
DROP FUNCTION configure_embedding_storage(INT);

CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_hnsw
  ON document_chunks
  USING hnsw (embedding vector_cosine_ops)
  WHERE embedding IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_legal_chunks_embedding_hnsw
  ON legal_chunks
  USING hnsw (embedding vector_cosine_ops)
  WHERE embedding IS NOT NULL;

COMMIT;
