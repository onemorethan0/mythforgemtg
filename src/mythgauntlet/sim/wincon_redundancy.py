"""Wincon redundancy — PLAN_CLOCK.md Phase 2 / docs/SPEC_wincon_redundancy.md.

"How many pieces of interaction must the table spend to stop the win?" for the four
non-combat kill mechanisms `sim/clock.apply_nut_kills` already reads: the storm granter,
magecraft/cast-damage burn payoffs, the overrun finisher, and a scaling-burn finisher.

Read the spec before touching this file — the four roles combine cards under three
DIFFERENT rules (OR / capped-sum / max), and treating them uniformly (e.g. "remove the
biggest card, report 1") silently misreports three of the four. This module never assumes
the combination rule; it re-runs the real `estimate_go_off`/`estimate_overrun` after every
candidate removal and lets the estimator itself decide.

Deliberately NOT modeled (see spec): a `ritual_mana` role (ablating it would require a
fresh simulation, since a ritual changes the mana curve this module holds fixed) and a
turn-delay figure (this reports a CARD COUNT, not a turn delta).
"""

from __future__ import annotations

from dataclasses import dataclass

from mythgauntlet.model.card import Card
from mythgauntlet.semantics import tags
from mythgauntlet.sim.overrun import estimate_overrun
from mythgauntlet.sim.storm import estimate_go_off

_ROLE_STORM_GRANTER = "storm_granter"
_ROLE_BURN_PAYOFF = "burn_payoff"
_ROLE_OVERRUN_FINISHER = "overrun_finisher"
_ROLE_SCALING_BURN_FINISHER = "scaling_burn_finisher"


@dataclass(frozen=True)
class RoleRedundancy:
    role: str
    contributing_cards: tuple[str, ...]
    pieces_to_disable: int | None
    involves_commander: bool


@dataclass(frozen=True)
class WinconRedundancyReport:
    applicable: bool
    roles: tuple[RoleRedundancy, ...]


def _without(cards: list[tuple[Card, int]], excluded: set[str]) -> list[tuple[Card, int]]:
    return [(c, n) for c, n in cards if c.name not in excluded]


def _storm_granters(cards: list[tuple[Card, int]]) -> list[Card]:
    return [c for c, _n in cards if tags.analyze(c).grants_storm]


def _burn_payoffs(cards: list[tuple[Card, int]]) -> list[Card]:
    scored = [
        (c, tags.analyze(c).magecraft_damage + tags.analyze(c).cast_damage)
        for c, _n in cards
    ]
    scored = [(c, s) for c, s in scored if s > 0]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [c for c, _s in scored]


def _overrun_finishers(cards: list[tuple[Card, int]]) -> list[Card]:
    scored = []
    for c, _n in cards:
        fx = tags.analyze(c)
        if fx.overrun_pump > 0 or fx.overrun_scales:
            scored.append((c, fx.overrun_scales, fx.overrun_pump))
    scored.sort(key=lambda t: (t[1], t[2]), reverse=True)
    return [c for c, _scales, _pump in scored]


def _scaling_burn_finishers(cards: list[tuple[Card, int]]) -> list[Card]:
    scored = [(c, c.mana_value) for c, _n in cards if tags.analyze(c).scaling_burn]
    scored.sort(key=lambda pair: pair[1])  # cheapest first -- the engine always casts it first
    return [c for c, _mv in scored]


def _pieces_to_disable_storm(
    all_cards: list[tuple[Card, int]], mana_by_turn: list[int], turns: int, candidates: list[Card],
) -> int | None:
    excluded: set[str] = set()
    for k, card in enumerate(candidates, start=1):
        excluded.add(card.name)
        if not estimate_go_off(_without(all_cards, excluded), mana_by_turn, turns).goes_off:
            return k
    return None


def _pieces_to_disable_overrun(
    all_cards: list[tuple[Card, int]], nut_power: int, nut_creatures: int, candidates: list[Card],
) -> int | None:
    excluded: set[str] = set()
    for k, card in enumerate(candidates, start=1):
        excluded.add(card.name)
        remaining = _without(all_cards, excluded)
        if not estimate_overrun(remaining, nut_power, nut_creatures).can_alpha_strike:
            return k
    return None


def _role(
    role: str, candidates: list[Card], pieces: int | None, commander_names: frozenset[str],
) -> RoleRedundancy:
    names = tuple(c.name for c in candidates)
    return RoleRedundancy(
        role=role,
        contributing_cards=names,
        pieces_to_disable=pieces,
        involves_commander=any(n in commander_names for n in names),
    )


def analyze_wincon_redundancy(
    all_cards: list[tuple[Card, int]],
    mana_by_turn: list[int],
    nut_power: int,
    nut_creatures: int,
    turns: int,
    commander_names: frozenset[str] = frozenset(),
) -> WinconRedundancyReport:
    roles: list[RoleRedundancy] = []

    if estimate_go_off(all_cards, mana_by_turn, turns).goes_off:
        granters = _storm_granters(all_cards)
        if granters:
            pieces = _pieces_to_disable_storm(all_cards, mana_by_turn, turns, granters)
            roles.append(_role(_ROLE_STORM_GRANTER, granters, pieces, commander_names))

        payoffs = _burn_payoffs(all_cards)
        if payoffs:
            pieces = _pieces_to_disable_storm(all_cards, mana_by_turn, turns, payoffs)
            roles.append(_role(_ROLE_BURN_PAYOFF, payoffs, pieces, commander_names))

        finishers = _scaling_burn_finishers(all_cards)
        if finishers:
            pieces = _pieces_to_disable_storm(all_cards, mana_by_turn, turns, finishers)
            roles.append(_role(_ROLE_SCALING_BURN_FINISHER, finishers, pieces, commander_names))

    if estimate_overrun(all_cards, nut_power, nut_creatures).can_alpha_strike:
        finishers = _overrun_finishers(all_cards)
        if finishers:
            pieces = _pieces_to_disable_overrun(all_cards, nut_power, nut_creatures, finishers)
            roles.append(_role(_ROLE_OVERRUN_FINISHER, finishers, pieces, commander_names))

    return WinconRedundancyReport(applicable=bool(roles), roles=tuple(roles))
