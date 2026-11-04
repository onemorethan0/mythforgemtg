"""The strength-engine proxy routes (measure / duel / advise) and the helpers behind them, with the
engine faked at `requests`. What is under test is Forge's own logic: how a stored deck becomes a
decklist, how engine failures map to HTTP codes, what gets persisted, and what the UI is told."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import server
from api import routes_strength as rs
from api import state

client = TestClient(server.app)
JOB = "0123456789abcdef"


class _Resp:
    def __init__(self, status=200, body=None, raises=False):
        self.status_code, self._body, self._raises = status, body if body is not None else {}, raises

    def json(self):
        if self._raises:
            raise ValueError("no json")
        return self._body


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "RENDER_DIR", tmp_path / "renders")
    (tmp_path / "renders").mkdir()
    rs._ENGINE_FP_CACHE.update(at=0.0, fp=None)
    with patch.dict(state._jobs, {}, clear=True), patch.dict(state._request_timestamps, {}, clear=True):
        yield tmp_path


def _write_deck(tmp, **kw):
    d = tmp / "renders" / JOB
    d.mkdir(parents=True)
    data = {"status": "done",
            "commander": {"original_name": "Tymna the Weaver", "themed_name": "The Weaver"},
            "partners": ["Thrasios, Triton Hero"],
            "deck": [{"original_name": "Sol Ring", "quantity": 1}, {"original_name": "Island", "quantity": 12}]}
    data.update(kw)
    (d / "deck.json").write_text(json.dumps(data), encoding="utf-8")
    return d / "deck.json"


# -- _deck_to_lines / _job_partners ------------------------------------------------------------------

def test_deck_to_lines_formats_commander_partners_and_quantities():
    text = rs._deck_to_lines({"name": "Tymna"}, [{"name": "Sol Ring", "quantity": 1}, {"name": "Island", "quantity": 12}],
                             partners=[{"name": "Thrasios"}])
    assert text.splitlines() == ["Commander:", "1 Tymna", "1 Thrasios", "", "Deck:", "1 Sol Ring", "12 Island"]


def test_deck_to_lines_skips_nameless_entries_and_defaults_quantity():
    text = rs._deck_to_lines({"name": "X"}, [{"name": ""}, {"name": "Forest"}, {}], partners=[{}, {"name": ""}])
    assert text.splitlines() == ["Commander:", "1 X", "", "Deck:", "1 Forest"]


def test_deck_to_lines_without_a_commander_has_no_commander_block():
    assert rs._deck_to_lines(None, [{"name": "Forest", "quantity": 3}]) == "Deck:\n3 Forest"
    assert rs._deck_to_lines({"name": ""}, []) == "Deck:"


def test_job_partners_turns_stored_names_back_into_dicts():
    assert rs._job_partners({"partners": ["A", "B"]}) == [{"name": "A"}, {"name": "B"}]
    assert rs._job_partners({}) == [] and rs._job_partners({"partners": None}) == []


# -- engine fingerprint ----------------------------------------------------------------------------------

def test_fingerprint_is_cached_for_a_minute_and_none_when_the_engine_is_down():
    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        return _Resp(body={"model_fingerprint": "abc123"})

    with patch.object(rs.requests, "get", fake_get):
        assert rs._engine_fingerprint() == "abc123"
        assert rs._engine_fingerprint() == "abc123"
    assert len(calls) == 1                                         # second answer came from the cache
    rs._ENGINE_FP_CACHE.update(at=0.0, fp=None)
    with patch.object(rs.requests, "get", lambda *a, **k: (_ for _ in ()).throw(OSError("down"))):
        assert rs._engine_fingerprint() is None


# -- _gauntlet_analyze -----------------------------------------------------------------------------------------

def test_analyze_posts_the_decklist_and_reshapes_the_response():
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen.update(url=url, body=json, timeout=timeout)
        return _Resp(body={"engine_version": "1", "model_fingerprint": "fp", "power_profile": {"bracket": 2},
                           "combos": [1], "insight": {"x": 1}, "deck": {"unresolved": ["Nope"]}})

    with patch.object(rs.requests, "post", fake_post):
        out = rs._gauntlet_analyze({"name": "Tymna"}, [{"name": "Sol Ring", "quantity": 1}], partners=[{"name": "Thrasios"}])
    assert seen["url"].endswith("/analyze") and seen["timeout"] >= 120
    assert seen["body"]["runs"] == 300 and seen["body"]["resilience"] is True and seen["body"]["combos"] is True
    assert "1 Thrasios" in seen["body"]["deck"] and seen["body"]["name"] == "Tymna"
    assert out["power_profile"] == {"bracket": 2} and out["unresolved"] == ["Nope"] and out["insight"] == {"x": 1}


def test_analyze_is_none_on_a_non_200_or_an_exception():
    with patch.object(rs.requests, "post", lambda *a, **k: _Resp(status=500)):
        assert rs._gauntlet_analyze({"name": "X"}, []) is None
    with patch.object(rs.requests, "post", lambda *a, **k: (_ for _ in ()).throw(OSError("refused"))):
        assert rs._gauntlet_analyze({"name": "X"}, []) is None


def test_analyze_tolerates_a_response_missing_the_deck_block():
    with patch.object(rs.requests, "post", lambda *a, **k: _Resp(body={})):
        assert rs._gauntlet_analyze({"name": "X"}, [])["unresolved"] == []


# -- _gauntlet_duel -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("games,expected", [(1, 20), (120, 120), (9999, 400), ("75", 75)])
def test_duel_clamps_the_game_count(games, expected):
    seen = {}
    with patch.object(rs.requests, "post", lambda url, json=None, timeout=None: seen.update(b=json) or _Resp(body={"ok": 1})):
        rs._gauntlet_duel({"name": "A"}, [], "1 Island", "A", "B", games)
    assert seen["b"]["games"] == expected and seen["b"]["seed"] == 42


def test_duel_maps_engine_statuses():
    with patch.object(rs.requests, "post", lambda *a, **k: _Resp(status=400, body={"detail": "bad list"})):
        assert rs._gauntlet_duel({"name": "A"}, [], "x", "A", "B", 50) == {"error": "bad list"}
    with patch.object(rs.requests, "post", lambda *a, **k: _Resp(status=400, raises=True)):
        assert rs._gauntlet_duel({"name": "A"}, [], "x", "A", "B", 50) == {"error": "duel failed"}
    with patch.object(rs.requests, "post", lambda *a, **k: _Resp(status=503)):
        assert rs._gauntlet_duel({"name": "A"}, [], "x", "A", "B", 50) is None
    with patch.object(rs.requests, "post", lambda *a, **k: (_ for _ in ()).throw(OSError("x"))):
        assert rs._gauntlet_duel({"name": "A"}, [], "x", "A", "B", 50) is None


# -- /measure ----------------------------------------------------------------------------------------------------------

def test_measure_validation_and_missing_decks(_isolated):
    assert client.post("/api/deck/short/measure").status_code == 404
    assert client.post(f"/api/deck/{JOB}/measure").status_code == 404
    _write_deck(_isolated, deck=[])
    assert client.post(f"/api/deck/{JOB}/measure").status_code == 400


def test_measure_is_503_when_the_engine_is_down(_isolated):
    _write_deck(_isolated)
    with patch.object(rs, "_gauntlet_analyze", lambda *a, **k: None):
        r = client.post(f"/api/deck/{JOB}/measure")
    assert r.status_code == 503 and "8020" in r.json()["detail"]


def test_measure_sends_the_stored_deck_and_persists_the_result(_isolated):
    p = _write_deck(_isolated)
    seen = {}

    def fake(commander, deck, partners=None):
        seen.update(commander=commander, deck=deck, partners=partners)
        return {"power_profile": {"bracket_estimate": 3}}

    state._jobs[JOB] = json.loads(p.read_text(encoding="utf-8"))
    with patch.object(rs, "_gauntlet_analyze", fake):
        r = client.post(f"/api/deck/{JOB}/measure")
    assert r.status_code == 200 and r.json() == {"power_profile": {"bracket_estimate": 3}}
    assert seen["commander"] == {"name": "Tymna the Weaver"}                 # ORIGINAL name, not the themed one
    assert seen["deck"] == [{"name": "Sol Ring", "quantity": 1}, {"name": "Island", "quantity": 12}]
    assert seen["partners"] == [{"name": "Thrasios, Triton Hero"}]
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["last_measure"]["simulation"]["power_profile"]["bracket_estimate"] == 3
    assert "date" in on_disk["last_measure"]
    assert state._jobs[JOB]["last_measure"]["simulation"] == r.json()          # in-memory copy too


def test_measure_still_answers_if_the_result_cannot_be_persisted(_isolated, monkeypatch):
    p = _write_deck(_isolated)
    real_write = type(p).write_text

    def failing(self, *a, **k):
        raise OSError("read-only")

    monkeypatch.setattr(type(p), "write_text", failing)
    with patch.object(rs, "_gauntlet_analyze", lambda *a, **k: {"power_profile": {}}):
        r = client.post(f"/api/deck/{JOB}/measure")
    monkeypatch.setattr(type(p), "write_text", real_write)
    assert r.status_code == 200


# -- /duel -------------------------------------------------------------------------------------------------------------------

def test_duel_validation(_isolated):
    assert client.post(f"/api/deck/{JOB}/duel", json={"opponent": "   "}).status_code == 400
    assert client.post(f"/api/deck/{JOB}/duel", json={"opponent": "1 Island"}).status_code == 404
    _write_deck(_isolated, deck=[])
    assert client.post(f"/api/deck/{JOB}/duel", json={"opponent": "1 Island"}).status_code == 400


def test_duel_maps_none_to_503_and_an_error_dict_to_400(_isolated):
    _write_deck(_isolated)
    with patch.object(rs, "_gauntlet_duel", lambda *a, **k: None):
        assert client.post(f"/api/deck/{JOB}/duel", json={"opponent": "1 Island"}).status_code == 503
    with patch.object(rs, "_gauntlet_duel", lambda *a, **k: {"error": "unparseable"}):
        r = client.post(f"/api/deck/{JOB}/duel", json={"opponent": "x"})
    assert r.status_code == 400 and r.json()["detail"] == "unparseable"


def test_duel_names_the_decks_and_passes_games_through(_isolated):
    _write_deck(_isolated)
    seen = {}

    def fake(commander, deck, opponent_text, name_a, name_b, games, partners=None):
        seen.update(name_a=name_a, name_b=name_b, games=games, opp=opponent_text)
        return {"win_rate": 0.55}

    with patch.object(rs, "_gauntlet_duel", fake):
        r = client.post(f"/api/deck/{JOB}/duel", json={"opponent": "1 Island", "opponent_name": "Bob", "games": 60})
    assert r.json() == {"win_rate": 0.55}
    assert seen == {"name_a": "The Weaver", "name_b": "Bob", "games": 60, "opp": "1 Island"}


# -- advise start / status ----------------------------------------------------------------------------------------------------

def test_advise_status_only_answers_for_advise_jobs():
    assert client.get("/api/deck/advise/" + JOB).status_code == 404
    state._jobs[JOB] = {"kind": "style_sample", "status": "done"}
    assert client.get("/api/deck/advise/" + JOB).status_code == 404


def test_advise_status_shapes():
    state._jobs[JOB] = {"kind": "advise", "status": "running"}
    assert client.get("/api/deck/advise/" + JOB).json() == {"status": "running"}
    state._jobs[JOB] = {"kind": "advise", "status": "done", "result": {"suggestions": []}}
    assert client.get("/api/deck/advise/" + JOB).json() == {"status": "done", "result": {"suggestions": []}}
    state._jobs[JOB] = {"kind": "advise", "status": "error", "error": "engine down"}
    assert client.get("/api/deck/advise/" + JOB).json() == {"status": "error", "detail": "engine down"}


def test_advise_start_validation(_isolated):
    assert client.post(f"/api/deck/{JOB}/advise", json={}).status_code == 404
    _write_deck(_isolated, deck=[])
    assert client.post(f"/api/deck/{JOB}/advise", json={}).status_code == 400


def test_advise_start_queues_a_job_and_runs_the_worker_with_the_stored_deck(_isolated):
    _write_deck(_isolated)
    seen = {}
    with patch.object(rs, "_run_advise_job", lambda *a, **k: seen.update(args=a)):
        r = client.post(f"/api/deck/{JOB}/advise", json={"axis": "speed"})
    assert r.status_code == 200
    jid = r.json()["job_id"]
    assert state._jobs[jid]["kind"] == "advise" and state._jobs[jid]["status"] == "running"
    args = seen["args"]
    assert args[0] == jid and args[1] == {"name": "Tymna the Weaver"} and args[3] == "speed"
    assert args[5] == [{"name": "Thrasios, Triton Hero"}] and args[-1] == JOB


def test_advise_start_is_rate_limited(_isolated):
    _write_deck(_isolated)
    with patch.object(rs, "_run_advise_job", lambda *a, **k: None):
        codes = [client.post(f"/api/deck/{JOB}/advise", json={}).status_code
                 for _ in range(state._RATE_LIMIT_CHAT_REQUESTS + 2)]
    assert codes[-1] == 429 and codes[0] == 200


# -- the advise worker -------------------------------------------------------------------------------------------------------------

def _run_worker(result, narrate=False, deck_job_id=JOB):
    jid = "a" * 16
    state._jobs[jid] = {"status": "running", "kind": "advise", "result": None, "error": None}
    with patch.object(rs, "_gauntlet_advise", lambda *a, **k: result), \
         patch.object(rs, "_suite_collection_mtime", lambda: 111.0), \
         patch.object(rs, "_narrate_suggestions", lambda r, j: {**r, "narrated": True}):
        rs._run_advise_job(jid, {"name": "Tymna"}, [{"name": "Sol Ring", "quantity": 1}], "speed", [], [],
                           narrate, {}, deck_job_id)
    return state._jobs[jid]


def test_worker_engine_down_and_engine_error_set_distinct_errors():
    assert "8020" in _run_worker(None)["error"]
    j = _run_worker({"error": "bad deck"})
    assert j["status"] == "error" and j["error"] == "bad deck"


def test_worker_success_caches_the_result_in_the_deck_with_its_validity_keys(_isolated):
    p = _write_deck(_isolated)
    j = _run_worker({"suggestions": [1]})
    assert j["status"] == "done" and j["result"] == {"suggestions": [1]}
    entry = json.loads(p.read_text(encoding="utf-8"))["advice_cache"]["speed"]
    assert entry["result"] == {"suggestions": [1]} and entry["collection_mtime"] == 111.0
    assert len(entry["deck_hash"]) >= 8 and entry["computed_at"]


def test_worker_narrates_only_when_asked():
    assert _run_worker({"suggestions": []}, narrate=True)["result"].get("narrated") is True
    assert "narrated" not in _run_worker({"suggestions": []}, narrate=False)["result"]


def test_worker_turns_an_unexpected_exception_into_an_error_job():
    jid = "b" * 16
    state._jobs[jid] = {"status": "running", "kind": "advise"}
    with patch.object(rs, "_gauntlet_advise", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kaboom"))):
        rs._run_advise_job(jid, {}, [], None, [], [], False, {}, None)
    assert state._jobs[jid]["status"] == "error" and "kaboom" in state._jobs[jid]["error"]


# -- advice cache validity -----------------------------------------------------------------------------------------------------------

def test_valid_advice_keeps_only_entries_matching_this_deck_and_collection(_isolated):
    job = {"commander": {"original_name": "Tymna"}, "deck": [{"original_name": "Sol Ring", "quantity": 1}], "partners": []}
    commander, deck = rs._job_deck_inputs(job)
    good_hash = rs._advice_deck_hash(commander, deck, rs._job_partners(job))
    job["advice_cache"] = {
        "speed":  {"result": {"a": 1}, "deck_hash": good_hash, "collection_mtime": 5.0, "computed_at": "t"},
        "stale_deck": {"result": {"a": 1}, "deck_hash": "other", "collection_mtime": 5.0},
        "stale_coll": {"result": {"a": 1}, "deck_hash": good_hash, "collection_mtime": 4.0},
        "no_result":  {"deck_hash": good_hash, "collection_mtime": 5.0},
        "junk": "not a dict",
    }
    with patch.object(rs, "_suite_collection_mtime", lambda: 5.0):
        assert set(rs._valid_advice(job)) == {"speed"}
    with patch.object(rs, "_suite_collection_mtime", lambda: None):
        assert rs._valid_advice(job) == {}                       # no collection file: nothing is valid
    assert rs._valid_advice({}) == {}
