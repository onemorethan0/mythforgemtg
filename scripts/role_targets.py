"""Regenerate `mythgauntlet.ratings.redundancy.ROLE_TARGETS` from real decks.

A redundancy detector answers "what does this deck have too MUCH of", so its targets have
to say what "too much" means. The first version borrowed them from the BUILDER's slot plan
(`playstyle.DEFAULT_SLOTS`) — the app's opinion of a deck it is about to construct — and
that turned out to be the wrong baseline for judging a deck someone already owns.

Measured over 120 corpus decks, the builder's plan sits BELOW the population median for
ramp and draw and ABOVE it for removal and wipe, so nearly every deck read as
draw/ramp-oversupplied and essentially none ever read as removal-oversupplied:

    role          plan   median supply
    ramp            10            12.0
    draw            10            14.5
    removal          7             4.0
    wipe             4             3.0
    counterspell     3             0.0

The consequence was a systematically lopsided cut pool — draw 48.7% and ramp 34.5% of
every suggestion, against removal 1.5% and wipe 1.0%. That is an artifact of the baseline,
not a judgement about any particular deck.

Targets are now the 60th percentile of what real decks actually supply, so a role has to
clear a modest evidential bar (above ~60% of decks) before it counts as over-served.
Swept, not chosen — top-role share of the cut pool:

    current  48.7%    draw+ramp 83.2%   removal+wipe  2.5%
    p50      34.9%    draw+ramp 63.8%   removal+wipe 12.3%
    p60      32.8%    draw+ramp 57.8%   removal+wipe 17.1%   <- knee
    p75      30.4%    draw+ramp 55.7%   removal+wipe 16.4%

p75 barely improves on p60 while pushing targets so high (ramp 18, draw 20) that little
would ever flag.

THE SAMPLE IS NOW THE WHOLE CORPUS, and that changed an answer. The sweep above ran under a
`DECKS = 120` cap; the corpus has since reached 499. Re-measured over all of them, `tutor`
moves 2 -> 4 and nothing else moves at all. Tutors were therefore judged against half their
real population target, and the module over-flagged them: 13.8% of every cut suggestion
against 10.6% after, with the pool changing on 16% of decks.

`--check` could not have caught this, because it re-measured under the SAME cap the constant
was generated from and so could only ever agree with itself. See `DECKS` below.

    python scripts/role_targets.py             # print the table
    python scripts/role_targets.py --check     # diff against the baked-in constant
    python scripts/role_targets.py --limit 120 # the old sample, for comparison
    python scripts/role_targets.py --by-identity  # per role: p60 among decks WITH vs WITHOUT
                                                  # each colour in their identity (see below)

`--by-identity` is the measurement behind `redundancy.ROLE_COLOR_REQUIREMENTS` (PLAN_MENTOR_ADHOC
C1). ROLE_TARGETS is a colour-blind population baseline, so a deck whose colours cannot run a role
is still told it is short of it (a Golgari deck "lacks counterspells"). The sweep reports, per
role and colour, the p60 supply of corpus decks that HAVE the colour against those that LACK it;
a requirement is baked only where the lacking half sits far below the baseline target.

Needs data/cards_slim.json (gitignored), so it is not CI-safe.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mythgauntlet.data.scryfall import load_card_db  # noqa: E402
from mythgauntlet.model.deck import Deck, resolve  # noqa: E402
from mythgauntlet.ratings import redundancy  # noqa: E402

PERCENTILE = 0.60
MIN_TARGET = 2      # a floor: counterspell's median is 0.0, and "any counterspell is
                    # redundant" is obviously wrong.

# ALL of them. This used to be `DECKS = 120`, a cap that predates the corpus reaching 499
# decks, and it silently mis-measured `tutor`: p60 over the first 120 is 2.0, over all 499
# it is 4.0. Every other role is identical, so the cap looked harmless.
#
# The cap was invisible because `--check` INHERITS IT. The checker re-measured with the same
# 120-deck sample the constant was generated from, re-derived 2, and reported "ROLE_TARGETS
# is current" — a self-confirming test that could only ever agree with itself. A calibration
# checker has to be able to disagree with the baked value, and this one structurally could
# not. Confirmed a population fact, not a shuffle: three disjoint thirds of the corpus each
# give tutor p60 = 4.0 independently.
#
# `--limit` is kept for a fast run while iterating; it is not the default.
DECKS = None


def _corpus_rows():
    """Yield (colour identity frozenset, role_supply dict) for every >=90-card corpus deck."""
    db = load_card_db()
    for path in sorted((Path(__file__).resolve().parents[1] / "corpus" / "decks").glob("*.txt")):
        deck = Deck.parse_text(path.read_text(encoding="utf-8"))
        resolved = resolve(deck, db)
        if resolved.card_count < 90:
            continue
        identity = frozenset(ch for c in resolved.commanders for ch in c.color_identity)
        yield identity, redundancy.role_supply(resolved)


def _pctile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(percentile * len(ordered)))]


def measure(percentile: float = PERCENTILE, decks: int | None = DECKS) -> dict[str, int]:
    supplies: dict[str, list[float]] = {r: [] for r in redundancy.ROLE_TARGETS}
    seen = 0
    for _identity, supply in _corpus_rows():
        for role in supplies:
            supplies[role].append(supply.get(role, 0.0))
        seen += 1
        if decks is not None and seen >= decks:
            break
    out = {}
    for role, values in supplies.items():
        out[role] = max(MIN_TARGET, round(_pctile(values, percentile)))
    return out


def measure_by_identity(percentile: float = PERCENTILE) -> dict:
    """{role: {colour: {"has": stats, "lacks": stats}}}, stats = {n, p60, median, share_nonzero}
    over corpus decks that have / lack `colour` in their colour identity. RAW p60 (no MIN_TARGET
    floor): the floor would hide exactly the zero we are looking for.

    Decks whose identity is EMPTY are excluded from both halves: a truly colourless commander is
    rare, and an empty identity is what an UNRESOLVED commander looks like too -- the 9 corpus
    decks in that state carry counterspells in 8 of 9, which would contaminate every "lacks" half
    with decks whose colours we simply do not know."""
    rows = [(i, s) for i, s in _corpus_rows() if i]
    out: dict = {}
    for role in redundancy.ROLE_TARGETS:
        out[role] = {}
        for colour in "WUBRG":
            halves = {"has": [], "lacks": []}
            for identity, supply in rows:
                halves["has" if colour in identity else "lacks"].append(supply.get(role, 0.0))
            out[role][colour] = {
                k: {
                    "n": len(v),
                    "p60": _pctile(v, percentile) if v else None,
                    "median": statistics.median(v) if v else None,
                    "share_nonzero": (sum(1 for x in v if x > 0) / len(v)) if v else None,
                }
                for k, v in halves.items()
            }
    return out


def measure_by_identity_set(role: str, colours: str, percentile: float = PERCENTILE) -> dict:
    """Same halves for a role that ANY of `colours` enables: has = identity shares a colour with
    `colours`, lacks = identity shares none. Used for roles several colours can fill (a board
    wipe is W, B or R; a finisher is R or G)."""
    halves = {"has": [], "lacks": []}
    for identity, supply in _corpus_rows():
        if not identity:
            continue
        halves["has" if identity & set(colours) else "lacks"].append(supply.get(role, 0.0))
    return {k: {"n": len(v), "p60": _pctile(v, percentile) if v else None,
                "share_nonzero": (sum(1 for x in v if x > 0) / len(v)) if v else None}
            for k, v in halves.items()}


def print_by_identity(percentile: float) -> None:
    table = measure_by_identity(percentile)
    print(f"p{int(percentile * 100)} supply by colour identity (strength units; "
          f"baseline target in brackets)")
    print(f"{'role':<13}{'col':<4}{'has n':>6}{'has p60':>9}{'has %>0':>9}"
          f"{'lacks n':>9}{'lacks p60':>10}{'lacks %>0':>10}")
    for role, cols in table.items():
        print(f"{role} [{redundancy.ROLE_TARGETS[role]}]")
        for colour, halves in cols.items():
            h, l = halves["has"], halves["lacks"]
            fmt = lambda x: "  -  " if x is None else f"{x:5.1f}"  # noqa: E731
            pct = lambda x: "  -  " if x is None else f"{100 * x:4.0f}%"  # noqa: E731
            print(f"{'':<13}{colour:<4}{h['n']:>6}{fmt(h['p60']):>9}{pct(h['share_nonzero']):>9}"
                  f"{l['n']:>9}{fmt(l['p60']):>10}{pct(l['share_nonzero']):>10}")
    print()
    print("ROLE_COLOR_REQUIREMENTS candidates (an ANY-of colour set; lacks = shares no colour):")
    for role, colours in sorted(redundancy.ROLE_COLOR_REQUIREMENTS.items()):
        m = measure_by_identity_set(role, "".join(sorted(colours)), percentile)
        print(f"  {role:<13}needs any of {''.join(sorted(colours))}: "
              f"has n={m['has']['n']} p60={m['has']['p60']} %>0={100 * m['has']['share_nonzero']:.0f}%  |  "
              f"lacks n={m['lacks']['n']} p60={m['lacks']['p60']} %>0={100 * m['lacks']['share_nonzero']:.0f}%")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--percentile", type=float, default=PERCENTILE)
    ap.add_argument("--limit", type=int, default=DECKS,
                    help="stop after N corpus decks (default: all of them)")
    ap.add_argument("--by-identity", action="store_true",
                    help="p60 supply per role among decks with vs without each colour")
    args = ap.parse_args()
    if args.by_identity:
        print_by_identity(args.percentile)
        return 0
    targets = measure(args.percentile, args.limit)

    if args.check:
        drift = {r: (redundancy.ROLE_TARGETS.get(r), v) for r, v in sorted(targets.items())
                 if redundancy.ROLE_TARGETS.get(r) != v}
        for role, (was, now) in drift.items():
            print(f"DRIFT {role}: baked {was} measured {now}")
        print("ROLE_TARGETS is current." if not drift else "ROLE_TARGETS needs regenerating.")
        return 0 if not drift else 1

    print("ROLE_TARGETS: dict[str, int] = {")
    for role, value in targets.items():
        print(f'    "{role}": {value},')
    print("}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
