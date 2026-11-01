"""Adalet Bakanlığı Bedesten `emsal-karar` arayüzü: Yargıtay ve Danıştay kararları, CAPTCHA'sız.

Mevzuat için zaten kullandığımız `bedesten.adalet.gov.tr` sunucusunun karar ucudur. Ölçüldü
(2026-09-26): `documentId` Yargıtay/Danıştay karar arama portalındaki doküman kimliğiyle ve
korpusumuzdaki `yargitay:<id>` / `danistay:<id>` dış kimlikleriyle aynıdır; içerik metni portal
metniyle boşluk farkı dışında birebir eşleşir. Bu yüzden buradan çekilen kayıt resmî sayılır.

Hız sınırı (ölçüm 2026-09-26): dakikada ~12-13 istek; aşılınca 429 gelir ve engel ~10 sn sürer.
Bu nedenle sabit ~5 sn aralık ve kısa (15 sn) bekleme en verimlisidir. Tüm süreçler (toplayıcı,
sorgu anı doğrulama) `data/campaign/bedesten-cooldown.json` içindeki ortak sırayı paylaşır: her
istek bir zaman dilimi ayırır ve 429 alınca hepsi bekler; böylece birbirinin bütçesini tüketmezler.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

BASE_URL = "https://bedesten.adalet.gov.tr/emsal-karar/"
ITEM_TYPES = {"yargitay": "YARGITAYKARARI", "danistay": "DANISTAYKARAR"}
# Arama, bir ifade ister; "karar" kararların neredeyse tamamını kapsar.
SEARCH_PHRASE = "karar"
MAX_PAGE_SIZE = 100

_ROOT = Path(__file__).resolve().parents[1]
COOLDOWN_FILE = _ROOT / "data" / "campaign" / "bedesten-cooldown.json"
_HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "AdaletApplicationName": "UyapMevzuat",
    "Origin": "https://mevzuat.adalet.gov.tr",
    "Referer": "https://mevzuat.adalet.gov.tr/",
    "User-Agent": "nhr-legal-ai/0.1 (official-public-source-ingestion)",
}


class BedestenError(RuntimeError):
    """Bedesten isteği başarısız oldu. Mesaj `source_errors` işaretleriyle sınıflanır."""


class BedestenRateLimited(BedestenError):
    """HTTP 429: hız sınırı. `retry_after` saniye beklenmelidir."""

    def __init__(self, message: str, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class BedestenItem:
    document_id: str
    chamber: str
    docket_no: str
    decision_no: str
    decision_date: date | None


@dataclass(frozen=True, slots=True)
class BedestenPage:
    total: int
    items: list[BedestenItem]


def day_window(day: date) -> tuple[str, str]:
    """Türkiye günü (UTC+3) için başlangıç/bitiş zaman damgaları."""
    start = day - timedelta(days=1)
    return (
        f"{start.isoformat()}T21:00:00.000Z",
        f"{day.isoformat()}T20:59:59.000Z",
    )


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


def _read_state(path: Path) -> dict[str, float]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {"until": float(raw.get("until", 0.0)), "next": float(raw.get("next", 0.0))}
    except (OSError, ValueError, TypeError, AttributeError):
        return {"until": 0.0, "next": 0.0}


def _write_state(state: dict[str, float], path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(state), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        pass


def read_cooldown(path: Path | None = None) -> float:
    return _read_state(path or COOLDOWN_FILE)["until"]


def write_cooldown(seconds: float, path: Path | None = None) -> None:
    path = path or COOLDOWN_FILE
    state = _read_state(path)
    state["until"] = max(state["until"], time.time() + seconds)
    _write_state(state, path)


def reserve_slot(interval: float, path: Path | None = None) -> float:
    """Sıradaki istek zamanını ayırır ve o ana kadar beklenecek saniyeyi döndürür (süreçler arası)."""
    path = path or COOLDOWN_FILE
    now = time.time()
    state = _read_state(path)
    slot = max(now, state["until"], state["next"])
    state["next"] = slot + interval
    _write_state(state, path)
    return max(slot - now, 0.0)


class BedestenClient:
    def __init__(
        self,
        *,
        min_interval: float = 5.0,
        timeout: float = 30.0,
        cooldown_seconds: float = 10.0,
        opener: Any = None,
    ) -> None:
        self.min_interval = min_interval
        self.timeout = timeout
        self.cooldown_seconds = cooldown_seconds
        self._opener = opener or urllib.request.build_opener()

    def _wait_turn(self) -> None:
        wait = reserve_slot(self.min_interval)
        if wait > 0:
            time.sleep(min(wait, 600.0))

    def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        self._wait_turn()
        body = json.dumps({"data": data, "applicationName": "UyapMevzuat"}).encode("utf-8")
        request = urllib.request.Request(BASE_URL + path, data=body, headers=_HEADERS, method="POST")
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                write_cooldown(self.cooldown_seconds)
                raise BedestenRateLimited(
                    f"Bedesten HTTP 429; hız sınırı ({path})", self.cooldown_seconds
                ) from exc
            raise BedestenError(f"Bedesten HTTP hatası: {exc.code} ({path})") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise BedestenError(f"Bedesten bağlantı hatası ({path}): {exc}") from exc
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BedestenError(f"Bedesten JSON olmayan yanıt döndürdü ({path})") from exc
        metadata = payload.get("metadata") or {}
        if metadata.get("FMTY") == "ERROR":
            raise BedestenError(f"Bedesten hata: {str(metadata.get('FMTE'))[:160]}")
        return payload

    def search(
        self, kind: str, start: date, end: date, *, page: int = 1, page_size: int = MAX_PAGE_SIZE,
        chamber: str | None = None,
    ) -> BedestenPage:
        """`start`..`end` (dahil) karar tarihli kararları, tarihe göre sıralı listeler.

        `chamber` (birimAdi, ör. "13. Hukuk Dairesi") verilirse yalnız o birimin kararları sayılır/listelenir
        (ölçüldü: 2026-10-05, 2015-10-21 günü 5387 karar, "1. Hukuk Dairesi" için toplam 75)."""
        first, _ = day_window(start)
        _, last = day_window(end)
        request = {
            "pageNumber": page,
            "pageSize": min(page_size, MAX_PAGE_SIZE),
            "itemTypeList": [ITEM_TYPES[kind]],
            "phrase": SEARCH_PHRASE,
            "sortFields": ["KARAR_TARIHI"],
            "sortDirection": "desc",
            "kararTarihiStart": first,
            "kararTarihiEnd": last,
        }
        if chamber:
            request["birimAdi"] = chamber
        payload = self._post("searchDocuments", request)
        data = payload.get("data") or {}
        items = [
            BedestenItem(
                document_id=str(row["documentId"]),
                chamber=str(row.get("birimAdi") or "").strip(),
                docket_no=str(row.get("esasNo") or "").strip(),
                decision_no=str(row.get("kararNo") or "").strip(),
                decision_date=_parse_date(row.get("kararTarihiStr")),
            )
            for row in (data.get("emsalKararList") or [])
            if row.get("documentId")
        ]
        return BedestenPage(total=int(data.get("total") or 0), items=items)

    def content_html(self, document_id: str) -> str:
        payload = self._post("getDocumentContent", {"documentId": str(document_id)})
        content = (payload.get("data") or {}).get("content")
        if not content:
            raise BedestenError(f"Bedesten karar içeriği boş: {document_id}")
        try:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        except ValueError as exc:
            raise BedestenError(f"Bedesten içerik çözülemedi: {document_id}") from exc
