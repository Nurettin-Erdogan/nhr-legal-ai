import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest

path = Path(__file__).resolve().parents[1] / 'scripts/run_bounded_official_batch.py'
spec = importlib.util.spec_from_file_location('bounded_official_batch_test', path)
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


def test_ssd_reserve_stops_before_disk_is_full():
    assert batch.storage_available('.', usage=lambda root: SimpleNamespace(free=101 * 1024**3))
    assert not batch.storage_available('.', usage=lambda root: SimpleNamespace(free=99 * 1024**3))


@pytest.mark.parametrize('reserve', [0, 1, 49, 501])
def test_unsafe_reserve_not_accepted(reserve):
    with pytest.raises(ValueError):
        batch.storage_available('.', reserve)


def test_staging_directory_is_scoped_to_project(tmp_path):
    archive = batch.archive_directory(tmp_path)
    assert archive.is_relative_to(tmp_path.resolve())
    assert str(archive).endswith(str(Path('.local/official-data-campaign/raw/aym')))
