"""Pod meta-rating: how often does a deck WIN a 4-player game (docs/VISION.md)?

The 1v1 gauntlet (ratings/gauntlet.py) rates decks by pairwise duels — a duel is cheaper and
correlates with quality, but Commander is a 4-player format and the 1v1 meta-rating inverts at
the top (STATUS.md "the B5 finding"). This runs the actual pod: seat the deck among (pod_size-1)
opponents sampled from a field, rotate its seat to average out turn-order advantage, and measure
its win share. The honest baseline is `1/pod_size` — a deck that beats that is above pod-average.

It runs the N-player Tier-2 engine (`sim/game.play_table`) under GreedyAgents. Engine-limit
caveats (docs/SIMULATION.md "Multiplayer"): threat-focus combat and each-opponent effect
scaling, and **reactions are still 1v1-only** (a multiplayer cast resolves immediately —
see `_cast` in sim/game.py), so counterspells and instant-speed removal do nothing here.

Death-trigger drains and opponent-cast fan-out ARE pod-wired, contrary to what this
docstring claimed for some time after they landed: a dying creature's "each opponent"
drain scales through `_others` in `_apply_declare_blocks`, and every opponent's taxer fires
on a cast via `state.opponents_of(state.active)`. That correction matters, because those
are exactly the cards whose value is opponent-count-dependent — Rhystic Study, Smothering
Tithe, Esper Sentinel — and a stale "not wired" note invites someone to go re-fix a
mechanism that already works.

Known limit that DOES bite: a rung-1 card's opponent-taxed draw is a flat per-turn
`engine_draw` approximation that does NOT scale with pod size; only a CCM-backed card
fires per-opponent. So a deck's taxer value in a pod is only as good as its semantics
coverage.

Still a measurement BY an instrument, tagged with the engine version like every rating.
Deterministic (invariant #1): all randomness via SeededRng.
"""

from __future__ import annotations

from dataclasses import dataclass

from mythgauntlet.agents.greedy import GreedyAgent
from mythgauntlet.model.card import Card
from mythgauntlet.semantics.store import SemanticsStore
from mythgauntlet.sim.game import GameCard, _seat_keys, play_table
from mythgauntlet.sim.rng import SeededRng

# A ready-to-seat deck: its expanded GameCards, its commander (or None), its assembled combos.
Seat = tuple[list[GameCard], GameCard | None, tuple[frozenset[str], ...]]


@dataclass(frozen=True)
class PodRating:
    games: int
    wins: int
    pod_size: int
    winrate: float   # wins / games
    baseline: float  # 1 / pod_size — an even, no-skill pod
    lift: float      # winrate - baseline (>0 = wins more than its fair share of the table)


def prepare_seat(
    cards: list[tuple[Card, int]], commander: Card | None, store: SemanticsStore,
    combos: tuple[frozenset[str], ...] = (),
) -> Seat:
    """Expand a decklist into a reusable Seat (frozen GameCards; play_table copies the library
    per game, so one Seat is safe to reuse across every pod)."""
    from mythgauntlet.sim.tier2 import build_game_cards, make_game_card

    deck = build_game_cards(cards, store)
    cmdr = make_game_card(commander, store) if commander is not None else None
    return deck, cmdr, combos


def pod_winrate(
    deck: Seat, opponents: list[Seat], cfg: object, *,
    games: int, seed: int, pod_size: int = 4,
) -> PodRating:
    """Run `games` pods: `deck` faces (pod_size-1) opponents sampled (with replacement) from
    `opponents`, its seat rotated across games so no fixed turn-order edge skews the result.
    Returns its win share vs the 1/pod_size pod-average baseline."""
    if not opponents:
        raise ValueError("pod_winrate needs at least one opponent deck")
    rng = SeededRng(seed)
    keys = _seat_keys(pod_size)
    agents = {k: GreedyAgent() for k in keys}
    wins = 0
    for g in range(games):
        field = [rng.choice(opponents) for _ in range(pod_size - 1)]
        seat_pos = g % pod_size  # rotate the deck through every seat
        seats: list[Seat] = []
        oi = 0
        for pos in range(pod_size):
            if pos == seat_pos:
                seats.append(deck)
            else:
                seats.append(field[oi])
                oi += 1
        winner, _turns, _reason = play_table(seats, cfg, rng.spawn(g), agents)
        if winner == keys[seat_pos]:
            wins += 1
    baseline = 1.0 / pod_size
    winrate = wins / games if games else 0.0
    return PodRating(
        games=games, wins=wins, pod_size=pod_size,
        winrate=winrate, baseline=baseline, lift=winrate - baseline,
    )
