"""Matchups against the reference field (B35, docs/SPEC_deck_scouting_report.md).

The field (`src/mythgauntlet/data/reference_field.json`, committed; built by `scripts/build_reference_field.py`) is, per
bracket 1-4, one corpus deck per archetype a casual pod meets. A deck is played `games`
two-player Tier-2 games against each (seats alternated by `tier2.duel`), and each matchup reports
its win rate with a 90% interval:

  weak against      below 40% AND the interval's upper end under 50%
  favoured against  above 60% AND the interval's lower end over 50%
  even              otherwise -- including every matchup the sample can't separate from 50%

plus WHY from B34's win methods: how the field deck won the games it won ("its losses are
mostly to combat, around T9").

FIDELITY. Tier-2 is a battlecruiser-fidelity duel: directional, not a prediction of a real
game; every result carries that note. Two players, not a pod -- the pod check (D4) and `/pod`
cover the table.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

FIELD_PATH = Path(__file__).resolve().parents[1] / "data" / "reference_field.json"
WEAK_BELOW, FAVOURED_ABOVE = 0.40, 0.60
FIDELITY = ("Tier-2 two-player simulation at battlecruiser fidelity: directional, not a "
            "prediction of a real game.")
ARCHETYPE_LABEL = {
    "go_wide": "go-wide tokens", "voltron": "Voltron / commander damage",
    "midrange": "big-creature midrange", "spellslinger": "spellslinger",
    "graveyard": "graveyard / reanimator", "artifact_combo": "artifacts / combo",
    "control": "control / stax-light",
}
_METHOD_WORD = {"combat": "combat", "noncombat": "burn and drain", "commander_damage":
                "commander damage", "combo": "a combo", "decked": "decking",
                "adjudicated": "the turn cap", "poison": "poison"}


@dataclass
class Matchup:
    archetype: str
    label: str
    opponent: str               # the field deck's commander
    games: int
    wins: int
    winrate: float
    low: float                  # 90% interval
    high: float
    verdict: str                # weak / even / favoured
    why: str = ""


@dataclass
class MatchupReport:
    bracket: int
    games_each: int
    matchups: list[Matchup] = field(default_factory=list)
    weak_against: list[str] = field(default_factory=list)
    favoured_against: list[str] = field(default_factory=list)
    fidelity: str = FIDELITY


def load_field(bracket: int, path: Path | None = None) -> dict[str, dict]:
    """{archetype: {deck, commander, ...}} for `bracket`; {} when the field has none."""
    p = path or FIELD_PATH
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return data.get("brackets", {}).get(str(bracket), {})


def verdict(rate: float, low: float, high: float) -> str:
    if rate < WEAK_BELOW and high < 0.5:
        return "weak"
    if rate > FAVOURED_ABOVE and low > 0.5:
        return "favoured"
    return "even"


def why_lost(result, label: str) -> str:
    """How the field deck won its games (B34 methods), and how long games ran."""
    methods = dict(result.win_methods_b or {})
    lost = sum(methods.values())
    if not lost:
        return f"never lost to {label} in {result.games} games"
    top, n = max(methods.items(), key=lambda kv: (kv[1], kv[0]))
    word = _METHOD_WORD.get(top, top)
    return (f"{n} of its {lost} losses to {label} came by {word}; games ran about "
            f"{result.avg_turns:.0f} turns")


def duel_seat(resolved) -> tuple[list, object]:
    """(cards, lead commander) for a Tier-2 duel. The duel takes ONE commander, so a partner
    (Thrasios + Tymna) or a background rides as a card -- as `analyze_deck` does -- instead of
    vanishing: dropping it made a partner field deck's win rate swing by seed (z 3.1)."""
    cmds = list(resolved.commanders)
    return list(resolved.cards) + [(c, 1) for c in cmds[1:]], (cmds[0] if cmds else None)


def combos_for(resolved) -> tuple[frozenset[str], ...]:
    """The deck's game-ending combos from Commander Spellbook (cached by decklist), as the duel
    engine takes them -- without them a combo deck can't win the way it is built to (an Oloro
    Thassa's Oracle list read "weak" against midrange with no combo win in 600 duels). A failed
    lookup gives (): the duel then runs combat-only, as before."""
    import requests

    from mythgauntlet.data import spellbook
    try:
        report = spellbook.find_combos([(c.name, n) for c, n in resolved.cards],
                                       [c.name for c in resolved.commanders])
    except requests.RequestException:
        return ()
    return tuple(spellbook.winning_combos(report))


def run(cards, commander, bracket: int, *, db, store, games: int = 120, seed: int = 42,
        corpus: Path | None = None, field_path: Path | None = None,
        duel_fn=None, combos: tuple = (), combos_fn=None) -> MatchupReport:
    """Play `games` duels against every field deck of `bracket`. `combos` are the deck's own
    game-ending combos (`combos_for`); each field deck gets its own the same way."""
    from mythgauntlet.config import corpus_dir
    from mythgauntlet.model.deck import Deck, resolve
    from mythgauntlet.ratings.kill_speed import wilson
    from mythgauntlet.sim.tier2 import DuelConfig, duel

    duel_fn = duel_fn or duel
    combos_fn = combos_fn or combos_for     # the field decks' own combos, cached by decklist
    corpus = corpus or corpus_dir()
    report = MatchupReport(bracket=bracket, games_each=games)
    cfg = DuelConfig(games=games, seed=seed, max_turns=30, start_life=40)
    for arch, entry in load_field(bracket, field_path).items():
        path = corpus / entry["deck"]
        if not path.exists():
            continue
        opp = resolve(Deck.parse_text(path.read_text(encoding="utf-8")), db)
        opp_cards, opp_cmd = duel_seat(opp)
        res = duel_fn(cards, commander, opp_cards, opp_cmd, cfg, store=store,
                      combos_a=combos, combos_b=combos_fn(opp))
        rate = res.wins_a / res.games if res.games else 0.0
        low, high = wilson(res.wins_a, res.games)
        label = ARCHETYPE_LABEL.get(arch, arch)
        v = verdict(rate, low, high)
        report.matchups.append(Matchup(arch, label, entry.get("commander", ""), res.games,
                                       res.wins_a, round(rate, 3), round(low, 3), round(high, 3),
                                       v, why_lost(res, label)))
        if v == "weak":
            report.weak_against.append(label)
        elif v == "favoured":
            report.favoured_against.append(label)
    return report
