import json
import os
from dataclasses import replace

import pytest

from ingestion.mevzuat.identity import article_headings, validate_record_identity
from ingestion.mevzuat.parser import record_from_article
from ingestion.mevzuat.text_verify import extract_article_text
from api.ai.retrieval import question_article_numbers, question_law_numbers
from scripts.repair_legislation_identities import build_plan, apply_plan, load_rows


@pytest.mark.parametrize("article", ["18", "18/A", "18/B", "EK 18", "GEÇİCİ 18"])
def test_pdf_extraction_never_confuses_distinct_articles(article):
    text = "\n\n".join(f"{prefix}MADDE {no}- Metin {identity}." for prefix,no,identity in [
        ("", "18", "18"), ("", "18/A", "18/A"), ("", "18/B", "18/B"),
        ("EK ", "18", "EK 18"), ("GEÇİCİ ", "18", "GEÇİCİ 18")])
    result = extract_article_text(text,article)
    assert len(article_headings(result)) == 1
    assert article_headings(result)[0].identity == article


def test_numeric_pdf_lookup_cannot_accept_only_a_lettered_article():
    assert extract_article_text("MADDE 18/A- Metin.","18") == ""


def test_parser_preserves_lettered_identity_and_original_portal_number():
    record = record_from_article(document={"mevzuatNo":"6325","mevzuatAdi":"Örnek",
        "mevzuatId":"1","mevzuatTur":"KANUN"}, article={"maddeNo":18,"maddeId":"2"},
        article_html="<p>MADDE 18/A- Açıklama.</p>")
    assert record.article_no == "18/A"
    assert record.external_id.endswith(":m.18/A")
    assert record.metadata["portal_article_no"] == "18"
    with pytest.raises(ValueError,match="identity mismatch"):
        validate_record_identity(replace(record,article_no="18"))


@pytest.mark.parametrize("question,article", [
    ("6325 madde 18/A nedir?","18/A"), ("HMK m.183/A nedir?","183/A"),
    ("6325 geçici madde 1 nedir?","GEÇİCİ 1"), ("6325 ek madde 2 nedir?","EK 2"),
])
def test_exact_query_retains_namespace(question,article):
    assert question_article_numbers(question) == (article,)
    if "HMK" in question:
        assert question_law_numbers(question) == ("6100",)


@pytest.mark.skipif(not os.getenv("NHR_TEST_DATABASE_URL"),reason="Separate test DB required")
def test_repair_splits_false_version_chain_without_replacing_chunks(tmp_path):
    import psycopg
    from psycopg.rows import dict_row
    from tests.test_mevzuat_store import _record
    from ingestion.mevzuat.store import upsert_legislation
    from ingestion.text import content_hash
    url = os.environ["NHR_TEST_DATABASE_URL"]
    with psycopg.connect(url) as db:
        with db.transaction():
            old = _record()
            newer_text = old.raw_text.replace("MADDE 25", "MADDE 25/A").replace("Madde 25", "Madde 25/A")
            new = replace(old,article_no="25/A",external_id=old.external_id+"/A",
                          title=old.title.replace("m. 25","m. 25/A"),raw_text=newer_text,
                          content_hash=content_hash(newer_text))
            first = upsert_legislation(db,old).legal_source_id
            second = upsert_legislation(db,new).legal_source_id
            old_identity = db.execute("SELECT legislation_identity_id FROM legislation_details WHERE legal_source_id=%s",(first,)).fetchone()[0]
            db.execute("UPDATE legal_sources SET is_current=false,superseded_by_id=%s WHERE id=%s",(second,first))
            db.execute("UPDATE legislation_details SET article_no='25',legislation_identity_id=%s WHERE legal_source_id=%s",(old_identity,second))
            db.execute("UPDATE legal_sources SET external_id=%s WHERE id=%s",(old.external_id,second))
            db.row_factory = dict_row
            rows = load_rows(db)
            plan = build_plan(rows)
            assert len(plan["changes"]) == 2
            before = db.execute("SELECT id,content_hash FROM legal_chunks WHERE legal_source_id=ANY(%s::uuid[]) ORDER BY id",([first,second],)).fetchall()
            backup = tmp_path / "repair-backup.json"
            assert apply_plan(db,rows,plan["digest"],backup) == 2
            after = db.execute("SELECT id,content_hash FROM legal_chunks WHERE legal_source_id=ANY(%s::uuid[]) ORDER BY id",([first,second],)).fetchall()
            assert before == after
            repaired = db.execute("SELECT article_no,is_current FROM legislation_details WHERE legal_source_id=ANY(%s::uuid[]) ORDER BY article_no",([first,second],)).fetchall()
            assert repaired == [{"article_no":"25","is_current":True},{"article_no":"25/A","is_current":True}]
            assert json.loads(backup.read_text(encoding="utf-8"))["plan"]["digest"] == plan["digest"]
            assert build_plan(load_rows(db))["changes"] == []
            raise psycopg.Rollback


@pytest.mark.skipif(not os.getenv("NHR_TEST_DATABASE_URL"),reason="Separate test DB required")
def test_official_article_import_is_row_scoped_and_does_not_inherit_gazette_flags(monkeypatch,tmp_path):
    import psycopg
    from contextlib import contextmanager
    from psycopg.rows import dict_row
    from tests.test_mevzuat_store import _record
    from ingestion.mevzuat.store import upsert_legislation
    from scripts import import_official_article as command
    with psycopg.connect(os.environ['NHR_TEST_DATABASE_URL']) as db:
        with db.transaction():
            record=_record()
            original=upsert_legislation(db,record).legal_source_id
            db.row_factory=dict_row
            @contextmanager
            def connection():
                yield db
            monkeypatch.setattr(command,'admin_database_connection',connection)
            monkeypatch.setattr(command,'ROOT',tmp_path)
            body='MADDE 18/B- '+('Sentetik test metni. '*30)
            monkeypatch.setattr(command,'fetch_official_pdf_text',lambda *a,**kw:body)
            monkeypatch.setattr(command.sys,'argv',['import','--law','999999','--article','18/B',
                '--url','https://www.mevzuat.gov.tr/MevzuatMetin/1.5.999999.pdf','--apply'])
            command.main()
            row=db.execute("SELECT metadata,ingest_status FROM legal_sources WHERE external_id='mevzuat:kanun:999999:m.18/B'").fetchone()
            assert row['ingest_status']=='ready'
            assert row['metadata']['verified_against_mbs'] is True
            assert not row['metadata'].get('verified_against_gazette')
            assert db.execute('SELECT ingest_status FROM legal_sources WHERE id=%s',(original,)).fetchone()['ingest_status']=='pending'
            # A differing official text never silently replaces the existing row.
            monkeypatch.setattr(command,'fetch_official_pdf_text',lambda *a,**kw:'MADDE 18/B- '+('Başka içerik. '*35))
            with pytest.raises(SystemExit,match='differs'):
                command.main()
            raise psycopg.Rollback
