"""Explicit pytest plugin for the zero-credit audit, not ordinary test startup."""
import builtins
import os
import pytest


def pytest_configure():
    if os.environ.get("NHR_OFFLINE_GUARD_ACTIVE") != "1":
        raise pytest.UsageError("Offline audit requires the inherited sitecustomize network barrier")
    url = os.environ.get("NHR_TEST_DATABASE_URL")
    if url:
        from psycopg.conninfo import conninfo_to_dict
        connection = conninfo_to_dict(url)
        if (connection.get("host") != "127.0.0.1" or connection.get("port") != "55439"
                or connection.get("dbname") != "nhr_legal_ai_test"
                or "55439" not in os.environ.get("NHR_OFFLINE_FIXTURE_PORTS", "").split(",")):
            raise pytest.UsageError("Audit DB must be the isolated local 55439 fixture")


def pytest_terminal_summary(terminalreporter):
    terminalreporter.write_line(
        "Offline audit: network barrier active; blocked real network attempts = "
        + str(getattr(builtins, "_nhr_offline_network_denials", 0))
    )
    for origin, count in sorted(getattr(builtins, "_nhr_offline_denials_by_test", {}).items()):
        terminalreporter.write_line(f"  {origin}: {count}")
