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

from dotenv import load_dotenv

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
    from ingestion.yargitay.scraper import ScraperConfig, YargitayScraper

    archive = DecisionArchive(args.archive_dir)
    config = ScraperConfig(
        headless=not args.headed,
        request_delay_seconds=args.delay,
    )
    scraper = YargitayScraper(archive, config=config, chamber=args.chamber)

    stats = asyncio.run(
        scraper.scrape(keyword=args.keyword, max_decisions=args.max_decisions)
    )

    logger.info(
        "Arşiv: %s | toplam kayıt: %s | bu çalıştırmada yeni: %s",
        archive.root,
        len(archive),
        stats.saved,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ingestion",
        description="Yargıtay kararlarını topla ve veritabanına aktar.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Ayrıntılı log")

    subparsers = parser.add_subparsers(dest="command", required=True)

    scrape = subparsers.add_parser("scrape", help="Portalı tara ve JSON arşivine yaz")
    scrape.add_argument("--keyword", default="", help="Arama kelimesi")
    scrape.add_argument("--chamber", default=None, help="Daire adı, ör. '9. Hukuk Dairesi'")
    scrape.add_argument("--max-decisions", type=int, default=50, help="Hedef karar sayısı")
    scrape.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    scrape.add_argument("--delay", type=float, default=1.5, help="İstekler arası bekleme (sn)")
    scrape.add_argument("--headed", action="store_true", help="Tarayıcıyı görünür çalıştır")
    scrape.set_defaults(handler=_run_scrape)

    ingest = subparsers.add_parser("ingest", help="JSON arşivini veritabanına aktar")
    ingest.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    ingest.add_argument("--database-url", default=None, help="Varsayılan: DATABASE_ADMIN_URL")
    ingest.add_argument("--max-chunk-chars", type=int, default=DEFAULT_MAX_CHARS)
    ingest.set_defaults(handler=_run_ingest)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
