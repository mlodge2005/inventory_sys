"""Backup, restore, and integrity helpers built on SQLite's backup API.

Copying only the main database file while WAL mode is active can drop committed
pages that still live in the WAL. These helpers always use the backup API.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from app import __version__
from app.core.config import get_settings


def backup_database(source: Path, dest: Path) -> dict:
    source = source.expanduser().resolve()
    dest = dest.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Database does not exist: {source}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise FileExistsError(f"Backup destination already exists: {dest}")
    _sqlite_backup(source, dest)
    integrity = integrity_check(dest)
    if integrity != "ok":
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"Backup failed integrity check: {integrity}")
    digest = sha256_file(dest)
    metadata = {
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "app_version": __version__,
        "schema_revision": schema_revision(dest),
        "source_database": str(source),
        "file_size": dest.stat().st_size,
        "sha256": digest,
        "integrity": integrity,
    }
    dest.with_suffix(dest.suffix + ".json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def restore_database(backup: Path, dest: Path) -> dict:
    """Replace ``dest`` with a consistent copy of ``backup``.

    The caller must stop writers first. The current database, WAL, and SHM are
    moved aside and kept. They are not deleted.
    """

    backup = backup.expanduser().resolve()
    dest = dest.expanduser().resolve()
    if not backup.exists():
        raise FileNotFoundError(f"Backup does not exist: {backup}")
    meta_path = backup.with_suffix(backup.suffix + ".json")
    if meta_path.exists():
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        actual = sha256_file(backup)
        if metadata.get("sha256") and metadata["sha256"] != actual:
            raise RuntimeError("Backup checksum does not match its metadata.")
    else:
        metadata = {}
    staged = dest.with_name(dest.name + ".restore-staging")
    if staged.exists():
        staged.unlink()
    _sqlite_backup(backup, staged)
    if integrity_check(staged) != "ok":
        staged.unlink(missing_ok=True)
        raise RuntimeError("Backup file failed integrity check and was not restored.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safety = None
    if dest.exists():
        safety = dest.with_name(f"{dest.stem}.before-restore-{stamp}{dest.suffix}")
        # The safety file is a standalone snapshot. Do not leave a WAL beside it
        # or SQLite will try to replay those pages onto the snapshot.
        _sqlite_backup(dest, safety)
        dest.unlink()
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(dest) + suffix)
            if sidecar.exists():
                sidecar.replace(sidecar.with_name(sidecar.name + f".aside-{stamp}"))
    staged.replace(dest)
    if integrity_check(dest) != "ok":
        raise RuntimeError("Restored database failed integrity check.")
    return {
        "database": str(dest),
        "safety_copy": str(safety) if safety else None,
        "schema_revision": schema_revision(dest),
        "backup_metadata": metadata,
        "integrity": "ok",
    }


def integrity_check(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA busy_timeout=30000")
        row = connection.execute("PRAGMA integrity_check").fetchone()
        return str(row[0]) if row else "missing"
    finally:
        connection.close()


def schema_revision(path: Path) -> str | None:
    connection = sqlite3.connect(path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "alembic_version" not in tables:
            return None
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        return str(row[0]) if row else None
    finally:
        connection.close()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_backup(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source)
    try:
        src.execute("PRAGMA busy_timeout=30000")
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cyberdeck Inventory database maintenance")
    sub = parser.add_subparsers(dest="command", required=True)

    backup = sub.add_parser("backup")
    backup.add_argument("--database", type=Path)
    backup.add_argument("--dest", type=Path)

    restore = sub.add_parser("restore")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--database", type=Path)

    check = sub.add_parser("integrity")
    check.add_argument("--database", type=Path)

    revision = sub.add_parser("revision")
    revision.add_argument("--database", type=Path)

    args = parser.parse_args(argv)
    settings = get_settings()
    database = args.database or settings.resolved_database_path
    try:
        if args.command == "backup":
            dest = args.dest
            if dest is None:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                dest = settings.resolved_backup_dir / f"inventory-{stamp}.db"
            metadata = backup_database(database, dest)
            print(json.dumps(metadata, indent=2))
        elif args.command == "restore":
            result = restore_database(args.backup, database)
            print(json.dumps(result, indent=2))
        elif args.command == "integrity":
            result = integrity_check(database)
            print(result)
            return 0 if result == "ok" else 1
        elif args.command == "revision":
            print(schema_revision(database) or "")
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
