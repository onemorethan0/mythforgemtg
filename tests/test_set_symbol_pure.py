"""set_symbol.py: the CPU-only drawing and rarity-recolour helpers.

Written directly (not drafted): the qwen3:8b draft imported a module that does not exist and
failed verification after two repair rounds. See docs/STATUS.md section 3.
"""
from __future__ import annotations

import math

import pytest
from PIL import Image, ImageDraw

import set_symbol


# -- colour helpers ---------------------------------------------------------------

@pytest.mark.parametrize("hue", [0, 60, 120, 180, 240, 300, 359.9])
def test_hue_to_rgb_is_a_valid_rgb_triple(hue):
    rgb = set_symbol._hue_to_rgb(hue)
    assert len(rgb) == 3 and all(isinstance(c, int) and 0 <= c <= 255 for c in rgb)


def test_hue_to_rgb_primaries():
    r, g, b = set_symbol._hue_to_rgb(0, s=1.0, v=1.0)
    assert (r, g, b) == (255, 0, 0)
    assert set_symbol._hue_to_rgb(120, s=1.0, v=1.0) == (0, 255, 0)
    assert set_symbol._hue_to_rgb(240, s=1.0, v=1.0) == (0, 0, 255)


def test_hue_wraps_at_360():
    assert set_symbol._hue_to_rgb(360) == set_symbol._hue_to_rgb(0)


def test_zero_saturation_is_grey():
    r, g, b = set_symbol._hue_to_rgb(200, s=0.0, v=0.5)
    assert r == g == b


def test_darken_scales_every_channel_down():
    assert set_symbol._darken((200, 100, 50), 0.5) == (100, 50, 25)
    out = set_symbol._darken((200, 100, 50))
    assert all(o < c for o, c in zip(out, (200, 100, 50)))


# -- geometry -----------------------------------------------------------------------

def test_polygon_has_one_point_per_side_on_the_circle():
    pts = set_symbol._polygon_points(10, 20, 5, 6)
    assert len(pts) == 6
    for x, y in pts:
        assert math.isclose(math.hypot(x - 10, y - 20), 5, abs_tol=1e-9)


def test_polygon_rotation_moves_the_first_vertex():
    assert set_symbol._polygon_points(0, 0, 1, 4)[0] == pytest.approx((1.0, 0.0))
    assert set_symbol._polygon_points(0, 0, 1, 4, rotation=math.pi / 2)[0] == pytest.approx((0.0, 1.0), abs=1e-9)


def test_star_alternates_outer_and_inner_radius():
    pts = set_symbol._star_points(0, 0, 10, 4, 5)
    assert len(pts) == 10
    radii = [math.hypot(x, y) for x, y in pts]
    assert radii[0::2] == pytest.approx([10.0] * 5)
    assert radii[1::2] == pytest.approx([4.0] * 5)


# -- shape families -------------------------------------------------------------------

SHAPES = sorted(n for n in dir(set_symbol) if n.startswith("_draw_shape_"))


def test_there_are_twelve_shape_families():
    assert len(SHAPES) == 12


@pytest.mark.parametrize("name", SHAPES)
def test_every_shape_draws_something_and_stays_in_bounds(name):
    img = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    getattr(set_symbol, name)(draw, 48, 48, 40, (230, 230, 230, 255), (30, 30, 30, 255), (200, 160, 40, 255))
    assert img.getchannel("A").getbbox() is not None, f"{name} drew nothing"


# -- rarity -------------------------------------------------------------------------------

def test_rarity_normalisation():
    assert set_symbol._normalize_rarity("Mythic Rare") == "mythic"
    assert set_symbol._normalize_rarity("  COMMON ") == "common"
    assert set_symbol._normalize_rarity(None) == "common"
    assert set_symbol._normalize_rarity("") == "common"
    assert set_symbol._normalize_rarity("bonus") == "special"
    assert set_symbol._normalize_rarity("weird") == "weird"       # unknown passes through


def _blob():
    img = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((8, 8, 32, 32), fill=(120, 120, 120, 255))
    return img


@pytest.mark.parametrize("rarity", ["common", "uncommon", "rare", "mythic", "special", "nonsense"])
def test_colorize_keeps_size_and_shape(rarity):
    src = _blob()
    out = set_symbol.colorize_by_rarity(src, rarity, add_outline=False)
    assert out.size == src.size and out.mode == "RGBA"
    assert out.getchannel("A").getbbox() == src.getchannel("A").getbbox()


def test_colorize_outline_only_grows_the_alpha():
    src = _blob()
    plain = set_symbol.colorize_by_rarity(src, "rare", add_outline=False).getchannel("A").getbbox()
    rimmed = set_symbol.colorize_by_rarity(src, "rare", add_outline=True).getchannel("A").getbbox()
    assert rimmed[0] <= plain[0] and rimmed[2] >= plain[2]


def test_rarities_get_different_metals():
    src = _blob()
    seen = {set_symbol.colorize_by_rarity(src, r, add_outline=False).getpixel((20, 20))
            for r in ("common", "uncommon", "rare", "mythic")}
    assert len(seen) >= 3


def test_flat_input_does_not_crash():
    flat = Image.new("RGBA", (16, 16), (100, 100, 100, 255))   # hi - lo < 8 path
    assert set_symbol.colorize_by_rarity(flat, "rare").size == (16, 16)


def test_metal_lut_is_a_256_step_ramp_from_shadow_to_highlight():
    stops = ((0, 0, 0), (100, 100, 100), (200, 200, 200))
    r, g, b = set_symbol._metal_luts(stops)
    assert len(r) == len(g) == len(b) == 256
    assert r[0] == 0 and r[255] == 200
    assert r == sorted(r)
