"""Yargıtay korpusu için komut satırı arayüzü.

Tarama ve veritabanına aktarım ayrı adımlardır; portal yeniden taranmadan
arşivden aktarım tekrarlanabilir.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

from ingestion.yargitay.archive import DecisionArchive
from ingestion.yargitay.chunking import DEFAULT_MAX_CHARS

DEFAULT_ARCHIVE_DIR = Path("data/yargitay")

logger = logging.getLogger("ingestion")


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _resolve_database_url(explicit: str | None) -> str:
    load_dotenv()
    database_url = explicit or os.getenv("DATABASE_ADMIN_URL")

    if not database_url:
        raise SystemExit(
            "DATABASE_ADMIN_URL tanımlı değil. .env dosyasını doldurun veya "
            "--database-url ile yönetim bağlantısını verin."
        )

    return database_url


def _run_scrape(args: argparse.Namespace) -> int:
    from ingestion.yargitay.portal import PortalError
    from ingestion.yargitay.scraper import ScraperConfig, YargitayScraper

    config = ScraperConfig(
        keyword=args.keyword,
        chamber=args.chamber,
        max_decisions=args.max_decisions,
        output_dir=args.archive_dir,
        page_size=args.page_size,
        delay_seconds=args.delay,
        timeout_seconds=args.timeout,
        max_retries=args.max_retries,
        refresh_existing=args.refresh_existing,
    )
    scraper = YargitayScraper(config)
    try:
        stats = asyncio.run(scraper.run())
    except PortalError as exc:
        logger.error("Yargıtay aktarımı durdu: %s", exc)
        return 2

    logger.info(
        "Arşiv: %s | işlenen=%s | yeni/güncel=%s | aynı=%s | hatalı=%s | bulunan=%s",
        scraper.archive.root,
        stats.processed,
        stats.saved,
        stats.duplicates,
        stats.failed,
        stats.records_filtered,
    )
    return 0 if stats.saved or stats.duplicates else 1


def _run_ingest(args: argparse.Namespace) -> int:
    import psycopg

    from ingestion.yargitay.store import ingest_decisions

    database_url = _resolve_database_url(args.database_url)
    archive = DecisionArchive(args.archive_dir)

    if len(archive) == 0:
        logger.warning("Arşiv boş: %s", archive.root)
        return 1

    with psycopg.connect(database_url) as connection:
        summary = ingest_decisions(
            connection,
            archive.iter_decisions(),
            max_chunk_chars=args.max_chunk_chars,
        )

    logger.info(
        "Aktarım bitti | yeni=%s | güncellenen=%s | değişmeyen=%s | toplam=%s",
        summary.created,
        summary.updated,
        summary.unchanged,
        summary.total,
    )
    return 0


def _run_embed(args: argparse.Namespace) -> int:
    import psycopg

    from api.ai.embeddings import EmbeddingProviderError, create_embedding_provider
    from ingestion.embeddings import embed_legal_chunks

    load_dotenv()
    file_values = dotenv_values(".env")
    api_key = (
        os.getenv("EMBEDDING_API_KEY")
        or file_values.get("EMBEDDING_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or file_values.get("GEMINI_API_KEY")
    )
    try:
        provider = create_embedding_provider(
            provider_name=args.provider,
            api_key=api_key,
            model=args.model,
            dimensions=args.dimensions,
        )
    except EmbeddingProviderError as exc:
        logger.error("Embedding başlatılamadı: %s", exc)
        return 2

    database_url = _resolve_database_url(args.database_url)
    with psycopg.connect(database_url) as connection:
        summary = embed_legal_chunks(
            connection,
            provider,
            limit=args.limit,
            batch_size=args.batch_size,
        )

    logger.info(
        "Embedding bitti | yazılan=%s | kalan=%s | model=%s",
        summary.embedded,
        summary.remaining,
        provider.model,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ingestion",
        description="Yargıtay kararlarını topla ve veritabanına aktar.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Ayrıntılı log")

    subparsers = parser.add_subparsers(dest="command", required=True)

    scrape = subparsers.add_parser("scrape", help="Portalı tara ve JSON arşivine yaz")
    scrape.add_argument("--keyword", default="", help="Arama kelimesi")
    scrape.add_argument("--chamber", default="", help="Daire adı, ör. '9. Hukuk Dairesi'")
    scrape.add_argument("--max-decisions", type=int, default=50, help="Hedef karar sayısı")
    scrape.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    scrape.add_argument("--delay", type=float, default=1.5, help="İstekler arası bekleme (sn)")
    scrape.add_argument("--page-size", type=int, default=20, help="Portal sayfa boyutu")
    scrape.add_argument("--timeout", type=float, default=30, help="HTTP zaman aşımı (sn)")
    scrape.add_argument("--max-retries", type=int, default=3, help="Geçici HTTP hatası deneme sayısı")
    scrape.add_argument(
        "--refresh-existing",
        action="store_true",
        help="Arşivdeki karar metinlerini portaldan yeniden kontrol et",
    )
    scrape.set_defaults(handler=_run_scrape)

    ingest = subparsers.add_parser("ingest", help="JSON arşivini veritabanına aktar")
    ingest.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    ingest.add_argument("--database-url", default=None, help="Varsayılan: DATABASE_ADMIN_URL")
    ingest.add_argument("--max-chunk-chars", type=int, default=DEFAULT_MAX_CHARS)
    ingest.set_defaults(handler=_run_ingest)

    embed = subparsers.add_parser(
        "embed", help="Veritabanındaki hukuk parçaları için embedding üret"
    )
    embed.add_argument("--database-url", default=None, help="Varsayılan: DATABASE_ADMIN_URL")
    embed.add_argument("--provider", default=os.getenv("EMBEDDING_PROVIDER", "gemini"))
    embed.add_argument("--model", default=os.getenv("EMBEDDING_MODEL", "gemini-embedding-2"))
    embed.add_argument("--dimensions", type=int, default=int(os.getenv("EMBEDDING_DIMENSIONS", "768")))
    embed.add_argument("--limit", type=int, default=500)
    embed.add_argument("--batch-size", type=int, default=10)
    embed.set_defaults(handler=_run_embed)

    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
