"""The table-contract dials (D3, docs/DESIGN_table_brackets.md): Denial, Pace, Inevitability.

Each dial is Low / Medium / High with the reasons that put it there, built only from what the
engine already measured -- no new simulation. They sit BESIDE the bracket and never move it;
they say what the pod should hear before shuffling up ("Bracket 2 - Denial High - Pace Long").

DENIAL (D2's roles). Points: a lock piece or a mass-land-denial card 3, each counterspell,
lasting theft card or extra-turn card 1. Medium from 4, High from 8: eight counterspells alone
is High, one lock and one counterspell is Medium. Calibrated 2026-11-08 on the 2,112 audited
labelled corpus decks: High is 5% of Bracket 1, 2% of Bracket 2, 7% of Bracket 3, 25% of
Bracket 4 and 61% of Bracket 5 -- at casual brackets it names the outliers.

PACE (B32/B33). Shares of games in which the deck has killed one unopposed opponent -- by
damage or, when the combo clock ran, by a combo, whichever comes first. Fast: a quarter of games
or more end by turn 6, breaking Wizards' Bracket 3 promise of "at least six turns before you win
or lose" often enough for a table to feel it. Long: fewer than half end by turn 10. A median
would not do: even a deck whose combo comes first in 75% of games has a combined median near T8.

INEVITABILITY (B33). How predictably the deck wins the same way. High: a combo wins before damage
in half the games, or in a quarter with three or more tutors, or the deck holds a game-ending
combo and six or more tutors that can fetch something (`semantics.tutor_reach`) -- enough to
find the same win when the clock can't time it. Medium: a game-ending combo, or four or more
tutors. Low otherwise. Without the combo lookup the dial says so and reads tutors only.

KNOWN LIMIT (2026-11-08 sample, 40 decks a bracket). The goldfish under-times cEDH: Bracket 5
decks end by T6 in a median 7% of games and their combo comes first in a median 0% (no mana
colour check, no fast-mana sequencing, assumption-carrying combos not counted as kills). So Pace
reads Fast for only 20% of Bracket 5 decks. The rules are tied to the game (Bracket 3's six
turns), not fitted to the labels; a faster clock will move the dial, not a moved threshold.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DENIAL_WEIGHTS = {"lock": 3, "mass_land_denial": 3, "counterspell": 1, "theft": 1, "extra_turn": 1}
DENIAL_MEDIUM, DENIAL_HIGH = 4, 8
PACE_FAST_SHARE_BY_T6, PACE_LONG_SHARE_BY_T10 = 0.25, 0.5
COMBO_FIRST_HIGH = 0.5
TUTORS_WITH_COMBO, TUTORS_MEDIUM, TUTORS_HIGH = 3, 4, 6


@dataclass
class Dial:
    band: str                                   # "Low" | "Medium" | "High" (Pace: "Fast"|"Typical"|"Long")
    reasons: list[str] = field(default_factory=list)
    value: float | None = None                  # the number the band was read from


@dataclass
class Dials:
    denial: Dial
    pace: Dial
    inevitability: Dial


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def denial_dial(d) -> Dial:
    """`d` is a `denial.DeckDenial`."""
    parts = [
        (len(d.locks), DENIAL_WEIGHTS["lock"], "lock piece"),
        (len(d.mass_land_denial), DENIAL_WEIGHTS["mass_land_denial"], "land-denial card"),
        (d.counterspells, DENIAL_WEIGHTS["counterspell"], "counterspell"),
        (d.theft, DENIAL_WEIGHTS["theft"], "theft card"),
        (d.extra_turn_cards, DENIAL_WEIGHTS["extra_turn"], "extra-turn card"),
    ]
    points = sum(n * w for n, w, _ in parts)
    band = "High" if points >= DENIAL_HIGH else "Medium" if points >= DENIAL_MEDIUM else "Low"
    reasons = [_plural(n, word) for n, _w, word in parts if n]
    if d.locks:
        reasons[0] += " (" + ", ".join(lk.name for lk in d.locks[:4]) + \
            (", ..." if len(d.locks) > 4 else "") + ")"
    return Dial(band, reasons or ["nothing that stops other players from playing"], float(points))


def _share(by_turn, turn: int) -> float:
    if not by_turn:
        return 0.0
    v = by_turn.get(turn, by_turn.get(str(turn)))
    return float(v or 0.0)


def pace_dial(kill_speed, combo_clock) -> Dial:
    """`kill_speed` is a `kill_speed.KillSpeed`, `combo_clock` a `combo_clock.ComboClock` or None.
    With the combo clock, its `by_turn` is the combined damage-or-combo share."""
    if kill_speed is None:
        return Dial("Typical", ["not measured"], None)
    by = combo_clock.by_turn if combo_clock is not None else kill_speed.by_turn
    by6, by10 = _share(by, 6), _share(by, 10)
    how = "by damage or combo" if combo_clock is not None else "by damage"
    reasons = [f"ends {by6:.0%} of games by T6 and {by10:.0%} by T10 ({how}, unopposed)"]
    if by6 >= PACE_FAST_SHARE_BY_T6:
        return Dial("Fast", reasons + ["often inside the six turns Bracket 3 promises a table"], by6)
    if by10 < PACE_LONG_SHARE_BY_T10:
        return Dial("Long", reasons, by10)
    return Dial("Typical", reasons, by10)


def inevitability_dial(combo_clock, combo_profile, tutors: int, combos_checked: bool) -> Dial:
    """`tutors`: cards whose own search text can fetch something (`tutor_reach`)."""
    reasons: list[str] = []
    first = 0.0
    if combo_clock is not None and combo_clock.games:
        first = combo_clock.combo_first_games / combo_clock.games
        if first:
            lead = " + ".join(combo_clock.lead_combo) if combo_clock.lead_combo else "a combo"
            reasons.append(f"a combo wins before damage in {first:.0%} of games (most often {lead})")
    n_combos = int(getattr(combo_profile, "total", 0) or 0) if combo_profile is not None else 0
    if n_combos:
        reasons.append(_plural(n_combos, "game-ending combo"))
    if tutors:
        reasons.append(_plural(tutors, "tutor"))
    if not combos_checked:
        reasons.append("combos not checked")
    high = (first >= COMBO_FIRST_HIGH
            or (first >= COMBO_FIRST_HIGH / 2 and tutors >= TUTORS_WITH_COMBO)
            or (n_combos and tutors >= TUTORS_HIGH))
    if high:
        return Dial("High", reasons, first)
    band = "Medium" if n_combos or tutors >= TUTORS_MEDIUM else "Low"
    return Dial(band, reasons or ["no combo and no tutors: games play out differently"], first)


def count_tutors(cards, commanders) -> int:
    from mythgauntlet.semantics.tutor_reach import tutor_reach
    return sum(n for c, n in list(cards) + [(c, 1) for c in commanders]
               if not c.is_land and tutor_reach(c) is not None)


def compute(resolved, analysis, deck_denial, combos_checked: bool) -> Dials:
    return Dials(
        denial=denial_dial(deck_denial),
        pace=pace_dial(getattr(analysis, "kill_speed", None), getattr(analysis, "combo_clock", None)),
        inevitability=inevitability_dial(
            getattr(analysis, "combo_clock", None), getattr(analysis, "combo_profile", None),
            count_tutors(resolved.cards, resolved.commanders), combos_checked),
    )
