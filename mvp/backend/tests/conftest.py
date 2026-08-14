"""Shared fixtures.

A small corpus is generated once per session into a temp directory and every
test reads from it. Nothing here touches `data/` — a test run that overwrote the
real corpus or the real database would be a nasty surprise, and the other build's
`--reset` flag exists because of exactly that class of accident.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.config import EngineConfig, load_config
from core.ocr import get_engine
from tools.corpus import build_case, generate_pairs

# Enough pairs to cover every class at least once, small enough that the suite
# runs in a few minutes on one core.
CORPUS_PAIRS = 27
CORPUS_SEED = 424242


@pytest.fixture(scope="session")
def corpus(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("pairs")
    generate_pairs(out, CORPUS_PAIRS, CORPUS_SEED)
    return out


@pytest.fixture(scope="session")
def truth(corpus) -> dict:
    import json

    return json.loads((corpus / "ground_truth.json").read_text())


@pytest.fixture(scope="session")
def cfg() -> EngineConfig:
    """The calibrated configuration, as shipped.

    Tests run against the same thresholds the tool ships with. Substituting
    convenient ones would make the suite pass while the product failed.
    """
    return load_config()


@pytest.fixture(scope="session")
def ocr():
    """One engine for the whole session — model load is the dominant cost."""
    return get_engine("auto")


@pytest.fixture(scope="session")
def artifacts(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("artifacts")


@pytest.fixture
def db_path(tmp_path, monkeypatch) -> Path:
    """A fresh database per test, pointed away from `data/`."""
    from db import session as db_session

    path = tmp_path / "test.sqlite"
    monkeypatch.setenv("PPC_DB_PATH", str(path))
    db_session.reset_engine()
    db_session.init_db()
    yield path
    db_session.reset_engine()


@pytest.fixture(scope="session")
def one_case(corpus):
    """Build a single extra case of a named class, on demand."""

    def make(case_class: str, index: int = 900):
        return build_case(index, case_class, corpus, CORPUS_SEED)

    return make


def cases_of(truth: dict, case_class: str) -> list[dict]:
    return [c for c in truth.values() if c["case_class"] == case_class]


def run_pair(corpus: Path, case: dict, cfg, ocr, artifacts: Path, index: int = 1):
    from domains.packaging.compare import compare_pair

    return compare_pair(
        corpus / case["reference"], corpus / case["marketplace"],
        comparison_id=index, config=cfg,
        artifacts_root=artifacts / case["name"], data_root=artifacts,
        ocr_engine=ocr)


os.environ.setdefault("PPC_LOG_LEVEL", "WARNING")
