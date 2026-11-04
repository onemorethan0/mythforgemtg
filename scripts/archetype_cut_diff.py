"""Before/after of the cut pool when ARCHETYPE_ROLE_TARGETS changes.

`advisor_bench` cannot see this defect class (its own docstring says so: `advise` tests every
add against the whole pool, so the simulation rescues a bad pool). What matters is whether the
cards OFFERED for cutting stop being the deck's own plan. This measures that directly:

    PYTHONPATH=src python scripts/archetype_cut_diff.py --old-tables old.json

`--old-tables` is a JSON {"strength": {...}, "cards": {...}} of the previous baked tables
(`git show HEAD:src/mythgauntlet/ratings/redundancy.py` -> paste the dicts). Without it the
script just reports the pool under the tables now in the tree.

For every corpus deck whose detected archetypes touch a changed cell it reports: pool changed
(old vs new top-k), and the number of offered cuts that fill the archetype's own role (the
false-positive class the table exists to prevent).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import archetype_role_targets as art  # noqa: E402
from mythgauntlet.data.scryfall import load_card_db  # noqa: E402
from mythgauntlet.ratings import redundancy  # noqa: E402
from mythgauntlet.model.deck import Deck, resolve  # noqa: E402

K = 6


def _pool(resolved, themes, strength_table):
    saved = redundancy.ARCHETYPE_ROLE_TARGETS
    redundancy.ARCHETYPE_ROLE_TARGETS = strength_table
    try:
        targets = redundancy.targets_for(themes)
        return [c.name for c in redundancy.rank_redundant(resolved, K, targets=targets)]
    finally:
        redundancy.ARCHETYPE_ROLE_TARGETS = saved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-tables", type=Path, required=True)
    args = ap.parse_args()
    old = json.loads(args.old_tables.read_text(encoding="utf-8"))["strength"]
    new = redundancy.ARCHETYPE_ROLE_TARGETS
    changed_themes = {t for t in set(old) | set(new) if old.get(t) != new.get(t)}

    db = load_card_db()
    n = moved = own_old = own_new = 0
    examples = []
    for path in sorted((ROOT / "corpus" / "decks").glob("*.txt")):
        resolved = resolve(Deck.parse_text(path.read_text(encoding="utf-8")), db)
        if resolved.card_count < 90:
            continue
        themes = art.deck_themes.detect_deck_themes(art._theme_view(resolved))
        touched = changed_themes & set(themes)
        if not touched:
            continue
        n += 1
        a, b = _pool(resolved, themes, old), _pool(resolved, themes, new)
        roles = {r for t in touched for r in (set(new.get(t, {})) | set(old.get(t, {})))}
        by_name = {c.name: c for c, _ in resolved.cards}

        def own(pool):
            hit = 0
            for nm in pool:
                card = by_name.get(nm)
                if card is not None and roles & set(redundancy.roles_for(card)):
                    hit += 1
            return hit

        own_old += own(a)
        own_new += own(b)
        if a != b:
            moved += 1
            if len(examples) < 6:
                examples.append((path.stem, sorted(touched), a, b))
    print(f"decks touching a changed cell: {n}; cut pool changed on {moved}")
    print(f"offered cuts that fill the archetype's own role: old {own_old}  new {own_new}  (of {n * K})")
    for stem, th, a, b in examples:
        print(f"\n{stem} {th}\n  old: {a}\n  new: {b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
