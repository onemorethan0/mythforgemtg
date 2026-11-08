"""Forge's pod check proxy (D4): library decks and pasted lists become engine seats."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import server
from api import routes_strength, state

client = TestClient(server.app)
JOB, JOB2 = "0123456789abcdef", "fedcba9876543210"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "RENDER_DIR", tmp_path / "renders")
    (tmp_path / "renders").mkdir()
    with patch.dict(state._jobs, {}, clear=True):
        yield tmp_path


def _write(tmp, job, commander):
    d = tmp / "renders" / job
    d.mkdir(parents=True)
    deck = {"status": "done",
            "commander": {"original_name": commander, "themed_name": ""},
            "deck": [{"original_name": "Sol Ring", "quantity": 1},
                     {"original_name": "Forest", "quantity": 98}]}
    (d / "deck.json").write_text(json.dumps(deck), encoding="utf-8")


class _Resp:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def test_seats_are_this_deck_then_library_decks_then_pasted_lists(_isolated):
    _write(_isolated, JOB, "Krenko, Mob Boss")
    _write(_isolated, JOB2, "Doran, the Siege Tower")
    sent = {}

    def fake_post(url, json=None, timeout=None):
        sent.update(url=url, body=json)
        return _Resp({"seats": [], "fit": {"fun": True, "checks": [], "summary": "ok"}})

    with patch.object(routes_strength.requests, "post", fake_post):
        r = client.post(f"/api/deck/{JOB}/pod-fit", json={"seats": [
            {"job_id": JOB2}, {"text": "Commander: Ghired\n1 Sol Ring", "name": "Sam's Ghired"}]})
    assert r.status_code == 200
    assert sent["url"].endswith("/pod-fit")
    names = [d["name"] for d in sent["body"]["decks"]]
    assert names == ["Krenko, Mob Boss", "Doran, the Siege Tower", "Sam's Ghired"]
    assert "Sol Ring" in sent["body"]["decks"][0]["deck"]


def test_an_empty_seat_or_unknown_deck_is_refused(_isolated):
    _write(_isolated, JOB, "Krenko, Mob Boss")
    assert client.post(f"/api/deck/{JOB}/pod-fit", json={"seats": [{}]}).status_code == 400
    assert client.post(f"/api/deck/{JOB}/pod-fit",
                       json={"seats": [{"job_id": JOB2}]}).status_code == 404


def test_engine_down_is_a_503(_isolated):
    _write(_isolated, JOB, "Krenko, Mob Boss")

    def boom(*a, **k):
        raise ConnectionError("refused")

    with patch.object(routes_strength.requests, "post", boom):
        r = client.post(f"/api/deck/{JOB}/pod-fit", json={"seats": [{"text": "1 Sol Ring"}]})
    assert r.status_code == 503
