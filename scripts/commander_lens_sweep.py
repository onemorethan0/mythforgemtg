"""Corpus sweep for the commander lens (`semantics/commander_lens.py`).

Prints three sections:

1. No-change check: every deck whose commander matches no lens kind must give the same
   `role_card_counts`, `role_supply` strengths, cut-protected set (`score_card(...).protected`
   per nonland card), `rank_redundant` top-10 order and `deck_card_rows` with the lens as
   without it, and `survives_mode("destroy")` must be False. Exit 1 on any difference, and
   exit 2 when no deck was checked at all (a vacuous pass is refused).
2. Moved decks: each lens-covered deck whose counts, supply strengths or protected set changed
   (each reported separately), then every flagged card (distinct card x lens kind) with its
   reason, for hand review against oracle text.
3. EDHREC coverage (report only): for up to N lens-covered commanders with a CACHED EDHREC
   page, the share of high-synergy cards (lift > 0.3) the lens flags. Never fetches.

    PYTHONPATH=src python scripts/commander_lens_sweep.py [--edhrec 30] [--edhrec-dir DIR]

No sim context is built, so X-cost Treasure credit is 0 throughout (the honest no-context
value); flags and labels do not depend on it. The sim-reading surfaces (Resilience's injected
wipe, analysis with a LensDeckContext) are not swept here; they are covered by tests.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mythgauntlet.data import edhrec  # noqa: E402
from mythgauntlet.data.scryfall import load_card_db  # noqa: E402
from mythgauntlet.mentor.deckview import deck_card_rows  # noqa: E402
from mythgauntlet.model.deck import Deck, resolve  # noqa: E402
from mythgauntlet.ratings.redundancy import (  # noqa: E402
    rank_redundant, role_card_counts, role_supply, score_card,
)
from mythgauntlet.semantics.commander_lens import build_lens  # noqa: E402

LIFT_BAR = 0.3
METRICS = ("counts", "supply", "protected", "ranked")


def _kind_of(facts) -> str:
    if facts.payoff_kind:
        return facts.payoff_kind
    return "one_sided_wipe" if facts.wipe_one_sided else "?"


def _cache_dirs(extra: list[str]) -> list[Path]:
    dirs = [Path(d) for d in extra]
    dirs.append(edhrec.data_dir() / "edhrec")
    dirs.append(REPO / "cache" / "edhrec")
    return [d for d in dirs if d.is_dir()]


def _cached_page(name: str, dirs: list[Path]) -> dict | None:
    slug = edhrec.commander_slug(name)
    for d in dirs:
        p = d / f"{slug}.json"
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
    return None


def _measure(resolved, lens) -> dict:
    """Every lens-read deck metric the sweep compares, with (lens) or without (None) the lens."""
    supply = role_supply(resolved, lens)
    protected = {card.name for card, _q in resolved.cards
                 if not card.is_land and score_card(card, supply, lens=lens).protected}
    ranked = [c.name for c in rank_redundant(resolved, 10, lens=lens)]
    return {"counts": role_card_counts(resolved, lens), "supply": supply,
            "protected": protected, "ranked": ranked}


def _delta(before: dict, after: dict, default):
    return {r: (round(after.get(r, default) - before.get(r, default), 2))
            for r in sorted(set(before) | set(after))
            if after.get(r, default) != before.get(r, default)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--edhrec", type=int, default=30, help="max commanders for coverage")
    ap.add_argument("--edhrec-dir", action="append", default=[],
                    help="extra directory of cached EDHREC commander pages (read only)")
    args = ap.parse_args()

    db = load_card_db()
    paths = sorted((REPO / "corpus" / "decks").glob("*.txt"))
    unresolved = no_commander = nochange_checked = covered = 0
    nochange_diffs: list[str] = []
    moved: list[tuple[str, str, list[str], dict, dict]] = []
    flagged: dict[tuple[str, str], dict] = {}
    covered_commanders: dict[str, tuple] = {}

    for path in paths:
        resolved = resolve(Deck.parse_text(path.read_text(encoding="utf-8"), name=path.stem), db)
        if not resolved.cards:
            unresolved += 1
            continue
        if not resolved.commanders:
            no_commander += 1
            continue
        lens = build_lens(resolved.commanders)
        base, with_lens = _measure(resolved, None), _measure(resolved, lens)
        if not lens.kinds:
            nochange_checked += 1
            diffs = [k for k in METRICS if base[k] != with_lens[k]]
            if lens.survives_mode("destroy"):
                diffs.append("survives_mode(destroy)")
            if deck_card_rows(resolved) != deck_card_rows(resolved, lens):
                diffs.append("deck_card_rows")
            if diffs:
                nochange_diffs.append(f"{path.stem}: {', '.join(diffs)} differ")
            continue
        covered += 1
        cmd_names = " + ".join(c.name for c in resolved.commanders)
        covered_commanders.setdefault(cmd_names, (resolved.commanders, lens))
        changed = [k for k in ("counts", "supply", "protected") if base[k] != with_lens[k]]
        if changed:
            moved.append((path.stem, cmd_names, changed, base, with_lens))
        for card, _qty in resolved.cards:
            if card.is_land:
                continue
            facts = lens.facts_for(card)
            if facts.empty:
                continue
            key = (card.name, _kind_of(facts))
            entry = flagged.setdefault(key, {
                "reason": facts.reason, "treasure": facts.payoff_treasure,
                "commanders": set(), "decks": 0,
            })
            entry["commanders"].add(cmd_names)
            entry["decks"] += 1

    print("== 1. No-change check ==")
    print(f"{len(paths)} corpus decks: {unresolved} unresolved (no cards), {no_commander} "
          f"without a resolved commander, {covered} lens-covered; {nochange_checked} with no "
          f"lens kind checked over {', '.join(METRICS)}, deck_card_rows and "
          f"survives_mode; {len(nochange_diffs)} differ")
    for line in nochange_diffs:
        print("  DIFF", line)

    by_kind = {k: sum(1 for m in moved if k in m[2]) for k in ("counts", "supply", "protected")}
    only = {k: sum(1 for m in moved if m[2] == [k]) for k in ("counts", "supply", "protected")}
    print(f"\n== 2. Moved decks ({len(moved)} of {covered} lens-covered decks; counts "
          f"{by_kind['counts']}, supply {by_kind['supply']}, protected {by_kind['protected']}; "
          f"supply-only {only['supply']}, protection-only {only['protected']}) ==")
    for stem, cmds, changed, before, after in moved:
        newly = sorted(after["protected"] - before["protected"])
        print(f"  {stem} [{cmds}] changed={changed} counts{_delta(before['counts'], after['counts'], 0)}"
              f" supply{_delta(before['supply'], after['supply'], 0.0)} newly_protected={newly}")
    print(f"\nLens-covered commanders ({len(covered_commanders)}):")
    for name, (_cmds, lens) in sorted(covered_commanders.items()):
        print(f"  {name}: {', '.join(lens.kinds)}")
    print(f"\nFlagged cards: {len(flagged)} distinct (card, kind) pairs, "
          f"{sum(e['decks'] for e in flagged.values())} deck-card instances")
    for (name, kind), e in sorted(flagged.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        print(f"  [{kind}] {name} x{e['decks']} t={e['treasure']} :: {e['reason']}"
              f"  <{'; '.join(sorted(e['commanders']))}>")

    print(f"\n== 3. EDHREC coverage (lift > {LIFT_BAR}, cached pages only) ==")
    dirs = _cache_dirs(args.edhrec_dir)
    tot_hi = tot_flag = n = 0
    for name, (cmds, lens) in sorted(covered_commanders.items()):
        if n >= args.edhrec:
            break
        if len(cmds) > 1:
            # A single commander's page is not the pair's population.
            print(f"  {name}: partner pair, skipped")
            continue
        page = _cached_page(cmds[0].name, dirs)
        if page is None:
            print(f"  {name}: no cached page")
            continue
        n += 1
        lifts = edhrec.lift_map(edhrec.parse_commander_page(page))
        hi: list[str] = []
        hits: list[str] = []
        for key in (k for k, v in lifts.items() if v > LIFT_BAR):
            card = db.get(key)   # CardDb aliases front faces, the lift key's shape
            if card is None or card.is_land:
                continue
            hi.append(key)
            if not lens.facts_for(card).empty:
                hits.append(card.name)
        tot_hi += len(hi)
        tot_flag += len(hits)
        share = (len(hits) / len(hi)) if hi else 0.0
        print(f"  {name}: {len(hits)}/{len(hi)} high-synergy nonland cards flagged "
              f"({share:.0%}) {sorted(hits)}")
    if tot_hi:
        print(f"  TOTAL over {n} commanders: {tot_flag}/{tot_hi} ({tot_flag / tot_hi:.1%})")
    else:
        print(f"  TOTAL: no cached pages found for lens-covered commanders in {dirs}")

    if nochange_checked == 0:
        print("NO deck reached the no-change check: vacuous pass refused")
        return 2
    return 1 if nochange_diffs else 0


if __name__ == "__main__":
    sys.exit(main())
