"""A running upgrade search can be stopped: the engine drops its queued work (AdviseCancelled),
and Forge's job reads `cancelled` at once instead of running to the end. Offline."""
import threading

import pytest

from mythgauntlet.ratings import advisor


def test_a_cancelled_search_raises_before_its_next_analysis(monkeypatch):
    calls = []
    monkeypatch.setattr(advisor, "analyze_deck", lambda *a, **k: calls.append(1) or "an")
    ev = threading.Event()
    ev.set()
    token = advisor._CANCEL.set(ev)
    try:
        with pytest.raises(advisor.AdviseCancelled):
            advisor._run_analyses([(None, None, 0, False, False)] * 3, None, 0)
    finally:
        advisor._CANCEL.reset(token)
    assert calls == []


def test_an_uncancelled_search_runs_every_analysis(monkeypatch):
    monkeypatch.setattr(advisor, "analyze_deck", lambda *a, **k: "an")
    out = advisor._run_analyses([(None, None, 0, False, False)] * 3, None, 0)
    assert out == ["an"] * 3


def test_cancel_stops_between_analyses(monkeypatch):
    ev = threading.Event()
    seen = []

    def fake(*a, **k):
        seen.append(1)
        ev.set()                      # the user presses Cancel during the first analysis
        return "an"
    monkeypatch.setattr(advisor, "analyze_deck", fake)
    token = advisor._CANCEL.set(ev)
    try:
        with pytest.raises(advisor.AdviseCancelled):
            advisor._run_analyses([(None, None, 0, False, False)] * 5, None, 0)
    finally:
        advisor._CANCEL.reset(token)
    assert len(seen) == 1


def test_advise_wrapper_scopes_the_cancel_token(monkeypatch):
    ev = threading.Event()
    seen = {}
    monkeypatch.setattr(advisor, "_advise", lambda *a, **k: seen.setdefault("tok", advisor._CANCEL.get()))
    advisor.advise(cancel=ev)
    assert seen["tok"] is ev
    assert advisor._CANCEL.get() is None          # restored afterwards


def test_forge_cancel_marks_the_job_and_tells_the_engine(monkeypatch):
    import asyncio
    from api import routes_strength as rs
    posted = []
    monkeypatch.setattr(rs.requests, "post", lambda url, **k: posted.append((url, k)))
    rs._jobs["adv1"] = {"status": "running", "kind": "advise"}
    try:
        assert asyncio.run(rs.advise_cancel("adv1")) == {"status": "cancelled"}
        assert asyncio.run(rs.advise_status("adv1")) == {"status": "cancelled"}
        assert posted and posted[0][1]["params"] == {"run_id": "adv1"}
        assert asyncio.run(rs.advise_cancel("adv1")) == {"status": "cancelled"}   # idempotent
        assert len(posted) == 1
    finally:
        rs._jobs.pop("adv1", None)


def test_a_cancelled_job_is_not_overwritten_by_a_late_result(monkeypatch):
    from api import routes_strength as rs
    job = {"status": "cancelled", "kind": "advise", "result": None, "error": None}
    rs._jobs["adv2"] = job
    monkeypatch.setattr(rs, "_gauntlet_advise", lambda *a, **k: {"suggestions": []})
    try:
        rs._run_advise_job("adv2", {}, [], None, [], [], False, {}, None)
        assert job["status"] == "cancelled" and job["result"] is None
    finally:
        rs._jobs.pop("adv2", None)
