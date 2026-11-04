"""mana_pips.py: the CPU-only (no ComfyUI) pip composition and save/load path.

Drafted on a local model (qwen3:8b), then rewritten: the draft never imported the module
it monkeypatched (NameError at collection), assumed ``save_mana_pips`` took a different
argument order, and used ``tmp_path`` in a test that did not request the fixture.
"""
from __future__ import annotations

import pytest
from PIL import Image

import mana_pips


@pytest.fixture(autouse=True)
def _no_comfyui(monkeypatch):
    # Force the procedural silhouette; nothing here may reach a running ComfyUI.
    monkeypatch.setattr(mana_pips, "_flux_silhouette", lambda *a, **k: None)


def test_procedural_silhouette_is_deterministic():
    a = mana_pips._procedural_silhouette("dragon", "fire")
    b = mana_pips._procedural_silhouette("dragon", "fire")
    assert isinstance(a, Image.Image)
    assert a.size == b.size and a.mode == b.mode
    assert a.tobytes() == b.tobytes()


def test_radial_has_requested_size():
    img = mana_pips._radial(64, 20, 20, 30)
    assert img.size == (64, 64)


def test_compose_pip_is_rgba_at_requested_size():
    sil = mana_pips._procedural_silhouette("dragon", "fire")
    pip = mana_pips._compose_pip((255, 255, 255), sil)
    assert pip.mode == "RGBA"
    assert pip.size == (mana_pips.PIP_BASE, mana_pips.PIP_BASE)
    assert mana_pips._compose_pip((255, 0, 0), sil, size=48).size == (48, 48)


def test_extract_silhouette_returns_image_or_none():
    out = mana_pips._extract_silhouette(Image.new("L", (64, 64), 0))
    assert out is None or isinstance(out, Image.Image)


def test_generate_mana_pips_covers_every_colour():
    pips = mana_pips.generate_mana_pips("fire", "dragon")
    assert set(pips) == set(mana_pips.MANA_DISC)
    assert all(p.mode == "RGBA" for p in pips.values())


def test_save_then_load_roundtrip(tmp_path):
    out = tmp_path / "deck" / "pips"          # save must create missing parents
    paths, sil = mana_pips.save_mana_pips("fire", out, "dragon")
    assert set(paths) == set(mana_pips.MANA_DISC)
    assert (out / "_silhouette.png").exists()
    assert isinstance(sil, Image.Image)
    loaded = mana_pips.load_mana_pips(out)
    assert set(loaded) == set(mana_pips.MANA_DISC)
    assert all(img.mode == "RGBA" for img in loaded.values())


def test_load_from_empty_dir_is_empty(tmp_path):
    assert mana_pips.load_mana_pips(tmp_path) == {}
