"""image_gen.py pure helpers: model-family detection, prompt tidying and de-duplication, the theme
darkness score that scales dark-only LoRAs, ComfyUI error summarising, and GenSettings.from_dict."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import image_gen as ig


# -- model-family detection ----------------------------------------------------------------------

@pytest.mark.parametrize("name,flux,krea,ltx,qwen,sd35,sdxl", [
    ("flux1-dev-fp8.safetensors",        True,  False, False, False, False, False),
    ("FLUX.1-Krea-dev.safetensors",      True,  True,  False, False, False, False),
    ("ltx-video-2b.safetensors",         False, False, True,  False, False, False),
    ("qwen_image_fp8.safetensors",       False, False, False, True,  False, False),
    ("sd3.5_large.safetensors",          False, False, False, False, True,  False),
    ("sd35_medium.safetensors",          False, False, False, False, True,  False),
    ("stable-diffusion-3-medium.safetensors", False, False, False, False, True, False),
    ("sd_xl_base_1.0_sdxl.safetensors",  False, False, False, False, False, True),
    ("illustriousXL_v1.safetensors",     False, False, False, False, False, True),
    ("juggernautXL_v9.safetensors",      False, False, False, False, False, True),
    ("dreamshaperXL.safetensors",        False, False, False, False, False, True),
    ("some_sd15_checkpoint.safetensors", False, False, False, False, False, False),
])
def test_model_family_detection(name, flux, krea, ltx, qwen, sd35, sdxl):
    assert ig._is_flux(name) is flux
    assert ig._is_krea(name) is krea
    assert ig._is_ltx(name) is ltx
    assert ig._is_qwen(name) is qwen
    assert ig._is_sd35(name) is sd35
    assert ig._is_sdxl(name) is sdxl


def test_detection_is_case_insensitive():
    assert ig._is_flux("FLUX-DEV") and ig._is_sdxl("SDXL-Base") and ig._is_qwen("QWEN-IMAGE")


# -- prompt tidying ---------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("a  b", "a b"),
    ("a , b", "a, b"),
    ("a,, b", "a, b"),
    ("a. , b", "a. b"),
    (" , a ,", "a"),
    ("a ; ", "a"),
    ("", ""),
])
def test_tidy_prompt(raw, expected):
    assert ig._tidy_prompt(raw) == expected


def test_tidy_prompt_is_idempotent():
    for raw in ("a , , b ;", "  x   y . , z", "plain"):
        once = ig._tidy_prompt(raw)
        assert ig._tidy_prompt(once) == once


# -- word sets and de-duplication ---------------------------------------------------------------------

def test_prompt_word_set_keeps_only_significant_lowercased_words():
    words = ig._prompt_word_set("A Majestic DRAGON over the Misty-Mountains, highly detailed")
    assert "majestic" in words and "dragon" in words and "misty-mountains" in words
    assert "the" not in words and "over" not in words        # too short
    assert "highly" not in words and "detailed" not in words  # stopwords


def test_strip_trigger_prefix_drops_only_fully_redundant_triggers():
    words = ig._prompt_word_set("a cyberpunk neon city")
    out = ig._strip_trigger_prefix("cyberpunk, kcyberpunk code. ", words)
    assert out == "kcyberpunk code. "                           # the unique code survives
    assert ig._strip_trigger_prefix("cyberpunk. ", words) == ""   # all redundant -> nothing left


def test_strip_trigger_prefix_passes_empty_through_and_keeps_the_trailing_period():
    assert ig._strip_trigger_prefix("", set()) == ""
    assert ig._strip_trigger_prefix("trigA, trigB. ", set()) == "trigA, trigB. "
    assert ig._strip_trigger_prefix("trigA, trigB", set()) == "trigA, trigB. "


def test_dedup_style_words_removes_what_the_prompt_already_says():
    words = ig._prompt_word_set("a watercolor landscape")
    out = ig._dedup_style_words("watercolor painting, soft light", words)
    assert "watercolor" not in out.lower() and "soft light" in out
    assert out.endswith(" ")
    assert ig._dedup_style_words("   ", words) == "   "
    assert ig._dedup_style_words("", words) == ""


# -- theme darkness ---------------------------------------------------------------------------------------

def test_darkness_neutral_dark_and_light_themes():
    assert ig._theme_darkness_score("a medieval castle") == 1.0
    assert ig._theme_darkness_score("") == 1.0
    assert ig._theme_darkness_score("grim gothic horror") == 1.0         # all dark -> full strength
    assert ig._theme_darkness_score("cute pastel rainbow kittens") == pytest.approx(0.2, abs=0.01)


def test_darkness_is_bounded_and_mixed_themes_sit_between():
    mixed = ig._theme_darkness_score("dark but cute")
    assert 0.2 < mixed < 1.0
    for t in ("dark", "cute", "dark cute", "nothing here", "grim gothic cute pastel"):
        assert 0.2 <= ig._theme_darkness_score(t) <= 1.0


def test_darkness_matches_whole_words_not_substrings():
    # "lightning" contains 'light' and "protector" contains 'rot': neither is a mood word
    assert ig._theme_darkness_score("a lightning storm over a castle") == 1.0
    assert ig._theme_darkness_score("a protector of the realm") == 1.0
    assert ig._theme_darkness_score("the swarm approaches") == 1.0          # 'swarm' contains 'warm'
    # real inflections still count
    assert ig._theme_darkness_score("shadows and darkness") == 1.0
    assert ig._theme_darkness_score("bright flowers and rainbows") < 0.5


# -- ComfyUI error summary -------------------------------------------------------------------------------------

class _Resp:
    def __init__(self, body=None, text="", json_raises=False):
        self._body, self.text, self._raises = body, text, json_raises

    def json(self):
        if self._raises:
            raise ValueError("no json")
        return self._body


def test_error_summary_combines_message_details_and_node_errors():
    body = {"error": {"message": "Prompt invalid", "details": "bad input"},
            "node_errors": {"5": {"errors": [{"message": "Missing", "details": "ckpt"}]}}}
    out = ig._summarize_comfy_error(_Resp(body))
    assert out == "Prompt invalid | bad input | node 5: Missing — ckpt"


def test_error_summary_does_not_repeat_identical_details_and_caps_node_noise():
    body = {"error": {"message": "same", "details": "same"},
            "node_errors": {str(i): {"errors": [{"message": f"e{i}a"}, {"message": f"e{i}b"}, {"message": f"e{i}c"}]}
                            for i in range(6)}}
    out = ig._summarize_comfy_error(_Resp(body))
    assert out.count("same") == 1
    assert out.count("node ") == 6 and "e0c" not in out and "node 4" not in out and "node 3" not in out


def test_error_summary_falls_back_to_text_when_there_is_no_json():
    assert ig._summarize_comfy_error(_Resp(text="  upstream exploded  ", json_raises=True)) == "upstream exploded"
    assert ig._summarize_comfy_error(_Resp(text="", json_raises=True)) == "<no body>"
    assert ig._summarize_comfy_error(_Resp(body={}, text="raw text")) == "raw text"


# -- GenSettings.from_dict -------------------------------------------------------------------------------------------

def test_from_dict_ignores_unknown_keys_none_and_empty():
    base = ig.GenSettings()
    assert ig.GenSettings.from_dict(None) == base and ig.GenSettings.from_dict({}) == base
    gs = ig.GenSettings.from_dict({"guidance": 2.5, "steps": 12, "not_a_field": 1, "seed": None})
    assert gs.guidance == 2.5 and gs.steps == 12 and gs.seed is None
    assert not hasattr(gs, "not_a_field")


def test_resolved_round_trips_through_from_dict():
    gs = ig.GenSettings.from_dict({"guidance": 4.0, "safe_mode": True, "lora_overrides": [{"filename": "x"}]})
    assert ig.GenSettings.from_dict(gs.resolved()) == gs
