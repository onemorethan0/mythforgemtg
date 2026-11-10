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
    return big, _kill_turns(resolved, big)


def drawn_value(resolved: ResolvedDeck, cfg: SimConfig, names, *, base=None) -> dict[str, CardValue]:
    """Paired, drawn-games value of each named card present in the deck. `base` is a
    `baseline(...)` result to share across calls; without it one is computed at cfg as given."""
    if base is None:
        big, (runs, kills) = cfg, _kill_turns(resolved, cfg)
    else:
        big, (runs, kills) = base
    out: dict[str, CardValue] = {}
    for name in names:
        if not any(c.name == name for c, _ in resolved.cards):
            continue
        drawn = [i for i, r in enumerate(runs) if name in r.seen_turn]
        if not drawn:
            out[name] = CardValue(name, 0.0, (0.0, 0.0), 0)
            continue
        _r, without = _kill_turns(_blanked(resolved, name), big, only=drawn)
        diffs = [w - kills[i] for i, w in zip(drawn, without)]
        n = len(diffs)
        mean = sum(diffs) / n
        var = sum((d - mean) ** 2 for d in diffs) / (n - 1) if n > 1 else 0.0
        half = Z90 * math.sqrt(var / n) if n > 1 else 0.0
        out[name] = CardValue(name, round(mean, 2), (round(mean - half, 2), round(mean + half, 2)),
                              n, round(mean * n / (n + SHRINK_GAMES), 3))
    return out


def load_bearing(resolved: ResolvedDeck, cfg: SimConfig, names) -> frozenset[str]:
    """The named cards the paired ablation shows the deck killing measurably sooner with, on
    its own ABLATION_RUNS sample (the caller's horizon and seed)."""
    vals = drawn_value(resolved, cfg, names, base=baseline(resolved, cfg))
    return frozenset(n for n, v in vals.items() if v.load_bearing)
