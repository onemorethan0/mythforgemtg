"""api/cards.py pure helpers (names, self-reference rewrite, provenance, mana cost).

Drafted on a local model (qwen3:14b), then rewritten: most of its expected values were
wrong (e.g. it treated {2}{W}{U} as mana value 3, and expected punctuation-free names
that ``_safe_name`` does not produce).
"""
from __future__ import annotations

from api import cards


# -- _safe_name -------------------------------------------------------------

def test_safe_name_replaces_every_non_alphanumeric_with_underscore():
    assert cards._safe_name("Sol Ring") == "Sol_Ring"
    assert cards._safe_name("Hello, World!") == "Hello__World_"
    assert cards._safe_name("Fire // Ice") == "Fire____Ice"


def test_safe_name_truncates_to_48():
    assert len(cards._safe_name("a" * 100)) == 48


# -- _replace_card_self_ref ---------------------------------------------------

def test_self_ref_full_name_is_replaced():
    out = cards._replace_card_self_ref("Kaalia of the Vast enters.", "Kaalia of the Vast", "Dante of the Deep")
    assert out == "Dante of the Deep enters."


def test_self_ref_comma_name_short_form_uses_themed_first_part():
    out = cards._replace_card_self_ref("Uro attacks.", "Uro, Titan of Nature's Wrath", "Vex, Dark Lord")
    assert out == "Vex attacks."


def test_self_ref_no_comma_name_uses_first_word():
    out = cards._replace_card_self_ref("Whenever Kaalia attacks, draw.", "Kaalia of the Vast", "Dante of the Deep")
    assert out == "Whenever Dante attacks, draw."


def test_self_ref_respects_word_boundaries():
    out = cards._replace_card_self_ref("Sol draws. Solitude stays.", "Sol, Mage", "Vex, Mage")
    assert out == "Vex draws. Solitude stays."


def test_self_ref_short_names_are_left_alone():
    # a 2-character pre-comma form is too ambiguous to rewrite
    assert cards._replace_card_self_ref("Ob attacks.", "Ob, Thing", "Vex, Thing") == "Ob attacks."


def test_self_ref_empty_inputs_return_text_unchanged():
    assert cards._replace_card_self_ref("text", "", "New") == "text"
    assert cards._replace_card_self_ref("text", "Old", "") == "text"
    assert cards._replace_card_self_ref("", "Old", "New") == ""


def test_self_ref_double_faced_replaces_each_face_with_themed_first_part():
    out = cards._replace_card_self_ref(
        "Delver of Secrets transforms.", "Delver of Secrets // Insectile Aberration", "Moth, Winged")
    assert out == "Moth transforms."


# -- _is_single_card ----------------------------------------------------------

def test_is_single_card_by_mode_or_playstyle():
    assert cards._is_single_card({"mode": "single_card"}) is True
    assert cards._is_single_card({"playstyle": "Single Card"}) is True
    assert cards._is_single_card({"mode": "deck", "playstyle": "Aggro"}) is False
    assert cards._is_single_card({}) is False
    assert cards._is_single_card(None) is False


def test_is_single_card_is_not_structural():
    # a build cancelled mid-theming also has deck == []; that is not a custom card
    assert cards._is_single_card({"deck": []}) is False


# -- _carry_provenance --------------------------------------------------------

def test_carry_provenance_copies_only_the_provenance_keys():
    src = {"imported": True, "mode": "single_card", "user_flavor": "x", "deck": [1, 2], "name": "n"}
    dst = cards._carry_provenance({}, src, generated_art=True)
    assert dst == {"imported": True, "mode": "single_card", "user_flavor": "x"}


def test_carry_provenance_skips_keys_the_source_lacks():
    dst = cards._carry_provenance({"mode": "keep"}, {"imported": True}, generated_art=True)
    assert dst["mode"] == "keep" and dst["imported"] is True


def test_imported_only_survives_a_text_only_rerun_and_clears_on_art():
    src = {"imported_only": True}
    assert cards._carry_provenance({}, src, generated_art=False)["imported_only"] is True
    assert "imported_only" not in cards._carry_provenance({"imported_only": True}, src, generated_art=True)
    assert "imported_only" not in cards._carry_provenance({"imported_only": True}, {}, generated_art=False)


# -- _normalize_mana_cost -----------------------------------------------------

def test_normalize_brace_free_cost():
    assert cards._normalize_mana_cost("2WU") == "{2}{W}{U}"
    assert cards._normalize_mana_cost("2 w u") == "{2}{W}{U}"
    assert cards._normalize_mana_cost("XRR") == "{X}{R}{R}"


def test_normalize_leaves_braced_empty_and_unparseable_alone():
    assert cards._normalize_mana_cost("{2}{W}") == "{2}{W}"
    assert cards._normalize_mana_cost("") == ""
    assert cards._normalize_mana_cost(None) == ""
    assert cards._normalize_mana_cost("hello") == "hello"


def test_normalize_is_idempotent():
    for raw in ("2WU", "{1}{G}", "XX", "hello", ""):
        once = cards._normalize_mana_cost(raw)
        assert cards._normalize_mana_cost(once) == once


# -- _parse_mana_cost ---------------------------------------------------------

def test_parse_generic_and_coloured():
    assert cards._parse_mana_cost("{2}{W}{U}") == (4.0, ["W", "U"])
    assert cards._parse_mana_cost("{G}{G}") == (2.0, ["G"])


def test_parse_x_is_zero_and_colourless_symbol_is_one():
    assert cards._parse_mana_cost("{X}") == (0.0, [])
    assert cards._parse_mana_cost("{X}{R}") == (1.0, ["R"])
    assert cards._parse_mana_cost("{C}") == (1.0, [])


def test_parse_hybrid_is_worth_the_highest_half():
    assert cards._parse_mana_cost("{2/W}") == (2.0, ["W"])
    assert cards._parse_mana_cost("{W/U}") == (1.0, ["W", "U"])
    assert cards._parse_mana_cost("{W/P}") == (1.0, ["W"])


def test_parse_colours_come_back_in_wubrg_order():
    assert cards._parse_mana_cost("{R}{B}{U}") == (3.0, ["U", "B", "R"])


def test_parse_empty_and_none():
    assert cards._parse_mana_cost("") == (0.0, [])
    assert cards._parse_mana_cost(None) == (0.0, [])
