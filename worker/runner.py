"""NHR Legal Data Collector CLI.

python -m worker.runner run --source yargitay
python -m worker.runner backfill --source all
python -m worker.runner daemon
python -m worker.runner status
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from threading import Event
from time import sleep

import psycopg
from dotenv import load_dotenv

from worker import ACTIVE_SOURCES, OPTIONAL_SOURCES, PLANNED_SOURCES
from worker.backfill import run_full_backfill
from worker.config import get_worker_settings
from worker.jobs import run_sync
from worker.lanes import CURRENT_LANE_SOURCES
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
    lane = args.lane
    if args.source == "all":
        sources = (
            [item for item in ACTIVE_SOURCES if item in CURRENT_LANE_SOURCES]
            if lane == "current"
            else list(ACTIVE_SOURCES)
        )
    else:
        sources = [args.source]
        if lane == "current" and args.source not in CURRENT_LANE_SOURCES:
            raise SystemExit(f"{args.source} current şeridine sahip değil")
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
                lane=lane,
            )
            result = run_sync(connection, request, should_stop=_should_stop)
            results.append(result)
            logging.getLogger("worker").info(
                "sync finished source=%s lane=%s status=%s run_id=%s",
                source,
                lane,
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


def _cmd_backfill(args: argparse.Namespace) -> int:
    get_worker_settings.cache_clear()
    sources = list(ACTIVE_SOURCES) if args.source == "all" else [args.source]
    if args.source == "all" and not args.serial:
        return _cmd_backfill_parallel(args, sources)
    with psycopg.connect(_database_url(args.database_url), autocommit=True) as connection:
        summary = run_full_backfill(
            connection,
            sources,
            should_stop=_should_stop,
            embed=not args.no_embed,
            then_incremental=not args.no_incremental,
        )
    return _print_backfill_summary(summary)


def _print_backfill_summary(summary: dict) -> int:
    printable = dict(summary)
    printable.pop("runs", None)
    printable["runs"] = [
        {
            "source": item.get("source"),
            "status": item.get("status"),
            "run_id": item.get("run_id"),
            "counters": item.get("counters"),
            "error": item.get("error"),
            "embedding": item.get("embedding"),
        }
        for item in summary.get("runs", [])
    ]
    print(json.dumps(printable, default=str, ensure_ascii=False, indent=2))
    if summary.get("blocked") or any(
        item.get("status") in {"failed", "captcha_required"} for item in summary.get("runs", [])
    ):
        return 2
    return 0


def _cmd_backfill_parallel(args: argparse.Namespace, sources: list[str]) -> int:
    logger = logging.getLogger("worker")
    extra: list[str] = []
    if args.verbose:
        extra.append("-v")
    if args.database_url:
        extra.extend(["--database-url", args.database_url])
    if args.no_embed:
        extra.append("--no-embed")
    log_dir = Path("data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    children: list[tuple[str, subprocess.Popen, object]] = []
    codes: dict[str, int] = {}
    try:
        for source in sources:
            log_path = log_dir / f"backfill-{source}.log"
            handle = log_path.open("a", encoding="utf-8")
            cmd = [
                sys.executable,
                "-m",
                "worker.runner",
                "backfill",
                "--source",
                source,
                "--no-incremental",
                *extra,
            ]
            proc = subprocess.Popen(
                cmd,
                stdout=handle,
                stderr=subprocess.STDOUT,
                env=env,
            )
            children.append((source, proc, handle))
            logger.info(
                "parallel backfill started source=%s pid=%s log=%s",
                source,
                proc.pid,
                log_path,
            )
        codes: dict[str, int] = {}
        while children:
            if _should_stop():
                for source, proc, _handle in children:
                    if proc.poll() is None:
                        logger.warning("stopping parallel backfill source=%s pid=%s", source, proc.pid)
                        proc.terminate()
                break
            still: list[tuple[str, subprocess.Popen, object]] = []
            for source, proc, handle in children:
                code = proc.poll()
                if code is None:
                    still.append((source, proc, handle))
                    continue
                handle.close()
                codes[source] = int(code)
                logger.info("parallel backfill finished source=%s code=%s", source, code)
            children = still
            if children:
                sleep(1)
        if children:
            for source, proc, handle in children:
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                handle.close()
                codes[source] = int(proc.returncode if proc.returncode is not None else 1)
    finally:
        for _source, proc, handle in children:
            if proc.poll() is None:
                proc.kill()
            try:
                handle.close()
            except Exception:  # noqa: BLE001
                pass
    if not args.no_incremental and not _should_stop():
        logger.info("parallel backfill children exited; switching to incremental daemon")
        with psycopg.connect(_database_url(args.database_url), autocommit=True) as connection:
            run_daemon(connection, should_stop=_should_stop)
    failed = [name for name, code in codes.items() if code not in {0, None}]
    print(
        json.dumps(
            {"status": "parallel", "codes": codes, "failed": failed},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 2 if failed or _should_stop() else 0


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
    run.add_argument(
        "--source",
        required=True,
        choices=(*ACTIVE_SOURCES, "all", *OPTIONAL_SOURCES, *PLANNED_SOURCES),
    )
    run.add_argument("--date-from", default=None)
    run.add_argument("--date-to", default=None)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--no-resume", action="store_true")
    run.add_argument("--max-records", type=int, default=None)
    run.add_argument("--keyword", default="")
    run.add_argument("--chamber", default="")
    run.add_argument("--law-no", default="")
    run.add_argument(
        "--lane",
        choices=("backfill", "current"),
        default="backfill",
        help="backfill: arşiv imlecinden devam; current: son ayları yeniden tara",
    )
    run.set_defaults(handler=_cmd_run)

    status = sub.add_parser("status", help="Checkpoint ve son run özeti")
    status.set_defaults(handler=_cmd_status)

    daemon = sub.add_parser("daemon", help="Periyodik sync döngüsü")
    daemon.add_argument("--poll-seconds", type=int, default=None)
    daemon.set_defaults(handler=_cmd_daemon)

    backfill = sub.add_parser(
        "backfill",
        help="Tarihsel korpusu checkpoint/resume ile doldur, bitince incremental daemon",
    )
    backfill.add_argument(
        "--source",
        default="all",
        choices=(*ACTIVE_SOURCES, "all"),
    )
    backfill.add_argument(
        "--no-embed",
        action="store_true",
        help="Tur sonunda yeni chunk'ları embed etme",
    )
    backfill.add_argument(
        "--no-incremental",
        action="store_true",
        help="Full backfill bitince daemon'a geçme",
    )
    backfill.add_argument(
        "--serial",
        action="store_true",
        help="Kaynakları tek süreçte sırayla çek (varsayılan: all için ayrı süreçler)",
    )
    backfill.set_defaults(handler=_cmd_backfill)
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
