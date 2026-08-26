"""`GET /api/decks` — the History/RecentDecks list endpoint.

PLAN_CLOCK Phase 4 (UI honesty audit): a deck's cached MythGauntlet measurement carries
`bracket_plays_up` (the engine's own flag that a bracket estimate sits on a boundary it
can't resolve from the card list alone — see `SimStrengthPanel.jsx`'s amber banner), and
this route already reads that same cached `power_profile` to build `measured_bracket` /
`measured_label` — but silently dropped `bracket_plays_up`, so a compact "⚡ B2" badge on a
History or RecentDecks tile could claim more precision than the engine itself claims for
that deck. This pins the fix: `measured_plays_up` on the response.

Offline: writes a real `deck.json` to a monkeypatched `RENDER_DIR`, no network/engine call.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

import server

client = TestClient(server.app)

_JOB_ID = "0123456789abcdef"


def _write_deck(render_dir, *, plays_up, job_id=_JOB_ID, bracket_estimate=2):
    job_dir = render_dir / job_id
    job_dir.mkdir(parents=True)
    deck = {
        "status": "done",
        "commander": {"original_name": "Test Commander"},
        "deck": [],
        "bracket": 2,
        "bracket_label": "Core",
        "built_at": "2026-08-26T00:00:00",
        "last_measure": {
            "simulation": {
                "power_profile": {
                    "bracket_estimate": bracket_estimate,
                    "bracket_label": "Core",
                    "bracket_plays_up": plays_up,
                }
            }
        },
    }
    (job_dir / "deck.json").write_text(json.dumps(deck), encoding="utf-8")
    return job_dir


def test_measured_plays_up_true_is_surfaced(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "RENDER_DIR", tmp_path)
    _write_deck(tmp_path, plays_up=True)
    entry = client.get("/api/decks").json()[0]
    assert entry["measured_bracket"] == 2
    assert entry["measured_plays_up"] is True


def test_measured_plays_up_false_is_surfaced_not_omitted(tmp_path, monkeypatch):
    """False must reach the client explicitly — a badge checking `entry.measured_plays_up`
    truthily needs the key to actually be False, not simply absent-and-falsy-by-luck."""
    monkeypatch.setattr(server, "RENDER_DIR", tmp_path)
    _write_deck(tmp_path, plays_up=False)
    entry = client.get("/api/decks").json()[0]
    assert entry["measured_plays_up"] is False


def test_no_measurement_yet_defaults_to_false(tmp_path, monkeypatch):
    """A deck never measured has no `last_measure` at all — must degrade cleanly, not raise."""
    monkeypatch.setattr(server, "RENDER_DIR", tmp_path)
    job_dir = tmp_path / _JOB_ID
    job_dir.mkdir()
    deck = {
        "status": "done", "commander": {"original_name": "X"}, "deck": [],
        "bracket": 2, "bracket_label": "Core", "built_at": "2026-08-26T00:00:00",
    }
    (job_dir / "deck.json").write_text(json.dumps(deck), encoding="utf-8")
    entry = client.get("/api/decks").json()[0]
    assert entry["measured_bracket"] is None
    assert entry["measured_plays_up"] is False
