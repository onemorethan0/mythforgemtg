"""How the deck kills (B34, docs/SPEC_deck_scouting_report.md).

From the goldfish runs (after apply_nut_kills), per killing game: which method delivered it --
`combat` (creatures and the anthems pumping them), `commander` (the commander's own combat
damage was the largest share of a life kill), `commander_damage` (21 combat damage from the
commander, CR 704.5a), `burn` (scaling burn, magecraft / cast-damage engines), `storm` (the
go-off detector), `overrun` (the alpha-strike detector) -- and which cards dealt the damage.

What it is not: tier0 has no alternate-win or infinite-combo execution (those are B33's
combo clock), and no opponent, so "relies on combat" means "this is how it kills when nobody
stops it". tier0 applies the commander-damage rule since B34: before, it counted only life, and
21 from the commander came first in 6-21% of games for commander-centric decks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

METHODS = ("combat", "commander", "commander_damage", "burn", "storm", "overrun")
TOP_CARDS = 5


@dataclass(frozen=True)
class KillMethods:
    games: int
    killing_games: int
    method_share: dict[str, float]          # over killing games, sums to 1
    median_kill_turn_by_method: dict[str, float]
    damage_share: dict[str, float]          # combat/commander/burn share of damage up to the kill
    top_damage_cards: list[dict] = field(default_factory=list)   # [{name, share}] over horizon


def _median(xs: list[int]) -> float:
    xs = sorted(xs)
    n = len(xs)
    return float(xs[n // 2]) if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def compute(runs, commander_name: str | None = None) -> KillMethods:
    killing = [r for r in runs if r.kill_turn is not None]
    counts = {m: 0 for m in METHODS}
    turns_by: dict[str, list[int]] = {m: [] for m in METHODS}
    dmg = {"combat": 0, "commander": 0, "burn": 0}
    for r in killing:
        m = r.kill_method if r.kill_method in counts else "combat"
        counts[m] += 1
        turns_by[m].append(r.kill_turn)
        for src, amt in (r.kill_sources or {}).items():
            dmg[src] = dmg.get(src, 0) + amt
    n_kill = len(killing)
    total_dmg = sum(dmg.values())

    per_card: dict[str, int] = {}
    for r in runs:
        for name, amt in r.damage_by_card.items():
            per_card[name] = per_card.get(name, 0) + amt
    horizon_total = sum(per_card.values())
    top = sorted(per_card.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_CARDS]

    return KillMethods(
        games=len(runs),
        killing_games=n_kill,
        method_share={m: round(c / n_kill, 3) for m, c in counts.items() if c} if n_kill else {},
        median_kill_turn_by_method={m: _median(t) for m, t in turns_by.items() if t},
        damage_share=({k: round(v / total_dmg, 3) for k, v in dmg.items() if v}
                      if total_dmg else {}),
        top_damage_cards=[{"name": n, "share": round(a / horizon_total, 3),
                           "commander": n == commander_name} for n, a in top]
        if horizon_total else [],
    )
