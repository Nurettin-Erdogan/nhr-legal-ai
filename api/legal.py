from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
from datetime import date
from pathlib import Path
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Query
from fastapi import Path as PathParam
from psycopg.errors import QueryCanceled
from starlette.concurrency import run_in_threadpool

from api.ai.seed_tier import seed_tier
from api.ai.turkish_text import restore_turkish
from api.db import database_connection
from api.schemas import (
    AdministrativeBreakdown,
    ChunkEmbeddingBreakdown,
    CorpusStats,
    CourtDecisionBreakdown,
    LegalSearchResponse,
    LegalSourceDetail,
    LegislationVerificationBreakdown,
    ThirdPartyBreakdown,
)

router = APIRouter(prefix="/api/legal", tags=["legal"])

logger = logging.getLogger(__name__)

_STATS_TTL_SECONDS = 4.0
_stats_cache: tuple[float, CorpusStats] | None = None

# `legal_sources` üzerindeki sayımlar 11M+ satırda tek tek 10-40 sn sürüyor (yalın count(*) ölçüldü: 35 sn): istek yolunda (8 sn sınır)
# çalıştırılamaz. Üretimde istatistik diske yazılır, API yeniden başlayınca oradan okunur ve arka planda uzun süreyle tazelenir;
# yoksa (hiç hesaplanmadıysa) uç 503 "hazırlanıyor" der ve hesap başlar. Önbellek yalnız bellekteyken her yeniden başlatma
# ucu bozuyordu (korpus paneli ve "Karar Hukuku" kutusu boş kalıyordu).
_STATS_FILE = Path(__file__).resolve().parents[1] / "data" / "cache" / "corpus_stats.json"
_STATS_REFRESH_SECONDS = 600.0
_STATS_REFRESH_TIMEOUT = "900s"
_stats_lock = threading.Lock()
_stats_refreshing = False

# count(*) over the multi-million-row chunk and seed sets takes 6-15 s, far past
# the 8 s budget of the interactive stats query. They refresh in the background
# and the endpoint serves the last good value in the meantime.
# Public-corpus search results are not user-specific, so repeats are served from
# memory. Common-word queries can still need 15+ s on ~10M chunks, hence 45 s.
_SEARCH_TIMEOUT = "45s"
# Katmanlı arama bu sürede bitmezse (soğuk disk) yalnız resmî katmanın küçük bir örneğiyle yeniden denenir; ilk
# denemenin okuduğu sayfalar önbellekte kaldığından ikinci deneme çoğunlukla hemen döner (ölçüldü: 0,2 sn). Yedeğin
# süresi yine de uzun tutulur: API yeni açıldığında arka plandaki sayım/ısınma sorguları diski meşgul eder ve ilk
# arama iki denemede de 10 sn'yi aşabiliyor (ölçüldü: 2026-10-08).
# İlk deneme 10 sn idi; 4 sn'ye indirildi (2026-10-10): arkada yoğun veri işi çalışırken toplu katmanın 31 GB'lık dizini
# bellekte kalamıyor, on iki aramanın onu 10 sn'yi doldurup ancak ondan sonra resmî katmana düşüyordu (ortanca 11 sn).
# Resmî katman ilk denemede zaten okunmuş olduğundan yedek hemen döner; olağan yükte katmanlı arama 0,9-3,1 sn'de bitiyor
# (ölçüldü: 2026-10-08), yani 4 sn onu kesmez. Toplam en kötü durum ~4 + 20 sn, arayüzün 50 sn bütçesi içinde.
_SEARCH_FULL_TIMEOUT = "4s"
_SEARCH_BOUNDED_TIMEOUT = "20s"
# Katmanlı aramada doğrulanmamış toplu katmandan puanlanan en çok eşleşme sayısı. Örnek zaten rastgeledir (tablo
# sırasındaki ilk eşleşmeler); 5000 yerine 3000, soğuk aramada okunan sayfayı ~%40 azaltır (ölçüldü: 2026-10-08).
_SEARCH_SEED_CAP = 3000
# Resmî katmanda puanlanan en çok eşleşme sayısı. Olağan (çok sözcüklü) aramada eşleşme bunun altındadır ve katman
# tam puanlanır; yaygın tek sözcükte ("tazminat": 492 bin resmî parça) hepsini puanlamak 35 sn sürüp 504 veriyordu.
# Sınır aşılırsa sonuç "kısmi" işaretlenir (bkz. migration 050, docs/legal-search-performance.md).
_SEARCH_OFFICIAL_CAP = 5000
# Zaman aşımı yedeği: toplu katman atlanır, resmî katmandan daha küçük bir örnek puanlanır.
_SEARCH_FALLBACK_OFFICIAL_CAP = 1500
# Toplu katman atlandığında resmî sonuç sayfayı doldurmuyorsa (ölçülen örnekler: 2, 4, 7 sonuç) kullanıcı neredeyse boş bir
# liste görür; o durumda toplu katman daha uzun süreyle bir kez daha denenir. Sayfa doluysa beklenmez. Soğuk önbellekte
# katmanlı arama 4-12 sn sürüyor (ölçüldü: 2026-10-10, bakım sonrası); önceki deneme sayfaları ısıttığı için ikinci
# deneme çoğunlukla yetişir.
_SEARCH_SPARSE_SEED_TIMEOUT = "10s"
# VEYA yedeğinde resmî katmandan puanlanan en çok eşleşme sayısı.
_SEARCH_OR_CANDIDATES = 10000
_SEARCH_WORK_MEM = "64MB"
_SEARCH_CACHE_TTL_SECONDS = 300.0
_SEARCH_CACHE_MAX_ENTRIES = 256
_search_cache: dict[tuple, tuple[float, LegalSearchResponse]] = {}

# Exact chunk counts are slow (see below), so the pill's live number comes from the
# planner's running tuple statistics: instant, updated as rows are committed, and
# approximate. It only overlays the cached exact value.
_LIVE_CHUNKS_TTL_SECONDS = 2.0
_live_chunks: tuple[float, int] | None = None
# "Embedding hazır" sayacı: embedding işçilerinin yazdığı kesin sayım + ilerleme dosyaları (bkz. scripts/embed_chunks.py).
_SHARD_PROGRESS_DIR = Path(__file__).resolve().parents[1] / "data" / "cache"

# The slow counts also live on disk so a restarted API serves the last known totals
# immediately instead of blocking on multi-minute count(*) scans of ~20M chunks.
_SLOW_COUNTS_FILE = Path(__file__).resolve().parents[1] / "data" / "cache" / "slow_counts.json"

_SLOW_COUNTS_TTL_SECONDS = 600.0
# Üçüncü taraf sayısı ağır (10M satır filtresi): chunk sayımı 15 sn'de bir, bu 10 dk'da bir.
_SEED_COUNT_TTL_SECONDS = 600.0
_seed_count_at = 0.0
_SLOW_COUNTS_TIMEOUT = "900s"
_SEED_BREAKDOWN_KEYS = ("seed_yargitay", "seed_danistay", "seed_aym_norm", "seed_emsal")
# Embedding yalnız resmî (`ingest_status = 'ready'`) kayıtlara yapılır; "bekleyen" yalnız onların
# henüz vektörü olmayan parçalarıdır. Doğrulanmamış arşivin parçaları hedef dışıdır ve sayılmaz.
_OFFICIAL_PENDING_SQL = """
SELECT count(*)::int AS official_pending
FROM legal_chunks c
WHERE c.embedding IS NULL
  AND c.legal_source_id = ANY(ARRAY(
      SELECT id FROM legal_sources
      WHERE ingest_status = 'ready' AND is_current AND deleted_at IS NULL
  ))
"""
# `= ANY(ARRAY(...))` planlayıcıyı kaynak-kimliği indeksine zorlar; JOIN'li biçim 28M satırlık
# tam tarama yapıp 15 dakikayı aşıyordu.
_official_pending_at = 0.0
_slow_counts: tuple[float, dict[str, int]] | None = None
_slow_counts_lock = threading.Lock()
_slow_counts_refreshing = False

_VERIFIED_SOURCE_FILTER = """
(
    (
        ls.ingest_status = 'ready'
        AND (
            ls.source_type <> 'legislation'
            OR (
                ls.metadata->>'verified_against_gazette' = 'true'
                OR ls.metadata->>'verified_against_mbs' = 'true'
            )
        )
    )
    -- Doğrulanmamış toplu kayıtlar (`bulk_seed` + `pending`) şimdilik aranmaz ve gösterilmez (kullanıcı kararı 2026-10-18):
    -- doğrulandıkça `ready` olup bu koşula kendiliğinden girer.
)
"""

# %(joiner)s is ' & ' first: an OR of common words ("kıdem | tazminat") matches
# millions of chunks and takes 6-45 s on the full corpus. ' | ' is only the
# fallback when the AND query finds nothing.
_SEARCH_TSQUERY_SQL = """
WITH search_query AS (
    SELECT to_tsquery(
        'turkish',
        array_to_string(
            tsvector_to_array(to_tsvector('turkish', %(query)s)),
            %(joiner)s
        )
    ) AS value
)
"""

_SEARCH_SELECT_COLUMNS = """
        ls.id,
        ls.source_type,
        ls.title,
        ls.source_url,
        ls.authority,
        COALESCE(decision.court_name, CASE WHEN ls.source_type = 'other' THEN ls.authority END) AS court_name,
        decision.chamber,
        decision.docket_no,
        COALESCE(
            decision.decision_no,
            CASE WHEN ls.source_type = 'other' THEN ls.metadata->>'decision_no' END
        ) AS decision_no,
        COALESCE(
            decision.decision_date,
            CASE WHEN ls.source_type = 'other'
                 THEN NULLIF(ls.metadata->>'decision_date', '')::date END
        ) AS decision_date,
        legislation.legislation_type,
        legislation.law_name,
        legislation.law_no,
        legislation.article_no,
        legislation.article_title,
        legislation.official_gazette_date,
        legislation.version_date,
        ls.effective_from,
        ls.effective_to,
        ls.source_version,
        ls.revision,
        -- Yalnız sıralama içindir (yanıttan çıkarılır): üçüncü taraf arşivden gelip henüz doğrulanmamış kayıt.
        (ls.ingestion_method = 'bulk_seed' AND ls.ingest_status = 'pending') AS seed_pending,
        left(chunk.content, 700) AS excerpt
"""

# Sonuç sırası: yeterince ilgili adaylar (en yüksek puanın en az %35'i) içinde önce kanun/KHK maddesi, sonra yüksek mahkeme
# (Yargıtay, Danıştay, AYM, Uyuşmazlık), sonra bölge mahkemeleri, sonra diğerleri; her katmanda puan ve tarih sırası korunur.
# Yalnız metin puanıyla sıralamada "kıdem tazminatı" aramasının başına, bu sözcüğü çok tekrarlayan iflas/rücu dosyalarındaki
# Asliye Ticaret kararları geliyor, aynı havuzdaki Yargıtay 9. HD kararları altta kalıyordu (ölçüldü: 2026-10-06). Katman
# yalnız SIRAYI etkiler: hiçbir kayıt eklenmez/çıkarılmaz, doğrulama rozeti ve "kısmi" bayrağı değişmez. Aynı katmanda resmî
# doğrulanmış kayıt, doğrulanmamış (üçüncü taraf) kayıttan önce gelir; doğrulanmamış kayıt her zaman rozetiyle gösterilir.
_AUTHORITY_ORDER_SQL = """
CASE WHEN rank >= 0.35 * max(rank) OVER () THEN
    CASE
        WHEN source_type = 'legislation' AND legislation_type IN ('law', 'constitution', 'decree') THEN 0
        WHEN court_name ~* '^(yargıtay|danıştay|anayasa mahkemesi|uyuşmazlık mahkemesi)' THEN 1
        WHEN court_name ~* 'bölge (adliye|idare) mahkemesi' THEN 2
        ELSE 3
    END
ELSE 4 END
"""
# Katmanlı sıra sayfalar arasında tutarlı kalsın diye ilk sayfalar aynı aday havuzundan çıkar.
_SEARCH_MIN_CANDIDATES = 300


def _current_search_sql(
    hits_call: str, partial_sql: str = "true", hits_columns: str = "hits.chunk_id, hits.rank"
) -> str:
    return f"""
{_SEARCH_TSQUERY_SQL},
hits AS (
    SELECT {hits_columns}
    FROM search_query
    CROSS JOIN LATERAL {hits_call} AS hits
    WHERE search_query.value IS NOT NULL
),
ranked AS (
    SELECT DISTINCT ON (ls.id)
{_SEARCH_SELECT_COLUMNS},
        hits.rank
    FROM hits
    JOIN legal_chunks chunk ON chunk.id = hits.chunk_id
    JOIN legal_sources ls ON ls.id = chunk.legal_source_id
    LEFT JOIN court_decision_details decision ON decision.legal_source_id = ls.id
    LEFT JOIN legislation_details legislation ON legislation.legal_source_id = ls.id
    WHERE ls.source_type IN ('court_decision', 'legislation', 'other')
      AND ls.deleted_at IS NULL
      AND {_VERIFIED_SOURCE_FILTER}
    ORDER BY ls.id, hits.rank DESC, chunk.chunk_index
)
SELECT ranked.*, count(*) OVER () AS total, {partial_sql} AS partial
FROM ranked
ORDER BY {_AUTHORITY_ORDER_SQL},
         seed_pending,
         rank DESC,
         COALESCE(decision_date, official_gazette_date, version_date) DESC NULLS LAST,
         title
LIMIT %(limit)s OFFSET %(offset)s
"""


# Katmanlı arama: resmî parçalar (kısmi GIN dizini) en çok %(official_cap)s eşleşmeye kadar tam puanlanır,
# doğrulanmamış toplu katmanda yalnız ilk %(seed_cap)s eşleşme puanlanır; bir sınır aşıldıysa sonuç "kısmi" işaretlenir.
_CURRENT_SEARCH_SQL = _current_search_sql(
    "legal_rag_current_lexical_hits_tiered("
    "search_query.value, %(candidate_limit)s, %(seed_cap)s, %(official_cap)s)",
    "(SELECT COALESCE(bool_or(hits.capped), false) FROM hits)",
    "hits.chunk_id, hits.rank, hits.capped",
)
# Geniş (VEYA) yedek: yalnız resmî katmanda sınırlı örnek.
_CURRENT_SEARCH_OR_SQL = _current_search_sql(
    "legal_rag_current_lexical_hits_official_bounded("
    "search_query.value, %(candidate_limit)s, %(or_candidates)s)"
)

_HISTORICAL_SEARCH_SQL = f"""
{_SEARCH_TSQUERY_SQL},
ranked AS (
    SELECT DISTINCT ON (ls.id)
{_SEARCH_SELECT_COLUMNS},
        ts_rank_cd(chunk.search_vector, search_query.value) AS rank
    FROM legal_chunks chunk
    JOIN legal_sources ls ON ls.id = chunk.legal_source_id
    LEFT JOIN court_decision_details decision ON decision.legal_source_id = ls.id
    LEFT JOIN legislation_details legislation ON legislation.legal_source_id = ls.id
    CROSS JOIN search_query
    WHERE ls.source_type IN ('court_decision', 'legislation', 'other')
      AND ls.deleted_at IS NULL
      AND {_VERIFIED_SOURCE_FILTER}
      AND (
          ls.source_type = 'legislation'
          AND ls.effective_from IS NOT NULL
          AND ls.effective_from <= CAST(%(as_of)s AS date)
          AND (
              ls.effective_to IS NULL
              OR ls.effective_to >= CAST(%(as_of)s AS date)
          )
          OR (
              ls.source_type = 'court_decision'
              AND ls.is_current
              AND decision.decision_date IS NOT NULL
              AND decision.decision_date <= CAST(%(as_of)s AS date)
          )
          OR (
              ls.source_type = 'other'
              AND ls.is_current
              AND ls.published_at IS NOT NULL
              AND ls.published_at <= CAST(%(as_of)s AS date)
          )
      )
      AND search_query.value IS NOT NULL
      AND chunk.search_vector @@ search_query.value
    ORDER BY ls.id, rank DESC, chunk.chunk_index
)
SELECT ranked.*, count(*) OVER () AS total
FROM ranked
ORDER BY {_AUTHORITY_ORDER_SQL},
         seed_pending,
         rank DESC,
         COALESCE(decision_date, official_gazette_date, version_date) DESC NULLS LAST,
         title
LIMIT %(limit)s OFFSET %(offset)s
"""

_DETAIL_SQL = f"""
SELECT
    ls.id,
    CASE WHEN ls.ingest_status = 'ready' THEN 'official'
         WHEN ls.ingestion_method = 'bulk_seed' AND ls.ingest_status = 'pending' THEN 'third_party'
         ELSE 'unknown' END AS verification,
    ls.source_type,
    ls.title,
    ls.source_url,
    ls.external_id,
    ls.authority,
    COALESCE(decision.court_name, CASE WHEN ls.source_type = 'other' THEN ls.authority END) AS court_name,
    decision.chamber,
    decision.docket_no,
    COALESCE(
        decision.decision_no,
        CASE WHEN ls.source_type = 'other' THEN ls.metadata->>'decision_no' END
    ) AS decision_no,
    COALESCE(
        decision.decision_date,
        CASE WHEN ls.source_type = 'other'
             THEN NULLIF(ls.metadata->>'decision_date', '')::date END
    ) AS decision_date,
    legislation.legislation_type,
    legislation.law_name,
    legislation.law_no,
    legislation.article_no,
    legislation.article_title,
    legislation.official_gazette_no,
    legislation.official_gazette_date,
    legislation.version_date,
    ls.effective_from,
    ls.effective_to,
    ls.canonical_source_name,
    ls.official_source_url,
    ls.ingestion_method,
    ls.fetched_at,
    ls.last_verified_at,
    ls.content_hash,
    ls.source_version,
    ls.revision,
    ls.is_current,
    ls.superseded_by_id,
    COALESCE(ls.raw_text, '') AS raw_text,
    ls.metadata
FROM legal_sources ls
LEFT JOIN court_decision_details decision ON decision.legal_source_id = ls.id
LEFT JOIN legislation_details legislation ON legislation.legal_source_id = ls.id
WHERE ls.id = %s
  AND ls.source_type IN ('court_decision', 'legislation', 'other')
  AND ls.deleted_at IS NULL
  AND {_VERIFIED_SOURCE_FILTER}
"""


def _database_unavailable(exc: psycopg.Error) -> HTTPException:
    return HTTPException(status_code=503, detail="Hukuk veritabanına şu anda ulaşılamıyor")


def _stats_from_row(row: dict[str, object]) -> CorpusStats:
    return CorpusStats(
        source_count=int(row["source_count"] or 0),
        chunk_count=int(row["chunk_count"] or 0),
        decision_count=int(row["decision_count"] or 0),
        legislation_count=int(row["legislation_count"] or 0),
        other_count=int(row["other_count"] or 0),
        latest_decision_date=row["latest_decision_date"],  # type: ignore[arg-type]
        court_decisions=CourtDecisionBreakdown(
            yargitay=int(row["yargitay_count"] or 0),
            danistay=int(row["danistay_count"] or 0),
            anayasa_mahkemesi=int(row["aym_count"] or 0),
            istinaf_emsal=int(row.get("emsal_count") or 0),
        ),
        administrative=AdministrativeBreakdown(
            kamu_denetciligi_kurumu=int(row["kdk_count"] or 0),
            sayistay=int(row.get("sayistay_count") or 0),
            uyusmazlik_mahkemesi=int(row.get("uyusmazlik_count") or 0),
        ),
        third_party=ThirdPartyBreakdown(
            yargitay=int(row.get("seed_yargitay") or 0),
            danistay=int(row.get("seed_danistay") or 0),
            istinaf_emsal=int(row.get("seed_emsal") or 0),
            aym_norm_denetimi=int(row.get("seed_aym_norm") or 0),
        ),
        legislation_verification=LegislationVerificationBreakdown(
            bedesten=int(row["legislation_bedesten_count"] or 0),
            both_verified=int(row["legislation_both_verified_count"] or 0),
            gazette_only=int(row["legislation_gazette_only_count"] or 0),
            mbs_only=int(row["legislation_mbs_only_count"] or 0),
            neither=int(row["legislation_neither_count"] or 0),
        ),
        embeddings=ChunkEmbeddingBreakdown(
            ready=int(row["chunk_embedded_count"] or 0),
            pending=int(row["chunk_embedding_pending_count"] or 0),
        ),
        seed_count=int(row.get("seed_count") or 0),
    )


def _live_chunk_estimate() -> int | None:
    global _live_chunks
    now = time.monotonic()
    cached = _live_chunks
    if cached is not None and now - cached[0] < _LIVE_CHUNKS_TTL_SECONDS:
        return cached[1]
    try:
        with database_connection() as connection:
            connection.execute("SET LOCAL statement_timeout = '2s'")
            # n_live_tup DB kabı yeniden başlayınca sıfırlanır; reltuples ANALYZE'dan gelir ve korunur.
            row = connection.execute(
                "SELECT greatest(coalesce(s.n_live_tup, 0), c.reltuples::bigint)::bigint AS n "
                "FROM pg_class c LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid "
                "WHERE c.oid = 'public.legal_chunks'::regclass"
            ).fetchone()
    except psycopg.Error:
        return cached[1] if cached is not None else None
    value = int(row["n"]) if row and row["n"] else None
    if value:
        _live_chunks = (now, value)
    return value


def _read_shard_progress() -> dict[str, tuple[float, int]]:
    """Embedding işçilerinin (dilim -> (başlangıç, üretilen)) ilerleme dosyaları."""
    progress: dict[str, tuple[float, int]] = {}
    for path in _SHARD_PROGRESS_DIR.glob("embed_shard_*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            progress[path.stem] = (float(raw["started"]), int(raw["done"]))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return progress


def _read_embedded_base() -> tuple[int, dict[str, tuple[float, int]]] | None:
    """Embedding işçisinin (admin bağlantısıyla) yazdığı son kesin sayım ve o andaki işçi ilerlemesi.

    nhr_runtime ile bu sayım RLS yüzünden 5 dakikada bile bitmiyor; bu yüzden API saymaz, dosyayı okur.
    """
    try:
        raw = json.loads((_SHARD_PROGRESS_DIR / "embed_base.json").read_text(encoding="utf-8"))
        snapshot = {name: (float(pair[0]), int(pair[1])) for name, pair in raw["snapshot"].items()}
        return int(raw["count"]), snapshot
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _live_embedded_count() -> int | None:
    """Embedding hazır sayısı = son kesin sayım + o günden beri işçilerin ürettiği parçalar.

    İşçiler her partide (birkaç sn) ilerleme yazar; kesin sayım işçi tarafından 30 dakikada bir tazelenir.
    """
    if "pytest" in sys.modules:
        return None
    base = _read_embedded_base()
    if base is None:
        return None
    count, snapshot = base
    extra = 0
    for name, (started, done) in _read_shard_progress().items():
        earlier = snapshot.get(name)
        extra += done - earlier[1] if earlier is not None and earlier[0] == started else done
    return count + max(extra, 0)


def _read_embed_progress_ready() -> int | None:
    from api.embed_progress import read_ready

    return read_ready()


def _with_live_chunks(stats: CorpusStats) -> CorpusStats:
    live = _live_chunk_estimate()
    if not live:
        return stats
    ready = _live_embedded_count() or _read_embed_progress_ready() or stats.embeddings.ready
    total = max(live, ready)
    # Bekleyen sayısı yavaş sayımdan gelir ve yalnız resmî parçaları kapsar; toplu arşivin
    # embedding'i yapılmadığı için `toplam - hazır` "bekleyen" olarak gösterilmez.
    pending = stats.embeddings.pending if _official_pending_at else total - ready
    return stats.model_copy(
        update={
            "chunk_count": total,
            "embeddings": stats.embeddings.model_copy(update={"ready": ready, "pending": pending}),
        }
    )


@router.get("/stats", response_model=CorpusStats)
def corpus_stats() -> CorpusStats:
    return _with_live_chunks(_corpus_stats_cached())


def _stats_in_background() -> bool:
    """Üretimde sayımlar istek yolunda değil arka planda yenilenir; testler satır içi yolu kullanır."""
    return "pytest" not in sys.modules


def _read_stats_file() -> tuple[float, CorpusStats] | None:
    try:
        raw = json.loads(_STATS_FILE.read_text(encoding="utf-8"))
        stats = CorpusStats.model_validate(raw["stats"])
        age = max(0.0, time.time() - float(raw["saved_at"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return time.monotonic() - age, stats


def _write_stats_file(stats: CorpusStats) -> None:
    try:
        _STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = _STATS_FILE.with_suffix(".tmp")
        payload = {"saved_at": time.time(), "stats": json.loads(stats.model_dump_json())}
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(_STATS_FILE)
    except OSError:
        logger.warning("Korpus istatistikleri diske yazılamadı", exc_info=True)


def _refresh_stats_in_background() -> None:
    global _stats_cache, _stats_refreshing
    with _stats_lock:
        if _stats_refreshing:
            return
        _stats_refreshing = True

    def refresh() -> None:
        global _stats_cache, _stats_refreshing
        try:
            stats = _load_corpus_stats(_STATS_REFRESH_TIMEOUT)
            _stats_cache = (time.monotonic(), stats)
            _write_stats_file(stats)
        except (psycopg.Error, RuntimeError, OSError):
            logger.exception("Korpus istatistikleri yenilenemedi")
        finally:
            with _stats_lock:
                _stats_refreshing = False

    threading.Thread(target=refresh, name="corpus-stats", daemon=True).start()


def _corpus_stats_cached() -> CorpusStats:
    global _stats_cache
    now = time.monotonic()
    cached = _stats_cache
    if _stats_in_background():
        if cached is None:
            cached = _read_stats_file()
            if cached is not None:
                _stats_cache = cached
        if cached is None:
            _refresh_stats_in_background()
            raise HTTPException(
                status_code=503,
                detail="Korpus istatistikleri hazırlanıyor; birkaç dakika sonra yeniden deneyin",
                headers={"Retry-After": "60"},
            )
        if now - cached[0] >= _STATS_REFRESH_SECONDS:
            _refresh_stats_in_background()
        return cached[1]
    if cached is not None and now - cached[0] < _STATS_TTL_SECONDS:
        return cached[1]
    try:
        stats = _load_corpus_stats()
    except psycopg.Error as exc:
        if cached is not None:
            logger.warning("Korpus istatistikleri yenilenemedi, eski değer sunuluyor: %s", exc)
            return cached[1]
        raise _database_unavailable(exc) from exc
    _stats_cache = (time.monotonic(), stats)
    return stats


# Toplam parça sayısı istatistikten (tam tarama yok); "embedding hazır" kısmi indeksten
# (`idx_legal_chunks_embedded`, migration 023) sayılır. Eskiden tek geçişte üç sayım 21M satırı
# tarıyor, embedding yazarken 120 sn sınırını aşıp sayaç donuyordu.
_CHUNK_COUNTS_SQL = """
SELECT
    total.n AS chunk_count,
    embedded.n AS chunk_embedded_count,
    greatest(total.n - embedded.n, 0) AS chunk_embedding_pending_count
FROM (
    SELECT coalesce(max(n_live_tup), 0)::int AS n
    FROM pg_stat_user_tables WHERE relname = 'legal_chunks'
) total,
(
    SELECT count(*)::int AS n FROM legal_chunks WHERE embedding IS NOT NULL
) embedded
"""

_SEED_COUNT_SQL = """
SELECT
    count(*)::int AS seed_count,
    count(*) FILTER (WHERE COALESCE(ls.authority, '') = 'Yargıtay')::int AS seed_yargitay,
    count(*) FILTER (WHERE COALESCE(ls.authority, '') = 'Danıştay')::int AS seed_danistay,
    count(*) FILTER (WHERE COALESCE(ls.authority, '') = 'Anayasa Mahkemesi')::int AS seed_aym_norm,
    count(*) FILTER (
        WHERE COALESCE(ls.authority, '') NOT IN ('Yargıtay', 'Danıştay', 'Anayasa Mahkemesi')
    )::int AS seed_emsal
FROM legal_sources ls
WHERE ls.ingestion_method = 'bulk_seed'
  AND ls.ingest_status = 'pending'
  AND ls.deleted_at IS NULL
  AND ls.is_current
  AND ls.source_type = 'court_decision'
"""


def _load_slow_counts(previous: dict[str, int] | None = None) -> dict[str, int]:
    """Her sayım ayrı sorguda: biri zaman aşımına uğrarsa diğeri yine tazelenir.

    Tek blokta çalışırken 21M satırlık chunk sayımı 120 sn sınırını aşıyor ve aynı
    istisna üçüncü taraf sayısını da tazelenmemiş bırakıyordu; kutudaki sayı donuyordu.
    """
    counts: dict[str, int] = dict(previous or {})
    failures: list[str] = []
    global _seed_count_at, _official_pending_at

    # Exact count(*) on legal_chunks takes minutes once the corpus has tens of
    # millions of rows.  The API already has lightweight live/progress counters;
    # use those so a stats refresh cannot compete with ingestion for disk I/O.
    chunk_count = _live_chunk_estimate()
    if chunk_count is not None:
        counts["chunk_count"] = chunk_count
    embedded_count = _live_embedded_count()
    if embedded_count is None:
        embedded_count = _read_embed_progress_ready()
    if embedded_count is not None:
        counts["chunk_embedded_count"] = embedded_count
    if "official_pending" not in counts and "chunk_count" in counts and "chunk_embedded_count" in counts:
        counts["chunk_embedding_pending_count"] = max(
            counts["chunk_count"] - counts["chunk_embedded_count"], 0
        )

    queries: list[tuple[str, str]] = []
    if "chunk_embedded_count" not in counts or "chunk_count" not in counts:
        # Canlı sayaç/ilerleme dosyası yoksa (yeni kurulum, dosya silinmiş) eski kısmi indeks
        # sayımına düşülür; aksi halde istatistik ucu anahtar eksikliğiyle çöker.
        queries.append(("chunk", _CHUNK_COUNTS_SQL))
    if "seed_count" not in counts or time.monotonic() - _seed_count_at >= _SEED_COUNT_TTL_SECONDS:
        queries.append(("seed", _SEED_COUNT_SQL))
    if "official_pending" not in counts or time.monotonic() - _official_pending_at >= _SEED_COUNT_TTL_SECONDS:
        queries.append(("official", _OFFICIAL_PENDING_SQL))
    for label, sql in queries:
        try:
            with database_connection() as connection:
                connection.execute(f"SET LOCAL statement_timeout = '{_SLOW_COUNTS_TIMEOUT}'")
                counts.update(dict(connection.execute(sql).fetchone()))
            if label == "seed":
                _seed_count_at = time.monotonic()
            elif label == "official":
                _official_pending_at = time.monotonic()
        except psycopg.Error:
            failures.append(label)
    if "official_pending" in counts:
        counts["chunk_embedding_pending_count"] = counts["official_pending"]
    if failures:
        logger.warning("Ağır sayımlar tazelenemedi: %s (eski değer korunuyor)", ", ".join(failures))
    if not counts:
        raise RuntimeError("Hiçbir ağır sayım alınamadı")
    return counts


def _read_slow_counts_file() -> dict[str, int] | None:
    global _official_pending_at
    if "pytest" in sys.modules:
        return None
    try:
        raw = json.loads(_SLOW_COUNTS_FILE.read_text(encoding="utf-8"))
        counts = {key: int(raw[key]) for key in ("chunk_count", "chunk_embedded_count", "chunk_embedding_pending_count", "seed_count")}
        counts.update({key: int(raw[key]) for key in (*_SEED_BREAKDOWN_KEYS, "official_pending") if key in raw})
        if "official_pending" in counts:
            # Dosyadaki değer son sayımdan; yeniden başlatmada da "toplam - hazır" gösterilmesin.
            _official_pending_at = time.monotonic()
        return counts
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_slow_counts_file(counts: dict[str, int]) -> None:
    if "pytest" in sys.modules:
        return
    try:
        _SLOW_COUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SLOW_COUNTS_FILE.write_text(json.dumps(counts), encoding="utf-8")
    except OSError:
        logger.warning("Ağır sayımlar diske yazılamadı", exc_info=True)


def _refresh_slow_counts_in_background() -> None:
    global _slow_counts, _slow_counts_refreshing
    with _slow_counts_lock:
        if _slow_counts_refreshing:
            return
        _slow_counts_refreshing = True

    def refresh() -> None:
        global _slow_counts, _slow_counts_refreshing
        try:
            previous = _slow_counts[1] if _slow_counts else None
            counts = _load_slow_counts(previous)
            _slow_counts = (time.monotonic(), counts)
            _write_slow_counts_file(counts)
        except (psycopg.Error, RuntimeError):
            logger.exception("Ağır korpus sayımları yenilenemedi")
        finally:
            with _slow_counts_lock:
                _slow_counts_refreshing = False

    threading.Thread(target=refresh, name="corpus-slow-counts", daemon=True).start()


def _slow_counts_snapshot() -> dict[str, int]:
    """Chunk and seed totals: computed once inline, then refreshed off the request path."""
    global _slow_counts
    cached = _slow_counts
    if cached is None:
        with _slow_counts_lock:
            if _slow_counts is None:
                on_disk = _read_slow_counts_file()
                if on_disk is not None:
                    # Serve the last known totals now; the stale timestamp triggers a refresh.
                    _slow_counts = (time.monotonic() - _SLOW_COUNTS_TTL_SECONDS, on_disk)
                else:
                    counts = _load_slow_counts()
                    _slow_counts = (time.monotonic(), counts)
                    _write_slow_counts_file(counts)
            cached = _slow_counts
        if time.monotonic() - cached[0] >= _SLOW_COUNTS_TTL_SECONDS:
            _refresh_slow_counts_in_background()
        return cached[1]
    if time.monotonic() - cached[0] >= _SLOW_COUNTS_TTL_SECONDS:
        _refresh_slow_counts_in_background()
    return cached[1]


def warm_slow_counts() -> None:
    """Fill the slow-count cache at startup so the first page load does not wait."""
    try:
        _slow_counts_snapshot()
    except psycopg.Error:
        logger.exception("Korpus sayımları ısıtılamadı")
    if _stats_in_background():
        # Kalıcı istatistik dosyası varsa bellek önbelleğine alınır; yoksa (ya da bayatsa) arka planda hesaplanır.
        global _stats_cache
        cached = _stats_cache or _read_stats_file()
        if cached is not None:
            _stats_cache = cached
        if cached is None or time.monotonic() - cached[0] >= _STATS_REFRESH_SECONDS:
            _refresh_stats_in_background()


def _load_corpus_stats(timeout: str = "8s") -> CorpusStats:
    bedesten = (
        "ls.source_type = 'legislation'"
        " AND ls.ingestion_method = 'bedesten_public_json_http'"
    )
    with database_connection() as connection:
        connection.execute(f"SET LOCAL statement_timeout = '{timeout}'")
        row = connection.execute(
            """
            SELECT
                count(*) FILTER (
                    WHERE ls.source_type = 'court_decision'
                )::int AS decision_count,
                count(*) FILTER (
                    WHERE ls.source_type = 'court_decision'
                      AND COALESCE(ls.authority, '') = 'Yargıtay'
                )::int AS yargitay_count,
                count(*) FILTER (
                    WHERE ls.source_type = 'court_decision'
                      AND COALESCE(ls.authority, '') = 'Danıştay'
                )::int AS danistay_count,
                count(*) FILTER (
                    WHERE ls.source_type = 'court_decision'
                      AND COALESCE(ls.authority, '') = 'Anayasa Mahkemesi'
                )::int AS aym_count,
                count(*) FILTER (
                    WHERE ls.source_type = 'court_decision'
                      AND COALESCE(ls.authority, '') NOT IN ('Yargıtay', 'Danıştay', 'Anayasa Mahkemesi')
                )::int AS emsal_count,
                count(*) FILTER (
                    WHERE ls.source_type = 'other'
                )::int AS other_count,
                count(*) FILTER (
                    WHERE ls.source_type = 'other'
                      AND COALESCE(ls.authority, '') = 'Kamu Denetçiliği Kurumu'
                )::int AS kdk_count,
                count(*) FILTER (
                    WHERE ls.source_type = 'other'
                      AND COALESCE(ls.authority, '') = 'Sayıştay'
                )::int AS sayistay_count,
                count(*) FILTER (
                    WHERE ls.source_type = 'other'
                      AND COALESCE(ls.authority, '') = 'Uyuşmazlık Mahkemesi'
                )::int AS uyusmazlik_count,
                max(ls.published_at) FILTER (
                    WHERE ls.source_type = 'court_decision'
                )::date AS latest_decision_date
            FROM legal_sources ls
            WHERE ls.deleted_at IS NULL
              AND ls.is_current
              AND ls.ingest_status = 'ready'
              AND ls.source_type IN ('court_decision', 'other')
            """
        ).fetchone()
        legislation = connection.execute(
            """
            SELECT count(*)::int AS legislation_count
            FROM legal_sources ls
            WHERE ls.source_type = 'legislation'
              AND ls.deleted_at IS NULL
              AND ls.is_current
              AND ls.ingest_status = 'ready'
              AND (ls.metadata->>'verified_against_gazette' = 'true' OR ls.metadata->>'verified_against_mbs' = 'true')
            """
        ).fetchone()
        verification = connection.execute(
            f"""
            SELECT
                count(*)::int AS legislation_bedesten_count,
                count(*) FILTER (
                    WHERE ls.metadata->>'verified_against_gazette' = 'true'
                      AND ls.metadata->>'verified_against_mbs' = 'true'
                )::int AS legislation_both_verified_count,
                count(*) FILTER (
                    WHERE ls.metadata->>'verified_against_gazette' = 'true'
                      AND ls.metadata->>'verified_against_mbs' IS DISTINCT FROM 'true'
                )::int AS legislation_gazette_only_count,
                count(*) FILTER (
                    WHERE ls.metadata->>'verified_against_mbs' = 'true'
                      AND ls.metadata->>'verified_against_gazette' IS DISTINCT FROM 'true'
                )::int AS legislation_mbs_only_count,
                count(*) FILTER (
                    WHERE ls.metadata->>'verified_against_gazette' IS DISTINCT FROM 'true'
                      AND ls.metadata->>'verified_against_mbs' IS DISTINCT FROM 'true'
                )::int AS legislation_neither_count
            FROM legal_sources ls
            WHERE {bedesten}
              AND ls.deleted_at IS NULL
              AND ls.is_current
            """
        ).fetchone()
    payload = dict(row)
    payload.update(dict(legislation))
    payload["source_count"] = (
        int(payload["decision_count"] or 0)
        + int(payload["legislation_count"] or 0)
        + int(payload["other_count"] or 0)
    )
    payload.update(dict(verification))
    payload.update(_slow_counts_snapshot())
    return _stats_from_row(payload)


def _verification_labels(source_ids: list) -> dict:
    """Sonuçların resmî mi üçüncü taraf mı olduğu (AI hattıyla aynı kural: `bulk_seed` + `pending` = üçüncü taraf).

    Birincil anahtarla ≤50 satır: ucuz. Okunamazsa hata verilir; etiketsiz sonuç "resmî" diye sunulmaz.
    """
    if not source_ids:
        return {}
    try:
        with database_connection() as connection:
            connection.execute("SET LOCAL statement_timeout = '5s'")
            rows = connection.execute(
                "SELECT id, COALESCE(ingestion_method = 'bulk_seed' AND ingest_status = 'pending', false) AS third_party "
                "FROM legal_sources WHERE id = ANY(%s)",
                (source_ids,),
            ).fetchall()
    except psycopg.Error as exc:
        raise _database_unavailable(exc) from exc
    return {row["id"]: ("third_party" if row["third_party"] else "official") for row in rows}


# "4857 sayılı Kanun 25", "6098 m. 344" gibi açık madde atfı: madde metninde kanun numarası geçmediği için sözcük araması
# maddenin kendisini bulamıyor, yalnız ona atıf yapan kararları getiriyordu (ölçüldü: 2026-10-06). Atıf tanınırsa resmî
# doğrulanmış güncel madde ilk sıraya eklenir; madde korpusta yoksa hiçbir şey eklenmez.
_EXPLICIT_ARTICLE_RE = re.compile(
    r"(?<![\d/])(\d{3,5})(?![\d/])\s*(?:sayılı|sayili)?\s*(?:\w+\s+){0,3}?(?:kanun\w*|yasa\w*|khk)?\s*(?:m(?:d|adde)?\.?\s*)?(\d{1,3})(?:\s*\.?\s*madde\w*)?\s*$",
    re.IGNORECASE,
)
_ARTICLE_HIT_SQL = f"""
SELECT
{_SEARCH_SELECT_COLUMNS},
    0::real AS rank
FROM legal_sources ls
JOIN legislation_details legislation ON legislation.legal_source_id = ls.id
LEFT JOIN court_decision_details decision ON decision.legal_source_id = ls.id
JOIN LATERAL (
    SELECT c.content FROM legal_chunks c WHERE c.legal_source_id = ls.id ORDER BY c.chunk_index LIMIT 1
) chunk ON true
WHERE legislation.law_no = %(law_no)s AND legislation.article_no = %(article_no)s
  AND ls.source_type = 'legislation' AND ls.deleted_at IS NULL AND ls.is_current
  AND {_VERIFIED_SOURCE_FILTER}
LIMIT 1
"""


def explicit_article_reference(query: str) -> tuple[str, str] | None:
    """Sorgu yalnız bir kanun numarası ve madde numarasından oluşuyorsa (kanun no, madde no); değilse None."""
    from api import legislation_browse

    marked = legislation_browse.parse_reference(query)
    if marked:
        return marked
    match = _EXPLICIT_ARTICLE_RE.search(query.strip())
    if not match or len(query.split()) > 8:
        return None
    return match.group(1), match.group(2)


def _explicit_article_hit(query: str) -> dict | None:
    reference = explicit_article_reference(query)
    if reference is None:
        return None
    try:
        with database_connection() as connection:
            connection.execute("SET LOCAL statement_timeout = '3s'")
            row = connection.execute(_ARTICLE_HIT_SQL, {"law_no": reference[0], "article_no": reference[1]}).fetchone()
    except psycopg.Error:
        return None
    return dict(row) if row else None


@router.get("/search", response_model=LegalSearchResponse)
def search_legal_sources(
    q: str = Query(min_length=2, max_length=300),
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    as_of: date | None = None,
) -> LegalSearchResponse:
    query = " ".join(q.split())
    params: dict[str, object] = {
        # ASCII yazılmış arama ("kidem tazminati") için aksanlar yalnız arama metninde geri getirilir.
        "query": restore_turkish(query),
        "limit": limit,
        "offset": offset,
        "as_of": as_of,
        "candidate_limit": max(_SEARCH_MIN_CANDIDATES, (offset + limit) * 10),
        "seed_cap": _SEARCH_SEED_CAP,
        "official_cap": _SEARCH_OFFICIAL_CAP,
        "or_candidates": _SEARCH_OR_CANDIDATES,
    }
    sql = _HISTORICAL_SEARCH_SQL if as_of is not None else _CURRENT_SEARCH_SQL

    cache_key = (query, limit, offset, as_of)
    cached = _search_cache.get(cache_key)
    if cached is not None and time.monotonic() - cached[0] < _SEARCH_CACHE_TTL_SECONDS:
        return cached[1]

    def run(
        joiner: str,
        statement: str = sql,
        timeout: str = _SEARCH_TIMEOUT,
        overrides: dict[str, object] | None = None,
    ) -> list[dict]:
        # Docker'ın 64 MB /dev/shm'i büyük paralel taramalarda dolabilir ("could not resize
        # shared memory segment", DiskFull); o zaman aynı sorgu paralel işçisiz yeniden denenir.
        for parallel_workers in (2, 0):
            try:
                with database_connection() as connection:
                    connection.execute(f"SET LOCAL statement_timeout = '{timeout}'")
                    # 4 MB varsayılan work_mem ile yüz binlerce eşleşen parçanın sıralanması
                    # diske taşıp sayfaları tekrar tekrar okur; 64 MB bunu belirgin azaltır.
                    connection.execute(f"SET LOCAL work_mem = '{_SEARCH_WORK_MEM}'")
                    connection.execute("SET LOCAL jit = off")
                    connection.execute(
                        f"SET LOCAL max_parallel_workers_per_gather = {parallel_workers}"
                    )
                    return connection.execute(
                        statement, {**params, **(overrides or {}), "joiner": joiner}
                    ).fetchall()
            except psycopg.errors.DiskFull:
                if parallel_workers == 0:
                    raise
                logger.warning("Paylaşımlı bellek yetmedi, paralelsiz yeniden deneniyor: %r", query)
        return []

    bounded = as_of is None  # sınırlı aday sürümü yalnız güncel aramada var
    try:
        skipped_seed_tier = False
        try:
            if bounded and not seed_tier.allow():
                # Toplu katman az önce art arda zaman aşımına uğradı (bkz. api.ai.seed_tier): bir süre hiç denenmez, arama
                # doğrudan resmî katmanla döner; sonuç "kısmi" işaretlenir.
                # Sigorta açıksa disk yük altındadır: resmî katmandan da küçük örnek puanlanır (5 000 parçanın puanlanması
                # o sırada 4 sn'yi aşıp ikinci bir denemeye yol açıyordu; ölçüldü: 2026-10-10).
                rows = run(
                    " & ", sql, _SEARCH_BOUNDED_TIMEOUT,
                    {"seed_cap": 0, "official_cap": _SEARCH_FALLBACK_OFFICIAL_CAP},
                )
                skipped_seed_tier = True
            else:
                rows = run(" & ", sql, _SEARCH_FULL_TIMEOUT if bounded else _SEARCH_TIMEOUT)
                if bounded:
                    seed_tier.record(True)
        except QueryCanceled:
            if not bounded:
                raise
            if seed_tier.allow():
                seed_tier.record(False)
            # Soğuk diskte katmanlı arama yetişmedi: toplu katman atlanır, resmî katmandan daha küçük bir örnek
            # puanlanır; sonuç her zaman "kısmi" işaretlenir.
            logger.warning("Katmanlı arama zaman aşımı, yalnız resmî katman: %r", query)
            rows = run(
                " & ", sql, _SEARCH_BOUNDED_TIMEOUT,
                {"seed_cap": 0, "official_cap": _SEARCH_FALLBACK_OFFICIAL_CAP},
            )
            skipped_seed_tier = True
        if skipped_seed_tier and (int(rows[0]["total"]) if rows else 0) < offset + limit:
            # Resmî sonuç sayfayı doldurmuyor: doğrulanmamış katman olmadan liste neredeyse boş kalır, bu yüzden beklenir.
            try:
                rows = run(" & ", sql, _SEARCH_SPARSE_SEED_TIMEOUT)
                seed_tier.record(True)
            except QueryCanceled:
                logger.warning("Az sonuçlu aramada toplu katman yine yetişmedi: %r", query)
        if not rows:
            try:
                rows = (
                    run(" | ", _CURRENT_SEARCH_OR_SQL, _SEARCH_BOUNDED_TIMEOUT)
                    if bounded
                    else run(" | ")
                )
            except QueryCanceled:
                logger.warning("Geniş (VEYA) arama zaman aşımına uğradı: %r", query)
    except QueryCanceled as exc:
        logger.warning("Arama zaman aşımına uğradı: %r", query)
        raise HTTPException(
            status_code=504,
            detail="Arama zaman aşımına uğradı; daha belirgin sözcüklerle yeniden deneyin",
        ) from exc
    except psycopg.Error as exc:
        raise _database_unavailable(exc) from exc

    total = int(rows[0]["total"]) if rows else 0
    partial = bool(rows[0].get("partial")) if rows else False
    results = [dict(row) for row in rows]
    if offset == 0 and as_of is None:
        article = _explicit_article_hit(params["query"])  # type: ignore[arg-type]
        if article is not None and all(result["id"] != article["id"] for result in results):
            results = [article, *results][:limit]
            total += 1
    for result in results:
        result.pop("total", None)
        result.pop("partial", None)
        result.pop("seed_pending", None)
    labels = _verification_labels([result["id"] for result in results])
    for result in results:
        result["verification"] = labels.get(result["id"], "unknown")
    response = LegalSearchResponse(
        query=query,
        as_of=as_of,
        total=total,
        partial=partial,
        limit=limit,
        offset=offset,
        results=results,
    )
    if len(_search_cache) >= _SEARCH_CACHE_MAX_ENTRIES:
        _search_cache.pop(next(iter(_search_cache)), None)
    _search_cache[cache_key] = (time.monotonic(), response)
    return response


# --- Olay anlatımıyla arama: "olayı anlat, benzer kararı bul" --------------------------------------------------------
# Sohbet hattının AYARLI hibrit getirmesini (api.ai.retrieval.retrieve_contexts) liste olarak sunar: hukuki ifade tanıma,
# kanun/madde eşleme, tam korpus sözcük araması (resmî + doğrulanmamış toplu katman) ve gömme tabanlı en yakın komşu.
# Yalnız gömme + basit sözcük örtüşmesi denendi ve zayıf kaldı ("kıdem tazminatı" sorusuna işyeri ruhsatı kanunu geliyordu:
# gömme modeli Türkçe hukuk için güçlü değil ve gömme yalnız resmî katmanda var). Doğrulama etiketi bağlamdan gelir:
# üçüncü taraf kayıtlar `third_party` olarak ayrı işaretlenir. Sorgu metni günlüğe YAZILMAZ: olay anlatımı müvekkil bilgisi içerebilir.
_SEMANTIC_MAX_RESULTS = 60
_SEMANTIC_RETRY_BELOW = 6  # kısmi getirme bu kadardan az kaynak verirse bir kez daha denenir
_semantic_cache: dict[tuple, tuple[float, LegalSearchResponse]] = {}


def _semantic_contexts(question: str, embedding: list[float] | None, model: str, top_k: int, info: dict) -> list:
    from api.ai.retrieval import retrieve_contexts

    # Soğuk önbellekte kollar zaman aşımına uğrayabilir: ilk deneme okuduğu sayfaları önbelleğe bırakır, ikinci deneme çoğunlukla geçer.
    # Getirme bir kol düşse bile kalanıyla döner ("kıdem tazminatı" anlatımında yalnız kanun maddesi kalıyordu): kısmi ve az sonuçlu
    # ilk deneme de bir kez yenilenir, iki denemeden çok sonuç vereni kullanılır.
    best: list = []
    for attempt in (1, 2):
        attempt_info: dict = {}
        try:
            with database_connection() as connection:
                contexts = retrieve_contexts(
                    connection, question=question, top_k=top_k,
                    query_embedding=embedding, embedding_model=model if embedding is not None else None,
                    diagnostics=attempt_info,
                )
        except QueryCanceled:
            if attempt == 2 and not best:
                raise
            continue
        if len(contexts) > len(best):
            best = contexts
            info.clear()
            info.update(attempt_info)
        if not (attempt_info.get("partial") and len(contexts) < _SEMANTIC_RETRY_BELOW):
            break
    return best


def _hit_from_context(context) -> dict:
    return {
        "id": context.source_id,
        "source_type": context.source_type,
        "title": context.title,
        "source_url": context.source_url,
        "authority": context.authority,
        "court_name": context.court_name,
        "chamber": context.chamber,
        "docket_no": context.docket_no,
        "decision_no": context.decision_no,
        "decision_date": context.decision_date,
        "legislation_type": None,
        "law_name": context.law_name,
        "law_no": context.law_no,
        "article_no": context.article_no,
        "article_title": context.article_title,
        "official_gazette_date": None,
        "version_date": context.version_date,
        "effective_from": context.effective_from,
        "effective_to": context.effective_to,
        "source_version": context.source_version,
        "revision": context.revision or 1,
        "excerpt": (context.content or "")[:700],
        "rank": float(context.rank),
        "verification": "third_party" if context.verification == "third_party" else "official" if context.verification == "official" else "unknown",
    }


@router.get("/semantic", response_model=LegalSearchResponse)
async def semantic_search_sources(
    q: str = Query(min_length=10, max_length=1500),
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> LegalSearchResponse:
    """Olayı doğal dille anlatan sorgu için benzer karar/mevzuat listesi (sohbet hattıyla aynı hibrit getirme)."""
    from api.ai.pipeline import _embed_question
    from api.config import get_settings

    query = " ".join(restore_turkish(" ".join(q.split())).split())
    cache_key = (query, limit, offset)
    cached = _semantic_cache.get(cache_key)
    if cached is not None and time.monotonic() - cached[0] < _SEARCH_CACHE_TTL_SECONDS:
        return cached[1]
    embedding = await _embed_question(query)  # None: gömme servisi yok, yalnız sözcük araması yapılır (sonuç "kısmi" işaretlenir)
    top_k = min(_SEMANTIC_MAX_RESULTS, offset + limit + 10)
    info: dict = {}
    try:
        contexts = await run_in_threadpool(_semantic_contexts, query, embedding, get_settings().embedding_model, top_k, info)
    except QueryCanceled as exc:
        raise HTTPException(status_code=504, detail="Arama zaman aşımına uğradı; olayı daha kısa ve belirgin anlatın") from exc
    except psycopg.Error as exc:
        raise _database_unavailable(exc) from exc
    unique: dict = {}
    for context in contexts:
        unique.setdefault(context.source_id, context)
    ordered = list(unique.values())
    page = [_hit_from_context(context) for context in ordered[offset : offset + limit]]
    response = LegalSearchResponse(
        query=query,
        total=len(ordered),
        # Getirme en iyi ~60 kaynakla sınırlıdır: "toplam" bu havuzdaki kaynak sayısıdır, korpusun tamamı değil.
        partial=True,
        limit=limit,
        offset=offset,
        results=page,
    )
    if len(_semantic_cache) >= _SEARCH_CACHE_MAX_ENTRIES:
        _semantic_cache.pop(next(iter(_semantic_cache)), None)
    _semantic_cache[cache_key] = (time.monotonic(), response)
    return response


# --- Mevzuat gezgini: kanun listesi ve madde dizini (api.legislation_browse) ---------------------------------------------
def _load_laws_cached():
    from api import legislation_browse

    def loader():
        with database_connection() as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            return legislation_browse.load_laws(connection)

    return legislation_browse.cached_laws(loader)


@router.get("/laws")
async def list_laws(
    q: str = Query(default="", max_length=200),
    kind: str | None = Query(default=None, pattern="^(constitution|law|decree|regulation|communique|other)$"),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Resmî doğrulanmış güncel mevzuat listesi; ad ya da numarayla aranır ("4857", "is kanunu", "4857 m. 18")."""
    from api import legislation_browse

    try:
        laws = await run_in_threadpool(_load_laws_cached)
    except psycopg.Error as exc:
        raise _database_unavailable(exc) from exc
    found = legislation_browse.search_laws(laws, q, kind)
    reference = legislation_browse.parse_reference(q)
    return {
        "query": q,
        "total": len(found),
        "limit": limit,
        "offset": offset,
        "article_reference": {"law_no": reference[0], "article_no": reference[1]} if reference and found and found[0].law_no == reference[0] else None,
        "results": [law.as_dict() for law in found[offset : offset + limit]],
    }


@router.get("/laws/{law_no}")
async def law_articles(law_no: str = PathParam(pattern="^[0-9A-Za-z]{1,20}$")) -> dict:
    """Bir mevzuatın madde dizini (madde no sırasıyla). Madde metni `/api/legal/sources/{id}` ile okunur."""
    from api import legislation_browse

    def load():
        with database_connection() as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            return legislation_browse.load_articles(connection, law_no)

    try:
        result = await run_in_threadpool(load)
    except QueryCanceled as exc:
        raise HTTPException(status_code=504, detail="Madde dizini zaman aşımına uğradı; yeniden deneyin") from exc
    except psycopg.Error as exc:
        raise _database_unavailable(exc) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Bu numarayla doğrulanmış mevzuat bulunamadı")
    return result


@router.get("/sources/{source_id}", response_model=LegalSourceDetail)
def legal_source_detail(source_id: UUID) -> LegalSourceDetail:
    try:
        with database_connection() as connection:
            source = connection.execute(_DETAIL_SQL, (source_id,)).fetchone()
            if source is None:
                raise HTTPException(status_code=404, detail="Hukuk kaynağı bulunamadı")
            chunks = connection.execute(
                """
                SELECT id, chunk_index, content
                FROM legal_chunks
                WHERE legal_source_id = %s
                ORDER BY chunk_index
                """,
                (source_id,),
            ).fetchall()
    except HTTPException:
        raise
    except psycopg.Error as exc:
        raise _database_unavailable(exc) from exc

    return LegalSourceDetail(**source, chunks=chunks)
