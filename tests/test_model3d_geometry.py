"""model3d GLB -> STL with real geometry (docs/BACKLOG.md B7). trimesh is optional and not installed in
CI, so this whole file skips without it; the ComfyUI plumbing tests live in test_model3d_pure.py."""
from __future__ import annotations

import pytest

trimesh = pytest.importorskip("trimesh")

import model3d  # noqa: E402

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
