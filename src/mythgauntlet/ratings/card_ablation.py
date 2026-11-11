"""What one card is worth to the goldfish kill, measured by PAIRED ablation in the games it is drawn.

The owner's question (2026-11-10), after a role swap cut Ambulatory Reactor: does the engine know
what a card does for winning? Two existing measures fail it in opposite ways:

  * whole-deck ablation (`advisor`'s axis deltas): one card is drawn in ~30% of games, so its
    effect on a whole-deck average sinks under the 2-3 point noise floor -- nearly every single
    card reads as "free to cut";
  * early uplift (`card_stats`, "seen by turn 3"): a fair A/B, but the window favours cards that
    act early. A rock seen on turn 3 is cast on turn 3; a 6-drop finisher seen on turn 3 still
    waits for turn 6, so ramp and cheap cards read as the deck's best and late bombs as nothing
    (Sol Ring read +1.17 turns there, +0.49 here).

This is the 17Lands "improvement when drawn" question asked of a simulator, which removes its
known confounder (deck quality, because the comparison is the SAME deck): the same seeded games
are played twice, once as built and once with the card replaced IN PLACE by a blank no one can
cast, so every shuffle is identical and every other card arrives on the same turn. The kill-turn
difference over the games where the card was drawn is what having it did, whenever it was drawn.
Games where it is never drawn are identical by construction; they are not replayed at all (only
the drawn games are, ~30% of the cost) and not averaged in as zeros.

Small samples are shrunk toward zero (17Lands-tool practice: a Bayesian average rather than a raw
rate), so a card drawn in few games cannot lead a ranking on noise.

Honest limits: it is still the goldfish. A card's value against an opponent (removal, counters,
protection) is invisible here, as on every goldfish measure; callers never use it to call
interaction weak.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass

from mythgauntlet.model.card import Card
from mythgauntlet.model.deck import ResolvedDeck
from mythgauntlet.sim.clock import apply_nut_kills
from mythgauntlet.sim.tier0 import SimConfig, simulate

# A blank that occupies a deck slot and is never cast or played: no type, an unpayable cost.
BLANK = Card(name="(ablated slot)", mana_cost_str="{99}", type_line="")

Z90 = 1.645
# Its own sample, whatever the caller's run count: a card is drawn in ~30% of games, so at a chat
# turn's 150 runs Ambulatory Reactor had 52 drawn games and an interval crossing zero; at 600 it
# has ~170 and reads +0.23 (+0.14..+0.32).
ABLATION_RUNS = 600
# Shrinkage: the estimate is scaled by n / (n + SHRINK_GAMES) -- a card drawn in 30 games keeps
# half its raw mean, one drawn in 170 keeps 85%.
SHRINK_GAMES = 30


@dataclass(frozen=True)
class CardValue:
    name: str
    turns_sooner: float          # raw mean kill-turn difference (without - with), drawn games
    ci90: tuple[float, float]
    games: int                   # games in which the card was drawn
    shrunk: float = 0.0          # turns_sooner * games / (games + SHRINK_GAMES)

    @property
    def load_bearing(self) -> bool:
        """The deck measurably kills sooner with it: the interval excludes zero, above it."""
        return self.games > 0 and self.ci90[0] > 0

    @property
    def drag(self) -> bool:
        """The deck measurably kills LATER with it (the interval excludes zero, below it)."""
        return self.games > 0 and self.ci90[1] < 0


def _blanked(resolved: ResolvedDeck, name: str) -> ResolvedDeck:
    """One copy of `name` replaced by BLANK at the SAME position (pairing needs it)."""
    out, done = [], False
    for card, count in resolved.cards:
        if not done and card.name == name:
            done = True
            out.append((BLANK, 1))
            if count > 1:
                out.append((card, count - 1))
        else:
            out.append((card, count))
    return dataclasses.replace(resolved, cards=out)


def _kill_turns(resolved: ResolvedDeck, cfg: SimConfig, only=None):
    """The analyze_deck deck model (partners folded in, nut kills applied)."""
    commander = resolved.commanders[0] if resolved.commanders else None
    cards = resolved.cards + [(c, 1) for c in resolved.commanders[1:]]
    runs = simulate(cards, commander, cfg, only=only)
    apply_nut_kills(runs, list(cards) + ([(commander, 1)] if commander else []), cfg.turns,
                    commanders=resolved.commanders)
    return runs, [r.kill_turn if r.kill_turn is not None else cfg.turns + 1 for r in runs]


def baseline(resolved: ResolvedDeck, cfg: SimConfig):
    """The shared baseline every card in a batch is compared against (ABLATION_RUNS games)."""
    big = SimConfig(turns=cfg.turns, runs=max(cfg.runs, ABLATION_RUNS), seed=cfg.seed)
    runs = runs_parallel(resolved, big)
    return big, (runs, [r.kill_turn if r.kill_turn is not None else big.turns + 1 for r in runs])


def _value(resolved: ResolvedDeck, big: SimConfig, name: str, drawn: list[int],
           base_kills: list[int]) -> CardValue:
    """One card's paired value: replay its drawn games with it blanked (a worker entry point --
    module level and picklable, so the batch below can run it in other processes)."""
    if not drawn:
        return CardValue(name, 0.0, (0.0, 0.0), 0)
    _r, without = _kill_turns(_blanked(resolved, name), big, only=drawn)
    diffs = [w - k for k, w in zip(base_kills, without)]
    n = len(diffs)
    mean = sum(diffs) / n
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1) if n > 1 else 0.0
    half = Z90 * math.sqrt(var / n) if n > 1 else 0.0
    return CardValue(name, round(mean, 2), (round(mean - half, 2), round(mean + half, 2)),
                     n, round(mean * n / (n + SHRINK_GAMES), 3))


# The cards of a batch are independent and every game is seeded by its own index, so they run in
# worker processes with byte-identical results (2026-11-11: the scouting report spent 127 of its
# ~160 s here, one card after another on one core). MYTHGAUNTLET_ABLATION_WORKERS=0 runs serially.
PARALLEL_MIN_CARDS = 6
_POOL = None


def _workers() -> int:
    import os
    env = os.environ.get("MYTHGAUNTLET_ABLATION_WORKERS")
    if env is not None:
        try:
            return max(0, int(env))
        except ValueError:
            return 0
    return max(0, min(8, (os.cpu_count() or 2) - 2))


def _pool():
    """A process pool kept for the life of the process (spawning one costs seconds)."""
    global _POOL
    if _POOL is None:
        from concurrent.futures import ProcessPoolExecutor
        _POOL = ProcessPoolExecutor(max_workers=_workers())
    return _POOL


def _chunk_runs(resolved: ResolvedDeck, big: SimConfig, idx: list[int]):
    return _kill_turns(resolved, big, only=idx)[0]


def runs_parallel(resolved: ResolvedDeck, big: SimConfig, chunks: int = 8):
    """All `big.runs` games of the analyze deck model (nut kills applied), in index order, split
    across the worker pool. Identical to `_kill_turns(resolved, big)[0]`: every game is seeded by
    its own index and the nut-kill pass reads each run alone."""
    n = big.runs
    if n < 200 or _workers() == 0:
        return _kill_turns(resolved, big)[0]
    size = -(-n // chunks)
    parts = [list(range(s, min(n, s + size))) for s in range(0, n, size)]
    try:
        futs = [_pool().submit(_chunk_runs, resolved, big, p) for p in parts]
        return [r for f in futs for r in f.result()]
    except Exception:                # noqa: BLE001 - a broken pool falls back to serial
        global _POOL
        _POOL = None
        return _kill_turns(resolved, big)[0]


def drawn_value(resolved: ResolvedDeck, cfg: SimConfig, names, *, base=None) -> dict[str, CardValue]:
    """Paired, drawn-games value of each named card present in the deck. `base` is a
    `baseline(...)` result to share across calls; without it one is computed at cfg as given."""
    if base is None:
        big, (runs, kills) = cfg, _kill_turns(resolved, cfg)
    else:
        big, (runs, kills) = base
    in_deck = {c.name for c, _ in resolved.cards}
    jobs = []
    for name in names:
        if name not in in_deck:
            continue
        drawn = [i for i, r in enumerate(runs) if name in r.seen_turn]
        jobs.append((name, drawn, [kills[i] for i in drawn]))
    if len(jobs) >= PARALLEL_MIN_CARDS and _workers() > 0:
        try:
            futs = [_pool().submit(_value, resolved, big, n, d, k) for n, d, k in jobs]
            return {n: f.result() for (n, _d, _k), f in zip(jobs, futs)}
        except Exception:            # noqa: BLE001 - a broken pool falls back to serial
            global _POOL
            _POOL = None
    return {n: _value(resolved, big, n, d, k) for n, d, k in jobs}


def load_bearing(resolved: ResolvedDeck, cfg: SimConfig, names) -> frozenset[str]:
    """The named cards the paired ablation shows the deck killing measurably sooner with, on
    its own ABLATION_RUNS sample (the caller's horizon and seed)."""
    vals = drawn_value(resolved, cfg, names, base=baseline(resolved, cfg))
    return frozenset(n for n, v in vals.items() if v.load_bearing)
