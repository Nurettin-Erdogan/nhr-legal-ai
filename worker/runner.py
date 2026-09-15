"""NHR Legal Data Collector CLI.

python -m worker.runner run --source yargitay
python -m worker.runner daemon
python -m worker.runner status
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
from datetime import datetime
from threading import Event

import psycopg
from dotenv import load_dotenv

from worker import ACTIVE_SOURCES
from worker.config import get_worker_settings
from worker.jobs import run_sync
from worker.models import SyncRequest
from worker.monitoring import format_status
from worker.scheduler import run_daemon

STOP = Event()


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s run_id=%(run_id)s source=%(source)s %(message)s",
    )
    logging.getLogger().handlers[0].formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )


def _handle_stop(signum: int, _frame: object) -> None:
    logging.getLogger("worker").warning("shutdown signal=%s", signum)
    STOP.set()


def _database_url(explicit: str | None) -> str:
    load_dotenv()
    url = explicit or os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL tanımlı değil")
    return url


def _parse_date(value: str | None):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _should_stop() -> bool:
    return STOP.is_set()


def _cmd_run(args: argparse.Namespace) -> int:
    sources = list(ACTIVE_SOURCES) if args.source == "all" else [args.source]
    results = []
    with psycopg.connect(_database_url(args.database_url), autocommit=True) as connection:
        for source in sources:
            if _should_stop():
                break
            request = SyncRequest(
                source=source,
                date_from=_parse_date(args.date_from),
                date_to=_parse_date(args.date_to),
                dry_run=args.dry_run,
                resume=not args.no_resume,
                max_records=args.max_records,
                keyword=args.keyword or "",
                chamber=args.chamber or "",
                law_no=args.law_no or "",
            )
            result = run_sync(connection, request, should_stop=_should_stop)
            results.append(result)
            logging.getLogger("worker").info(
                "sync finished source=%s status=%s run_id=%s",
                source,
                result.get("status"),
                result.get("run_id"),
            )
    print(json.dumps(results, default=str, ensure_ascii=False, indent=2))
    if any(item.get("status") in {"failed", "captcha_required"} for item in results):
        return 2
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    with psycopg.connect(_database_url(args.database_url), autocommit=True) as connection:
        print(format_status(connection))
    return 0


def _cmd_daemon(args: argparse.Namespace) -> int:
    get_worker_settings.cache_clear()
    with psycopg.connect(_database_url(args.database_url), autocommit=True) as connection:
        run_daemon(connection, should_stop=_should_stop, poll_seconds=args.poll_seconds)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m worker.runner")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--database-url", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Tek seferlik kaynak senkronu")
    run.add_argument("--source", required=True, choices=("yargitay", "mevzuat", "all", "danistay", "aym", "resmi_gazete"))
    run.add_argument("--date-from", default=None)
    run.add_argument("--date-to", default=None)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--no-resume", action="store_true")
    run.add_argument("--max-records", type=int, default=None)
    run.add_argument("--keyword", default="")
    run.add_argument("--chamber", default="")
    run.add_argument("--law-no", default="")
    run.set_defaults(handler=_cmd_run)

    status = sub.add_parser("status", help="Checkpoint ve son run özeti")
    status.set_defaults(handler=_cmd_status)

    daemon = sub.add_parser("daemon", help="Periyodik sync döngüsü")
    daemon.add_argument("--poll-seconds", type=int, default=None)
    daemon.set_defaults(handler=_cmd_daemon)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    signal.signal(signal.SIGINT, _handle_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_stop)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
