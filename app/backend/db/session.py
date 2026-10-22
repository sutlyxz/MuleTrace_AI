"""SQLAlchemy engine/session factory driven by DATABASE_URL."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.backend.db.config import get_database_url

_ENGINES: dict[str, Engine] = {}


def get_engine(url: str | None = None) -> Engine:
    """Return a cached Engine per URL (pool_pre_ping survives RDS failovers/idle drops)."""
    resolved = url or get_database_url()
    engine = _ENGINES.get(resolved)
    if engine is None:
        engine = create_engine(resolved, pool_pre_ping=True, pool_recycle=1800)
        _ENGINES[resolved] = engine
    return engine


def dispose_engines() -> None:
    """Close all pooled connections (used by tests and short-lived scripts)."""
    for engine in _ENGINES.values():
        engine.dispose()
    _ENGINES.clear()


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on any error."""
    session = Session(bind=engine or get_engine(), expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
