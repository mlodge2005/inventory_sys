from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.db.session import init_database, make_engine, make_session_factory
from app.main import create_app


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    database = tmp_path / "inventory.db"
    monkeypatch.setenv("INVENTORY_DATABASE_PATH", str(database))
    monkeypatch.setenv("INVENTORY_ENVIRONMENT", "test")
    monkeypatch.delenv("INVENTORY_PUBLIC_URL", raising=False)
    get_settings.cache_clear()
    configured = Settings(
        environment="test",
        database_path=database,
        frontend_dist=tmp_path / "missing-frontend",
        host="127.0.0.1",
        port=8765,
        allowed_origins="",
    )
    init_database(configured, migrate=False)
    return configured


@pytest.fixture
def session_factory(settings):
    engine = make_engine(settings.resolved_database_path)
    factory = make_session_factory(engine)
    yield factory
    engine.dispose()


@pytest.fixture
def client(settings) -> TestClient:
    application = create_app(settings)
    with TestClient(application) as test_client:
        test_client.headers.update(
            {
                "X-Cyberdeck-Request": "1",
                "X-Cyberdeck-Client": "api",
            }
        )
        yield test_client


@pytest.fixture
def bare_client(settings) -> TestClient:
    application = create_app(settings)
    with TestClient(application) as test_client:
        yield test_client
