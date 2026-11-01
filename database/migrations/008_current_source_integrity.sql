\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE court_decision_details
  ADD COLUMN is_current BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE legislation_details
  ADD COLUMN is_current BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE court_decision_details AS detail
SET is_current = source.is_current
FROM legal_sources AS source
WHERE source.id = detail.legal_source_id;

UPDATE legislation_details AS detail
SET is_current = source.is_current
FROM legal_sources AS source
WHERE source.id = detail.legal_source_id;

CREATE OR REPLACE FUNCTION sync_legal_detail_current_from_source()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.is_current IS DISTINCT FROM OLD.is_current THEN
    UPDATE court_decision_details
    SET is_current = NEW.is_current
    WHERE legal_source_id = NEW.id;

    UPDATE legislation_details
    SET is_current = NEW.is_current
    WHERE legal_source_id = NEW.id;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER legal_sources_sync_detail_current
AFTER UPDATE OF is_current ON legal_sources
FOR EACH ROW
EXECUTE FUNCTION sync_legal_detail_current_from_source();

CREATE OR REPLACE FUNCTION enforce_legal_detail_current()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  SELECT source.is_current
  INTO NEW.is_current
  FROM legal_sources AS source
  WHERE source.id = NEW.legal_source_id;
  RETURN NEW;
END;
$$;

CREATE TRIGGER court_decision_details_enforce_current
BEFORE INSERT OR UPDATE OF legal_source_id, is_current ON court_decision_details
FOR EACH ROW
EXECUTE FUNCTION enforce_legal_detail_current();

CREATE TRIGGER legislation_details_enforce_current
BEFORE INSERT OR UPDATE OF legal_source_id, is_current ON legislation_details
FOR EACH ROW
EXECUTE FUNCTION enforce_legal_detail_current();

SET CONSTRAINTS ALL IMMEDIATE;

CREATE UNIQUE INDEX uq_court_decision_current_natural
  ON court_decision_details (
    lower(court_name),
    lower(COALESCE(chamber, '')),
    docket_no,
    decision_no
  )
  WHERE is_current AND docket_no IS NOT NULL AND decision_no IS NOT NULL;

CREATE UNIQUE INDEX uq_legislation_current_natural
  ON legislation_details (legislation_type, law_no, article_no)
  WHERE is_current AND law_no IS NOT NULL AND article_no IS NOT NULL;

COMMIT;
