import threading
from pathlib import Path

from sqlalchemy import inspect

from app.core.config import Settings, get_settings
from app.db.session import init_database, make_engine, make_session_factory, run_alembic_upgrade
from app.services.inventory import InventoryService


def test_alembic_upgrade_matches_models_and_seeds_no_parts(tmp_path, monkeypatch):
    database = tmp_path / "migrated.db"
    monkeypatch.setenv("INVENTORY_DATABASE_PATH", str(database))
    monkeypatch.setenv("INVENTORY_ENVIRONMENT", "test")
    get_settings.cache_clear()
    settings = Settings(environment="test", database_path=database, frontend_dist=tmp_path / "none")
    run_alembic_upgrade(settings)
    engine = make_engine(database, immediate=False)
    names = set(inspect(engine).get_table_names())
    assert {
        "categories",
        "parts",
        "slots",
        "slot_inventory",
        "stock_transactions",
        "audit_events",
        "app_settings",
        "alembic_version",
    } <= names
    factory = make_session_factory(engine)
    with factory() as session:
        service = InventoryService(session, source="migration")
        assert len(service.list_categories()) == 9
        views, total = service.list_part_views(limit=10, offset=0)
        assert total == 0
        assert views == []
    created = tmp_path / "created.db"
    init_database(
        Settings(environment="test", database_path=created, frontend_dist=tmp_path / "none"),
        migrate=False,
    )
    created_engine = make_engine(created, immediate=False)
    migrated_columns = {
        table: {column["name"] for column in inspect(engine).get_columns(table)}
        for table in names
        if table != "alembic_version"
    }
    created_names = set(inspect(created_engine).get_table_names())
    for table, columns in migrated_columns.items():
        assert table in created_names
        assert columns == {column["name"] for column in inspect(created_engine).get_columns(table)}
    engine.dispose()
    created_engine.dispose()


def test_concurrent_removals_cannot_go_negative(tmp_path):
    database = tmp_path / "concurrent.db"
    settings = Settings(environment="test", database_path=database, frontend_dist=tmp_path / "none")
    init_database(settings, migrate=False)
    engine = make_engine(database)
    factory = make_session_factory(engine)
    session = factory()
    service = InventoryService(session, source="api")
    service.create_slot(slot_number=110)
    part = service.create_part(
        {
            "name": "Shared screw",
            "sku": "SHARED",
            "initial_quantity": 10,
            "allocations": [{"slot_number": 110, "quantity": 10}],
        }
    )
    session.commit()
    session.close()

    barrier = threading.Barrier(2)
    results: list[str] = []

    def worker() -> None:
        local = factory()
        local_service = InventoryService(local, source="api")
        try:
            barrier.wait(timeout=5)
            local_service.remove_stock(part_id=part["id"], slot_number=110, quantity=8)
            local.commit()
            results.append("ok")
        except Exception as exc:
            local.rollback()
            results.append(getattr(exc, "code", type(exc).__name__))
        finally:
            local.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    check = factory()
    remaining = InventoryService(check, source="api").part_view(part["id"])["current_quantity"]
    check.close()
    engine.dispose()
    assert results.count("ok") == 1
    assert "negative_stock" in results
    assert remaining == 2
    assert Path(database).exists()
