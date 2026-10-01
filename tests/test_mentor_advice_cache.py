"""Mentor adhoc D2 (Forge side): the Advise job persists `advice_cache` into deck.json, and
`/api/deck/{job_id}/mentor` passes only still-valid entries (deck hash AND collection mtime)
to the engine as `advice`."""
import json
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import server

_JOB_ID = "0123456789abcdef"
_COMMANDER = {"name": "Test Commander"}
_DECK = [{"name": "Sol Ring", "quantity": 1}]
_RESULT = {"axis": "clock", "axis_label": "Clock", "baseline": 40.0, "evaluated": 3,
           "min_delta": 1.0, "suggestions": []}


def _resp(status_code, json_body):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_body
    return r


def _job(advice_cache=None, card="Sol Ring"):
    job = {
        "commander": {"original_name": "Test Commander"},
        "deck": [{"original_name": card, "quantity": 1}],
        "stats": {},
    }
    if advice_cache is not None:
        job["advice_cache"] = advice_cache
    return job


def _entry(*, deck=None, mtime=100.0, result=None):
    return {
        "result": result or _RESULT,
        "deck_hash": server._advice_deck_hash(_COMMANDER, deck or _DECK),
        "collection_mtime": mtime, "computed_at": "2026-09-30T12:00:00",
    }


def _collection(tmp_path, mtime=None):
    p = tmp_path / "collection.csv"
    p.write_text("Count,Name\n1,Sol Ring\n", encoding="utf-8")
    if mtime is not None:
        import os
        os.utime(p, (mtime, mtime))
    return p


def _ask(job, collection_path):
    with patch.object(server, "_jobs", {_JOB_ID: job}), \
         patch.object(server, "suite_collection_path", lambda: collection_path), \
         patch("server.requests.post", return_value=_resp(200, {"reply": "x", "gated": True})) as m:
        resp = TestClient(server.app).post(f"/api/deck/{_JOB_ID}/mentor", json={"question": "q"})
    assert resp.status_code == 200
    return m.call_args.kwargs["json"]


# ── persistence ──────────────────────────────────────────────────────────────────────

def _run(tmp_path, axis, result=_RESULT, mtime=100.0):
    deck_dir = tmp_path / _JOB_ID
    deck_dir.mkdir()
    (deck_dir / "deck.json").write_text(json.dumps({"deck": [], "status": "done"}), encoding="utf-8")
    col = _collection(tmp_path, mtime)
    mem_deck = {"commander": {}}
    advise_jobs = {"adv": {"status": "running", "kind": "advise"}}
    with patch.object(server, "RENDER_DIR", tmp_path), \
         patch.object(server, "_jobs", {**advise_jobs, _JOB_ID: mem_deck}), \
         patch.object(server, "suite_collection_path", lambda: col), \
         patch.object(server, "_gauntlet_advise", return_value=result):
        server._run_advise_job("adv", _COMMANDER, _DECK, axis, [], [], False, mem_deck, _JOB_ID)
        status = server._jobs["adv"]["status"]
    disk = json.loads((deck_dir / "deck.json").read_text(encoding="utf-8"))
    return disk, mem_deck, status


def test_advise_job_persists_the_result_under_the_requested_axis(tmp_path):
    disk, mem, status = _run(tmp_path, "clock")
    assert status == "done"
    e = disk["advice_cache"]["clock"]
    assert e["result"] == _RESULT
    assert e["deck_hash"] == server._advice_deck_hash(_COMMANDER, _DECK)
    assert e["collection_mtime"] == 100.0 and e["computed_at"]
    assert mem["advice_cache"]["clock"] == e         # in-memory job kept in step
    assert disk["status"] == "done"                  # the rest of deck.json is untouched


def test_advise_job_keys_an_unspecified_axis_as_auto(tmp_path):
    disk, _, _ = _run(tmp_path, None)
    assert list(disk["advice_cache"]) == ["auto"]


def test_a_failed_advise_job_caches_nothing(tmp_path):
    disk, _, status = _run(tmp_path, "clock", result={"error": "boom"})
    assert status == "error" and "advice_cache" not in disk


def test_advice_cache_is_not_carried_across_a_rebuild():
    assert "advice_cache" not in server._PROVENANCE_KEYS


def test_advise_route_passes_the_deck_job_id_and_accepts_clock(tmp_path):
    calls = []
    job = _job()
    with patch.object(server, "_jobs", {_JOB_ID: job}), \
         patch.object(server, "_run_advise_job", lambda *a, **k: calls.append(a)):
        resp = TestClient(server.app).post(f"/api/deck/{_JOB_ID}/advise",
                                           json={"axis": "clock", "narrate": False})
    assert resp.status_code == 200 and "job_id" in resp.json()
    assert calls[0][3] == "clock" and calls[0][-1] == _JOB_ID


# ── pass-through + invalidation ──────────────────────────────────────────────────────

def test_valid_cache_entry_is_passed_to_the_engine(tmp_path):
    col = _collection(tmp_path, 100.0)
    payload = _ask(_job({"clock": _entry(mtime=100.0)}), col)
    assert payload["advice"] == {"clock": {"result": _RESULT, "computed_at": "2026-09-30T12:00:00"}}


def test_an_edited_deck_invalidates_the_entry(tmp_path):
    col = _collection(tmp_path, 100.0)
    stale = _entry(mtime=100.0)                      # hashed against Sol Ring ...
    payload = _ask(_job({"clock": stale}, card="Arcane Signet"), col)   # ... deck now differs
    assert "advice" not in payload


def test_a_changed_collection_invalidates_the_entry(tmp_path):
    col = _collection(tmp_path, 200.0)
    payload = _ask(_job({"clock": _entry(mtime=100.0)}), col)
    assert "advice" not in payload


def test_a_missing_collection_invalidates_the_entry(tmp_path):
    payload = _ask(_job({"clock": _entry(mtime=100.0)}), tmp_path / "gone.csv")
    assert "advice" not in payload


def test_only_the_still_valid_entries_survive(tmp_path):
    col = _collection(tmp_path, 100.0)
    cache = {"clock": _entry(mtime=100.0), "ceiling": _entry(mtime=99.0)}
    payload = _ask(_job(cache), col)
    assert list(payload["advice"]) == ["clock"]


def test_a_deck_with_no_cache_sends_no_advice(tmp_path):
    payload = _ask(_job(), _collection(tmp_path, 100.0))
    assert "advice" not in payload


def test_helper_omits_advice_when_falsy():
    with patch("server.requests.post", return_value=_resp(200, {})) as m:
        server._gauntlet_mentor_chat({"name": "X"}, [], "q", advice={})
    assert "advice" not in m.call_args.kwargs["json"]
    with patch("server.requests.post", return_value=_resp(200, {})) as m:
        server._gauntlet_mentor_chat({"name": "X"}, [], "q", advice={"clock": {"result": {}}})
    assert m.call_args.kwargs["json"]["advice"] == {"clock": {"result": {}}}
