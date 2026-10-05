"""Kullanıcı verisi yedeği: tablo sınıflandırması, döndürme ve zip. Docker/veritabanı gerekmez."""

from __future__ import annotations

import zipfile

from scripts import backup_user_data as backup


def test_user_tables_are_backed_up_and_the_corpus_is_not():
    tables = ["users", "office_cases", "legal_chunks", "legal_sources", "bulk_seed_inventory", "messages"]
    user, corpus, unknown = backup.classify_tables(tables)
    assert user == ["messages", "office_cases", "users"] and sorted(corpus) == ["bulk_seed_inventory", "legal_chunks", "legal_sources"]
    assert unknown == []


def test_an_unclassified_new_table_is_included_rather_than_silently_skipped():
    user, _, unknown = backup.classify_tables(["users", "office_yeni_tablo"])
    assert unknown == ["office_yeni_tablo"] and "office_yeni_tablo" in user


def test_the_lists_do_not_overlap():
    assert not set(backup.USER_TABLES) & set(backup.CORPUS_TABLES)


def test_rotation_keeps_the_newest_and_never_touches_foreign_folders():
    names = ["jurisai-20261001-020000", "jurisai-20261003-020000", "jurisai-20261002-020000", "jurisai-20261004-020000", "belgelerim", "jurisai-bozuk"]
    assert backup.rotation_victims(names, keep=2) == ["jurisai-20261001-020000", "jurisai-20261002-020000"]
    assert backup.rotation_victims(names, keep=10) == []
    assert backup.rotation_victims(names, keep=0) == ["jurisai-20261001-020000", "jurisai-20261002-020000", "jurisai-20261003-020000"]  # en az 1 yedek kalır


def test_zip_contains_every_file_with_relative_paths(tmp_path):
    source = tmp_path / "uploads"
    (source / "a" / "b").mkdir(parents=True)
    (source / "a" / "b" / "evrak.udf").write_bytes(b"123")
    (source / "kök.txt").write_text("merhaba", encoding="utf-8")
    target = tmp_path / "uploads.zip"
    assert backup.zip_directory(source, target) == 2
    with zipfile.ZipFile(target) as archive:
        assert sorted(archive.namelist()) == ["a/b/evrak.udf", "kök.txt"] and archive.testzip() is None


def test_sha256_changes_when_the_file_changes(tmp_path):
    path = tmp_path / "x"
    path.write_bytes(b"bir")
    first = backup.sha256(path)
    path.write_bytes(b"iki")
    assert first != backup.sha256(path) and len(first) == 64
