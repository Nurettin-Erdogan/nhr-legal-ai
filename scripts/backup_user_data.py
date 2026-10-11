"""Kullanıcı verisi yedeği: avukatların kendi verileri (hesap, müvekkil, dava, belge, sohbet, denetim kaydı) + yüklenen dosyalar.

Hukuk korpusu (legal_* ve toplama tabloları, ~210 GB) YEDEKLENMEZ: toplayıcılar yeniden üretir; kullanıcı verisi ise yeniden üretilemez.
Tablolar iki listeden biridir (`USER_TABLES`, `CORPUS_TABLES`). Listede olmayan YENİ bir tablo uyarıyla birlikte yedeğe dahil edilir
(fazla yedeklemek eksik yedeklemekten iyidir); sınıflandırması sonradan yapılır.

Çıktı klasörü: <dest>/jurisai-YYYYMMDD-HHMMSS/ { user-data.dump, uploads.zip, manifest.json }. `--verify` yedeği geçici bir veritabanına geri
yükleyip satır sayılarını karşılaştırır ve zip'i sınar: **geri yüklenemeyen yedek yedek değildir.**

KVKK: yedek müvekkil verisi içerir; şifreli/erişimi kısıtlı bir diskte tutun, kopyasını başka bir fiziksel yere alın.

    .venv\\Scripts\\python.exe scripts\\backup_user_data.py --dest D:\\yedekler --verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

USER_TABLES = (
    "users", "roles", "user_roles", "auth_google_identities", "activity_logs",
    "clients", "projects", "project_members", "documents", "document_chunks", "conversations", "messages", "citations", "saved_legal_sources",
    "office_ai_outputs", "office_basvurular", "office_calendar_events", "office_call_settings", "office_calls", "office_case_documents",
    "office_cases", "office_clients", "office_feedback", "office_legal_documents", "office_project_notes", "office_projects", "office_reminders", "office_uyap_audit_runs",
    "office_risk_analyses", "office_tasks", "office_uyap_ingest_tokens", "office_uyap_sync_runs",
)
CORPUS_TABLES = (
    "bulk_seed_fulltext_queue", "bulk_seed_inventory", "court_decision_details", "legal_chunks", "legal_source_quarantine",
    "legal_source_revisions", "legal_sources", "legislation_details", "legislation_identities", "seed_verification_queue",
    "source_coverage_windows", "source_sync_checkpoints", "source_sync_runs",
)
_BACKUP_DIR = re.compile(r"^jurisai-\d{8}-\d{6}$")
_SAFE_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def classify_tables(all_tables: list[str]) -> tuple[list[str], list[str], list[str]]:
    """(yedeklenecek, korpus, sınıflandırılmamış). Sınıflandırılmamış tablolar yedeğe DAHİL edilir."""
    user = [name for name in all_tables if name in USER_TABLES]
    corpus = [name for name in all_tables if name in CORPUS_TABLES]
    unknown = [name for name in all_tables if name not in USER_TABLES and name not in CORPUS_TABLES]
    return sorted(user + unknown), corpus, unknown


def rotation_victims(names: list[str], keep: int) -> list[str]:
    """En yeni `keep` yedek kalır; yalnızca bu betiğin adlandırdığı klasörler silinebilir."""
    backups = sorted(name for name in names if _BACKUP_DIR.match(name))
    return backups[: max(0, len(backups) - max(keep, 1))]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def zip_directory(source: Path, target: Path) -> int:
    """`source` altındaki dosyaları zip'ler; dosya sayısını döndürür. Sembolik bağlar izlenmez."""
    count = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file() and not path.is_symlink():
                archive.write(path, path.relative_to(source).as_posix())
                count += 1
    return count


def load_env() -> dict[str, str]:
    env = dict(os.environ)
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                env.setdefault(key.strip(), value.strip().strip('"'))
    return env


def docker(container: str, *args: str, stdin=None, stdout=None, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "exec", *(["-i"] if stdin else []), container, *args], stdin=stdin, stdout=stdout, stderr=subprocess.PIPE, check=check)


def psql_scalar(container: str, user: str, database: str, sql: str) -> str:
    result = subprocess.run(
        ["docker", "exec", container, "psql", "-U", user, "-d", database, "-At", "-c", sql], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def table_counts(container: str, user: str, database: str, tables: list[str]) -> dict[str, int]:
    return {name: int(psql_scalar(container, user, database, f'SELECT count(*) FROM "{name}"')) for name in tables}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dest", type=Path, default=Path(os.environ.get("BACKUP_DIR", ROOT / "data" / "backups" / "user")))
    parser.add_argument("--keep", type=int, default=14, help="saklanacak yedek sayısı")
    parser.add_argument("--verify", action="store_true", help="yedeği geçici veritabanına geri yükleyip doğrula")
    parser.add_argument("--no-uploads", action="store_true", help="yüklenen dosyaları yedekleme")
    args = parser.parse_args()

    env = load_env()
    container = env.get("BACKUP_DB_CONTAINER", "nhr-legal-ai-db")
    user, database = env.get("POSTGRES_USER", "nhr_app"), env.get("POSTGRES_DB", "nhr_legal_ai")
    uploads = Path(env.get("DOCUMENT_STORAGE_DIR", "uploads"))
    uploads = uploads if uploads.is_absolute() else ROOT / uploads

    tables_present = psql_scalar(container, user, database, "SELECT string_agg(tablename, ',') FROM pg_tables WHERE schemaname = 'public'").split(",")
    tables, corpus, unknown = classify_tables(sorted(tables_present))
    if unknown:
        print(f"UYARI: sınıflandırılmamış tablolar yedeğe dahil edildi: {', '.join(unknown)} (scripts/backup_user_data.py listelerine ekleyin)", flush=True)
    if not all(_SAFE_IDENT.match(name) for name in tables):
        print("HATA: beklenmeyen tablo adı", file=sys.stderr)
        return 2

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = args.dest / f"jurisai-{stamp}"
    target.mkdir(parents=True, exist_ok=False)
    dump = target / "user-data.dump"
    counts = table_counts(container, user, database, tables)
    with dump.open("wb") as handle:
        docker(container, "pg_dump", "-U", user, "-d", database, "-Fc", "-Z", "6", *[arg for name in tables for arg in ("-t", f"public.{name}")], stdout=handle)
    manifest: dict = {
        "created_at": datetime.now().astimezone().isoformat(),
        "database": database,
        "tables": counts,
        "corpus_tables_skipped": corpus,
        "unclassified_tables_included": unknown,
        "dump": {"file": dump.name, "bytes": dump.stat().st_size, "sha256": sha256(dump)},
    }
    if not args.no_uploads and uploads.is_dir():
        archive = target / "uploads.zip"
        files = zip_directory(uploads, archive)
        manifest["uploads"] = {"file": archive.name, "files": files, "bytes": archive.stat().st_size, "sha256": sha256(archive)}
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Yedek alındı: {target} ({dump.stat().st_size / 1e6:.1f} MB veritabanı, {sum(counts.values())} satır)", flush=True)

    ok = True
    if args.verify:
        ok = verify(container, user, database, target, manifest)
    for victim in rotation_victims([p.name for p in args.dest.iterdir() if p.is_dir()], args.keep):
        shutil.rmtree(args.dest / victim)
        print(f"Eski yedek silindi: {victim}", flush=True)
    return 0 if ok else 1


def verify(container: str, user: str, database: str, target: Path, manifest: dict) -> bool:
    """Yedeği geçici veritabanına yükler: dosya özetleri, satır sayıları ve zip bütünlüğü kontrol edilir."""
    scratch = "jurisai_restore_check"
    problems: list[str] = []
    if sha256(target / "user-data.dump") != manifest["dump"]["sha256"]:
        problems.append("dump özeti uyuşmuyor")
    if "uploads" in manifest:
        archive = target / "uploads.zip"
        if sha256(archive) != manifest["uploads"]["sha256"]:
            problems.append("uploads.zip özeti uyuşmuyor")
        with zipfile.ZipFile(archive) as handle:
            if handle.testzip() is not None:
                problems.append("uploads.zip bozuk")
            if len(handle.namelist()) != manifest["uploads"]["files"]:
                problems.append("uploads.zip dosya sayısı uyuşmuyor")
    docker(container, "dropdb", "-U", user, "--if-exists", scratch)
    docker(container, "createdb", "-U", user, scratch)
    # Tablolar vektör sütunu içerir: eklenti şema yüklenmeden önce kurulmalı (kurulu eklentileri kaynaktan al).
    for extension in psql_scalar(container, user, database, "SELECT string_agg(extname, ',') FROM pg_extension WHERE extname <> 'plpgsql'").split(","):
        if extension:
            docker(container, "psql", "-U", user, "-d", scratch, "-c", f'CREATE EXTENSION IF NOT EXISTS "{extension}"')
    try:
        with (target / "user-data.dump").open("rb") as handle:
            # Şema + veri; dış anahtar kısıtları (post-data) korpus tablolarına bağlı olduğundan atlanır.
            restored = docker(container, "pg_restore", "-U", user, "-d", scratch, "--section=pre-data", "--section=data", "--no-owner", stdin=handle, check=False)
        if restored.returncode not in (0, 1):  # 1: yalnız uyarı (ör. eksik rol)
            problems.append(f"pg_restore başarısız (kod {restored.returncode}): {restored.stderr.decode('utf-8', 'replace')[:300]}")
        for name, expected in manifest["tables"].items():
            try:
                actual = int(psql_scalar(container, user, scratch, f'SELECT count(*) FROM "{name}"'))
            except subprocess.CalledProcessError:
                actual = None  # tablo geri yüklenemedi
            if actual != expected:
                problems.append(f"{name}: geri yüklenen {actual} ≠ yedeklenen {expected}")
    finally:
        docker(container, "dropdb", "-U", user, "--if-exists", scratch, check=False)
    if problems:
        print("DOĞRULAMA BAŞARISIZ:\n  " + "\n  ".join(problems), file=sys.stderr, flush=True)
        return False
    print(f"Doğrulandı: {len(manifest['tables'])} tablo geçici veritabanına geri yüklendi, satır sayıları eşit, zip sağlam.", flush=True)
    return True


if __name__ == "__main__":
    sys.exit(main())
