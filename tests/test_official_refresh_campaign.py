from types import SimpleNamespace

from scripts import refresh_official_law_campaign as campaign
from scripts.refresh_official_law import apply
import pytest


def test_failed_child_does_not_export_raw_credentials_or_error_text(monkeypatch):
    monkeypatch.setattr(campaign.subprocess, 'run', lambda *args, **kwargs:
        SimpleNamespace(returncode=1, stdout='', stderr='sensitive test credential'))
    assert campaign.run_helper('6325') is None


def test_apply_child_is_bound_to_the_preview_digest(monkeypatch):
    seen = []
    def run(command, **kwargs):
        seen.append(command)
        return SimpleNamespace(returncode=0, stdout='{"apply":true}\n{"applied":1}\n')
    monkeypatch.setattr(campaign.subprocess, 'run', run)
    assert len(campaign.run_helper('6325', 'digest-from-preview')) == 2
    assert seen[0][-3:] == ['--apply', '--expect-digest', 'digest-from-preview']


def test_changed_preview_aborts_before_any_database_or_backup_action():
    with pytest.raises(ValueError, match='Preview changed'):
        apply(object(), {}, 'changed', 'expected')


@pytest.mark.parametrize('stderr,expected', [
    ('MbsTextVerificationError: MBS PDF indirilemedi: HTTP Error 429', 'portal_unavailable'),
    ('MbsTextVerificationError: MBS beklenen PDF belgesini döndürmedi', 'unexpected_official_response'),
    ('MbsTextVerificationError: MBS PDF indirilemedi: HTTP Error 404', 'official_document_not_found'),
    ('ValueError: Official PDF title does not match the stored law', 'official_title_mismatch'),
])
def test_official_portal_failures_are_distinguished_without_exporting_errors(stderr, expected):
    assert campaign.failure_code(stderr) == expected
