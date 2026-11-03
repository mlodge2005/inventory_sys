"""Open the same database the API uses."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.core.errors import InventoryError
from app.db.session import make_engine, make_session_factory
from app.services.inventory import InventoryService


def _database_permission_error() -> InventoryError:
    return InventoryError(
        "forbidden",
        "Cannot open the inventory database. Your account must be in the cyberdeck "
        "group; log out and back in after that membership changes. Database, WAL, "
        "and shared-memory files must be mode 0660. Restart cyberdeck-inventory.service, "
        "or re-run the installer, so the file owner can repair them. Do not run "
        "the inventory command as root.",
        403,
    )


@contextmanager
def open_service() -> Iterator[InventoryService]:
    settings = get_settings()
    path = settings.resolved_database_path
    try:
        exists = path.exists()
    except PermissionError as exc:
        raise _database_permission_error() from exc
    if not exists:
        raise InventoryError(
            "not_found",
            f"Database not found at {path}. Install the service or set INVENTORY_DATABASE_PATH.",
            404,
        )
    engine = make_engine(path)
    factory = make_session_factory(engine)
    session = factory()
    service = InventoryService(session, source="cli")
    try:
        yield service
        session.commit()
    except PermissionError as exc:
        session.rollback()
        raise _database_permission_error() from exc
    except OperationalError as exc:
        session.rollback()
        message = str(exc).lower()
        if "readonly" in message or "unable to open" in message or "permission" in message:
            raise _database_permission_error() from exc
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()
