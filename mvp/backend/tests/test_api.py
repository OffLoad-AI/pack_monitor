"""API behaviour, including the failure paths.

The persistence tests matter as much as the happy path here: the record of *how*
a comparison decided is the product, so a stage row that never got written is a
defect even when the verdict is right.
"""

from __future__ import annotations

import io
import time

import pytest
from fastapi.testclient import TestClient

from .conftest import cases_of


@pytest.fixture
def client(db_path, tmp_path, monkeypatch):
    """A client with its own database and its own artefact directory."""
    import core.paths as paths

    data = tmp_path / "data"
    (data / "comparisons").mkdir(parents=True)
    (data / "uploads").mkdir(parents=True)
    monkeypatch.setattr(paths, "DATA_DIR", data)
    monkeypatch.setattr(paths, "COMPARISON_DIR", data / "comparisons")
    monkeypatch.setattr(paths, "UPLOAD_DIR", data / "uploads")

    import api.routes.comparisons as routes
    import api.worker as worker
    import domains.packaging.compare as compare

    monkeypatch.setattr(routes, "UPLOAD_DIR", data / "uploads")
    monkeypatch.setattr(worker, "COMPARISON_DIR", data / "comparisons")
    monkeypatch.setattr(worker, "DATA_DIR", data)
    monkeypatch.setattr(compare, "COMPARISON_DIR", data / "comparisons")
    monkeypatch.setattr(compare, "DATA_DIR", data)

    from api.main import app

    with TestClient(app) as c:
        yield c


def _upload(path):
    return (path.name, io.BytesIO(path.read_bytes()), "image/png")


def _wait(client, comparison_id, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/comparisons/{comparison_id}").json()
        if body["status"] in ("COMPLETE", "FAILED"):
            return body
        time.sleep(0.25)
    raise AssertionError(f"comparison {comparison_id} did not finish in {timeout}s")


class TestSystem:
    def test_health(self, client):
        body = client.get("/api/health").json()
        assert body["status"] == "ok"
        assert body["pipeline_version"]

    def test_stage_list_lets_the_ui_draw_the_pipeline_before_it_runs(self, client):
        stages = client.get("/api/comparisons/stages").json()
        assert stages[0] == "load_normalize"
        assert stages[-1] == "verdict"

    def test_config_reports_what_is_editable(self, client):
        body = client.get("/api/config").json()
        assert body["values"]
        assert "ssim_threshold" in body["editable"]
        assert "ocr_backend" not in body["editable"]

    def test_editing_a_structural_key_is_rejected(self, client):
        r = client.put("/api/config", json={"values": {"ocr_backend": 1}})
        assert r.status_code == 400
        assert "editable" in r.json()["detail"].lower()

    def test_editing_with_a_bad_value_is_rejected(self, client):
        assert client.put(
            "/api/config", json={"values": {"ssim_threshold": -1}}).status_code == 400
        assert client.put(
            "/api/config", json={"values": {"ssim_threshold": "big"}}).status_code == 400


class TestComparisons:
    def test_empty_list(self, client):
        body = client.get("/api/comparisons").json()
        assert body == {"total": 0, "offset": 0, "limit": 50, "items": []}

    def test_unknown_verdict_filter_is_rejected(self, client):
        assert client.get("/api/comparisons?verdict=BANANA").status_code == 400

    def test_missing_comparison_is_a_404(self, client):
        assert client.get("/api/comparisons/4242").status_code == 404

    def test_non_image_upload_is_rejected(self, client):
        r = client.post("/api/comparisons", files={
            "reference": ("notes.txt", io.BytesIO(b"hello"), "text/plain"),
            "marketplace": ("notes.txt", io.BytesIO(b"hello"), "text/plain"),
        })
        assert r.status_code == 400
        assert "PNG" in r.json()["detail"]

    def test_end_to_end_persists_every_stage(self, client, corpus, truth):
        """A comparison run through the API records its whole trace.

        This is the test that protects the product rather than the pipeline: a
        verdict with no stages behind it is exactly what this build exists not
        to produce.
        """
        case = cases_of(truth, "NUMERIC_DRIFT")[0]
        r = client.post("/api/comparisons", files={
            "reference": _upload(corpus / case["reference"]),
            "marketplace": _upload(corpus / case["marketplace"]),
        }, data={"label": "SKU001 front"})
        assert r.status_code == 202
        comparison_id = r.json()["id"]

        body = _wait(client, comparison_id)
        assert body["status"] == "COMPLETE"
        assert body["verdict"]
        assert body["label"] == "SKU001 front"
        assert body["reference_sha256"] and body["marketplace_sha256"]

        stages = [s["stage"] for s in body["stages"]]
        assert stages == client.get("/api/comparisons/stages").json()
        for stage in body["stages"]:
            assert stage["notes"], f"{stage['stage']} persisted no explanation"

        # Artefacts are served as paths, never inlined.
        registration = next(s for s in body["stages"] if s["stage"] == "registration")
        assert registration["artifacts"].get("checkerboard")
        assert not registration["artifacts"]["checkerboard"].startswith("data:")

    def test_identical_pair_short_circuits_but_still_records_every_stage(
            self, client, corpus, truth):
        case = cases_of(truth, "IDENTICAL")[0]
        r = client.post("/api/comparisons", files={
            "reference": _upload(corpus / case["reference"]),
            "marketplace": _upload(corpus / case["marketplace"]),
        })
        body = _wait(client, r.json()["id"])

        assert body["verdict"] == "IDENTICAL"
        assert body["confidence"] == 1.0
        stages = {s["stage"]: s for s in body["stages"]}
        assert stages["registration"]["status"] == "SKIPPED"
        assert stages["registration"]["notes"], "a skipped stage did not say why"
        assert stages["verdict"]["status"] == "OK"

    def test_delete_removes_the_row_and_its_artefacts(self, client, corpus, truth):
        case = cases_of(truth, "IDENTICAL")[0]
        r = client.post("/api/comparisons", files={
            "reference": _upload(corpus / case["reference"]),
            "marketplace": _upload(corpus / case["marketplace"]),
        })
        comparison_id = r.json()["id"]
        _wait(client, comparison_id)

        import core.paths as paths

        artefacts = paths.COMPARISON_DIR / str(comparison_id)
        assert artefacts.exists()

        assert client.delete(f"/api/comparisons/{comparison_id}").status_code == 204
        assert client.get(f"/api/comparisons/{comparison_id}").status_code == 404
        assert not artefacts.exists()


class TestBatch:
    def test_pairs_by_naming_convention(self, client, corpus, truth):
        case = cases_of(truth, "REENCODED")[0]
        ref = corpus / case["reference"]
        mkt = corpus / case["marketplace"]
        r = client.post("/api/comparisons/batch", files=[
            ("files", ("ref__demo.png", io.BytesIO(ref.read_bytes()), "image/png")),
            ("files", (f"mkt__demo{mkt.suffix}", io.BytesIO(mkt.read_bytes()),
                       "image/jpeg")),
        ])
        assert r.status_code == 202
        assert len(r.json()["created"]) == 1

    def test_unpaired_files_are_reported_not_dropped(self, client, corpus, truth):
        case = cases_of(truth, "REENCODED")[0]
        ref = corpus / case["reference"]
        mkt = corpus / case["marketplace"]
        r = client.post("/api/comparisons/batch", files=[
            ("files", ("ref__a.png", io.BytesIO(ref.read_bytes()), "image/png")),
            ("files", (f"mkt__a{mkt.suffix}", io.BytesIO(mkt.read_bytes()),
                       "image/jpeg")),
            ("files", ("ref__lonely.png", io.BytesIO(ref.read_bytes()), "image/png")),
        ])
        body = r.json()
        assert len(body["created"]) == 1
        assert any("lonely" in u for u in body["unmatched"])

    def test_a_batch_with_no_pairs_explains_the_convention(self, client, corpus, truth):
        case = cases_of(truth, "REENCODED")[0]
        ref = corpus / case["reference"]
        r = client.post("/api/comparisons/batch", files=[
            ("files", ("whatever.png", io.BytesIO(ref.read_bytes()), "image/png")),
        ])
        assert r.status_code == 400
        assert "ref__" in r.json()["detail"]
