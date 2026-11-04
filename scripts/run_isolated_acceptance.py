"""Offline acceptance tests against the disposable 55439 fixture, never production.

Requires an empty PostgreSQL/pgvector fixture named nhr_legal_ai_test.
No application secrets are read; model/provider network traffic is blocked.
"""
from pathlib import Path
import os
import re
import subprocess
import sys
from uuid import uuid4

import psycopg

ROOT = Path(__file__).resolve().parents[1]
DSN = "postgresql://nhr_app:isolated-test-only@127.0.0.1:55439/nhr_legal_ai_test"


def migration_text(path):
    text = path.read_text(encoding="utf-8")
    def include(match):
        included = (ROOT / "database" / match[1]).resolve()
        assert included.is_relative_to((ROOT / "database").resolve())
        return migration_text(included)
    text = re.sub(r"(?m)^\\i /nhr-database/([a-zA-Z0-9_./-]+)\s*$", include, text)
    text = re.sub(r"\bCONCURRENTLY\b", "", text)
    text = re.sub(r"(?m)^\\set ON_ERROR_STOP on\s*$", "", text)
    assert not re.search(r"(?m)^\\", text), path.name
    return text


def main():
    with psycopg.connect(DSN, autocommit=True, connect_timeout=5) as db:
        assert db.execute("SELECT current_database()").fetchone()[0] == "nhr_legal_ai_test"
        migrations = []
        if db.execute("SELECT to_regclass('public.legal_sources')").fetchone()[0] is None:
            migrations = sorted((ROOT / "database/init").glob("*.sql"))
        elif db.execute("SELECT to_regclass('public.office_bureau_decisions')").fetchone()[0] is None:
            migrations = [ROOT / "database/init/064_bureau_assistant.sql"]
        if migrations:
            for migration in migrations:
                db.execute(migration_text(migration))
            print("Disposable test schema ready; no production data copied.", flush=True)
    env = dict(os.environ, NHR_TEST_DATABASE_URL=DSN,
               DATABASE_URL="postgresql://dummy:dummy@127.0.0.1:1/dummy",
               DATABASE_ADMIN_URL="postgresql://dummy:dummy@127.0.0.1:1/dummy",
               JWT_SECRET="isolated-test-only-not-a-real-secret-000000000",
               NHR_OFFLINE_AUDIT="1", NHR_OFFLINE_FIXTURE_PORTS="55439",
               PYTHONPATH=str(ROOT / "scripts/offline_guard") + os.pathsep + str(ROOT),
               PYTHONIOENCODING="utf-8")
    requested_args = sys.argv[1:]
    browser_fixtures = "--with-browser-fixtures" in requested_args
    requested_args = [arg for arg in requested_args if arg != "--with-browser-fixtures"]
    if browser_fixtures:
        env["NHR_BROWSER_TESTS"] = "1"
    else:
        env.pop("NHR_BROWSER_TESTS", None)
    for key in list(env):
        if key.endswith("API_KEY"):
            env.pop(key)
    args = requested_args or ([] if browser_fixtures else ["--ignore=tests/test_uyap_extension_browser.py"])
    # A fixed basetemp collides with concurrent runs and Windows file handles.
    # Let pytest create a fresh, workspace-scoped directory; never delete or
    # take ownership of another run's directory to make a test pass.
    temporary_root = ROOT / ".local" / "tmp" / ("acceptance-" + uuid4().hex)
    return subprocess.run([sys.executable, "-X", "utf8", "-m", "pytest", "-q", "-ra",
                           "-p", "tests.offline_network_guard", "--basetemp", str(temporary_root), *args], cwd=ROOT,
                          env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
