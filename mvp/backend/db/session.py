"""Engine and session factory. SQLite lives at `data/db.sqlite` by default."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from core.paths import DEFAULT_DB_PATH

from .models import Base


def db_path() -> Path:
    return Path(os.environ.get("PPC_DB_PATH", str(DEFAULT_DB_PATH)))


def make_engine(path: Path | None = None):
    p = Path(path) if path else db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(
        f"sqlite:///{p}",
        future=True,
        connect_args={"timeout": 30, "check_same_thread": False},
    )

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        # WAL lets the API read a comparison's progress while the worker thread
        # is still writing its stages.
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return eng


_engine = None
_SessionLocal = None


def engine():
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def SessionLocal() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=engine(), expire_on_commit=False, future=True)
    return _SessionLocal()


def init_db() -> None:
    Base.metadata.create_all(engine())


def reset_engine() -> None:
    """Drop the cached engine — used by tests that repoint `PPC_DB_PATH`."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
