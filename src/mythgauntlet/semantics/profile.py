"""PlayProfile: the bridge from card semantics to the Tier-2 engine.

A PlayProfile flattens what a card does into fields the adversarial engine executes:
one-shot resolution effects plus per-turn engines. It is derived from the best available
semantics rung — a CCM (rung 2/3) when the store has one, else the rung-1 EffectVector —
and records which, so reports stay honest.

The CCM interpreter (`semantics/interpreter.py`) is now the SINGLE source of truth for what
a CCM card does on resolution: the T2 engine executes CCM cards' on-resolution effects (and
event triggers) through it per-effect (`sim/tier2._apply_resolved`). As of 2026-07-21 the old
parallel on-resolution *flattening* is RETIRED (docs/ROADMAP.md Phase 6): `profile_from_ccm`
no longer re-derives on-resolution fields with a second hand-rolled walk — it FOLDS the same
interpreted effects into `PlayProfile`'s `draw/removal/wipe/damage_*/tokens/gain_life/
fetches_land` fields, which now serve only as the greedy agent's VALUATION prior and reactive-
answer detection (never as an executor). The prior therefore can't drift from execution.

For CCM cards this flattening still supplies the STRUCTURAL/prior fields (creature stats, mana
abilities, engine draw, activated/death triggers, the interpreter-folded resolution summary);
rung-1 cards (no CCM) keep the whole `profile_from_fx` EffectVector path. Deliberate limits
(docs/ROADMAP.md Phase 6):
  - Activated abilities ARE executed when repeatable and payable with generic mana
    (color requirements ignored); abilities costing a sacrifice or life are skipped.
  - Death triggers fire on the permanent's own death only ("whenever ANOTHER creature
    dies" over-narrows to self — under-counts, never over-counts).
  - Event triggers (cast/attack/upkeep/landfall/...): the T2 engine EXECUTES these at their
    event via the interpreter (sim/tier2.py); `engine_draw` here stays the periodic-draw
    valuation prior (the engine zeroes it on CCM permanents to avoid double-count).
  - The valuation summary uses DefaultResolver conventions (X/each -> 1; optional/conditional
    assumed to happen); real X/each resolve against live board state at execution time only.
"""

from __future__ import annotations

from dataclasses import dataclass

from mythgauntlet.model.card import Card, ManaCost
from mythgauntlet.semantics import tags
from mythgauntlet.semantics.interpreter import interpret_ability
from mythgauntlet.semantics.model import EffectVector

_PERIODIC_TRIGGERS = {"upkeep", "draw_step", "end_step", "landfall", "cast_creature",
                      "cast_spell", "attack", "combat_damage_to_player"}
_REMOVAL_TARGET_TYPES = {"creature", "permanent", "artifact", "enchantment", "any",
                         "planeswalker"}


@dataclass(frozen=True)
class ActivatedEffect:
    """A repeatable activated ability the engine can pay (generic) mana to use."""

    cost_mana: int  # mana value of the activation cost; colors ignored at this fidelity
    needs_tap: bool  # tap-limited: once per turn, respects summoning sickness
    draw: int = 0
    damage_face: int = 0
    damage_any: int = 0
    tokens: tuple[int, int, int] | None = None
    gain_life: int = 0


@dataclass(frozen=True)
class DeathEffect:
    """Fires when the permanent dies (self-death only at this fidelity)."""

    draw: int = 0
    drain: int = 0  # opponent loses this much life
    gain_life: int = 0
    tokens: tuple[int, int, int] | None = None


@dataclass(frozen=True)
class PlayProfile:
    rung: int
    draw: int = 0  # cards drawn on resolution
    ramp_sources: int = 0  # persistent mana sources added (rocks/dorks)
    fetches_land: bool = False  # pulls a land from library onto the battlefield
    removal: int = 0  # targeted kills available on resolution
    wipe: bool = False  # destroys/exiles all creatures
    damage_face: int = 0  # direct damage aimable at a player
    damage_any: int = 0  # direct damage aimable anywhere
    tokens: tuple[int, int, int] | None = None  # (count, power, toughness)
    gain_life: int = 0
    engine_draw: int = 0  # extra draws per turn while this permanent is on board
    activated: tuple[ActivatedEffect, ...] = ()  # repeatable outlets while on board
    death: DeathEffect | None = None
    impact: float = 0.0  # generic value prior (rung-1 popularity seed)
    counter: bool = False  # counters target spell on the stack (T2 stack MVP)
    is_instant: bool = False  # castable at instant speed (reactive windows in T2)
    tutor: bool = False  # searches the library for a specific card (cEDH combo assembly)


def _amount(value, default: int = 1) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return max(0, value)
    return default  # "X" and friends resolve as 1 at this fidelity


def _activated_from(ability: dict, effects: list[dict]) -> ActivatedEffect | None:
    cost = ability.get("cost")
    if not isinstance(cost, dict):  # tolerate a malformed hand-authored cost (str/None/…)
        cost = {}
    if cost.get("sacrifice_self"):
        return None  # one-shot, not a repeatable outlet
    mana = cost.get("mana")
    cost_mana = ManaCost.parse(mana if isinstance(mana, str) else "").mana_value
    needs_tap = bool(cost.get("tap"))
    if cost_mana == 0 and not needs_tap:
        return None  # nothing bounds it; skip rather than loop
    draw = face = any_dmg = life = 0
    tokens: tuple[int, int, int] | None = None
    for effect in effects:
        op = effect.get("op")
        if op == "draw":
            draw += min(_amount(effect.get("count"), 1), 2)
        elif op == "deal_damage":
            target = _as_dict(effect.get("target"))
            amount = _amount(effect.get("amount"), 1)
            if target.get("type") in ("player", "opponent"):
                face += amount
            else:
                any_dmg += amount
        elif op == "create_token":
            tokens = (
                _amount(effect.get("count"), 1),
                _amount(effect.get("power"), 1),
                _amount(effect.get("toughness"), 1),
            )
        elif op == "gain_life":
            life += _amount(effect.get("amount"), 1)
    if not (draw or face or any_dmg or life or tokens):
        return None
    return ActivatedEffect(
        cost_mana=cost_mana, needs_tap=needs_tap, draw=draw,
        damage_face=face, damage_any=any_dmg, tokens=tokens, gain_life=life,
    )


def _death_from(effects: list[dict]) -> DeathEffect | None:
    draw = drain = life = 0
    tokens: tuple[int, int, int] | None = None
    for effect in effects:
        op = effect.get("op")
        target = _as_dict(effect.get("target"))
        if op == "draw":
            draw += _amount(effect.get("count"), 1)
        elif op == "lose_life" and effect.get("who", "opponent") in (
            "opponent", "each_opponent", "each",
        ):
            drain += _amount(effect.get("amount"), 1)
        elif op == "deal_damage" and target.get("type") in ("player", "opponent"):
            drain += _amount(effect.get("amount"), 1)
        elif op == "gain_life":
            life += _amount(effect.get("amount"), 1)
        elif op == "create_token":
            tokens = (
                _amount(effect.get("count"), 1),
                _amount(effect.get("power"), 1),
                _amount(effect.get("toughness"), 1),
            )
    if not (draw or drain or life or tokens):
        return None
    return DeathEffect(draw=draw, drain=drain, gain_life=life, tokens=tokens)


def _has_counter_spell(doc: dict) -> bool:
    """True if any ability counters a spell (CCM op `counter_spell`)."""
    for ability in doc.get("abilities") or []:
        if not isinstance(ability, dict):
            continue
        for effect in ability.get("effects") or []:
            if isinstance(effect, dict) and effect.get("op") == "counter_spell":
                return True
    return False


def _is_tutor(doc: dict) -> bool:
    """True if any ability searches the library to fetch a specific card (a tutor). A basic-land
    fetch to the battlefield is ramp (`fetches_land`), NOT a combo tutor, so it doesn't count."""
    for ability in doc.get("abilities") or []:
        if not isinstance(ability, dict):
            continue
        for effect in ability.get("effects") or []:
            if not isinstance(effect, dict) or effect.get("op") != "search_library":
                continue
            what = _as_dict(effect.get("what"))
            to = str(effect.get("to", "hand")).lower()
            if what.get("type") == "land" and to == "battlefield":
                continue  # land ramp, not a tutor
            return True
    return False


@dataclass(frozen=True)
class _ResolutionSummary:
    """Aggregate of a CCM card's on-resolution effects, for the greedy VALUATION prior and
    reactive-answer detection ONLY. The interpreter (`sim.tier2._apply_resolved` over
    `interpret_ability`) is the single source of truth for what actually happens on
    resolution; this summary is folded from those SAME interpreted effects so the prior can
    never drift from execution (the retirement of the old parallel flattening — Phase 6)."""

    draw: int = 0
    removal: int = 0
    wipe: bool = False
    damage_face: int = 0
    damage_any: int = 0
    gain_life: int = 0
    fetches_land: bool = False
    tokens: tuple[int, int, int] | None = None


def _resolution_abilities(doc: dict) -> list[dict]:
    """The abilities that fire on resolution: one-shot spell effects + ETB triggers (mirrors
    sim.tier2._resolution_abilities; the interpreter executes exactly this set)."""
    out = []
    for ability in doc.get("abilities") or []:
        if not isinstance(ability, dict):
            continue
        kind = ability.get("kind")
        trig = ability.get("trigger")
        event = trig.get("event") if isinstance(trig, dict) else None
        if kind == "spell_effect" or (kind == "triggered" and event == "etb"):
            out.append(ability)
    return out


def _as_dict(value: object) -> dict:
    """A `target`/`what` field the compiler occasionally emits as a bare string (not a dict);
    coerce it to an empty dict so the readers never crash on a malformed-but-gate-passing CCM."""
    return value if isinstance(value, dict) else {}


def _targets_all(target: dict) -> bool:
    return target.get("count") == "all" or target.get("controller") == "each"


def _resolution_is_wipe(doc: dict) -> bool:
    """Whether an on-resolution effect sweeps the board — read from the RAW effects so a
    variable/X sweeper ("deal X to each creature", Quake) is still recognized after the
    interpreter would have collapsed X to 1. Matches the retired flattening's wipe rule."""
    for ability in _resolution_abilities(doc):
        for e in ability.get("effects") or []:
            if not isinstance(e, dict):
                continue
            op, target = e.get("op"), _as_dict(e.get("target"))
            if not _targets_all(target) or target.get("controller") == "you":
                continue
            kind = target.get("type") or "creature"
            if op in ("destroy", "exile") and kind in _REMOVAL_TARGET_TYPES:
                return True
            if op == "deal_damage":
                raw = e.get("amount")
                is_int = isinstance(raw, int) and not isinstance(raw, bool)
                if not is_int or raw >= 3:  # a fixed >=3 or any variable/X sweep
                    return True
    return False


def _summarize_resolution(doc: dict) -> _ResolutionSummary:
    """Interpret the on-resolution abilities (DefaultResolver: X/each -> 1, matching the old
    flattening) and fold them with the SAME op categorization `_apply_resolved` executes, so
    the valuation prior stays consistent with what the engine does. Differences from the
    retired hand-rolled flattening are deliberate corrections toward execution: removal counts
    one kill per destroy effect (as `_apply_resolved` kills one), and opponent-draw riders
    don't inflate the caster's own-draw value. `wipe` comes from `_resolution_is_wipe` (raw,
    to keep X-sweeper recognition); board-target destroy/damage add nothing else."""
    draw = removal = face = any_dmg = life = 0
    fetches = False
    tokens: tuple[int, int, int] | None = None
    wipe = _resolution_is_wipe(doc)
    for ability in _resolution_abilities(doc):
        for eff in interpret_ability(ability):  # DefaultResolver (X -> 1)
            op, pr = eff.op, eff.params
            if op == "draw":
                if pr.get("who") not in ("opponent", "each_opponent"):
                    draw += max(0, pr.get("count", 1))
            elif op in ("destroy", "exile"):
                target = _as_dict(pr.get("target"))
                if target.get("controller") == "you":
                    continue  # destroying your own permanents isn't interaction/removal
                if (target.get("type") or "creature") not in _REMOVAL_TARGET_TYPES:
                    continue
                if not _targets_all(target):
                    removal += 1  # `_apply_resolved` kills exactly one per destroy effect
            elif op == "deal_damage":
                target = _as_dict(pr.get("target"))
                amount = max(0, pr.get("amount", 1))
                if not amount or _targets_all(target):
                    continue  # board-sweep damage is captured by `wipe`, not face/any
                if target.get("type") in ("player", "opponent"):
                    face += amount
                else:
                    any_dmg += amount
            elif op == "create_token":
                tokens = (
                    max(0, pr.get("count", 1)),
                    max(0, pr.get("power", 1)),
                    max(0, pr.get("toughness", 1)),
                )
            elif op == "gain_life":
                life += max(0, pr.get("amount", 1))
            elif op == "lose_life":
                if pr.get("who", "opponent") in ("opponent", "each_opponent", "each"):
                    face += max(0, pr.get("amount", 1))
            elif op == "search_library":
                what = _as_dict(pr.get("what"))
                to = str(pr.get("to", "hand")).lower()
                if what.get("type") == "land" and to == "battlefield":
                    fetches = True
    return _ResolutionSummary(
        draw=draw, removal=removal, wipe=wipe, damage_face=face, damage_any=any_dmg,
        gain_life=life, fetches_land=fetches, tokens=tokens,
    )


def profile_from_ccm(doc: dict, card: Card, fx: EffectVector) -> PlayProfile:
    ramp = engine = 0
    activated: list[ActivatedEffect] = []
    death_effects: list[dict] = []

    is_permanent = not (card.has_type("Instant") or card.has_type("Sorcery"))

    for ability in doc.get("abilities") or []:
        if not isinstance(ability, dict):
            continue  # tolerate malformed hand-authored entries (gates only cover compiled)
        kind = ability.get("kind")
        trig = ability.get("trigger")
        trigger = trig.get("event") if isinstance(trig, dict) else None  # tolerate str/None
        effects = [e for e in ability.get("effects") or [] if isinstance(e, dict)]

        if kind == "mana_ability" and is_permanent and not card.is_land:
            for effect in effects:
                if effect.get("op") == "add_mana":
                    ramp += _amount(effect.get("amount"), 1)
        elif kind == "activated" and is_permanent:
            act = _activated_from(ability, effects)
            if act is not None:
                activated.append(act)
        elif kind == "triggered" and trigger == "death" and is_permanent:
            death_effects.extend(effects)
        elif kind == "triggered" and trigger in _PERIODIC_TRIGGERS:
            for effect in effects:  # only periodic DRAW feeds the engine_draw prior; other
                if effect.get("op") == "draw":  # periodic effects EXECUTE at their event
                    engine += min(_amount(effect.get("count"), 1), 2)

    # On-resolution effects (spell_effect + ETB): sourced from the interpreter, not a parallel
    # flattening, so this VALUATION/reactive summary matches what `_apply_resolved` executes.
    r = _summarize_resolution(doc)

    return PlayProfile(
        rung=doc.get("rung", 2),
        draw=r.draw,
        ramp_sources=ramp,
        fetches_land=r.fetches_land,
        removal=r.removal,
        wipe=r.wipe,
        damage_face=r.damage_face,
        damage_any=r.damage_any,
        tokens=r.tokens,
        gain_life=r.gain_life,
        engine_draw=engine if is_permanent else 0,
        activated=tuple(activated),
        death=_death_from(death_effects),
        impact=fx.impact,
        counter=_has_counter_spell(doc),
        is_instant=card.has_type("Instant"),
        tutor=_is_tutor(doc),
    )


def profile_from_fx(fx: EffectVector, card: Card) -> PlayProfile:
    is_permanent = not (card.has_type("Instant") or card.has_type("Sorcery"))
    return PlayProfile(
        rung=1,
        draw=fx.draw_cards,
        ramp_sources=0 if fx.fetches_land else fx.ramp_sources,
        fetches_land=fx.fetches_land,
        removal=fx.removal,
        wipe=fx.board_wipe,
        engine_draw=fx.engine_draw if is_permanent else 0,
        impact=fx.impact,
        counter=fx.counterspell,
        is_instant=card.has_type("Instant"),
    )


def profile_for(
    card: Card, ccm_doc: dict | None, fx: EffectVector | None = None
) -> PlayProfile:
    """Best-rung profile. Pass `fx` when the caller already ran tags.analyze."""
    if fx is None:
        fx = tags.analyze(card)
    if ccm_doc is not None:
        return profile_from_ccm(ccm_doc, card, fx)
    return profile_from_fx(fx, card)
