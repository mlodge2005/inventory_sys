"""SQLite engine configured for a single-board computer.

Writers use BEGIN IMMEDIATE so two stock mutations cannot both observe the
same quantity and drive it negative. Foreign keys, WAL, and a busy timeout
are set on every connection.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.seed import seed_reference_data


def apply_sqlite_pragmas(engine: Engine, *, immediate: bool) -> None:
    @event.listens_for(engine, "connect")
    def _connect(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        if immediate:
            # Let SQLAlchemy emit BEGIN via the begin hook below.
            dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=FULL")
        cursor.close()

    if immediate:

        @event.listens_for(engine, "begin")
        def _begin(connection) -> None:  # noqa: ANN001
            connection.exec_driver_sql("BEGIN IMMEDIATE")


def make_engine(path: Path, *, immediate: bool = True) -> Engine:
    url = "sqlite:///" + path.expanduser().resolve().as_posix()
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
    )
    apply_sqlite_pragmas(engine, immediate=immediate)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def init_database(settings: Settings, *, migrate: bool = False) -> None:
    """Create the database file, parent directory, and schema.

    ``migrate=True`` runs Alembic (the installer path). ``migrate=False``
    creates tables from the ORM metadata and seeds reference data. That path
    is for tests and local experiments. Production installs use Alembic.
    """

    path = settings.resolved_database_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if migrate:
        run_alembic_upgrade(settings)
        return
    engine = make_engine(path, immediate=True)
    # Import models so they register on the metadata.
    import app.models  # noqa: F401

    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        seed_reference_data(session)
        session.commit()
    engine.dispose()


def run_alembic_upgrade(settings: Settings) -> None:
    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.sqlalchemy_url)
    command.upgrade(cfg, "head")
