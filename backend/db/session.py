"""Engine + session factory. SQLite lives at data/db.sqlite by default."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "db.sqlite"


def db_path() -> Path:
    return Path(os.environ.get("PCM_DB_PATH", str(DEFAULT_DB_PATH)))


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
        # WAL lets the API read while a run's worker pool writes findings.
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


# The first migration describes exactly the schema `create_all` produced before
# Alembic existed, so any database predating it can be stamped here and then
# upgraded forward.
BASELINE_REVISION = "0001"


def _alembic_config():
    from alembic.config import Config

    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    return cfg


def init_db(auto_upgrade: bool = True) -> None:
    """Bring the configured database up to the current schema.

    Three cases, and they are genuinely different:

    * **Fresh** — `create_all` builds the current schema directly and the database
      is stamped at head. Replaying migrations would produce the same result more
      slowly, and the test suite creates one of these per test.
    * **Pre-Alembic** — tables but no version table. Its schema is the baseline by
      definition, so it is stamped there and then upgraded forward.
    * **Managed** — already stamped; just upgrade.

    Falls back to plain `create_all` if Alembic is not installed, so the pipeline
    still runs without it.
    """
    eng = engine()
    existing = set(inspect(eng).get_table_names())
    has_tables = bool(existing - {"alembic_version"})
    stamped = "alembic_version" in existing

    try:
        from alembic import command
    except ImportError:  # pragma: no cover - alembic is a declared dependency
        Base.metadata.create_all(eng)
        return

    cfg = _alembic_config()
    if not has_tables:
        Base.metadata.create_all(eng)
        command.stamp(cfg, "head")
        return

    if not stamped:
        command.stamp(cfg, BASELINE_REVISION)
    if auto_upgrade:
        command.upgrade(cfg, "head")


def reset_engine() -> None:
    """Drop cached engine/session factory — used by tests that repoint PCM_DB_PATH."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
