"""SQLite group-write repair. Umask cannot add the bit SQLite never requests."""

from __future__ import annotations

import os
import sqlite3
import stat
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.core.config import Settings, get_settings
from app.db.permissions import DB_DIR_MODE, DB_FILE_MODE, ensure_database_permissions
from app.db.session import apply_sqlite_pragmas, make_engine, run_alembic_upgrade
from app.maintenance import backup_database, restore_database


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_engine_makes_wal_group_writable_under_private_umask(tmp_path):
    database = tmp_path / "inventory.db"
    previous = os.umask(0o077)
    engine = make_engine(database)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("CREATE TABLE marker (n INTEGER)")
            connection.exec_driver_sql("INSERT INTO marker VALUES (42)")
            connection.commit()
            assert connection.exec_driver_sql("SELECT n FROM marker").scalar() == 42
            wal = Path(f"{database}-wal")
            shm = Path(f"{database}-shm")
            assert wal.is_file()
            assert shm.is_file()
            assert _mode(database) == DB_FILE_MODE
            assert _mode(wal) == DB_FILE_MODE
            assert _mode(shm) == DB_FILE_MODE
        assert _mode(tmp_path) == DB_DIR_MODE
        assert _mode(database) == DB_FILE_MODE
        reread = sqlite3.connect(database)
        try:
            assert reread.execute("SELECT n FROM marker").fetchone()[0] == 42
        finally:
            reread.close()
    finally:
        engine.dispose()
        os.umask(previous)


def test_existing_private_and_world_modes_become_group_writable(tmp_path):
    database = tmp_path / "inventory.db"
    previous = os.umask(0o077)
    try:
        raw = sqlite3.connect(database)
        raw.execute("CREATE TABLE marker (n INTEGER)")
        raw.execute("INSERT INTO marker VALUES (42)")
        raw.commit()
        raw.close()
        assert _mode(database) == 0o600
        database.chmod(0o666)
        engine = make_engine(database)
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT n FROM marker").scalar() == 42
            wal = Path(f"{database}-wal")
            assert _mode(database) == DB_FILE_MODE
            assert _mode(wal) == DB_FILE_MODE
            assert _mode(database) & 0o007 == 0
            assert _mode(wal) & 0o007 == 0
        engine.dispose()
    finally:
        os.umask(previous)


def test_memory_database_and_empty_path_do_not_raise():
    engine = create_engine("sqlite:///:memory:")
    apply_sqlite_pragmas(engine, immediate=True)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT 1").scalar() == 1
    engine.dispose()
    ensure_database_permissions(":memory:")
    ensure_database_permissions("")
    ensure_database_permissions(None)


def test_chmod_failure_keeps_bytes_and_rejects_world_access(tmp_path, monkeypatch):
    database = tmp_path / "inventory.db"
    database.write_bytes(b"keep")
    tmp_path.chmod(DB_DIR_MODE)
    database.chmod(0o600)
    real_chmod = os.chmod

    def deny(*_args, **_kwargs):
        raise OSError("denied")

    monkeypatch.setattr(os, "chmod", deny)
    with pytest.raises(PermissionError, match="0660"):
        ensure_database_permissions(database)
    assert database.read_bytes() == b"keep"

    real_chmod(database, 0o670)
    ensure_database_permissions(database)
    assert database.read_bytes() == b"keep"

    real_chmod(database, 0o664)
    with pytest.raises(PermissionError, match="0660"):
        ensure_database_permissions(database)
    assert database.read_bytes() == b"keep"


def test_other_owners_directory_is_left_alone(tmp_path, monkeypatch):
    database = tmp_path / "inventory.db"
    database.write_bytes(b"keep")
    tmp_path.chmod(0o755)
    real_uid = os.geteuid()
    monkeypatch.setattr("app.db.permissions.os.geteuid", lambda: real_uid + 1)
    ensure_database_permissions(database)
    assert _mode(tmp_path) == 0o755
    assert _mode(database) == DB_FILE_MODE
    assert database.read_bytes() == b"keep"


def test_alembic_upgrade_repairs_private_umask(tmp_path, monkeypatch):
    database = tmp_path / "migrated.db"
    monkeypatch.setenv("INVENTORY_DATABASE_PATH", str(database))
    monkeypatch.setenv("INVENTORY_ENVIRONMENT", "test")
    get_settings.cache_clear()
    previous = os.umask(0o077)
    try:
        run_alembic_upgrade(
            Settings(environment="test", database_path=database, frontend_dist=tmp_path / "none")
        )
        assert database.is_file()
        assert _mode(database) == DB_FILE_MODE
        connection = sqlite3.connect(database)
        try:
            count = connection.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        finally:
            connection.close()
        assert count == 9
    finally:
        os.umask(previous)


def test_backup_and_restore_preserve_rows_and_group_mode(tmp_path):
    source_dir = tmp_path / "live"
    source_dir.mkdir()
    source = source_dir / "inventory.db"
    previous = os.umask(0o077)
    try:
        raw = sqlite3.connect(source)
        raw.execute("CREATE TABLE marker (n INTEGER)")
        raw.execute("INSERT INTO marker VALUES (42)")
        raw.commit()
        raw.close()
        assert _mode(source) == 0o600
        dest = tmp_path / "backups" / "copy.db"
        backup_database(source, dest)
        metadata = dest.with_suffix(".db.json")
        assert _mode(dest) == DB_FILE_MODE
        assert _mode(metadata) == DB_FILE_MODE
        assert _mode(source) == DB_FILE_MODE
        assert _mode(dest) & 0o007 == 0
        raw = sqlite3.connect(source)
        raw.execute("UPDATE marker SET n = 7")
        raw.commit()
        raw.close()
        restored = restore_database(dest, source)
        raw = sqlite3.connect(source)
        try:
            assert raw.execute("SELECT n FROM marker").fetchone()[0] == 42
        finally:
            raw.close()
        safety = Path(restored["safety_copy"])
        assert safety.is_file()
        assert _mode(source) == DB_FILE_MODE
        assert _mode(safety) == DB_FILE_MODE
        assert safety.read_bytes()
    finally:
        os.umask(previous)
