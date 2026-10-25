"""`GET /api/deck/{job_id}/3d-status/{job_3d_id}` - the 3D progress stream.

An unknown 3D job id (never started, or lost in a server restart) used to hold the stream open
forever, polling every 0.5 s; a client saw a spinner that never ended. It now 404s at once,
like the build progress stream does for an unknown job. Offline: no ComfyUI, no 3D job.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import server

client = TestClient(server.app)


def test_unknown_3d_job_is_404_not_an_endless_stream():
    r = client.get("/api/deck/0123456789abcdef/3d-status/never-started")
    assert r.status_code == 404
