"""Boyut sınırı olmayan yükleme: içerik belleğe alınmadan ölçülür, diske akıtılır; yalnız işletmecinin isteğe bağlı sınırı vardır."""
from __future__ import annotations

import hashlib
import io

import pytest

from api import upload_stream
from api.upload_stream import CHUNK_BYTES, Upload, UploadTooLarge, file_sha256, measure, upload_limit


def test_limit_is_off_unless_the_operator_sets_a_valid_positive_value(monkeypatch):
    monkeypatch.delenv("MAX_UPLOAD_BYTES", raising=False)
    assert upload_limit() is None
    for value in ("", "0", "-5", "abc", "1.5"):
        monkeypatch.setenv("MAX_UPLOAD_BYTES", value)
        assert upload_limit() is None, value  # bozuk ayar sessizce sınır koymaz
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "1048576")
    assert upload_limit() == 1048576


def test_measure_counts_every_byte_and_hashes_across_chunk_boundaries():
    payload = bytes(range(256)) * (CHUNK_BYTES // 256 * 2 + 3)  # birkaç parça ve düzensiz bir kuyruk
    stream = io.BytesIO(payload)

    size, digest = measure(stream)

    assert size == len(payload) and digest == hashlib.sha256(payload).hexdigest()
    assert stream.tell() == 0  # akış yeniden kullanılabilir bırakılır


def test_the_optional_limit_is_enforced_while_reading_not_after():
    stream = io.BytesIO(b"x" * 11)
    with pytest.raises(UploadTooLarge) as caught:
        measure(stream, limit=10)
    assert caught.value.limit == 10
    assert measure(io.BytesIO(b"x" * 10), limit=10)[0] == 10  # sınırın tam değeri kabul edilir


def test_small_content_is_available_as_bytes_but_large_content_never_is():
    small = Upload.from_stream(io.BytesIO(b"kucuk icerik"))
    large = Upload.from_stream(io.BytesIO(b"b" * 2048))

    assert small.small_bytes(1024) == b"kucuk icerik"
    assert large.small_bytes(1024) is None  # büyük dosya belleğe alınmaz
    assert Upload.from_bytes(b"abc").small_bytes(1) == b"abc"  # bellek içi içerik zaten bellektedir


def test_place_writes_atomically_and_exclusive_never_touches_an_existing_file(tmp_path):
    payload = b"belge " * 300_000  # birden çok kopyalama parçası
    upload = Upload.from_stream(io.BytesIO(payload))

    target = tmp_path / "a" / "belge.bin"
    upload.place(target)
    assert target.read_bytes() == payload
    assert not list(target.parent.glob("*.tmp"))  # geçici dosya kalmaz

    existing = tmp_path / "var.bin"
    existing.write_bytes(b"baska bir kullanicinin dosyasi")
    with pytest.raises(FileExistsError):
        upload.place(existing, exclusive=True)
    assert existing.read_bytes() == b"baska bir kullanicinin dosyasi"  # var olan dosya silinmedi, ezilmedi


class _Breaking(io.BytesIO):
    """İkinci okumada disk/okuma hatası veren akış (yarım kalan kopya)."""

    def __init__(self, data):
        super().__init__(data)
        self.reads = 0

    def read(self, size=-1):
        self.reads += 1
        if self.reads > 3:
            raise OSError("disk dolu")
        return super().read(size)


@pytest.mark.parametrize("exclusive", [False, True])
def test_a_failed_copy_leaves_no_partial_file(tmp_path, exclusive):
    upload = Upload(size=10, sha256="x", stream=_Breaking(b"y" * (CHUNK_BYTES * 8)))
    target = tmp_path / "yarim.bin"

    with pytest.raises(OSError):
        upload.place(target, exclusive=exclusive)

    assert not list(tmp_path.glob("*"))  # ne hedef ne geçici dosya


def test_discard_is_idempotent_and_closes_the_temporary_stream():
    stream = io.BytesIO(b"abc")
    upload = Upload.from_stream(stream)

    upload.discard()
    upload.discard()

    assert stream.closed


def test_file_sha256_streams_from_disk(tmp_path):
    path = tmp_path / "x.bin"
    path.write_bytes(b"icerik" * 400_000)
    assert file_sha256(path) == hashlib.sha256(b"icerik" * 400_000).hexdigest()


def test_module_has_no_fixed_size_constant_that_could_become_a_hidden_cap():
    assert not [name for name in dir(upload_stream) if name.startswith("MAX_") and name != "MAX_UPLOAD_BYTES"]
