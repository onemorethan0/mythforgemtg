"""Tier-0 goldfish consistency simulator (docs/SIMULATION.md).

One player, no opponent. Measures the statistical skeleton of a deck: mulligans, land
drops, color access, mana development, and how efficiently the curve deploys.

Documented simplifications (T0 is built to be fast, deterministic, and honest — not complete):
  - Commander tax, haste, and activated abilities are ignored.
  - Rocks/dorks/fetched lands come in "asleep" and produce from the next untap onward.
  - Land-fetch spells pull a land out of the library (thinning) and add a source next turn.
  - One-shot draws resolve immediately; triggered engines draw a flat engine_draw per turn
    starting the turn after they resolve (trigger conditions not evaluated).
  - X spells are cast for X=0. Every source produces exactly one mana.
  - Casting order is a fixed greedy policy: ramp early, then commander, then draw,
    then highest-impact castable spell.
  - The goldfish clock: creatures attack a single non-blocking opponent (goldfish_life,
    default 40) starting the turn after they resolve; kill_turn is when cumulative combat
    damage crosses that threshold. Noncombat damage isn't modeled at rung 1.

All randomness flows through SeededRng (invariant #1). No card names appear here
(invariant #2): behavior comes exclusively from the semantics layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mythgauntlet.model.card import Card
from mythgauntlet.semantics import tags
from mythgauntlet.semantics.model import EffectVector
from mythgauntlet.sim.rng import SeededRng

# User-facing default goldfish horizon for `analyze`/`advise`. Casual (Bracket 1-3) decks
# routinely land their clock turns 10-14; an 8-turn goldfish can't see it, so Speed and
# Ceiling read ~0 and the deck is mislabeled toward Exhibition (measured on the labeled corpus
# 2026-07-22: 8->12 turns lifted B1-3 bracket agreement 5/10 -> 8/10). 12 matches typical
# casual game length; the SimConfig dataclass default stays 8 for unit tests / internal callers.
DEFAULT_ANALYZE_TURNS = 12


@dataclass(frozen=True)
class SimConfig:
    turns: int = 8
    runs: int = 1000
    seed: int = 42
    draw_on_first_turn: bool = True  # multiplayer rule (Commander); False for 1v1 on the play
    free_first_mulligan: bool = True  # Commander house rule / official multiplayer rule
    ramp_priority_turns: int = 4  # cast ramp before other spells through this turn
    goldfish_life: int = 40  # single-opponent goldfish clock
    mulligan_min_lands: int = 2  # keep a 7/6-card hand only with lands in [min, max]
    mulligan_max_lands: int = 5


@dataclass(frozen=True)
class SimCard:
    """Engine-facing view of a card: data + rung-1 semantics, precomputed once per deck."""

    card: Card
    fx: EffectVector

    @property
    def is_land(self) -> bool:
        return self.card.is_land

    @property
    def mana_value(self) -> int:
        return self.card.mana_value

    def produced_colors(self) -> frozenset[str]:
        produced = frozenset(p for p in self.card.produced_mana if p in "WUBRGC")
        if produced:
            return produced
        if self.card.color_identity:
            return frozenset(self.card.color_identity)
        return frozenset(("C",))

    @property
    def attack_power(self) -> int:
        return _stat_value(self.card.power)

    @property
    def toughness_value(self) -> int:
        return _stat_value(self.card.toughness)


def _stat_value(stat: str | int | None) -> int:
    """Numeric power/toughness; '*', '1+*' etc. count 0 at rung 1."""
    try:
        return max(0, int(stat or 0))
    except ValueError:
        return 0


@dataclass
class _Source:
    colors: frozenset[str]
    ready: bool = True
    from_creature: bool = False  # mana dork — dies to a board wipe (Tier-1 disruption)
    temp: bool = False  # ritual mana (T2): expires at the controller's next untap step


@dataclass
class RunStats:
    mulligans: int = 0
    kept_hand_size: int = 7
    land_drops: list[bool] = field(default_factory=list)  # index 0 = turn 1
    sources_by_turn: list[int] = field(default_factory=list)
    mana_available_by_turn: list[int] = field(default_factory=list)
    mana_spent_by_turn: list[int] = field(default_factory=list)
    spells_cast: int = 0
    commander_turn: int | None = None
    dead_cards: int = 0  # nonland cards still in hand at horizon
    cards_drawn: int = 0
    damage_by_turn: list[int] = field(default_factory=list)  # cumulative goldfish damage
    kill_turn: int | None = None  # turn cumulative damage reached cfg.goldfish_life
    final_board_power: int = 0  # attacking power on board at the horizon
    final_board_creatures: int = 0  # able-to-attack creatures at the horizon (go-wide proxy)
    # established (not-summoning-sick) board just before this turn's combat, one entry per
    # turn — feeds sim/clock.py's per-run overrun detection (final_board_* is just the last
    # entry of these, kept for callers that only want the horizon snapshot).
    board_power_by_turn: list[int] = field(default_factory=list)
    board_creatures_by_turn: list[int] = field(default_factory=list)


def build_sim_cards(cards: list[tuple[Card, int]]) -> list[SimCard]:
    out: list[SimCard] = []
    for card, count in cards:
        sc = SimCard(card=card, fx=tags.analyze(card))
        out.extend([sc] * count)
    return out


def _can_pay(sources: list[_Source], cost) -> list[int] | None:
    """Exact pip assignment via Kuhn's augmenting-path bipartite matching.

    Returns indices of sources to tap, or None if unpayable. Optimal for pip
    satisfiability (a greedy assignment can strand a flexible source on the wrong pip);
    generic mana is paid from whatever ready sources remain.
    """
    ready = [i for i, s in enumerate(sources) if s.ready]
    if len(ready) < cost.mana_value:
        return None
    adjacency = [[i for i in ready if sources[i].colors & pip] for pip in cost.pips]
    source_to_pip: dict[int, int] = {}

    def try_assign(pip_idx: int, visited: set[int]) -> bool:
        for src_idx in adjacency[pip_idx]:
            if src_idx in visited:
                continue
            visited.add(src_idx)
            if src_idx not in source_to_pip or try_assign(source_to_pip[src_idx], visited):
                source_to_pip[src_idx] = pip_idx
                return True
        return False

    for pip_idx in range(len(cost.pips)):
        if not try_assign(pip_idx, set()):
            return None

    used = list(source_to_pip.keys())
    remaining = [i for i in ready if i not in source_to_pip]
    if len(remaining) < cost.generic:
        return None
    used.extend(remaining[: cost.generic])
    return used


def _keepable(hand: list[SimCard], size: int, cfg: SimConfig) -> bool:
    lands = sum(1 for c in hand if c.is_land)
    if size <= 5:
        return 1 <= lands <= size - 1
    return cfg.mulligan_min_lands <= lands <= min(cfg.mulligan_max_lands, size - 1)


def _mulligan(
    deck: list[SimCard], rng: SeededRng, cfg: SimConfig
) -> tuple[list[SimCard], list[SimCard], int]:
    """London-lite: redraw whole hands at decreasing size. Returns (hand, library, mulls)."""
    sizes = [7, 7, 6, 5] if cfg.free_first_mulligan else [7, 6, 5]
    hand: list[SimCard] = []
    library: list[SimCard] = []
    mulls = 0
    for attempt, size in enumerate(sizes):
        library = deck[:]
        rng.shuffle(library)
        hand = [library.pop() for _ in range(min(size, len(library)))]
        if _keepable(hand, size, cfg) or attempt == len(sizes) - 1:
            mulls = attempt
            break
    return hand, library, mulls


def _needed_colors(hand: list[SimCard], commander: SimCard | None) -> set[str]:
    needed: set[str] = set()
    pool = [c for c in hand if not c.is_land]
    if commander is not None:
        pool.append(commander)
    for c in pool:
        for pip in c.card.cost.pips:
            needed |= pip
    return needed


def _choose_land(hand: list[SimCard], needed: set[str]) -> SimCard | None:
    lands = [c for c in hand if c.is_land]
    if not lands:
        return None

    def score(land: SimCard) -> tuple[int, int]:
        colors = land.produced_colors()
        return (0 if land.fx.enters_tapped else 1, len(colors & needed))

    return max(lands, key=score)


def _cast_priority(sc: SimCard, turn: int, cfg: SimConfig) -> tuple:
    """Lower sorts first. Fixed greedy policy — see module docstring."""
    is_ramp = sc.fx.ramp_sources > 0
    if is_ramp and turn <= cfg.ramp_priority_turns:
        return (0, sc.mana_value)
    if sc.fx.draw_cards > 0:
        return (2, -sc.fx.impact, sc.mana_value)
    return (3, -sc.fx.impact, -sc.mana_value)


def _run_one(
    deck: list[SimCard], commander: SimCard | None, cfg: SimConfig, rng: SeededRng,
    board_wipe_turn: int | None = None,
) -> RunStats:
    stats = RunStats()
    hand, library, stats.mulligans = _mulligan(deck, rng, cfg)
    stats.kept_hand_size = len(hand)

    sources: list[_Source] = []
    commander_in_zone = commander is not None
    board_power = 0  # creatures able to attack (resolved on a previous turn)
    pending_power = 0  # creatures that came down this turn (summoning-sick)
    board_creatures = 0  # count of able-to-attack creatures (mirrors board_power, for go-wide)
    pending_creatures = 0
    engine_active = 0  # extra draws per turn from resolved engines
    engine_pending = 0
    enabler_active = False  # a cheat-into-play enabler (Kaalia class) is online + can attack
    enabler_pending = False
    damage = 0

    def draw(n: int) -> None:
        for _ in range(n):
            if library:
                hand.append(library.pop())
                stats.cards_drawn += 1

    def apply_effects(sc: SimCard) -> None:
        nonlocal pending_power, pending_creatures, engine_pending, enabler_pending
        if sc.card.is_creature:
            pending_power += sc.attack_power
            pending_creatures += 1
        if sc.fx.cheats_creatures:  # active next turn (a creature enabler must untap + attack)
            enabler_pending = True
        engine_pending += sc.fx.engine_draw
        if sc.fx.fetches_land:
            fetched = next((c for c in library if c.is_land), None)
            if fetched is not None:
                library.remove(fetched)
                sources.append(_Source(fetched.produced_colors(), ready=False))
        elif sc.fx.ramp_sources > 0:
            for _ in range(sc.fx.ramp_sources):
                sources.append(
                    _Source(sc.produced_colors(), ready=False,
                            from_creature=sc.card.is_creature)
                )
        draw(sc.fx.draw_cards)

    for turn in range(1, cfg.turns + 1):
        for s in sources:
            s.ready = True
        board_power += pending_power
        pending_power = 0
        board_creatures += pending_creatures
        pending_creatures = 0
        engine_active += engine_pending
        engine_pending = 0
        enabler_active = enabler_active or enabler_pending
        enabler_pending = False

        # Tier-1 disruption: a board wipe at the start of this turn destroys creatures.
        # In T0 that resets the creature clock and kills mana dorks; lands, rocks, and
        # noncreature engines survive (T0 doesn't tag engine sources, so creature-based
        # draw engines are conservatively left intact — the hit is never over-counted).
        if board_wipe_turn is not None and turn == board_wipe_turn:
            board_power = 0
            pending_power = 0
            board_creatures = 0
            pending_creatures = 0
            sources = [s for s in sources if not s.from_creature]
            enabler_active = enabler_pending = False  # the enabler died too

        if turn > 1 or cfg.draw_on_first_turn:
            draw(1)
        draw(engine_active)

        land = _choose_land(hand, _needed_colors(hand, commander if commander_in_zone else None))
        if land is not None:
            hand.remove(land)
            sources.append(_Source(land.produced_colors(), ready=not land.fx.enters_tapped))
        stats.land_drops.append(land is not None)

        mana_available = sum(1 for s in sources if s.ready)
        stats.sources_by_turn.append(len(sources))
        stats.mana_available_by_turn.append(mana_available)

        spent = 0
        while True:
            castable: list[tuple[tuple, SimCard, list[int], bool]] = []
            for sc in hand:
                if sc.is_land:
                    continue
                payment = _can_pay(sources, sc.card.cost)
                if payment is not None:
                    castable.append((_cast_priority(sc, turn, cfg), sc, payment, False))
            if commander_in_zone and commander is not None:
                payment = _can_pay(sources, commander.card.cost)
                if payment is not None:
                    castable.append(((1, commander.mana_value), commander, payment, True))
            if not castable:
                break

            _, sc, payment, is_commander = min(castable, key=lambda t: t[0])
            for idx in payment:
                sources[idx].ready = False
            spent += sc.mana_value
            stats.spells_cast += 1

            if is_commander:
                commander_in_zone = False
                stats.commander_turn = turn
            else:
                hand.remove(sc)
            apply_effects(sc)

        stats.mana_spent_by_turn.append(spent)

        # combat: everything that was already down swings at the goldfish opponent
        stats.board_power_by_turn.append(board_power)
        stats.board_creatures_by_turn.append(board_creatures)
        damage += board_power
        if enabler_active:  # Kaalia class: cheat the biggest STRANDED creature in, attacking now
            stranded = [c for c in hand if c.card.is_creature]
            if stranded:
                cheated = max(stranded, key=lambda c: c.attack_power)
                hand.remove(cheated)
                damage += cheated.attack_power       # enters tapped + attacking -> hits this turn
                pending_power += cheated.attack_power  # ... and stays on board thereafter
                pending_creatures += 1
        stats.damage_by_turn.append(damage)
        if stats.kill_turn is None and damage >= cfg.goldfish_life:
            stats.kill_turn = turn

    stats.final_board_power = board_power
    stats.final_board_creatures = board_creatures
    stats.dead_cards = sum(1 for c in hand if not c.is_land)
    return stats


def simulate(
    cards: list[tuple[Card, int]], commander: Card | None, cfg: SimConfig,
    board_wipe_turn: int | None = None,
) -> list[RunStats]:
    """Run cfg.runs seeded goldfish games. Deterministic for a given (deck, cfg).

    board_wipe_turn injects a Tier-1 disruption (see _run_one). Because run i always
    draws from the same seeded stream, a clean run and a wiped run at the same seed are
    a matched pair — variance cancels when their outcomes are differenced (resilience).
    """
    deck = build_sim_cards(cards)
    sim_commander = SimCard(card=commander, fx=tags.analyze(commander)) if commander else None
    root = SeededRng(cfg.seed)
    return [
        _run_one(deck, sim_commander, cfg, root.spawn(i), board_wipe_turn)
        for i in range(cfg.runs)
    ]
