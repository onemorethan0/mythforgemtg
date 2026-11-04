"""api/models.py gen-settings helpers.

Drafted on a local model (qwen3:8b); the draft invented a dozen GenSettings fields
(model_speed, checkpoint, face_key ...) that do not exist. Rewritten against the real
fields in image_gen.GenSettings / api.models.GenSettingsModel.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from api import models
from image_gen import GenSettings


def test_resolve_none_gives_default_settings():
    assert models._resolve_gen_settings(None) == GenSettings()


def test_to_dict_none_is_empty():
    assert models._gen_settings_to_dict(None) == {}


def test_to_dict_strips_unset_fields():
    gs = models.GenSettingsModel(guidance=4.0, steps=20)
    assert models._gen_settings_to_dict(gs) == {"guidance": 4.0, "steps": 20}


def test_resolve_carries_set_fields_and_defaults_the_rest():
    gs = models.GenSettingsModel(guidance=2.5, seed_mode="fixed", seed=7, safe_mode=True)
    out = models._resolve_gen_settings(gs)
    assert out.guidance == 2.5
    assert out.seed_mode == "fixed" and out.seed == 7
    assert out.safe_mode is True
    assert out.steps == GenSettings().steps  # untouched -> default


def test_resolve_reusing_prefers_the_request():
    gs = models.GenSettingsModel(guidance=1.5)
    out = models._resolve_gen_settings_reusing(gs, {"gen_settings": {"guidance": 5.0}})
    assert out.guidance == 1.5


def test_resolve_reusing_falls_back_to_stored_deck_settings():
    out = models._resolve_gen_settings_reusing(None, {"gen_settings": {"guidance": 4.5, "steps": 12}})
    assert out.guidance == 4.5 and out.steps == 12


def test_resolve_reusing_with_nothing_stored_is_default():
    assert models._resolve_gen_settings_reusing(None, None) == GenSettings()
    assert models._resolve_gen_settings_reusing(None, {}) == GenSettings()


def test_dict_roundtrip_through_persistence():
    gs = models.GenSettingsModel(guidance=3.0, steps=9, style_variant="auto", enhance=True)
    stored = models._gen_settings_to_dict(gs)
    assert models._resolve_gen_settings_reusing(None, {"gen_settings": stored}) == models._resolve_gen_settings(gs)


def test_request_models_reject_wrong_types():
    with pytest.raises(ValidationError):
        models.SearchRequest(query=["not", "a", "string"])
    with pytest.raises(ValidationError):
        models.GenSettingsModel(steps="many")
    with pytest.raises(ValidationError):
        models.GenSettingsModel(guidance="high")
