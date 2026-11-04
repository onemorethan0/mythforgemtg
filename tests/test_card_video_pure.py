"""card_video.py pure helpers: clip-length arithmetic, motion strength, loop construction, prompt
assembly and the option lists the UI reads. No ComfyUI, no encoders."""
from __future__ import annotations

import pytest
from PIL import Image

import card_video as cv


def _frames(n, size=(8, 8)):
    return [Image.new("RGBA", size, (i * 10 % 256, 0, 0, 255)) for i in range(n)]


# -- frames_for_duration ---------------------------------------------------------------------------

def test_motion_frame_counts_snap_to_the_models_k_n_plus_one():
    # ltxv wants 8n+1, wan wants 4n+1
    for sec in (1.0, 2.0, 3.0, 4.5, 6.0):
        assert (cv.frames_for_duration("ltxv", sec, 24) - 1) % 8 == 0, sec
        assert (cv.frames_for_duration("wan", sec, 16) - 1) % 4 == 0, sec


def test_known_values():
    assert cv.frames_for_duration("ltxv", 2.0, 24) == 49          # 48 -> n=round(47/8)=6 -> 49
    assert cv.frames_for_duration("wan", 2.0, 16) == 33           # 32 -> n=round(31/4)=8 -> 33
    assert cv.frames_for_duration("unknown", 2.0, 24) == 48       # no snapping for an unknown method
    assert cv.frames_for_duration(None, 2.0, 24) == 48


def test_motion_duration_is_clamped_to_the_safe_range():
    lo = cv.frames_for_duration("ltxv", 0.0, 24)
    hi = cv.frames_for_duration("ltxv", 999.0, 24)
    assert lo == cv.frames_for_duration("ltxv", cv.MOTION_MIN_S, 24)
    assert hi == cv.frames_for_duration("ltxv", cv.MOTION_MAX_S, 24)
    assert lo < hi


def test_foil_allows_any_count_within_its_wider_bounds():
    assert cv.frames_for_duration(None, 4.0, 24, foil=True) == 96
    assert cv.frames_for_duration("ltxv", 4.0, 24, foil=True) == 96     # method snap does not apply
    assert cv.frames_for_duration(None, 999, 24, foil=True) == int(cv.FOIL_MAX_S * 24)
    assert cv.frames_for_duration(None, 0, 24, foil=True) == int(cv.FOIL_MIN_S * 24)


def test_a_bad_fps_falls_back_instead_of_dividing_by_zero():
    assert cv.frames_for_duration("ltxv", 2.0, 0) == cv.frames_for_duration("ltxv", 2.0, 24)
    assert cv.frames_for_duration("ltxv", 2.0, None) == cv.frames_for_duration("ltxv", 2.0, 24)
    assert cv.frames_for_duration(None, 1.0, -5, foil=True) >= 2


def test_frame_count_is_never_below_a_playable_minimum():
    for method in ("ltxv", "wan", None):
        assert cv.frames_for_duration(method, 1.0, 1) >= 2


# -- motion strength -------------------------------------------------------------------------------

def test_conditioning_fps_runs_from_subtle_to_strong_and_is_monotone():
    assert cv._ltxv_cond_fps(0.0) == cv._MOTION_COND_FPS_MAX
    assert cv._ltxv_cond_fps(1.0) == cv._MOTION_COND_FPS_MIN
    vals = [cv._ltxv_cond_fps(s / 10) for s in range(11)]
    assert vals == sorted(vals, reverse=True)                  # more strength -> lower fps
    assert cv._ltxv_cond_fps(-5) == cv._MOTION_COND_FPS_MAX    # clamped
    assert cv._ltxv_cond_fps(99) == cv._MOTION_COND_FPS_MIN


# -- loops ------------------------------------------------------------------------------------------------

def test_ping_pong_is_a_seamless_boomerang_without_duplicated_endpoints():
    out = cv.ping_pong(list("ABCD"))
    assert out == list("ABCDCB")                                # ends on the frame before the first
    assert cv.ping_pong(list("AB")) == list("AB")               # too short to loop
    assert cv.ping_pong(list("ABCD"), loop=False) == list("ABCD")


def test_make_loop_styles():
    frames = _frames(8)
    assert len(cv.make_loop(frames, "off")) == 8
    assert len(cv.make_loop(frames, "none")) == 8
    assert len(cv.make_loop(frames, "bounce")) == 8 + 6
    xf = cv.make_loop(frames, "crossfade")
    assert 0 < len(xf) < 8                                      # forward-only, shorter by the dissolve
    assert cv.make_loop(frames) == xf or len(cv.make_loop(frames)) == len(xf)   # crossfade is the default


def test_make_loop_leaves_tiny_clips_alone():
    assert len(cv.make_loop(_frames(2), "crossfade")) == 2
    assert cv.make_loop([], "bounce") == []


def test_crossfade_blends_the_tail_into_the_head_and_never_runs_backwards():
    frames = _frames(8)
    out = cv._crossfade_loop(frames)
    k = 8 - len(out)
    assert 1 <= k <= 4
    # frames after the dissolve are the original frames untouched
    assert out[k].tobytes() == frames[k].tobytes()
    # the first output pixel sits between tail and head values (a real blend)
    r = out[0].getpixel((0, 0))[0]
    lo, hi = sorted((frames[len(out)].getpixel((0, 0))[0], frames[0].getpixel((0, 0))[0]))
    assert lo <= r <= hi


def test_loop_style_back_compat():
    assert cv._resolve_loop_style(True, None) == cv._MOTION_LOOP_DEFAULT
    assert cv._resolve_loop_style(False, None) == "off"
    assert cv._resolve_loop_style(False, "bounce") == "bounce"       # explicit style wins


# -- prompts -------------------------------------------------------------------------------------------------

def test_a_custom_motion_wins_over_the_preset_and_carries_the_still_subject_guard():
    out = cv.build_motion_prompt("fire", "a dragon", custom="slow drifting embers")
    assert out.startswith("slow drifting embers")
    assert cv._CUSTOM_MOTION_GUARD in out and out.endswith("Scene: a dragon")


def test_custom_motion_is_trimmed_and_blank_custom_falls_back_to_the_preset():
    long = cv.build_motion_prompt("fire", "", custom="x" * 500)
    assert long.startswith("x" * 300 + ",") and "x" * 301 not in long
    blank = cv.build_motion_prompt("fire", "", custom="   ")
    assert blank == cv._MOTION_PRESETS["fire"]


def test_unknown_preset_uses_the_default_and_the_scene_is_capped():
    assert cv.build_motion_prompt("nope") == cv._MOTION_PRESETS[cv._DEFAULT_PRESET]
    assert cv.build_motion_prompt(None) == cv._MOTION_PRESETS[cv._DEFAULT_PRESET]
    scene = cv.build_motion_prompt("fire", "y" * 900).split("Scene: ")[1]
    assert len(scene) == 400


# -- option lists the UI reads ----------------------------------------------------------------------------------------

def test_motion_presets_list_every_preset_with_a_label():
    presets = cv.motion_presets()
    assert [p["key"] for p in presets] == list(cv._MOTION_PRESETS)
    assert all(p["label"] and p["label"] != p["key"] for p in presets)    # none fell back to its key


def test_option_lists_match_their_constants():
    assert [o["key"] for o in cv.format_options()] == list(cv.VIDEO_FORMATS)
    assert [o["key"] for o in cv.loop_styles()] == list(cv.LOOP_STYLES)
    assert [o["key"] for o in cv.foil_styles()] == list(cv._FOIL_STYLES)


def test_video_caps_report_the_real_bounds():
    caps = cv.video_caps()
    assert caps["motion"]["min_s"] == cv.MOTION_MIN_S and caps["motion"]["max_s"] == cv.MOTION_MAX_S
    assert caps["foil"]["max_s"] == cv.FOIL_MAX_S
    assert caps["fps_options"] == list(cv.FPS_OPTIONS)
    assert caps["motion"]["min_s"] <= caps["motion"]["default_s"] <= caps["motion"]["max_s"]
    assert caps["foil"]["min_s"] <= caps["foil"]["default_s"] <= caps["foil"]["max_s"]


def test_encode_rejects_an_unknown_format(tmp_path):
    with pytest.raises(ValueError):
        cv.encode_loop(_frames(4), tmp_path / "x.avi", fmt="avi")
