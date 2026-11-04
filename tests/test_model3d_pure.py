"""model3d: the ComfyUI plumbing and the GLB -> STL conversion, with real geometry (docs/BACKLOG.md B7).
ComfyUI is faked at `requests`; the mesh work runs for real through trimesh."""
from __future__ import annotations

import pytest
import trimesh

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


# -- GLB -> STL, real geometry ----------------------------------------------------------------------------------------

def _glb(path, mesh):
    trimesh.Scene([mesh]).export(str(path))


def test_stl_is_scaled_to_the_target_seated_on_the_bed_and_centred(tmp_path):
    box = trimesh.creation.box(extents=(2.0, 1.0, 0.5))
    box.apply_translation((5, -3, 7))                         # far from the origin on purpose
    glb, stl = tmp_path / "m.glb", tmp_path / "out" / "m.stl"
    _glb(glb, box)
    msgs = []
    out = model3d.convert_glb_to_stl(glb, stl, progress_cb=msgs.append, target_mm=60)
    assert out == stl and stl.exists() and msgs == ["Converting GLB → STL…"]
    m = trimesh.load(str(stl))
    assert max(m.extents) == pytest.approx(60.0, rel=1e-3)
    assert m.extents[1] == pytest.approx(30.0, rel=1e-3)      # proportions kept
    assert m.bounds[0][2] == pytest.approx(0.0, abs=1e-6)     # on the bed
    assert (m.bounds[0][0] + m.bounds[1][0]) / 2 == pytest.approx(0.0, abs=1e-6)
    assert m.is_watertight and m.volume > 0                   # winding fixed: positive volume


def test_stl_with_no_target_keeps_the_original_size(tmp_path):
    glb, stl = tmp_path / "m.glb", tmp_path / "m.stl"
    _glb(glb, trimesh.creation.box(extents=(2.0, 1.0, 0.5)))
    model3d.convert_glb_to_stl(glb, stl, target_mm=0)
    assert max(trimesh.load(str(stl)).extents) == pytest.approx(2.0, rel=1e-3)


def test_stl_merges_several_meshes_in_a_scene(tmp_path):
    a = trimesh.creation.box(extents=(1, 1, 1))
    b = trimesh.creation.box(extents=(1, 1, 1))
    b.apply_translation((3, 0, 0))
    glb, stl = tmp_path / "m.glb", tmp_path / "m.stl"
    trimesh.Scene([a, b]).export(str(glb))
    model3d.convert_glb_to_stl(glb, stl, target_mm=40)
    m = trimesh.load(str(stl))
    assert max(m.extents) == pytest.approx(40.0, rel=1e-3) and len(m.faces) == 24
