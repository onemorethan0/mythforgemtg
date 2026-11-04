"""B9 / S13 experiment: does measuring cut-pool OVERSUPPLY in CARDS instead of STRENGTH change the pool,
and which unit offers cuts from roles the player would agree are over-served?

    PYTHONPATH=src python scripts/cut_unit_experiment.py [--decks 400] [--k 6]

`card_roles` gives each role a fixed strength per card (a wipe or counterspell is 3.0, removal 1.0, a
tutor 2.0, ramp/draw scale), so `supply - target` is in STRENGTH units and one over-served counterspell
(3.0 over) outranks a role that is, in the player's own terms, further over (three extra removal
spells = 3.0 too, or six extra ramp cards). The unit a player means by "I run too many X" is CARDS, and
`role_card_counts` / `card_targets_for` already exist. This compares:

  strength : the shipped scoring (score_card)
  cards    : same formula, but oversupply = (cards in role - card target) instead

Metrics (lower is better unless noted):
  pool_changed      share of decks whose top-k cut pool differs between the two units
  not_over_in_cards share of offered cuts whose scored role is NOT over its CARD target (the cut
                    comes from a role the player would say is fine)
  own_plan          offered cuts that fill a role the deck's own archetype raises (the false
                    positive the archetype tables exist to prevent)

Nothing here changes shipped behaviour. The sim's axis delta cannot rank two cut policies (see
advisor_bench), so this reports the quantities that CAN be measured and leaves the decision.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import archetype_role_targets as art  # noqa: E402
from mythgauntlet.data.scryfall import load_card_db  # noqa: E402
from mythgauntlet.model.deck import Deck, resolve  # noqa: E402
from mythgauntlet.ratings import redundancy as R  # noqa: E402


def _pool(resolved, themes, k, unit):
    targets = R.targets_for(themes)
    card_targets = R.card_targets_for(themes)
    supply = R.role_supply(resolved)
    counts = R.role_card_counts(resolved)
    seen, scored = set(), []
    for card, _n in resolved.cards:
        if card.is_land or card.name in seen:
            continue
        seen.add(card.name)
        roles = R.roles_for(card)
        if not roles:
            continue                                   # protected: sorts last in the real thing
        best = (-1.0, None, 0.0)
        for role in sorted(roles):
            if unit == "strength":
                over = max(0.0, supply.get(role, 0.0) - float(targets.get(role, 0)))
            else:
                over = float(max(0, counts.get(role, 0) - int(card_targets.get(role, 0))))
            if over > best[0]:
                best = (over, role, roles[role])
        over, role, within = best
        within += R._efficiency(card)
        scored.append((over / (1.0 + within), role, card))
    scored.sort(key=lambda t: (-t[0], -R._rank_key(t[2]), t[2].name))
    return [(role, card.name) for _s, role, card in scored[:k]], counts, card_targets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", type=int, default=400)
    ap.add_argument("--k", type=int, default=6)
    args = ap.parse_args()
    db = load_card_db()
    paths = sorted((ROOT / "corpus" / "decks").glob("*.txt"))
    step = max(1, len(paths) // args.decks)
    n = changed = 0
    tot = {"strength": 0, "cards": 0}
    not_over = {"strength": 0, "cards": 0}
    own = {"strength": 0, "cards": 0}
    examples = []
    for p in paths[::step]:
        resolved = resolve(Deck.parse_text(p.read_text(encoding="utf-8")), db)
        if resolved.card_count < 90:
            continue
        themes = art.deck_themes.detect_deck_themes(art._theme_view(resolved))
        plan_roles = {r for t in themes for r in R.ARCHETYPE_ROLE_TARGETS.get(t, {})}
        pools = {}
        for unit in ("strength", "cards"):
            pool, counts, card_targets = _pool(resolved, themes, args.k, unit)
            pools[unit] = pool
            for role, _name in pool:
                tot[unit] += 1
                if counts.get(role, 0) <= int(card_targets.get(role, 0)):
                    not_over[unit] += 1
                if role in plan_roles:
                    own[unit] += 1
        n += 1
        if pools["strength"] != pools["cards"]:
            changed += 1
            if len(examples) < 4:
                examples.append((p.stem, pools["strength"][:3], pools["cards"][:3]))
    print(f"decks measured: {n}   pool changed on {changed} ({100 * changed / n:.1f}%)")
    for unit in ("strength", "cards"):
        t = tot[unit]
        print(f"  {unit:<9} offered cuts {t:5d} | role NOT over its card target {not_over[unit]:4d} "
              f"({100 * not_over[unit] / t:4.1f}%) | fills the deck's own plan role {own[unit]:4d} ({100 * own[unit] / t:4.1f}%)")
    for stem, a, b in examples:
        print(f"\n{stem}\n  strength: {a}\n  cards   : {b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
