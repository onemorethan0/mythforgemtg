"""Pod fit (D4, docs/DESIGN_table_brackets.md): will these decks have a good game together?

Fun is a property of the POD, not of one deck. Given each seat's measured bracket and its three
table-contract dials (D3), four checks, each "ok", "warn" (worth saying before the game) or
"fail" (a mismatch likely to decide the game or sour it), and each failure or warning written
as a sentence for the pre-game talk:

  power          brackets within one of each other (fail at a gap of two or more)
  pace           no Fast deck with a Long one at the same table (fail); one Fast deck among
                 slower ones (warn) -- it ends games before the others get going
  denial         no deck two steps above the pod's median Denial (fail): one High-denial deck at
                 a table of Low ones takes the game away from three people; one step (warn)
  inevitability  at most one High-inevitability deck unless it is a Bracket 4-5 pod (fail
                 at two or more); one at a Bracket 1-3 table (warn)

A pod is predicted fun when nothing fails. These are predictions from goldfish measurements and
card roles, not a played game: the pod simulator (D5) is what will test them.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

_LEVEL = {"Low": 0, "Medium": 1, "High": 2}


@dataclass
class Seat:
    name: str
    bracket: int
    denial: str            # Low / Medium / High
    pace: str              # Fast / Typical / Long
    inevitability: str     # Low / Medium / High
    denial_reasons: list[str] = field(default_factory=list)
    inevitability_reasons: list[str] = field(default_factory=list)
    pace_reasons: list[str] = field(default_factory=list)


@dataclass
class Check:
    key: str
    status: str            # ok / warn / fail
    text: str


@dataclass
class PodFit:
    fun: bool
    checks: list[Check]
    summary: str


def _names(seats: list[Seat]) -> str:
    names = [s.name for s in seats]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _power(seats: list[Seat]) -> Check:
    hi = max(seats, key=lambda s: s.bracket)
    lo = min(seats, key=lambda s: s.bracket)
    gap = hi.bracket - lo.bracket
    if gap >= 2:
        return Check("power", "fail",
                     f"{hi.name} measures Bracket {hi.bracket} and {lo.name} Bracket {lo.bracket}: "
                     f"a {gap}-bracket gap. Expect {hi.name} to run away with it unless it is "
                     "swapped for a lower-power list.")
    if gap == 1:
        return Check("power", "ok",
                     f"Brackets {lo.bracket}-{hi.bracket}: within one of each other.")
    return Check("power", "ok", f"Every deck measures Bracket {hi.bracket}.")


def _pace(seats: list[Seat]) -> Check:
    fast = [s for s in seats if s.pace == "Fast"]
    long_ = [s for s in seats if s.pace == "Long"]
    if fast and long_:
        return Check("pace", "fail",
                     f"{_names(fast)} often ends games by turn 6 while {_names(long_)} rarely "
                     "kills before turn 10: the slow decks may never get to play their game.")
    if len(fast) == 1 and len(seats) > 1:
        return Check("pace", "warn",
                     f"{fast[0].name} is the only fast deck: it often ends games by turn 6, "
                     "before the others get going.")
    return Check("pace", "ok", "The decks close games on similar turns.")


def _denial(seats: list[Seat]) -> Check:
    levels = [_LEVEL[s.denial] for s in seats]
    median = statistics.median(levels)
    worst = max(seats, key=lambda s: _LEVEL[s.denial])
    step = _LEVEL[worst.denial] - median
    detail = f" ({'; '.join(worst.denial_reasons)})" if worst.denial_reasons else ""
    if step >= 2:
        return Check("denial", "fail",
                     f"{worst.name} runs heavy denial{detail} at a table that runs little: it can "
                     "stop the other three from playing. Say so before the game, or bring a "
                     "lower-denial list.")
    if step >= 1:
        return Check("denial", "warn",
                     f"{worst.name} denies more than the rest of the table{detail}.")
    return Check("denial", "ok", "Similar amounts of interaction and denial around the table.")


def _inevitability(seats: list[Seat]) -> Check:
    high = [s for s in seats if s.inevitability == "High"]
    high_pod = statistics.median(s.bracket for s in seats) >= 4
    if not high:
        return Check("inevitability", "ok", "No deck wins the same way most games.")
    # the reason is its own clause: it carries parentheses of its own ("(most often A + B)")
    detail = f": {high[0].inevitability_reasons[0]}" if high[0].inevitability_reasons else ""
    if high_pod:
        return Check("inevitability", "ok",
                     f"{_names(high)} win{'s' if len(high) == 1 else ''} the same way most games "
                     "-- expected at a Bracket 4-5 table.")
    if len(high) >= 2:
        return Check("inevitability", "fail",
                     f"{_names(high)} each win the same way most games at a Bracket 1-3 table: "
                     "games become a race to assemble, not a game of Magic.")
    return Check("inevitability", "warn",
                 f"{high[0].name} wins the same way most games{detail}. Tell the table what to "
                 "watch for.")


def check(seats: list[Seat]) -> PodFit:
    if len(seats) < 2:
        raise ValueError("a pod needs at least two decks")
    checks = [_power(seats), _pace(seats), _denial(seats), _inevitability(seats)]
    fails = [c for c in checks if c.status == "fail"]
    warns = [c for c in checks if c.status == "warn"]
    if fails:
        summary = (f"Likely a lopsided game: {len(fails)} mismatch{'es' if len(fails) > 1 else ''}"
                   + (f" and {len(warns)} thing{'s' if len(warns) > 1 else ''} to mention"
                      if warns else "") + ".")
    elif warns:
        summary = (f"Should be a fair game; {len(warns)} thing{'s' if len(warns) > 1 else ''} "
                   "worth saying before shuffling up.")
    else:
        summary = "A good fit: similar power, pace, denial and predictability."
    return PodFit(fun=not fails, checks=checks, summary=summary)
