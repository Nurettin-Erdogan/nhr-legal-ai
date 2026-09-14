from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from api.projects import ProjectCreate


def test_project_create_accepts_legal_matter_metadata():
    project = ProjectCreate(
        name="İşçilik alacağı dosyası",
        matter_type="case",
        docket_no="2026/42",
        opened_on=date(2026, 9, 14),
    )

    assert project.matter_type == "case"
    assert project.docket_no == "2026/42"


def test_project_create_rejects_unknown_matter_type():
    with pytest.raises(ValidationError):
        ProjectCreate(name="Test dosyası", matter_type="unknown")
