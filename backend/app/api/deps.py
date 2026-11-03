"""Request-scoped inventory service. The session commits when the request succeeds."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.constants import SOURCES
from app.services.inventory import InventoryService


def get_service(request: Request) -> Iterator[InventoryService]:
    factory = request.app.state.session_factory
    raw = request.headers.get("x-cyberdeck-client", "api")
    source = raw if raw in SOURCES else "api"
    session: Session = factory()
    service = InventoryService(session, source=source)
    try:
        yield service
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
