"""Semantics-layer data structures.

Rung 1 of the semantics ladder (see docs/CARD_SEMANTICS.md): the EffectVector, a cheap
statistical approximation of what a card does. Rungs 2–3 (the CCM) land here in Phase 3.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EffectVector:
    """Approximate functional profile of a card, derived from Oracle-text heuristics."""

    ramp_sources: int = 0  # permanent mana sources added when this resolves
    fetches_land: bool = False  # ramp via searching a land onto the battlefield
    draw_cards: int = 0  # immediate cards drawn on resolution
    engine_draw: int = 0  # repeatable draws per turn once on the battlefield (triggered)
    tutor: bool = False  # searches library for a nonland card
    removal: int = 0  # targeted answers
    board_wipe: bool = False
    counterspell: bool = False
    enters_tapped: bool = False  # lands only
    cheats_creatures: bool = False  # puts creatures from hand onto the battlefield (Kaalia class)
    # storm / spellslinger go-off engine (docs/SIMULATION.md, feeds the Ceiling axis)
    grants_storm: bool = False  # "spells you cast have storm" (Prismari class)
    mana_on_cast: int = 0  # mana per cast-OR-COPY (Storm-Kiln magecraft treasure) -- copies amplify
    magecraft_damage: int = 0  # burn per cast OR COPY (magecraft) -- storm copies each trigger it
    cast_damage: int = 0  # burn per CAST only (Guttersnipe class) -- storm copies do NOT trigger it
    scaling_burn: bool = False  # an X-damage-to-player finisher (Fireball / Comet Storm class)
    spell_cost_reduction: int = 0  # your instant/sorcery spells cost {N} less
    self_reduction_per_creature: int = 0  # THIS spell costs {N} less for each creature in play
    ritual_mana: int = 0  # net mana this spell yields when cast (Dark Ritual class), for storm
    # go-wide / overrun finisher (docs/SIMULATION.md, feeds the Ceiling axis): a ONE-SHOT team pump
    overrun_pump: int = 0  # "creatures you control get +N/+N ... until end of turn" (Overrun class)
    overrun_scales: bool = False  # the pump is +X/+X where X scales with your board (Craterhoof)
    # ROLE-ONLY facts (2026-10-18). Read by `ratings.redundancy.card_roles` and nothing in the
    # simulator: each is a function a player counts in a role but that tier0/tier2 must NOT
    # spend the way they spend the fields above (a Naturalize is not a creature kill, a
    # Treasure is not an untapping mana source, a cost reducer is not a mana ability).
    noncreature_removal: bool = False  # answers ONLY a noncreature permanent (Crush Contraband)
    treasure_ramp: int = 0  # Treasure made by a REPEATABLE trigger/activation, net of its cost
    cost_reduction: int = 0  # your spells cost {N} less / gain improvise-convoke-affinity
    top_of_library: bool = False  # standing permission to cast/play from the top (Mystic Forge)
    alt_win: bool = False  # "you win the game" (Mechanized Production, Thassa's Oracle)
    extra_combat: bool = False  # "an additional combat phase"
    team_anthem: bool = False  # STATIC team pump (Tempered Steel); not a tribe or colour lord
    impact: float = 0.0  # generic resolution-value prior in [0, 1] (popularity-seeded)
