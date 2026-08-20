"""Regenerate `mythgauntlet.ratings.redundancy.ARCHETYPE_ROLE_TARGETS` from real decks.

`ROLE_TARGETS` judges every deck against ONE population baseline, so a deck that plays to a
role as its PLAN reads as over-supplied in exactly the thing it is trying to do. The measured
case: `counterspell`'s population target is 3 supply units — the weight of a single card,
because the median corpus deck runs zero — while the 24 corpus decks that actually ARE
spellslinger decks supply a p60 of TWELVE. Every one of them is scored 3x-to-9x over in
counterspells and its interaction becomes the cut pool. That is how a Prismari deck came to
be told to cut Flusterstorm and Mental Misstep, its two best counterspells.

So the target for a role has to know what the deck is TRYING to do. This measures, per
archetype, the same p60 of real supply that `role_targets.py` measures per population.

WHY THE TABLE ONLY EVER RAISES A TARGET. A cell is baked only when the archetype supplies
MORE than the population does, never less. The defect is false-positive cut suggestions —
telling a deck to cut its own plan — and lowering a target creates MORE of them, which
nothing measured here argues for. It is also where small-sample noise would do the damage.
An archetype can earn a higher allowance; it cannot earn a tighter one.

THREE GATES, and all three are load-bearing. Measured over 499 corpus decks:

  1. MIN_DECKS — at least 20 decks carry the theme. Split-half disagreement falls
     monotonically with sample size, over cells that clear the global target:

         n >= 30       18 cells   mean |A-B| 1.86   max  4.5
         20 <= n < 30  24 cells   mean |A-B| 3.04   max 13.0
         12 <= n < 20  29 cells   mean |A-B| 3.84   max  9.0
         n < 12        28 cells   mean |A-B| 4.45   max 34.0

     Relaxing to 12 admits seven more cells — tribal_dragons, tribal_elves and
     tribal_warriors on ramp/finisher/tutor — whose halves disagree by 8.5 to 9.0, which is
     the noise band itself. 20 is where the evidence stops supporting a number.

  2. SPLIT-HALF AGREEMENT — both halves of the theme's decks must independently exceed the
     global target. This is what rejects a cell whose full-sample p60 is an artifact of one
     half: `draw_matters` draw reads 23.0 overall but its halves are 27 and 14, and 14 is
     BELOW the population's 16. `chaos` counterspell (6 / 0) and `theft` wipe (0 / 6) go the
     same way. Note it is per (theme, ROLE), not per theme — draw_matters is unstable on
     `draw` and rock-steady on `counterspell` (9 / 9), and a theme-level gate would have to
     throw the good cell away with the bad one.

  3. MIN_MARGIN — the archetype must want at least 3 more supply units than the population,
     so the table records a difference that changes a judgement rather than a rounding step.

Together they admit five cells, and every one is Magic-plausible: spellslinger wants
counterspells and card draw, draw_matters holds up interaction, landfall ramps with lands,
chaos draws.

MEASURED PAYOFF (k=6, the pool size Forge's /advise asks for), over the 106 corpus decks that
carry an overridden archetype: the cut pool changes on 52 of them (49%), and the share of cut
slots drawn from the deck's OWN plan role falls 64.0% -> 33.8%. The residual is not a failure
and should not be driven to zero — a spellslinger deck running 27 counterspells against a
target of 12 IS over-served, and saying so is the module working.

    python scripts/archetype_role_targets.py             # print the table
    python scripts/archetype_role_targets.py --check     # diff against the baked-in constant
    python scripts/archetype_role_targets.py --audit     # every candidate cell and its gate

THE FORGE IMPORT IS DELIBERATE, AND IT IS A SCRIPT-ONLY PRIVILEGE. `deck_themes` lives in
Forge, not the engine, and the engine must not import it — the engine is a separate process
on :8020 and Forge's modules are not on its path. This script may, because what it produces
is a TABLE OF PLAIN STRINGS that the engine bakes as a constant; `redundancy.targets_for`
then takes archetype names as ordinary strings from whoever is calling. That is the whole
contract: the calibration crosses the boundary once, offline; the runtime never does.

Needs data/cards_slim.json (gitignored), so it is not CI-safe.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import deck_themes  # noqa: E402

from mythgauntlet.data.scryfall import load_card_db  # noqa: E402
from mythgauntlet.model.deck import Deck, resolve  # noqa: E402
from mythgauntlet.ratings import redundancy  # noqa: E402

PERCENTILE = 0.60      # the same bar `role_targets.py` sets for the population
MIN_DECKS = 20         # gate 1
MIN_MARGIN = 3         # gate 3, in supply units above the population target


def _percentile(values: list[float], q: float = PERCENTILE) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _theme_view(resolved) -> list[dict]:
    """The engine's cards in the dict shape `theme_match` reads.

    `theme_score` reads `oracle_text`, `type_line` and `card_faces` and nothing else, so this
    is exact for single-faced cards. The engine's `Card` keeps the FRONT face's oracle text
    only, so a modal or transforming card is scored on its front half — 4.1% of corpus card
    slots. An under-count, and in the safe direction: it can only fail to DETECT a theme,
    which leaves the population target in place.
    """
    return [
        {"name": c.name, "type_line": c.type_line, "oracle_text": c.oracle_text}
        for c, _count in resolved.cards
    ]


def survey() -> list[tuple[list[str], dict[str, float]]]:
    """`(themes, role supply)` for every corpus deck big enough to judge."""
    db = load_card_db()
    out = []
    for path in sorted((ROOT / "corpus" / "decks").glob("*.txt")):
        resolved = resolve(Deck.parse_text(path.read_text(encoding="utf-8")), db)
        if resolved.card_count < 90:
            continue
        supply = redundancy.role_supply(resolved)
        out.append((
            deck_themes.detect_deck_themes(_theme_view(resolved)),
            {role: supply.get(role, 0.0) for role in redundancy.ROLE_TARGETS},
        ))
    return out


def measure(rows, *, min_decks: int = MIN_DECKS, min_margin: int = MIN_MARGIN, audit=None):
    """The archetype overrides the evidence supports, as `{theme: {role: target}}`.

    `audit`, when a list is passed, collects one row per candidate cell naming the gate that
    decided it — so a rejection is inspectable rather than merely absent.
    """
    counts: collections.Counter[str] = collections.Counter()
    for themes, _supply in rows:
        counts.update(themes)

    table: dict[str, dict[str, int]] = {}
    for theme, n in sorted(counts.items()):
        sub = [supply for themes, supply in rows if theme in themes]
        halves = (sub[0::2], sub[1::2])
        # A theme carried by one deck has an empty second half and no split-half evidence at
        # all, so no cell of it could clear gate 2 whatever `--min-decks` is lowered to.
        # Skipped here rather than inside the percentile, which would have to invent a value.
        if not all(halves):
            continue
        for role, population in redundancy.ROLE_TARGETS.items():
            full = _percentile([s[role] for s in sub])
            a, b = (_percentile([s[role] for s in half]) for half in halves)
            if audit is not None and max(full, a, b) > population:
                audit.append((theme, n, role, population, full, a, b, _gate(
                    n, full, a, b, population, min_decks, min_margin)))
            if n < min_decks:
                continue
            if not (a > population and b > population):
                continue
            if full < population + min_margin:
                continue
            table.setdefault(theme, {})[role] = round(full)
    return table


def _gate(n, full, a, b, population, min_decks, min_margin) -> str:
    """Which gate decided this cell — the first one it fails, or KEPT."""
    if n < min_decks:
        return "sample"
    if not (a > population and b > population):
        return "split-half"
    if full < population + min_margin:
        return "margin"
    return "KEPT"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--min-decks", type=int, default=MIN_DECKS)
    ap.add_argument("--min-margin", type=int, default=MIN_MARGIN)
    args = ap.parse_args()

    rows = survey()
    audit: list | None = [] if args.audit else None
    table = measure(rows, min_decks=args.min_decks, min_margin=args.min_margin, audit=audit)

    if audit is not None:
        print(f"{len(rows)} decks; every candidate cell and the gate that decided it\n")
        head = f"{'theme':<18}{'n':>4}  {'role':<13}{'pop':>4}{'full':>6}{'A':>6}{'B':>6}   gate"
        print(head)
        for theme, n, role, population, full, a, b, reason in audit:
            print(f"{theme:<18}{n:>4}  {role:<13}{population:>4}"
                  f"{full:>6.1f}{a:>6.1f}{b:>6.1f}   {reason}")
        print()

    if args.check:
        baked = redundancy.ARCHETYPE_ROLE_TARGETS
        drift = False
        for theme in sorted(set(baked) | set(table)):
            was, now = baked.get(theme, {}), table.get(theme, {})
            for role in sorted(set(was) | set(now)):
                if was.get(role) != now.get(role):
                    print(f"DRIFT {theme}.{role}: baked {was.get(role)} measured {now.get(role)}")
                    drift = True
        print("ARCHETYPE_ROLE_TARGETS needs regenerating." if drift
              else "ARCHETYPE_ROLE_TARGETS is current.")
        return 1 if drift else 0

    print("ARCHETYPE_ROLE_TARGETS: dict[str, dict[str, int]] = {")
    for theme, roles in sorted(table.items()):
        body = ", ".join(f'"{r}": {v}' for r, v in sorted(roles.items()))
        print(f'    "{theme}": {{{body}}},')
    print("}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
