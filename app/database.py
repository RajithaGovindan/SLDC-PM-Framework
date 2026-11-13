"""Database engine/session with automatic SQLite fallback."""
from __future__ import annotations

import logging
from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

log = logging.getLogger("sdlc.db")


class Base(DeclarativeBase):
    pass


def _sqlite_engine(url: str) -> Engine:
    eng = create_engine(url, connect_args={"check_same_thread": False}, future=True)

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _):  # enforce FK cascades in SQLite
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return eng


def _cloudsql_engine(settings) -> Engine:
    """PostgreSQL on Cloud SQL through the connector, signed in with the service account (no password)."""
    from google.cloud.sql.connector import Connector, IPTypes

    connector = Connector(refresh_strategy="lazy")

    def getconn():
        return connector.connect(settings.cloudsql_instance, "pg8000", user=settings.db_iam_user,
                                 db=settings.db_name, enable_iam_auth=True, ip_type=IPTypes.PUBLIC)

    return create_engine("postgresql+pg8000://", creator=getconn, pool_size=settings.db_pool_size, max_overflow=1,
                         pool_pre_ping=True, pool_recycle=1800, future=True)


def build_engine() -> tuple[Engine, str]:
    """Return (engine, backend_label). Falls back to SQLite if DATABASE_URL is empty or unreachable, unless
    db_fallback_to_sqlite is off (the cloud), where a throwaway SQLite file would silently lose data."""
    settings = get_settings()
    if settings.cloudsql_instance:
        eng = _cloudsql_engine(settings)
        with eng.connect() as conn:  # fail at startup, not on the first request
            conn.execute(text("SELECT 1"))
        return eng, f"postgresql (Cloud SQL {settings.db_name})"
    url = settings.database_url.strip()
    if url and not url.startswith("sqlite"):
        try:
            eng = create_engine(url, pool_pre_ping=True, future=True)
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            return eng, eng.dialect.name
        except Exception as exc:  # noqa: BLE001 - any connection failure triggers fallback
            if not settings.db_fallback_to_sqlite:
                raise
            log.warning("DATABASE_URL unreachable (%s). Falling back to SQLite at %s", exc, settings.sqlite_path)
    elif url.startswith("sqlite"):
        return _sqlite_engine(url), "sqlite"
    if not settings.db_fallback_to_sqlite:
        raise RuntimeError("No database configured (CLOUDSQL_INSTANCE or DATABASE_URL) and SQLite fallback is off.")
    return _sqlite_engine(settings.sqlite_url), "sqlite (fallback)"


engine, DB_BACKEND = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401 - register models

    Base.metadata.create_all(bind=engine)
