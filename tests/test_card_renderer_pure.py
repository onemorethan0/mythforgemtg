"""card_renderer.py: the pure, GPU-free helpers (colour keys, legibility maths, text tokenising,
type-line tidy). Rendering itself stays covered by test_smoke.py."""
from __future__ import annotations

import pytest
from PIL import Image

import card_renderer as cr


# -- mana / colour keys -------------------------------------------------------------------

def test_parse_mana_lists_symbols_in_order():
    assert cr._parse_mana("{2}{W}{U/B}{X}") == ["2", "W", "U/B", "X"]
    assert cr._parse_mana("") == []


def test_sort_colors_is_wubrg_order_and_tolerates_unknowns():
    assert cr._sort_colors(["G", "W", "R"]) == "WRG"
    assert cr._sort_colors(["B", "U"]) == "UB"
    assert cr._sort_colors(["Q", "W"]) == "WQ"        # unknown sorts last, kept


@pytest.mark.parametrize("colors,type_line,expected", [
    ([], "Land", "Land"),
    (["G"], "Basic Land — Forest", "Land"),             # land beats colour
    ([], "Artifact — Equipment", "Artifact"),
    ([], "Creature", "Colourless"),
    (["R"], "Instant", "R"),
    (["U", "W"], "Creature — Sphinx", "WU"),            # two colours: WUBRG-sorted pair
    (["W", "U", "B"], "Creature", "Gold"),
    (None, None, "Colourless"),
])
def test_frame_key(colors, type_line, expected):
    assert cr._frame_key(colors or [], type_line) == expected


def test_box_and_crown_keys():
    for k in ("W", "U", "B", "R", "G", "Artifact", "Colourless", "Land"):
        assert cr._box_key(k) == k
    assert cr._box_key("WU") == "Gold" and cr._box_key("Gold") == "Gold"
    assert cr._crown_key("WU") == "WU"                  # crowns keep the full frame stem


def test_mm_scales_linearly():
    assert cr._mm(0) == 0
    assert cr._mm(10) == round(10 * cr._MM)
    assert cr._mm(20) >= cr._mm(10)


# -- legibility maths ------------------------------------------------------------------------

def test_relative_luminance_extremes():
    assert cr._rel_luminance((0, 0, 0)) == pytest.approx(0.0)
    assert cr._rel_luminance((255, 255, 255)) == pytest.approx(1.0)
    assert cr._rel_luminance((255, 0, 0)) < cr._rel_luminance((0, 255, 0))   # green carries more


def test_contrast_ratio_wcag_bounds_and_symmetry():
    assert cr._contrast_ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0)
    assert cr._contrast_ratio((50, 50, 50), (50, 50, 50)) == pytest.approx(1.0)
    a, b = (200, 30, 30), (20, 90, 200)
    assert cr._contrast_ratio(a, b) == pytest.approx(cr._contrast_ratio(b, a))


def test_avg_region_rgb_of_a_solid_block_and_degenerate_boxes():
    img = Image.new("RGB", (100, 100), (40, 80, 120))
    assert cr._avg_region_rgb(img, (10, 10, 60, 60)) == (40, 80, 120)
    assert cr._avg_region_rgb(img, (10, 10, 11, 11)) is None          # under 2px
    assert cr._avg_region_rgb(img, (200, 200, 300, 300)) is None       # off-canvas
    assert cr._avg_region_rgb(img, (-50, -50, 40, 40)) == (40, 80, 120)  # clipped to canvas


def test_legible_text_colour_flips_with_the_background():
    dark = Image.new("RGB", (60, 30), (5, 5, 5))
    light = Image.new("RGB", (60, 30), (250, 250, 250))
    assert cr._legible_text_color(dark, (0, 0, 60, 30)) == cr._LIGHT_TEXT
    assert cr._legible_text_color(light, (0, 0, 60, 30)) == cr._DARK_TEXT


def test_legible_text_colour_falls_back_when_unsampleable():
    img = Image.new("RGB", (10, 10), (0, 0, 0))
    assert cr._legible_text_color(img, (500, 500, 600, 600), fallback=(1, 2, 3)) == (1, 2, 3)


# -- text tokenising -----------------------------------------------------------------------------

def test_italic_regions_mark_reminder_text_only():
    runs = cr._italic_regions("Flying (This can fly.) Draw a card.")
    assert [(t, i) for t, i in runs if i] == [("(This can fly.)", True)]
    assert "".join(t for t, _ in runs) == "Flying (This can fly.) Draw a card."


def test_italic_regions_handle_nested_and_unbalanced_parens():
    nested = cr._italic_regions("a (b (c) d) e")
    assert [t for t, i in nested if i] == ["(b (c) d)"]
    assert all(not i for t, i in cr._italic_regions("oops ) stray"))   # a lone ')' stays upright


def test_tokenise_splits_symbols_from_text_and_keeps_italic_flags():
    toks = cr._tokenise("{T}: Add {G}. (Reminder.)")
    kinds = [(k, v) for k, v, _ in toks]
    assert ("sym", "T") in kinds and ("sym", "G") in kinds
    assert any(k == "text" and "Add" in v for k, v, _ in toks)
    assert any(ital for k, v, ital in toks if k == "text" and "Reminder" in v)
    assert not any(ital for k, v, ital in toks if k == "sym")


def test_tokenise_plain_text_is_one_token():
    assert cr._tokenise("Just words") == [("text", "Just words", False)]
    assert cr._tokenise("") == []


# -- border theme --------------------------------------------------------------------------------------

def test_border_theme_matches_keywords_case_insensitively():
    assert cr._classify_border_theme("An OVERGROWN forest grove")[0] == "vine"
    assert cr._classify_border_theme("frozen tundra")[0] == "frost"
    assert cr._classify_border_theme("a roaring Inferno")[0] == "flame"


def test_border_theme_default_when_nothing_matches():
    assert cr._classify_border_theme("xyzzy") == cr._BORDER_THEME_DEFAULT
    assert cr._classify_border_theme("") == cr._BORDER_THEME_DEFAULT


# -- type-line tidy ----------------------------------------------------------------------------------------

def test_name_as_creature_type_reverts_to_the_original_type():
    card = {"original_type_line": "Legendary Creature — Elf Druid"}
    out = cr.clean_display_type_line(card, "Legendary Creature — Cyber Champion", "Cyber Champion")
    assert out == "Legendary Creature — Elf Druid"


def test_name_as_type_matches_on_the_pre_comma_part():
    card = {"original_type_line": "Legendary Creature — Human"}
    out = cr.clean_display_type_line(card, "Legendary Creature — Kara", "Kara, Ashen Queen")
    assert out == "Legendary Creature — Human"


def test_name_as_type_is_kept_when_there_is_no_original_to_revert_to():
    out = cr.clean_display_type_line({}, "Creature — Bob", "Bob")
    assert out == "Creature — Bob"


def test_class_subtype_is_dropped_from_enchantments_but_aura_stays():
    assert cr.clean_display_type_line({}, "Enchantment — Class") == "Enchantment"
    assert cr.clean_display_type_line({}, "Enchantment — Aura") == "Enchantment — Aura"


def test_plain_and_empty_type_lines_pass_through():
    assert cr.clean_display_type_line({}, "Instant") == "Instant"
    assert cr.clean_display_type_line({}, "") == ""
    assert cr.clean_display_type_line({}, None) == ""
    assert cr.clean_display_type_line({}, "Creature - Elf", "x") == "Creature - Elf"


def test_border_theme_keyword_must_start_a_word():
    # "inferno" contains the vine keyword "fern"; "flash" contains the flame keyword "ash"
    assert cr._classify_border_theme("inferno")[0] == "flame"
    assert cr._classify_border_theme("flash of light")[0] != "flame"
    assert cr._classify_border_theme("ashen wastes")[0] == "flame"      # prefix still matches
    assert cr._classify_border_theme("frozen")[0] == "frost"
