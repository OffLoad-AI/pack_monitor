"""FastAPI application.

    uvicorn api.main:app --reload --port 8000

Images are served from static mounts rather than encoded into JSON responses; the
review queue shows dozens of thumbnails per page and the comparison viewer loads
full-resolution artwork, neither of which should pass through the JSON layer.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from db.session import init_db
from pipeline.run import reap_stale_runs
from pipeline.config import PIPELINE_VERSION, REPO_ROOT

from .routes import findings, products, runs, system

DATA_ROOT = REPO_ROOT / "data"
CALIBRATION_ROOT = REPO_ROOT / "calibration"

app = FastAPI(
    title="Packaging Compliance Monitor",
    version=PIPELINE_VERSION,
    description="Identifies which approved artwork version each marketplace "
                "listing is currently serving.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(products.router)
app.include_router(runs.router)
app.include_router(findings.router)
app.include_router(system.router)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    # A server restart during a run leaves that run marked RUNNING; clear it so the
    # dashboard does not show phantom progress and new runs are not blocked.
    reap_stale_runs()
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    CALIBRATION_ROOT.mkdir(parents=True, exist_ok=True)


@app.get("/api/health")
def health():
    return {"status": "ok", "pipeline_version": PIPELINE_VERSION}


DATA_ROOT.mkdir(parents=True, exist_ok=True)
CALIBRATION_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=str(DATA_ROOT)), name="files")
app.mount("/calibration", StaticFiles(directory=str(CALIBRATION_ROOT)), name="calibration")
