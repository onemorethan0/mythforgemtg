"""The deck lifecycle routes that had no tests: get, duplicate, delete, batch delete, the decklist
export, and the playstyle catalogue. Offline: RENDER_DIR/ART_DIR are tmp dirs and the in-memory
job store is replaced per test, so nothing touches the real renders."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import server
from api import state

client = TestClient(server.app)

JOB = "0123456789abcdef"
JOB2 = "fedcba9876543210"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MYTHSUITE_DIR", str(tmp_path / "suite"))
    monkeypatch.setattr(state, "RENDER_DIR", tmp_path / "renders")
    monkeypatch.setattr(state, "ART_DIR", tmp_path / "art")
    (tmp_path / "renders").mkdir()
    (tmp_path / "art").mkdir()
    with patch.dict(state._jobs, {}, clear=True), patch.dict(state._progress, {}, clear=True):
        yield tmp_path


def _deck(**kw):
    base = {"status": "done",
            "commander": {"original_name": "Atraxa, Praetors' Voice", "themed_name": "The Four Sovereigns"},
            "deck": [{"original_name": "Sol Ring", "quantity": 1}, {"original_name": "Island", "quantity": 12}],
            "built_at": 1.0}
    base.update(kw)
    return base


def _write(tmp, job=JOB, **kw):
    d = tmp / "renders" / job
    d.mkdir(parents=True)
    (d / "deck.json").write_text(json.dumps(_deck(**kw)), encoding="utf-8")
    (d / "extra.txt").write_text("render", encoding="utf-8")
    return d


# -- get ------------------------------------------------------------------------------------------

def test_get_deck_rejects_a_malformed_job_id_and_an_unknown_one():
    assert client.get("/api/deck/not-a-job-id").status_code == 404
    assert client.get(f"/api/deck/{JOB}").status_code == 404


def test_get_deck_returns_a_deck_from_disk(_isolated):
    _write(_isolated)
    r = client.get(f"/api/deck/{JOB}")
    assert r.status_code == 200
    assert r.json()["commander"]["original_name"] == "Atraxa, Praetors' Voice"


def test_get_deck_while_building_or_failed_is_a_409():
    state._jobs[JOB] = {"status": "building", "commander": {}}
    assert client.get(f"/api/deck/{JOB}").status_code == 409
    state._jobs[JOB2] = {"status": "error", "error": "boom", "commander": {}}
    r = client.get(f"/api/deck/{JOB2}")
    assert r.status_code == 409 and "boom" in r.json()["detail"]


def test_get_deck_never_leaks_the_internal_cancel_event():
    import threading
    state._jobs[JOB] = {"status": "done", **_deck(), "cancel_event": threading.Event()}
    r = client.get(f"/api/deck/{JOB}")
    assert r.status_code == 200 and "cancel_event" not in r.json()


# -- duplicate -------------------------------------------------------------------------------------

def test_duplicate_copies_the_whole_directory_under_a_new_id(_isolated):
    src = _write(_isolated)
    r = client.post(f"/api/deck/{JOB}/duplicate")
    assert r.status_code == 200
    new = r.json()["new_job_id"]
    assert new != JOB and len(new) == 16 and r.json()["themed_name"] == "The Four Sovereigns"
    dst = _isolated / "renders" / new
    assert (dst / "extra.txt").read_text(encoding="utf-8") == "render"       # renders came along
    data = json.loads((dst / "deck.json").read_text(encoding="utf-8"))
    assert data["is_copy"] is True and data["copied_from"] == JOB
    assert json.loads((src / "deck.json").read_text(encoding="utf-8")).get("is_copy") is None   # source untouched
    assert state._jobs[new]["copied_from"] == JOB


def test_duplicate_of_an_unknown_or_unfinished_deck_fails_cleanly(_isolated):
    assert client.post(f"/api/deck/{JOB}/duplicate").status_code == 404
    _write(_isolated, job=JOB2, status="building")
    assert client.post(f"/api/deck/{JOB2}/duplicate").status_code == 400
    assert client.post("/api/deck/../../etc/duplicate").status_code in (404, 405)


# -- delete ------------------------------------------------------------------------------------------

def test_delete_removes_the_directory_and_the_in_memory_job(_isolated):
    d = _write(_isolated)
    state._jobs[JOB] = _deck()
    state._progress[JOB] = ["x"]
    r = client.delete(f"/api/deck/{JOB}")
    assert r.status_code == 200 and r.json() == {"ok": True, "job_id": JOB}
    assert not d.exists() and JOB not in state._jobs and JOB not in state._progress


def test_delete_also_clears_that_jobs_generated_art(_isolated):
    _write(_isolated)
    art = _isolated / "art" / f"theme_{JOB[:8]}"
    art.mkdir()
    other = _isolated / "art" / "theme_ffffffff"
    other.mkdir()
    assert client.delete(f"/api/deck/{JOB}").status_code == 200
    assert not art.exists() and other.exists()


def test_delete_refuses_a_deck_that_is_still_building(_isolated):
    d = _write(_isolated)
    state._jobs[JOB] = {"status": "building"}
    assert client.delete(f"/api/deck/{JOB}").status_code == 409
    assert d.exists()


def test_delete_rejects_a_malformed_id_before_touching_the_disk(_isolated):
    keep = _isolated / "renders" / "keep"
    keep.mkdir()
    assert client.delete("/api/deck/keep").status_code == 404
    assert keep.exists()


def test_delete_batch_reports_deleted_and_skipped(_isolated):
    _write(_isolated, job=JOB)
    _write(_isolated, job=JOB2)
    state._jobs[JOB2] = {"status": "building"}
    r = client.post("/api/decks/delete-batch", json={"job_ids": [JOB, JOB2]})
    assert r.status_code == 200
    assert r.json() == {"deleted": [JOB], "skipped": [JOB2]}
    assert not (_isolated / "renders" / JOB).exists() and (_isolated / "renders" / JOB2).exists()


# -- decklist export -----------------------------------------------------------------------------------

def test_decklist_export_round_trips_original_names_and_quantities(_isolated):
    _write(_isolated)
    r = client.get(f"/api/deck/{JOB}/export/decklist")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    lines = r.text.splitlines()
    assert lines[0] == "Commander: Atraxa, Praetors' Voice"
    assert "1 Sol Ring" in lines and "12 Island" in lines
    assert 'filename="Atraxa__Praetors__Voice_decklist.txt"' in r.headers["content-disposition"]


def test_decklist_export_is_not_commander_headed_for_a_non_commander_deck(_isolated):
    _write(_isolated, is_commander_deck=False)
    lines = client.get(f"/api/deck/{JOB}/export/decklist").text.splitlines()
    assert not any(l.startswith("Commander:") for l in lines)
    assert "1 Atraxa, Praetors' Voice" in lines          # the display face re-imports as a maindeck card


def test_decklist_export_marks_unresolved_cards_as_comments(_isolated):
    _write(_isolated, import_unresolved=["Mystery Card", "Another"])
    text = client.get(f"/api/deck/{JOB}/export/decklist").text
    assert "# 2 card(s) from the source could not be matched" in text
    assert "# Mystery Card" in text and "# Another" in text


def test_export_of_an_unbuilt_or_empty_deck_is_refused(_isolated):
    assert client.get(f"/api/deck/{JOB}/export/decklist").status_code == 404
    _write(_isolated, job=JOB2, deck=[])
    assert client.get(f"/api/deck/{JOB2}/export/decklist").status_code == 409
    state._jobs[JOB] = {"status": "building"}
    assert client.get(f"/api/deck/{JOB}/export/decklist").status_code == 409


def test_a_single_custom_card_exports_with_an_empty_deck_list(_isolated):
    _write(_isolated, deck=[], mode="single_card")
    r = client.get(f"/api/deck/{JOB}/export/decklist")
    assert r.status_code == 200 and "Commander: Atraxa, Praetors' Voice" in r.text


# -- playstyles -------------------------------------------------------------------------------------------------

def test_playstyles_endpoint_lists_every_playstyle():
    import playstyle
    r = client.get("/api/playstyles")
    assert r.status_code == 200
    body = r.json()
    keys = [p["key"] for p in body] if isinstance(body, list) else list(body)
    assert set(playstyle.PLAYSTYLES) <= set(keys)


# -- batch delete must validate ids like the single delete does ---------------------------------------

def test_delete_batch_never_deletes_outside_the_renders_directory(_isolated):
    """`delete_deck` calls _require_job_id because it rmtree's a path built from the id; the batch
    route built the same path from each id with NO check, so '../victim' removed a sibling folder."""
    victim = _isolated / "victim"
    victim.mkdir()
    (victim / "precious.txt").write_text("keep", encoding="utf-8")
    sub = _isolated / "renders" / "plain-dir"
    sub.mkdir()
    r = client.post("/api/decks/delete-batch",
                    json={"job_ids": ["../victim", "plain-dir", "", "..", JOB]})
    assert r.status_code == 200
    assert victim.exists() and (victim / "precious.txt").exists()
    assert sub.exists()
    assert r.json()["deleted"] in ([], [JOB])         # a well-formed id that never existed is harmless
    assert set(r.json()["skipped"]) >= {"../victim", "plain-dir", "", ".."}


# -- stated bracket -------------------------------------------------------------------------------

def test_stated_bracket_is_saved_read_back_and_cleared(_isolated):
    _write(_isolated)
    r = client.post(f"/api/deck/{JOB}/stated-bracket", json={"stated_bracket": 2})
    assert r.status_code == 200 and r.json()["stated_bracket"] == 2
    disk = json.loads((_isolated / "renders" / JOB / "deck.json").read_text(encoding="utf-8"))
    assert disk["stated_bracket"] == 2
    assert client.get(f"/api/deck/{JOB}").json()["stated_bracket"] == 2
    client.post(f"/api/deck/{JOB}/stated-bracket", json={"stated_bracket": None})
    disk = json.loads((_isolated / "renders" / JOB / "deck.json").read_text(encoding="utf-8"))
    assert disk["stated_bracket"] is None


def test_stated_bracket_rejects_out_of_range_and_unknown_decks(_isolated):
    _write(_isolated)
    assert client.post(f"/api/deck/{JOB}/stated-bracket", json={"stated_bracket": 6}).status_code == 422
    assert client.post(f"/api/deck/{JOB2}/stated-bracket", json={"stated_bracket": 3}).status_code == 404
    assert client.post("/api/deck/nope/stated-bracket", json={"stated_bracket": 3}).status_code in (400, 404)
