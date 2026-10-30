"""Run UYAP acceptance tests against a new, disposable, empty database.

Never copies production data or changes cluster roles. The existing non-bypass
runtime role is reused; grants/migrations apply only inside the new *_test DB.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.config import get_settings

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    admin_url = get_settings().admin_database_url
    name = f"nhr_uyap_{uuid4().hex[:12]}_test"
    assert re.fullmatch(r"nhr_uyap_[a-f0-9]{12}_test", name)
    created = False
    with psycopg.connect(admin_url, autocommit=True, connect_timeout=5) as admin:
        role = admin.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname='nhr_runtime'").fetchone()
        assert role == (False, False), "Existing runtime role must not bypass RLS"
        try:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            created = True
            test_url = make_conninfo(admin_url, dbname=name)
            with psycopg.connect(test_url, autocommit=True) as connection:
                for migration in sorted((ROOT / "database/init").glob("*.sql")):
                    # Empty, exclusively owned test DB: normal index creation is
                    # equivalent and lets a multi-statement migration execute.
                    text = migration.read_text(encoding="utf-8")
                    include = re.fullmatch(r"\s*\\i /nhr-database/([a-zA-Z0-9_./-]+)\s*", text)
                    if include:
                        included = (ROOT / "database" / include[1]).resolve()
                        assert included.is_relative_to((ROOT / "database").resolve())
                        text = included.read_text(encoding="utf-8")
                    text = re.sub(r"\bCONCURRENTLY\b", "", text)
                    text = re.sub(r"(?m)^\\set ON_ERROR_STOP on\s*$", "", text)
                    assert not re.search(r"(?m)^\\", text), f"Unsupported psql command: {migration.name}"
                    connection.execute(text)
            print("Isolated UYAP schema ready; no production rows copied.", flush=True)
            env = dict(os.environ, NHR_TEST_DATABASE_URL=test_url,
                       DATABASE_URL="postgresql://dummy:dummy@127.0.0.1:1/dummy",
                       DATABASE_ADMIN_URL="postgresql://dummy:dummy@127.0.0.1:1/dummy",
                       JWT_SECRET="isolated-test-only-not-a-real-secret-000000000",
                       PYTHONIOENCODING="utf-8")
            env.pop("NHR_BROWSER_TESTS", None)
            tests = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("test_uyap_*.py"))
            tests += ["tests/test_office_public.py", "tests/test_upload_stream.py", "tests/test_case_document_index_api.py"]
            return subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=short",
                                   f"--basetemp=.local/tmp/{name}", *tests],
                                  cwd=ROOT, env=env, check=False).returncode
        finally:
            if created:
                assert re.fullmatch(r"nhr_uyap_[a-f0-9]{12}_test", name)
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
                print("Removed only the disposable database created by this run.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
