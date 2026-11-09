"""Forge's matchups proxy (B35): the measured bracket goes to the engine, and the result is
cached per decklist."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import server
from api import routes_strength, state

client = TestClient(server.app)
JOB = "0123456789abcdef"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "RENDER_DIR", tmp_path / "renders")
    (tmp_path / "renders").mkdir()
    with patch.dict(state._jobs, {}, clear=True):
        yield tmp_path


def _write(tmp, **extra):
    d = tmp / "renders" / JOB
    d.mkdir(parents=True, exist_ok=True)
    deck = {"status": "done",
            "commander": {"original_name": "Krenko, Mob Boss", "themed_name": ""},
            "deck": [{"original_name": "Sol Ring", "quantity": 1},
                     {"original_name": "Mountain", "quantity": 98}], **extra}
    (d / "deck.json").write_text(json.dumps(deck), encoding="utf-8")
    return d / "deck.json"


class _Resp:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


ENGINE = {"bracket": 3, "games_each": 120, "matchups": [], "weak_against": ["go-wide tokens"],
          "favoured_against": [], "fidelity": "directional"}


def test_scout_sends_the_measured_bracket_and_caches_per_decklist(_isolated):
    path = _write(_isolated, last_measure={"simulation": {"power_profile": {"bracket_estimate": 3}}})
    sent = {}

    def fake_post(url, json=None, timeout=None):
        sent.update(url=url, body=json)
        return _Resp(ENGINE)

    assert client.get(f"/api/deck/{JOB}/matchups").json() == {"cached": False}
    with patch.object(routes_strength.requests, "post", fake_post):
        r = client.post(f"/api/deck/{JOB}/matchups")
    assert r.status_code == 200 and r.json()["weak_against"] == ["go-wide tokens"]
    assert sent["url"].endswith("/matchups") and sent["body"]["bracket"] == 3
    assert "Sol Ring" in sent["body"]["deck"]
    got = client.get(f"/api/deck/{JOB}/matchups").json()
    assert got["cached"] is True and got["weak_against"] == ["go-wide tokens"]
    # an edited list misses the cache
    state._jobs.clear()
    disk = json.loads(path.read_text(encoding="utf-8"))
    disk["deck"].append({"original_name": "Lightning Bolt", "quantity": 1})
    path.write_text(json.dumps(disk), encoding="utf-8")
    assert client.get(f"/api/deck/{JOB}/matchups").json() == {"cached": False}


def test_engine_down_is_a_503(_isolated):
    _write(_isolated)

    def boom(*a, **k):
        raise ConnectionError("refused")

    with patch.object(routes_strength.requests, "post", boom):
        assert client.post(f"/api/deck/{JOB}/matchups").status_code == 503
