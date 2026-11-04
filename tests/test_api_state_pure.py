"""api/state.py in-memory job helpers (ids, rate limit, SSE push, trimming).

The draft came from a local model (qwen3:8b) and failed verification even after two
automatic repair rounds (wrong exception type, wrong SSE shape, missing import). This is a
from-scratch rewrite against the real code; only the list of functions to cover was kept.
"""
from __future__ import annotations

import asyncio
import json
import threading
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api import state

GOOD = "0123456789abcdef"


@pytest.fixture(autouse=True)
def _isolate():
    with patch.dict(state._jobs, {}, clear=True), \
         patch.dict(state._progress, {}, clear=True), \
         patch.dict(state._request_timestamps, {}, clear=True), \
         patch.dict(state._deck_regen_locks, {}, clear=True):
        yield


# -- _require_job_id ------------------------------------------------------------

def test_valid_job_id_is_returned_unchanged():
    assert state._require_job_id(GOOD) == GOOD


@pytest.mark.parametrize("bad", ["", "short", GOOD + "0", GOOD.upper(), "../../etc/passwd", "g" * 16])
def test_bad_job_ids_are_a_404(bad):
    with pytest.raises(HTTPException) as e:
        state._require_job_id(bad)
    assert e.value.status_code == 404


# -- _check_rate_limit ----------------------------------------------------------

def test_rate_limit_allows_up_to_the_limit_then_refuses():
    for _ in range(state._RATE_LIMIT_BUILD_REQUESTS):
        assert state._check_rate_limit("1.2.3.4") is True
    assert state._check_rate_limit("1.2.3.4") is False


def test_rate_limit_is_per_client():
    for _ in range(state._RATE_LIMIT_BUILD_REQUESTS):
        state._check_rate_limit("a")
    assert state._check_rate_limit("a") is False
    assert state._check_rate_limit("b") is True


def test_rate_limit_custom_max_and_window_expiry():
    assert state._check_rate_limit("c", max_requests=1) is True
    assert state._check_rate_limit("c", max_requests=1) is False
    # age the recorded request out of the window: allowed again
    state._request_timestamps["c"] = [t - state._RATE_LIMIT_WINDOW - 1 for t in state._request_timestamps["c"]]
    assert state._check_rate_limit("c", max_requests=1) is True


# -- _push ----------------------------------------------------------------------

def test_push_appends_an_sse_formatted_message():
    state._push(GOOD, "progress", '{"pct": 5}')
    state._push(GOOD, "done", "{}")
    assert state._progress[GOOD] == ['event: progress\ndata: {"pct": 5}\n\n', "event: done\ndata: {}\n\n"]


# -- _mark_job_error / _finalize_job ---------------------------------------------

def test_mark_job_error_sets_status_and_pushes_an_error_event():
    state._jobs[GOOD] = {"status": "building"}
    state._mark_job_error(GOOD, ValueError("boom"))
    assert state._jobs[GOOD]["status"] == "error"
    assert state._jobs[GOOD]["error"] == "boom"
    ev = state._progress[GOOD][-1]
    assert ev.startswith("event: error\n")
    assert json.loads(ev.split("data: ", 1)[1]) == {"msg": "boom"}


def test_finalize_drops_cancel_event_and_caps_the_sse_buffer():
    state._jobs[GOOD] = {"status": "done", "cancel_event": threading.Event()}
    state._progress[GOOD] = [f"m{i}" for i in range(200)]
    state._finalize_job(GOOD)
    assert "cancel_event" not in state._jobs[GOOD]
    assert state._progress[GOOD] == [f"m{i}" for i in range(120, 200)]   # last 80 kept


def test_finalize_tolerates_an_unknown_job():
    state._finalize_job("deadbeefdeadbeef")      # must not raise


# -- _serializable_job -----------------------------------------------------------

def test_serializable_job_strips_internal_keys_and_dumps_as_json():
    job = {"status": "building", "cancel_event": threading.Event(), "deck": [1]}
    out = state._serializable_job(job)
    assert out == {"status": "building", "deck": [1]}
    json.dumps(out)
    assert "cancel_event" in job            # the original is untouched


# -- _trim_in_memory_jobs ---------------------------------------------------------

def test_trim_keeps_the_newest_finished_jobs_in_full():
    n = state._MAX_INMEM_JOBS + 3
    for i in range(n):
        jid = f"{i:016x}"
        state._jobs[jid] = {"status": "done", "built_at": i, "deck": ["card"], "extra": 1}
        state._progress[jid] = ["x"]
    state._trim_in_memory_jobs()
    full = [j for j in state._jobs.values() if "deck" in j]
    assert len(full) == state._MAX_INMEM_JOBS
    # the oldest three were reduced to status metadata only, and lost their progress
    for i in range(3):
        jid = f"{i:016x}"
        assert state._jobs[jid] == {"status": "done", "error": None, "built_at": i}
        assert jid not in state._progress
    assert f"{n - 1:016x}" in state._progress


def test_trim_never_touches_running_jobs():
    for i in range(state._MAX_INMEM_JOBS + 2):
        state._jobs[f"{i:016x}"] = {"status": "building", "deck": [1]}
    state._trim_in_memory_jobs()
    assert all("deck" in j for j in state._jobs.values())


# -- _get_deck_regen_lock -----------------------------------------------------------

def test_regen_lock_is_stable_per_deck_and_distinct_across_decks():
    a1 = state._get_deck_regen_lock("a")
    assert state._get_deck_regen_lock("a") is a1
    assert state._get_deck_regen_lock("b") is not a1


# -- _sse_stream -------------------------------------------------------------------

def test_sse_stream_replays_buffered_events_and_stops_when_the_job_is_done():
    state._jobs[GOOD] = {"status": "done"}
    state._push(GOOD, "progress", "1")
    state._push(GOOD, "done", "2")

    async def collect():
        return [m async for m in state._sse_stream(GOOD)]

    assert asyncio.run(collect()) == ["event: progress\ndata: 1\n\n", "event: done\ndata: 2\n\n"]
