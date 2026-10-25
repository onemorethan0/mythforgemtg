"""Exports are sent as one whole Response, not StreamingResponse(io.BytesIO(...)).

Iterating a BytesIO yields it line by line, so a 12 MB ZIP left the server as ~46k
newline-split chunks and took ~55 s to download though it was built in 0.4 s (2026-10-25).
A whole-body Response carries Content-Length; the line-split stream did not. Offline.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

import server
from api import state

client = TestClient(server.app)
_JOB = "0123456789abcdef"


def test_decklist_export_is_a_whole_response(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "RENDER_DIR", tmp_path)
    job_dir = tmp_path / _JOB
    job_dir.mkdir()
    deck = {"status": "done",
            "commander": {"original_name": "Test Commander", "name": "Test Commander"},
            "deck": [{"original_name": "Sol Ring", "name": "Sol Ring", "quantity": 1},
                     {"original_name": "Forest", "name": "Forest", "quantity": 30}]}
    (job_dir / "deck.json").write_text(json.dumps(deck), encoding="utf-8")
    r = client.get(f"/api/deck/{_JOB}/export/decklist")
    assert r.status_code == 200
    assert int(r.headers["content-length"]) == len(r.content)
    assert "30 Forest" in r.text
