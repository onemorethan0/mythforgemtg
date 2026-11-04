"""mentor / breakdown / card-impact / mentor-feedback routes (docs/BACKLOG.md B7). The engine helpers
(`_gauntlet_*`) are faked; what is under test is Forge's own logic: job lookup, 404/400/503 mapping,
what is forwarded to the engine, rate limiting, and the breakdown cache."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import server
from api import routes_strength as rs
from api import state
from tests.test_strength_routes import JOB, _Resp, _write_deck  # noqa: F401  (autouse fixture is re-imported below)
from tests.test_strength_routes import _isolated  # noqa: F401

client = TestClient(server.app)


def _post(path, body=None):
    return client.post(f"/api/deck/{JOB}/{path}", json=body or {})


# -- mentor ----------------------------------------------------------------------------------------------------

def test_mentor_404_for_unknown_deck_and_422_for_empty_question(_isolated):
    assert _post("mentor", {"question": "why?"}).status_code == 404
    _write_deck(_isolated)
    assert _post("mentor", {"question": ""}).status_code == 422


def test_mentor_400_for_a_single_card_build(_isolated):
    _write_deck(_isolated, deck=[])
    assert _post("mentor", {"question": "hi"}).status_code == 400


def test_mentor_forwards_original_names_partners_and_trimmed_question(_isolated):
    _write_deck(_isolated)
    seen = {}

    def fake(commander, deck, question, **kw):
        seen.update(commander=commander, deck=deck, question=question, kw=kw)
        return {"answer": "ok", "gated": True}

    with patch.object(rs, "_gauntlet_mentor_chat", fake):
        r = _post("mentor", {"question": "  is it fast?  ", "model": "qwen3:8b"})
    assert r.status_code == 200 and r.json()["answer"] == "ok"
    assert seen["question"] == "is it fast?"
    assert seen["commander"] == {"name": "Tymna the Weaver"}            # original, not the themed name
    assert seen["deck"] == [{"name": "Sol Ring", "quantity": 1}, {"name": "Island", "quantity": 12}]
    assert seen["kw"]["partners"] == [{"name": "Thrasios, Triton Hero"}]
    assert seen["kw"]["model"] == "qwen3:8b"


def test_mentor_maps_engine_down_and_engine_error(_isolated):
    _write_deck(_isolated)
    with patch.object(rs, "_gauntlet_mentor_chat", lambda *a, **k: None):
        assert _post("mentor", {"question": "q"}).status_code == 503
    with patch.object(rs, "_gauntlet_mentor_chat", lambda *a, **k: {"error": "run fetch-rules"}):
        r = _post("mentor", {"question": "q"})
    assert r.status_code == 400 and "fetch-rules" in r.json()["detail"]


def test_mentor_is_rate_limited(_isolated, monkeypatch):
    _write_deck(_isolated)
    monkeypatch.setattr(rs, "_RATE_LIMIT_CHAT_REQUESTS", 2)
    with patch.object(rs, "_gauntlet_mentor_chat", lambda *a, **k: {"answer": "ok"}):
        codes = [_post("mentor", {"question": "q"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_bad_job_id_is_rejected_before_any_lookup(_isolated):
    r = client.post("/api/deck/not-a-job/mentor", json={"question": "q"})
    assert r.status_code in (400, 404, 422)


# -- card-impact --------------------------------------------------------------------------------------------------

def test_card_impact_forwards_the_stripped_card_and_maps_errors(_isolated):
    _write_deck(_isolated)
    seen = {}

    def fake(commander, deck, card, **kw):
        seen["card"] = card
        return {"verdict": "helps"}

    with patch.object(rs, "_gauntlet_card_impact", fake):
        r = _post("card-impact", {"card": "  Rhystic Study "})
    assert r.status_code == 200 and seen["card"] == "Rhystic Study"
    with patch.object(rs, "_gauntlet_card_impact", lambda *a, **k: None):
        assert _post("card-impact", {"card": "X"}).status_code == 503
    with patch.object(rs, "_gauntlet_card_impact", lambda *a, **k: {"error": "off-colour"}):
        r = _post("card-impact", {"card": "X"})
    assert r.status_code == 400 and r.json()["detail"] == "off-colour"


def test_card_impact_404_and_single_card_400(_isolated):
    assert _post("card-impact", {"card": "X"}).status_code == 404
    _write_deck(_isolated, deck=[])
    assert _post("card-impact", {"card": "X"}).status_code == 400


# -- breakdown: persisted, cached, refreshable --------------------------------------------------------------------

def test_breakdown_computes_persists_then_serves_from_cache(_isolated):
    path = _write_deck(_isolated)
    calls = []

    def fake(commander, deck, themes=None, partners=None):
        calls.append(1)
        return {"roles": {"ramp": 3}}

    with patch.object(rs, "_gauntlet_breakdown", fake):
        first = _post("breakdown")
        second = _post("breakdown")
        refreshed = client.post(f"/api/deck/{JOB}/breakdown?refresh=true")
    assert first.json()["cached"] is False and second.json()["cached"] is True
    assert refreshed.json()["cached"] is False
    assert len(calls) == 2                                         # first + refresh; the middle one was cached
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["breakdown"]["data"] == {"roles": {"ramp": 3}} and stored["breakdown"]["key"]


def test_breakdown_recomputes_when_the_decklist_changes(_isolated):
    path = _write_deck(_isolated)
    calls = []
    with patch.object(rs, "_gauntlet_breakdown", lambda *a, **k: calls.append(1) or {"x": 1}):
        _post("breakdown")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["deck"].append({"original_name": "Arcane Signet", "quantity": 1})
        path.write_text(json.dumps(data), encoding="utf-8")
        assert _post("breakdown").json()["cached"] is False
    assert len(calls) == 2


def test_breakdown_errors(_isolated):
    assert _post("breakdown").status_code == 404
    _write_deck(_isolated)
    with patch.object(rs, "_gauntlet_breakdown", lambda *a, **k: None):
        assert _post("breakdown").status_code == 503
    with patch.object(rs, "_gauntlet_breakdown", lambda *a, **k: {"error": "bad"}):
        assert _post("breakdown").status_code == 400


def test_breakdown_400_for_a_single_card_build(_isolated):
    _write_deck(_isolated, deck=[])
    assert _post("breakdown").status_code == 400


# -- mentor feedback ----------------------------------------------------------------------------------------------

def test_feedback_passes_the_rating_through(_isolated):
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen.update(url=url, body=json)
        return _Resp(body={"ok": True})

    with patch.object(rs.requests, "post", fake_post):
        r = _post("mentor/feedback", {"turn_id": "t1", "rating": "up", "note": "good"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert seen["url"].endswith("/mentor/feedback")
    assert seen["body"] == {"turn_id": "t1", "rating": "up", "note": "good"}


def test_feedback_error_mapping(_isolated):
    body = {"turn_id": "t1", "rating": "up"}
    with patch.object(rs.requests, "post", lambda *a, **k: _Resp(status=400, body={"detail": "bad rating"})):
        r = _post("mentor/feedback", body)
    assert r.status_code == 400 and r.json()["detail"] == "bad rating"
    with patch.object(rs.requests, "post", lambda *a, **k: _Resp(status=400, raises=True)):
        assert _post("mentor/feedback", body).json()["detail"] == "invalid feedback"
    with patch.object(rs.requests, "post", lambda *a, **k: _Resp(status=500)):
        assert _post("mentor/feedback", body).status_code == 502

    def boom(*a, **k):
        raise ConnectionError("down")

    with patch.object(rs.requests, "post", boom):
        assert _post("mentor/feedback", body).status_code == 503


def test_feedback_rejects_an_empty_turn_id(_isolated):
    assert _post("mentor/feedback", {"turn_id": "", "rating": "up"}).status_code == 422
