"""Yüklenen dosyayı belleğe almadan işler: boyut sınırı yoktur.

Gövde, Starlette'in geçici dosyasına (1 MB üstü diskte) yazılmıştır. Burada dosya bir kez okunarak boyutu ve SHA-256
özeti hesaplanır; yerleştirme sırasında dosyadan dosyaya kopyalanır. Sunucunun belleği dosya boyutuyla büyümez, bu yüzden
UYAP'tan gelen büyük ekler (ses/video/çok sayfalı tarama paketleri) için sabit bir üst sınır gerekmez.

Yalnız işletmecinin isteğe bağlı `MAX_UPLOAD_BYTES` ortam değişkeni bir üst sınır koyabilir; ayarlanmamışsa sınır yoktur.
Diskte yer kalmaması (`OSError`) çağıranlarda "kaydedilemedi" olarak ele alınır.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from fastapi.concurrency import run_in_threadpool

CHUNK_BYTES = 1024 * 1024
# Metin örneği çıkarmak ve ODT/UDF'yi karşılaştırmak için belleğe alınabilecek en büyük içerik; daha büyük dosyalar yalnız
# diskten diske akıtılır (örnek çıkarılmaz, belge yine saklanır).
IN_MEMORY_PARSE_BYTES = 64 * 1024 * 1024


class UploadTooLarge(Exception):
    """İşletmecinin ayarladığı isteğe bağlı üst sınır aşıldı."""

    def __init__(self, limit: int) -> None:
        super().__init__(f"Dosya sunucunun ayarlı üst sınırını ({limit // (1024 * 1024)} MB) aşıyor")
        self.limit = limit


def upload_limit() -> int | None:
    """`MAX_UPLOAD_BYTES` ayarlıysa bayt cinsinden üst sınır; yoksa (varsayılan) sınır yoktur."""
    raw = os.getenv("MAX_UPLOAD_BYTES", "").strip()
    try:
        value = int(raw) if raw else 0
    except ValueError:
        return None  # bozuk ayar sessizce sınır koymaz; sınırsız davranış tek ve öngörülebilir kalır
    return value if value > 0 else None


def measure(stream: BinaryIO, limit: int | None = None) -> tuple[int, str]:
    """Akışı baştan sona bir kez okur: (bayt sayısı, SHA-256). `limit` aşılırsa `UploadTooLarge`."""
    stream.seek(0)
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(CHUNK_BYTES):
        size += len(chunk)
        if limit is not None and size > limit:
            raise UploadTooLarge(limit)
        digest.update(chunk)
    stream.seek(0)
    return size, digest.hexdigest()


def file_sha256(path: Path) -> str:
    """Diskteki dosyanın SHA-256'sı (bellekte tutmadan)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(slots=True)
class Upload:
    """Yüklenmiş içeriğin bellekte ya da (büyükse) geçici dosyada duran hâli.

    `_store` ve yükleme uç noktaları aynı nesneyi kullanır; sahibi kullanımı bitirince `discard()` çağrılır (tekrar
    çağrılabilir). Bellek içi `data` küçük içerik ve eski çağıranlar içindir.
    """

    size: int
    sha256: str
    stream: BinaryIO | None = None
    data: bytes | None = None
    _closed: bool = field(default=False, repr=False)

    @classmethod
    def from_bytes(cls, data: bytes) -> "Upload":
        return cls(size=len(data), sha256=hashlib.sha256(data).hexdigest(), data=data)

    @classmethod
    def from_stream(cls, stream: BinaryIO, limit: int | None = None) -> "Upload":
        size, digest = measure(stream, limit)
        return cls(size=size, sha256=digest, stream=stream)

    def small_bytes(self, limit: int = IN_MEMORY_PARSE_BYTES) -> bytes | None:
        """İçerik `limit`'ten küçükse baytları; değilse None (büyük dosya belleğe alınmaz)."""
        if self.data is not None:
            return self.data
        if self.stream is None or self.size > limit:
            return None
        self.stream.seek(0)
        content = self.stream.read()
        self.stream.seek(0)
        return content

    def place(self, target: Path, *, exclusive: bool = False) -> None:
        """İçeriği `target`'a yazar. Varsayılan: geçici dosya + atomik yer değiştirme; `exclusive`: var olan dosyaya
        yazmayı reddeder (`FileExistsError`). Yarım kalan hedef dosya silinir."""
        target.parent.mkdir(parents=True, exist_ok=True)
        if exclusive:
            written = target
            written_mode = "xb"
        else:
            written = target.with_name(target.name + ".tmp")
            written_mode = "wb"
        created = False  # yalnız bu çağrının kendi açtığı dosya silinir (var olan hedefe asla dokunulmaz)
        try:
            with written.open(written_mode) as output:
                created = True
                if self.data is not None:
                    output.write(self.data)
                elif self.stream is not None:
                    self.stream.seek(0)
                    shutil.copyfileobj(self.stream, output, CHUNK_BYTES)
            if not exclusive:
                os.replace(written, target)
        except BaseException:
            if created:
                written.unlink(missing_ok=True)
            raise
        finally:
            if not exclusive:
                written.unlink(missing_ok=True)

    def discard(self) -> None:
        """Geçici dosyayı kapatır (silinir). Birden çok kez çağrılabilir."""
        if self._closed:
            return
        self._closed = True
        if self.stream is not None:
            try:
                self.stream.close()
            except OSError:
                pass


async def receive_upload(file, limit: int | None = None) -> Upload:
    """Starlette `UploadFile`'ı bellek kullanmadan ölçer; ölçüm iş parçacığında çalışır, olay döngüsünü bloklamaz."""
    return await run_in_threadpool(Upload.from_stream, file.file, limit)
