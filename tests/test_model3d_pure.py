"""model3d: the ComfyUI plumbing (docs/BACKLOG.md B7).
ComfyUI is faked at `requests`; nothing here needs trimesh (see test_model3d_geometry.py)."""
from __future__ import annotations

import pytest

import model3d


class _R:
    def __init__(self, status=200, body=None, text=""):
        self.status_code, self._b, self.text = status, body or {}, text

    def json(self):
        return self._b


# -- submit / wait -----------------------------------------------------------------------------------------------

def test_submit_returns_the_prompt_id_and_sends_the_workflow(monkeypatch):
    seen = {}

    def post(url, json=None, timeout=None):
        seen.update(url=url, body=json)
        return _R(200, {"prompt_id": "p-1"})

    monkeypatch.setattr(model3d.requests, "post", post)
    assert model3d._submit_workflow({"1": {}}, "http://c") == "p-1"
    assert seen["url"] == "http://c/prompt" and seen["body"]["prompt"] == {"1": {}} and seen["body"]["client_id"]


def test_submit_raises_with_the_status_when_rejected(monkeypatch):
    monkeypatch.setattr(model3d.requests, "post", lambda *a, **k: _R(400, text="bad node"))
    with pytest.raises(RuntimeError, match="400.*bad node"):
        model3d._submit_workflow({}, "http://c")


def _history(monkeypatch, entries):
    it = iter(entries)
    monkeypatch.setattr(model3d.requests, "get", lambda *a, **k: next(it))
    monkeypatch.setattr(model3d.time, "sleep", lambda s: None)


def test_wait_returns_outputs_once_completed(monkeypatch):
    done = {"p": {"status": {"completed": True}, "outputs": {"9": {"mesh": []}}}}
    _history(monkeypatch, [_R(200, {}), _R(200, {"p": {"status": {}}}), _R(200, done)])
    assert model3d._wait_for_completion("p", "http://c", timeout=60) == {"9": {"mesh": []}}


def test_wait_surfaces_the_execution_error_message(monkeypatch):
    err = {"p": {"status": {"status_str": "error",
                            "messages": [["execution_start", {}],
                                         ["execution_error", {"exception_message": "CUDA out of memory"}]]}}}
    _history(monkeypatch, [_R(200, err)])
    with pytest.raises(RuntimeError, match="CUDA out of memory"):
        model3d._wait_for_completion("p", "http://c", timeout=60)


def test_wait_tolerates_transient_poll_errors_then_times_out(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("blip")

    clock = iter(range(0, 1000, 20))
    monkeypatch.setattr(model3d.requests, "get", boom)
    monkeypatch.setattr(model3d.time, "sleep", lambda s: None)
    monkeypatch.setattr(model3d.time, "monotonic", lambda: next(clock))
    ticks = []
    with pytest.raises(RuntimeError, match="timed out"):
        model3d._wait_for_completion("p", "http://c", progress_cb=ticks.append, timeout=50)
    assert ticks and "Generating 3D mesh" in ticks[0]


# -- finding the GLB --------------------------------------------------------------------------------------------------

def test_find_glb_looks_in_the_output_dir_and_skips_missing_files(tmp_path, monkeypatch):
    monkeypatch.setattr(model3d, "_COMFY_OUTPUT_DIR", tmp_path)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.glb").write_bytes(b"x")
    assert model3d._find_glb_output({"1": {"mesh": [{"filename": "a.glb", "subfolder": "sub"}]}}) == tmp_path / "sub" / "a.glb"
    assert model3d._find_glb_output({"1": {"mesh": [{"filename": "ghost.glb", "subfolder": "sub"}]}}) is None
    assert model3d._find_glb_output({"1": {"images": [{"filename": "a.png", "subfolder": "sub"}]}}) is None
    assert model3d._find_glb_output({}) is None


def test_find_glb_accepts_file_path_outputs_as_str_or_dict(tmp_path, monkeypatch):
    monkeypatch.setattr(model3d, "_COMFY_OUTPUT_DIR", tmp_path / "nowhere")
    g = tmp_path / "m.GLB"
    g.write_bytes(b"x")
    assert model3d._find_glb_output({"1": {"file_path": [str(g)]}}) == g
    assert model3d._find_glb_output({"1": {"file_path": [{"value": str(g)}]}}) == g
    txt = tmp_path / "m.txt"
    txt.write_bytes(b"x")
    assert model3d._find_glb_output({"1": {"file_path": [str(txt)]}}) is None


def test_model_presence_check_reports_the_expected_dit_path(tmp_path, monkeypatch):
    monkeypatch.setattr(model3d, "_COMFY_OUTPUT_DIR", tmp_path / "output")
    assert model3d._check_hunyuan3d_models()["dit"] is False
    dit = tmp_path / "models" / "diffusion_models" / "hy3dgen"
    dit.mkdir(parents=True)
    (dit / model3d.HUNYUAN3D_DIT_MODEL).write_bytes(b"x")
    r = model3d._check_hunyuan3d_models()
    assert r["dit"] is True and r["all"] is True and r["dit_path"].endswith(model3d.HUNYUAN3D_DIT_MODEL)


def test_comfy_node_check_needs_the_loader_node_in_the_response(monkeypatch):
    monkeypatch.setattr(model3d, "_comfy_base", lambda: "http://c")
    monkeypatch.setattr(model3d.requests, "get",
                        lambda *a, **k: _R(200, {"Hy3DModelLoader": {"input": {}}}))
    assert model3d._check_comfy_nodes() is True
    monkeypatch.setattr(model3d.requests, "get", lambda *a, **k: _R(200, {"Other": {}}))
    assert model3d._check_comfy_nodes() is False
    monkeypatch.setattr(model3d.requests, "get", lambda *a, **k: _R(404))
    assert model3d._check_comfy_nodes() is False

    def down(*a, **k):
        raise ConnectionError

    monkeypatch.setattr(model3d.requests, "get", down)
    assert model3d._check_comfy_nodes() is False
