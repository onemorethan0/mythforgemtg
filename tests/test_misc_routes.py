"""routes_misc: face upload validation, face-method probe cache, health, frame config (docs/BACKLOG.md B7).
The ComfyUI / LLM probes are faked; what is under test is Forge's own gating and caching."""
from __future__ import annotations

import io
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import cc_frames
import face_ref
import server
from api import routes_misc as rm

client = TestClient(server.app)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    rm._probe_cache.update(ts=0, data=None)
    monkeypatch.delenv("MYTHFORGE_CC_DIR", raising=False)


def _png(size=(4, 4)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 10, 10)).save(buf, "PNG")
    return buf.getvalue()


def _up(*files):
    return client.post("/api/upload-face", files=[("files", f) for f in files])


# -- upload-face -------------------------------------------------------------------------------------------

def test_upload_face_accepts_a_real_image_and_reports_the_method(monkeypatch):
    saved = {}
    monkeypatch.setattr(face_ref, "save_face_images",
                        lambda fl, key: saved.update(n=len(fl), key=key) or ["p1"] * len(fl))
    rm._probe_cache.update(ts=__import__("time").time(), data={"face_method": "PuLID"})
    r = _up(("a.png", _png(), "image/png"), ("b.png", _png(), "image/png"))
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2 and body["face_method"] == "PuLID" and len(body["face_key"]) == 16
    assert saved["n"] == 2 and saved["key"] == body["face_key"]


def test_upload_face_rejects_a_non_image_by_magic_bytes(monkeypatch):
    monkeypatch.setattr(face_ref, "save_face_images", lambda *a: pytest.fail("must not save"))
    r = _up(("evil.png", b"MZ\x90\x00 not an image", "image/png"))
    assert r.status_code == 400 and "not a recognized image" in r.json()["detail"]


def test_upload_face_rejects_a_valid_header_with_a_corrupt_body(monkeypatch):
    monkeypatch.setattr(face_ref, "save_face_images", lambda *a: pytest.fail("must not save"))
    r = _up(("bad.png", b"\x89PNG\r\n\x1a\n" + b"garbage" * 5, "image/png"))
    assert r.status_code == 400 and "corrupt" in r.json()["detail"]


def test_upload_face_rejects_empty_file_and_too_many_files(monkeypatch):
    monkeypatch.setattr(face_ref, "save_face_images", lambda *a: pytest.fail("must not save"))
    assert _up(("e.png", b"", "image/png")).status_code == 400
    many = [("p%d.png" % i, _png(), "image/png") for i in range(16)]
    r = _up(*many)
    assert r.status_code == 400 and "Maximum 15" in r.json()["detail"]


def test_upload_face_without_files_is_rejected():
    assert client.post("/api/upload-face").status_code == 422


def test_upload_face_rejects_oversize_file(monkeypatch):
    monkeypatch.setattr(face_ref, "save_face_images", lambda *a: pytest.fail("must not save"))
    big = _png() + b"\0" * (20 * 1024 * 1024)
    assert _up(("big.png", big, "image/png")).status_code == 413


# -- face-method probe -----------------------------------------------------------------------------------------

def test_face_method_reports_offline_and_caches(monkeypatch):
    calls = []

    def down(url, timeout=None):
        calls.append(url)
        raise ConnectionError

    monkeypatch.setattr(rm.requests, "get", down)
    first = client.get("/api/face-method").json()
    second = client.get("/api/face-method").json()
    assert first["comfyui_offline"] is True and first["available"] is False and first == second
    assert len(calls) == 1                                           # second answer came from the cache


def test_face_method_online_reads_the_generator(monkeypatch):
    monkeypatch.setattr(rm.requests, "get", lambda *a, **k: object())

    class Gen:
        face_method_label, face_method = "InstantID", "instantid"

    monkeypatch.setattr(rm, "ImageGen", type("IG", (Gen,), {"list_checkpoints": staticmethod(
        lambda: {"schnell": ["s"], "dev": []})}))
    body = client.get("/api/face-method").json()
    assert body["face_method"] == "InstantID" and body["available"] is True
    assert body["has_schnell"] is True and body["has_dev"] is False


def test_face_method_error_is_reported_not_raised_and_not_cached(monkeypatch):
    monkeypatch.setattr(rm.requests, "get", lambda *a, **k: object())

    def boom():
        raise RuntimeError("comfy exploded")

    monkeypatch.setattr(rm.ImageGen, "list_checkpoints", staticmethod(boom))
    body = client.get("/api/face-method").json()
    assert body["available"] is False and "comfy exploded" in body["error"]
    assert rm._probe_cache["data"] is None


# -- health -------------------------------------------------------------------------------------------------------

def test_health_reports_each_service_independently(monkeypatch):
    class R:
        status_code = 200

    monkeypatch.setattr(rm.requests, "get", lambda *a, **k: R())
    monkeypatch.setattr("themer.installed_models", lambda timeout=2: [])
    b = client.get("/api/health").json()
    assert b["comfyui"] == "up" and b["llm"] == "down" and b["ollama"] == b["llm"]

    R.status_code = 500
    monkeypatch.setattr("themer.installed_models", lambda timeout=2: ["qwen3:14b"])
    b = client.get("/api/health").json()
    assert b["comfyui"] == "down" and b["llm"] == "up"

    def refuse(*a, **k):
        raise ConnectionError

    monkeypatch.setattr(rm.requests, "get", refuse)
    assert client.get("/api/health").json()["comfyui"] == "down"


# -- frame config ---------------------------------------------------------------------------------------------------

def test_frame_config_env_var_overrides_the_ui_setting(monkeypatch):
    monkeypatch.setenv("MYTHFORGE_CC_DIR", "C:/somewhere")
    monkeypatch.setattr(cc_frames, "set_cc_dir", lambda p: pytest.fail("env var must win"))
    r = client.post("/api/frame-config", json={"cc_dir": "D:/other"}).json()
    assert r["ok"] is False and "MYTHFORGE_CC_DIR" in r["error"]
    assert client.get("/api/frame-config").json()["from_env"] is True


def test_frame_config_persists_and_validates_the_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(cc_frames, "_CONFIG_FILE", tmp_path / "cc_config.json")
    r = client.post("/api/frame-config", json={"cc_dir": str(tmp_path)}).json()
    assert r["ok"] is True and r["valid"] is False and "img/frames" in r["note"]
    (tmp_path / "img" / "frames").mkdir(parents=True)
    r = client.post("/api/frame-config", json={"cc_dir": str(tmp_path)}).json()
    assert r["valid"] is True and r["note"] == ""
    assert client.get("/api/frame-config").json()["cc_dir"] == str(tmp_path)
    cleared = client.post("/api/frame-config", json={"cc_dir": ""}).json()
    assert cleared["valid"] is False and cleared["note"] == ""     # clearing is not an error


def test_frame_styles_builtin_is_always_available_and_m15_follows_the_install(monkeypatch):
    monkeypatch.setattr(cc_frames, "is_available", lambda style="m15": style == "m15")
    styles = {s["key"]: s for s in client.get("/api/frame-styles").json()["styles"]}
    assert styles["builtin"]["available"] and styles["m15"]["available"]
    assert not styles["m15_fullart"]["available"] and "MYTHFORGE_CC_DIR" in styles["m15_fullart"]["note"]
