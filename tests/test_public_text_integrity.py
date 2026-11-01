from scripts.audit_public_text_integrity import inspect_text
from ingestion.text import content_hash
import json
from scripts import audit_public_text_integrity as audit


def test_matching_normalized_text():
    assert inspect_text(dict(raw_text='Madde 1\r\n Metin ', content_hash=content_hash('Madde 1\nMetin'))) == []


def test_different_hash_is_integrity_issue_not_official_verdict():
    assert inspect_text(dict(raw_text='Metin', content_hash='wrong')) == ['hash_mismatch']


def test_empty_text_is_always_reported():
    assert inspect_text(dict(raw_text=None, content_hash=content_hash(''))) == ['empty_text']


def test_checkpoint_retries_transient_windows_file_lock(tmp_path, monkeypatch):
    target = tmp_path / 'checkpoint.json'
    target.write_text('{"scanned": 1}')
    replace = audit.os.replace
    attempts = []

    def transient(source, destination):
        attempts.append(1)
        if len(attempts) < 3:
            assert json.loads(target.read_text())['scanned'] == 1
            raise PermissionError('simulated reader lock')
        return replace(source, destination)

    monkeypatch.setattr(audit.os, 'replace', transient)
    monkeypatch.setattr(audit.time, 'sleep', lambda _: None)
    audit.save_checkpoint(target, {'scanned': 2})
    assert len(attempts) == 3
    assert json.loads(target.read_text()) == {'scanned': 2}
