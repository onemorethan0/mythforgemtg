"""CCM schema + gates (offline)."""

import json
from pathlib import Path

from mythgauntlet.semantics.ccm import (
    cross_check,
    lint_against_card,
    unsupported_ops,
    validate,
    validate_schema,
)

GOOD_DRAW_CCM = {
    "name": "Insight Spell",
    "ccm_version": 1,
    "cost": {"mana": "{2}{U}"},
    "types": ["sorcery"],
    "abilities": [{"kind": "spell_effect", "effects": [{"op": "draw", "count": 2}]}],
}


def test_schema_accepts_good_doc():
    assert validate_schema(GOOD_DRAW_CCM) == []


def test_schema_tolerates_unknown_op_and_flags_it():
    """Unknown ops are kept and flagged (unsupported_ops), not rejected — but a KNOWN op
    alongside them is still validated, so real behavior is still checked."""
    doc = dict(GOOD_DRAW_CCM, abilities=[{
        "kind": "spell_effect",
        "effects": [{"op": "proliferate"}, {"op": "draw", "count": 2}],
    }])
    assert validate_schema(doc) == []
    assert unsupported_ops(doc) == ["proliferate"]


def test_schema_tolerates_unknown_target_keys_and_trigger_events():
    doc = dict(GOOD_DRAW_CCM, types=["creature"], abilities=[{
        "kind": "triggered", "trigger": {"event": "becomes_monstrous"},  # not in vocab
        "effects": [{"op": "destroy", "target": {
            "type": "creature", "count": 1, "condition": "if it attacked", "exclude": "yours",
        }}],
    }])
    assert validate_schema(doc) == []


def test_schema_still_validates_known_op_params():
    """Tolerance does not leak into known ops: a bad count on draw still errors."""
    doc = dict(GOOD_DRAW_CCM, abilities=[
        {"kind": "spell_effect", "effects": [{"op": "draw", "count": -3}]}
    ])
    assert any("non-negative" in e for e in validate_schema(doc))


def test_schema_accepts_variable_quantities():
    """X/X tokens and all/each counts are legal (resolved to a default in the profile)."""
    xx_token = dict(GOOD_DRAW_CCM, types=["creature"], abilities=[{
        "kind": "triggered", "trigger": {"event": "etb"},
        "effects": [{"op": "create_token", "count": "X", "power": "X", "toughness": "X",
                     "types": ["creature"]}],
    }])
    assert validate_schema(xx_token) == []
    mill_all = dict(GOOD_DRAW_CCM, abilities=[
        {"kind": "spell_effect", "effects": [{"op": "mill", "count": "all", "who": "opponent"}]}
    ])
    assert validate_schema(mill_all) == []
    each = dict(GOOD_DRAW_CCM, abilities=[{
        "kind": "spell_effect",
        "effects": [{"op": "destroy", "target": {"type": "creature", "count": "each"}}],
    }])
    assert validate_schema(each) == []


def test_schema_accepts_x_basis_and_enforces_its_type():
    """x_basis (prompt v8+) is a descriptive string; unknown values tolerated, type not."""
    good = dict(GOOD_DRAW_CCM, abilities=[{
        "kind": "spell_effect",
        "effects": [{"op": "draw", "count": "X", "x_basis": "cards_in_hand"}],
    }])
    assert validate_schema(good) == []
    novel = dict(GOOD_DRAW_CCM, abilities=[{
        "kind": "spell_effect",
        "effects": [{"op": "draw", "count": "X", "x_basis": "storm_count"}],  # not in vocab
    }])
    assert validate_schema(novel) == []  # descriptive vocabulary: unknown value tolerated
    bad = dict(GOOD_DRAW_CCM, abilities=[{
        "kind": "spell_effect",
        "effects": [{"op": "draw", "count": "X", "x_basis": 7}],
    }])
    assert any("x_basis" in e for e in validate_schema(bad))


def test_schema_still_rejects_nonsense_quantity():
    """The variable set is CLOSED — genuine garbage still errors."""
    doc = dict(GOOD_DRAW_CCM, abilities=[
        {"kind": "spell_effect", "effects": [{"op": "draw", "count": "banana"}]}
    ])
    assert validate_schema(doc) != []


def test_schema_accepts_add_counter():
    doc = dict(GOOD_DRAW_CCM, types=["creature"], abilities=[{
        "kind": "triggered", "trigger": {"event": "etb"},
        "effects": [{"op": "add_counter", "count": 2, "counter_type": "+1/+1",
                     "target": {"type": "creature", "controller": "you"}}],
    }])
    assert validate_schema(doc) == []
    assert unsupported_ops(doc) == []  # add_counter is now a first-class op


def test_schema_rejects_missing_required_param():
    doc = dict(GOOD_DRAW_CCM, abilities=[
        {"kind": "spell_effect", "effects": [{"op": "draw"}]}
    ])
    assert any("missing required param" in e for e in validate_schema(doc))


def test_schema_tolerates_unknown_trigger_event_rejects_missing():
    ok = dict(GOOD_DRAW_CCM, types=["creature"], abilities=[
        {"kind": "triggered", "trigger": {"event": "full_moon"},  # not in vocab -> inert
         "effects": [{"op": "draw", "count": 1}]}
    ])
    assert validate_schema(ok) == []
    missing = dict(GOOD_DRAW_CCM, types=["creature"], abilities=[
        {"kind": "triggered", "trigger": {}, "effects": [{"op": "draw", "count": 1}]}
    ])
    assert any("trigger.event" in e for e in validate_schema(missing))


def test_schema_rejects_non_mana_op_in_mana_ability():
    doc = dict(GOOD_DRAW_CCM, abilities=[
        {"kind": "mana_ability", "cost": {"tap": True},
         "effects": [{"op": "draw", "count": 1}]}
    ])
    assert any("mana_ability" in e for e in validate_schema(doc))


def test_schema_accepts_x_amounts_and_all_counts():
    doc = dict(GOOD_DRAW_CCM, abilities=[
        {"kind": "spell_effect", "effects": [
            {"op": "draw", "count": "X"},
            {"op": "destroy", "target": {"type": "creature", "count": "all"}},
        ]}
    ])
    assert validate_schema(doc) == []


def test_lint_cost_mismatch(make_card):
    card = make_card("Insight Spell", mana_cost="{1}{U}", type_line="Sorcery",
                     oracle_text="Draw two cards.")
    errors = lint_against_card(GOOD_DRAW_CCM, card)
    assert any("printed cost" in e for e in errors)


def test_lint_type_not_on_type_line(make_card):
    card = make_card("Insight Spell", mana_cost="{2}{U}", type_line="Instant",
                     oracle_text="Draw two cards.")
    assert any("type line" in e for e in lint_against_card(GOOD_DRAW_CCM, card))


def test_lint_sanity_ceiling(make_card):
    card = make_card("Big Draw", mana_cost="{2}{U}", type_line="Sorcery",
                     oracle_text="Draw two cards.")
    doc = dict(GOOD_DRAW_CCM, abilities=[
        {"kind": "spell_effect", "effects": [{"op": "draw", "count": 50}]}
    ])
    assert any("sanity ceiling" in e for e in lint_against_card(doc, card))


def test_cross_check_catches_hallucinated_draw(make_card):
    card = make_card("Vanilla Bear", mana_cost="{2}{U}", type_line="Sorcery",
                     oracle_text="Destroy target artifact.")
    doc = dict(GOOD_DRAW_CCM, types=["sorcery"])
    errors = cross_check(doc, card)
    assert any("never says draw" in e for e in errors)


def test_cross_check_licenses_reminder_text_keywords(make_card):
    """Cycling/ward/landcycling define their effect in REMINDER text, which gate 3 strips.

    "Cycling {2} ({2}, Discard this card: Draw a card.)" reduces to "Cycling {2}" once
    parentheticals are removed, so a CCM that correctly models the draw used to be failed
    for declaring an effect "the text never says". That false-positive class was 155 of the
    240 hallucination quarantines — real cards (Canyon Slough, Ash Barrens, Tolarian Terror)
    the compiler had modeled right all along.
    """
    cycler = make_card("Canyon Slough", type_line="Land — Swamp Mountain",
                       oracle_text="This land enters tapped.\n{T}: Add {B} or {R}.\n"
                                   "Cycling {2} ({2}, Discard this card: Draw a card.)")
    doc = dict(GOOD_DRAW_CCM, name="Canyon Slough", types=["land"], enters_tapped=True)
    assert not any("never says draw" in e for e in cross_check(doc, cycler))

    warded = make_card("Tolarian Terror", mana_cost="{6}{U}", type_line="Creature — Serpent",
                       oracle_text="Ward {2} (Whenever this creature becomes the target of a "
                                   "spell or ability an opponent controls, counter it unless "
                                   "that player pays {2}.)")
    warded_doc = dict(GOOD_DRAW_CCM, name="Tolarian Terror", types=["creature"], abilities=[
        {"kind": "triggered", "trigger": {"event": "other"},
         "effects": [{"op": "counter_spell", "unless_pays": "{2}"}]}
    ])
    assert not any("never says counter" in e for e in cross_check(warded_doc, warded))

    # The omission half is untouched: a keyword can't excuse a MISSING effect.
    bare = make_card("Vanilla Bear", mana_cost="{2}{U}", type_line="Sorcery",
                     oracle_text="Destroy target artifact.")
    assert any("never says draw" in e for e in cross_check(GOOD_DRAW_CCM, bare))


def test_cross_check_catches_missing_draw(make_card):
    card = make_card("Insight Spell", mana_cost="{2}{U}", type_line="Sorcery",
                     oracle_text="Draw two cards.")
    doc = dict(GOOD_DRAW_CCM, abilities=[
        {"kind": "spell_effect", "effects": [{"op": "scry", "count": 2}]}
    ])
    assert any("no draw effect" in e for e in cross_check(doc, card))


def test_cross_check_tapland_flag(make_card):
    card = make_card("Slow Caves", type_line="Land",
                     oracle_text="Slow Caves enters the battlefield tapped.")
    doc = {
        "name": "Slow Caves", "ccm_version": 1, "cost": {"mana": ""},
        "types": ["land"], "abilities": [],
    }
    assert any("enters_tapped" in e for e in cross_check(doc, card))
    doc["enters_tapped"] = True
    assert cross_check(doc, card) == []


def test_full_validate_pass(make_card):
    card = make_card("Insight Spell", mana_cost="{2}{U}", type_line="Sorcery",
                     oracle_text="Draw two cards.")
    gates = validate(GOOD_DRAW_CCM, card)
    assert gates == {"schema": [], "lint": [], "cross_check": []}


def test_schema_accepts_pay_life_cost_and_note_param():
    doc = {
        "name": "Fetch Land", "ccm_version": 1, "cost": {"mana": ""}, "types": ["land"],
        "abilities": [{
            "kind": "activated",
            "cost": {"tap": True, "pay_life": 1, "sacrifice_self": True},
            "effects": [{
                "op": "search_library", "what": {"type": "land"}, "count": 1,
                "to": "battlefield", "shuffle": True, "note": "an Island or Swamp card",
            }],
        }],
    }
    assert validate_schema(doc) == []


def test_cross_check_allows_intrinsic_mana_on_typed_lands(make_card):
    """Shock/dual lands: mana ability is reminder text; produced_mana is the referee."""
    shock = make_card(
        "Shock Dual", type_line="Land — Island Swamp",
        oracle_text="As Shock Dual enters the battlefield, you may pay 2 life. If you "
        "don't, it enters the battlefield tapped.",
        produced_mana=("U", "B"),
    )
    doc = {
        "name": "Shock Dual", "ccm_version": 1, "cost": {"mana": ""}, "types": ["land"],
        "abilities": [{
            "kind": "mana_ability", "cost": {"tap": True},
            "effects": [{"op": "add_mana", "amount": 1, "colors": "UB"}],
        }],
    }
    assert not any("never says add" in e for e in cross_check(doc, shock))


def test_lint_rejects_activated_ability_on_instant(make_card):
    card = make_card("Ritual Spell", mana_cost="{B}", type_line="Instant",
                     oracle_text="Add {B}{B}{B}.")
    doc = {
        "name": "Ritual Spell", "ccm_version": 1, "cost": {"mana": "{B}"},
        "types": ["instant"],
        "abilities": [{
            "kind": "mana_ability", "cost": {"tap": True},
            "effects": [{"op": "add_mana", "amount": 3, "colors": "B"}],
        }],
    }
    assert any("use spell_effect" in e for e in lint_against_card(doc, card))
    doc["abilities"][0] = {
        "kind": "spell_effect",
        "effects": [{"op": "add_mana", "amount": 3, "colors": "B"}],
    }
    assert lint_against_card(doc, card) == []


def test_schema_accepts_attach_op():
    doc = dict(GOOD_DRAW_CCM, abilities=[
        {"kind": "activated", "cost": {"mana": "{1}"},
         "effects": [{"op": "attach", "target": {"type": "creature", "controller": "you"}}]}
    ])
    assert validate_schema(doc) == []


def test_lint_normalizes_or_separated_colors(make_card):
    dual = make_card(
        "Dual Land", type_line="Land", produced_mana=("U", "B"),
        oracle_text="{T}: Add {U} or {B}.",
    )
    doc = {
        "name": "Dual Land", "ccm_version": 1, "cost": {"mana": ""}, "types": ["land"],
        "abilities": [{
            "kind": "mana_ability", "cost": {"tap": True},
            "effects": [{"op": "add_mana", "amount": 1, "colors": "U or B"}],
        }],
    }
    assert lint_against_card(doc, dual) == []
    doc["abilities"][0]["effects"][0]["colors"] = "G"
    assert any("produced_mana" in e for e in lint_against_card(doc, dual))


def test_all_authored_exemplars_pass_schema():
    # Ask the engine where its exemplars live rather than counting directories up from
    # this file — the test moved to tests/engine/ when the engine merged into Myth Forge
    # (2026-07-29) and a hardcoded parents[1] silently found an empty directory instead
    # of failing loudly.
    from mythgauntlet.semantics.compiler import authored_dir

    files = sorted(authored_dir().glob("*.json"))
    assert len(files) >= 10
    for path in files:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        assert "card" in doc and "ccm" in doc, path.name
        errors = validate_schema(doc["ccm"])
        assert errors == [], f"{path.name}: {errors}"
