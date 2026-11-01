from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts" / "official_sources"
ENTRYPOINTS = (
    "01_yargitay.py",
    "02_danistay.py",
    "03_aym.py",
    "04_kdk.py",
    "05_mevzuat_bedesten.py",
    "06_resmi_gazete.py",
    "07_mevzuat_bilgi_sistemi.py",
)


@pytest.mark.parametrize("script", ENTRYPOINTS)
def test_direct_source_script_has_help_without_database_or_network(script: str):
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / script), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--help" in result.stdout


def test_ingestion_script_passes_safety_options_to_worker():
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "01_yargitay.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert "--dry-run" in result.stdout
    assert "--max-records" in result.stdout
    assert "--no-resume" in result.stdout


def test_verification_reports_failure_with_nonzero_exit(monkeypatch, capsys):
    sys.path.insert(0, str(SCRIPTS))
    try:
        from _entrypoint import run_verification
        from worker import adapters

        class Adapter:
            def health_check(self):
                from worker.models import AdapterHealth

                return AdapterHealth("resmi_gazete", "degraded", "not verified", False)

        monkeypatch.setattr(adapters, "get_adapter", lambda source: Adapter())
        monkeypatch.setattr(sys, "argv", ["06_resmi_gazete.py"])

        assert run_verification("resmi_gazete") == 1
        assert json.loads(capsys.readouterr().out)["health"] == "degraded"
    finally:
        sys.path.remove(str(SCRIPTS))
