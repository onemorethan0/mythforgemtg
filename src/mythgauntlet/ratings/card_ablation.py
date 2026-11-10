"""What one card is worth to the goldfish kill, measured by PAIRED ablation in the games it is drawn.

The owner's question (2026-11-10), after a role swap cut Ambulatory Reactor: does the engine know
what a card does for winning? Two existing measures fail it in opposite ways:

  * whole-deck ablation (`advisor`'s axis deltas): one card is drawn in ~30% of games, so its
    effect on a whole-deck average sinks under the 2-3 point noise floor -- nearly every single
    card reads as "free to cut";
  * early uplift (`card_stats`, "seen by turn 3"): a fair A/B, but the window favours cards that
    act early. A rock seen on turn 3 is cast on turn 3; a 6-drop finisher seen on turn 3 still
    waits for turn 6, so ramp and cheap cards read as the deck's best and late bombs as nothing.

This measures the card itself. The same seeded games are played twice: once as built, once with
the card replaced IN PLACE by a blank no one can cast (same deck position, so every shuffle is
identical and every other card arrives on the same turn). The difference in kill turn, over the
games where the card was actually drawn, is what having it did -- whenever it was drawn. Games
where it is never drawn are identical by construction and carry no information, so they are left
out instead of diluting the estimate.

Honest limits: it is still the goldfish. A card's value against an opponent (removal, counters,
protection) is invisible here, exactly as on every other goldfish measure; `cut_pool` callers use
it only to keep a measurably load-bearing card from being cut, never to call interaction weak.
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
# has ~170 and reads +0.23 (+0.14..+0.32). ~3 s per card.
ABLATION_RUNS = 600


@dataclass(frozen=True)
class CardValue:
    name: str
    turns_sooner: float          # mean kill-turn difference (without - with), drawn games only
    ci90: tuple[float, float]
    games: int                   # games in which the card was drawn

    @property
    def load_bearing(self) -> bool:
        """The deck measurably kills sooner with it: the interval excludes zero, above it."""
        return self.games > 0 and self.ci90[0] > 0


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


def _kill_turns(resolved: ResolvedDeck, cfg: SimConfig):
    """The analyze_deck deck model (partners folded in, nut kills applied)."""
    commander = resolved.commanders[0] if resolved.commanders else None
    cards = resolved.cards + [(c, 1) for c in resolved.commanders[1:]]
    runs = simulate(cards, commander, cfg)
    apply_nut_kills(runs, list(cards) + ([(commander, 1)] if commander else []), cfg.turns,
                    commanders=resolved.commanders)
    return runs, [r.kill_turn if r.kill_turn is not None else cfg.turns + 1 for r in runs]


def drawn_value(resolved: ResolvedDeck, cfg: SimConfig, names, *, base=None) -> dict[str, CardValue]:
    """Paired, drawn-games value of each named nonland card (see the module docstring). One
    extra simulation per card; `base` reuses a baseline `_kill_turns` result."""
    runs, kills = base or _kill_turns(resolved, cfg)
    out: dict[str, CardValue] = {}
    for name in names:
        if not any(c.name == name for c, _ in resolved.cards):
            continue
        _r, without = _kill_turns(_blanked(resolved, name), cfg)
        diffs = [w - k for r, k, w in zip(runs, kills, without) if name in r.seen_turn]
        n = len(diffs)
        if n == 0:
            out[name] = CardValue(name, 0.0, (0.0, 0.0), 0)
            continue
        mean = sum(diffs) / n
        var = sum((d - mean) ** 2 for d in diffs) / (n - 1) if n > 1 else 0.0
        half = Z90 * math.sqrt(var / n) if n > 1 else 0.0
        out[name] = CardValue(name, round(mean, 2), (round(mean - half, 2), round(mean + half, 2)),
                              n)
    return out


def load_bearing(resolved: ResolvedDeck, cfg: SimConfig, names) -> frozenset[str]:
    """The named cards the paired ablation shows the deck killing measurably sooner with, on
    its own ABLATION_RUNS sample (the caller's horizon and seed)."""
    big = SimConfig(turns=cfg.turns, runs=max(cfg.runs, ABLATION_RUNS), seed=cfg.seed)
    return frozenset(n for n, v in drawn_value(resolved, big, names).items() if v.load_bearing)
