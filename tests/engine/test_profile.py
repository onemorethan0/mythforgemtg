"""PlayProfile derivation: CCM (rung 2/3) vs EffectVector fallback (rung 1)."""

from mythgauntlet.semantics.profile import profile_for, profile_from_ccm
from mythgauntlet.semantics.tags import analyze


def test_ccm_spell_effect_draw(make_card):
    card = make_card("Insight", mana_cost="{2}{U}", type_line="Sorcery")
    doc = {
        "name": "Insight", "ccm_version": 1, "rung": 2, "cost": {"mana": "{2}{U}"},
        "types": ["sorcery"],
        "abilities": [{"kind": "spell_effect", "effects": [{"op": "draw", "count": 3}]}],
    }
    profile = profile_for(card, doc)
    assert profile.rung == 2
    assert profile.draw == 3
    assert profile.engine_draw == 0


def test_ccm_destroy_all_is_wipe(make_card):
    card = make_card("Judgment", mana_cost="{2}{W}{W}", type_line="Sorcery")
    doc = {
        "name": "Judgment", "ccm_version": 1, "cost": {"mana": "{2}{W}{W}"},
        "types": ["sorcery"],
        "abilities": [{
            "kind": "spell_effect",
            "effects": [{"op": "destroy", "target": {"type": "creature", "count": "all"}}],
        }],
    }
    profile = profile_from_ccm(doc, card, analyze(card))
    assert profile.wipe
    assert profile.removal == 0


def test_ccm_targeted_destroy_is_removal(make_card):
    card = make_card("Doom Spell", mana_cost="{1}{B}", type_line="Instant")
    doc = {
        "name": "Doom Spell", "ccm_version": 1, "cost": {"mana": "{1}{B}"},
        "types": ["instant"],
        "abilities": [{
            "kind": "spell_effect",
            "effects": [{"op": "destroy", "target": {"type": "creature", "count": 1}}],
        }],
    }
    assert profile_from_ccm(doc, card, analyze(card)).removal == 1


def test_ccm_periodic_draw_is_engine_on_permanents_only(make_card):
    doc = {
        "name": "Arena", "ccm_version": 1, "cost": {"mana": "{1}{B}{B}"},
        "types": ["enchantment"],
        "abilities": [{
            "kind": "triggered", "trigger": {"event": "upkeep"},
            "effects": [{"op": "draw", "count": 1}],
        }],
    }
    enchantment = make_card("Arena", mana_cost="{1}{B}{B}", type_line="Enchantment")
    assert profile_from_ccm(doc, enchantment, analyze(enchantment)).engine_draw == 1
    sorcery = make_card("Arena Sorcery", mana_cost="{1}{B}{B}", type_line="Sorcery")
    assert profile_from_ccm(doc, sorcery, analyze(sorcery)).engine_draw == 0


def test_ccm_mana_rock_ramps(make_card):
    card = make_card("Rock", mana_cost="{2}", type_line="Artifact", produced_mana=("C",))
    doc = {
        "name": "Rock", "ccm_version": 1, "cost": {"mana": "{2}"}, "types": ["artifact"],
        "abilities": [{
            "kind": "mana_ability", "cost": {"tap": True},
            "effects": [{"op": "add_mana", "amount": 2, "colors": "C"}],
        }],
    }
    assert profile_from_ccm(doc, card, analyze(card)).ramp_sources == 2


def test_ccm_damage_split_face_vs_any(make_card):
    card = make_card("Bolt Spell", mana_cost="{R}", type_line="Instant")
    doc = {
        "name": "Bolt Spell", "ccm_version": 1, "cost": {"mana": "{R}"}, "types": ["instant"],
        "abilities": [{
            "kind": "spell_effect",
            "effects": [{"op": "deal_damage", "amount": 3, "target": {"type": "any"}}],
        }],
    }
    profile = profile_from_ccm(doc, card, analyze(card))
    assert profile.damage_any == 3 and profile.damage_face == 0


def test_malformed_trigger_and_cost_tolerated(make_card):
    """Hand-authored CCMs with a string trigger or string cost must not crash derivation."""
    card = make_card("Odd", mana_cost="{1}{R}", type_line="Creature — Wizard")
    doc = {
        "name": "Odd", "ccm_version": 1, "cost": {"mana": "{1}{R}"}, "types": ["creature"],
        "abilities": [
            {"kind": "triggered", "trigger": "etb", "effects": [{"op": "draw", "count": 1}]},
            {"kind": "activated", "cost": "{2}, T", "effects": [{"op": "draw", "count": 1}]},
            {"kind": "activated", "cost": {"mana": 2}, "effects": [{"op": "draw", "count": 1}]},
        ],
    }
    profile = profile_for(card, doc)  # must not raise
    assert profile.rung is not None


def test_x_damage_to_each_creature_is_a_wipe(make_card):
    card = make_card("Quake", mana_cost="{X}{R}", type_line="Sorcery")
    doc = {
        "name": "Quake", "ccm_version": 1, "cost": {"mana": "{X}{R}"}, "types": ["sorcery"],
        "abilities": [{"kind": "spell_effect", "effects": [
            {"op": "deal_damage", "amount": "X", "target": {"type": "creature", "count": "all"}}
        ]}],
    }
    assert profile_for(card, doc).wipe is True


def test_resolution_summary_sourced_from_interpreter_per_effect_removal(make_card):
    """Retirement (2026-07-21): the on-resolution summary is folded from the interpreter's
    effects, which kill exactly ONE creature per destroy effect -- so `removal` counts effects,
    not a `count: N` field. Two separate destroy effects => removal 2 (matches _apply_resolved)."""
    card = make_card("Double Kill", mana_cost="{2}{B}", type_line="Sorcery")
    doc = {
        "name": "Double Kill", "ccm_version": 1, "cost": {"mana": "{2}{B}"}, "types": ["sorcery"],
        "abilities": [{"kind": "spell_effect", "effects": [
            {"op": "destroy", "target": {"type": "creature", "count": 1}},
            {"op": "destroy", "target": {"type": "creature", "count": 1}},
        ]}],
    }
    assert profile_for(card, doc).removal == 2


def test_opponent_draw_rider_does_not_inflate_own_draw(make_card):
    """A "each opponent draws" downside must not read as the caster drawing (a deliberate
    correction the raw flattening missed -- the interpreter tags the draw's `who`)."""
    card = make_card("Group Hug", mana_cost="{2}{U}", type_line="Sorcery")
    doc = {
        "name": "Group Hug", "ccm_version": 1, "cost": {"mana": "{2}{U}"}, "types": ["sorcery"],
        "abilities": [{"kind": "spell_effect", "effects": [
            {"op": "draw", "count": 2},                       # you draw 2
            {"op": "draw", "count": 1, "who": "each_opponent"},  # opponents draw 1 (downside)
        ]}],
    }
    assert profile_for(card, doc).draw == 2  # not 3


def test_self_destruction_not_counted_as_removal(make_card):
    card = make_card("Sac Outlet", mana_cost="{B}", type_line="Sorcery")
    doc = {
        "name": "Sac Outlet", "ccm_version": 1, "cost": {"mana": "{B}"}, "types": ["sorcery"],
        "abilities": [{"kind": "spell_effect", "effects": [
            {"op": "destroy", "target": {"type": "creature", "controller": "you", "count": 1}}
        ]}],
    }
    profile = profile_for(card, doc)
    assert profile.removal == 0 and profile.wipe is False


def test_string_target_is_tolerated_not_crashed(make_card):
    """A gate-passing compiled CCM can emit `target`/`what` as a bare string; the profile
    reader must coerce it, not crash (regression: the pod field surfaced such a card)."""
    card = make_card("Odd Target", mana_cost="{1}{R}", type_line="Sorcery")
    doc = {
        "name": "Odd Target", "ccm_version": 1, "cost": {"mana": "{1}{R}"}, "types": ["sorcery"],
        "abilities": [{"kind": "spell_effect", "effects": [
            {"op": "deal_damage", "amount": 3, "target": "any target"},        # str, not dict
            {"op": "destroy", "target": "target creature"},
            {"op": "search_library", "what": "a land", "to": "battlefield"},
        ]}],
    }
    profile = profile_for(card, doc)  # must not raise
    assert profile.damage_any == 3  # a stringy target falls back to non-player -> "any"


def test_malformed_ability_entries_tolerated(make_card):
    """Hand-authored CCMs never pass compiler gates; profile must not crash on junk."""
    card = make_card("Odd Card", mana_cost="{1}", type_line="Artifact")
    doc = {
        "name": "Odd Card", "ccm_version": 1, "cost": {"mana": "{1}"}, "types": ["artifact"],
        "abilities": [
            None,
            "not a dict",
            {"kind": "spell_effect", "effects": ["junk", {"op": "draw", "count": 1}]},
        ],
    }
    profile = profile_for(card, doc)
    assert profile.draw == 1  # the one well-formed effect still applies


def test_precomputed_fx_matches_internal_analysis(make_card):
    card = make_card(
        "Insight Spell", mana_cost="{2}{U}", type_line="Sorcery", oracle_text="Draw two cards."
    )
    assert profile_for(card, None, fx=analyze(card)) == profile_for(card, None)


def test_activated_ability_parsed(make_card):
    card = make_card("Pinger", mana_cost="{1}{R}", type_line="Creature — Wizard")
    doc = {
        "name": "Pinger", "ccm_version": 1, "cost": {"mana": "{1}{R}"}, "types": ["creature"],
        "abilities": [
            {"kind": "activated", "cost": {"tap": True},
             "effects": [{"op": "deal_damage", "amount": 1, "target": {"type": "any"}}]},
            {"kind": "activated", "cost": {"mana": "{2}"},
             "effects": [{"op": "draw", "count": 1}]},
            {"kind": "activated", "cost": {"mana": "{1}", "sacrifice_self": True},
             "effects": [{"op": "draw", "count": 1}]},  # one-shot: skipped
        ],
    }
    profile = profile_for(card, doc)
    assert len(profile.activated) == 2
    ping, outlet = profile.activated
    assert ping.needs_tap and ping.cost_mana == 0 and ping.damage_any == 1
    assert not outlet.needs_tap and outlet.cost_mana == 2 and outlet.draw == 1


def test_free_untapped_activation_skipped(make_card):
    card = make_card("Degenerate", mana_cost="{1}", type_line="Artifact")
    doc = {
        "name": "Degenerate", "ccm_version": 1, "cost": {"mana": "{1}"}, "types": ["artifact"],
        "abilities": [{"kind": "activated", "cost": {},
                       "effects": [{"op": "gain_life", "amount": 1}]}],
    }
    assert profile_for(card, doc).activated == ()


def test_death_trigger_parsed(make_card):
    card = make_card("Martyr", mana_cost="{1}{B}", type_line="Creature — Cleric")
    doc = {
        "name": "Martyr", "ccm_version": 1, "cost": {"mana": "{1}{B}"}, "types": ["creature"],
        "abilities": [{
            "kind": "triggered", "trigger": {"event": "death"},
            "effects": [
                {"op": "lose_life", "amount": 2, "who": "each_opponent"},
                {"op": "gain_life", "amount": 1},
            ],
        }],
    }
    death = profile_for(card, doc).death
    assert death is not None
    assert death.drain == 2 and death.gain_life == 1


def test_fallback_uses_effect_vector(make_card):
    card = make_card(
        "Growth Ritual", mana_cost="{1}{G}", type_line="Sorcery",
        oracle_text="Search your library for a basic land card, put it onto the "
        "battlefield tapped, then shuffle.",
    )
    profile = profile_for(card, None)
    assert profile.rung == 1
    assert profile.fetches_land
