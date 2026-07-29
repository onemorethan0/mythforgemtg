"""Storm / spellslinger go-off estimator (docs/SIMULATION.md; feeds the Ceiling axis).

A best-case NUT-DRAW model: given a deck's rung-1 engine facts + the T0 mana curve, find the
earliest turn a storm chain reaches lethal. It answers "how good is the BEST draw" — exactly the
Ceiling axis's question — so a best-case model is correct here, not a claim about the average game.

Deterministic (no RNG), bounded (a hard cap on the chain length), offline. It only reaches lethal
when the FULL engine is present (a storm-granter + a per-cast/scaling payoff + spell density), so
it can never inflate a fair deck: no engine -> the chain deals ~no damage and `goes_off` is False.

Documented simplifications: the engine pieces are assumed reachable in the nut hand (capped);
opponents, targeting, interaction, and per-copy targeting rules are ignored; magecraft/treasure
engines are aggregated with a nut-draw cap; native-storm payoffs without a granter and treasure-
mana doubling are coarse in this first cut.
"""

from __future__ import annotations

from dataclasses import dataclass

from mythgauntlet.model.card import Card
from mythgauntlet.semantics import tags

_LETHAL = 40           # one goldfish opponent
_MAX_CASTS = 25        # bound the chain
_ENGINE_DEPLOY = 12    # cumulative mana before the engine (granter + payoff) is realistically down
_HAND_CAP = 12         # nut-draw: how many spells a good storm draw chains through (best-case)
_DMG_ENGINE_CAP = 4    # nut-draw cap on stacked per-cast burn (Guttersnipe-class) online
_MANA_ENGINE_CAP = 3   # nut-draw cap on stacked per-cast mana (magecraft-treasure) online
_COST_REDUCTION_CAP = 2


@dataclass(frozen=True)
class GoOffReport:
    goes_off: bool
    earliest_turn: int | None
    peak_damage: int
    storm_engine: bool  # a real storm engine (granter + spell density), for the bracket gate


@dataclass(frozen=True)
class _Spell:
    cmc: int
    ritual: int  # net mana yielded on cast
    burn: bool   # a scaling X-damage finisher


def _engine(cards: list[tuple[Card, int]]):
    """Aggregate the deck-level engine (nut-draw: assume the key pieces are online).

    Damage splits by whether STORM COPIES trigger it: `mage_dmg` (magecraft, fires on cast OR copy,
    so storm amplifies it) vs `cast_dmg` (Guttersnipe, fires only on the cast, NOT the copies)."""
    grants_storm = False
    per_cast_mana = mage_dmg = cast_dmg = cost_reduction = 0
    spells: list[_Spell] = []
    for card, _count in cards:
        fx = tags.analyze(card)
        grants_storm = grants_storm or fx.grants_storm
        per_cast_mana += fx.mana_on_cast
        mage_dmg += fx.magecraft_damage
        cast_dmg += fx.cast_damage
        cost_reduction = max(cost_reduction, fx.spell_cost_reduction)
        if card.has_type("Instant") or card.has_type("Sorcery"):
            spells.append(_Spell(card.mana_value, fx.ritual_mana, fx.scaling_burn))
    return (
        grants_storm,
        min(per_cast_mana, _MANA_ENGINE_CAP),
        min(mage_dmg, _DMG_ENGINE_CAP),
        min(cast_dmg, _DMG_ENGINE_CAP),
        min(cost_reduction, _COST_REDUCTION_CAP),
        spells,
    )


def _run_chain(spells, start_mana, grants_storm, per_cast_mana, mage_dmg, cast_dmg, cost_reduction,
               hand_cap):
    """One nut-draw turn: cast cheap spells to build the storm count + mana, then the finisher.
    Returns total damage dealt to the single opponent. Each I/S cast is copied `storm_count-1`
    times (storm counts spells cast before it); magecraft payoffs fire on the cast AND every copy,
    a cast-only payoff (Guttersnipe) fires just once."""
    mana = start_mana
    storm_count = 0
    damage = 0
    non_burn = sorted((s for s in spells if not s.burn), key=lambda s: s.cmc)[:hand_cap]
    for s in non_burn:
        cost = max(0, s.cmc - cost_reduction)
        if mana < cost or storm_count >= _MAX_CASTS:
            break  # the engine ran out of mana (or hit the cap)
        mana -= cost
        storm_count += 1
        copies = storm_count if grants_storm else 1  # storm: the cast + (storm_count-1) copies
        damage += mage_dmg * copies + cast_dmg       # Guttersnipe fires once, not per copy
        mana += per_cast_mana * copies + s.ritual
    # finisher: the cheapest affordable scaling burn, X = all remaining mana, storm-copied
    for b in sorted((s for s in spells if s.burn), key=lambda s: s.cmc):
        cost = max(0, b.cmc - cost_reduction)
        if mana >= cost:
            mana -= cost
            storm_count += 1
            copies = storm_count if grants_storm else 1
            # the burn spell + its copies each deal X (= remaining mana); magecraft rides the
            # copies too; the cast-only payoff fires once for the finisher's cast.
            damage += (mana + mage_dmg) * copies + cast_dmg
            break
    return damage


def estimate_go_off(
    cards: list[tuple[Card, int]], mana_by_turn: list[int], turns: int
) -> GoOffReport:
    """The earliest turn a nut-draw storm chain reaches lethal, or None. `mana_by_turn` is the
    T0 nut-draw mana curve (RunStats.mana_available_by_turn averaged), so the estimate is grounded
    in the deck's real mana, not a fantasy."""
    grants_storm, per_cast_mana, mage_dmg, cast_dmg, cost_reduction, spells = _engine(cards)
    # nothing that scales a chain -> can't go off (a fair deck exits here immediately)
    if not (mage_dmg or cast_dmg or any(s.burn for s in spells)) or len(spells) < 4:
        return GoOffReport(False, None, 0, False)

    earliest = None
    peak = 0
    cumulative = 0.0
    for t in range(1, turns + 1):
        mana = mana_by_turn[min(t - 1, len(mana_by_turn) - 1)] if mana_by_turn else float(t)
        cumulative += mana
        # gate: the engine (a granter + a payoff + a chain starter) must be DEPLOYABLE by now --
        # a nutty storm turn still needs the pieces on board, not turn 1. Cumulative mana is the
        # proxy; the nut hand grows as you draw/dig into the chain.
        if cumulative < _ENGINE_DEPLOY:
            continue
        hand_cap = min(_HAND_CAP, len(spells), 2 + t)
        dmg = _run_chain(
            spells, int(mana), grants_storm, per_cast_mana, mage_dmg, cast_dmg, cost_reduction,
            hand_cap,
        )
        peak = max(peak, dmg)
        if dmg >= _LETHAL and earliest is None:
            earliest = t
            break
    storm_engine = grants_storm and len(spells) >= _HAND_CAP
    return GoOffReport(earliest is not None, earliest, peak, storm_engine)
