"""Test fixtures.

Every test runs against a synthetic corpus with exact ground truth, generated once
per session into a temp directory. Tests that mutate state (acknowledgements, extra
runs) get their own database so they cannot order-depend on each other.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

TEST_PRODUCTS = 8
TEST_VARIANTS = 8


@pytest.fixture(scope="session")
def corpus(tmp_path_factory) -> Path:
    from tools.corpus import generate

    out = tmp_path_factory.mktemp("corpus")
    generate(out, n_products=TEST_PRODUCTS, seed=4242,
             variants_per_version=TEST_VARIANTS, full=False,
             run_label="run_test")
    return out


@pytest.fixture(scope="session")
def ground_truth(corpus) -> dict:
    return json.loads((corpus / "ground_truth.json").read_text())


@pytest.fixture(scope="session")
def manifest(corpus) -> dict:
    return json.loads((corpus / "variants_manifest.json").read_text())


def _point_db_at(path: Path) -> None:
    from db import session as dbsession

    os.environ["PCM_DB_PATH"] = str(path)
    dbsession.reset_engine()
    dbsession.init_db()


class Env:
    """A processed corpus: references registered and one run completed."""

    def __init__(self, corpus: Path, db_path: Path):
        self.corpus = corpus
        self.db_path = db_path
        self.input_dir = corpus / "scraped" / "run_test"
        self.run_id: int | None = None

    def process_references(self):
        from pipeline.references import process_corpus

        _point_db_at(self.db_path)
        return process_corpus(self.corpus, verbose=False)

    def run(self, **kwargs) -> int:
        from pipeline.run import run_pipeline

        _point_db_at(self.db_path)
        self.run_id = run_pipeline(self.input_dir, **kwargs)
        return self.run_id

    def activate(self):
        _point_db_at(self.db_path)
        return self


@pytest.fixture(scope="session")
def baseline(corpus, tmp_path_factory) -> Env:
    """Shared read-only environment: references processed, one run completed."""
    env = Env(corpus, tmp_path_factory.mktemp("db") / "baseline.sqlite")
    env.process_references()
    env.run(workers=4)
    return env


@pytest.fixture
def fresh_env(corpus, tmp_path) -> Env:
    """An isolated environment for tests that add runs or acknowledgements."""
    env = Env(corpus, tmp_path / "test.sqlite")
    env.process_references()
    return env
