"""Build lifecycle routes that had no tests: validation, rate limiting, cancel, status and the SSE
events stream. The workers are patched out, so nothing builds, themes, or touches the GPU."""
from __future__ import annotations

import json
import threading
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import server
from api import routes_builds, state

client = TestClient(server.app)
JOB = "0123456789abcdef"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "RENDER_DIR", tmp_path / "renders")
    (tmp_path / "renders").mkdir()
    monkeypatch.setattr(routes_builds, "_run_build", lambda *a, **k: None)
    monkeypatch.setattr(routes_builds, "_run_card_build", lambda *a, **k: None)
    with patch.dict(state._jobs, {}, clear=True), patch.dict(state._progress, {}, clear=True), \
         patch.dict(state._request_timestamps, {}, clear=True):
        yield tmp_path


# -- /api/deck/active --------------------------------------------------------------------------------

def test_active_job_is_none_when_nothing_is_building():
    assert client.get("/api/deck/active").json() == {"job_id": None, "status": "none"}


def test_active_job_returns_the_most_recent_building_one():
    state._jobs["a" * 16] = {"status": "building"}
    state._jobs["b" * 16] = {"status": "done"}
    state._jobs["c" * 16] = {"status": "building"}
    assert client.get("/api/deck/active").json() == {"job_id": "c" * 16, "status": "building"}


# -- /api/deck/build ---------------------------------------------------------------------------------

def test_build_needs_a_commander_or_a_decklist():
    r = client.post("/api/deck/build", json={})
    assert r.status_code == 400
    assert client.post("/api/deck/build", json={"commander_name": "   "}).status_code == 400


def test_build_queues_a_job_and_returns_its_id():
    r = client.post("/api/deck/build", json={"commander_name": "Atraxa, Praetors' Voice"})
    assert r.status_code == 200
    jid = r.json()["job_id"]
    assert len(jid) == 16 and state._jobs[jid]["status"] == "queued"
    assert isinstance(state._jobs[jid]["cancel_event"], threading.Event)
    assert state._progress[jid] == []


def test_build_accepts_an_import_instead_of_a_commander():
    assert client.post("/api/deck/build", json={"deck_list": "1 Sol Ring"}).status_code == 200
    assert client.post("/api/deck/build", json={"deck_url": "https://archidekt.com/decks/1/x"}).status_code == 200


def test_build_is_rate_limited_per_client():
    codes = [client.post("/api/deck/build", json={"commander_name": "X"}).status_code
             for _ in range(state._RATE_LIMIT_BUILD_REQUESTS + 2)]
    assert codes[:state._RATE_LIMIT_BUILD_REQUESTS] == [200] * state._RATE_LIMIT_BUILD_REQUESTS
    assert codes[-1] == 429


def test_single_card_build_needs_a_name():
    assert client.post("/api/card/build", json={"card": {"name": "  "}}).status_code == 400
    ok = client.post("/api/card/build", json={"card": {"name": "My Card"}})
    assert ok.status_code == 200 and len(ok.json()["job_id"]) == 16


# -- cancel ------------------------------------------------------------------------------------------------

def test_cancel_an_unknown_job_is_a_404():
    assert client.post(f"/api/deck/{JOB}/cancel").status_code == 404


def test_cancel_sets_the_event_and_schedules_vram_eviction_exactly_once():
    ev = threading.Event()
    state._jobs[JOB] = {"status": "building", "cancel_event": ev}
    with patch.object(routes_builds, "_free_all_vram") as free:
        first = client.post(f"/api/deck/{JOB}/cancel")
        second = client.post(f"/api/deck/{JOB}/cancel")
    assert first.json() == {"status": "cancelling"} and ev.is_set()
    assert second.json()["status"] == "already done or not cancellable"
    assert free.call_count == 1                       # not once per click


def test_cancel_a_job_with_no_event_is_a_harmless_no_op():
    state._jobs[JOB] = {"status": "done"}
    assert client.post(f"/api/deck/{JOB}/cancel").json()["status"] == "already done or not cancellable"


# -- status / events -------------------------------------------------------------------------------------------

def test_status_of_a_bad_or_unknown_id_is_404():
    assert client.get("/api/deck/short/status").status_code == 404
    assert client.get(f"/api/deck/{JOB}/status").status_code == 404


def test_status_reports_memory_state_and_error():
    state._jobs[JOB] = {"status": "error", "error": "boom"}
    assert client.get(f"/api/deck/{JOB}/status").json() == {"status": "error", "error": "boom"}


def test_status_falls_back_to_disk_and_rehydrates(_isolated):
    d = _isolated / "renders" / JOB
    d.mkdir()
    (d / "deck.json").write_text(json.dumps({"status": "done", "commander": {"original_name": "X"},
                                             "deck": [], "built_at": 1.0}), encoding="utf-8")
    assert client.get(f"/api/deck/{JOB}/status").json() == {"status": "done", "error": None}
    assert JOB in state._jobs                              # cached for the next call


def test_events_for_an_unknown_job_is_404_and_a_finished_job_streams_then_closes():
    assert client.get(f"/api/deck/{JOB}/events").status_code == 404
    state._jobs[JOB] = {"status": "done"}
    state._push(JOB, "progress", '{"pct": 50}')
    state._push(JOB, "done", "{}")
    r = client.get(f"/api/deck/{JOB}/events")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    assert r.text == 'event: progress\ndata: {"pct": 50}\n\nevent: done\ndata: {}\n\n'


# -- style sample --------------------------------------------------------------------------------------------------

def test_style_sample_status_only_answers_for_style_sample_jobs():
    assert client.get(f"/api/deck/style-sample/{JOB}").status_code == 404
    state._jobs[JOB] = {"status": "done", "kind": "build"}
    assert client.get(f"/api/deck/style-sample/{JOB}").status_code == 404
    state._jobs[JOB] = {"status": "running", "kind": "style_sample", "current": 1, "total": 4, "images": []}
    body = client.get(f"/api/deck/style-sample/{JOB}").json()
    assert body["status"] == "running" and body["current"] == 1 and body["total"] == 4


def test_style_sample_image_404s_for_a_missing_file_and_a_bad_id(monkeypatch, tmp_path):
    monkeypatch.setattr(routes_builds, "_STYLE_SAMPLE_DIR", tmp_path / "samples")
    assert client.get(f"/api/deck/style-sample/{JOB}/img/0").status_code == 404
    assert client.get("/api/deck/style-sample/not-an-id/img/0").status_code == 404
    (tmp_path / "samples" / JOB).mkdir(parents=True)
    (tmp_path / "samples" / JOB / "sample_0.png").write_bytes(b"\x89PNG")
    r = client.get(f"/api/deck/style-sample/{JOB}/img/0")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


# -- animate panel data ---------------------------------------------------------------------------------------------------

def test_video_presets_expose_every_option_list():
    body = client.get("/api/video-presets").json()
    assert set(body) == {"presets", "foil_styles", "formats", "loop_styles", "caps"}
    assert body["presets"] and body["formats"] and body["loop_styles"]
    assert body["caps"]["motion"]["min_s"] < body["caps"]["motion"]["max_s"]
