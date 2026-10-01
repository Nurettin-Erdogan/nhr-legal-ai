"""Sayıştay yargı kararları (Temyiz Kurulu, Daire, Genel Kurul) resmî portal istemcisi.

Kaynak: https://www.sayistay.gov.tr (herkese açık, CAPTCHA yok). Liste, DataTables sunucu
servisidir (`/<Tür>/DataTablesList`, ASP.NET antiforgery jetonu + çerez ister); tam metin
`/<Tür>/Detay/<Id>/` sayfasındadır. CAPTCHA/429 aşılmaz; hata olduğunda çağıran bekler.
"""

from __future__ import annotations

import http.client
import http.cookiejar
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

BASE_URL = "https://www.sayistay.gov.tr"
USER_AGENT = "nhr-legal-ai/0.1 (official-public-source-ingestion)"


class SayistayError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Kind:
    key: str  # veritabanı kimliğinde kullanılan kısa ad
    path: str  # ör. KararlarTemyiz
    label: str
    date_field: str


KINDS = {
    "temyiz": Kind("temyiz", "KararlarTemyiz", "Temyiz Kurulu", "TEMYIZTUTANAKTARIHI"),
    "daire": Kind("daire", "KararlarDaire", "Daire", "KARARTRH"),
    "genelkurul": Kind("genelkurul", "KararlarGenelKurul", "Genel Kurul", "KARARTARIH"),
}

_COLUMNS = re.compile(r"""['"]data['"]\s*:\s*"([A-Za-z_]+)""")
_TOKEN = re.compile(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"')
_INVARIANT = re.compile(r'name="__Invariant"[^>]*value="([^"]+)"')


class SayistayClient:
    def __init__(self, *, delay_seconds: float = 1.5, timeout_seconds: float = 45.0, max_retries: int = 3) -> None:
        self.delay = delay_seconds
        self.timeout = timeout_seconds
        self.max_retries = max_retries
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self._last = 0.0
        self._sessions: dict[str, dict[str, Any]] = {}

    def _pace(self) -> None:
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def _request(self, url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> bytes:
        last: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._pace()
            request = urllib.request.Request(
                url,
                data=data,
                headers={"User-Agent": USER_AGENT, **(headers or {})},
                method="POST" if data is not None else "GET",
            )
            try:
                with self._opener.open(request, timeout=self.timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    raise SayistayError("Sayıştay HTTP 429; kaynak hız sınırı, beklenmeli") from exc
                if exc.code in {400, 403, 404}:
                    raise SayistayError(f"Sayıştay HTTP {exc.code}: {url}") from exc
                last = exc
            except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
                last = exc
            time.sleep(min(30, 2**attempt))
        raise SayistayError(f"Sayıştay isteği başarısız: {last}")

    def _session(self, kind: Kind) -> dict[str, Any]:
        cached = self._sessions.get(kind.key)
        if cached:
            return cached
        html = self._request(f"{BASE_URL}/{kind.path}").decode("utf-8", errors="replace")
        detail = html.find("Detay")
        start = html.find("columns: [", detail if detail >= 0 else 0)
        columns = _COLUMNS.findall(html[start : start + 4000]) if start >= 0 else []
        token = _TOKEN.search(html)
        if not columns or token is None:
            raise SayistayError(f"Sayıştay {kind.label} sayfa yapısı beklenenden farklı")
        invariant = _INVARIANT.search(html)
        session = {"columns": columns, "token": token.group(1), "invariant": invariant.group(1) if invariant else None}
        self._sessions[kind.key] = session
        return session

    def list_page(self, kind: Kind, *, start: int, length: int = 100) -> tuple[list[dict[str, Any]], int]:
        """(satırlar, toplam). Jeton/oturum süresi dolarsa bir kez yenilenir."""
        for attempt in (1, 2):
            session = self._session(kind)
            params = [
                ("draw", "1"),
                ("start", str(start)),
                ("length", str(length)),
                ("search[value]", ""),
                ("search[regex]", "false"),
                ("order[0][column]", "1"),
                ("order[0][dir]", "desc"),
            ]
            for index, name in enumerate(session["columns"] + [None]):
                params += [
                    (f"columns[{index}][data]", name or ""),
                    (f"columns[{index}][name]", ""),
                    (f"columns[{index}][searchable]", "true"),
                    (f"columns[{index}][orderable]", "true"),
                    (f"columns[{index}][search][value]", ""),
                    (f"columns[{index}][search][regex]", "false"),
                ]
            params.append(("lang", "tr"))
            if session["invariant"]:
                params.append(("__Invariant", session["invariant"]))
            params.append(("__RequestVerificationToken", session["token"]))
            raw = self._request(
                f"{BASE_URL}/{kind.path}/DataTablesList",
                data=urllib.parse.urlencode(params).encode(),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"{BASE_URL}/{kind.path}",
                },
            )
            try:
                payload = json.loads(raw.decode("utf-8"))
                return list(payload["data"]), int(payload["recordsTotal"])
            except (ValueError, KeyError, TypeError):
                self._sessions.pop(kind.key, None)
                if attempt == 2:
                    raise SayistayError(f"Sayıştay {kind.label} liste yanıtı JSON değil") from None
        raise AssertionError("unreachable")

    def detail_html(self, kind: Kind, record_id: int) -> str:
        return self._request(f"{BASE_URL}/{kind.path}/Detay/{record_id}/").decode("utf-8", errors="replace")

    @staticmethod
    def detail_url(kind: Kind, record_id: int) -> str:
        return f"{BASE_URL}/{kind.path}/Detay/{record_id}/"
