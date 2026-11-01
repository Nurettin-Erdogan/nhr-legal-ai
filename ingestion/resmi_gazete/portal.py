"""Resmî Gazete'nin public arama ucuyla mevzuat künyesi doğrulama.

Bu modül Resmî Gazete içeriğini ikinci bir mevzuat kopyası olarak yazmaz.
Bedesten'den gelen tarih/sayı/kanun numarasını resmî arşiv kaydıyla
karşılaştırır ve denetlenebilir bir doğrulama sonucu üretir.
"""

from __future__ import annotations

import io
import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from http.client import IncompleteRead
from http.cookiejar import CookieJar
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

from ingestion.http import is_retryable_status, retry_wait_seconds
from ingestion.text import html_to_text, normalize_text, tr_casefold

BASE_URL = "https://www.resmigazete.gov.tr/"
FILTER_PATH = "Home/Filter"
_ALLOWED_HOSTS = {"resmigazete.gov.tr", "www.resmigazete.gov.tr"}
_ISSUE_NO = re.compile(r"\bsay[\u0131i]\s*:\s*(\d{1,6})\b", re.IGNORECASE)
_HTML_CHARSET = re.compile(br"charset\s*=\s*[\"']?\s*([A-Za-z0-9._-]+)", re.IGNORECASE)
logger = logging.getLogger(__name__)


class ResmiGazeteError(RuntimeError):
    """Resmî Gazete yanıtı erişilemez veya sözleşmeye uymaz."""


# Tebliğ ve yönetmeliklerin Resmî Gazete'de kanun/karar numarası yoktur; bunlar numarayla aranamaz.
# Kimlik, gazetenin kendi arama dizininde yayın tarihine göre listelenen girdiler arasında başlığın
# tam eşleşmesiyle doğrulanır. Parantez içi ekler ("(Tebliğ No: 2023/14)" / "(No: 2023/14)") iki
# kaynakta farklı yazılabildiğinden temel anahtardan çıkarılır; aynı gün aynı başlıkla yayımlanan
# kardeş tebliğleri (2023/13 ile 2023/14) ayırmak için eklerdeki tanımlayıcı belirteçler kullanılır.
_TITLE_PAREN = re.compile(r"\([^()]*\)")
_TITLE_NON_ALNUM = re.compile(r"[^0-9a-zçğıöşü]+")
_TITLE_IDENT = re.compile(r"[0-9a-zçğıöşü]+(?:[/\-.][0-9a-zçğıöşü]+)+|\d+")
TITLE_DAY_ENTRY_LIMIT = 1000
_DAY_PAGE_SIZE = 100


def title_base_key(title: str) -> str:
    """Parantez ekleri atılmış, noktalama/boşluk/büyük-küçük harf farkı yutulmuş başlık anahtarı."""
    return _TITLE_NON_ALNUM.sub("", tr_casefold(normalize_text(_TITLE_PAREN.sub(" ", title or ""))))


def title_ident_tokens(title: str) -> tuple[str, ...]:
    """Parantez içindeki numara/kod belirteçleri ("2023/14", "tgm-2011/01", "1")."""
    folded = [tr_casefold(part) for part in _TITLE_PAREN.findall(normalize_text(title or ""))]
    return tuple(sorted(token for part in folded for token in _TITLE_IDENT.findall(part)))


def match_title_entries(
    entries: list[Mapping[str, Any]],
    *,
    title: str,
    publication_date: date,
    issue_no: str | None,
) -> Mapping[str, Any]:
    """Tarih + başlıkla TEK bir girdi seçer; belirsiz veya çelişkili ise ResmiGazeteError atar."""
    base = title_base_key(title)
    if not base:
        raise ResmiGazeteError("başlık boş; Resmî Gazete'de başlıkla aranamaz")
    wanted_issue = _normalize_issue_no(issue_no)
    unique: dict[tuple[Any, ...], Mapping[str, Any]] = {}
    for entry in entries:
        if parse_portal_date(entry.get("resmiGazeteTarihi")) != publication_date:
            continue
        if title_base_key(str(entry.get("konu") or "")) != base:
            continue
        unique[(entry.get("resmiGazeteSayisi"), entry.get("konu"), entry.get("url"))] = entry
    candidates = list(unique.values())
    if wanted_issue is not None:
        same_issue = [c for c in candidates if _normalize_issue_no(c.get("resmiGazeteSayisi")) == wanted_issue]
        if candidates and not same_issue:
            raise ResmiGazeteError(
                f"başlık + tarih eşleşti ama gazete sayısı çelişiyor (kayıt {wanted_issue}, "
                f"gazete {_normalize_issue_no(candidates[0].get('resmiGazeteSayisi'))})"
            )
        candidates = same_issue
    wanted_ident = title_ident_tokens(title)
    if len(candidates) > 1 and wanted_ident:
        candidates = [c for c in candidates if title_ident_tokens(str(c.get("konu") or "")) == wanted_ident]
    if len(candidates) != 1:
        raise ResmiGazeteError(
            f"başlık + tarih ile tekil Resmî Gazete kaydı bulunamadı ({len(candidates)} aday)"
        )
    chosen = candidates[0]
    found_ident = title_ident_tokens(str(chosen.get("konu") or ""))
    if wanted_ident and found_ident and wanted_ident != found_ident:
        raise ResmiGazeteError(
            f"başlık eşleşti ama numara/kod çelişiyor (kayıt {wanted_ident}, gazete {found_ident})"
        )
    return chosen


@dataclass(frozen=True, slots=True)
class GazetteIssue:
    publication_date: date
    issue_no: str | None
    archive_url: str
    title: str
    raw_text: str
    # 1980'ler öncesi sayılar taranmış görüntü PDF'idir (metin katmanı yok); tarih + kanun no'nun
    # RG'nin kendi arama dizininde tekil eşleşmesi kimliği doğrular ama tam metin karşılaştırması
    # yapılamaz. `raw_text` bu durumda boştur.
    text_available: bool = True


@dataclass(frozen=True, slots=True)
class GazetteVerification:
    verified: bool
    archive_url: str | None
    requested_date: str | None
    observed_date: str
    requested_issue_no: str | None
    observed_issue_no: str | None
    law_no: str
    law_no_present: bool
    law_name_present: bool
    verified_at: str
    detail: str
    # Metin katmanı olmayan taranmış arşivlerde False olur (bkz. GazetteIssue.text_available).
    # Varsayılan True: bu alanı bilmeyen eski çağıranlar (testler) normal davranışı korur.
    text_confirmed: bool = True

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def parse_portal_date(value: Any) -> date | None:
    text = str(value or "").strip().split("T", 1)[0]
    for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def _normalize_issue_no(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text == "0":
        return None
    # "30354 (Mükerrer)" gibi kayıtlar: sayının kendisi (Resmî Gazete arama ucu ek metni 500 ile reddediyor;
    # kanun numarası kaydı zaten tekilleştirir).
    match = re.match(r"\d+", text)
    return match.group(0) if match else text


def _official_archive_url(value: Any, *, base_url: str) -> str:
    url = urljoin(base_url, str(value or "").strip())
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
        raise ResmiGazeteError("Resmî Gazete arama sonucu resmî olmayan URL döndürdü")
    return url


def _decode_archive_html(raw: bytes) -> str:
    declared = _HTML_CHARSET.search(raw[:4096])
    encodings = []
    if declared:
        encodings.append(declared.group(1).decode("ascii", errors="ignore"))
    encodings.extend(("utf-8", "windows-1254", "iso-8859-9"))
    for encoding in dict.fromkeys(encodings):
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


# 1980 öncesi sayılar `arsiv/<sayı>.pdf` altında tek dosyada ciltlenmiş, onlarca MB'lık taranmış
# görüntülerdir (test edildi: 74 MB, 35 sayfa, metin katmanı yok). Bu sayfaları `pypdf` ile açmak
# hem yavaş hem sonuçsuzdur; yalnız ilk birkaç sayfa denenir, bulunamazsa tarama kabul edilir.
_PDF_MAX_PAGES = 8
_PDF_TIMEOUT_SECONDS = 20.0


def _pdf_text_unbounded(raw: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(raw))
        parts = [page.extract_text() or "" for page in reader.pages[:_PDF_MAX_PAGES]]
    except (PdfReadError, ValueError, KeyError):
        return ""
    return "\n".join(parts)


def _pdf_text_worker(raw: bytes, queue: Any) -> None:
    try:
        queue.put(_pdf_text_unbounded(raw))
    except Exception:  # noqa: BLE001 - hiçbir pypdf istisnası alt süreci çökertmesin
        queue.put("")


def _pdf_text(raw: bytes) -> str:
    """`pypdf` bazı bozuk taranmış PDF'lerde (bozuk font tablosu) süresiz takılabiliyor
    (ölçüldü: 2026-09-27, `mevzuat_verify` işçisi saatlerce CPU'yu tüketerek askıda kaldı).
    İş parçacığı (thread) GIL'i bıraktığı için CPU'da dönen bir döngüyü GERÇEKTEN durdurmaz;
    yalnız çağıran tarafı serbest bırakır, arka planda tüketmeye devam eder ve her denemede
    bir tane daha birikir. Bu yüzden `multiprocessing` kullanılır: zaman aşımında `terminate()`
    alt süreci gerçekten öldürür, CPU/GIL geri alınır.
    """
    import multiprocessing

    ctx = multiprocessing.get_context("spawn")
    queue: Any = ctx.Queue()
    process = ctx.Process(target=_pdf_text_worker, args=(raw, queue), daemon=True)
    process.start()
    process.join(_PDF_TIMEOUT_SECONDS)
    if process.is_alive():
        logger.warning("PDF metin çıkarma %.0f sn'de zaman aşımına uğradı, alt süreç öldürüldü", _PDF_TIMEOUT_SECONDS)
        process.terminate()
        process.join(5.0)
        if process.is_alive():
            process.kill()
        return ""
    try:
        return queue.get_nowait()
    except Exception:  # noqa: BLE001 - süreç sonuçsuz bitmiş olabilir
        return ""


class ResmiGazeteClient:
    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout_seconds: float = 30,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1,
        opener: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(1, max_retries)
        self.retry_backoff_seconds = max(0, retry_backoff_seconds)
        self.opener = opener or build_opener(HTTPCookieProcessor(CookieJar()))

    def _request(self, url: str, *, body: Mapping[str, Any] | None = None) -> bytes:
        data = None
        headers = {
            "Accept": "application/json, text/html, */*",
            "Referer": self.base_url,
            "User-Agent": "nhr-legal-ai/0.1 (official-public-source-verification)",
        }
        if body is not None:
            data = json.dumps(dict(body), ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        for attempt in range(1, self.max_retries + 1):
            request = Request(url, data=data, headers=headers, method="POST" if data else "GET")
            try:
                with self.opener.open(request, timeout=self.timeout_seconds) as response:
                    return response.read()
            except HTTPError as exc:
                if not is_retryable_status(exc.code) or attempt == self.max_retries:
                    raise ResmiGazeteError(f"Resmî Gazete HTTP hatası: {exc.code} ({url})") from exc
                wait = retry_wait_seconds(
                    attempt,
                    base_seconds=self.retry_backoff_seconds,
                    retry_after=exc.headers.get("Retry-After") if exc.headers else None,
                )
                logger.warning("Resmî Gazete HTTP %s; %.1f saniye sonra yeniden denenecek", exc.code, wait)
                time.sleep(wait)
            except (URLError, TimeoutError, IncompleteRead) as exc:
                # response.read() zaman aşımı bare TimeoutError fırlatır (URLError'ın .reason
                # sarmalaması yalnız open() sırasındaki hatalarda olur) - ölçüldü: 2026-09-28,
                # "The read operation timed out" yakalanmadan turun tamamını başarısız kıldı.
                # IncompleteRead de aynı şekilde ayrı bir sınıf (http.client.HTTPException,
                # OSError değil) - ölçüldü: 2026-09-28, sunucu yanıtı tamamlamadan bağlantıyı
                # kesince (16565/beklenen bayt) 163 kayıtlık ilerleme tek seferde heba oldu.
                if attempt == self.max_retries:
                    detail = getattr(exc, "reason", exc)
                    raise ResmiGazeteError(f"Resmî Gazete bağlantı hatası: {detail}") from exc
                time.sleep(retry_wait_seconds(attempt, base_seconds=self.retry_backoff_seconds))
        raise AssertionError("unreachable")

    def _search_candidates(
        self, *, law_no: str, date_from: date | None, date_to: date | None, issue_no: str | None
    ) -> list[Mapping[str, Any]]:
        parameters = {
            "searchtype": "1",
            "genelaranacakkelime": "",
            "genelbaslangictarihi": date_from.isoformat() if date_from else "",
            "genelbitistarihi": date_to.isoformat() if date_to else "",
            "genelsayi": "" if date_from else (_normalize_issue_no(issue_no) or ""),
            "genelmevzuatsayisi": law_no.strip(),
            "genelmukerrer": "",
            "genelmevzuatturu": "",
            "genelkurumkodu": "",
        }
        body = {"draw": 1, "start": 0, "length": 25, "parameters": parameters}
        raw = self._request(urljoin(self.base_url, FILTER_PATH), body=body)
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ResmiGazeteError("Resmî Gazete arama ucu JSON olmayan yanıt döndürdü") from exc
        if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
            raise ResmiGazeteError("Resmî Gazete arama yanıtı beklenen sözleşmede değil")
        candidates = [item for item in payload["data"] if isinstance(item, Mapping)]
        # Arama dizini bazen aynı kaydı iki kez döndürür (aynı tarih/sayı/kanun no); bu bir
        # belirsizlik değildir, tek belgenin yinelenmesidir.
        return list(
            {
                (c.get("resmiGazeteTarihi"), c.get("resmiGazeteSayisi"), c.get("kanunKararNo"), c.get("url")): c
                for c in candidates
                if str(c.get("kanunKararNo") or "").strip() == law_no.strip()
            }.values()
        )

    def search_legislation(
        self,
        *,
        law_no: str,
        publication_date: date | None = None,
        expected_issue_no: str | None = None,
    ) -> GazetteIssue:
        # Ana sayfa isteği public arama oturumunu/cookie'lerini kurar.
        self._request(self.base_url)
        # Sayı (`genelsayi`) sunucu tarafı filtre olarak gönderilmez: Bedesten'den gelen
        # `official_gazette_no` "mükerrer" ciltlerde veya eski kayıtlarda birkaç sayı kayabiliyor
        # (ölçüldü: 2026-09-27, bir kanun için 31455 kaydedilmiş, gerçeği 31457'ydi ve bu tek
        # başına aramayı sonuçsuz bırakıyordu). Tarih verilmişse kanun no + tarih zaten tekil bir
        # anahtardır; sayı yalnız tarih YOKSA (bazı eski kayıtlarda tek bilinen alan odur) arama
        # anahtarı olarak kullanılır.
        has_date = publication_date is not None
        candidates = self._search_candidates(
            law_no=law_no,
            date_from=publication_date if has_date else None,
            date_to=publication_date if has_date else None,
            issue_no=expected_issue_no,
        )
        if has_date:
            candidates = [
                c for c in candidates if parse_portal_date(c.get("resmiGazeteTarihi")) == publication_date
            ]
            if not candidates:
                # Bedesten'in kaydettiği tarih de kayabiliyor (ölçüldü: 2026-09-27, 2 gün fark;
                # 2026-09-28, kanun "4933" için 5 gün fark: bizde 13.06.1946, gerçeği 18.06.1946).
                # Aynı kanun no'nun farklı dönemlerde (1946/1967/2003/2021 gibi) tekrarı yıllarca
                # arayla olduğundan geniş bir pencere (±14 gün) yanlış eşleşme riski taşımaz;
                # pencerede tek aday varsa kimlik yine güvenle doğrulanır.
                window_from = date.fromordinal(publication_date.toordinal() - 14)
                window_to = date.fromordinal(publication_date.toordinal() + 14)
                candidates = self._search_candidates(
                    law_no=law_no, date_from=window_from, date_to=window_to, issue_no=None
                )
        elif expected_issue_no:
            expected = _normalize_issue_no(expected_issue_no)
            candidates = [c for c in candidates if _normalize_issue_no(c.get("resmiGazeteSayisi")) == expected]
        if len(candidates) != 1:
            raise ResmiGazeteError(
                f"{law_no} numaralı mevzuat için tekil Resmî Gazete kaydı bulunamadı"
            )
        item = candidates[0]
        observed_date = parse_portal_date(item.get("resmiGazeteTarihi"))
        if observed_date is None:
            raise ResmiGazeteError("Resmî Gazete arama sonucunda yayın tarihi eksik")
        archive_url = _official_archive_url(item.get("url"), base_url=self.base_url)
        # Arama sonucu eski (taranmış görüntü) ciltleri `isNewFormat: false` ile işaretliyor.
        # Bunlar onlarca MB'lık, metin katmanı olmayan PDF'lerdir (ölçüldü: 2026-09-27, 74 MB,
        # `pypdf` bazılarında süresiz takılıyordu — bkz. `_pdf_text`). Bu bayrak açıkça false ise
        # dosya hiç indirilmez/açılmaz; doğrudan taranmış-arşiv yoluna gidilir.
        if item.get("isNewFormat") is False:
            raw_text = ""
        else:
            archive_raw = self._request(archive_url)
            if archive_raw.startswith(b"%PDF"):
                raw_text = normalize_text(_pdf_text(archive_raw))
            else:
                raw_text = normalize_text(html_to_text(_decode_archive_html(archive_raw)))
        text_available = bool(raw_text)
        issue_no = _normalize_issue_no(item.get("resmiGazeteSayisi"))
        if issue_no is None and text_available:
            match = _ISSUE_NO.search(raw_text)
            issue_no = match.group(1) if match else None
        return GazetteIssue(
            publication_date=observed_date,
            issue_no=issue_no,
            archive_url=archive_url,
            title=str(item.get("konu") or "").strip(),
            raw_text=raw_text,
            text_available=text_available,
        )

    def _entries_for_day(self, day: date) -> list[Mapping[str, Any]]:
        """Bir yayın gününün tüm girdileri (sayfa başına en çok 100; günde 235'e kadar girdi olabilir)."""
        cache = self.__dict__.setdefault("_day_cache", {})
        if day in cache:
            return cache[day]
        entries: list[Mapping[str, Any]] = []
        start = 0
        while start < TITLE_DAY_ENTRY_LIMIT:
            parameters = {
                "searchtype": "1",
                "genelaranacakkelime": "",
                "genelbaslangictarihi": day.isoformat(),
                "genelbitistarihi": day.isoformat(),
                "genelsayi": "",
                "genelmevzuatsayisi": "",
                "genelmukerrer": "",
                "genelmevzuatturu": "",
                "genelkurumkodu": "",
            }
            body = {"draw": 1, "start": start, "length": _DAY_PAGE_SIZE, "parameters": parameters}
            raw = self._request(urljoin(self.base_url, FILTER_PATH), body=body)
            try:
                payload = json.loads(raw.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ResmiGazeteError("Resmî Gazete arama ucu JSON olmayan yanıt döndürdü") from exc
            if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
                raise ResmiGazeteError("Resmî Gazete arama yanıtı beklenen sözleşmede değil")
            page = [item for item in payload["data"] if isinstance(item, Mapping)]
            entries.extend(page)
            total = int(payload.get("recordsFiltered") or payload.get("recordsTotal") or 0)
            start += len(page)
            if not page or start >= total:
                break
        if len(cache) >= 256:
            cache.clear()
        cache[day] = entries
        return entries

    def verify_by_title(
        self,
        *,
        publication_date: date | None,
        issue_no: str | None,
        title: str,
    ) -> GazetteVerification:
        """Numarasız türler (tebliğ, yönetmelik): yayın günü + başlığın tam eşleşmesiyle kimlik doğrulaması."""
        if publication_date is None:
            raise ResmiGazeteError("yayın tarihi yok; başlıkla doğrulanamaz")
        self._request(self.base_url)  # public arama oturumunu/cookie'lerini kurar
        item = match_title_entries(
            self._entries_for_day(publication_date),
            title=title,
            publication_date=publication_date,
            issue_no=issue_no,
        )
        observed_date = parse_portal_date(item.get("resmiGazeteTarihi"))
        if observed_date is None:
            raise ResmiGazeteError("Resmî Gazete arama sonucunda yayın tarihi eksik")
        return GazetteVerification(
            verified=True,
            archive_url=_official_archive_url(item.get("url"), base_url=self.base_url),
            requested_date=publication_date.isoformat(),
            observed_date=observed_date.isoformat(),
            requested_issue_no=_normalize_issue_no(issue_no),
            observed_issue_no=_normalize_issue_no(item.get("resmiGazeteSayisi")),
            law_no="",
            law_no_present=False,
            law_name_present=True,
            text_confirmed=False,
            verified_at=datetime.now(UTC).isoformat(),
            detail=(
                "Resmî Gazete arama dizininde başlık + yayın tarihi tekil eşleşti "
                "(numarasız tür: tebliğ/yönetmelik; tam metin karşılaştırılmadı)"
            ),
        )

    def verify_legislation(
        self,
        *,
        publication_date: date | None,
        issue_no: str | None,
        law_no: str,
        law_name: str,
    ) -> GazetteVerification:
        issue = self.search_legislation(
            law_no=law_no,
            publication_date=publication_date,
            expected_issue_no=issue_no,
        )
        normalized_law_no = law_no.strip()
        normalized_name = normalize_text(law_name)
        requested_issue = _normalize_issue_no(issue_no)
        # Sayı yalnız bilgi amaçlıdır: kimlik zaten kanun no + tarihin RG'nin kendi dizininde
        # tekil eşleşmesiyle doğrulanmıştır (bkz. search_legislation). Bizim kaydettiğimiz sayı
        # (Bedesten) yanlışsa doğrulamayı reddetmemesi için burada engel olarak kullanılmaz.
        issue_matches = requested_issue is None or requested_issue == issue.issue_no
        # search_legislation() zaten kanun no + (gerekirse ±14 gün penceresi içinde) tekil bir
        # aday bularak kimliği doğruladı; kaydımızdaki tarih o pencere içinde ama tam eşit
        # değilse (ölçüldü: 2026-09-28, "4933" için 5 gün fark) bu artık bir doğrulama engeli
        # değil, yalnız bilgi notudur — tıpkı sayı (issue_no) uyuşmazlığı gibi.
        exact_date_match = publication_date is None or publication_date == issue.publication_date
        date_matches = (
            exact_date_match
            or (
                publication_date is not None
                and abs((publication_date - issue.publication_date).days) <= 14
            )
        )
        reasons = []
        if not date_matches:
            reasons.append(
                f"tarih uyuşmuyor: beklenen={publication_date}, bulunan={issue.publication_date}"
            )
        elif not exact_date_match:
            reasons.append(
                f"not: kaydımızdaki tarih ({publication_date}) RG'de {issue.publication_date}; "
                "kimlik kanun no ile tekil eşleşmeyle doğrulandı"
            )
        if not issue_matches:
            reasons.append(
                f"not: kayıtlı sayı ({requested_issue}) RG'de {issue.issue_no}; kimlik kanun no + tarihle doğrulandı"
            )

        if issue.text_available:
            folded = tr_casefold(issue.raw_text)
            law_no_present = bool(
                normalized_law_no
                and re.search(rf"(?<!\d){re.escape(normalized_law_no)}(?!\d)", issue.raw_text)
            )
            law_name_present = bool(normalized_name and tr_casefold(normalized_name) in folded)
            if law_no_present:
                verified = date_matches
                text_confirmed = True
                detail = "Resmî Gazete tarih/sayı ve mevzuat numarası doğrulandı" if verified else ""
            elif law_name_present:
                # Eski "eskiler" arşivinin OCR metninde rakam hataları görülüyor (ölçüldü:
                # 2026-09-27, "2797" için metinde "8797" yazıyordu). Kanun adı ve tarih eşleşiyorsa
                # bu, tekil arama sonucuyla birlikte yeterli bir kimlik doğrulamasıdır.
                verified = date_matches
                text_confirmed = False
                reasons.append(f"{normalized_law_no} numarası metinde yok (OCR hatası olabilir), başlık eşleşti")
                detail = (
                    "Resmî Gazete: kanun no + tarih tekil eşleşti, başlık metinde doğrulandı "
                    "(numara OCR/tarama kaynaklı metinde bulunamadı)"
                    if verified
                    else ""
                )
            else:
                verified = False
                text_confirmed = False
                reasons.append(f"{normalized_law_no} numarası arşiv sayfasında yok")
                detail = ""
            if not verified:
                detail = "; ".join(r for r in reasons if not r.startswith("not:"))
        else:
            # Taranmış (görüntü) arşiv: metin katmanı yok, tam metin karşılaştırması yapılamaz.
            # Kimlik zaten RG'nin arama dizininde kanun no + tarihle tekil eşleşti; bu, ikinci
            # bir metin taramasından daha zayıf ama yine de RG'nin kendi resmî verisidir.
            law_no_present = True
            law_name_present = False
            text_confirmed = False
            verified = date_matches
            detail = (
                "Resmî Gazete arama dizininde kanun no + tarih tekil eşleşti "
                "(taranmış görüntü arşiv, tam metin doğrulanamadı)"
                if verified
                else "; ".join(reasons)
            )
        return GazetteVerification(
            verified=verified,
            archive_url=issue.archive_url,
            requested_date=publication_date.isoformat() if publication_date else None,
            observed_date=issue.publication_date.isoformat(),
            requested_issue_no=requested_issue,
            observed_issue_no=issue.issue_no,
            law_no=normalized_law_no,
            law_no_present=law_no_present,
            law_name_present=law_name_present,
            text_confirmed=text_confirmed,
            verified_at=datetime.now(UTC).isoformat(),
            detail=detail,
        )
