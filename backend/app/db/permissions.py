"""Group access for the SQLite database without making it world-accessible.

SQLite creates the database, WAL, and shared-memory files with mode 0o644.
A process umask can only clear bits, so ``UMask=0007`` produces 0o640 and
``umask 0077`` produces 0o600. Group members can read 0o640 but cannot write
the WAL or shared-memory file, which is why ``inventory`` fails for a user
who is in the ``cyberdeck`` group. After SQLite creates or reopens those
files, this module sets mode 0o660 (owner and group read/write, no other
access). The setgid data directory supplies the ``cyberdeck`` group. Callers
that are not the file owner leave an already-correct mode alone and raise a
clear error when they cannot repair a private or world-accessible file.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

DB_FILE_MODE = 0o660
DB_DIR_MODE = 0o2770
_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
_OWNER_RW = stat.S_IRUSR | stat.S_IWUSR
_GROUP_RW = stat.S_IRGRP | stat.S_IWGRP

_REPAIR_HINT = (
    "Restart cyberdeck-inventory.service, or re-run the installer as root, "
    "so the file owner can repair permissions. Do not run the inventory command as root."
)


def ensure_sqlite_connection(dbapi_connection: object) -> None:
    """Set 0o660 on every database file this connection has open."""

    cursor = dbapi_connection.cursor()
    try:
        rows = list(cursor.execute("PRAGMA database_list"))
    finally:
        cursor.close()
    for row in rows:
        filename = row[2] if len(row) > 2 else None
        if filename:
            ensure_database_permissions(filename)


def ensure_database_permissions(path: Path | str | None) -> None:
    """Make one database and its SQLite sidecar files group-writable."""

    if path is None:
        return
    text = os.fspath(path)
    if not text or text == ":memory:":
        return
    database = Path(text)
    _ensure_directory(database.parent)
    for candidate in _database_files(database):
        if candidate.is_file():
            ensure_private_file(candidate)


def ensure_private_file(path: Path | str) -> None:
    """Set one regular file to owner/group read-write and no other access."""

    file_path = Path(path)
    try:
        current = stat.S_IMODE(file_path.stat().st_mode)
    except FileNotFoundError:
        return
    if current == DB_FILE_MODE:
        return
    try:
        os.chmod(file_path, DB_FILE_MODE)
    except FileNotFoundError:
        return
    except OSError as exc:
        try:
            refreshed = stat.S_IMODE(file_path.stat().st_mode)
        except OSError:
            refreshed = current
        if _group_writable_private(refreshed):
            return
        raise PermissionError(
            f"Could not set {file_path} to mode {DB_FILE_MODE:04o} "
            f"(current mode {refreshed:04o}). {_REPAIR_HINT}"
        ) from exc


def _database_files(path: Path) -> list[Path]:
    return [path, *[Path(f"{path}{suffix}") for suffix in _SIDECAR_SUFFIXES]]


def _ensure_directory(directory: Path) -> None:
    """Set the data directory to 0o2770 when this process owns it.

    A process that does not own the directory must not chmod it. That keeps a
    group member from changing ``/tmp`` or another parent it does not own.
    """

    if directory == Path(""):
        return
    try:
        info = directory.stat()
    except OSError:
        return
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        return
    if stat.S_IMODE(info.st_mode) == DB_DIR_MODE:
        return
    try:
        os.chmod(directory, DB_DIR_MODE)
    except OSError as exc:
        raise PermissionError(
            f"Could not set directory {directory} to mode {DB_DIR_MODE:04o}. {_REPAIR_HINT}"
        ) from exc


def _group_writable_private(mode: int) -> bool:
    return (
        (mode & _OWNER_RW) == _OWNER_RW
        and (mode & _GROUP_RW) == _GROUP_RW
        and (mode & stat.S_IRWXO) == 0
    )
