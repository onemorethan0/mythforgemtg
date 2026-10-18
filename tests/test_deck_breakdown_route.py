"""`POST /api/deck/{job_id}/breakdown` -- the Deck Mentor's measurements for the deck view's
charts and group-by-role. The engine call is stubbed; what is pinned here is the cache: a
revisit reads deck.json instead of re-measuring, a changed decklist re-measures, and
`refresh=true` always re-measures (an engine tagger fix moves roles without moving the list).
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

import server

client = TestClient(server.app)

_JOB_ID = "fedcba9876543210"


def _write_deck(render_dir, cards):
    job_dir = render_dir / _JOB_ID
    job_dir.mkdir(parents=True, exist_ok=True)
    deck = {
        "status": "done",
        "commander": {"original_name": "Test Commander"},
        "deck": [{"original_name": n, "quantity": q, "type_line": "Instant"} for n, q in cards],
        "built_at": "2026-10-18T00:00:00",
    }
    (job_dir / "deck.json").write_text(json.dumps(deck), encoding="utf-8")
    return job_dir


def _stub(monkeypatch, calls):
    def fake(commander, deck, themes=None, partners=None):
        calls.append([c["name"] for c in deck])
        return {"roles": {"rows": [{"role": "removal", "cards": 1, "card_target": 7, "short_by": 6}]},
                "cards": [{"name": deck[0]["name"], "qty": 1, "roles": ["removal"], "commander": False}]}
    monkeypatch.setattr(server, "_gauntlet_breakdown", fake)


def test_breakdown_is_measured_once_then_read_from_deck_json(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "RENDER_DIR", tmp_path)
    server._jobs.pop(_JOB_ID, None)
    job_dir = _write_deck(tmp_path, [("Murder", 1)])
    calls = []
    _stub(monkeypatch, calls)

    first = client.post(f"/api/deck/{_JOB_ID}/breakdown").json()
    assert first["cached"] is False and first["cards"][0]["roles"] == ["removal"]
    assert "breakdown" in json.loads((job_dir / "deck.json").read_text(encoding="utf-8"))

    second = client.post(f"/api/deck/{_JOB_ID}/breakdown").json()
    assert second["cached"] is True
    assert len(calls) == 1


def test_changed_decklist_and_refresh_both_re_measure(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "RENDER_DIR", tmp_path)
    server._jobs.pop(_JOB_ID, None)
    calls = []
    _stub(monkeypatch, calls)
    _write_deck(tmp_path, [("Murder", 1)])
    client.post(f"/api/deck/{_JOB_ID}/breakdown")

    # A swap rewrites the list but keeps the stale breakdown in deck.json.
    p = tmp_path / _JOB_ID / "deck.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["deck"] = [{"original_name": "Doom Blade", "quantity": 1, "type_line": "Instant"}]
    p.write_text(json.dumps(data), encoding="utf-8")
    assert client.post(f"/api/deck/{_JOB_ID}/breakdown").json()["cached"] is False

    assert client.post(f"/api/deck/{_JOB_ID}/breakdown?refresh=true").json()["cached"] is False
    assert calls == [["Murder"], ["Doom Blade"], ["Doom Blade"]]


def test_engine_down_is_a_503(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "RENDER_DIR", tmp_path)
    server._jobs.pop(_JOB_ID, None)
    _write_deck(tmp_path, [("Murder", 1)])
    monkeypatch.setattr(server, "_gauntlet_breakdown", lambda *a, **k: None)
    resp = client.post(f"/api/deck/{_JOB_ID}/breakdown")
    assert resp.status_code == 503
    assert ":8020" in resp.json()["detail"]
