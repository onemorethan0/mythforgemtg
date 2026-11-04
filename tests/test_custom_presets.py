"""Custom art-style presets: the storage helpers in image_gen and the three routes in routes_misc
(list / upsert / delete). The preset file is redirected to tmp_path, so the real one is untouched."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import image_gen
import server

client = TestClient(server.app)


@pytest.fixture
def presets_file(tmp_path, monkeypatch):
    p = tmp_path / "custom_presets.json"
    monkeypatch.setattr(image_gen, "_CUSTOM_PRESETS_PATH", str(p))
    return p


# -- storage -----------------------------------------------------------------------------------------

def test_load_of_a_missing_file_is_empty(presets_file):
    assert image_gen._load_custom_presets() == {}


def test_save_then_load_round_trips_unicode(presets_file):
    image_gen._save_custom_presets({"mine": {"label": "Mon style ✨", "loras": []}})
    assert image_gen._load_custom_presets()["mine"]["label"] == "Mon style ✨"
    assert not (presets_file.parent / "custom_presets.json.tmp").exists()        # temp file cleaned


def test_a_corrupt_file_loads_as_empty_instead_of_crashing(presets_file):
    presets_file.write_text("{ not json", encoding="utf-8")
    assert image_gen._load_custom_presets() == {}


@pytest.mark.parametrize("content", ["[]", '"a string"', "42", "null"])
def test_a_valid_json_file_that_is_not_an_object_loads_as_empty(presets_file, content):
    """A hand-edited '[]' parsed fine, then `merged.update([])`-style callers blew up."""
    presets_file.write_text(content, encoding="utf-8")
    assert image_gen._load_custom_presets() == {}
    assert isinstance(image_gen.get_all_presets(), dict)                     # the list endpoint survives


def test_a_failed_save_raises_and_leaves_the_old_file_intact(presets_file, monkeypatch):
    image_gen._save_custom_presets({"keep": {"label": "K"}})
    monkeypatch.setattr(image_gen._os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        image_gen._save_custom_presets({"new": {}})
    assert json.loads(presets_file.read_text(encoding="utf-8")) == {"keep": {"label": "K"}}
    assert not (presets_file.parent / "custom_presets.json.tmp").exists()


def test_upsert_and_delete(presets_file):
    image_gen.upsert_custom_preset("a", {"label": "A"})
    image_gen.upsert_custom_preset("a", {"label": "A2"})
    assert image_gen._load_custom_presets()["a"]["label"] == "A2"
    assert image_gen.delete_custom_preset("a") is True
    assert image_gen.delete_custom_preset("a") is False


def test_custom_presets_extend_but_the_builtins_stay(presets_file):
    image_gen.upsert_custom_preset("zzz_custom", {"label": "Z"})
    merged = image_gen.get_all_presets()
    assert "zzz_custom" in merged and set(image_gen._LORA_PRESETS) <= set(merged)


# -- routes --------------------------------------------------------------------------------------------

def test_post_requires_a_key_and_refuses_to_overwrite_a_builtin(presets_file):
    assert client.post("/api/art-styles/custom", json={"label": "x"}).status_code == 400
    assert client.post("/api/art-styles/custom", json={"key": "   "}).status_code == 400
    builtin = next(iter(image_gen._LORA_PRESETS))
    r = client.post("/api/art-styles/custom", json={"key": builtin})
    assert r.status_code == 400 and "built-in" in r.json()["detail"]
    assert not presets_file.exists()


def test_post_normalises_spaces_in_the_key_and_stores_the_preset(presets_file):
    r = client.post("/api/art-styles/custom", json={"key": " my cool style ", "label": "Cool",
                                                    "negative_prompt": "blurry"})
    assert r.status_code == 200 and r.json() == {"ok": True, "key": "my_cool_style"}
    stored = json.loads(presets_file.read_text(encoding="utf-8"))["my_cool_style"]
    assert stored["label"] == "Cool" and stored["negative_prompt"] == "blurry"
    assert "negative_prompt" not in client.post("/api/art-styles/custom", json={"key": "plain"}).json()
    assert "negative_prompt" not in json.loads(presets_file.read_text(encoding="utf-8"))["plain"]


@pytest.mark.parametrize("bad_key", [5, ["a"], {"x": 1}, True])
def test_post_with_a_non_string_key_is_a_400_not_a_500(presets_file, bad_key):
    assert client.post("/api/art-styles/custom", json={"key": bad_key}).status_code == 400


def test_post_reports_a_failed_write_instead_of_claiming_success(presets_file, monkeypatch):
    def boom(*a, **k):
        raise OSError("read-only")
    monkeypatch.setattr(image_gen, "_save_custom_presets", boom)
    r = client.post("/api/art-styles/custom", json={"key": "x"})
    assert r.status_code == 500 and "Could not save" in r.json()["detail"]


def test_delete_route(presets_file):
    client.post("/api/art-styles/custom", json={"key": "gone"})
    assert client.delete("/api/art-styles/custom/gone").json() == {"ok": True, "key": "gone"}
    assert client.delete("/api/art-styles/custom/gone").status_code == 404
    builtin = next(iter(image_gen._LORA_PRESETS))
    assert client.delete(f"/api/art-styles/custom/{builtin}").status_code == 400


def test_art_styles_list_includes_a_saved_custom_style(presets_file):
    client.post("/api/art-styles/custom", json={"key": "listed_style", "label": "Listed"})
    body = client.get("/api/art-styles").json()
    keys = [s["key"] for s in body] if isinstance(body, list) else list(body)
    assert "listed_style" in keys
