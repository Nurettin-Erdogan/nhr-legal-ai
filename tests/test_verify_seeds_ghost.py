"""Bedesten'de olmayan (hayalet) kayıt portala düşüp takılmaz: kalıcı sayılır."""

from __future__ import annotations

import pytest

from ingestion.bedesten_emsal import BedestenError
from scripts import verify_seeds


class _GhostBedesten:
    def content_html(self, document_id):
        raise BedestenError(f"Bedesten hata: Record not found exception:{document_id} Id'li döküman sistemde bulunamadı!!!")


class _PortalMustNotBeUsed:
    def fetch_document_html(self, document_id):
        pytest.fail("hayalet kayıt için portala düşülmemeli")


def test_missing_bedesten_record_is_permanent_and_never_falls_back_to_the_portal(monkeypatch):
    monkeypatch.setattr(verify_seeds, "_BEDESTEN", _GhostBedesten())
    with pytest.raises(ValueError) as caught:
        verify_seeds._fetch_official_text("yargitay", _PortalMustNotBeUsed(), "863162600")
    message = str(caught.value).lower()
    # Döngü "geçersiz" sözcüğünü kalıcı hata sayıp beklemeden `unavailable` işaretler.
    assert "geçersiz" in message and "863162600" in message


def test_other_bedesten_errors_still_fall_back_to_the_portal(monkeypatch):
    class _Flaky:
        def content_html(self, document_id):
            raise BedestenError("Bedesten hata: sunucu 500")

    class _Portal:
        def fetch_document_html(self, document_id):
            return "<html><body><p>Karar metni portaldan geldi.</p></body></html>"

    monkeypatch.setattr(verify_seeds, "_BEDESTEN", _Flaky())
    assert "portaldan geldi" in verify_seeds._fetch_official_text("yargitay", _Portal(), "1")
