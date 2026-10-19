"""Corpus sweep for the commander lens (`semantics/commander_lens.py`).

Prints three sections:

1. No-change check: every deck whose commander matches no lens kind must give the same
   `role_card_counts` and `deck_card_rows` with the lens as without it. Exit 1 on any
   difference (the spec's byte-identical guarantee).
2. Moved decks: each lens-covered deck whose role card counts changed, then every flagged
   card (distinct card x lens kind) with its reason, for hand review against oracle text.
3. EDHREC coverage (report only): for up to N lens-covered commanders with a CACHED EDHREC
   page, the share of high-synergy cards (lift > 0.3) the lens flags. Never fetches.

    PYTHONPATH=src python scripts/commander_lens_sweep.py [--edhrec 30] [--edhrec-dir DIR]

No sim context is built, so X-cost Treasure credit is 0 throughout (the honest no-context
value); flags and labels do not depend on it.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mythgauntlet.data import edhrec  # noqa: E402
from mythgauntlet.data.scryfall import load_card_db  # noqa: E402
from mythgauntlet.mentor.deckview import deck_card_rows  # noqa: E402
from mythgauntlet.model.deck import Deck, resolve  # noqa: E402
from mythgauntlet.ratings.redundancy import role_card_counts  # noqa: E402
from mythgauntlet.semantics.commander_lens import build_lens  # noqa: E402

LIFT_BAR = 0.3


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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--edhrec", type=int, default=30, help="max commanders for coverage")
    ap.add_argument("--edhrec-dir", action="append", default=[],
                    help="extra directory of cached EDHREC commander pages (read only)")
    args = ap.parse_args()

    db = load_card_db()
    paths = sorted((REPO / "corpus" / "decks").glob("*.txt"))
    nochange_checked = 0
    nochange_diffs: list[str] = []
    covered = 0
    moved: list[tuple[str, str, dict, dict]] = []
    flagged: dict[tuple[str, str], dict] = {}
    covered_commanders: dict[str, object] = {}

    for path in paths:
        resolved = resolve(Deck.parse_text(path.read_text(encoding="utf-8"), name=path.stem), db)
        if not resolved.cards or not resolved.commanders:
            continue
        lens = build_lens(resolved.commanders)
        base_counts = role_card_counts(resolved)
        lens_counts = role_card_counts(resolved, lens)
        if not lens.kinds:
            nochange_checked += 1
            if base_counts != lens_counts:
                nochange_diffs.append(f"{path.stem}: counts {base_counts} != {lens_counts}")
            elif deck_card_rows(resolved) != deck_card_rows(resolved, lens):
                nochange_diffs.append(f"{path.stem}: deck_card_rows differ")
            continue
        covered += 1
        cmd_names = " + ".join(c.name for c in resolved.commanders)
        covered_commanders.setdefault(cmd_names, (resolved.commanders, lens))
        if base_counts != lens_counts:
            moved.append((path.stem, cmd_names, base_counts, lens_counts))
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
    print(f"{nochange_checked} decks with no lens kind checked; {len(nochange_diffs)} differ")
    for line in nochange_diffs:
        print("  DIFF", line)

    print(f"\n== 2. Moved decks ({len(moved)} of {covered} lens-covered decks) ==")
    for stem, cmds, before, after in moved:
        delta = {r: after.get(r, 0) - before.get(r, 0)
                 for r in sorted(set(before) | set(after))
                 if after.get(r, 0) != before.get(r, 0)}
        print(f"  {stem} [{cmds}] {delta}")
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
        hi = []
        hi_names = [k for k, v in lifts.items() if v > LIFT_BAR]
        hits = []
        for key in hi_names:
            card = _lookup(db, key)
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

    return 1 if nochange_diffs else 0


def _lookup(db, key: str):
    """Card by the EDHREC lift key (front face, casefolded); CardDb aliases front faces."""
    return db.get(key)


if __name__ == "__main__":
    sys.exit(main())
