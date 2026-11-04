"""themer.py helpers with no test coverage: prompt sanitising, model-size gating, creature
subtypes, the RO element/type maps, theme palette extraction, and the LLM batch parser."""
from __future__ import annotations

import json

import pytest

import themer


# -- _quote_user_text -----------------------------------------------------------------------

def test_quote_removes_the_prompt_delimiters():
    assert themer._quote_user_text("a <<<b>>> c") == "a b c"
    assert "<<<" not in themer._quote_user_text("<<<<<<x")


def test_quote_strips_control_characters_but_keeps_newline_and_tab():
    out = themer._quote_user_text("a\x00b\x07c\nd\te\x85f")
    assert out == "abc\nd\tef"


def test_quote_caps_length_with_an_ellipsis():
    out = themer._quote_user_text("x" * 50, max_len=10)
    assert out == "x" * 10 + "..."
    assert themer._quote_user_text("short", max_len=10) == "short"


def test_quote_handles_empty_and_unicode():
    assert themer._quote_user_text("") == "" and themer._quote_user_text(None) == ""
    assert themer._quote_user_text("Café — naïve") == "Café — naïve"


# -- model size / few-shot gate -----------------------------------------------------------------

@pytest.mark.parametrize("model,size", [
    ("qwen3:14b", 14.0), ("llama3.1:8b", 8.0), ("qwen3:32b", 32.0),
    ("gemma-2b-it", 2.0), ("QWEN3:14B", 14.0), ("mixtral-8x7b", 7.0),
])
def test_model_param_b_parses_the_size_tag(model, size):
    assert themer._model_param_b(model) == size


def test_model_param_b_is_zero_when_unparseable_or_empty():
    assert themer._model_param_b("") == 0.0
    assert themer._model_param_b(None) == 0.0
    assert themer._model_param_b("totally-unknown:latest") == 0.0


def test_fewshot_is_gated_to_large_models_in_auto_mode(monkeypatch):
    monkeypatch.setattr(themer, "_FEWSHOT_MODE", "auto")
    monkeypatch.setattr(themer, "_FEWSHOT_MIN_B", 14.0)
    assert themer._use_fewshot("qwen3:14b") is True
    assert themer._use_fewshot("qwen3:32b") is True
    assert themer._use_fewshot("llama3.1:8b") is False
    assert themer._use_fewshot("totally-unknown") is False


def test_fewshot_mode_overrides(monkeypatch):
    monkeypatch.setattr(themer, "_FEWSHOT_MODE", "on")
    assert themer._use_fewshot("llama3.1:8b") is True
    monkeypatch.setattr(themer, "_FEWSHOT_MODE", "off")
    assert themer._use_fewshot("qwen3:32b") is False


# -- creature subtypes ----------------------------------------------------------------------------

def test_creature_subtypes_basic_and_non_creatures():
    assert themer._creature_subtypes("Legendary Creature — Faerie Warlock") == ["Faerie", "Warlock"]
    assert themer._creature_subtypes("Creature - Elf") == ["Elf"]          # ASCII dash accepted
    assert themer._creature_subtypes("Instant") == []
    assert themer._creature_subtypes("Artifact — Equipment") == []
    assert themer._creature_subtypes("") == [] and themer._creature_subtypes(None) == []


def test_creature_subtypes_read_each_face_separately():
    # the bug this guards: a single split on the first dash leaked 'Legendary', 'Creature', '//'
    out = themer._creature_subtypes("Creature — Ogre Shaman // Legendary Creature — Ogre Shaman")
    assert out == ["Ogre", "Shaman", "Ogre", "Shaman"]
    assert "//" not in out and "Legendary" not in out and "Creature" not in out


def test_creature_subtypes_skip_a_noncreature_face():
    assert themer._creature_subtypes("Creature — Human // Land") == ["Human"]
    assert themer._creature_subtypes("Creature — Human Werewolf // Creature") == ["Human", "Werewolf"]


def test_subtype_echoes_name():
    assert themer._subtype_echoes_name("Legendary Creature — Cyber Champion", "Cyber Champion") is True
    assert themer._subtype_echoes_name("Legendary Creature — Cyber Champion", "Cyber Champion, Light") is True
    assert themer._subtype_echoes_name("Legendary Creature — Elf", "Cyber Champion") is False
    assert themer._subtype_echoes_name("Instant", "Anything") is False
    assert themer._subtype_echoes_name("Creature — Bob", "") is False


# -- Ragnarok Online maps ---------------------------------------------------------------------------

def test_ro_tag_to_display():
    assert themer._ro_tag_to_display("lord_knight_(ragnarok_online)") == "Lord Knight"
    assert themer._ro_tag_to_display("priest") == "Priest"


@pytest.mark.parametrize("ci,expected", [
    (["W", "R"], "holy fire element"), (["U", "B"], "water shadow element"),
    (["G"], "earth element"), (["R"], "fire element"), (["W"], "holy element"),
    (["U"], "water element"), (["B"], "shadow element"), ([], "neutral element"),
    (["W", "U", "B", "R", "G"], "holy fire element"),                   # first matching pair wins
])
def test_ro_element_from_color_identity(ci, expected):
    assert themer._ro_element({"color_identity": ci}) == expected


def test_ro_element_falls_back_to_colors_and_is_case_insensitive():
    assert themer._ro_element({"colors": ["g"]}) == "earth element"
    assert themer._ro_element({}) == "neutral element"


def test_ro_type_for_tribe_defaults_to_demihuman_and_is_deterministic():
    assert themer._ro_type_for_tribe("") == "Demihuman"
    assert themer._ro_type_for_tribe(None) == "Demihuman"
    assert themer._ro_type_for_tribe("Xyzzy") == "Demihuman"
    for tribe in ("Knight", "Dragon", "Elf", "Zombie", "Wizard"):
        out = themer._ro_type_for_tribe(tribe)
        assert out == themer._ro_type_for_tribe(tribe) and out and out == out.title()


# -- theme palette ---------------------------------------------------------------------------------------

def test_palette_orders_by_first_appearance():
    out = themer._extract_theme_palette("black and green")
    assert out.index("black") < out.index("green")
    assert " / " in out


def test_palette_is_empty_without_colour_words():
    assert themer._extract_theme_palette("") == ""
    assert themer._extract_theme_palette("a neon city") == ""


def test_palette_does_not_repeat_when_two_words_share_one_palette():
    # 'gold' and 'golden' map to the same palette string
    out = themer._extract_theme_palette("a golden city of gold")
    assert out == "gold, amber, brass"


def test_palette_matches_whole_words_not_substrings():
    # 'hundred' contains 'red'; 'tealight' contains 'teal'; 'goldfish' is not the colour gold
    assert themer._extract_theme_palette("a hundred years war") == ""
    assert themer._extract_theme_palette("scared") == ""
    assert themer._extract_theme_palette("red dragon").startswith("red")


# -- _parse_batch ---------------------------------------------------------------------------------------

CARDS = [{"name": "Sol Ring"}, {"name": "Island"}, {"name": "Forest"}]


def _entry(i, name="Themed", art="an image", flavor="words"):
    return {"idx": i, "themed_name": name, "art_prompt": art, "flavor_text": flavor}


def test_parse_batch_reads_a_plain_json_array():
    raw = json.dumps([_entry(0, "A"), _entry(1, "B"), _entry(2, "C")])
    out = themer._parse_batch(raw, CARDS)
    assert [e["themed_name"] for e in out] == ["A", "B", "C"]
    assert [e["idx"] for e in out] == [0, 1, 2]


def test_parse_batch_strips_fences_and_thinking_noise():
    raw = "<think>I considered [1, 2] and decided</think>\n```json\n" + json.dumps([_entry(0, "A")]) + "\n```"
    out = themer._parse_batch(raw, CARDS[:1])
    assert out[0]["themed_name"] == "A"


def test_parse_batch_unwraps_a_cards_object_and_a_bare_entry():
    out = themer._parse_batch(json.dumps({"cards": [_entry(0, "A"), _entry(1, "B")]}), CARDS[:2])
    assert [e["themed_name"] for e in out] == ["A", "B"]
    out = themer._parse_batch(json.dumps(_entry(0, "Solo")), CARDS[:1])
    assert out[0]["themed_name"] == "Solo"


def test_parse_batch_fills_missing_entries_with_the_original_name():
    out = themer._parse_batch(json.dumps([_entry(1, "B")]), CARDS)
    assert out[0] == {"idx": 0, "themed_name": "Sol Ring", "art_prompt": "", "flavor_text": ""}
    assert out[1]["themed_name"] == "B"
    assert out[2]["themed_name"] == "Forest"


@pytest.mark.parametrize("bad", [
    _entry(0, ""), _entry(0, "x" * 101), _entry(0, "[Theme Name]"), _entry(0, "A", art="y" * 801),
])
def test_parse_batch_rejects_mangled_entries(bad):
    out = themer._parse_batch(json.dumps([bad]), CARDS[:1])
    assert out[0]["themed_name"] == "Sol Ring" and out[0]["art_prompt"] == ""


def test_parse_batch_keeps_an_entry_with_an_empty_art_prompt():
    # a truncated art prompt is the caller's retry signal, not a reason to drop the name
    out = themer._parse_batch(json.dumps([_entry(0, "A", art="")]), CARDS[:1])
    assert out[0]["themed_name"] == "A" and out[0]["art_prompt"] == ""


def test_parse_batch_survives_garbage_and_empty_input():
    assert themer._parse_batch("   ", CARDS) == []
    out = themer._parse_batch("not json at all", CARDS)
    assert [e["themed_name"] for e in out] == ["Sol Ring", "Island", "Forest"]
    assert all(e["art_prompt"] == "" and e["flavor_text"] == "" for e in out)


# -- RO race/class: keywords match at a word START, not anywhere ---------------------------------------

def test_ro_race_class_known_subtypes():
    assert themer._ro_race_class("Creature — Dragon") == ("dragon race", "")
    assert themer._ro_race_class("Creature — Human Knight")[1] == "lord_knight_(ragnarok_online)"
    assert themer._ro_race_class("Creature — Cat")[0] == "brute race"
    assert themer._ro_race_class("Instant") == ("", "")


def test_ro_race_does_not_match_inside_a_longer_word():
    # 'ape' is inside 'shapeshifter'; it made every Shapeshifter a Brute
    race, _ = themer._ro_race_class("Creature — Shapeshifter")
    assert race == "demihuman race"                       # the unmatched-creature default
    assert themer._ro_type_for_tribe("Shapeshifter") == "Demihuman"


def test_ro_race_still_matches_a_keyword_prefix():
    assert themer._ro_race_class("Creature — Catfolk")[0] == "brute race"
    assert themer._ro_type_for_tribe("Dragons") == themer._ro_type_for_tribe("Dragon")
