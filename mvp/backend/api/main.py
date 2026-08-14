"""FastAPI application.

    uvicorn api.main:app --reload --port 8000

Artefacts are served from a static mount rather than encoded into JSON. The
detail screen loads a dozen images per comparison — normalized pairs, a
checkerboard blend, an SSIM heatmap, two crops per region — and putting those
through the JSON layer would make every response megabytes and uncacheable.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from core.logging import configure
from core.paths import CALIBRATION_DIR, DATA_DIR, PIPELINE_VERSION, ensure_dirs
from db.session import init_db

from . import worker
from .routes import comparisons, system


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure()
    ensure_dirs()
    init_db()
    # A server restart during a comparison leaves that row marked RUNNING; clear
    # it so the history screen does not show progress nothing is making.
    worker.reap_stale()
    yield


app = FastAPI(
    title="Pairwise Packaging Comparison",
    version=PIPELINE_VERSION,
    description="Compares one reference artwork against one marketplace image "
                "and shows every step of how it decided.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(comparisons.router)
app.include_router(system.router)

ensure_dirs()
app.mount("/files", StaticFiles(directory=str(DATA_DIR)), name="files")
app.mount("/calibration", StaticFiles(directory=str(CALIBRATION_DIR)),
          name="calibration")
