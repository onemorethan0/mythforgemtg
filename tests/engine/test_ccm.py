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


def test_trigger_evidence_reads_the_wording_cards_actually_use(make_card):
    """Gate 3 must not reject a trigger the card plainly has, written another way.

    All three wordings below are taken from real cards that the v10 refresh blocked. The
    `tap_for_mana` one is not hypothetical: `\\btaps? ` never matched the PASSIVE "is
    tapped for mana", and on 2026-08-07 that demoted Storm Cauldron and Trace of
    Abundance from accepted to quarantined — the refresh campaign's first two losses.

    The negative half is the point of the test. Widening evidence is the direction that
    lets a FABRICATED event through, so each pattern stays scoped: "deals damage to an
    opponent" is the card dealing damage, not being dealt it, and must still fail.
    """
    def evidence(event, oracle):
        card = make_card("Probe", mana_cost="{1}", type_line="Artifact", oracle_text=oracle)
        doc = dict(GOOD_DRAW_CCM, types=["artifact"], abilities=[
            {"kind": "triggered", "trigger": {"event": event},
             "effects": [{"op": "draw", "count": 1}]},
        ])
        return not any("has no support" in e for e in cross_check(doc, card))

    # Real wordings that must be RECOGNISED
    assert evidence("tap_for_mana", "Whenever a Mountain is tapped for mana, draw a card.")
    assert evidence("dealt_damage",
                    "Whenever a source you control deals damage to you, draw a card.")
    assert evidence("dealt_damage",
                    "Whenever a source an opponent controls deals damage to this creature, "
                    "draw a card.")
    assert evidence("leaves_battlefield",
                    "When this Aura is put into a graveyard from the battlefield, draw a card.")

    # Wordings that must still be REJECTED
    assert not evidence("dealt_damage",
                        "Whenever this creature deals damage to an opponent, draw a card."), (
        "dealing damage is not being dealt damage"
    )
    assert not evidence("tap_for_mana",
                        "Whenever you cast a red spell, you may untap this creature."), (
        "'untap' must not read as a tap-for-mana trigger"
    )
    assert not evidence("tap_for_mana",
                        "{T}: This creature deals 1 damage to any target."), (
        "tapping for an effect is not tapping for mana"
    )
    assert not evidence("etb", "{T}: Draw a card, then discard a card."), (
        "a card that never mentions entering has no ETB trigger"
    )


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


def _triggered(event, oracle, make_card, name="Trigger Test", effects=None):
    doc = {
        "name": name, "ccm_version": 1, "cost": {"mana": "{1}{R}"},
        "types": ["creature"],
        "abilities": [{
            "kind": "triggered", "trigger": {"event": event},
            "effects": effects or [{"op": "create_token", "count": 1, "power": 0,
                                    "toughness": 0, "types": ["treasure"]}],
        }],
    }
    card = make_card(name, mana_cost="{1}{R}", type_line="Creature — Dragon",
                     oracle_text=oracle)
    return doc, card


def test_cross_check_rejects_smaug_noncombat_damage_as_combat(make_card):
    """The exact card that exposed this: 'noncombat damage' is not combat damage.

    Smaug the Impenetrable — "Whenever Smaug is dealt noncombat damage, create that many
    Treasure tokens" — compiled as combat_damage_to_player and was ACCEPTED, so the engine
    minted Treasures every time he connected in combat: an ability the card does not have.
    The substring "combat damage" is literally present inside "noncombat damage", so the
    evidence pattern has to exclude the negation rather than merely search for the phrase.
    """
    oracle = ("Flying, indestructible, haste\nWhenever Smaug is dealt noncombat damage, "
              "create that many Treasure tokens.")
    doc, card = _triggered("combat_damage_to_player", oracle, make_card, name="Smaug")
    assert any("combat_damage_to_player" in e for e in cross_check(doc, card))

    # dealt_damage is the honest answer — the engine doesn't execute it, so the card
    # under-counts instead of fabricating Treasures.
    ok, card = _triggered("dealt_damage", oracle, make_card, name="Smaug")
    assert not any("trigger event" in e for e in cross_check(ok, card))


def test_cross_check_rejects_blocking_declared_as_attacking(make_card):
    """Blocking is the other side of combat; 155 cards had it mapped to attack."""
    oracle = "Whenever this creature blocks a creature, return that creature to its owner's hand."
    doc, card = _triggered("attack", oracle, make_card)
    assert any("attack" in e for e in cross_check(doc, card))
    ok, card = _triggered("blocks", oracle, make_card)
    assert not any("trigger event" in e for e in cross_check(ok, card))


def test_cross_check_rejects_self_cast_declared_as_cast_creature(make_card):
    """"When you cast THIS spell" fires once; cast_creature fires on every creature spell.

    112 cards carried this, turning a one-shot into a repeating engine.
    """
    oracle = "When you cast this spell, target opponent loses 3 life and you gain 3 life."
    doc, card = _triggered("cast_creature", oracle, make_card)
    assert any("cast_creature" in e for e in cross_check(doc, card))
    ok, card = _triggered("self_cast", oracle, make_card)
    assert not any("trigger event" in e for e in cross_check(ok, card))


def test_cross_check_rejects_land_to_graveyard_as_landfall(make_card):
    oracle = ("Whenever a land is put into a graveyard from the battlefield, "
              "this creature gets +1/+0 until end of turn.")
    doc, card = _triggered("landfall", oracle, make_card)
    assert any("landfall" in e for e in cross_check(doc, card))


def test_cross_check_rejects_an_invented_etb(make_card):
    """The most common failure (696 cards): an etb trigger on a card that never enters."""
    oracle = "{T}: Prevent the next 1 damage that would be dealt to any target this turn."
    doc, card = _triggered("etb", oracle, make_card)
    assert any("etb" in e for e in cross_check(doc, card))


def test_cross_check_licenses_reminder_text_trigger_keywords(make_card):
    """Cascade IS a cast trigger and modular IS a death trigger — the parenthetical that
    says so is stripped before the check, exactly as for keyword-implied OPS."""
    doc, card = _triggered("cast_spell", "Reach, trample\nCascade", make_card)
    assert not any("trigger event" in e for e in cross_check(doc, card))
    doc, card = _triggered("death", "Modular 3", make_card)
    assert not any("trigger event" in e for e in cross_check(doc, card))
    doc, card = _triggered("death", "Soulshift 8", make_card)
    assert not any("trigger event" in e for e in cross_check(doc, card))


def test_cross_check_always_allows_other(make_card):
    """'other' is the escape hatch — it must never be penalised, or the model will pick a
    wrong-but-specific event to satisfy the gate."""
    doc, card = _triggered("other", "Some text the vocabulary cannot express.", make_card)
    assert not any("trigger event" in e for e in cross_check(doc, card))


def test_cross_check_accepts_correct_events(make_card):
    for event, oracle in [
        ("etb", "When this creature enters, draw a card."),
        ("death", "When this creature dies, each opponent loses 2 life."),
        ("attack", "Whenever this creature attacks, create a 1/1 Soldier token."),
        ("upkeep", "At the beginning of your upkeep, scry 1."),
        ("landfall", "Whenever a land enters under your control, gain 1 life."),
        ("combat_damage_to_player",
         "Whenever this creature deals combat damage to a player, draw a card."),
        ("saga_chapter", "I — Draw a card."),
        ("becomes_blocked", "Whenever this creature becomes blocked, it gets +2/+0."),
    ]:
        doc, card = _triggered(event, oracle, make_card)
        assert not any("trigger event" in e for e in cross_check(doc, card)), \
            f"{event} should be supported by {oracle!r}"
