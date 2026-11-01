"""The test harness must not silently target the live corpus."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

spec = spec_from_file_location("nhr_test_conftest", Path(__file__).with_name("conftest.py"))
assert spec is not None and spec.loader is not None
test_config = module_from_spec(spec)
spec.loader.exec_module(test_config)
pytest_configure = test_config.pytest_configure
validate_test_database_url = test_config.validate_test_database_url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://nhr_app:secret@localhost:5433/nhr_legal_ai",
        "postgresql://nhr_app:secret@localhost:5433/nhr_legal_ai_test?dbname=nhr_legal_ai",
        "postgresql://nhr_app:secret@localhost:5433/",
    ],
)
def test_live_or_ambiguous_database_is_rejected(url):
    with pytest.raises(pytest.UsageError):
        validate_test_database_url(url)


def test_explicit_test_database_is_accepted():
    validate_test_database_url(
        "postgresql://nhr_app:secret@localhost:5433/nhr_legal_ai_test"
    )


def test_without_explicit_database_does_not_connect(monkeypatch):
    monkeypatch.delenv("NHR_TEST_DATABASE_URL", raising=False)
    monkeypatch.setattr("psycopg.connect", lambda *args, **kwargs: pytest.fail("unexpected DB call"))
    pytest_configure()
