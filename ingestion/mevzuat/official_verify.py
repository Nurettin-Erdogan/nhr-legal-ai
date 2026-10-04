"""Kanun bazlı Resmî Gazete + MBS doğrulaması.

Bedesten çekimi her madde için tekrar doğrulamaz. Aynı kanun numarası
bellekte ve, her iki bayrak da true ise, veritabanında cache'lenir.
Bekleyen kanunlar ayrı `mevzuat_verify` worker'ı veya
`scripts/reverify_mevzuat.py` ile tamamlanır.
"""

from __future__ import annotations

import time

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from psycopg.types.json import Jsonb

from ingestion.mevzuat_bilgi_sistemi.portal import MbsClient, MbsError
from ingestion.resmi_gazete.portal import ResmiGazeteClient, ResmiGazeteError
from ingestion.source_errors import is_verification_cooldown_error

_STORED_VERIFIED_SQL = """
SELECT ls.metadata
FROM legal_sources ls
JOIN legislation_details d ON d.legal_source_id = ls.id
WHERE ls.source_type = 'legislation'
  AND ls.is_current
  AND ls.deleted_at IS NULL
  AND d.law_no = %s
  AND ls.metadata->>'verified_against_gazette' = 'true'
  AND ls.metadata->>'verified_against_mbs' = 'true'
LIMIT 1
"""

_PENDING_LAWS_SQL = """
SELECT *
FROM (
    SELECT DISTINCT ON (d.legislation_type, d.law_no,
                        d.official_gazette_date, d.official_gazette_no)
           d.legislation_type, d.law_no, d.law_name,
           d.official_gazette_date, d.official_gazette_no,
           ls.metadata
    FROM legal_sources ls
    JOIN legislation_details d ON d.legal_source_id = ls.id
    WHERE ls.source_type = 'legislation' AND ls.is_current
      AND ls.deleted_at IS NULL
      AND (ls.metadata->>'verified_against_gazette' IS DISTINCT FROM 'true'
           OR ls.metadata->>'verified_against_mbs' IS DISTINCT FROM 'true')
      -- Tebliğ ve yönetmeliklerin law_no değeri gazete numarası değil MBS iç kimliğidir; bunlar
      -- Resmî Gazete'de yayın günü + başlıkla doğrulanır (bkz. official_verify._check_gazette),
      -- bu yüzden artık sorgudan dışlanmaz.
    ORDER BY d.legislation_type, d.law_no,
             d.official_gazette_date, d.official_gazette_no,
             ls.fetched_at DESC
) pending
ORDER BY
  -- Bir tür (ör. bazı KHK/Kararname'ler MBS'nin yapısal veritabanında hiç yer almıyor,
  -- ölçüldü: 2026-09-28, 2023 deprem OHAL kararnameleri 129-140) kalıcı olarak geçemezse
  -- eskiden tür önceliği bunlara sonsuza dek verilmeye devam ediyordu ve kanun/KHK'nın
  -- ARDINDAKİ yönetmelik/tebliğ türüne (binlerce çözülebilir aday, ölçüldü: "regulation"
  -- türünde 495/15.635 zaten geçiyor) hiç sıra gelmiyordu. Tükenme (5+ deneme) artık tür
  -- önceliğinin de ÖNÜNE geçer: tükenmiş kayıt, türü ne olursa olsun taze adayların gerisine
  -- düşer; böylece kilitlenen tür diğerlerini sonsuza dek tıkayamaz.
  CASE
    WHEN COALESCE((pending.metadata->>'verify_attempt_count')::int, 0) >= 50 THEN 2
    WHEN COALESCE((pending.metadata->>'verify_attempt_count')::int, 0) >= 5 THEN 1
    ELSE 0
  END,
  -- Yakın zamanda (20 dk) denenmiş kayıt, tür önceliğinden ÖNCE sona geçer. Eskiden bu ölçüt tür
  -- önceliğinden sonra geliyordu: kurtarılamayan 74 kanun/kararname (366-650 başarısız deneme)
  -- her turda en öne dönüyor, tebliğlere hiç sıra gelmiyordu (ölçüldü: 2026-10-03, 90 dakikada
  -- tek tebliğ bile denenmedi). 50+ deneme en son kademedir: gerçekten çözülemeyenler sona gömülür.
  CASE
    WHEN (
      CASE
        WHEN pending.metadata->>'verify_last_attempt_at' ~ '^[0-9]{4}-'
        THEN (pending.metadata->>'verify_last_attempt_at')::timestamptz
      END
    ) > NOW() - INTERVAL '20 minutes'
    THEN 1 ELSE 0
  END,
  -- Resmî Gazete ve MBS yalnız kanun, KHK ve Anayasa'yı doğrulayabiliyor; tebliğ/yönetmelik
  -- (binlerce kanun numarası) sırayı tıkamasın diye bunlar en sona bırakılır.
  CASE WHEN pending.legislation_type IN ('law', 'decree', 'constitution') THEN 0 ELSE 1 END,
  -- Aynı kademede en az denenen önce (adil dönüş). "Bir tarafı doğrulanmış önce" kuralı bunun
  -- ÖNÜNDEYKEN 300 kadar kalıcı başarısız kayıt (35+ deneme) 2.740 hiç doğrulanmamış tebliğin
  -- önünde kalıyor ve onlara sıra gelmiyordu (ölçüldü: 2026-10-04, bir saatte yalnız bunlar denendi).
  COALESCE((pending.metadata->>'verify_attempt_count')::int, 0),
  CASE
    WHEN (pending.metadata->>'verified_against_gazette' = 'true')
         <> (pending.metadata->>'verified_against_mbs' = 'true')
    THEN 0 ELSE 1
  END,
  COALESCE(pending.metadata->>'verify_last_attempt_at', '') ASC,
  pending.legislation_type, pending.law_no
LIMIT %s
"""

_APPLY_SQL = """
UPDATE legal_sources ls
SET metadata = ls.metadata || %s,
    ingest_status = CASE
        WHEN (ls.metadata || %s)->>'verified_against_gazette' = 'true'
         AND (ls.metadata || %s)->>'verified_against_mbs' = 'true'
        THEN 'ready' ELSE 'pending' END,
    last_verified_at = CASE
        WHEN (ls.metadata || %s)->>'verified_against_gazette' = 'true'
         AND (ls.metadata || %s)->>'verified_against_mbs' = 'true'
        THEN NOW() ELSE ls.last_verified_at END
FROM legislation_details d
WHERE d.legal_source_id = ls.id AND ls.is_current
  AND d.legislation_type = %s AND d.law_no = %s
  AND d.official_gazette_date IS NOT DISTINCT FROM %s
  AND d.official_gazette_no IS NOT DISTINCT FROM %s
"""

VerificationTriple = tuple[dict[str, Any], dict[str, Any], int]

_GAZETTE_OK: dict[tuple[str, str | None, str | None], dict[str, Any]] = {}

# Gazetede numarası olmayan türler: başlık + yayın günüyle doğrulanır (bkz. _check_gazette).
TITLE_VERIFIED_TYPES = frozenset({"communique", "regulation"})


def _number_search_plausible(law: dict[str, Any]) -> bool:
    """law_no gerçekten gazete numarası olabilir mi? Uzun numaralar MBS'nin iç kimliğidir."""
    law_no = str(law.get("law_no") or "")
    if law.get("legislation_type") == "communique":
        return len(law_no) <= 4
    if law.get("legislation_type") == "regulation":
        return len(law_no) <= 6
    return True
_MBS_OK: dict[str, dict[str, Any]] = {}


class VerificationCooldown(RuntimeError):
    """RG veya MBS geçici olarak kullanılamıyor; turu kes, kaynağı soğut."""

    def __init__(self, source: str, detail: str) -> None:
        self.source = source
        super().__init__(detail)


def clear_verification_cache() -> None:
    _GAZETTE_OK.clear()
    _MBS_OK.clear()


def _metadata_from_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        payload = row.get("metadata")
    else:
        payload = row[0]
    return payload if isinstance(payload, dict) else None


def stored_law_verification(connection: Any, law_no: str) -> VerificationTriple | None:
    if connection is None or not str(law_no or "").strip():
        return None
    try:
        result = connection.execute(_STORED_VERIFIED_SQL, (law_no,))
        row = result.fetchone()
    except Exception:  # noqa: BLE001
        return None
    metadata = _metadata_from_row(row)
    if metadata is None:
        return None
    if (
        metadata.get("verified_against_gazette") is not True
        or metadata.get("verified_against_mbs") is not True
    ):
        return None
    gazette = metadata.get("official_gazette_verification")
    mbs = metadata.get("mbs_verification")
    if not isinstance(gazette, dict):
        gazette = {"verified": True, "law_no": law_no, "detail": "kanun cache"}
    if not isinstance(mbs, dict):
        mbs = {"verified": True, "law_no": law_no, "detail": "kanun cache"}
    return gazette, mbs, 0


def pending_laws(connection: Any, *, limit: int) -> list[dict[str, Any]]:
    result = connection.execute(_PENDING_LAWS_SQL, (max(1, limit),))
    rows = result.fetchall()
    pending: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            pending.append(row)
            continue
        pending.append(
            {
                "legislation_type": row[0],
                "law_no": row[1],
                "law_name": row[2],
                "official_gazette_date": row[3],
                "official_gazette_no": row[4],
                "metadata": row[5] if len(row) > 5 else {},
            }
        )
    return pending


def apply_law_verification(
    connection: Any,
    law: dict[str, Any],
    *,
    flags: dict[str, bool],
    results: dict[str, Any],
) -> None:
    prior_metadata = law.get("metadata") if isinstance(law.get("metadata"), dict) else {}
    prior_count = prior_metadata.get("verify_attempt_count")
    prior_count = prior_count if isinstance(prior_count, int) else 0
    fully_verified = bool(flags) and all(flags.values())
    attempt_count = {"verify_attempt_count": 0 if fully_verified else prior_count + 1}
    metadata = {**flags, **results, **attempt_count}
    connection.execute(
        _APPLY_SQL,
        (Jsonb(metadata),) * 5
        + (
            law["legislation_type"],
            law["law_no"],
            law["official_gazette_date"],
            law["official_gazette_no"],
        ),
    )


def _check_gazette(
    law: dict[str, Any], *, gazette_client: ResmiGazeteClient, gazette_key: tuple[Any, ...]
) -> tuple[bool | None, dict[str, Any] | None, int]:
    """Yalnız RG tarafı. Dönüş: (verified veya None=denenmedi, sonuç kaydı, istek sayısı)."""
    cached = _GAZETTE_OK.get(gazette_key)
    if cached:
        return cached.get("verified") is True, cached, 0
    title_detail: str | None = None
    if (
        law.get("legislation_type") in TITLE_VERIFIED_TYPES
        and law.get("law_name")
        and law.get("official_gazette_date")
    ):
        # Tebliğ ve yönetmeliklerin gazetede kanun numarası yoktur; kimlik yayın günü + başlıkla
        # doğrulanır (ölçüldü: 2026-10-03, 120 rastgele kayıttan tebliğlerin %91'i tekil eşleşti).
        try:
            result = gazette_client.verify_by_title(
                publication_date=law.get("official_gazette_date"),
                issue_no=law.get("official_gazette_no"),
                title=law["law_name"],
            ).to_json()
            result["method"] = "title_date"
            _GAZETTE_OK[gazette_key] = result
            return True, result, 3
        except ResmiGazeteError as exc:
            if is_verification_cooldown_error(exc):
                raise VerificationCooldown("gazette", str(exc)) from exc
            title_detail = str(exc)
        if not _number_search_plausible(law):
            # Numara gazete numarası değil (MBS iç kimliği): numarayla aramak yalnız istek harcar.
            return False, {"verified": False, "detail": f"başlıkla: {title_detail}"}, 3
    try:
        result = gazette_client.verify_legislation(
            publication_date=law.get("official_gazette_date"),
            issue_no=law.get("official_gazette_no"),
            law_no=law["law_no"],
            law_name=law.get("law_name"),
        ).to_json()
        if result.get("verified") is True:
            _GAZETTE_OK[gazette_key] = result
        return result.get("verified") is True, result, 3
    except ResmiGazeteError as exc:
        if is_verification_cooldown_error(exc):
            raise VerificationCooldown("gazette", str(exc)) from exc
        detail = str(exc) if title_detail is None else f"{exc}; başlıkla: {title_detail}"
        return False, {"verified": False, "detail": detail}, 3


def _check_mbs(
    law: dict[str, Any], *, mbs_client: MbsClient, law_no: str
) -> tuple[bool | None, dict[str, Any] | None, int]:
    """Yalnız MBS tarafı. Dönüş: (verified veya None=denenmedi, sonuç kaydı, istek sayısı)."""
    cached_mbs = _MBS_OK.get(law_no)
    if cached_mbs:
        return cached_mbs.get("verified") is True, cached_mbs, 0
    try:
        result = mbs_client.verify_legislation(
            law_no=law["law_no"],
            law_name=law.get("law_name"),
            publication_date=law.get("official_gazette_date"),
            issue_no=law.get("official_gazette_no"),
        ).to_json()
        if result.get("verified") is True:
            _MBS_OK[law_no] = result
        return result.get("verified") is True, result, 2
    except MbsError as exc:
        if is_verification_cooldown_error(exc):
            raise VerificationCooldown("mbs", str(exc)) from exc
        return False, {"verified": False, "detail": str(exc)}, 2


def verify_law_against_portals(
    law: dict[str, Any],
    *,
    gazette_client: ResmiGazeteClient,
    mbs_client: MbsClient,
    skip_gazette: bool = False,
    skip_mbs: bool = False,
) -> tuple[dict[str, bool], dict[str, Any], int]:
    metadata = law.get("metadata") if isinstance(law.get("metadata"), dict) else {}
    flags = {
        "verified_against_gazette": metadata.get("verified_against_gazette") is True,
        "verified_against_mbs": metadata.get("verified_against_mbs") is True,
    }
    results: dict[str, Any] = {}
    requests_made = 0
    law_no = str(law.get("law_no") or "")
    gazette_date = law.get("official_gazette_date")
    gazette_key = (
        law_no,
        gazette_date.isoformat() if hasattr(gazette_date, "isoformat") else str(gazette_date or "") or None,
        str(law.get("official_gazette_no") or "") or None,
    )
    need_gazette = not flags["verified_against_gazette"] and not skip_gazette
    need_mbs = not flags["verified_against_mbs"] and not skip_mbs
    # RG ve MBS sırayla sorgulanır. Eşzamanlı (ThreadPoolExecutor) deneme 2026-09-28'de
    # geri alındı: RG yolu taranmış PDF'ler için `multiprocessing` (spawn) alt süreci açıyor
    # ve bunu ana olmayan bir iş parçacığından açmak Windows'ta turların takılmasına yol
    # açtı (ölçüldü: değişiklikten sonraki 3 tur da 0 işlenmiş kayıtla asılı kaldı).
    if need_gazette:
        verified, result, req = _check_gazette(
            law, gazette_client=gazette_client, gazette_key=gazette_key
        )
        flags["verified_against_gazette"] = bool(verified)
        if result is not None:
            results["official_gazette_verification"] = result
        requests_made += req
    if need_mbs:
        verified, result, req = _check_mbs(law, mbs_client=mbs_client, law_no=law_no)
        flags["verified_against_mbs"] = bool(verified)
        if result is not None:
            results["mbs_verification"] = result
        requests_made += req
    results["verify_last_attempt_at"] = datetime.now(UTC).isoformat()
    return flags, results, requests_made


def iter_pending_verifications(
    connection: Any,
    *,
    limit: int,
    gazette_client: ResmiGazeteClient,
    mbs_client: MbsClient,
    dry_run: bool = False,
    skip_gazette: bool = False,
    skip_mbs: bool = False,
    pause_seconds: float = 0.0,
) -> Iterator[dict[str, Any]]:
    fetch_limit = limit * 4 if (skip_gazette or skip_mbs) else limit
    laws = pending_laws(connection, limit=fetch_limit)
    processed = 0
    first = True
    for law in laws:
        metadata = law.get("metadata") if isinstance(law.get("metadata"), dict) else {}
        gazette_done = metadata.get("verified_against_gazette") is True
        mbs_done = metadata.get("verified_against_mbs") is True
        need_gazette = not gazette_done and not skip_gazette
        need_mbs = not mbs_done and not skip_mbs
        if not need_gazette and not need_mbs:
            continue
        # Kanunlar arasında bekle: bekleme olmadan MBS ~24-30 istekte JSON yerine engel sayfası döndürüyor.
        if pause_seconds > 0 and not first:
            time.sleep(pause_seconds)
        first = False
        try:
            flags, results, requests_made = verify_law_against_portals(
                law,
                gazette_client=gazette_client,
                mbs_client=mbs_client,
                skip_gazette=skip_gazette,
                skip_mbs=skip_mbs,
            )
        except VerificationCooldown as exc:
            if not dry_run and exc.source != "mbs":
                # MBS tüm servis olarak JSON dönmüyorsa (kesinti) hiçbir kanuna deneme damgası vurulmaz.
                # Denemeyi kaydet: aksi halde sıralama (en eski deneme önce) hep aynı kanunu
                # başa koyar ve kalıcı 5xx veren tek bir kanun tüm kuyruğu kilitler.
                apply_law_verification(
                    connection,
                    law,
                    flags={},
                    results={
                        "verify_last_attempt_at": datetime.now(UTC).isoformat(),
                        "verify_cooldown_source": exc.source,
                    },
                )
            yield {
                "law_no": law["law_no"],
                "ready": False,
                "flags": {},
                "results": {},
                "requests_made": 0,
                "cooldown": exc.source,
                "reason": str(exc),
            }
            return
        if not dry_run:
            apply_law_verification(connection, law, flags=flags, results=results)
        yield {
            "law_no": law["law_no"],
            "ready": all(flags.values()),
            "flags": flags,
            "results": results,
            "requests_made": requests_made,
        }
        processed += 1
        if processed >= limit:
            return
